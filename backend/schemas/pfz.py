"""
PFZ Zone Pydantic Schemas
Owner: M-B / M-C
Module: backend/schemas/pfz.py

Validation and serialization schemas for Potential Fishing Zones (PFZ).
"""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class PFZZoneBase(BaseModel):
    """Shared attributes for PFZZone."""
    place: str = Field(..., description="Landing center / place name, e.g. Pallithottam")
    sector: str = Field(..., description="INCOIS sector code, e.g. SEC005")
    sector_name: str = Field(..., description="State / Sector name, e.g. KERALA")
    direction: Optional[str] = Field(None, description="Compass direction e.g. SW, NE")
    bearing: Optional[int] = Field(None, ge=0, le=360, description="Bearing angle in degrees")
    depth_range: Optional[str] = Field(None, description="Depth range e.g. 55-60 m")
    distance_km: Optional[float] = Field(None, ge=0.0, description="Offshore distance in km")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude (WGS84)")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude (WGS84)")
    intensity: str = Field("medium", description="Intensity level: high, medium, low")
    source: str = Field("incois_textdata", description="Data source identifier")
    valid_date: Optional[date] = Field(default_factory=date.today, description="Validity date")


class PFZZoneCreate(PFZZoneBase):
    """Schema for creating a new PFZZone."""
    zone_id: str = Field(..., description="Unique zone identifier")


class PFZZoneUpdate(BaseModel):
    """Schema for updating an existing PFZZone. All fields optional."""
    place: Optional[str] = None
    sector: Optional[str] = None
    sector_name: Optional[str] = None
    direction: Optional[str] = None
    bearing: Optional[int] = Field(None, ge=0, le=360)
    depth_range: Optional[str] = None
    distance_km: Optional[float] = Field(None, ge=0.0)
    lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    lon: Optional[float] = Field(None, ge=-180.0, le=180.0)
    intensity: Optional[str] = None
    source: Optional[str] = None
    valid_date: Optional[date] = None


class PFZZoneRead(PFZZoneBase):
    """Schema for reading a PFZZone from DB/Cache."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    zone_id: str
    created_at: Optional[datetime] = None


class PFZZoneFilter(BaseModel):
    """Query filter parameters for PFZ zones."""
    sector: Optional[str] = None
    place: Optional[str] = None
    valid_date: Optional[date] = None
    min_distance_km: Optional[float] = None
    max_distance_km: Optional[float] = None
