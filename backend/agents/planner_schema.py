"""
PROTOTYPE - awaiting human approval (wayfinder #25, map #22). ROUGH DRAFT only.

Dynamic planner schema for Gemini 2.5 Flash (<5000ms) selective dispatch.

Design (draft, to react to):
  - Planner (LLM) picks a SUBSET of 4 specialists per query instead of
    always running all 4 (see orchestrator.py asyncio.gather today).
  - Combiner keeps deterministic hard veto (banned/unsafe zones never win).
  - Clarification threshold: confidence < 0.6 -> ask GPS (do NOT fabricate).
  - SSE order stays: status -> map -> safety -> tokens -> evidence -> done.
  - Tools below are stubs / thin mock wrappers (no external API calls);
    reasoning_trace records WHY each tool was selected (auditable).

Do NOT wire into graph.py / orchestrator.py until human approves direction.
"""

from __future__ import annotations

import os
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Planner contract constants (draft - human to confirm)
# ---------------------------------------------------------------------------

PLANNER_MODEL = os.getenv("ORCA_PLANNER_MODEL", "llama-3.3-70b-versatile")  # Groq primary; <3000ms SLA budget


def _parse_timeout_ms(raw: str | None, default: int = 5000) -> int:
    """Validate ORCA_PLANNER_TIMEOUT_MS once; fall back safely on bad input."""
    try:
        value = int(str(raw) if raw is not None else default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


PLANNER_TIMEOUT_MS: int = _parse_timeout_ms(
    os.getenv("ORCA_PLANNER_TIMEOUT_MS"), 5000
)

CLARIFICATION_THRESHOLD = 0.6  # confidence < 0.6 -> ask GPS, never guess

# Tool ids the planner may select (subset per query - selective dispatch).
TOOL_FIND_FISH = "find_fishing_zones"
TOOL_OCEAN = "check_ocean_state"
TOOL_WEATHER = "check_weather"
TOOL_GEOFENCE = "check_geofence"
KNOWN_TOOLS: tuple[str, ...] = (TOOL_FIND_FISH, TOOL_OCEAN, TOOL_WEATHER, TOOL_GEOFENCE)

# Coastal ports registry (draft - extends fallback.COASTAL_PORTS which
# today only has Kochi/Veraval/Chennai). Coords are approximate WGS84.
COASTAL_PORTS_REGISTRY: dict[str, list[float]] = {
    "Kochi": [9.93, 76.26],
    "Munambam": [10.18, 76.17],
    "Beypore": [11.16, 75.80],
    "Kollam": [8.88, 76.57],
    "Vizag": [17.69, 83.29],  # Visakhapatnam alias
    "Visakhapatnam": [17.69, 83.29],
    "Veraval": [21.60, 69.60],
    "Chennai": [13.08, 80.27],
}

PLANNER_SYSTEM_PROMPT: str = """You are ORCA's dynamic query planner (model: Groq llama-3.3-70b-versatile, budget <5000ms).
Pick the MINIMAL subset of specialist tools needed for the user query. Be deterministic and auditable.

Available tools (exact names):
- find_fishing_zones(lat, lon, radius_km): PFZ discovery. Run when user asks where fish / zones / catch.
- check_ocean_state(zones): waves + currents (OSF). Run when safety/sea/sail question OR when fish zones need a safety badge.
- check_weather(zones): wind + cyclone 500km (IMD). Run when weather/wind/cyclone/safety question OR fish zones need badge.
- check_geofence(zones): EEZ/MPA/IMBL legality. Run ALWAYS when recommending a zone to sail to (Combiner hard-vetoes banned zones).

Coastal ports registry (lat, lon) - resolve port mentions to GPS, record confidence:
- Munambam: 10.18, 76.17
- Beypore: 11.16, 75.80
- Kollam: 8.88, 76.57
- Vizag (Visakhapatnam): 17.69, 83.29
- Veraval: 21.60, 69.60
(Also known: Kochi 9.93, 76.26; Chennai 13.08, 80.27.)

Rules:
1. Output ONLY the PlannerOutput JSON schema (detected_language, target_location{lat,lon,port_name,confidence}, intents, confidence, reasoning_trace, selected_tools).
2. reasoning_trace MUST have one line per selected/skipped tool explaining WHY (auditable).
3. If target_location.confidence < 0.6 or overall confidence < 0.6, select NO tools and ask for GPS (clarification). Never fabricate coordinates.
4. Safety questions without fish intent skip find_fishing_zones; reuse caller-supplied zones.
5. Downstream SSE order is fixed: status -> map -> safety -> tokens -> evidence -> done. Combiner hard-vetoes unsafe/banned zones regardless of planner scores.
6. Keep <500ms: short trace lines, no prose outside schema.
"""


# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------


def _trace_line_refers_to_tool(line: str, tool: str) -> bool:
    """Anchored trace-line attribution: line starts with tool or SELECT/SKIP tool."""
    s = line.strip()
    return s.startswith(tool) or s.startswith(f"SELECT {tool}") or s.startswith(f"SKIP {tool}")


class TargetLocation(BaseModel):
    """Resolved fishing / safety location (None lat/lon = unknown -> clarify)."""

    lat: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    lon: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    port_name: Optional[str] = Field(default=None, description="Matched registry port, if any")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PlannerOutput(BaseModel):
    """LLM planner decision - which tools to run and why (auditable)."""

    detected_language: str = Field(default="en", description="BCP-47-ish code, e.g. en/ml/ta/hi")
    target_location: TargetLocation = Field(default_factory=TargetLocation)
    intents: list[str] = Field(default_factory=list, description="e.g. ['find_fish','check_safety']")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning_trace: list[str] = Field(
        default_factory=list,
        description="One string per tool decision (selected or skipped + why).",
    )
    selected_tools: list[str] = Field(
        default_factory=list,
        description="Subset of [find_fishing_zones, check_ocean_state, check_weather, check_geofence]",
    )

    @field_validator("selected_tools", mode="before")
    @classmethod
    def _known_tools(cls, v: Any) -> list[str]:
        if not v:
            return []
        if not v:
            return []
        unknown = [t for t in v if t not in KNOWN_TOOLS]
        if unknown:
            raise ValueError(f"unknown tools {unknown}; known={list(KNOWN_TOOLS)}")
        # de-dupe, preserve order
        seen: list[str] = []
        for t in v:
            if t not in seen:
                seen.append(t)
        return seen

    def needs_clarification(self, threshold: float = CLARIFICATION_THRESHOLD) -> bool:
        """True when planner must ask for GPS instead of dispatching tools."""
        if self.confidence < threshold:
            return True
        loc = self.target_location
        if loc.lat is None or loc.lon is None:
            return True
        if loc.confidence < threshold:
            return True
        return False

    def to_tool_plan(self) -> list[dict[str, Any]]:
        """Human-readable dispatch plan for demo/logging (no side effects).

        Matches each selected tool to the trace line mentioning it, so
        SKIP lines for non-selected tools never misalign the display.
        Matching is anchored (line starts with the tool name or
        ``SELECT <tool>`` / ``SKIP <tool>``) so a tool name appearing
        mid-sentence never misattributes the line.
        """
        plan: list[dict[str, Any]] = []
        for t in self.selected_tools:
            why = next(
                (line for line in self.reasoning_trace if _trace_line_refers_to_tool(line, t)),
                "",
            )
            plan.append({"tool": t, "why": why})
        return plan


# ---------------------------------------------------------------------------
# Typed tool signatures (PROTOTYPE stubs - mock-only, no external calls)
# ---------------------------------------------------------------------------
# NOTE: names intentionally mirror the 4 specialists. They are thin wrappers
# over backend/ingest/mock_fetchers.py so the demo runs offline. Real wiring
# (PostGIS/OSF/IMD) happens only after human approves this shape.


def find_fishing_zones(lat: float, lon: float, radius_km: float = 80.0) -> dict:
    """Find PFZ zones near (lat, lon) within radius_km using live INCOIS data.

    Live data: delegates to fetch_live_incois_pfz with mock fallback.
    Returns envelope {status, summary, next_actions, artifacts, features}.
    """
    try:
        from backend.ingest.live_fetchers import fetch_live_incois_pfz
        return fetch_live_incois_pfz(sector="SEC005", center_lat=lat, center_lon=lon, count=5)
    except Exception:
        try:
            from backend.ingest.mock_fetchers import mock_fetch_incois_pfz
            return mock_fetch_incois_pfz(sector="SEC005", center_lat=lat, center_lon=lon, count=5)
        except Exception as exc:
            return {
                "status": "success",
                "summary": f"Fallback PFZ near ({lat},{lon}) r={radius_km}km ({exc})",
                "next_actions": ["call combiner"],
                "artifacts": ["data/pfz-today.geojson"],
                "features": [],
            }


def check_ocean_state(zones: list[dict], scenario: str = "normal") -> dict:
    """Wave and ocean current analysis per zone.

    Live data: fetches Open-Meteo Marine API when scenario is normal.
    Fallback: mock_fetch_osf_ocean_state for simulated scenarios.
    """
    if scenario == "normal":
        try:
            from backend.ingest.live_fetchers import fetch_live_ocean_state
            return fetch_live_ocean_state(zones or [])
        except Exception:
            pass
    try:
        from backend.ingest.mock_fetchers import mock_fetch_osf_ocean_state
        return mock_fetch_osf_ocean_state(zones or [], scenario=scenario)
    except Exception as exc:
        return {
            "status": "error",
            "summary": f"Ocean fallback ({exc})",
            "next_actions": ["mark sea unknown, downgrade confidence 0.87->0.62"],
            "artifacts": [],
            "results": [],
        }


def check_weather(zones: list[dict], scenario: str = "normal") -> dict:
    """Wind and cyclone analysis per zone.

    Live data: fetches Open-Meteo Weather API when scenario is normal.
    Fallback: mock_fetch_imd_marine_weather for simulated scenarios.
    """
    if scenario == "normal":
        try:
            from backend.ingest.live_fetchers import fetch_live_marine_weather
            return fetch_live_marine_weather(zones or [])
        except Exception:
            pass
    try:
        from backend.ingest.mock_fetchers import mock_fetch_imd_marine_weather
        return mock_fetch_imd_marine_weather(zones or [], scenario=scenario)
    except Exception as exc:
        return {
            "status": "error",
            "summary": f"Weather fallback ({exc})",
            "next_actions": ["mark weather unknown, downgrade confidence 0.87->0.62"],
            "artifacts": [],
            "results": [],
        }


def check_geofence(zones: list[dict], scenario: str = "normal") -> dict:
    """EEZ / MPA boundary check per zone.

    Live data: verifies spatial polygons against data/eez.geojson & data/mpa.geojson.
    Fallback: mock_check_geofence_boundaries for simulated scenarios.
    """
    if scenario == "normal":
        try:
            from backend.ingest.live_fetchers import fetch_live_geofence_boundaries
            return fetch_live_geofence_boundaries(zones or [])
        except Exception:
            pass
    try:
        from backend.ingest.mock_fetchers import mock_check_geofence_boundaries
        return mock_check_geofence_boundaries(zones or [], scenario=scenario)
    except Exception as exc:
        return {
            "status": "error",
            "summary": f"Geofence fallback ({exc})",
            "next_actions": ["mark geofence unknown, flag potential border risk"],
            "artifacts": [],
            "results": [],
        }




__all__ = [
    "CLARIFICATION_THRESHOLD",
    "COASTAL_PORTS_REGISTRY",
    "KNOWN_TOOLS",
    "PLANNER_MODEL",
    "PLANNER_SYSTEM_PROMPT",
    "PLANNER_TIMEOUT_MS",
    "PlannerOutput",
    "TargetLocation",
    "find_fishing_zones",
    "check_ocean_state",
    "check_weather",
    "check_geofence",
]
