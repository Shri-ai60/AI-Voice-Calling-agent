from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes.agents import router as agents_router
from app.api.routes.businesses import router as businesses_router
from app.api.routes.calls import router as calls_router
from app.api.routes.campaigns import router as campaigns_router
from app.api.routes.contacts import router as contacts_router
from app.api.routes.followups import router as followups_router
from app.api.routes.general import router as general_router
from app.api.routes.invoices import router as invoices_router
from app.api.routes.calendar import router as calendar_router
from app.api.routes.leads import router as leads_router
from app.api.routes.questionnaires import router as questionnaires_router
from app.api.routes.reports import router as reports_router
from app.api.routes.stats import router as stats_router
from app.api.routes.telephony import router as telephony_router
from app.api.routes.vobiz_direct import router as vobiz_direct_router
from app.api.routes.voice import router as voice_router
from app.api.routes.webhooks import router as webhooks_router
from app.config import settings
from app.database import engine, init_db
from app.database_migrations import run_async_migrations
from app.services.dograh_service import DograhServiceException, dograh_service
from app.services.storage.s3 import storage_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("calling_agent_backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    try:
        await init_db()
        await run_async_migrations()
        from app.services.seed_service import seed_initial_data_if_needed
        await seed_initial_data_if_needed()
        logger.info("Database initialized, schema verified, and seed agents checked.")
    except Exception as e:
        logger.error(f"Database initialization warning: {e}")

    import platform
    if platform.system() == "Windows":
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)
            logger.info("Windows high-resolution multimedia timer (1ms) enabled.")
        except Exception as e:
            logger.warning(f"Could not enable Windows multimedia timer: {e}")

    logger.info("Backend service initialized.")

    # Automatic follow-up dispatcher: places customer-requested callback
    # calls when their scheduled time arrives (offline asyncio loop).
    dispatcher_task = None
    try:
        import asyncio as _asyncio

        from app.services.followup_dispatcher import run_dispatcher_forever

        dispatcher_task = _asyncio.create_task(run_dispatcher_forever())
    except Exception as e:
        logger.warning(f"Follow-up dispatcher not started: {e}")

    yield

    if dispatcher_task is not None:
        dispatcher_task.cancel()
    logger.info("Backend service shutting down.")


app = FastAPI(
    title="Calling Agent Backend",
    description="Enterprise voice AI backend connecting web application to Dograh voice engine and persistent storage",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS Configuration
origins = settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else [settings.CORS_ORIGINS]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DograhServiceException)
async def dograh_exception_handler(request: Request, exc: DograhServiceException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.error_code,
            "message": exc.message,
            "detail": exc.message,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        content = dict(exc.detail)
        if "detail" not in content and "message" in content:
            content["detail"] = content["message"]
        return JSONResponse(status_code=exc.status_code, content=content)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": "HTTP_ERROR",
            "message": str(exc.detail),
            "detail": str(exc.detail),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "INTERNAL_SERVER_ERROR", "message": "An internal server error occurred"},
    )


@app.get("/", tags=["system"])
async def root():
    return {
        "service": "Calling Agent Backend",
        "status": "online",
        "docs": "/docs",
        "health": "/health",
        "api": "/api",
    }


@app.get("/health", tags=["system"])
async def health_check():
    """
    Service health check endpoint reporting DB, Redis, Storage, Dograh, Voice AI Engine, and Telephony status.
    """
    # 1. Database check
    db_status = "healthy"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"degraded ({e})"

    # 2. Redis check (non-blocking fast check)
    redis_status = "offline"
    try:
        import redis
        r = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=0.3, socket_connect_timeout=0.3)
        if r.ping():
            redis_status = "healthy"
    except Exception:
        redis_status = "offline"

    # 3. MinIO / S3 check
    storage_status = "healthy" if storage_service._client else "offline"

    # 4. Voice AI Engine & Telephony Engine check
    is_sarvam = getattr(settings, "VOICE_ENGINE", "sarvam") == "sarvam"
    if is_sarvam:
        dograh_health = {"reachable": False, "status": "not_needed_sarvam_native"}
        voice_ai_status = {
            "status": "healthy",
            "engine": "sarvam_native",
            "stt": settings.SARVAM_STT_MODEL,
            "tts": settings.SARVAM_TTS_MODEL,
            "llm": settings.SARVAM_LLM_MODEL,
        }
    else:
        # Dograh check
        dograh_health = {"reachable": False, "status": "unavailable"}
        try:
            dograh_health = await dograh_service.check_health()
        except Exception:
            pass

        # Local Voice AI Engine check (Kokoro TTS on port 8002)
        voice_ai_status = {"status": "offline", "stt": "offline", "tts": "offline", "llm": "offline"}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=0.4) as client:
                resp = await client.get("http://127.0.0.1:8002/health")
                if resp.status_code == 200:
                    data = resp.json()
                    voice_ai_status = {
                        "status": "healthy",
                        "stt": data.get("stt", "ready"),
                        "tts": data.get("tts", "ready"),
                        "llm": data.get("llm_provider", "ready"),
                    }
        except Exception:
            pass

    # 6. Telephony carrier checks
    vobiz_configured = bool(settings.VOBIZ_AUTH_ID and settings.VOBIZ_AUTH_TOKEN)
    twilio_configured = bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN)

    return {
        "status": "ok",
        "service": "calling-agent-backend",
        "controller": "ok",
        "database": {
            "type": "sqlite" if "sqlite" in settings.DATABASE_URL.lower() else "postgresql",
            "status": db_status,
        },
        "redis": {
            "status": redis_status,
        },
        "storage": {
            "provider": "minio/s3",
            "bucket": settings.S3_BUCKET,
            "status": storage_status,
        },
        "dograh": {
            "healthy": dograh_health,
        },
        "voice_ai": voice_ai_status,
        "telephony": {
            "provider": "vobiz",
            "configured": vobiz_configured,
            "from_number": settings.VOBIZ_FROM_NUMBER or None,
            "vobiz": {
                "configured": vobiz_configured,
                "from_number": settings.VOBIZ_FROM_NUMBER or None,
                "status": "ready" if vobiz_configured else "unconfigured",
            },
            "twilio": {
                "configured": twilio_configured,
                "from_number": settings.TWILIO_PHONE_NUMBER or None,
                "status": "ready" if twilio_configured else "unconfigured",
            },
        },
    }



# Mount all API routers (both under /api and root to support all frontend client URL conventions)
routers_to_mount = [
    businesses_router,
    agents_router,
    calls_router,
    campaigns_router,
    contacts_router,
    leads_router,
    followups_router,
    reports_router,
    questionnaires_router,
    telephony_router,
    vobiz_direct_router,
    webhooks_router,
    stats_router,
    voice_router,
    invoices_router,
    calendar_router,
    general_router,
]

for r in routers_to_mount:
    app.include_router(r, prefix="/api/v1")
    app.include_router(r, prefix="/api")
    app.include_router(r)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=(settings.ENVIRONMENT == "development"),
        reload_dirs=["app"],
        reload_excludes=[".env", "*.env", "*.db", "*.sqlite", "*.log"],
    )
