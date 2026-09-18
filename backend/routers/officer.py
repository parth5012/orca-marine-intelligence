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
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from backend.core.ports import get_port
except ImportError:  # pragma: no cover - alternate import root
    from core.ports import get_port

try:
    from backend.ingest.boundaries import (
        IMBL_BUFFER_KM,
        check_point_in_eez,
        check_point_in_mpa,
        distance_to_imbl_km,
    )
except ImportError:  # pragma: no cover - alternate import root
    try:
        from ingest.boundaries import (  # type: ignore
            IMBL_BUFFER_KM,  # type: ignore
            check_point_in_eez,  # type: ignore
            check_point_in_mpa,  # type: ignore
            distance_to_imbl_km,  # type: ignore
        )
    except ImportError:  # pragma: no cover - degraded: boundary data absent
        # Duplicated from backend/ingest/boundaries.py + geofence.py:58.
        # No new values invented; used only if the ingest module is absent.
        IMBL_BUFFER_KM = 2.0


        def check_point_in_eez(lat: float, lon: float):  # type: ignore
            return False, float("inf")


        def check_point_in_mpa(lat: float, lon: float):  # type: ignore
            return False, None, float("inf")


        def distance_to_imbl_km(lat: float, lon: float) -> float:  # type: ignore
            return float("inf")

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

# T4 go-no-go kill switch (issue #174): ORCA_ENABLE_GONOGO=false hides the
# frontend card (no weather fetch from it). Default true. Backend keeps
# serving overrides regardless (flag is display-only, documented in
# .env.example); this helper exists so tests + ops can assert the default.
GONOGO_FLAG = "ORCA_ENABLE_GONOGO"


def is_gonogo_enabled() -> bool:
    """Return True unless ORCA_ENABLE_GONOGO is an explicit falsy value. Pure."""
    raw = os.getenv(GONOGO_FLAG, "true")
    return (raw or "true").strip().lower() not in ("false", "0", "no", "off")

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


# ---------------------------------------------------------------------------
# T5 register alerts (issue #175): computed geofence + weather flags per row
# ---------------------------------------------------------------------------
# All thresholds reused, none invented:
# - overdue amber>120 / red>360 mins: compute_overdue above (T2).
# - geofence IMBL 2km buffer: IMBL_BUFFER_KM from ingest/boundaries.py
#   (surfaced at geofence.py:58 as imbl_buffer_km).
# - weather red rule: wind>25kt or wave>2.5m or current>2.5kt or
#   pressure<995hPa, mirroring weather.py:136.
# Backend stores no history, so weather_flag compares the officer-logged
# status at departure (weather_at_log, optional POST field) against a
# current dest status supplied by the caller or DEST_STATUS_PROVIDER.
# Default provider is None (no network I/O in the departures path, so the
# existing suite stays fast/offline); a live deployment may wire a cached
# weather lookup. Unknown either side -> "none" (never invent a flip).

GEOFENCE_NONE = "none"
GEOFENCE_MPA = "mpa"
GEOFENCE_IMBL = "imbl"
GEOFENCE_OUTSIDE_EEZ = "outside_eez"
WEATHER_NONE = "none"
WEATHER_FLIP = "flip"
_WEATHER_KNOWN = ("safe", "caution", "danger")

# Optional hook: (dest_lat, dest_lon) -> "safe"|"caution"|"danger"|None.
# Tests inject a fake; prod may wire a cached lookup. Default None = no I/O.
DEST_STATUS_PROVIDER: Optional[Callable[[float, float], Optional[str]]] = None


def classify_geofence(mpa_hit: bool, imbl_km: float, inside_eez: bool) -> str:
    """Pure geofence flag from precomputed checks. Priority: mpa > imbl > outside_eez."""
    if mpa_hit:
        return GEOFENCE_MPA
    try:
        near_imbl = float(imbl_km) < float(IMBL_BUFFER_KM)
    except (TypeError, ValueError):
        near_imbl = False
    if near_imbl:
        return GEOFENCE_IMBL
    if not inside_eez:
        return GEOFENCE_OUTSIDE_EEZ
    return GEOFENCE_NONE


def compute_geofence_flag(dest_lat: float, dest_lon: float) -> str:
    """Live flag for a destination via ingest boundary data. Never raises (degraded -> none)."""
    try:
        mpa_hit, _, _ = check_point_in_mpa(dest_lat, dest_lon)
        imbl_km = distance_to_imbl_km(dest_lat, dest_lon)
        inside_eez, _ = check_point_in_eez(dest_lat, dest_lon)
    except Exception as exc:
        logger.warning("geofence flag degraded for (%s, %s): %s", dest_lat, dest_lon, exc)
        return GEOFENCE_NONE
    return classify_geofence(bool(mpa_hit), imbl_km, bool(inside_eez))


def is_danger_sea_state(
    wind_kt: float = 0.0,
    wave_m: float = 0.0,
    current_kt: float = 0.0,
    pressure_hpa: float = 1013.0,
) -> bool:
    """True when the weather.py:136 red rule fires. Pure, same thresholds."""
    try:
        return (
            float(wind_kt) > 25.0
            or float(wave_m) > 2.5
            or float(current_kt) > 2.5
            or float(pressure_hpa) < 995.0
        )
    except (TypeError, ValueError):
        return False


def compute_weather_flag(status_at_log: Optional[str], status_now: Optional[str]) -> str:
    """Flip iff a boat logged under safe/caution now faces danger. Pure."""
    if (status_now or "").strip().lower() == "danger" and (
        status_at_log or ""
    ).strip().lower() in ("safe", "caution"):
        return WEATHER_FLIP
    return WEATHER_NONE


def normalize_weather_status(value: Optional[str]) -> Optional[str]:
    """Lowercase known sea statuses, else None. Pure."""
    candidate = (value or "").strip().lower()
    return candidate if candidate in _WEATHER_KNOWN else None


def with_alerts(
    row: Dict[str, Any],
    now: datetime,
    dest_status_now: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a copy of a departure row plus computed alerts (never stored). Pure except provider."""
    out = with_overdue(row, now)
    try:
        out["geofence_flag"] = compute_geofence_flag(float(row["dest_lat"]), float(row["dest_lon"]))
    except (TypeError, ValueError, KeyError):
        out["geofence_flag"] = GEOFENCE_NONE
    status_now = normalize_weather_status(dest_status_now)
    if status_now is None and DEST_STATUS_PROVIDER is not None:
        try:
            status_now = normalize_weather_status(
                DEST_STATUS_PROVIDER(float(row["dest_lat"]), float(row["dest_lon"]))
            )
        except Exception as exc:
            logger.warning("dest status provider failed for row %s: %s", row.get("id"), exc)
            status_now = None
    out["weather_flag"] = compute_weather_flag(row.get("weather_at_log"), status_now)
    return out


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
    # T5 #175: sea status the officer saw at log time (safe|caution|danger).
    # Optional baseline for the weather-flip rule; omitted -> weather_flag none.
    weather_at_log: Optional[str] = None


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
        "weather_at_log": normalize_weather_status(body.weather_at_log),
        "created_at": _now_iso(),
    }
    _departures.append(row)
    return with_alerts(row, datetime.now(timezone.utc))


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
    return {"count": len(rows), "departures": [with_alerts(r, now) for r in rows]}


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
    if not (body.reason or "").strip():
        # T4 #174: a reason is mandatory (esp. when overriding the auto-suggest).
        raise HTTPException(status_code=400, detail="reason is required (non-empty).")
    row = {
        "id": str(uuid.uuid4()),
        "port_id": body.port_id.strip().lower(),
        "date": body.date.isoformat(),
        "decision": body.decision,
        "reason": body.reason.strip(),
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
