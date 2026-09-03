"""
ORCA Marine Intelligence — PostGIS Database Models
Owner: M-B (Data Extractors & Storage)
Module: backend/db/models.py

SQLAlchemy 2.0 + GeoAlchemy2 models for spatial marine data,
coastal ports, geofencing boundaries, and multi-turn chat sessions.
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    String, Integer, Float, Boolean, Text, Date, DateTime,
    ForeignKey, Index, func
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from geoalchemy2 import Geometry


# --- Declarative Base ---
class Base(DeclarativeBase):
    pass


# ==============================================================================
# 1. Potential Fishing Zones (PFZ) — Daily Fishing Spots from INCOIS
# ==============================================================================
class PFZZone(Base):
    """
    Stores daily recommended fishing spots published by INCOIS.
    Each spot is a Point on Earth (lat/lon) with depth, bearing, and distance.
    """
    __tablename__ = "pfz_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zone_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    # Reference Landing Center & Sector
    place: Mapped[str] = mapped_column(String(256), index=True, nullable=False)   # e.g. "Pallithottam"
    sector: Mapped[str] = mapped_column(String(32), index=True, nullable=False)    # e.g. "SEC005"
    sector_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False) # e.g. "KERALA"

    # Nautical Navigation Values
    direction: Mapped[Optional[str]] = mapped_column(String(16))   # e.g. "SW", "NE"
    bearing: Mapped[Optional[int]] = mapped_column(Integer)        # e.g. 232 degrees
    depth_range: Mapped[Optional[str]] = mapped_column(String(32)) # e.g. "55-60 m"
    distance_km: Mapped[Optional[float]] = mapped_column(Float)    # e.g. 14.2 km offshore

    # Decimal Coordinates (WGS84)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    # Spatial Point Geometry (SRID 4326) with automatic GiST index
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False
    )

    # Metadata & Auditing
    intensity: Mapped[str] = mapped_column(String(32), default="medium")  # high / medium / low
    source: Mapped[str] = mapped_column(String(64), default="incois_textdata")
    valid_date: Mapped[date] = mapped_column(Date, default=func.current_date(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<PFZZone {self.zone_id}: {self.place} ({self.lat}, {self.lon})>"


# ==============================================================================
# 2. Coastal Ports & Landing Centers Registry
# ==============================================================================
class CoastalPort(Base):
    """
    Registry of major coastal fishing harbors and landing centers across India's 9 maritime states.
    Stores regional aliases so ORCA recognizes port names in any language or Romanized spelling.
    """
    __tablename__ = "coastal_ports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False) # e.g. "Kochi"
    state: Mapped[str] = mapped_column(String(64), index=True, nullable=False)              # e.g. "Kerala"

    # Regional aliases (e.g. {"ml": ["കൊച്ചി", "മുനമ്പം"], "roman": ["kochi", "cochin"]})
    aliases: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    # Spatial Point Geometry of harbor entrance
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<CoastalPort {self.name}, {self.state}>"


# ==============================================================================
# 3. National Borders & Safety Zones (Geofencing)
# ==============================================================================
class EEZBoundary(Base):
    """
    Stores India's Exclusive Economic Zone (EEZ) & International Maritime Boundary Lines.
    Used by DangerAgent to check for international border proximity and unauthorized crossing.
    """
    __tablename__ = "eez_boundaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country: Mapped[str] = mapped_column(String(64), default="India", index=True)
    boundary_name: Mapped[str] = mapped_column(String(128), nullable=False) # e.g. "India EEZ"
    boundary_type: Mapped[str] = mapped_column(String(32), default="EEZ")   # "EEZ" or "IMBL"

    # MultiPolygon boundary shape
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<EEZBoundary {self.boundary_name} ({self.country})>"


class MPABoundary(Base):
    """
    Stores Marine Protected Areas (National Parks / Sanctuaries).
    Fishing inside these boundaries is legally prohibited.
    """
    __tablename__ = "mpa_boundaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mpa_name: Mapped[str] = mapped_column(String(128), nullable=False) # e.g. "Gulf of Mannar Marine National Park"
    state: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    restriction_level: Mapped[str] = mapped_column(String(32), default="no-take")

    # Shape of the protected park
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<MPABoundary {self.mpa_name}>"


# ==============================================================================
# 4. Multi-Turn Chat Memory & Language Tracking
# ==============================================================================
class ChatSession(Base):
    """
    Maintains user conversation sessions, boat position, and language preference.
    Allows fishermen to ask follow-up questions without repeating their location or language.
    """
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    preferred_language: Mapped[str] = mapped_column(String(8), default="en") # e.g. "ml", "ta", "hi"

    # Last known GPS location of the boat / user
    last_lat: Mapped[Optional[float]] = mapped_column(Float)
    last_lon: Mapped[Optional[float]] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationship to conversation messages
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )

    def __repr__(self) -> str:
        return f"<ChatSession {self.session_id} (lang: {self.preferred_language})>"


class ChatMessage(Base):
    """
    Stores individual queries and advisory responses in a conversation.
    """
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), index=True, nullable=False
    )

    sender: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" or "orca"
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Language identification tracking
    detected_language: Mapped[Optional[str]] = mapped_column(String(8))
    detected_script: Mapped[Optional[str]] = mapped_column(String(16))

    # Stores the cards, map coordinates, and safety badges
    advisory_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage {self.id} from {self.sender} in {self.session_id}>"


# ==============================================================================
# 5. Ingest Audit Log (INCOIS 11:30 AM Daily Runs & Satellite Data)
# ==============================================================================
class IngestRun(Base):
    """
    Tracks daily automated data downloads from INCOIS and satellites.
    """
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False) # e.g. "incois_textdata", "copernicus"
    status: Mapped[str] = mapped_column(String(32), nullable=False) # "success" / "failed" / "partial"
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<IngestRun {self.id}: {self.source} - {self.status} ({self.feature_count} features)>"