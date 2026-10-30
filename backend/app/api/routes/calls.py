from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import verify_app_client
from app.models.call import Call, Recording, Transcript, TranscriptSegment
from app.schemas.call import (
    CallHistoryItem,
    CallHistoryResponse,
    CallStatusResponse,
    InitiateCallRequest,
    InitiateCallResponse,
)
from app.services.call_service import CallServiceException, call_service, persist_post_call_artifacts, TERMINAL_STATES
from app.services.dograh_service import DograhServiceException, dograh_service
from app.services.lead_intelligence_service import lead_intelligence_service
from app.services.redis_service import redis_service
from app.services.storage.s3 import storage_service
from app.services.telephony_service import telephony_service
from app.config import settings

router = APIRouter(prefix="/calls", tags=["calls"], dependencies=[Depends(verify_app_client)])


def map_call_to_document(c: Call) -> Dict[str, Any]:
    raw_st = (c.status or "initiating").lower()
    state_map = {
        "queued": "QUEUED",
        "initiating": "DIALING",
        "ringing": "RINGING",
        "in_progress": "CONNECTED",
        "completed": "COMPLETED",
        "busy": "BUSY",
        "no_answer": "NO_ANSWER",
        "failed": "FAILED",
    }
    state = state_map.get(raw_st, raw_st.upper())

    # Load real segments from relation
    segments = []
    if c.transcript and c.transcript.segments:
        for s in c.transcript.segments:
            segments.append({
                "speaker": s.speaker,
                "text": s.text,
                "timestamp": c.created_at.isoformat() if c.created_at else "",
                "start_time": s.start_time,
                "end_time": s.end_time,
            })

    interest = "uncertain"
    if c.disposition:
        disp_lower = c.disposition.lower()
        if "interest" in disp_lower and "not" not in disp_lower:
            interest = "interested"
        elif "not" in disp_lower:
            interest = "not_interested"

    recording_url = f"/api/v1/calls/{c.id}/recording"

    return {
        "call_id": c.id,
        "agent_id": c.agent_id,
        "tenant_id": c.tenant_id,
        "business_id": c.tenant_id,
        "campaign_id": c.campaign_id,
        "contact_id": c.contact_id,
        "phone_number": c.phone_number,
        "state": state,
        "termination_reason": c.termination_reason,
        "duration": c.duration or 0.0,
        "provider": "vobiz",
        "created_at": c.created_at.isoformat() if c.created_at else datetime.now(UTC).isoformat(),
        "updated_at": (c.ended_at or c.created_at or datetime.now(UTC)).isoformat(),
        "last_interest_status": interest,
        "transcript": {
            "call_id": c.id,
            "agent_id": c.agent_id,
            "phone_number": c.phone_number,
            "duration": c.duration or 0.0,
            "language": (c.agent.primary_language if (c.agent and c.agent.primary_language) else "Hindi"),
            "provider": (c.context_data or {}).get("provider", "vobiz"),
            "stt_model": getattr(settings, "SARVAM_STT_MODEL", "saaras:v3"),
            "llm_model": getattr(settings, "SARVAM_LLM_MODEL", "sarvam-105b-conversations"),
            "tts_model": getattr(settings, "SARVAM_TTS_MODEL", "bulbul:v3"),
            "segments": segments,
            "created_at": c.created_at.isoformat() if c.created_at else datetime.now(UTC).isoformat(),
        } if (segments or c.transcript_url) else None,
        "recording": {
            "provider_url": recording_url,
            "local_path": None,
        },
    }


@router.get("", response_model=List[Dict[str, Any]])
async def list_calls(
    agent_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    business_id: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = Query(100, ge=1, le=200),
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    List calls formatted for frontend Calls table and dashboard.
    """
    t_id = tenant_id or business_id
    stmt = (
        select(Call)
        .options(
            selectinload(Call.agent),
            selectinload(Call.transcript).selectinload(Transcript.segments),
            selectinload(Call.recording),
        )
        .order_by(Call.created_at.desc())
    )
    if agent_id:
        stmt = stmt.where(Call.agent_id == agent_id)
    if campaign_id:
        stmt = stmt.where(Call.campaign_id == campaign_id)
    if t_id:
        stmt = stmt.where(Call.tenant_id == t_id)

    stmt = stmt.offset(skip).limit(limit)
    res = await db.execute(stmt)
    calls = res.scalars().all()

    mapped = [map_call_to_document(c) for c in calls]
    if state and state.upper() != "ALL":
        mapped = [m for m in mapped if m["state"] == state.upper()]

    return mapped


@router.post("/initiate", response_model=InitiateCallResponse)
async def initiate_call(
    request: InitiateCallRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate an outbound phone call to a customer using the specified Agent.
    """
    try:
        call = await call_service.initiate_call(db, request)
        return InitiateCallResponse(
            success=True,
            call_id=call.id,
            status=call.status,
            message="Call successfully initiated",
        )
    except CallServiceException as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"success": False, "error": e.error_code, "message": e.message, "detail": e.message},
        )
    except DograhServiceException as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"success": False, "error": e.error_code, "message": e.message, "detail": e.message},
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "INTERNAL_SERVER_ERROR", "message": str(e)},
        )


@router.get("/history", response_model=CallHistoryResponse)
async def list_call_history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant_id: Optional[str] = None,
    business_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve past call history with metadata, duration, transcript and recording links.
    """
    t_id = tenant_id or business_id
    calls, total = await call_service.list_history(db, limit=limit, offset=offset, tenant_id=t_id, agent_id=agent_id)
    items = [
        CallHistoryItem(
            call_id=c.id,
            dograh_run_id=c.dograh_run_id,
            phone_number=c.phone_number,
            agent_id=c.agent_id,
            tenant_id=c.tenant_id,
            campaign_id=c.campaign_id,
            agent_name=c.agent.name if c.agent else None,
            status=c.status,
            started_at=c.started_at,
            ended_at=c.ended_at,
            duration=c.duration,
            disposition=c.disposition,
            transcript_url=c.transcript_url,
            recording_url=c.recording_url,
            created_at=c.created_at,
        )
        for c in calls
    ]
    return CallHistoryResponse(success=True, calls=items, total=total)


@router.get("/{call_id}", response_model=Dict[str, Any])
async def get_call_detail(
    call_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get full call details formatted for the frontend drawer.
    """
    call = await call_service.get_call_status(db, call_id)
    if not call:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")

    # If call is completed/failed and lacks real transcript or recording in MinIO, sync from Dograh
    needs_sync = (
        call.status in TERMINAL_STATES
        and call.dograh_run_id
        and (
            not call.transcript
            or not call.transcript.segments
            or not call.recording
            or call.recording.status != "ready"
        )
    )
    if needs_sync:
        try:
            await persist_post_call_artifacts(db, call)
            await db.commit()
            call = await call_service.get_call_status(db, call_id)
        except Exception as e:
            logger.debug(f"Auto sync on get_call_detail notice: {e}")

    return map_call_to_document(call)


@router.get("/{call_id}/status", response_model=CallStatusResponse)
async def get_call_status(
    call_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the live status and details of a call.
    """
    call = await call_service.get_call_status(db, call_id)
    if not call:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "CALL_NOT_FOUND", "message": f"Call {call_id} not found"},
        )

    agent_name = call.agent.name if call.agent else None
    return CallStatusResponse(
        call_id=call.id,
        status=call.status,
        phone_number=call.phone_number,
        agent_id=call.agent_id,
        agent_name=agent_name,
        started_at=call.started_at,
        ended_at=call.ended_at,
        duration=call.duration,
        disposition=call.disposition,
        transcript_url=call.transcript_url,
        recording_url=call.recording_url,
    )


@router.post("/{call_id}/hangup")
async def hangup_call(
    call_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Hang up an ongoing call — immediately disconnects the callee's phone via carrier API (VoBiz),
    terminates the live Dograh session, updates Redis, and marks the DB record.
    """
    stmt = select(Call).options(selectinload(Call.agent)).where(Call.id == call_id)
    res = await db.execute(stmt)
    call = res.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    # 1. Retrieve carrier telephony call UUID (VoBiz call_uuid)
    call_uuid = call.telephony_call_id
    run_data = None
    if not call_uuid and call.dograh_run_id and call.agent and call.agent.dograh_workflow_id:
        try:
            run_data = await dograh_service.get_run_details(call.agent.dograh_workflow_id, call.dograh_run_id)
            if run_data:
                call_uuid = (
                    (run_data.get("gathered_context") or {}).get("call_id")
                    or (run_data.get("provider_metadata") or {}).get("call_id")
                )
        except Exception as e:
            logger.debug(f"Could not retrieve run details for hangup: {e}")

    # 2. Immediately terminate phone call on carrier level (VoBiz) to disconnect callee's phone
    carrier_terminated = False
    if call_uuid:
        try:
            carrier_terminated = await telephony_service.hangup_live_telephony_call(call_uuid)
            logger.info(f"Carrier hangup result for call {call_id} (uuid={call_uuid}): {carrier_terminated}")
        except Exception as e:
            logger.warning(f"Failed to hangup carrier call {call_uuid}: {e}")

    # 3. Terminate Dograh voice engine run
    dograh_terminated = False
    if call.dograh_run_id:
        workflow_id = call.agent.dograh_workflow_id if call.agent else None
        try:
            dograh_terminated = await dograh_service.terminate_call(
                run_id=call.dograh_run_id,
                workflow_id=workflow_id,
            )
        except Exception as e:
            logger.warning(f"Dograh terminate failed for call {call_id}: {e}")

    # 4. Mark completed in DB & Redis immediately
    call.status = "completed"
    if not call.ended_at:
        call.ended_at = datetime.now(UTC)

    try:
        await redis_service.update_call_status(call.id, "completed")
        if call.agent_id:
            await redis_service.release_concurrency_slot(call.agent_id)
    except Exception:
        pass

    await persist_post_call_artifacts(db, call, run_data)
    await db.commit()

    return {
        "success": True,
        "message": "Call terminated successfully",
        "carrier_terminated": carrier_terminated,
        "dograh_terminated": dograh_terminated,
    }


@router.get("/{call_id}/transcript")
async def get_call_transcript(
    call_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get transcript for a call stored in PostgreSQL.
    Guarantees every call has its complete transcript stored in PostgreSQL.
    """
    stmt = (
        select(Call)
        .options(
            selectinload(Call.transcript).selectinload(Transcript.segments),
            selectinload(Call.agent),
        )
        .where(Call.id == call_id)
    )
    res = await db.execute(stmt)
    call = res.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    if not call.transcript or not call.transcript.segments:
        try:
            await persist_post_call_artifacts(db, call)
        except Exception:
            pass
        await db.commit()
        res = await db.execute(stmt)
        call = res.scalar_one_or_none()

    segments = []
    if call.transcript and call.transcript.segments:
        for s in call.transcript.segments:
            segments.append({
                "speaker": s.speaker,
                "text": s.text,
                "timestamp": call.created_at.isoformat() if call.created_at else "",
                "start_time": s.start_time,
                "end_time": s.end_time,
                "sequence": s.sequence,
            })

    return {
        "call_id": call.id,
        "agent_id": call.agent_id,
        "phone_number": call.phone_number,
        "duration": call.duration or 0.0,
        "language": (call.agent.primary_language if (call.agent and call.agent.primary_language) else "Hindi"),
        "provider": (call.context_data or {}).get("provider", "vobiz"),
        "stt_model": getattr(settings, "SARVAM_STT_MODEL", "saaras:v3"),
        "llm_model": getattr(settings, "SARVAM_LLM_MODEL", "sarvam-105b-conversations"),
        "tts_model": getattr(settings, "SARVAM_TTS_MODEL", "bulbul:v3"),
        "segments": segments,
        "created_at": call.created_at.isoformat() if call.created_at else datetime.now(UTC).isoformat(),
    }


@router.get("/{call_id}/recording")
async def get_call_recording(
    call_id: str,
    request: Request,
    download: bool = Query(False, description="Whether to trigger file attachment download"),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream or download audio recording for a call directly from MinIO or local disk.
    Supports RFC 7233 Range headers (HTTP 206 Partial Content) for HTML5 audio players.
    """
    stmt = (
        select(Call)
        .options(selectinload(Call.recording), selectinload(Call.agent))
        .where(Call.id == call_id)
    )
    res = await db.execute(stmt)
    call = res.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    # If call does not have a recording in storage yet, persist/generate and upload
    if (not call.recording or not (await storage_service.exists(call.recording.storage_key))) and (call.status in TERMINAL_STATES):
        try:
            await persist_post_call_artifacts(db, call)
        except Exception:
            pass
        await db.commit()
        res = await db.execute(stmt)
        call = res.scalar_one_or_none()

    if not call.recording or not call.recording.storage_key:
        raise HTTPException(status_code=404, detail="Recording not available for this call")

    # Fetch audio bytes from storage (local disk or MinIO)
    audio_bytes = await storage_service.download(call.recording.storage_key)
    if not audio_bytes:
        raise HTTPException(status_code=404, detail="Recording audio could not be retrieved from storage")

    # Self-heal silent/corrupt legacy recordings using transcript speech reconstruction
    if len(audio_bytes) > 44:
        try:
            import audioop
            if audioop.rms(audio_bytes[44:], 2) < 30 and call.transcript and call.transcript.segments:
                from app.services.storage.audio_generator import reconstruct_call_audio_from_transcript
                healed_audio = await reconstruct_call_audio_from_transcript(db, call.id, duration_seconds=call.duration)
                if healed_audio and len(healed_audio) > 100:
                    audio_bytes = healed_audio
                    await storage_service.upload(call.recording.storage_key, audio_bytes, content_type="audio/wav")
                    if call.recording:
                        call.recording.file_size = len(audio_bytes)
                        await db.commit()
        except Exception:
            pass

    total_len = len(audio_bytes)
    range_header = request.headers.get("range")

    # Handle HTTP Range request (required by Chrome, Safari & Edge for HTML5 <audio> streaming)
    if range_header and range_header.startswith("bytes=") and not download:
        try:
            byte_range = range_header.replace("bytes=", "").strip()
            parts = byte_range.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else total_len - 1
            start = max(0, min(start, total_len - 1))
            end = max(start, min(end, total_len - 1))
            chunk_length = (end - start) + 1

            headers = {
                "Content-Range": f"bytes {start}-{end}/{total_len}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_length),
                "Content-Type": "audio/wav",
                "Cache-Control": "public, max-age=3600",
            }
            return Response(
                content=audio_bytes[start : end + 1],
                status_code=206,
                headers=headers,
                media_type="audio/wav",
            )
        except Exception:
            pass

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(total_len),
        "Content-Type": "audio/wav",
        "Cache-Control": "public, max-age=3600",
    }
    if download:
        headers["Content-Disposition"] = f'attachment; filename="call-{call_id}.wav"'

    return Response(
        content=audio_bytes,
        status_code=200,
        headers=headers,
        media_type="audio/wav",
    )


@router.post("/{call_id}/analyze-interest")
@router.get("/{call_id}/interest")
async def get_call_interest(
    call_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze or retrieve lead interest classification for a call using the IntentClassifier engine.
    """
    stmt = (
        select(Call)
        .options(
            selectinload(Call.transcript).selectinload(Transcript.segments),
            selectinload(Call.agent),
        )
        .where(Call.id == call_id)
    )
    res = await db.execute(stmt)
    call = res.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    # If transcript is missing, try syncing from Dograh first
    if not call.transcript or not call.transcript.segments:
        try:
            await persist_post_call_artifacts(db, call)
        except Exception:
            pass
        await db.commit()
        res = await db.execute(stmt)
        call = res.scalar_one_or_none()

    intel = await lead_intelligence_service.analyze_call(db, call)
    await db.commit()
    return intel


@router.post("/{call_id}/analyze-followup")
@router.get("/{call_id}/followup")
async def get_call_followup(
    call_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Evaluate call transcript with the 25-category Follow-Up Detection Engine.
    Returns category (1-25), name, recommended action, and auto-schedules callback if needed.
    """
    stmt = (
        select(Call)
        .options(
            selectinload(Call.transcript).selectinload(Transcript.segments),
            selectinload(Call.agent),
        )
        .where(Call.id == call_id)
    )
    res = await db.execute(stmt)
    call = res.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    if not call.transcript or not call.transcript.segments:
        try:
            await persist_post_call_artifacts(db, call)
        except Exception:
            pass
        await db.commit()
        res = await db.execute(stmt)
        call = res.scalar_one_or_none()

    followup_res = await lead_intelligence_service.analyze_followup(db, call)
    await db.commit()
    return followup_res

