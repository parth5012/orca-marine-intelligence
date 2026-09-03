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

# Normalize URL to asyncpg driver format if needed
if RAW_DATABASE_URL.startswith("postgresql://"):
    ASYNC_DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    ASYNC_DATABASE_URL = RAW_DATABASE_URL

# Create async engine for PostgreSQL + PostGIS
engine = create_async_engine(
    ASYNC_DATABASE_URL,
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