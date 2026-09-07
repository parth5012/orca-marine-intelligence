"""
Coastal Port Pydantic Schemas
Owner: M-B / M-C
Module: backend/schemas/ports.py

Validation and serialization schemas for Coastal Ports & Landing Centers.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class CoastalPortBase(BaseModel):
    """Shared attributes for CoastalPort."""
    name: str = Field(..., description="Standard harbor/port name, e.g. Kochi")
    state: str = Field(..., description="Coastal state, e.g. Kerala")
    aliases: Dict[str, Any] = Field(
        default_factory=dict,
        description="Regional language and phonetic aliases, e.g. {'ml': ['കൊച്ചി'], 'roman': ['cochin']}"
    )
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude (WGS84)")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude (WGS84)")


class CoastalPortCreate(CoastalPortBase):
    """Schema for creating a new CoastalPort."""
    pass


class CoastalPortUpdate(BaseModel):
    """Schema for updating an existing CoastalPort."""
    name: Optional[str] = None
    state: Optional[str] = None
    aliases: Optional[Dict[str, Any]] = None
    lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    lon: Optional[float] = Field(None, ge=-180.0, le=180.0)


class CoastalPortRead(CoastalPortBase):
    """Schema for reading a CoastalPort from DB/Cache."""
    model_config = ConfigDict(from_attributes=True)

    id: int


class CoastalPortFilter(BaseModel):
    """Filter criteria for CoastalPort queries."""
    state: Optional[str] = None
    search: Optional[str] = None
