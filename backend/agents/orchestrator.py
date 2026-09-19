"""
ORCA Brain — Orchestrator Agent

Owner: M-A (Agents & Orchestration) — 6 agents: the intelligence layer
Module: backend/agents/orchestrator.py

The Orchestrator is the central "brain" of ORCA. It receives a user query
(e.g., "Where is fish near Kochi?"), detects intent, and coordinates the
four specialist agents in parallel to produce a unified, safe advisory.

Flow:
    1. Receive user query + detected language + location (GPS or text)
    2. Split query into sub-tasks: fish location, sea conditions, weather, danger zones
    3. Dispatch to 4 agents in parallel (all reading the same GeoJSON points)
    4. Collect results, pass to Smart Combiner for ranking
    5. Return combined answer with map reference, evidence citations, and language

Agents dispatched:
    - FishFinder  → Closest PFZ zones within radius
    - SeaChecker  → Wave height and current speed at those points
    - WeatherAgent → Wind speed and tide at those points
    - DangerAgent  → EEZ/MPA geofence and cyclone checks

Dependencies:
    - Redis for multi-turn conversation memory
    - PostGIS for spatial queries on shared GeoJSON data
    - Bhashini for language detection and translation
"""

import asyncio
import datetime
import logging
import time
import uuid
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Legacy regex decommission (#35) — archived in fallback.py
# ---------------------------------------------------------------------------
# COASTAL_PORTS / _parse_intent / _resolve_location / _parse_relative_offset
# (+ _parse_explicit_location / _coastal_port_lookup / _is_temporal_followup)
# are ARCHIVED in backend/agents/fallback.py for offline/edge dev reference
# only. They are re-exported here SOLELY for backward compatibility
# (existing tests import orchestrator._parse_intent etc.) and MUST NOT be
# used by the primary execution path below (orchestrate/orchestrate_stream
# delegate straight to the LLM graph — no silent regex heuristics).
# graph.py imports its lazy deterministic baseline from fallback.py directly.
try:
    from backend.agents.fallback import (  # noqa: F401 (deprecated re-exports)
        COASTAL_PORTS,
        _KNOWN_PORTS,
        _coastal_port_lookup,
        _is_temporal_followup,
        _parse_explicit_location,
        _parse_intent,
        _parse_relative_offset,
        _resolve_location,
    )
except ImportError:
    from fallback import (  # type: ignore # noqa: F401 (direct script runs)
        COASTAL_PORTS,
        _KNOWN_PORTS,
        _coastal_port_lookup,
        _is_temporal_followup,
        _parse_explicit_location,
        _parse_intent,
        _parse_relative_offset,
        _resolve_location,
    )

TIMEOUT_S = 10.0
DEFAULT_CONFIDENCE = 0.87
DEGRADED_CONFIDENCE = 0.62

# US-ORCA-014 canonical GeoJSON contract thresholds — SINGLE SOURCE OF
# TRUTH is backend/agents/safety_thresholds.py (wayfinder #196). Aliases
# below preserve the legacy private names; the veto itself delegates to
# safety_thresholds.veto_safety (wind converted kph → kt, canonical
# 15/25kt bands). CONFIDENCE constants are imported for the same reason.
from backend.agents.safety_thresholds import (
    DEGRADED_CONFIDENCE as DEGRADED_CONFIDENCE,
)
from backend.agents.safety_thresholds import (
    KT_TO_KPH as _KT_TO_KPH,
)
from backend.agents.safety_thresholds import (
    WIND_DANGER_MIN_KPH as _WIND_DANGER_KPH,
)
from backend.agents.safety_thresholds import (
    WIND_SAFE_MAX_KPH as _WIND_CAUTION_KPH,
)
from backend.agents.safety_thresholds import (
    WAVE_DANGER_MIN_M as _WAVE_DANGER_M,
)
from backend.agents.safety_thresholds import (
    WAVE_SAFE_MAX_M as _WAVE_CAUTION_M,
)


# ---------------------------------------------------------------------------
# Degraded fallbacks (status "unknown")
# ---------------------------------------------------------------------------

def _unknown_danger(points: list[dict]) -> list[dict]:
    """Unknown-shaped geofence entries for a deselected check_geofence.

    inside_eez=None (unknown, never a ban) so the combiner degrades to
    caution instead of a false "outside Indian EEZ" DO NOT SAIL.
    """
    unknown = []
    for idx, pt in enumerate(points):
        zone_id = pt.get("zone_id") if isinstance(pt, dict) else None
        zone_id = str(zone_id) if zone_id else f"unknown_{idx}"
        place = pt.get("place", "") if isinstance(pt, dict) else ""
        lat = pt.get("lat") if isinstance(pt, dict) else None
        lon = pt.get("lon") if isinstance(pt, dict) else None
        unknown.append({
            "zone_id": zone_id,
            "place": str(place),
            "lat": lat,
            "lon": lon,
            "is_safe": None,
            "status": "unknown",
            "warnings": ["geofence check skipped by planner"],
            "inside_eez": None,
            "inside_mpa": False,
            "mpa_name": None,
        })
    return unknown


def _degraded_sea(points: list[dict]) -> list[dict]:
    degraded = []
    for idx, pt in enumerate(points):
        zone_id = pt.get("zone_id") if isinstance(pt, dict) else None
        zone_id = str(zone_id) if zone_id else f"unknown_{idx}"
        place = pt.get("place", "") if isinstance(pt, dict) else ""
        lat = pt.get("lat") if isinstance(pt, dict) else None
        lon = pt.get("lon") if isinstance(pt, dict) else None
        degraded.append({
            "zone_id": zone_id,
            "place": str(place),
            "lat": lat,
            "lon": lon,
            "wave_height_m": None,
            "current_kt": None,
            "wave_status": "unknown",
            "current_status": "unknown",
            "status": "unknown",
            "reason": "sea check unavailable (timeout/error)",
            "source": "unknown",
        })
    return degraded


def _degraded_weather(points: list[dict]) -> list[dict]:
    degraded = []
    for idx, pt in enumerate(points):
        zone_id = pt.get("zone_id") if isinstance(pt, dict) else None
        zone_id = str(zone_id) if zone_id else f"unknown_{idx}"
        place = pt.get("place", "") if isinstance(pt, dict) else ""
        lat = pt.get("lat") if isinstance(pt, dict) else None
        lon = pt.get("lon") if isinstance(pt, dict) else None
        degraded.append({
            "zone_id": zone_id,
            "place": str(place),
            "lat": lat,
            "lon": lon,
            "wind_kt": None,
            "wind_speed_kt": None,
            "wind_dir": "unknown",
            "wind_direction": "unknown",
            "wind_deg": None,
            "wind_status": "unknown",
            "cyclone_alert": False,
            "nearest_cyclone_km": None,
            "cyclone_name": None,
            "status": "unknown",
            "reason": "weather check unavailable (timeout/error)",
            "source": "unknown",
        })
    return degraded


def _degraded_danger(points: list[dict]) -> list[dict]:
    degraded = []
    for idx, pt in enumerate(points):
        zone_id = pt.get("zone_id") if isinstance(pt, dict) else None
        zone_id = str(zone_id) if zone_id else f"unknown_{idx}"
        place = pt.get("place", "") if isinstance(pt, dict) else ""
        lat = pt.get("lat") if isinstance(pt, dict) else None
        lon = pt.get("lon") if isinstance(pt, dict) else None
        degraded.append({
            "zone_id": zone_id,
            "place": str(place),
            "lat": lat,
            "lon": lon,
            "is_safe": False,
            "status": "unknown",
            "warnings": ["danger check unavailable (timeout/error)"],
            "inside_eez": None,
            "inside_mpa": False,
            "mpa_name": None,
        })
    return degraded


def _parse_depth_m(depth_range: Any) -> float | None:
    """Parse a depth_range like "20-30" or "45-50" to a float metres value.

    Returns the interval midpoint (None when unparseable). US-ORCA-014.
    """
    if depth_range is None:
        return None
    if isinstance(depth_range, (int, float)):
        try:
            return float(depth_range)
        except (TypeError, ValueError):
            return None
    if not isinstance(depth_range, str):
        return None
    import re as _re

    nums = _re.findall(r"\d+(?:\.\d+)?", depth_range)
    if not nums:
        return None
    try:
        vals = [float(n) for n in nums]
    except (TypeError, ValueError):
        return None
    if len(vals) >= 2:
        return round((vals[0] + vals[1]) / 2.0, 2)
    return round(vals[0], 2)


def _wind_kt_to_kph(wind_kt: Any) -> float | None:
    """Convert wind knots to kph (US-ORCA-014 canonical contract)."""
    from backend.agents.safety_thresholds import wind_kt_to_kph as _conv

    return _conv(wind_kt)


def _veto_safety(
    wave_m: float | None,
    wind_kph: float | None,
    inside_eez: Any,
    inside_mpa: Any,
    cyclone_alert: Any = False,
    current_kt: Any = None,
) -> tuple[str, float]:
    """Apply the US-ORCA-014 safety veto.

    Canonical implementation lives in safety_thresholds.veto_safety;
    this wrapper preserves the legacy (wave_m, wind_kph, ...) signature
    by converting kph → kt into the canonical 15/25kt bands (#196).

    danger: wave>2.5m or wind>25kt or current>2.5kt or cyclone alert
        or inside MPA or explicitly outside EEZ. caution: wave>=1.5m
        or wind>=15kt or current>=1.5kt.
    Missing measurements degrade to caution. Returns (safety, confidence)
    where confidence is DEFAULT_CONFIDENCE only for safe, else degraded.
    """
    from backend.agents.safety_thresholds import veto_safety as _canonical
    from backend.agents.safety_thresholds import wind_kph_to_kt as _to_kt

    try:
        wind_kt = _to_kt(wind_kph) if wind_kph is not None else None
    except Exception:
        wind_kt = None
    safety, conf = _canonical(
        wave_m, wind_kt, inside_eez, inside_mpa, cyclone_alert, current_kt
    )
    if safety == "safe":
        return "safe", DEFAULT_CONFIDENCE
    return safety, conf


def _to_geojson_features(ranked_zones: list[dict]) -> list[dict]:
    """Render ranked zones as GeoJSON Features (US-ORCA-014 canonical contract).

    Canonical properties: safety, distance_km, depth_m, wave_m, wind_kph,
    confidence — converted from combiner fields (distance_from_user_km →
    distance_km, depth_range → depth_m float, wave_height_m → wave_m,
    wind_kt × 1.852 → wind_kph) with the safety veto applied per zone.
    Legacy properties (zone_id/place/sector/bearing/direction/depth_range/
    wave_height_m/wind_kt/inside_eez/inside_mpa/score) are preserved for
    backward compatibility.

    Dedup: provisional + final map events both flow through here, so twin
    rows (same place, rounded coords) collapse to one Feature. Keeps first.
    """
    # Normalize + dedup by place|rounded-coords before rendering.
    try:
        from backend.agents.zone_dedup import dedup_zones as _dedup_zones

        ranked_zones = _dedup_zones(list(ranked_zones or []))
    except Exception:
        _seen: set[str] = set()
        _uniq: list[dict] = []
        for _z in ranked_zones or []:
            if not isinstance(_z, dict):
                continue
            try:
                _p = str(_z.get("place") or "").strip().lower()
                _la = round(float(str(_z.get("lat"))), 4)
                _lo = round(float(str(_z.get("lon"))), 4)
                _k = f"{_p}|{_la:.4f}|{_lo:.4f}"
            except (TypeError, ValueError):
                _k = f"id:{_z.get('zone_id') or _z.get('id')}"
            if _k in _seen:
                continue
            _seen.add(_k)
            _uniq.append(_z)
        ranked_zones = _uniq
    features = []
    for z in ranked_zones:
        lat = z.get("lat")
        lon = z.get("lon")
        if lat is None or lon is None:
            continue
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        # distance_km with legacy fallbacks
        dist_raw = z.get("distance_km")
        if dist_raw is None:
            dist_raw = z.get("distance_from_user_km", z.get("distance"))
        try:
            dist_km = round(float(dist_raw), 2) if dist_raw is not None else None
        except (TypeError, ValueError):
            dist_km = None
        depth_m = _parse_depth_m(z.get("depth_range", z.get("depth")))
        wave_raw = z.get("wave_height_m", z.get("wave_m", z.get("wave")))
        try:
            wave_m = round(float(wave_raw), 2) if wave_raw is not None else None
        except (TypeError, ValueError):
            wave_m = None
        wind_raw = z.get("wind_kt", z.get("wind_speed_kt", z.get("wind_kph")))
        if z.get("wind_kph") is not None and z.get("wind_kt") is None and z.get("wind_speed_kt") is None:
            try:
                wind_kph: float | None = round(float(z.get("wind_kph")), 2)
            except (TypeError, ValueError):
                wind_kph = None
        else:
            wind_kph = _wind_kt_to_kph(wind_raw)
        cyclone_alert = z.get("cyclone_alert", z.get("cyclone"))
        current_kt = z.get("current_kt")
        if current_kt is None:
            current_kt = z.get("current_speed_kt", z.get("current"))
        safety, confidence = _veto_safety(
            wave_m,
            wind_kph,
            z.get("inside_eez"),
            z.get("inside_mpa"),
            cyclone_alert,
            current_kt,
        )
        features.append({
            "type": "Feature",
            "properties": {
                "zone_id": z.get("zone_id"),
                "place": z.get("place"),
                "sector": z.get("sector"),
                "bearing": z.get("bearing"),
                "direction": z.get("direction"),
                "depth_range": z.get("depth_range", ""),
                "distance_km": dist_km if dist_km is not None else z.get("distance_km"),
                "score": z.get("score"),
                "wave_height_m": z.get("wave_height_m"),
                "wind_kt": z.get("wind_kt"),
                "inside_eez": z.get("inside_eez"),
                "inside_mpa": z.get("inside_mpa"),
                # US-ORCA-014 canonical contract
                "safety": safety,
                "depth_m": depth_m,
                "wave_m": wave_m,
                "wind_kph": wind_kph,
                "confidence": confidence,
            },
            "geometry": {"type": "Point", "coordinates": [lon_f, lat_f]},
        })
    return features


def _badge_for_best(best: dict | None, sea_status: str, wind_status: str, danger_status: str) -> str:
    # unknown degrades to amber per spec
    if best is None:
        return "amber"
    # If any explicit unknown, amber
    if "unknown" in (sea_status, wind_status, danger_status):
        return "amber"
    if danger_status == "danger" or sea_status == "danger" or wind_status == "danger":
        return "red"
    if danger_status == "caution" or sea_status == "caution" or wind_status == "caution":
        return "amber"
    return "green"


def _chunk_text(text: str, chunk_size: int = 40) -> list[str]:
    """Split advisory reply into token-sized chunks for SSE streaming."""
    if not text:
        return []
    # Prefer splitting on word boundaries while keeping chunks ~chunk_size chars
    words = text.split()
    chunks: list[str] = []
    current = ""
    for w in words:
        # +1 for space if current non-empty
        extra = (1 if current else 0) + len(w)
        if current and len(current) + extra > chunk_size:
            chunks.append(current)
            current = w
        else:
            current = f"{current} {w}" if current else w
    if current:
        chunks.append(current)
    # Append trailing space to each chunk except last to preserve original spacing when concatenated
    # Frontend appends raw text, so we keep natural spacing.
    return chunks


async def orchestrate(query: str, language: str, location: dict | None = None, session_id: str | None = None) -> dict:
    """
    Main entry point for the ORCA brain — always via LangGraph supervisor.

    SIH26176 Agentic AI: sub-agents (planner, fish_finder, sea_checker,
    weather_agent, danger_agent, decision) decide and call tools (PostGIS,
    OSF, IMD, GeoJSON). Deterministic gather fallback is isolated in
    backend/agents/fallback.py for future edge/offline use.

    No Silent Fallback (#35): this primary path NEVER calls archived regex
    heuristics (fallback._parse_intent / _resolve_location). LLM failures
    surface explicitly via planner_error / synthesis_error (fallback:none)
    in the returned payload; uncaught exceptions propagate to the caller
    (never masked by a heuristic result).

    Args:
        query: User's question in any of 22 supported languages.
        language: Detected language code (e.g., "ml" for Malayalam).
        location: Optional GPS coordinates {"lat": float, "lon": float}.
        session_id: Optional multi-turn session ID (generated if missing).

    Returns:
        Combined advisory with map reference, evidence, and translated response
        matching POST /api/chat contract:
        {reply, map, safety, evidence, language, confidence, session_id}

    Raises:
        Any exception from the graph pipeline propagates transparently —
        callers must NOT mask it with regex heuristics.
    """
    # Always via LangGraph supervisor (PS SIH26176 — agents decide, tools fetch)
    from backend.agents.graph import orchestrate_via_graph  # type: ignore

    try:
        return await orchestrate_via_graph(query, language, location, session_id)
    except Exception:
        logger.warning("orchestrator.orchestrate: uncaught pipeline error", exc_info=True)
        raise


async def orchestrate_stream(
    query: str, language: str, location: dict | None = None, session_id: str | None = None
) -> AsyncGenerator[dict, None]:
    """
    SSE streaming variant of orchestrate() for POST /api/chat — always via graph.

    Yields dict events with a ``type`` field in strict order:
        status (running/done) -> map (early onMapHighlight) -> safety -> token(s) -> evidence -> done

    Transparent errors (#35): planner/synthesizer LLM failures flow through
    verbatim as ``{type:error, fallback:none}`` events from the graph (never
    hidden). Any UNCAUGHT exception in this primary path is emitted here as
    ``{type:error, agent:orchestrator, message:..., fallback:unknown}`` —
    never a silent heuristic fallback. ``error`` events are ignored for
    streaming-order assertions per docs/API.md.
    """
    # Always via LangGraph supervisor streaming
    from backend.agents.graph import orchestrate_stream_via_graph  # type: ignore

    try:
        async for evt in orchestrate_stream_via_graph(query, language, location, session_id):
            yield evt
    except Exception as exc:
        logger.warning("orchestrator.stream: uncaught error (%s)", exc, exc_info=True)
        yield {
            "type": "error",
            "agent": "orchestrator",
            "message": f"orchestrator stream failed: {exc}",
            "fallback": "unknown",
        }

