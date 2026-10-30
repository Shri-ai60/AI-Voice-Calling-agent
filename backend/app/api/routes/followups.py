from datetime import UTC, datetime, timedelta
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import verify_app_client
from app.models.lead import Followup
from app.models.call import Call, Transcript, TranscriptSegment
from app.models.agent import Agent
from app.schemas.lead import FollowupResponse, UpdateFollowupRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/followups", tags=["followups"], dependencies=[Depends(verify_app_client)])


def map_followup_to_response(f: Followup) -> FollowupResponse:
    return FollowupResponse(
        id=f.id,
        followup_id=f.id,
        tenant_id=f.tenant_id,
        contact_id=f.contact_id,
        agent_id=f.agent_id,
        call_id=f.call_id,
        phone_number=f.phone_number,
        scheduled_at=f.scheduled_at.isoformat() if f.scheduled_at else None,
        status=f.status or "pending",
        notes=f.notes,
        created_at=f.created_at.isoformat() if f.created_at else datetime.now(UTC).isoformat(),
        updated_at=f.updated_at.isoformat() if f.updated_at else None,
    )


async def sync_qualifying_calls_to_followups(db: AsyncSession):
    """
    Evaluates qualifying calls:
    Only calls where the customer explicitly requested a callback (callback_requested)
    with exact time extracted from transcript are added to Scheduled Follow-ups.
    (Carrier busy or unanswered attempts are not spammed into Scheduled Follow-ups).
    """
    try:
        stmt = (
            select(Call)
            .where(Call.disposition == "callback_requested")
            .order_by(Call.created_at.desc())
            .limit(100)
        )
        res = await db.execute(stmt)
        candidate_calls = res.scalars().all()

        if not candidate_calls:
            return

        candidate_ids = [c.id for c in candidate_calls]
        f_stmt = select(Followup.call_id).where(Followup.call_id.in_(candidate_ids))
        existing_call_ids = set((await db.execute(f_stmt)).scalars().all())

        new_count = 0
        now = datetime.now(UTC)

        for call in candidate_calls:
            if call.id in existing_call_ids:
                continue

            call_phone = call.phone_number or getattr(call, "caller_number", None)
            if not call_phone:
                continue

            from app.services.callback_time import schedule_from_transcript
            tr_stmt = select(Transcript).options(selectinload(Transcript.segments)).where(Transcript.call_id == call.id)
            tr_res = await db.execute(tr_stmt)
            tr = tr_res.scalar_one_or_none()
            tr_text = ""
            if tr and tr.segments:
                tr_text = "\n".join(f"{s.speaker}: {s.text}" for s in tr.segments)
            
            parsed_time = schedule_from_transcript(tr_text) if tr_text else None
            sched = parsed_time or (now + timedelta(hours=2))
            time_str = sched.strftime('%d %b %Y, %I:%M %p') if parsed_time else 'as requested'
            notes = f"Customer requested callback for {time_str}. (Action: Schedule callback)"
            status_val = "scheduled"

            new_f = Followup(
                tenant_id=call.tenant_id,
                contact_id=call.contact_id,
                agent_id=call.agent_id,
                call_id=call.id,
                phone_number=call_phone,
                scheduled_at=sched,
                status=status_val,
                notes=notes,
                created_at=call.created_at or now,
            )
            db.add(new_f)
            existing_call_ids.add(call.id)
            new_count += 1

        if new_count > 0:
            await db.commit()
            logger.info(f"Auto-synced {new_count} qualifying calls into Followup table")
    except Exception as e:
        logger.warning(f"Notice during call-to-followup auto-sync: {e}")


@router.get("", response_model=List[FollowupResponse])
async def list_followups(
    agent_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    business_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    List scheduled followups, automatically checking and syncing all qualifying calls.
    """
    # 1. Silently sync any recent busy / unanswered / failed calls into followups
    await sync_qualifying_calls_to_followups(db)

    t_id = tenant_id or business_id
    stmt = select(Followup).order_by(Followup.created_at.desc())
    if agent_id:
        stmt = stmt.where(Followup.agent_id == agent_id)
    if t_id:
        stmt = stmt.where(Followup.tenant_id == t_id)
    stmt = stmt.offset(skip).limit(limit)

    res = await db.execute(stmt)
    items = res.scalars().all()
    return [map_followup_to_response(f) for f in items]


@router.post("/dispatch")
async def dispatch_followups(db: AsyncSession = Depends(get_db)):
    """
    Manually or automatically starts all follow-up calls that are due according to their scheduled time.
    """
    # Sync qualifying calls first
    await sync_qualifying_calls_to_followups(db)
    
    from app.services.followup_dispatcher import dispatch_due_followups
    placed = await dispatch_due_followups()
    return {
        "status": "success",
        "placed_count": placed,
        "message": f"{placed} follow-up call(s) initiated according to their scheduled time." if placed > 0 else "No follow-up calls are currently due for dialing.",
    }


@router.post("/{followup_id}/call")
async def call_followup_now(followup_id: str, db: AsyncSession = Depends(get_db)):
    """
    Immediately starts an outbound follow-up call to the contact.
    """
    stmt = select(Followup).where(Followup.id == followup_id)
    f = (await db.execute(stmt)).scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    if not f.phone_number:
        raise HTTPException(status_code=400, detail="Follow-up has no phone number")

    # Resolve agent
    agent_id = f.agent_id
    if not agent_id and f.call_id:
        c_orig = (await db.execute(select(Call).where(Call.id == f.call_id))).scalar_one_or_none()
        if c_orig:
            agent_id = c_orig.agent_id
    if not agent_id:
        ag = (await db.execute(select(Agent).where(Agent.enabled == True).limit(1))).scalar_one_or_none()
        if ag:
            agent_id = ag.id
    if not agent_id:
        raise HTTPException(status_code=400, detail="No active agent available to place follow-up call")

    from app.services.call_service import CallService
    from app.schemas.call import InitiateCallRequest
    try:
        new_call = await CallService.initiate_call(
            db,
            InitiateCallRequest(
                phone_number=f.phone_number,
                agent_id=agent_id,
                tenant_id=f.tenant_id,
                contact_id=f.contact_id,
                initial_context={
                    "auto_callback": True,
                    "followup_id": f.id,
                    "reason": "Direct follow-up call initiated by operator",
                },
            ),
        )
        f.status = "completed"
        f.notes = (f.notes or "") + f" | Follow-up call placed (call {new_call.id})"
        f.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(f)
        return {
            "status": "success",
            "call_id": new_call.id,
            "phone_number": f.phone_number,
            "message": f"Follow-up call placed to {f.phone_number}!",
            "followup": map_followup_to_response(f),
        }
    except Exception as e:
        logger.error(f"Error placing follow-up call {f.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to place follow-up call: {str(e)}")


@router.get("/{followup_id}", response_model=FollowupResponse)
async def get_followup(followup_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Followup).where(Followup.id == followup_id)
    res = await db.execute(stmt)
    f = res.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="Followup not found")
    return map_followup_to_response(f)


@router.patch("/{followup_id}", response_model=FollowupResponse)
async def update_followup(followup_id: str, payload: UpdateFollowupRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(Followup).where(Followup.id == followup_id)
    res = await db.execute(stmt)
    f = res.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="Followup not found")

    if payload.status is not None:
        f.status = payload.status
    if payload.notes is not None:
        f.notes = payload.notes
    if payload.scheduled_at is not None:
        try:
            f.scheduled_at = datetime.fromisoformat(payload.scheduled_at.replace("Z", "+00:00"))
        except Exception:
            pass

    f.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(f)
    return map_followup_to_response(f)
