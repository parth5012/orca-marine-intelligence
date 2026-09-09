"""
Geofence Check Router

Owner: M-C (Backend API & Platform) & M-B (Data Extractors & Storage)
Module: backend/routers/geofence.py

Provides real-time maritime boundary validation and safety alerts against:
- Sovereign Exclusive Economic Zone (EEZ) boundaries
- Marine Protected Areas (MPAs) / Sanctuaries (WDPA)
- International Maritime Boundary Line (IMBL) buffer zones (2km / 5km)

Endpoints:
- GET /api/geofence/status  : Active sanctuaries, EEZ zones, and protection thresholds

Wayfinder T3 (map #92): /geofence/check (GET+POST) and /geofence/route
deleted per human grill decision — status endpoint only.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from backend.ingest.boundaries import (
    EEZ_CAUTION_KM,
    IMBL_BUFFER_KM,
    IMBL_CAUTION_KM,
    get_eez_boundaries,
    get_mpa_boundaries,
)

logger = logging.getLogger("orca.geofence")

router = APIRouter(tags=["geofence"])


# ---------------------------------------------------------------------------
# Pydantic Request & Response Models
# ---------------------------------------------------------------------------
class GeofenceStatusResponse(BaseModel):
    status: str = "ok"
    active_mpas: List[str]
    eez_zones: List[str]
    imbl_buffer_km: float = 2.0
    imbl_caution_threshold_km: float = 5.0
    eez_caution_threshold_km: float = 10.0
    count_protected_boundaries: int
    protected_boundaries_count: int
    boundary_counts: Dict[str, int]


# ---------------------------------------------------------------------------
# Router Endpoints
# ---------------------------------------------------------------------------
@router.get("/geofence/status", response_model=GeofenceStatusResponse)
async def get_geofence_status() -> GeofenceStatusResponse:
    """
    Returns active Marine Protected Areas (MPAs), sovereign EEZ zones,
    IMBL buffer protection rules, and total count of active boundary layers.
    """
    eez_features = get_eez_boundaries()
    mpa_features = get_mpa_boundaries()

    eez_zones = [
        f.get("properties", {}).get("boundary_name", f"EEZ Zone {idx}")
        for idx, f in enumerate(eez_features)
    ]
    active_mpas = [
        f.get("properties", {}).get("mpa_name")
        or f.get("properties", {}).get("name")
        or f"MPA {idx}"
        for idx, f in enumerate(mpa_features)
    ]

    total_count = len(eez_zones) + len(active_mpas)

    return GeofenceStatusResponse(
        status="ok",
        active_mpas=active_mpas,
        eez_zones=eez_zones,
        imbl_buffer_km=IMBL_BUFFER_KM,
        imbl_caution_threshold_km=IMBL_CAUTION_KM,
        eez_caution_threshold_km=EEZ_CAUTION_KM,
        count_protected_boundaries=total_count,
        protected_boundaries_count=total_count,
        boundary_counts={
            "eez": len(eez_zones),
            "mpa": len(active_mpas),
            "total": total_count,
        },
    )
