"""
Verification script for ORCA SQLAlchemy Database Models.
Validates table creation DDL, GeoAlchemy2 types, and model constraints.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql
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

def test_models_ddl():
    print("Testing SQLAlchemy 2.0 DDL generation for PostGIS...")
    dialect = postgresql.dialect()

    models = [
        PFZZone,
        CoastalPort,
        EEZBoundary,
        MPABoundary,
        ChatSession,
        ChatMessage,
        IngestRun,
    ]

    for model in models:
        ddl = CreateTable(model.__table__).compile(dialect=dialect)
        print(f"\n[OK] Model '{model.__name__}' -> Table '{model.__tablename__}':")
        first_lines = "\n".join(str(ddl).strip().splitlines()[:4])
        print(first_lines)

    assert hasattr(ChatSession, "messages"), "ChatSession should have relationship to messages"
    assert hasattr(ChatMessage, "session"), "ChatMessage should have relationship to session"
    print("\n[OK] Relationships verified successfully!")
    print(f"\nTotal tables registered in Base.metadata: {len(Base.metadata.tables)}")
    for name in Base.metadata.tables:
        print(f" - {name}")

if __name__ == "__main__":
    test_models_ddl()