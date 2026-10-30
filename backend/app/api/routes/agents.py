import uuid
from app.config import settings
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import verify_app_client
from app.models.agent import Agent
from app.models.call import Call
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate, StartCallsRequest
from app.schemas.call import InitiateCallRequest
from app.services.agent_service import agent_service
from app.services.call_service import call_service, validate_and_normalize_phone
from app.services.dograh_service import DograhServiceException
from app.services.voice_service import voice_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(verify_app_client)])


@router.get("", response_model=List[AgentResponse])
async def list_agents(
    tenant_id: Optional[str] = None,
    business_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    List all configured agents.
    """
    t_id = tenant_id or business_id
    agents = await agent_service.list_agents(db, tenant_id=t_id)
    return agents


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    request: AgentCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new agent and synchronize its workflow to Dograh.
    """
    if request.voice_id:
        try:
            await voice_service.validate_voice_config(
                provider=request.tts_provider,
                voice_id=request.voice_id,
                speaking_speed=request.speaking_speed,
                language_mode=request.language_mode,
            )
        except Exception as e:
            logger.warning(f"Voice validation warning: {e}")

    agent = await agent_service.create_agent(db, request)
    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve an agent by its unique ID.
    """
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "AGENT_NOT_FOUND", "message": f"Agent {agent_id} not found"},
        )
    return agent


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    request: AgentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing agent's configuration and re-sync to Dograh.
    """
    existing = await agent_service.get_agent(db, agent_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "AGENT_NOT_FOUND", "message": f"Agent {agent_id} not found"},
        )

    # Validate updated voice fields if specified
    v_provider = request.tts_provider or existing.tts_provider
    v_voice_id = request.voice_id or existing.voice_id
    v_speed = request.speaking_speed if request.speaking_speed is not None else existing.speaking_speed
    v_lang_mode = request.language_mode or existing.language_mode

    if request.voice_id is not None or request.speaking_speed is not None:
        try:
            await voice_service.validate_voice_config(
                provider=v_provider,
                voice_id=v_voice_id,
                speaking_speed=v_speed,
                language_mode=v_lang_mode,
            )
        except Exception as e:
            logger.warning(f"Voice validation warning: {e}")

    agent = await agent_service.update_agent(db, agent_id, request)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "AGENT_NOT_FOUND", "message": f"Agent {agent_id} not found"},
        )
    return agent


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete an agent.
    """
    deleted = await agent_service.delete_agent(db, agent_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "AGENT_NOT_FOUND", "message": f"Agent {agent_id} not found"},
        )
    return {"success": True, "message": f"Agent {agent_id} deleted successfully", "deleted": True, "agent_id": agent_id}


@router.post("/{agent_id}/toggle", response_model=AgentResponse)
async def toggle_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Toggle agent active/inactive status.
    """
    existing = await agent_service.get_agent(db, agent_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    update_req = AgentUpdate(enabled=not existing.enabled)
    updated = await agent_service.update_agent(db, agent_id, update_req)
    return updated


@router.post("/{agent_id}/duplicate", response_model=AgentResponse)
async def duplicate_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Duplicate an existing agent.
    """
    existing = await agent_service.get_agent(db, agent_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    new_create = AgentCreate(
        name=f"{existing.name} (Copy)",
        purpose=existing.purpose,
        instructions=existing.instructions,
        allowed_topics=existing.allowed_topics or [],
        restricted_topics=existing.restricted_topics or [],
        behavior_rules=existing.behavior_rules or [],
        enabled=True,
        voice_gender=existing.voice_gender,
        voice_id=existing.voice_id,
        voice_name=existing.voice_name,
        tts_provider=existing.tts_provider,
        language_mode=existing.language_mode,
        primary_language=existing.primary_language,
        voice_style=existing.voice_style,
        speaking_speed=existing.speaking_speed,
    )
    duplicated = await agent_service.create_agent(db, new_create)
    return duplicated


@router.post("/{agent_id}/start-calls")
async def start_calls(
    agent_id: str,
    request: StartCallsRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate outbound voice calls using the specified agent.
    Enqueues all numbers into BatchDialerService to run with strict concurrency control.
    """
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    if not agent.enabled:
        raise HTTPException(status_code=400, detail=f"Agent '{agent.name}' is disabled. Please enable it first.")

    concurrency = max(1, min(20, int(request.concurrency or agent.concurrency or 1)))

    queued_ids = []
    errors = []
    for raw_phone in request.phone_numbers:
        phone = raw_phone.strip()
        if not phone:
            continue
        try:
            norm_phone = validate_and_normalize_phone(phone)
        except Exception as e:
            errors.append(f"{phone}: {e}")
            continue

        call_id = str(uuid.uuid4())
        call = Call(
            id=call_id,
            tenant_id=agent.tenant_id,
            agent_id=agent.id,
            phone_number=norm_phone,
            status="queued",
            disposition="queued",
            direction="outbound",
            context_data={
                "provider": request.provider or getattr(agent, "telephony_provider", None) or "vobiz",
                "language": request.language or agent.default_language or "English",
                "questionnaire_id": request.questionnaire_id,
                "caller_id": getattr(agent, "telephony_from_number", None) or settings.VOBIZ_FROM_NUMBER or "+918065354620",
            },
        )
        db.add(call)
        queued_ids.append(call_id)

    if not queued_ids:
        err_msg = "; ".join(errors) if errors else "No valid phone numbers provided."
        raise HTTPException(status_code=400, detail=err_msg)

    await db.commit()

    # Hand off to background BatchDialerService
    from app.services.batch_dialer_service import batch_dialer_service
    await batch_dialer_service.enqueue_batch(
        agent_id=agent.id,
        call_ids=queued_ids,
        concurrency=concurrency,
    )

    return {
        "status": "QUEUED",
        "queued": len(queued_ids),
        "call_ids": queued_ids,
        "concurrency": concurrency,
        "message": f"Successfully queued {len(queued_ids)} call(s) with {concurrency}x concurrency. Dialing started in background.",
    }


@router.post("/{agent_id}/preview-batch")
async def preview_batch(
    agent_id: str,
    payload: Dict[str, Any],
):
    """
    Validate phone numbers in batch.
    """
    numbers = payload.get("phone_numbers", [])
    valid = []
    invalid = []
    for n in numbers:
        try:
            norm = validate_and_normalize_phone(str(n))
            valid.append(norm)
        except Exception:
            invalid.append(str(n))
    return {"total": len(numbers), "valid": valid, "invalid": invalid}


@router.get("/{agent_id}/summary")
async def get_agent_summary(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get summary stats for an agent.
    """
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Aggregate call counts
    stmt = select(Call.status, func.count(Call.id)).where(Call.agent_id == agent_id).group_by(Call.status)
    res = await db.execute(stmt)
    status_counts = dict(res.all())

    total = sum(status_counts.values())
    completed = status_counts.get("completed", 0)
    failed = status_counts.get("failed", 0) + status_counts.get("busy", 0) + status_counts.get("no_answer", 0)
    active = status_counts.get("in_progress", 0) + status_counts.get("ringing", 0) + status_counts.get("initiating", 0)

    # Real interest count from database
    int_stmt = select(func.count(Call.id)).where(
        Call.agent_id == agent_id,
        Call.disposition.ilike("%interest%"),
        ~Call.disposition.ilike("%not%")
    )
    int_res = await db.execute(int_stmt)
    interested_contacts = int_res.scalar() or 0

    return {
        "agent_id": agent.id,
        "name": agent.name,
        "description": agent.purpose,
        "is_enabled": agent.enabled,
        "default_language": "English" if "en" in (agent.primary_language or "") else "Hindi",
        "provider": agent.provider or "vobiz",
        "total_calls": total,
        "active_calls": active,
        "completed_calls": completed,
        "failed_calls": failed,
        "interested_contacts": interested_contacts,
        "created_at": agent.created_at.isoformat() if agent.created_at else "",
    }


@router.get("/{agent_id}/dashboard")
async def get_agent_dashboard(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get full telemetry dashboard for an agent.
    """
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Real aggregated counts from DB
    total_stmt = select(func.count(Call.id)).where(Call.agent_id == agent_id)
    total_calls_count = (await db.execute(total_stmt)).scalar() or 0

    status_stmt = select(Call.status, func.count(Call.id)).where(Call.agent_id == agent_id).group_by(Call.status)
    status_dict = dict((await db.execute(status_stmt)).all())

    completed_count = status_dict.get("completed", 0)
    failed_count = status_dict.get("failed", 0) + status_dict.get("busy", 0) + status_dict.get("no_answer", 0)
    active_count = status_dict.get("in_progress", 0) + status_dict.get("ringing", 0)
    queued_count = status_dict.get("initiating", 0) + status_dict.get("queued", 0)

    # Average duration
    dur_stmt = select(func.avg(Call.duration)).where(Call.agent_id == agent_id, Call.duration.isnot(None))
    avg_dur = (await db.execute(dur_stmt)).scalar() or 0.0

    # Calls for this agent
    stmt = select(Call).where(Call.agent_id == agent_id).order_by(Call.created_at.desc()).limit(20)
    res = await db.execute(stmt)
    calls = res.scalars().all()

    recent_mapped = []
    for c in calls[:10]:
        state = (c.status or "queued").upper()
        if state == "IN_PROGRESS":
            state = "CONNECTED"
        recent_mapped.append({
            "call_id": c.id,
            "agent_id": c.agent_id,
            "phone_number": c.phone_number,
            "state": state,
            "termination_reason": c.termination_reason,
            "duration": c.duration or 0.0,
            "provider": (c.context_data or {}).get("provider", "vobiz"),
            "created_at": c.created_at.isoformat(),
            "updated_at": (c.ended_at or c.created_at).isoformat(),
        })

    # Real interest counts from DB
    interested_stmt = select(func.count(Call.id)).where(
        Call.agent_id == agent_id,
        Call.disposition.ilike("%interest%"),
        ~Call.disposition.ilike("%not%")
    )
    interested_count = (await db.execute(interested_stmt)).scalar() or 0

    not_interested_stmt = select(func.count(Call.id)).where(
        Call.agent_id == agent_id,
        Call.disposition.ilike("%not%")
    )
    not_interested_count = (await db.execute(not_interested_stmt)).scalar() or 0

    uncertain_count = max(0, total_calls_count - (interested_count + not_interested_count))
    completion_rate = round((completed_count / total_calls_count * 100), 1) if total_calls_count > 0 else 0.0

    lang = agent.primary_language or "Hindi"
    lang_name = "Hindi" if "hi" in lang.lower() else ("English" if "en" in lang.lower() else "Marathi")

    return {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "total_calls": total_calls_count,
        "active_calls": active_count,
        "queued_calls": queued_count,
        "completed_calls": completed_count,
        "failed_calls": failed_count,
        "average_duration_seconds": round(float(avg_dur), 1),
        "questionnaire_completion_rate": completion_rate,
        "interested_count": interested_count,
        "not_interested_count": not_interested_count,
        "uncertain_count": uncertain_count,
        "language_distribution": {lang_name: total_calls_count},
        "recent_calls": recent_mapped,
    }
