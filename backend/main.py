"""
ORCA Agentic Marine Intelligence — FastAPI Application Entry Point

Owner: M-C (Backend API & Platform) — FastAPI app + CORS
Module: backend/main.py

This is the main FastAPI application that serves the ORCA backend API.
It configures CORS middleware, mounts all routers, manages lifecycle, and starts the server.

Routers:
    - /api/chat     → Chat endpoint for ORCA brain (chat.py)
    - /api/pfz      → PFZ data proxy (pfz.py)
    - /api/weather  → Weather data endpoint (weather.py)
    - /api/geofence → Geofence check endpoint (geofence.py)
    - /api/tiles    → Vector tile server (tiles.py)

Usage:
    uvicorn backend.main:app --reload --port 8000
"""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict

from dotenv import load_dotenv

# Automatically load environment variables from .env (root, backend, or current working dir)
_base_dir = Path(__file__).resolve().parent
_root_dir = _base_dir.parent
for _env_file in (_root_dir / ".env", _base_dir / ".env", Path(".env")):
    if _env_file.is_file():
        load_dotenv(dotenv_path=_env_file, override=False)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from backend.routers import chat, geofence, officer, pfz, status, tiles, weather
except ImportError:
    from routers import chat, geofence, officer, pfz, status, tiles, weather

try:
    from backend.core.logging import get_logger, setup_logging
    from backend.core.middleware import RequestLoggingMiddleware
except ImportError:
    from core.logging import get_logger, setup_logging
    from core.middleware import RequestLoggingMiddleware

logger = get_logger("orca.api")

DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000,https://cron-system.vercel.app"

_start_time: float = time.time()


async def check_database() -> str:
    """Verify database connection (PostGIS/SQLite via session or connection helper)."""
    # Check backend/db/connection.py if present
    try:
        import backend.db.connection as conn_mod
        if hasattr(conn_mod, "check_connection"):
            res = conn_mod.check_connection()
            if asyncio.iscoroutine(res):
                res = await res
            return "connected" if res else "disconnected"
    except ImportError:
        pass
    except Exception as e:
        logger.debug("backend.db.connection check error: %s", e)

    # Check backend/db/session.py engine
    try:
        from backend.db.session import engine
        from sqlalchemy import text

        async def _ping():
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        # Neon pooler cold start (TLS + wake) can take 2-5s; allow headroom
        await asyncio.wait_for(_ping(), timeout=8.0)
        return "connected"
    except Exception as e:
        logger.debug("Database ping error: %s", e)
        return "disconnected"


async def check_redis() -> str:
    """Verify Redis pool readiness."""
    try:
        from backend.db import redis as r_mod
        client = getattr(r_mod, "_redis_client", None)
        if client is not None:
            await asyncio.wait_for(client.ping(), timeout=1.0)
            return "connected"
        return "disconnected"
    except Exception as e:
        logger.debug("Redis ping error: %s", e)
        return "disconnected"

def get_telemetry_status() -> Dict[str, Any]:
    """Inspect and report LangSmith tracing configuration readiness."""
    tracing_v2 = os.getenv("LANGCHAIN_TRACING_V2", "").strip().lower() in ("true", "1", "yes")
    raw_key = os.getenv("LANGCHAIN_API_KEY", "").strip()
    api_key_configured = bool(raw_key and not raw_key.lower().startswith("your_"))
    project = os.getenv("LANGCHAIN_PROJECT", "orca-marine-intelligence").strip() or "orca-marine-intelligence"
    endpoint = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com").strip() or "https://api.smith.langchain.com"

    return {
        "langsmith": {
            "enabled": tracing_v2 and api_key_configured,
            "tracing_v2": tracing_v2,
            "api_key_configured": api_key_configured,
            "project": project,
            "endpoint": endpoint,
        }
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Async lifespan handler verifying database connection,
    Redis pool readiness, environment variable configuration.
    Gracefully handles disconnected states without crashing.
    """
    global _start_time
    _start_time = time.time()
    setup_logging()
    logger.info("Starting ORCA Marine Intelligence API...")

    # Log environment variable configuration
    db_url = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL")
    allowed_origins = os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    data_source = os.getenv("ORCA_DATA_SOURCE", "mock")
    # Ensure placeholder or missing key does not trigger background 401 attempts
    raw_key = os.getenv("LANGCHAIN_API_KEY", "").strip()
    if not raw_key or raw_key.lower().startswith("your_"):
        if os.getenv("LANGCHAIN_TRACING_V2", "").strip().lower() in ("true", "1", "yes"):
            logger.info("LangSmith: Placeholder or missing API key detected; setting LANGCHAIN_TRACING_V2=false")
            os.environ["LANGCHAIN_TRACING_V2"] = "false"

    telemetry = get_telemetry_status()
    logger.info(
        "Configured environment: ORCA_DATA_SOURCE=%s, DATABASE_URL=%s, REDIS_URL=%s, ALLOWED_ORIGINS=%s, LANGSMITH_ENABLED=%s",
        data_source,
        "set" if db_url else "default/unset",
        "set" if redis_url else "default/unset",
        allowed_origins,
        telemetry["langsmith"]["enabled"],
    )

    # Verify database connection (gracefully handle disconnected state)
    try:
        db_status = await check_database()
        if db_status == "connected":
            logger.info("Database connection verified (PostGIS ready).")
            try:
                from backend.db.session import init_db
                await init_db()
            except Exception as e:
                logger.warning("Database schema initialization notice: %s", e)
        else:
            logger.warning("Database unavailable; running in degraded/mock mode.")
    except Exception as e:
        logger.warning("Database check failed (%s); running in degraded/mock mode.", e)

    # Verify Redis pool readiness (gracefully handle disconnected state)
    try:
        from backend.db.redis import init_redis
        redis_client = await init_redis()
        if redis_client is not None:
            logger.info("Redis cache pool verified and ready.")
        else:
            logger.warning("Redis unavailable; using in-memory cache fallback.")
    except Exception as e:
        logger.warning("Redis initialization error (%s); using in-memory cache fallback.", e)

    yield

    # Shutdown: gracefully release connections
    logger.info("Shutting down ORCA Marine Intelligence API...")
    try:
        import backend.db.redis as r_mod
        client = getattr(r_mod, "_redis_client", None)
        if client is not None:
            await client.close()
    except Exception:
        pass

    try:
        from backend.db.session import engine
        await engine.dispose()
    except Exception:
        pass


app = FastAPI(
    title="ORCA Agentic Marine Intelligence",
    description="Multi-agent marine advisory system for Indian fishermen (SIH26176)",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS from environment
allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
allowed_origins = [origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()]
allow_credentials = True
if "*" in allowed_origins:
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

# Mount live routers under /api
app.include_router(chat.router, prefix="/api")
app.include_router(pfz.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(geofence.router, prefix="/api")
app.include_router(tiles.router, prefix="/api")
app.include_router(officer.router, prefix="/api")
app.include_router(status.router)


@app.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint returning service identity and status."""
    return {
        "service": "orca-marine-intelligence",
        "status": "ok",
        "version": app.version,
    }


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Enhanced health check endpoint for monitoring and deployment readiness.
    Returns status, database, redis, data_source, version, uptime, and service name.
    """
    db_status = await check_database()
    redis_status = await check_redis()
    uptime_sec = round(time.time() - _start_time, 2)

    try:
        from backend.ingest.mock_fetchers import get_data_source
        data_source = get_data_source()
    except Exception:
        data_source = os.getenv("ORCA_DATA_SOURCE", "mock")

    is_ready = (db_status == "connected" and redis_status == "connected")
    overall_status = "ok" if is_ready else "degraded"

    return {
        "status": overall_status,
        "service": "orca-marine-intelligence",
        "version": app.version,
        "uptime": uptime_sec,
        "database": db_status,
        "redis": redis_status,
        "data_source": data_source,
        "telemetry": get_telemetry_status(),
    }
