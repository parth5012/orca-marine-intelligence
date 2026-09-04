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
import math
import re
import time
import uuid
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

# Deterministic coastal port lookup — fast-path before any LLM
COASTAL_PORTS: dict[str, list[float]] = {
    "Kochi": [9.93, 76.26],
    "Veraval": [21.6, 69.6],
    "Chennai": [13.08, 80.27],
}

TIMEOUT_S = 10.0
DEFAULT_CONFIDENCE = 0.87
DEGRADED_CONFIDENCE = 0.62


# ---------------------------------------------------------------------------
# Location resolution helpers
# ---------------------------------------------------------------------------

def _parse_explicit_location(location: dict | None) -> tuple[float, float] | None:
    if not isinstance(location, dict):
        return None
    # Support multiple key variants
    lat = None
    lon = None
    for k in ("lat", "latitude", "y"):
        if location.get(k) is not None:
            try:
                lat = float(location[k])
                break
            except (TypeError, ValueError):
                continue
    for k in ("lon", "lng", "longitude", "x"):
        if location.get(k) is not None:
            try:
                lon = float(location[k])
                break
            except (TypeError, ValueError):
                continue
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return float(lat), float(lon)


def _coastal_port_lookup(query: str) -> tuple[float, float] | None:
    if not query or not isinstance(query, str):
        return None
    q = query.lower()
    for port, coords in COASTAL_PORTS.items():
        if port.lower() in q:
            return float(coords[0]), float(coords[1])
    return None


def _resolve_location(query: str, location: dict | None) -> tuple[float, float] | None:
    # 1. Explicit location dict wins
    explicit = _parse_explicit_location(location)
    if explicit is not None:
        return explicit
    # 2. Substring match on query vs COASTAL_PORTS
    port_match = _coastal_port_lookup(query)
    if port_match is not None:
        return port_match
    return None


# ---------------------------------------------------------------------------
# Follow-up contextualization helpers (#10, #17)
# ---------------------------------------------------------------------------

# 0.09 deg ≈ 10km (111km per degree). lon adjusted by cos(lat).
_DEG_PER_10KM = 0.09

def _parse_relative_offset(query: str, cached_lat: float, cached_lon: float) -> tuple[float, float] | None:
    """Parse relative spatial offset like '10km south', '20km further north'.

    Returns (new_lat, new_lon) if offset detected, else None.
    Supports directions: south/north/east/west with distance in km.
    """
    if not query or not isinstance(query, str):
        return None
    q = query.lower()
    # Pattern: <num> km [further] <direction>, also handle "further south 10km" variants
    # Primary: "10km south" / "20 km further south" / "10km further east"
    m = re.search(r"(\d+(?:\.\d+)?)\s*km\s*(?:further\s*)?(south|north|east|west)\b", q)
    if not m:
        # Secondary: "further south 10km" or "south 10km"
        m = re.search(r"(south|north|east|west)\s*(?:further\s*)?(\d+(?:\.\d+)?)\s*km", q)
        if m:
            direction = m.group(1)
            try:
                km = float(m.group(2))
            except (TypeError, ValueError):
                return None
        else:
            # Also handle "10km further south" where further after km but before direction already covered
            # Check for direction without distance but with 'further' keyword -> default 10km
            if re.search(r"\bfurther\s+(south|north|east|west)\b", q):
                dm = re.search(r"\bfurther\s+(south|north|east|west)\b", q)
                direction = dm.group(1) if dm else None
                km = 10.0
                if direction is None:
                    return None
            else:
                return None
        if 'direction' not in locals():
            return None
    else:
        try:
            km = float(m.group(1))
        except (TypeError, ValueError):
            return None
        direction = m.group(2)

    factor = km / 10.0
    delta_deg = _DEG_PER_10KM * factor
    new_lat = float(cached_lat)
    new_lon = float(cached_lon)
    if direction == "south":
        new_lat = cached_lat - delta_deg
    elif direction == "north":
        new_lat = cached_lat + delta_deg
    elif direction == "east":
        # Adjust lon by cos(lat)
        try:
            cos_lat = math.cos(math.radians(cached_lat))
            if abs(cos_lat) < 0.1:
                cos_lat = 0.1 if cos_lat >= 0 else -0.1
            new_lon = cached_lon + delta_deg / cos_lat
        except Exception:
            new_lon = cached_lon + delta_deg
    elif direction == "west":
        try:
            cos_lat = math.cos(math.radians(cached_lat))
            if abs(cos_lat) < 0.1:
                cos_lat = 0.1 if cos_lat >= 0 else -0.1
            new_lon = cached_lon - delta_deg / cos_lat
        except Exception:
            new_lon = cached_lon - delta_deg
    else:
        return None
    # Clamp to valid ranges
    new_lat = max(-90.0, min(90.0, new_lat))
    # Normalize lon to -180..180
    while new_lon > 180:
        new_lon -= 360
    while new_lon < -180:
        new_lon += 360
    return float(new_lat), float(new_lon)


def _is_temporal_followup(query: str) -> bool:
    """Detect temporal follow-up phrases that should reuse cached coords."""
    if not query or not isinstance(query, str):
        return False
    q = query.lower()
    temporal_keywords = [
        "tomorrow", "morning", "evening", "tonight", "afternoon",
        "next", "later", "safe", "safety", "weather", "sea",
    ]
    # If query is short follow-up (e.g., "Is it safe tomorrow morning?") reuse
    # We treat any query containing temporal keyword as temporal reuse candidate
    # when location is missing — the caller checks cached existence.
    return any(k in q for k in temporal_keywords)


# ---------------------------------------------------------------------------
# Intent helper (independent flags per #8)
# ---------------------------------------------------------------------------

def _parse_intent(query: str) -> dict:
    q = (query or "").lower()
    # wants_fish: keywords for fish/PFZ
    fish_keywords = ["fish", "pfz", "catch", "fishing", "zone", "மீன்", "മത്സ്യം", "machhli", "chepa"]
    # wants_safety: wave, wind, cyclone, safe, danger, tide, weather, storm
    safety_keywords = ["safe", "danger", "wave", "wind", "cyclone", "storm", "tide", "weather", "sea", "current", "lightning"]
    # For W1, if query is short or unknown, default both true (independent)
    wants_fish = any(k in q for k in fish_keywords)
    wants_safety = any(k in q for k in safety_keywords)
    # If neither keyword matched, assume user wants both (fish + safety)
    if not wants_fish and not wants_safety:
        wants_fish = True
        wants_safety = True
    return {"wants_fish": wants_fish, "wants_safety": wants_safety}


# ---------------------------------------------------------------------------
# Degraded fallbacks (status "unknown")
# ---------------------------------------------------------------------------

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
            "inside_eez": True,
            "inside_mpa": False,
            "mpa_name": None,
        })
    return degraded


def _to_geojson_features(ranked_zones: list[dict]) -> list[dict]:
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
        features.append({
            "type": "Feature",
            "properties": {
                "zone_id": z.get("zone_id"),
                "place": z.get("place"),
                "sector": z.get("sector"),
                "bearing": z.get("bearing"),
                "direction": z.get("direction"),
                "depth_range": z.get("depth_range", ""),
                "distance_km": z.get("distance_km"),
                "score": z.get("score"),
                "wave_height_m": z.get("wave_height_m"),
                "wind_kt": z.get("wind_kt"),
                "inside_eez": z.get("inside_eez"),
                "inside_mpa": z.get("inside_mpa"),
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

    Args:
        query: User's question in any of 22 supported languages.
        language: Detected language code (e.g., "ml" for Malayalam).
        location: Optional GPS coordinates {"lat": float, "lon": float}.
        session_id: Optional multi-turn session ID (generated if missing).

    Returns:
        Combined advisory with map reference, evidence, and translated response
        matching POST /api/chat contract:
        {reply, map, safety, evidence, language, confidence, session_id}
    """
    # Always via LangGraph supervisor (PS SIH26176 — agents decide, tools fetch)
    from backend.agents.graph import orchestrate_via_graph  # type: ignore

    return await orchestrate_via_graph(query, language, location, session_id)


async def orchestrate_stream(
    query: str, language: str, location: dict | None = None, session_id: str | None = None
) -> AsyncGenerator[dict, None]:
    """
    SSE streaming variant of orchestrate() for POST /api/chat/stream — always via graph.

    Yields dict events with a ``type`` field in strict order:
        status (running/done) -> map (early onMapHighlight) -> safety -> token(s) -> evidence -> done
    """
    # Always via LangGraph supervisor streaming
    from backend.agents.graph import orchestrate_stream_via_graph  # type: ignore

    async for evt in orchestrate_stream_via_graph(query, language, location, session_id):
        yield evt

