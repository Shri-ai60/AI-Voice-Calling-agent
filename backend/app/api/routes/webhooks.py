import logging
from datetime import UTC, datetime, timedelta
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import verify_webhook_secret
from app.models.call import Call
from app.models.lead import Followup
from app.schemas.call import DograhWebhookPayload
from app.services.call_service import call_service, normalize_dograh_status, TERMINAL_STATES

logger = logging.getLogger(__name__)

# Dograh webhooks require the optional webhook secret (passthrough if not configured)
dograh_router = APIRouter(prefix="/webhooks", tags=["webhooks"], dependencies=[Depends(verify_webhook_secret)])

# VoBiz telephony webhooks — no secret required (VoBiz does not support custom headers)
vobiz_router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Combined router (both get merged into the same path prefix)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/dograh", dependencies=[Depends(verify_webhook_secret)])
async def receive_dograh_webhook(
    payload: DograhWebhookPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Receives post-call webhook reports from Dograh.
    Updates call duration, transcript URL, audio recording URL, and final call disposition.
    """
    logger.info(f"Received Dograh webhook payload: {payload.model_dump(exclude_none=True)}")
    call = await call_service.process_webhook(db, payload)
    if not call:
        # Acknowledge without failing to prevent webhook retries on unknown test payloads
        return {"success": True, "processed": False, "message": "Call not found for payload"}

    return {
        "success": True,
        "processed": True,
        "call_id": call.id,
        "status": call.status,
    }


@router.post("/call-status")
@router.post("/twilio")
async def receive_vobiz_call_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receives real-time call status updates from VoBiz or Twilio telephony.
    Carriers send these during a call lifecycle: initiated, ringing, in-progress, completed, etc.
    """
    try:
        body = await request.json()
    except Exception:
        try:
            form = await request.form()
            body = dict(form)
        except Exception:
            body = {}

    logger.info(f"Received telephony call-status webhook: {body}")

    call_uuid = (
        body.get("CallUUID")
        or body.get("call_uuid")
        or body.get("CallSid")
        or body.get("call_sid")
        or body.get("UUID")
    )
    raw_status = (
        body.get("Status")
        or body.get("status")
        or body.get("CallStatus")
        or ""
    )
    duration_raw = body.get("Duration") or body.get("BillDuration") or body.get("duration")

    if not raw_status:
        return {"success": True, "processed": False, "message": "No status in payload"}

    new_status = normalize_dograh_status(raw_status)

    call = None

    # Try to find call by VoBiz UUID or Twilio CallSid stored in context_data
    if call_uuid:
        stmt = select(Call).where(Call.status.in_(["initiating", "ringing", "in_progress"]))
        res = await db.execute(stmt)
        active_calls = res.scalars().all()
        for c in active_calls:
            ctx = c.context_data or {}
            if (
                ctx.get("vobiz_call_uuid") == str(call_uuid)
                or ctx.get("CallUUID") == str(call_uuid)
                or ctx.get("call_uuid") == str(call_uuid)
                or ctx.get("twilio_call_sid") == str(call_uuid)
                or ctx.get("CallSid") == str(call_uuid)
                or ctx.get("call_sid") == str(call_uuid)
            ):
                call = c
                break

    if not call:
        logger.debug(f"VoBiz webhook: no active call matched UUID={call_uuid} status={raw_status}")
        # Still return 200 so VoBiz doesn't retry
        return {"success": True, "processed": False, "message": "No matching active call found"}

    # Only update if not already in a terminal state
    if call.status not in TERMINAL_STATES:
        call.status = new_status
        logger.info(f"VoBiz status update: call {call.id} -> {new_status}")

    if new_status in TERMINAL_STATES and not call.ended_at:
        call.ended_at = datetime.now(UTC)

    if new_status in ("busy", "no_answer", "failed", "cancelled") and (call.phone_number or getattr(call, "caller_number", None)):
        f_stmt = select(Followup).where(Followup.call_id == call.id)
        existing_f = (await db.execute(f_stmt)).scalar_one_or_none()
        if not existing_f:
            if new_status == "busy":
                delay = 30
                notes = f"Category 2: PHONE / LINE BUSY. Status: {new_status}. Action: Retry call after {delay} minutes"
            elif new_status == "no_answer":
                delay = 60
                notes = f"Category 3: CALL NOT ANSWERED / NO RESPONSE. Status: {new_status}. Action: Retry call in 1 hour"
            else:
                delay = 45
                notes = f"Category 4: CALL DISCONNECTED WITHOUT CONVERSATION. Status: {new_status}. Action: Retry call in 45 minutes"

            new_f = Followup(
                tenant_id=call.tenant_id,
                contact_id=call.contact_id,
                agent_id=call.agent_id,
                call_id=call.id,
                phone_number=call.phone_number or getattr(call, "caller_number", None),
                scheduled_at=datetime.now(UTC) + timedelta(minutes=delay),
                status="pending",
                notes=notes,
            )
            db.add(new_f)

    await db.commit()

    return {
        "success": True,
        "processed": True,
        "call_id": call.id,
        "status": call.status,
    }
