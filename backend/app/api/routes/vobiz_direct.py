import logging
from fastapi import APIRouter, Request, Response, WebSocket
from app.services.sarvam_telephony_service import sarvam_telephony_service

logger = logging.getLogger("vobiz_direct_routes")

router = APIRouter(prefix="/telephony/vobiz", tags=["vobiz-direct"])


@router.get("/status")
async def get_telephony_status():
    """
    Diagnostic status endpoint checking public webhook tunnel,
    Sarvam AI API key, VoBiz carrier credentials, and storage paths.
    """
    from app.config import DATA_DIR, RECORDINGS_DIR, TRANSCRIPTS_DIR, settings
    public_url = sarvam_telephony_service._get_public_url()
    return {
        "status": "ready" if public_url else "warning",
        "tunnel_url": public_url or None,
        "tunnel_active": bool(public_url and public_url.startswith("https://")),
        "sarvam_configured": bool(settings.SARVAM_API_KEY and len(settings.SARVAM_API_KEY) > 10),
        "vobiz_configured": bool(settings.VOBIZ_AUTH_ID and settings.VOBIZ_AUTH_TOKEN),
        "gemini_configured": bool(settings.GEMINI_API_KEY and len(settings.GEMINI_API_KEY) > 10),
        "data_directory": str(DATA_DIR),
        "recordings_count": len(list(RECORDINGS_DIR.glob("*.wav"))),
        "transcripts_count": len(list(TRANSCRIPTS_DIR.glob("*.txt"))),
    }


@router.api_route("/answer/{call_id}", methods=["GET", "POST"])
async def vobiz_answer_webhook(call_id: str, request: Request):
    """
    Called by VoBiz when the customer answers the phone.
    Returns the Plivo/VoBiz XML stream directive to connect the audio WebSocket.
    """
    logger.info(f"[VoBiz Direct] Received answer webhook for Call ID: {call_id}")
    xml_content = sarvam_telephony_service.get_vobiz_answer_xml(call_id)
    return Response(content=xml_content, media_type="application/xml")


async def _save_vobiz_recording_url(call_id: str, data: dict):
    rec_url = (
        data.get("RecordUrl")
        or data.get("RecordingUrl")
        or data.get("record_url")
        or data.get("recording_url")
    )
    if not rec_url or not str(rec_url).startswith("http"):
        return

    import asyncio
    import httpx
    from app.config import settings
    from app.services.storage.s3 import storage_service
    from app.database import AsyncSessionLocal
    from app.models.call import Call, Recording
    from app.models.agent import Agent
    from sqlalchemy import select

    async def _download_and_save():
        # Retrieve agent credentials if custom, otherwise use system settings
        auth_id = getattr(settings, "VOBIZ_AUTH_ID", "")
        auth_token = getattr(settings, "VOBIZ_AUTH_TOKEN", "")

        try:
            async with AsyncSessionLocal() as session:
                call_obj = await session.get(Call, call_id)
                if call_obj and call_obj.agent_id:
                    agent_obj = await session.get(Agent, call_obj.agent_id)
                    if agent_obj:
                        if getattr(agent_obj, "telephony_auth_id", None):
                            auth_id = agent_obj.telephony_auth_id
                        if getattr(agent_obj, "telephony_auth_token", None):
                            auth_token = agent_obj.telephony_auth_token
        except Exception as err:
            logger.debug(f"[VoBiz Direct] Could not resolve agent credentials: {err}")

        headers = {
            "X-Auth-ID": auth_id,
            "X-Auth-Token": auth_token,
        }

        # Retry with slight delays if carrier is still finalizing the audio file
        for attempt in range(4):
            try:
                logger.info(f"[VoBiz Direct] Downloading carrier recording (attempt {attempt + 1}) from {rec_url} for call {call_id}...")
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                    resp = await client.get(rec_url, headers=headers)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        storage_key = f"calls/{call_id}/recording.wav"
                        await storage_service.upload(storage_key, resp.content, content_type="audio/wav")
                        logger.info(f"[VoBiz Direct] Successfully saved authentic carrier recording to {storage_key} ({len(resp.content)} bytes)")

                        async with AsyncSessionLocal() as session:
                            call = await session.get(Call, call_id)
                            if call:
                                call.recording_url = f"/api/v1/calls/{call.id}/recording"
                                rec_res = await session.execute(select(Recording).where(Recording.call_id == call_id))
                                rec = rec_res.scalar_one_or_none()
                                if rec:
                                    rec.file_size = len(resp.content)
                                    rec.storage_key = storage_key
                                    rec.status = "ready"
                                await session.commit()
                        return
                    else:
                        logger.warning(f"[VoBiz Direct] Carrier recording attempt {attempt + 1} status: {resp.status_code}, content: {len(resp.content)} bytes")
            except Exception as e:
                logger.warning(f"[VoBiz Direct] Download error on attempt {attempt + 1}: {e}")

            await asyncio.sleep(2.0)

    asyncio.create_task(_download_and_save())


@router.api_route("/recording-callback/{call_id}", methods=["GET", "POST"])
async def vobiz_recording_callback(call_id: str, request: Request):
    """
    Called by VoBiz when carrier-side call recording finishes.
    """
    try:
        data = await request.json()
    except Exception:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            data = dict(request.query_params)

    logger.info(f"[VoBiz Direct] Received recording callback for Call ID: {call_id}, data: {data}")
    await _save_vobiz_recording_url(call_id, data)
    return {"status": "ok", "call_id": call_id}


@router.post("/hangup/{call_id}")
async def vobiz_hangup_webhook(call_id: str, request: Request):
    """
    Called by VoBiz when the call terminates.
    """
    try:
        data = await request.json()
    except Exception:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            data = {}

    logger.info(f"[VoBiz Direct] Received hangup callback for Call ID: {call_id}, data: {data}")
    call_status = (data.get("CallStatus") or "").lower()
    hangup_cause = data.get("HangupCause") or data.get("HangupCauseName") or ""
    try:
        from app.database import AsyncSessionLocal
        from app.models.call import Call
        from datetime import datetime, timezone
        async with AsyncSessionLocal() as session:
            call = await session.get(Call, call_id)
            if call:
                if call_status in ("busy", "failed", "no-answer", "rejected") or "busy" in hangup_cause.lower():
                    call.status = "busy" if ("busy" in hangup_cause.lower() or call_status == "busy") else "failed"
                    call.disposition = call.status
                elif call.status in ("initiating", "ringing"):
                    call.status = "no_answer"
                    call.disposition = "no_answer"
                elif call.status != "completed":
                    call.status = "completed"
                call.termination_reason = hangup_cause or call_status
                call.ended_at = datetime.now(timezone.utc)
                await session.commit()
    except Exception as e:
        logger.warning(f"[VoBiz Direct] Could not update call status on hangup: {e}")

    await _save_vobiz_recording_url(call_id, data)
    return {"status": "ok", "call_id": call_id}


@router.websocket("/stream/{call_id}")
async def vobiz_media_stream_websocket(websocket: WebSocket, call_id: str):
    """
    Bidirectional audio WebSocket stream from VoBiz.
    Streams 8kHz mu-law audio directly to/from Sarvam AI.
    """
    logger.info(f"[VoBiz Direct] Incoming audio stream connection for Call ID: {call_id}")
    await sarvam_telephony_service.handle_vobiz_media_stream(websocket, call_id)

