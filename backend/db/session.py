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


async def seed_initial_pfz_if_empty(force: bool = False) -> int:
    """
    Ensure the pfz_zones table has records for today.
    If the table is empty OR today's valid_date has 0 rows (or force=True),
    seeds it from data/pfz-today.geojson so that find_pfz_near works
    immediately without waiting for daily cron ingestion.
    """
    try:
        from backend.db.models import PFZZone
        from backend.db.postgis import upsert_pfz_features
        from backend.agents.subagents.fish_finder import _load_geojson_features
        from datetime import date
        from sqlalchemy import func, select

        today = date.today()
        if not force:
            async with AsyncSessionLocal() as session:
                today_q = select(func.count(PFZZone.id)).where(PFZZone.valid_date == today)
                today_res = await session.execute(today_q)
                today_count = today_res.scalar() or 0
                if today_count > 0:
                    return 0

        features = _load_geojson_features()
        if not features:
            logger.info("seed_initial_pfz_if_empty: no local GeoJSON features found to seed")
            return 0

        upserted = await upsert_pfz_features(features, valid_date=today)
        logger.info("seed_initial_pfz_if_empty: seeded %d PFZ zones into PostGIS database for %s", upserted, today)
        return upserted
    except Exception as exc:
        logger.warning("seed_initial_pfz_if_empty notice: %s", exc)
        return 0


async def _boundary_counts() -> tuple[int, int]:
    """(eez_rows, mpa_rows) currently in PostGIS. (0, 0) means "needs seed"."""
    from sqlalchemy import func, select

    from backend.db.models import EEZBoundary, MPABoundary

    async with AsyncSessionLocal() as session:
        eez = (await session.execute(select(func.count(EEZBoundary.id)))).scalar() or 0
        mpa = (await session.execute(select(func.count(MPABoundary.id)))).scalar() or 0
    return int(eez), int(mpa)


async def seed_boundaries_if_empty() -> int:
    """
    Seed eez_boundaries / mpa_boundaries from data/*.geojson when empty.

    An unseeded eez_boundaries makes PostGIS report EVERY point as
    "outside Indian EEZ", which the combiner turns into a false
    all-zones-unsafe DO NOT SAIL advisory — and the chat danger veto then
    wipes the zone cards (and their Show-on-Map buttons) mid-stream.
    Mirrors seed_initial_pfz_if_empty. Returns features ingested (0 if
    already populated).
    """
    from backend.ingest.boundaries import ingest_boundaries

    eez_n, mpa_n = await _boundary_counts()
    if eez_n > 0 and mpa_n > 0:
        logger.info("seed_boundaries_if_empty: already populated (%d EEZ, %d MPA)", eez_n, mpa_n)
        return 0
    res = await ingest_boundaries()
    ingested = int(res.get("eez_count", 0)) + int(res.get("mpa_count", 0))
    logger.info(
        "seed_boundaries_if_empty: ingested %d EEZ + %d MPA (db_synced=%s)",
        int(res.get("eez_count", 0)),
        int(res.get("mpa_count", 0)),
        res.get("db_synced"),
    )
    return ingested


async def init_db():
    """
    Initialize database:
    1. Enables PostGIS extension if not present.
    2. Creates all tables defined in Base.metadata.
    3. Seeds initial PFZ data if table is empty.
    4. Seeds EEZ/MPA boundary tables if empty.
    """
    logger.info("Initializing database schema...")
    async with engine.begin() as conn:
        # Enable PostGIS extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema initialized successfully.")

    try:
        await seed_initial_pfz_if_empty()
    except Exception as seed_err:
        logger.warning("Post-init PFZ seeding notice: %s", seed_err)

    try:
        await seed_boundaries_if_empty()
    except Exception as seed_err:
        logger.warning("Post-init boundary seeding notice: %s", seed_err)