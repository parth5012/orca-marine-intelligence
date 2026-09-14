"""
Asynchronous Database Engine and Session Generator
Owner: M-B (Data Extractors & Storage)
Module: backend/db/session.py

Manages asyncpg connection pool, session lifecycle, and table initialization.
"""

import os
import logging
from collections.abc import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.db.models import Base

logger = logging.getLogger(__name__)

# Ensure we use the asyncpg driver
RAW_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://orca:orca@localhost:5432/orca_marine"
)


def _normalize_async_url(raw: str) -> tuple[str, dict]:
    """Strip libpq-only query params (sslmode, channel_binding) that the
    asyncpg SQLAlchemy driver rejects as connect() kwargs, and translate
    sslmode=require into connect_args={'ssl': True} for Neon/Upstash TLS.
    """
    from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

    connect_args: dict = {}
    try:
        parts = urlparse(raw)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)  # asyncpg has no such kwarg
        stripped = urlunparse(parts._replace(query=urlencode(query)))
        if sslmode in ("require", "prefer", "allow"):
            connect_args["ssl"] = True
    except Exception:
        stripped = raw
    if stripped.startswith("postgresql://"):
        stripped = stripped.replace("postgresql://", "postgresql+asyncpg://", 1)
    return stripped, connect_args


# Normalize URL to asyncpg driver format if needed
ASYNC_DATABASE_URL, _CONNECT_ARGS = _normalize_async_url(RAW_DATABASE_URL)

# Create async engine for PostgreSQL + PostGIS
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    connect_args=_CONNECT_ARGS,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async database session per request.
    Automatically closes session on completion.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """
    Initialize database:
    1. Enables the PostGIS extension if not already present.
    2. Creates all tables defined in Base.metadata.
    """
    logger.info("Initializing database schema...")
    async with engine.begin() as conn:
        # Enable PostGIS extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema initialized successfully.")