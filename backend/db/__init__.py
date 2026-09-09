"""
ORCA Marine Intelligence — Database Package
Owner: M-B (Data Extractors & Storage)
Module: backend/db/__init__.py
"""

from backend.db.models import (
    Base,
    PFZZone,
    CoastalPort,
    EEZBoundary,
    MPABoundary,
    ChatSession,
    ChatMessage,
    IngestRun,
)
from backend.db.session import (
    engine,
    AsyncSessionLocal,
    get_db,
    init_db,
)
from backend.db.postgis import (
    ping_postgis,
    is_db_degraded,
    set_db_degraded,
    reset_circuit_breaker,
)

__all__ = [
    "Base",
    "PFZZone",
    "CoastalPort",
    "EEZBoundary",
    "MPABoundary",
    "ChatSession",
    "ChatMessage",
    "IngestRun",
    "engine",
    "AsyncSessionLocal",
    "get_db",
    "init_db",
    "ping_postgis",
    "is_db_degraded",
    "set_db_degraded",
    "reset_circuit_breaker",
]