"""
Officer Command & Surveillance Overview Router

Owner: M-C (Backend API & Platform) — GET /api/officer/overview
Module: backend/routers/officer.py

Provides restricted maritime command center metrics for coastal officers,
enforcement authorities, and maritime researchers.
Enforces role-based access control (RBAC).

Map #170 T2 additions (issue #172): manual departure register, GO/HOLD
overrides, and advisory broadcasts per port, gated by shared officer
tokens (X-Officer-Token: PORT_TOKEN = port role, WATCH_TOKEN = watch
role). Runtime store is in-memory (works without Postgres so tests and
degraded mode stay green); backend/db/schema.sql §7 + models.py §6
define the Postgres tables for prod. No PostGIS needed (lat/lon floats).
Local-first register: identical behaviour under ORCA_DATA_SOURCE live/mock.
"""

import hmac
import logging
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from backend.core.ports import get_port
except ImportError:  # pragma: no cover - alternate import root
    from core.ports import get_port

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


# ---------------------------------------------------------------------------
# T2 officer register: token auth + port validation + overdue (pure helpers)
# ---------------------------------------------------------------------------

ROLE_PORT = "port"
ROLE_WATCH = "watch"
DEFAULT_PORT_TOKEN = "test-port-token"
DEFAULT_WATCH_TOKEN = "test-watch-token"

# In-memory runtime stores (module-level; Postgres schema in prod).
# Rows never carry computed fields (overdue_* added at read time only).
_departures: List[Dict[str, Any]] = []
_overrides: List[Dict[str, Any]] = []
_broadcasts: List[Dict[str, Any]] = []


def get_officer_tokens() -> Tuple[str, str]:
    """Read shared officer tokens from env (per-call so tests can override)."""
    port_token = os.getenv("PORT_TOKEN", DEFAULT_PORT_TOKEN)
    watch_token = os.getenv("WATCH_TOKEN", DEFAULT_WATCH_TOKEN)
    if port_token in (DEFAULT_PORT_TOKEN,) or watch_token in (DEFAULT_WATCH_TOKEN,):
        logger.warning("Officer tokens using dev defaults; set PORT_TOKEN/WATCH_TOKEN in prod.")
    return port_token, watch_token


def resolve_officer_role(token: Optional[str], port_token: str, watch_token: str) -> Optional[str]:
    """Map a raw header token to port/watch role, else None. Pure."""
    candidate = (token or "").strip()
    if candidate and hmac.compare_digest(candidate, port_token):
        return ROLE_PORT
    if candidate and hmac.compare_digest(candidate, watch_token):
        return ROLE_WATCH
    return None


def require_officer_role(token: Optional[str]) -> str:
    """Return port/watch role for a valid token, else 401. Dependencies explicit."""
    port_token, watch_token = get_officer_tokens()
    role = resolve_officer_role(token, port_token, watch_token)
    if role is None:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Officer-Token.")
    return role


def validate_port_id(port_id: str) -> Dict[str, Any]:
    """Return the port entry for a known id, else 400. Explicit dep: ports registry."""
    port = get_port(port_id or "")
    if port is None:
        raise HTTPException(status_code=400, detail=f"Unknown port_id: {port_id}.")
    return port


def compute_overdue(expected_in: datetime, now: datetime) -> Tuple[int, str]:
    """Overdue minutes + band from expected return time. Pure, no storage."""
    exp = expected_in if expected_in.tzinfo else expected_in.replace(tzinfo=timezone.utc)
    ref = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    mins = max(0, int((ref - exp).total_seconds() // 60))
    band = "red" if mins > 360 else ("amber" if mins > 120 else "none")
    return mins, band


def with_overdue(row: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Return a copy of a departure row plus computed overdue fields. Pure."""
    expected_in = row["expected_in"]
    if isinstance(expected_in, str):
        expected_in = datetime.fromisoformat(expected_in)
    mins, band = compute_overdue(expected_in, now)
    return {**row, "overdue_mins": mins, "overdue_status": band}


def clear_officer_stores() -> None:
    """Reset in-memory stores (tests + local dev only)."""
    _departures.clear()
    _overrides.clear()
    _broadcasts.clear()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_scoped_port(role: str, port_id: Optional[str]) -> str:
    """Port role must scope every read to one ?port_id=; watch may omit (read-all)."""
    if role == ROLE_PORT and not (port_id or "").strip():
        raise HTTPException(status_code=400, detail="port_id query param required for port role.")
    if port_id:
        validate_port_id(port_id)
    return (port_id or "").strip()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DepartureCreate(BaseModel):
    port_id: str
    boat_id: str
    crew: int = Field(ge=1)
    time_out: datetime
    expected_in: datetime
    dest_lat: float
    dest_lon: float
    dest_zone: Optional[str] = None
    status: str = "at_sea"


class OverrideCreate(BaseModel):
    port_id: str
    date: date
    decision: Literal["GO", "HOLD"]
    reason: str


class BroadcastCreate(BaseModel):
    port_id: str
    text_en: str
    text_local: Optional[str] = None
    lang: str = "en"


# ---------------------------------------------------------------------------
# Departures
# ---------------------------------------------------------------------------

@router.post("/departures")
async def create_departure(
    body: DepartureCreate,
    x_officer_token: Optional[str] = Header(None, alias="X-Officer-Token"),
) -> Dict[str, Any]:
    """Register a boat departure for a port (port + watch roles)."""
    require_officer_role(x_officer_token)
    validate_port_id(body.port_id)
    row = {
        "id": str(uuid.uuid4()),
        "port_id": body.port_id.strip().lower(),
        "boat_id": body.boat_id,
        "crew": body.crew,
        "time_out": body.time_out.isoformat(),
        "expected_in": body.expected_in.isoformat(),
        "dest_lat": body.dest_lat,
        "dest_lon": body.dest_lon,
        "dest_zone": body.dest_zone,
        "status": body.status or "at_sea",
        "created_at": _now_iso(),
    }
    _departures.append(row)
    return with_overdue(row, datetime.now(timezone.utc))


@router.get("/departures")
async def list_departures(
    port_id: Optional[str] = Query(None),
    x_officer_token: Optional[str] = Header(None, alias="X-Officer-Token"),
) -> Dict[str, Any]:
    """List departures; port role scoped to ?port_id=, watch reads all."""
    role = require_officer_role(x_officer_token)
    scoped = _require_scoped_port(role, port_id)
    now = datetime.now(timezone.utc)
    rows = [r for r in _departures if not scoped or r["port_id"] == scoped.lower()]
    return {"count": len(rows), "departures": [with_overdue(r, now) for r in rows]}


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

@router.post("/overrides")
async def create_override(
    body: OverrideCreate,
    x_officer_token: Optional[str] = Header(None, alias="X-Officer-Token"),
) -> Dict[str, Any]:
    """Record a GO/HOLD override; by_role derived from the token (never client)."""
    role = require_officer_role(x_officer_token)
    validate_port_id(body.port_id)
    row = {
        "id": str(uuid.uuid4()),
        "port_id": body.port_id.strip().lower(),
        "date": body.date.isoformat(),
        "decision": body.decision,
        "reason": body.reason,
        "by_role": role,
        "created_at": _now_iso(),
    }
    _overrides.append(row)
    return row


@router.get("/overrides")
async def list_overrides(
    port_id: Optional[str] = Query(None),
    date_: Optional[str] = Query(None, alias="date"),
    x_officer_token: Optional[str] = Header(None, alias="X-Officer-Token"),
) -> Dict[str, Any]:
    """List overrides, optionally filtered by port and date (YYYY-MM-DD)."""
    role = require_officer_role(x_officer_token)
    scoped = _require_scoped_port(role, port_id)
    rows = [r for r in _overrides if not scoped or r["port_id"] == scoped.lower()]
    if date_:
        rows = [r for r in rows if r["date"] == date_.strip()]
    return {"count": len(rows), "overrides": rows}


# ---------------------------------------------------------------------------
# Broadcasts
# ---------------------------------------------------------------------------

@router.post("/broadcasts")
async def create_broadcast(
    body: BroadcastCreate,
    x_officer_token: Optional[str] = Header(None, alias="X-Officer-Token"),
) -> Dict[str, Any]:
    """Draft a port advisory broadcast (English + optional local text)."""
    require_officer_role(x_officer_token)
    validate_port_id(body.port_id)
    row = {
        "id": str(uuid.uuid4()),
        "port_id": body.port_id.strip().lower(),
        "text_en": body.text_en,
        "text_local": body.text_local,
        "lang": body.lang or "en",
        "created_at": _now_iso(),
    }
    _broadcasts.append(row)
    return row


@router.get("/broadcasts")
async def list_broadcasts(
    port_id: Optional[str] = Query(None),
    x_officer_token: Optional[str] = Header(None, alias="X-Officer-Token"),
) -> Dict[str, Any]:
    """List broadcasts; port role scoped to ?port_id=, watch reads all."""
    role = require_officer_role(x_officer_token)
    scoped = _require_scoped_port(role, port_id)
    rows = [r for r in _broadcasts if not scoped or r["port_id"] == scoped.lower()]
    return {"count": len(rows), "broadcasts": rows}
