"""
Officer Command & Surveillance Overview Router

Owner: M-C (Backend API & Platform) — GET /api/officer/overview
Module: backend/routers/officer.py

Provides restricted maritime command center metrics for coastal officers,
enforcement authorities, and maritime researchers.
Enforces role-based access control (RBAC).
"""

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("orca.officer")

router = APIRouter(prefix="/officer", tags=["officer"])


class OfficerOverviewResponse(BaseModel):
    active_vessels_monitored: int
    eez_patrol_active: int
    distress_alerts_open: int
    incois_bulletins_active: int
    fleet_compliance_pct: float
    border_alerts_24h: int
    critical_weather_zones: int
    system_health: str


@router.get("/overview", response_model=OfficerOverviewResponse)
async def get_officer_overview(
    x_user_role: Optional[str] = Header(None, alias="X-User-Role", description="User role (official/public)"),
    role: Optional[str] = Query(None, description="Optional fallback role query param"),
) -> Dict[str, Any]:
    """
    Return command-level maritime operations summary.
    Restricted to users with 'official' role.
    """
    effective_role = (x_user_role or role or "").strip().lower()

    if effective_role != "official" and effective_role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Access restricted: Official maritime authority credentials required.",
        )

    return {
        "active_vessels_monitored": 142,
        "eez_patrol_active": 6,
        "distress_alerts_open": 0,
        "incois_bulletins_active": 14,
        "fleet_compliance_pct": 98.5,
        "border_alerts_24h": 0,
        "critical_weather_zones": 1,
        "system_health": "optimal",
    }
