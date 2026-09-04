"""
ORCA Fallback — Legacy Deterministic Gather (Reserved for Future)

Owner: M-A (Agents & Orchestration)
Module: backend/agents/fallback.py

This module preserves the W1 deterministic `asyncio.gather` orchestration
as a self-contained fallback, separated from the LangGraph supervisor.

It is NOT used by `backend/agents/orchestrator.py` in the
SIH26176 Agentic AI path (graph is now always-on per PS requirement).
It is retained for:
  - offline / P95<2s strict fallback (future: edge devices without langgraph)
  - regression comparison
  - future: hybrid planner that dynamically chooses gather vs graph

For current production, `orchestrator.orchestrate()` delegates to
`backend/agents/graph.py:orchestrate_via_graph` where sub-agents
(planner, fish_finder, sea_checker,
weather_agent, danger_agent, decision_agent)
decide and call tools (PostGIS, OSF, IMD, GeoJSON).

TODO (future):
  - [ ] Re-enable as `fallback_orchestrate()` when langgraph unavailable
  - [ ] Add feature-flag/edge-mode (e.g., ORCA_MODE=edge)
  - [ ] Benchmark gather vs graph latency for hybrid routing
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import math
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ARCHIVED legacy deterministic regex utilities (#35 — offline/edge dev only)
# ---------------------------------------------------------------------------
# Moved verbatim from backend/agents/orchestrator.py W1. These are NOT used
# by the primary LLM execution path (orchestrator.orchestrate/stream
# delegate straight to backend/agents/graph.py where the Gemini planner +
# synthesizer decide). They are preserved here strictly as an offline/edge
# dev reference and as the intentional lazy deterministic baseline for
# graph.py planner_node when plan_query raises (per #32 fix — surfacing,
# not blocking: planner_error fallback:none is still yielded).
#
# DO NOT import these from orchestrator.py — import from this module.
# DO NOT call these on the LLM success path — they mask LLM failures
# with silent heuristics. Uncaught LLM errors must surface as explicit
# SSE {type:error, agent:..., message:..., fallback:unknown/none}.

# Deterministic coastal port lookup — fast-path before any LLM (archived)
COASTAL_PORTS: dict[str, list[float]] = {
    "Kochi": [9.93, 76.26],
    "Veraval": [21.6, 69.6],
    "Chennai": [13.08, 80.27],
}


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
    # Primary: "10km south" / "20 km further south" / "10km further east"
    m = re.search(r"(\d+(?:\.\d+)?)\s*km\s*(?:further\s*)?(south|north|east|west)\b", q)
    if m:
        try:
            km = float(m.group(1))
        except (TypeError, ValueError):
            return None
        direction = m.group(2)
    else:
        # Secondary: "south 10km" / "further south 10km" (via substring)
        m2 = re.search(r"(south|north|east|west)\s*(?:further\s*)?(\d+(?:\.\d+)?)\s*km", q)
        if m2:
            direction = m2.group(1)
            try:
                km = float(m2.group(2))
            except (TypeError, ValueError):
                return None
        else:
            # Tertiary: "further south" without distance -> default 10km
            m3 = re.search(r"\bfurther\s+(south|north|east|west)\b", q)
            if m3:
                direction = m3.group(1)
                km = 10.0
            else:
                return None

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
# Legacy gather placeholders (reserved for future edge/offline mode)
# ---------------------------------------------------------------------------

# For reference, the legacy flow was:
#   1. _resolve_location(query, location) or Redis session reuse + _parse_relative_offset
#   2. fish_finder.find_fishing_zones(lat, lon) with 10s wait_for
#   3. asyncio.gather(
#         sea_checker.check_sea_conditions(shared_points),
#         weather_agent.check_weather(shared_points),
#         danger_agent.check_safety_batch(shared_points),
#         return_exceptions=True
#      ) each with 10s timeout → degraded to "unknown"
#   4. combiner.combine_and_rank(...)
#   5. assemble POST /api/chat payload + Redis save_session 24h TTL
#
# See git history orchestrator.py @bb4e01d..a7831f4 for full code.
# This stub exists so future work can re-implement without
# re-extracting from history.

async def fallback_orchestrate(*args: Any, **kwargs: Any) -> dict:
    """Placeholder — legacy gather reserved for future."""
    raise NotImplementedError(
        "fallback_orchestrate is reserved for future edge/offline mode. "
        "Use backend.agents.graph:orchestrate_via_graph (LangGraph supervisor) for SIH26176."
    )


async def fallback_orchestrate_stream(*args: Any, **kwargs: Any):  # type: ignore
    """Placeholder — legacy SSE streaming reserved for future."""
    raise NotImplementedError(
        "fallback_orchestrate_stream reserved for future. "
        "Use backend.agents.graph:orchestrate_stream_via_graph."
    )
    yield {}  # make it an async generator type
