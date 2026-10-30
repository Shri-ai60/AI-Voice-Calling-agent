from typing import AsyncGenerator
from urllib.parse import quote_plus, unquote
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy import event

from app.config import settings


def sanitize_db_url(url: str) -> str:
    """
    Ensures special characters like '@' in database passwords are URL-encoded
    so asyncpg/SQLAlchemy parses credentials correctly.
    """
    import os
    if os.environ.get("IN_DOCKER") == "true" or os.path.exists("/.dockerenv"):
        if "@localhost:" in url:
            url = url.replace("@localhost:", "@host.docker.internal:")
        elif "@127.0.0.1:" in url:
            url = url.replace("@127.0.0.1:", "@host.docker.internal:")

    if url.startswith("sqlite"):
        import shutil
        from app.config import DATABASE_DIR, PROJECT_ROOT
        db_file = DATABASE_DIR / "calling_agent.db"
        # Auto-migrate legacy DB file if present and target doesn't exist yet
        legacy_db = PROJECT_ROOT / "backend" / "calling_agent.db"
        root_legacy_db = PROJECT_ROOT / "calling_agent.db"
        if not db_file.exists():
            if legacy_db.exists() and legacy_db.stat().st_size > 0:
                shutil.copy2(legacy_db, db_file)
            elif root_legacy_db.exists() and root_legacy_db.stat().st_size > 0:
                shutil.copy2(root_legacy_db, db_file)
        if "///./" in url or "calling_agent.db" in url:
            return f"sqlite+aiosqlite:///{db_file.resolve().as_posix()}"
        return url

    if not (url.startswith("postgresql") or url.startswith("postgres")):
        return url
    if "://" not in url or "@" not in url:
        return url
    try:
        scheme, rest = url.split("://", 1)
        creds_part, host_part = rest.rsplit("@", 1)
        if ":" in creds_part:
            user, pwd = creds_part.split(":", 1)
            safe_pwd = quote_plus(unquote(pwd))
            return f"{scheme}://{user}:{safe_pwd}@{host_part}"
    except Exception:
        pass
    return url


# Build engine kwargs based on DB dialect
_raw_db_url = settings.DATABASE_URL
_db_url = sanitize_db_url(_raw_db_url)

connect_args = {}
engine_kwargs = {
    "echo": (settings.ENVIRONMENT == "debug"),
}

if _db_url.startswith("sqlite"):
    # SQLite: check_same_thread not needed with async, 30s timeout to prevent locking
    connect_args = {
        "check_same_thread": False,
        "timeout": 30.0,
    }
    engine_kwargs["connect_args"] = connect_args
elif _db_url.startswith("postgresql"):
    # PostgreSQL: configure connection pool
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300

engine = create_async_engine(_db_url, **engine_kwargs)

if _db_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    # Import all models so they are registered with Base.metadata
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
