"""
ORCA Fallback Legacy Deterministic Gather (Reserved for Future)

Owner: M1 / M-A (Agents & Orchestration)
Module: backend/agents/fallback.py

This module preserves the W1 deterministic `asyncio.gather` orchestration
as a self-contained fallback, separated from the LangGraph supervisor.

It is NOT called by `backend/agents/orchestrator.py` during normal
SIH26176 Agentic path (graph is now always-on per PS requirement).
It is retained for:
  - offline / P95 < 2s strict fallback (future: edge devices without langgraph)
  - regression comparison
  - future: hybrid planner that dynamically chooses gather vs graph

In current production, `orchestrator.orchestrate()` delegates to
`backend/agents/graph.py:orchestrate_via_graph` where sub-agents
(planner, fish_finder, sea_checker,
weather_agent, danger_agent, decision_agent)
autonomously decide when to call tools (PostGIS, OSF, IMD, GeoJSON).

TODO (future):
  [ ] Re-enable `fallback_orchestrate()` when langgraph is unavailable
  [ ] Add feature-flag / edge-mode (e.g., ORCA_MODE=edge)
  [ ] Benchmark gather vs graph latency for hybrid routing
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import math
import os
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ARCHIVED legacy deterministic regex utilities (#35 — offline/edge dev only)
# ---------------------------------------------------------------------------
# Moved verbatim from backend/agents/orchestrator.py during W1. They are NOT
# the primary LLM execution path (orchestrator.orchestrate/stream
# delegate straight to backend/agents/graph.py where Gemini planner and
# synthesizer decide). They are preserved strictly for offline/edge
# dev reference and as an intentional lazy deterministic baseline in
# graph.py planner_node when plan_query raises (per #32 fix: surfacing,
# not blocking: planner_error fallback:none is yielded).
#
# DO NOT import orchestrator.py from this module.
# DO NOT call on LLM success path to mask LLM failures with
# silent heuristics. Uncaught LLM errors must surface as explicit
# SSE {type: error, agent: ..., message: ..., fallback: unknown/none}.

# Deterministic coastal port lookup fast-path before any LLM (archived)
COASTAL_PORTS: dict[str, list[float]] = {
    "Kochi": [9.93, 76.26],
    "Veraval": [21.6, 69.6],
    "Chennai": [13.08, 80.27],
}

# Extended registry of known coastal ports for query lookup (ticket #77)
_KNOWN_PORTS: dict[str, list[float]] = {
    "Kochi": [9.93, 76.26],
    "Veraval": [21.6, 69.6],
    "Chennai": [13.08, 80.27],
    "Munambam": [10.18, 76.17],
    "Beypore": [11.16, 75.80],
    "Kollam": [8.88, 76.57],
    "Vizag": [17.69, 83.29],
    "Visakhapatnam": [17.69, 83.29],
}

# ---------------------------------------------------------------------------
# Coastline geometry for inland GPS detection (ticket #77)
# Continuous polyline tracing the Indian mainland coastline (Gujarat -> West Bengal)
# ---------------------------------------------------------------------------
_COASTLINE_POLYLINE: list[tuple[float, float]] = [
    # Gujarat: Kutch, Saurashtra, Gulf of Khambhat
    (23.70, 68.20),  # Sir Creek / Kori Creek (NW border)
    (23.25, 68.55),  # Jakhau / Narayan Sarovar
    (22.82, 69.40),  # Mandvi
    (23.00, 70.20),  # Kandla / Gandhidham
    (23.05, 70.75),  # Gulf of Kutch inner apex
    (22.70, 70.30),  # Jodiya
    (22.50, 69.80),  # Jamnagar / Bedi
    (22.46, 69.07),  # Okha (tip NW)
    (22.24, 68.97),  # Dwarka
    (21.64, 69.60),  # Porbandar
    (21.17, 70.05),  # Mangrol
    (20.90, 70.36),  # Veraval
    (20.71, 70.92),  # Diu / Kodinar
    (20.87, 71.36),  # Jafrabad
    (21.08, 71.77),  # Mahuva
    (21.50, 72.24),  # Gopnath
    (21.76, 72.15),  # Bhavnagar (West Gulf of Khambhat)
    (22.25, 72.55),  # Gulf of Khambhat head / Cambay
    (21.70, 72.50),  # Dahej (East Gulf of Khambhat)
    (21.10, 72.70),  # Surat / Hazira
    (20.58, 72.90),  # Valsad
    (20.40, 72.83),  # Daman
    # Maharashtra
    (19.97, 72.73),  # Dahanu
    (19.35, 72.78),  # Vasai / Palghar
    (18.92, 72.83),  # Mumbai
    (18.64, 72.87),  # Alibag
    (18.30, 72.95),  # Murud / Janjira
    (17.98, 73.05),  # Harihareshwar
    (17.50, 73.15),  # Dabhol / Guhagar
    (16.99, 73.30),  # Ratnagiri
    (16.50, 73.33),  # Vijaydurg
    (16.05, 73.47),  # Malvan
    (15.86, 73.63),  # Vengurla
    # Goa
    (15.60, 73.74),  # Arambol / Calangute
    (15.40, 73.80),  # Panaji / Mormugao
    (15.00, 73.95),  # Palolem / Canacona
    # Karnataka
    (14.81, 74.13),  # Karwar
    (14.53, 74.32),  # Ankola
    (14.42, 74.41),  # Kumta
    (14.28, 74.43),  # Honnavar
    (13.97, 74.55),  # Bhatkal
    (13.63, 74.68),  # Kundapura
    (13.35, 74.70),  # Malpe / Udupi
    (12.91, 74.85),  # Mangalore
    # Kerala
    (12.50, 74.98),  # Kasaragod
    (12.00, 75.20),  # Payyanur
    (11.87, 75.36),  # Kannur
    (11.75, 75.49),  # Thalassery
    (11.56, 75.60),  # Vadakara
    (11.25, 75.77),  # Kozhikode
    (11.16, 75.80),  # Beypore
    (10.77, 75.92),  # Ponnani
    (10.18, 76.17),  # Munambam
    (9.93, 76.26),   # Kochi
    (9.49, 76.33),   # Alappuzha
    (8.88, 76.57),   # Kollam
    (8.50, 76.85),   # Varkala
    (8.38, 76.99),   # Vizhinjam / Trivandrum
    (8.08, 77.55),   # Kanyakumari (Southern tip)
    # Tamil Nadu (East coast)
    (8.30, 77.90),   # Koodankulam
    (8.49, 78.12),   # Tiruchendur
    (8.76, 78.13),   # Tuticorin (Thoothukudi)
    (9.10, 78.40),   # Vembar
    (9.28, 79.12),   # Mandapam
    (9.28, 79.31),   # Rameswaram
    (9.18, 79.52),   # Dhanushkodi
    (9.74, 79.02),   # Thondi / Palk Strait
    (10.29, 79.86),  # Point Calimere (Kodikkarai)
    (10.76, 79.84),  # Nagapattinam
    (10.92, 79.84),  # Karaikal
    (11.42, 79.77),  # Parangipettai
    (11.75, 79.77),  # Cuddalore
    (11.94, 79.83),  # Puducherry
    (12.25, 80.00),  # Marakkanam
    (12.62, 80.19),  # Mahabalipuram
    (13.08, 80.27),  # Chennai
    (13.42, 80.32),  # Pulicat
    # Andhra Pradesh
    (13.90, 80.20),  # Durgarajupatnam
    (14.25, 80.12),  # Krishnapatnam
    (15.00, 80.05),  # Kavali
    (15.78, 80.35),  # Ongole / Vadarevu
    (15.91, 80.62),  # Nizampatnam
    (16.18, 81.14),  # Machilipatnam
    (16.50, 81.65),  # Narsapur
    (16.85, 82.25),  # Yanam
    (16.99, 82.25),  # Kakinada
    (17.30, 82.70),  # Tuni
    (17.69, 83.29),  # Visakhapatnam (Vizag)
    (18.00, 83.55),  # Bheemunipatnam
    (18.34, 84.13),  # Kalingapatnam
    (18.90, 84.58),  # Sompeta / Bhavanapadu
    # Odisha
    (19.26, 84.91),  # Gopalpur
    (19.50, 85.30),  # Chilika lake mouth
    (19.81, 85.83),  # Puri
    (20.00, 86.20),  # Konark
    (20.31, 86.61),  # Paradip
    (20.70, 86.90),  # Gahirmatha
    (20.80, 86.96),  # Dhamra
    (21.47, 87.02),  # Chandipur / Balasore
    # West Bengal
    (21.62, 87.51),  # Digha
    (21.75, 87.75),  # Mandarmani / Shankarpur
    (21.80, 88.00),  # Junput
    (21.65, 88.08),  # Sagar Island
    (21.56, 88.25),  # Bakkhali / Namkhana
    (21.70, 89.10),  # Sundarbans / Raimangal River border
]

_ISLAND_COAST_POINTS: list[tuple[float, float]] = [
    # Lakshadweep
    (10.57, 72.64),  # Kavaratti
    (10.85, 72.18),  # Agatti
    (11.20, 72.78),  # Amini
    (8.28, 73.05),   # Minicoy
    # Andaman & Nicobar
    (11.67, 92.74),  # Port Blair
    (12.50, 92.90),  # Diglipur / North Andaman
    (9.16, 92.78),   # Car Nicobar
    (7.00, 93.85),   # Great Nicobar
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers between two points on Earth."""
    r = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * r * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def _distance_point_to_segment_km(
    plat: float, plon: float, lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Approximate distance from point (plat, plon) to segment (lat1, lon1)-(lat2, lon2)."""
    if abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9:
        return _haversine_km(plat, plon, lat1, lon1)

    mean_lat = math.radians((plat + lat1 + lat2) / 3.0)
    cos_lat = math.cos(mean_lat)

    px = plon * cos_lat
    py = plat
    x1 = lon1 * cos_lat
    y1 = lat1
    x2 = lon2 * cos_lat
    y2 = lat2

    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq <= 0:
        return _haversine_km(plat, plon, lat1, lon1)

    t = ((px - x1) * dx + (py - y1) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))

    closest_lon = lon1 + t * (lon2 - lon1)
    closest_lat = lat1 + t * (lat2 - lat1)
    return _haversine_km(plat, plon, closest_lat, closest_lon)


def _distance_to_coastline_km(lat: float, lon: float) -> float:
    """Minimum haversine distance in km from (lat, lon) to any coastline."""
    min_dist = float("inf")
    for i in range(len(_COASTLINE_POLYLINE) - 1):
        lat1, lon1 = _COASTLINE_POLYLINE[i]
        lat2, lon2 = _COASTLINE_POLYLINE[i + 1]
        d = _distance_point_to_segment_km(lat, lon, lat1, lon1, lat2, lon2)
        if d < min_dist:
            min_dist = d
    for ilat, ilon in _ISLAND_COAST_POINTS:
        d = _haversine_km(lat, lon, ilat, ilon)
        if d < min_dist:
            min_dist = d
    return min_dist


def _get_inland_threshold_km() -> float:
    """Read inland GPS threshold from ORCA_INLAND_GPS_THRESHOLD env var (default 50km)."""
    raw = os.getenv("ORCA_INLAND_GPS_THRESHOLD", "50")
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 50.0


def _is_inland(lat: float, lon: float, threshold_km: float | None = None) -> bool:
    """Return True if (lat, lon) is > threshold_km from any coastline."""
    if threshold_km is None:
        threshold_km = _get_inland_threshold_km()
    return _distance_to_coastline_km(lat, lon) > threshold_km


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
    all_ports = {**COASTAL_PORTS, **_KNOWN_PORTS}
    for port, coords in all_ports.items():
        if port.lower() in q:
            return float(coords[0]), float(coords[1])
    return None


def _resolve_location(query: str, location: dict | None) -> tuple[float, float] | None:
    """Resolve target coordinates from user query and optional GPS location.

    Priority Rules (ticket #77):
    1. If user query explicitly names a known coastal port (Kochi, Veraval, Chennai, etc.):
       - If browser GPS is provided but inland (> ORCA_INLAND_GPS_THRESHOLD, default 50km
         from any coastline), prioritize the named port over the inland browser GPS.
       - If browser GPS is provided and near the coast (<= threshold), use the browser GPS.
       - If no GPS is provided, use the named port.
    2. If no coastal port is named in query:
       - Use explicit location if provided.
       - Otherwise return None.
    """
    explicit = _parse_explicit_location(location)
    port_match = _coastal_port_lookup(query)

    # 1. Named coastal port in query
    if port_match is not None:
        if explicit is not None:
            lat, lon = explicit
            if _is_inland(lat, lon):
                threshold_val = _get_inland_threshold_km()
                logger.info(
                    "GPS (%s, %s) is inland (>%skm from coastline); prioritizing named port query",
                    lat,
                    lon,
                    threshold_val,
                )
                return port_match
            # GPS is near coast (<= threshold) -> preserve browser GPS
            return explicit
        # No GPS provided -> use named port
        return port_match

    # 2. No named port in query -> fallback to explicit location if present.
    # Inland GPS (>threshold from coastline) with no named port is NOT a
    # searchable marine location — return None so callers fire the coastal
    # GPS clarification prompt instead of a misleading DO NOT SAIL.
    if explicit is not None:
        try:
            if _is_inland(float(explicit[0]), float(explicit[1])):
                logger.info(
                    "GPS (%s, %s) is inland with no named port; returning None for clarification",
                    explicit[0],
                    explicit[1],
                )
                return None
        except Exception:
            pass
        return explicit

    return None


# ~0.09 deg ~= 10 km (111 km per degree). lon adjusted by cos(lat).
_DEG_PER_10KM = 0.09


def _parse_relative_offset(query: str, cached_lat: float, cached_lon: float) -> tuple[float, float] | None:
    """Parse relative spatial offset like '10km south', '20km further north'.

    Returns (new_lat, new_lon) if offset detected, else None.
    Supports directions: south/north/east/west and distance in km.
    """
    if not query or not isinstance(query, str):
        return None
    q = query.lower()
    # Primary: "10km south" / "20 further south" / "10km further east"
    m = re.search(r"(\d+(?:\.\d+)?)\s*km\s*(?:further\s*)?(south|north|east|west)\b", q)
    if m:
        try:
            dist_km = float(m.group(1))
        except (TypeError, ValueError):
            return None
        direction = m.group(2)
    else:
        # Secondary: "south 10km" / "further south 10km" (via substring)
        m2 = re.search(r"(south|north|east|west)\s*(?:further\s*)?(\d+(?:\.\d+)?)\s*km", q)
        if m2:
            direction = m2.group(1)
            try:
                dist_km = float(m2.group(2))
            except (TypeError, ValueError):
                return None
        else:
            # Tertiary: "further south" without distance -> default 10km
            m3 = re.search(r"\bfurther\s+(south|north|east|west)\b", q)
            if m3:
                direction = m3.group(1)
                dist_km = 10.0
            else:
                return None

    factor = dist_km / 10.0
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
                cos_lat = 0.1
            new_lon = cached_lon + (delta_deg / cos_lat)
        except Exception:
            new_lon = cached_lon + delta_deg
    elif direction == "west":
        try:
            cos_lat = math.cos(math.radians(cached_lat))
            if abs(cos_lat) < 0.1:
                cos_lat = 0.1
            new_lon = cached_lon - (delta_deg / cos_lat)
        except Exception:
            new_lon = cached_lon - delta_deg

    # Clamp to valid ranges
    new_lat = max(-90.0, min(90.0, new_lat))
    # Normalize lon to -180..180
    while new_lon > 180:
        new_lon -= 360
    while new_lon < -180:
        new_lon += 360
    return float(new_lat), float(new_lon)


def _is_temporal_followup(query: str) -> bool:
    """Detect temporal follow-up phrases that can reuse cached coords."""
    if not query or not isinstance(query, str):
        return False
    q = query.lower()
    temporal_keywords = [
        "tomorrow", "morning", "evening", "tonight", "afternoon",
        "next", "later", "safe", "safety", "weather", "sea",
    ]
    # If query is a short follow-up (e.g., "Is it safe tomorrow morning?") reuse
    # We treat any query containing a temporal keyword as a temporal reuse candidate
    # when location is missing and caller checks cached existence.
    return any(k in q for k in temporal_keywords)


def _parse_intent(query: str) -> dict:
    q = (query or "").lower()
    # wants_fish: keywords fish/PFZ
    fish_keywords = ["fish", "pfz", "catch", "fishing", "zone", "மீன்", "மீன", "മീൻ", "മത്സ്യം", "machhli", "chepa"]
    # wants_safety: wave, wind, cyclone, safe, danger, tide, weather, storm
    safety_keywords = ["safe", "danger", "wave", "wind", "cyclone", "storm", "tide", "weather", "sea", "current", "lightning"]
    # In W1, if query is short or unknown, default both to true (independent)
    wants_fish = any(k in q for k in fish_keywords)
    wants_safety = any(k in q for k in safety_keywords)
    # If neither keyword matched, assume user wants both (fish + safety)
    if not wants_fish and not wants_safety:
        wants_fish = True
        wants_safety = True
    return {"wants_fish": wants_fish, "wants_safety": wants_safety}


# ---------------------------------------------------------------------------
# Legacy gather placeholders (reserved for future edge/offline mode)
# ---------------------------------------------------------------------------
#
# For reference, legacy flow was:
# 1. _resolve_location(query, location) with Redis session reuse & _parse_relative_offset
# 2. fish_finder.find_fishing_zones(lat, lon) with 10s wait_for
# 3. asyncio.gather(
#        sea_checker.check_sea_conditions(shared_points),
#        weather_agent.check_weather(shared_points),
#        danger_agent.check_safety_batch(shared_points),
#        return_exceptions=True
#    ) with each 10s timeout and degraded "unknown"
# 4. combiner.combine_and_rank(...)
# 5. assemble POST /api/chat payload and Redis save_session with 24h TTL
#
# See git history on orchestrator.py @ bb4e01d..a7831f4 for full code.
# This stub exists so future work can re-implement without
# re-extracting history.


async def fallback_orchestrate(*args: Any, **kwargs: Any) -> dict:
    """Placeholder for legacy gather reserved for future."""
    raise NotImplementedError(
        "fallback_orchestrate is reserved for future edge/offline mode. "
        "Use backend.agents.graph:orchestrate_via_graph for the LangGraph supervisor (SIH26176)."
    )


async def fallback_orchestrate_stream(*args: Any, **kwargs: Any):  # type: ignore
    """Placeholder for legacy SSE streaming reserved for future."""
    raise NotImplementedError(
        "fallback_orchestrate_stream is reserved for future. "
        "Use backend.agents.graph:orchestrate_stream_via_graph."
    )
    yield  # make it a generator for type checking
