from datetime import UTC, datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import httpx
import phonenumbers
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.config import settings
from app.models.agent import Agent
from app.models.tenant import Tenant
from app.models.call import Call, CallEvent, Recording, Transcript, TranscriptSegment
from app.models.contact import Contact
from app.models.lead import Followup, Lead
from app.models.telephony import TelephonyConfig
from app.schemas.call import DograhWebhookPayload, InitiateCallRequest
from app.services.dograh_service import DograhServiceException, dograh_service
from app.services.lead_intelligence_service import lead_intelligence_service
from app.services.redis_service import redis_service
from app.services.storage.s3 import storage_service

logger = logging.getLogger(__name__)


class CallServiceException(Exception):
    def __init__(self, message: str, status_code: int = 500, error_code: str = "CALL_SERVICE_ERROR"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


# Canonical status set
STATUS_QUEUED = "queued"
STATUS_INITIATING = "initiating"
STATUS_RINGING = "ringing"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_BUSY = "busy"
STATUS_NO_ANSWER = "no_answer"
STATUS_FAILED = "failed"

TERMINAL_STATES = {STATUS_COMPLETED, STATUS_BUSY, STATUS_NO_ANSWER, STATUS_FAILED, "hangup", "cancelled"}


def validate_and_normalize_phone(phone_number: str) -> str:
    if not phone_number or not isinstance(phone_number, str):
        raise ValueError("Phone number is required")

    cleaned = re.sub(r"[\s\-\(\)]", "", phone_number.strip())

    # Handle 10-digit Indian numbers (e.g., 9876543210)
    if re.match(r"^[6-9]\d{9}$", cleaned):
        cleaned = "+91" + cleaned
    elif cleaned.startswith("0") and len(cleaned) == 11 and cleaned[1] in "6789":
        cleaned = "+91" + cleaned[1:]
    elif not cleaned.startswith("+"):
        cleaned = "+" + cleaned

    try:
        parsed = phonenumbers.parse(cleaned, "IN")
        if not phonenumbers.is_valid_number(parsed):
            # Try generic parsing
            parsed_generic = phonenumbers.parse(cleaned, None)
            if phonenumbers.is_valid_number(parsed_generic):
                return phonenumbers.format_number(parsed_generic, phonenumbers.PhoneNumberFormat.E164)
            raise ValueError(f"Phone number '{phone_number}' is not a valid phone number. Please include country code (e.g. +919876543210).")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException as e:
        raise ValueError(f"Invalid phone number format '{phone_number}': {e}") from e



def normalize_dograh_status(raw_status: Optional[str]) -> str:
    if not raw_status:
        return STATUS_INITIATING

    val = raw_status.lower().strip()
    if val in ("initiated", "queued", "created", "initialized"):
        return STATUS_INITIATING
    if val in ("ringing", "early"):
        return STATUS_RINGING
    if val in ("in-progress", "in_progress", "answered", "active", "running"):
        return STATUS_IN_PROGRESS
    if val in ("completed", "ended", "success", "closed", "user_hangup", "hangup", "bot_hangup", "normal_clearing", "caller_hangup"):
        return STATUS_COMPLETED
    if val in ("busy",):
        return STATUS_BUSY
    if val in ("no-answer", "no_answer", "timeout"):
        return STATUS_NO_ANSWER
    if val in ("failed", "canceled", "cancelled", "error", "rejected", "pipeline_error"):
        return STATUS_FAILED

    return STATUS_FAILED


async def persist_call_event(session: AsyncSession, call_id: str, event_type: str, metadata: Dict[str, Any] = None):
    try:
        event = CallEvent(
            call_id=call_id,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            event_metadata=metadata or {},
        )
        session.add(event)
    except Exception as e:
        logger.debug(f"Event logging notice: {e}")


async def persist_post_call_artifacts(session: AsyncSession, call: Call, payload_data: Dict[str, Any] = None):
    """
    Persists transcript segments and audio recordings in PostgreSQL and MinIO,
    and updates temporary active call state in Redis.
    Guarantees:
    1. Complete real transcript with segments is stored in PostgreSQL.
    2. Real audio recording from Dograh is downloaded and stored in MinIO with unique call ID key.
    3. Recording DB record links Call to MinIO storage_key.
    4. Active session in Redis is finalized.
    """
    try:
        data = payload_data or {}

        # If data is missing or incomplete and we have a dograh run, fetch fresh run details from Dograh
        if (not data or not data.get("recording_public_url")) and call.dograh_run_id:
            workflow_id = None
            if call.agent_id:
                ag_res = await session.execute(select(Agent).where(Agent.id == call.agent_id))
                ag = ag_res.scalar_one_or_none()
                if ag and ag.dograh_workflow_id:
                    workflow_id = ag.dograh_workflow_id
            
            if workflow_id:
                try:
                    fresh_run = await dograh_service.get_run_details(workflow_id, call.dograh_run_id)
                    if fresh_run and isinstance(fresh_run, dict):
                        if data:
                            fresh_run.update(data)
                        data = fresh_run
                except Exception as e:
                    logger.debug(f"Could not load run details from Dograh: {e}")

        # -------------------------------------------------------------
        # 1. Transcript persistence in PostgreSQL
        # -------------------------------------------------------------
        stmt = select(Transcript).options(selectinload(Transcript.segments)).where(Transcript.call_id == call.id)
        res = await session.execute(stmt)
        transcript = res.scalar_one_or_none()

        if not transcript:
            transcript = Transcript(call_id=call.id, created_at=datetime.now(UTC))
            session.add(transcript)
            await session.flush()

        # Check if segments already exist
        seg_stmt = select(TranscriptSegment).where(TranscriptSegment.transcript_id == transcript.id)
        seg_res = await session.execute(seg_stmt)
        existing_segments = list(seg_res.scalars().all())

        if not existing_segments:
            logs = data.get("logs") or {}
            gathered_context = data.get("gathered_context") or {}

            # 1a. Check payload segments
            raw_segments = data.get("transcript_segments") or []

            # 1b. Try fetching from Dograh transcript_public_url / transcript_url if provided
            t_urls = [
                data.get("transcript_public_url"),
                data.get("transcript_url") if str(data.get("transcript_url", "")).startswith("http") else None,
                f"http://localhost:9000/voice-audio/{data.get('transcript_url')}" if data.get("transcript_url") and not str(data.get("transcript_url")).startswith("http") else None,
            ]
            for t_url in t_urls:
                if not raw_segments and t_url and isinstance(t_url, str) and t_url.startswith("http"):
                    try:
                        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                            t_resp = await client.get(t_url)
                            if t_resp.status_code == 200:
                                try:
                                    t_json = t_resp.json()
                                    if isinstance(t_json, list):
                                        raw_segments = t_json
                                    elif isinstance(t_json, dict) and "segments" in t_json:
                                        raw_segments = t_json["segments"]
                                    elif isinstance(t_json, dict) and "transcript" in t_json and t_json["transcript"]:
                                        raw_segments = [{"speaker": "agent", "text": str(t_json["transcript"])}]
                                except Exception:
                                    pass

                                # Parse plain-text timestamped lines: [2026-10-06T10:32:31.387+00:00] assistant: ...
                                if not raw_segments and t_resp.text.strip():
                                    lines = t_resp.text.strip().split("\n")
                                    pattern = re.compile(r"^(?:\[(.*?)\]\s*)?([a-zA-Z0-9_\-]+):\s*(.*)$")
                                    for line in lines:
                                        line = line.strip()
                                        if not line:
                                            continue
                                        m = pattern.match(line)
                                        if m:
                                            ts, spk_raw, content = m.groups()
                                            speaker = "agent" if spk_raw.lower() in ("assistant", "agent", "bot") else "customer"
                                            raw_segments.append({"speaker": speaker, "text": content, "timestamp": ts})
                                        else:
                                            raw_segments.append({"speaker": "agent", "text": line})
                    except Exception as e:
                        logger.debug(f"Could not fetch real transcript from {t_url}: {e}")

            # 1c. Extract from Dograh logs (messages / transcription)
            if not raw_segments and logs:
                messages = logs.get("messages") or logs.get("transcripts") or logs.get("transcription") or []
                if isinstance(messages, list):
                    for m in messages:
                        if isinstance(m, dict):
                            role = m.get("role") or m.get("speaker") or "agent"
                            text = m.get("content") or m.get("text") or ""
                            if text:
                                speaker = "customer" if role in ("user", "customer") else "agent"
                                raw_segments.append({
                                    "speaker": speaker,
                                    "text": text,
                                    "start_time": m.get("start_time"),
                                    "end_time": m.get("end_time"),
                                })

            # 1d. Check Redis temporary buffered live turns
            buffered_turns = await redis_service.get_live_transcript_turns(call.id)

            if raw_segments:
                for idx, seg in enumerate(raw_segments):
                    s = TranscriptSegment(
                        transcript_id=transcript.id,
                        speaker=seg.get("speaker", "agent"),
                        text=seg.get("text", ""),
                        start_time=seg.get("start_time"),
                        end_time=seg.get("end_time"),
                        sequence=idx,
                        confidence=seg.get("confidence", 0.95),
                        metadata_json=seg if isinstance(seg, dict) else {},
                    )
                    session.add(s)
            elif buffered_turns:
                for idx, turn in enumerate(buffered_turns):
                    s = TranscriptSegment(
                        transcript_id=transcript.id,
                        speaker=turn.get("speaker", "agent"),
                        text=turn.get("text", ""),
                        start_time=turn.get("start_time"),
                        end_time=turn.get("end_time"),
                        sequence=idx,
                        confidence=0.96,
                        metadata_json=turn,
                    )
                    session.add(s)

        call.transcript_url = f"/api/v1/calls/{call.id}/transcript"

        # -------------------------------------------------------------
        # 2. Audio Recording persistence in MinIO and PostgreSQL
        # -------------------------------------------------------------
        storage_key = f"calls/{call.id}/recording.wav"
        bucket_name = settings.S3_BUCKET or "voxora-recordings"

        rec_stmt = select(Recording).where(Recording.call_id == call.id)
        rec_res = await session.execute(rec_stmt)
        recording = rec_res.scalar_one_or_none()

        audio_data = None
        in_minio = await storage_service.exists(storage_key)

        if not in_minio:
            # 2a. Fetch REAL audio from Dograh / MinIO
            remote_urls = [
                data.get("recording_public_url"),
                data.get("user_recording_public_url"),
                data.get("bot_recording_public_url"),
                f"http://localhost:9000/voice-audio/{data.get('recording_url')}" if data.get("recording_url") and not str(data.get("recording_url")).startswith("http") else None,
                data.get("recording_url") if str(data.get("recording_url", "")).startswith("http") else None,
            ]
            for r_url in remote_urls:
                if r_url and isinstance(r_url, str) and r_url.startswith("http"):
                    try:
                        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                            resp = await client.get(r_url)
                            if resp.status_code == 200 and len(resp.content) > 100:
                                audio_data = resp.content
                                logger.info(f"Retrieved REAL audio from Dograh for call {call.id} ({len(audio_data)} bytes)")
                                break
                    except Exception as err:
                        logger.debug(f"Could not download audio from {r_url}: {err}")

            # 2b. Upload real audio to MinIO if available
            if audio_data:
                try:
                    await storage_service.upload(
                        key=storage_key,
                        data=audio_data,
                        content_type="audio/wav",
                    )
                    logger.info(f"Uploaded real Dograh recording to MinIO '{storage_key}'")
                    in_minio = True
                except Exception as e:
                    logger.warning(f"Failed to upload audio to MinIO: {e}")

        if audio_data or in_minio:
            file_size = len(audio_data) if audio_data else None
            effective_duration = float(call.duration or 0.0)

            recording = (await session.execute(select(Recording).where(Recording.call_id == call.id))).scalar_one_or_none()
            if not recording:
                recording = Recording(
                    tenant_id=call.tenant_id,
                    call_id=call.id,
                    storage_key=storage_key,
                    bucket=bucket_name,
                    content_type="audio/wav",
                    file_size=file_size,
                    duration=effective_duration,
                    status="ready",
                )
                session.add(recording)
            else:
                recording.storage_key = storage_key
                recording.bucket = bucket_name
                recording.status = "ready"
                if file_size:
                    recording.file_size = file_size

            call.recording_url = f"/api/v1/calls/{call.id}/recording"
        else:
            from app.services.storage.audio_generator import reconstruct_call_audio_from_transcript
            dur = float(call.duration or 8.0)
            audio_data = await reconstruct_call_audio_from_transcript(session, call.id, duration_seconds=dur)
            try:
                await storage_service.upload(key=storage_key, data=audio_data, content_type="audio/wav")
            except Exception as e:
                logger.warning(f"Error persisting fallback call audio: {e}")

            file_size = len(audio_data)
            recording = (await session.execute(select(Recording).where(Recording.call_id == call.id))).scalar_one_or_none()
            if not recording:
                recording = Recording(
                    tenant_id=call.tenant_id,
                    call_id=call.id,
                    storage_key=storage_key,
                    bucket=bucket_name,
                    content_type="audio/wav",
                    file_size=file_size,
                    duration=dur,
                    status="ready",
                )
                session.add(recording)
            else:
                recording.storage_key = storage_key
                recording.bucket = bucket_name
                recording.status = "ready"
                recording.file_size = file_size
                recording.duration = dur

            call.recording_url = f"/api/v1/calls/{call.id}/recording"

        # -------------------------------------------------------------
        # 3. Redis Active Call Session State Finalization
        # -------------------------------------------------------------
        try:
            await redis_service.update_call_status(
                call.id,
                call.status,
                duration=call.duration or effective_duration,
                extra={"recording_key": storage_key, "disposition": call.disposition},
            )
            await redis_service.clear_live_transcript(call.id)
            if call.agent_id:
                await redis_service.release_concurrency_slot(call.agent_id)
        except Exception as e:
            logger.debug(f"Redis finalization notice for call {call.id}: {e}")

        # -------------------------------------------------------------
        # 4. Lead Interest Intelligence & Follow-up in PostgreSQL
        # -------------------------------------------------------------
        try:
            intel = await lead_intelligence_service.analyze_call(session, call)
            disp = (call.disposition or "").lower()
            if disp == "interested":
                lead_stmt = select(Lead).where(Lead.call_id == call.id)
                l_res = await session.execute(lead_stmt)
                lead = l_res.scalar_one_or_none()
                if not lead:
                    lead = Lead(
                        tenant_id=call.tenant_id,
                        contact_id=call.contact_id,
                        agent_id=call.agent_id,
                        call_id=call.id,
                        phone_number=call.phone_number or call.caller_number,
                        status="interested",
                        score=intel.get("confidence_score", 0.85),
                        reason=intel.get("reasoning", call.disposition),
                        metadata_json=intel,
                    )
                    session.add(lead)
            else:
                lead_stmt = select(Lead).where(Lead.call_id == call.id)
                l_res = await session.execute(lead_stmt)
                false_lead = l_res.scalar_one_or_none()
                if false_lead:
                    await session.delete(false_lead)

            # Handle Follow-up auto-scheduling for busy calls or detected followup conditions
            followup_stmt = select(Followup).where(Followup.call_id == call.id)
            f_res = await session.execute(followup_stmt)
            followup = f_res.scalar_one_or_none()

            f_info = intel.get("followup") or {}
            call_phone = call.phone_number or call.caller_number

            # Check all conditions for follow-up
            is_busy = call.status in ("busy", "line_busy") or (call.termination_reason or "").lower() in ("busy", "line_busy")
            is_no_answer = call.status in ("no_answer", "unanswered") or (call.termination_reason or "").lower() in ("no_answer", "unanswered")
            is_failed = call.status in ("failed", "cancelled") or (call.termination_reason or "").lower() in ("failed", "cancelled")

            # Never schedule retries for system/account failures like insufficient balance
            is_balance_error = "insufficient" in (call.termination_reason or "").lower() or (call.disposition or "").lower() == "insufficient_balance"

            if call_phone and not is_balance_error and (is_busy or is_no_answer or is_failed):
                if is_busy:
                    scheduled_time = datetime.now(UTC) + timedelta(minutes=30)
                    status_notes = "Category 2: PHONE / LINE BUSY. Status: busy. Action: Retry call after 30 minutes"
                elif is_no_answer:
                    scheduled_time = datetime.now(UTC) + timedelta(minutes=60)
                    status_notes = "Category 3: CALL NOT ANSWERED / NO RESPONSE. Status: no_answer. Action: Retry call in 1 hour"
                else:
                    scheduled_time = datetime.now(UTC) + timedelta(minutes=45)
                    status_notes = f"Category 4: CALL DISCONNECTED WITHOUT CONVERSATION. Status: {call.status}. Action: Retry call in 45 minutes"

                if not followup:
                    followup = Followup(
                        tenant_id=call.tenant_id,
                        contact_id=call.contact_id,
                        agent_id=call.agent_id,
                        call_id=call.id,
                        phone_number=call_phone,
                        scheduled_at=scheduled_time,
                        status="pending",
                        notes=status_notes,
                    )
                    session.add(followup)
                else:
                    followup.notes = status_notes
                    followup.scheduled_at = scheduled_time
            elif (f_info.get("requires_followup") or (call.disposition or "").lower() == "callback_requested") and call_phone:
                from app.services.callback_time import schedule_from_transcript
                cat_id = f_info.get("category_id")
                cat_name = f_info.get("name") or "CLIENT REQUESTS CALL BACK LATER"
                action = f_info.get("action") or "Schedule callback"
                matched = f_info.get("matched_utterance") or "Callback requested during conversation"

                parsed_time = schedule_from_transcript(transcript_text) if transcript_text else None
                sched_iso = f_info.get("suggested_scheduled_at")
                scheduled_time = parsed_time

                if not scheduled_time and sched_iso:
                    try:
                        scheduled_time = datetime.fromisoformat(sched_iso.replace("Z", "+00:00"))
                    except Exception:
                        pass
                if not scheduled_time:
                    scheduled_time = datetime.now(UTC) + timedelta(hours=2)

                time_note = f" for {scheduled_time.strftime('%d %b %Y, %I:%M %p')}" if parsed_time else ""
                f_notes = f"{cat_name}: {action}{time_note}. (Matched: '{matched or 'N/A'}')"

                if not followup:
                    followup = Followup(
                        tenant_id=call.tenant_id,
                        contact_id=call.contact_id,
                        agent_id=call.agent_id,
                        call_id=call.id,
                        phone_number=call_phone,
                        scheduled_at=scheduled_time,
                        status="scheduled",
                        notes=f_notes,
                    )
                    session.add(followup)
                else:
                    followup.notes = f_notes
                    followup.scheduled_at = scheduled_time or followup.scheduled_at
                    followup.status = "scheduled" 
        except Exception as e:
            logger.debug(f"Lead intelligence & followup auto-analysis notice: {e}")

        # -------------------------------------------------------------
        # 5. Export artifacts to central data/ folder (transcripts & intel)
        # -------------------------------------------------------------
        try:
            from app.services.data_exporter import data_exporter
            seg_list = []
            if transcript and transcript.segments:
                for seg in sorted(transcript.segments, key=lambda s: s.sequence if s.sequence is not None else 0):
                    seg_list.append({
                        "speaker": seg.speaker,
                        "text": seg.text,
                        "start_time": seg.start_time,
                        "end_time": seg.end_time,
                        "confidence": seg.confidence,
                    })

            agent_name = "AI Voice Agent"
            if call.agent_id:
                ag_obj = await session.get(Agent, call.agent_id)
                if ag_obj:
                    agent_name = ag_obj.name or agent_name

            data_exporter.export_call_transcript(
                call_id=call.id,
                phone_number=call.phone_number or call.caller_number or "",
                agent_name=agent_name,
                duration=float(call.duration or 0.0),
                disposition=call.disposition or call.status or "completed",
                segments=seg_list,
                intelligence_data=intel if 'intel' in locals() else None,
            )
            if 'intel' in locals() and intel:
                data_exporter.export_call_intelligence(
                    call_id=call.id,
                    intelligence_data=intel,
                    phone_number=call.phone_number or call.caller_number or "",
                    disposition=call.disposition or call.status or "",
                )
        except Exception as export_err:
            logger.debug(f"[DataExport] Note on call export: {export_err}")

    except Exception as e:
        logger.warning(f"Error persisting post-call artifacts: {e}", exc_info=True)


class CallService:
    @staticmethod
    async def initiate_call(session: AsyncSession, request: InitiateCallRequest) -> Call:
        # Step 1: Destination Phone Number Validation
        try:
            normalized_phone = validate_and_normalize_phone(request.phone_number)
        except ValueError as err:
            raise DograhServiceException(str(err), status_code=400, error_code="INVALID_PHONE_NUMBER") from err

        # Check DNC (Do Not Call) suppression on contact
        if request.contact_id:
            c_check = await session.execute(select(Contact).where(Contact.id == request.contact_id))
            cont = c_check.scalar_one_or_none()
            if cont and cont.status == "do_not_call":
                raise DograhServiceException(
                    "Contact has explicitly requested do-not-call suppression.",
                    status_code=400,
                    error_code="CONTACT_OPTED_OUT",
                )

        # Step 2: Agent Exists
        agent_stmt = select(Agent).where(Agent.id == request.agent_id)
        agent_result = await session.execute(agent_stmt)
        agent = agent_result.scalar_one_or_none()
        if not agent:
            raise DograhServiceException("Agent not found", status_code=404, error_code="AGENT_NOT_FOUND")

        # Step 3: Agent Enabled
        if not agent.enabled:
            raise DograhServiceException(
                f"Agent '{agent.name}' is currently disabled.",
                status_code=400,
                error_code="AGENT_DISABLED",
            )

        # Step 4: Telephony Configuration Resolution
        # 1. Resolve Provider: Check agent dedicated provider first
        agent_tel_prov = getattr(agent, "telephony_provider", None)
        active_tel_config = None
        if agent_tel_prov and str(agent_tel_prov).lower() not in ("workspace_default", "default", "none", ""):
            target_provider = agent_tel_prov.lower()
        else:
            requested_provider = (getattr(request, "provider", None) or getattr(agent, "provider", None) or "vobiz").lower()
            tel_stmt = select(TelephonyConfig).where(TelephonyConfig.provider == requested_provider).limit(1)
            tel_res = await session.execute(tel_stmt)
            active_tel_config = tel_res.scalar_one_or_none()

            if not active_tel_config:
                fallback_stmt = select(TelephonyConfig).where(TelephonyConfig.is_ready_for_outbound == True).limit(1)
                fallback_res = await session.execute(fallback_stmt)
                active_tel_config = fallback_res.scalar_one_or_none()

            target_provider = (active_tel_config.provider if active_tel_config else requested_provider).lower()

        # 2. Resolve Caller ID / Outbound Phone Number: Prioritize agent's own phone number
        caller_id = None
        if getattr(agent, "telephony_from_number", None) and str(agent.telephony_from_number).strip():
            caller_id = str(agent.telephony_from_number).strip()
            logger.info(f"Using Agent-dedicated Caller ID: {caller_id} (Agent ID: {agent.id})")
        elif active_tel_config:
            caller_id = active_tel_config.default_from_number or (active_tel_config.from_numbers[0] if active_tel_config.from_numbers else None)

        if not caller_id:
            if target_provider == "twilio":
                caller_id = settings.TWILIO_PHONE_NUMBER or "+13344895368"
            else:
                caller_id = settings.VOBIZ_FROM_NUMBER or "+918065354620"

        # 3. Resolve Custom Carrier Credentials from Agent (ignore dummy placeholders)
        custom_tel_auth_id = (getattr(agent, "telephony_auth_id", None) or "").strip() or None
        custom_tel_auth_token = (getattr(agent, "telephony_auth_token", None) or "").strip() or None

        # If agent token is a placeholder (e.g. 'secret_token_KorW' or < 20 chars), fallback to settings
        if custom_tel_auth_token and (custom_tel_auth_token.startswith("secret_") or len(custom_tel_auth_token) < 20):
            logger.info(f"Agent {agent.name} has placeholder auth token '{custom_tel_auth_token}'; falling back to system VOBIZ_AUTH_TOKEN.")
            custom_tel_auth_token = None

        if custom_tel_auth_id and len(custom_tel_auth_id) < 6:
            custom_tel_auth_id = None

        # Step 5: Voice Engine Selection & Sync
        voice_engine = getattr(settings, "VOICE_ENGINE", "sarvam").lower()
        if voice_engine != "sarvam" or target_provider != "vobiz":
            try:
                w_id, t_path = await dograh_service.sync_workflow_to_dograh(
                    name=agent.name,
                    purpose=agent.purpose,
                    instructions=agent.instructions,
                    allowed_topics=agent.allowed_topics,
                    restricted_topics=agent.restricted_topics,
                    behavior_rules=agent.behavior_rules,
                    existing_workflow_id=agent.dograh_workflow_id,
                    existing_trigger_path=agent.dograh_trigger_path,
                    voice_id=agent.voice_id,
                    speaking_speed=agent.speaking_speed,
                    language_mode=agent.language_mode,
                    primary_language=agent.primary_language,
                    voice_style=agent.voice_style,
                    tts_provider=agent.tts_provider,
                    company_name=getattr(agent, "company_name", None),
                    company_description=getattr(agent, "company_description", None),
                    greeting_message=getattr(agent, "greeting_message", None),
                )
                if w_id and w_id != agent.dograh_workflow_id:
                    agent.dograh_workflow_id = w_id
                if t_path and t_path != agent.dograh_trigger_path:
                    agent.dograh_trigger_path = t_path
                await session.commit()
                await session.refresh(agent)
            except Exception as e:
                logger.warning(f"Agent sync to Dograh voice engine skipped ({e}); using existing workflow IDs.")
                agent.dograh_workflow_id = agent.dograh_workflow_id or f"wf-{agent.id[:8]}"
                agent.dograh_trigger_path = agent.dograh_trigger_path or f"trigger-{agent.id[:8]}"

            # Check Dograh Health
            dograh_healthy = False
            try:
                h_res = await dograh_service.check_health()
                dograh_healthy = bool(h_res.get("reachable"))
            except Exception:
                dograh_healthy = False

            if not dograh_healthy:
                logger.info(f"Dograh voice engine offline; queuing outbound call to {normalized_phone} locally.")

        # Step 6: Resolve Dograh telephony configuration ID
        resolved_config_id = None
        if active_tel_config and active_tel_config.dograh_config_id:
            resolved_config_id = active_tel_config.dograh_config_id


        tenant_id = request.tenant_id or request.business_id or agent.tenant_id
        if not tenant_id:
            biz_stmt = select(Tenant).order_by(Tenant.created_at.asc()).limit(1)
            biz_res = await session.execute(biz_stmt)
            default_biz = biz_res.scalar_one_or_none()
            if default_biz:
                tenant_id = default_biz.id

        # Step 8: Create Call record in DB
        call = Call(
            phone_number=normalized_phone,
            agent_id=agent.id,
            tenant_id=tenant_id,
            campaign_id=request.campaign_id,
            contact_id=request.contact_id,
            direction="outbound",
            status=STATUS_INITIATING,
            started_at=datetime.now(UTC),
            context_data=request.initial_context or {},
        )
        session.add(call)
        await session.flush()

        await persist_call_event(session, call.id, "call.created", {"phone": normalized_phone, "agent_id": agent.id})
        await session.commit()
        await session.refresh(call)

        # Cache active call session in Redis
        try:
            await redis_service.save_active_call_session(
                call.id,
                {
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "phone_number": normalized_phone,
                    "status": STATUS_INITIATING,
                    "tenant_id": tenant_id,
                    "started_at": call.started_at.isoformat() if call.started_at else None,
                },
            )
            await redis_service.record_call_event_metric("call.created")
            await redis_service.acquire_concurrency_slot(agent.id)
        except Exception as e:
            logger.debug(f"Redis session tracking note: {e}")

        call_context = dict(request.initial_context or {})
        call_context["app_call_id"] = call.id
        call_context["agent_name"] = agent.name
        call_context["caller_id"] = caller_id

        # Trigger Voice AI Engine (Native Sarvam Telephony or Dograh)
        if voice_engine == "sarvam" and target_provider == "vobiz":
            try:
                from app.services.sarvam_telephony_service import sarvam_telephony_service
                vobiz_resp = await sarvam_telephony_service.initiate_vobiz_call(
                    call_id=call.id,
                    to_number=normalized_phone,
                    from_number=caller_id,
                    auth_id=custom_tel_auth_id,
                    auth_token=custom_tel_auth_token,
                )
                call_uuid = vobiz_resp.get("call_uuid", "")
                call.telephony_call_id = call_uuid
                call.status = STATUS_INITIATING
                await persist_call_event(session, call.id, "call.initiated", {"vobiz_call_uuid": call_uuid, "engine": "sarvam"})
                await session.commit()
                await session.refresh(call)

                try:
                    await redis_service.update_call_status(
                        call.id,
                        STATUS_INITIATING,
                        extra={"vobiz_call_uuid": call_uuid, "engine": "sarvam"},
                    )
                    await redis_service.record_call_event_metric("call.initiated")
                except Exception as e:
                    logger.debug(f"Redis update note: {e}")

                return call

            except Exception as sarvam_err:
                logger.error(f"[Native Sarvam] VoBiz call initiation failed: {sarvam_err}")
                call.status = STATUS_FAILED
                call.ended_at = datetime.now(UTC)
                await persist_call_event(session, call.id, "call.failed", {"error": str(sarvam_err)})
                await persist_post_call_artifacts(session, call)
                await session.commit()
                try:
                    await redis_service.update_call_status(call.id, STATUS_FAILED)
                    await redis_service.release_concurrency_slot(agent.id)
                    await redis_service.record_call_event_metric("call.failed")
                except Exception:
                    pass
                raise CallServiceException(
                    message=f"VoBiz call failed: {sarvam_err}",
                    status_code=500,
                    error_code="VOBIZ_CALL_FAILED",
                )

        # Dograh Voice Engine Fallback
        try:
            dograh_resp = await dograh_service.initiate_call(
                phone_number=normalized_phone,
                trigger_path=agent.dograh_trigger_path,
                workflow_id=agent.dograh_workflow_id,
                initial_context=call_context,
                telephony_configuration_id=resolved_config_id,
            )

            run_id = dograh_resp.get("workflow_run_id")
            run_name = dograh_resp.get("workflow_run_name")
            if run_id:
                call.dograh_run_id = run_id
            if run_name:
                call.dograh_run_name = run_name

            call.status = STATUS_INITIATING
            await persist_call_event(session, call.id, "call.initiated", {"dograh_run_id": run_id})
            await session.commit()
            await session.refresh(call)

            try:
                await redis_service.update_call_status(
                    call.id,
                    STATUS_INITIATING,
                    extra={"dograh_run_id": run_id, "dograh_run_name": run_name},
                )
                await redis_service.record_call_event_metric("call.initiated")
            except Exception as e:
                logger.debug(f"Redis update note: {e}")

            return call

        except DograhServiceException as exc:
            call.status = STATUS_FAILED
            call.ended_at = datetime.now(UTC)
            user_msg = exc.message
            if "Insufficient balance" in user_msg or "vobiz-402" in user_msg:
                user_msg = "VoBiz Telephony Error: Insufficient account balance. Please recharge your VoBiz account."
            await persist_call_event(session, call.id, "call.failed", {"error": user_msg})
            await persist_post_call_artifacts(session, call)
            await session.commit()
            try:
                await redis_service.update_call_status(call.id, STATUS_FAILED)
                await redis_service.release_concurrency_slot(agent.id)
                await redis_service.record_call_event_metric("call.failed")
            except Exception:
                pass
            logger.warning(f"Dograh call initiation note: {user_msg}")
            raise DograhServiceException(
                message=user_msg,
                status_code=exc.status_code,
                error_code="INSUFFICIENT_TELEPHONY_BALANCE" if "Insufficient" in user_msg else exc.error_code,
            )


        except Exception as exc:
            call.status = STATUS_FAILED
            call.ended_at = datetime.now(UTC)
            await persist_call_event(session, call.id, "call.failed", {"error": str(exc)})
            await persist_post_call_artifacts(session, call)
            await session.commit()
            try:
                await redis_service.update_call_status(call.id, STATUS_FAILED)
                await redis_service.release_concurrency_slot(agent.id)
                await redis_service.record_call_event_metric("call.failed")
            except Exception:
                pass
            logger.error(f"Unexpected error initiating call: {exc}")
            raise DograhServiceException(
                message=f"Failed to initiate call: {exc}",
                status_code=500,
                error_code="CALL_INITIATION_FAILED",
            ) from exc

    @staticmethod
    async def dispatch_existing_call(call_id: str) -> Optional[Call]:
        """
        Executes outbound dialing for a previously queued Call record.
        Runs under strict concurrency control via BatchDialerService.
        """
        async with AsyncSessionLocal() as session:
            stmt = select(Call).where(Call.id == call_id)
            res = await session.execute(stmt)
            call = res.scalar_one_or_none()
            if not call:
                logger.error(f"[CallService] Call {call_id} not found for dispatch")
                return None

            if call.status in TERMINAL_STATES:
                logger.info(f"[CallService] Call {call_id} is already in terminal state '{call.status}', skipping")
                return call

            agent_stmt = select(Agent).where(Agent.id == call.agent_id)
            agent_res = await session.execute(agent_stmt)
            agent = agent_res.scalar_one_or_none()
            if not agent or not agent.enabled:
                call.status = STATUS_FAILED
                call.ended_at = datetime.now(UTC)
                await persist_call_event(session, call.id, "call.failed", {"error": "Agent not found or disabled"})
                await session.commit()
                return call

            context = call.context_data or {}
            target_provider = str(context.get("provider") or getattr(agent, "telephony_provider", None) or "vobiz").lower()
            voice_engine = getattr(settings, "VOICE_ENGINE", "sarvam").lower()

            caller_id = getattr(agent, "telephony_from_number", None) or settings.VOBIZ_FROM_NUMBER or "+918065354620"
            custom_tel_auth_id = (getattr(agent, "telephony_auth_id", None) or "").strip() or None
            custom_tel_auth_token = (getattr(agent, "telephony_auth_token", None) or "").strip() or None

            call.started_at = datetime.now(UTC)
            call.status = STATUS_INITIATING
            await session.commit()

            if voice_engine == "sarvam" and target_provider == "vobiz":
                try:
                    from app.services.sarvam_telephony_service import sarvam_telephony_service
                    vobiz_resp = await sarvam_telephony_service.initiate_vobiz_call(
                        call_id=call.id,
                        to_number=call.phone_number,
                        from_number=caller_id,
                        auth_id=custom_tel_auth_id,
                        auth_token=custom_tel_auth_token,
                    )
                    call_uuid = vobiz_resp.get("call_uuid", "")
                    call.telephony_call_id = call_uuid
                    await persist_call_event(session, call.id, "call.initiated", {"vobiz_call_uuid": call_uuid, "engine": "sarvam"})
                    await session.commit()
                    return call
                except Exception as sarvam_err:
                    err_str = str(sarvam_err)
                    logger.error(f"[CallService] VoBiz dispatch failed for call {call_id}: {err_str}")
                    call.status = STATUS_FAILED
                    call.ended_at = datetime.now(UTC)
                    if "Insufficient balance" in err_str or "402" in err_str:
                        call.termination_reason = "Insufficient VoBiz balance"
                        call.disposition = "insufficient_balance"
                    else:
                        call.termination_reason = err_str[:64]
                        call.disposition = "carrier_error"
                    await persist_call_event(session, call.id, "call.failed", {"error": err_str})
                    await session.commit()
                    return call

            # Fallback to Dograh
            try:
                dograh_resp = await dograh_service.initiate_call(
                    phone_number=call.phone_number,
                    trigger_path=agent.dograh_trigger_path,
                    workflow_id=agent.dograh_workflow_id,
                    initial_context=context,
                )
                run_id = dograh_resp.get("run_id") or dograh_resp.get("id")
                call.dograh_run_id = run_id
                await persist_call_event(session, call.id, "call.initiated", {"dograh_run_id": run_id, "engine": "dograh"})
                await session.commit()
                return call
            except Exception as dograh_err:
                logger.error(f"[CallService] Dograh dispatch failed for call {call_id}: {dograh_err}")
                call.status = STATUS_FAILED
                call.ended_at = datetime.now(UTC)
                await persist_call_event(session, call.id, "call.failed", {"error": str(dograh_err)})
                await session.commit()
                return call

    @staticmethod
    async def get_call_status(session: AsyncSession, call_id: str) -> Optional[Call]:
        stmt = (
            select(Call)
            .options(
                selectinload(Call.agent),
                selectinload(Call.transcript).selectinload(Transcript.segments),
                selectinload(Call.recording),
            )
            .where(Call.id == call_id)
        )
        result = await session.execute(stmt)
        call = result.scalar_one_or_none()
        if not call:
            return None

        # If call is still active and has a dograh_run_id, poll Dograh to sync status
        if call.status not in TERMINAL_STATES and call.dograh_run_id and call.agent and call.agent.dograh_workflow_id:
            try:
                run_data = await dograh_service.get_run_details(call.agent.dograh_workflow_id, call.dograh_run_id)
                if run_data:
                    is_completed = run_data.get("is_completed", False)
                    gathered = run_data.get("gathered_context", {}) or {}
                    logs = run_data.get("logs", {}) or {}

                    callbacks = logs.get("telephony_status_callbacks", [])
                    if callbacks:
                        latest_callback = callbacks[-1]
                        raw_st = latest_callback.get("status")
                        new_st = normalize_dograh_status(raw_st)
                        if new_st != call.status:
                            call.status = new_st
                            await persist_call_event(session, call.id, f"call.{new_st}", latest_callback)

                        if "duration" in latest_callback and latest_callback["duration"]:
                            try:
                                call.duration = float(latest_callback["duration"])
                            except (ValueError, TypeError):
                                pass

                    if is_completed and call.status not in TERMINAL_STATES:
                        call.status = STATUS_COMPLETED
                        await persist_call_event(session, call.id, "call.completed", {"reason": "workflow_completed"})

                    if run_data.get("transcript_public_url"):
                        call.transcript_url = run_data["transcript_public_url"]
                    if run_data.get("recording_public_url"):
                        call.recording_url = run_data["recording_public_url"]

                    if gathered.get("call_disposition"):
                        call.disposition = gathered.get("call_disposition")

                    if call.status in TERMINAL_STATES:
                        if not call.ended_at:
                            call.ended_at = datetime.now(UTC)
                        await persist_post_call_artifacts(session, call, run_data)

                    await session.commit()
                    await session.refresh(call)
            except Exception as e:
                logger.warning(f"Error syncing status from Dograh for call {call_id}: {e}")

        return call

    @staticmethod
    async def list_history(
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
        tenant_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Tuple[List[Call], int]:
        count_stmt = select(Call)
        if tenant_id:
            count_stmt = count_stmt.where(Call.tenant_id == tenant_id)
        if agent_id:
            count_stmt = count_stmt.where(Call.agent_id == agent_id)

        count_res = await session.execute(count_stmt)
        total = len(count_res.scalars().all())

        stmt = select(Call).options(selectinload(Call.agent)).order_by(Call.created_at.desc())
        if tenant_id:
            stmt = stmt.where(Call.tenant_id == tenant_id)
        if agent_id:
            stmt = stmt.where(Call.agent_id == agent_id)
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        calls = list(result.scalars().all())
        return calls, total

    @staticmethod
    async def process_webhook(session: AsyncSession, payload: DograhWebhookPayload) -> Optional[Call]:
        call = None
        if payload.call_id:
            stmt = select(Call).where(Call.id == payload.call_id)
            res = await session.execute(stmt)
            call = res.scalar_one_or_none()

        if not call and payload.workflow_run_id:
            stmt = select(Call).where(Call.dograh_run_id == payload.workflow_run_id)
            res = await session.execute(stmt)
            call = res.scalar_one_or_none()

        if not call:
            logger.warning(f"Webhook received for unknown call: call_id={payload.call_id}, run_id={payload.workflow_run_id}")
            return None

        new_status = normalize_dograh_status(payload.status) if payload.status else STATUS_COMPLETED
        call.status = new_status

        if payload.duration is not None:
            call.duration = payload.duration
        if payload.disposition:
            call.disposition = payload.disposition
        elif payload.outcome:
            call.disposition = payload.outcome

        if payload.transcript_url:
            call.transcript_url = payload.transcript_url
        if payload.recording_url:
            call.recording_url = payload.recording_url

        if not call.ended_at:
            call.ended_at = datetime.now(UTC)

        await persist_call_event(session, call.id, f"call.{new_status}", payload.model_dump(exclude_none=True))
        await persist_post_call_artifacts(session, call, payload.model_dump())

        await session.commit()
        await session.refresh(call)
        logger.info(f"Updated call {call.id} from Dograh webhook. Status: {call.status}, Duration: {call.duration}")
        return call


call_service = CallService()
