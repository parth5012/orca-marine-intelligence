"""
ORCA LangGraph — Supervisor + Specialized Sub-Agents

Owner: M-A (Agents & Orchestration)
Module: backend/agents/graph.py

Implements SIH26176 Expected Solution as a modular multi-agent
StateGraph. Each specialized agent is a node that *decides* and calls
*tools* to fetch data from heterogeneous sources.

Agents (nodes) vs Tools (stateless fetchers):
  - fish_finder  -> tools: find_pfz_near (PostGIS), _geojson_fallback (haversine)
  - sea_checker -> tools: fetch_osf_wave_current / get_wave_current
  - weather_agent   -> tools: fetch_imd_wind, fetch_imd_cyclones / get_wind, get_cyclone_alert
  - danger_agent -> tools: check_geofence (PostGIS), ray_cast_eez/mpa, distance_to_imbl
  - decision_agent        -> tools: score_zones (combiner.combine_and_rank), citation builder

Supervisor (planner) performs autonomous intent decomposition
(wants_fish, wants_safety per fallback._parse_intent archived baseline) and routes
via Send() for parallel tool-augmented execution.

The deterministic *.py helpers are preserved as TOOL layer so the graph
remains auditable, testable (tests/test_agents.py 41 tests), and
offline-capable. The graph merely demonstrates Agentic AI principles:
planning, reasoning, tool selection, collaboration, explainability.

LangGraph is optional at runtime — when unavailable, orchestrate_via_graph
raises transparently via backend/agents/fallback.py (archived legacy gather,
NotImplementedError) and orchestrate_stream_via_graph emits an explicit SSE
``{type:error, fallback:unknown}`` event (never a silent regex fallback).

Refs:
  PS SIH26176 — ORCA Marine EcOsystem Reasoning with Collaborative Agents
  wayfinder:map#7 — Multi-Agent Orchestration System
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
import time
import uuid
from typing import Any, TypedDict, Annotated
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

# Native-token placeholder guard (#34 review fix 1): raw masked spans
# (``__MBEARING_*__`` / ``__MKNOTS_*__`` / ``__MDIST_*__`` /
# ``__MCOORD_*__``) must NEVER reach the client. ``decision_agent``
# synthesizes via the raw ``google-genai`` SDK (not a LangChain chat
# model), so ``on_chat_model_stream`` fires no events today — verified on
# langgraph 1.1.2. The hook below is kept for a future LangChain chat
# model inside ``decision_agent``; any native text matching this pattern
# is dropped/buffered, never yielded live. Only the VALIDATED
# ``synthesizer_service.iter_reply_tokens`` path yields tokens to SSE.
_NATIVE_PLACEHOLDER_RE = re.compile(r"__M[A-Za-z0-9_]+__")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _degraded_or(a: bool | None, b: bool | None) -> bool:
    """OR reducer for ``degraded`` across Send fan-out branches.

    Ticket #20 (Send fan-out): ``sea_checker`` / ``weather_agent`` /
    ``danger_agent`` run as parallel Send branches converging on
    ``decision_agent``. When >=2 branches return ``degraded`` in the same
    super-step, LangGraph requires a reducer (else ``InvalidUpdateError``).
    Single-writer steps set the value directly; multi-writer steps OR.
    """
    return bool(a) or bool(b)


class ORCAState(TypedDict, total=False):
    # inputs
    query: str
    language: str
    location: dict | None  # explicit GPS
    session_id: str
    # conversational router (chitchat vs marine subgraph)
    route: str | None  # chitchat | marine | None (None = not yet routed)
    chitchat_reply: str | None
    # supervisor outputs
    intent: dict  # {wants_fish, wants_safety}
    user_location: dict | None  # {lat, lon} resolved
    cached_session: dict | None
    degraded: Annotated[bool, _degraded_or]
    # fan-out
    fish_results: list[dict]
    sea_results: list[dict]
    weather_results: list[dict]
    danger_results: list[dict]
    # decision
    combined: dict | None
    best: dict | None
    ranked_zones: list[dict]
    citation: str
    explanation: str
    # final payload fields (mirrors POST /api/chat)
    reply: str
    map: dict
    safety: dict
    evidence: list[str]
    confidence: float
    # masked-LLM synthesis observability (ticket #33, M-A only)
    synthesis_status: str
    synthesis_error: dict | None
    synthesis_elapsed_ms: int
    masked_spans: int
    # LLM supervisor observability (ticket #32, M-A only)
    # Selective dispatch subset of [find_fishing_zones, check_ocean_state,
    # check_weather, check_geofence]. None = legacy/offline run-all.
    selected_tools: list[str] | None
    reasoning_trace: list[str]
    needs_clarification: bool
    clarification_text: str | None
    planner_status: str  # success | fallback_deterministic
    planner_error: dict | None  # explicit SSE error event (fallback:none)
    planner_elapsed_ms: int
    planner_confidence: float

TIMEOUT_S = float(os.getenv("ORCA_NODE_TIMEOUT_S", "15.0"))

# Per-agent tool budget (US-ORCA-014): individual Send branches get 6s via
# asyncio.wait_for; the outer fan-out is bounded by TIMEOUT_S (15s).
PER_AGENT_TIMEOUT_S = float(os.getenv("ORCA_PER_AGENT_TIMEOUT_S", "6.0"))

# Planner LLM call budget (US-ORCA-014): plan_query wrapped in wait_for 5s;
# on timeout the deterministic baseline runs, falling back to Kochi
# {lat: 9.93, lon: 76.26} when no location resolves.
PLANNER_CALL_TIMEOUT_S = float(os.getenv("ORCA_PLANNER_TIMEOUT_MS", "5000")) / 1000.0
KOCHI_FALLBACK_LOCATION = {"lat": 9.93, "lon": 76.26}

# ---------------------------------------------------------------------------
# Lazy imports — keep graph importable even if langgraph not installed
# ---------------------------------------------------------------------------
# Upstream warning: installed langgraph's cache base imports JsonPlusSerializer
# without allowed_objects; ORCA instantiates no cache, so suppress it here.
import warnings
warnings.filterwarnings("ignore", message=".*allowed_objects.*", category=Warning, module=r"langgraph\..*")

try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.graph.message import add_messages  # noqa: F401 (kept for future chat history)
    from langgraph.types import Send

    _HAS_LANGGRAPH = True
except ImportError:
    StateGraph = None  # type: ignore
    START = "START"  # type: ignore
    END = "END"  # type: ignore
    Send = None  # type: ignore
    _HAS_LANGGRAPH = False
    logger.warning("graph: langgraph not installed — supervisor unavailable")

# Legacy deterministic baseline (#35 — archived in fallback.py, NOT orchestrator).
# graph.py lazy baseline is INTENTIONAL offline support (per #32 fix): the LLM
# planner is tried first; these regex helpers run ONLY on plan_query failure
# (surfacing planner_error fallback:none, never silent). Import from fallback
# directly so orchestrator.py primary path stays decommissioned.
try:
    from backend.agents.fallback import (
        COASTAL_PORTS,
        _parse_intent,
        _resolve_location,
        _parse_relative_offset,
        _is_inland,
        _parse_explicit_location,
        _distance_to_coastline_km,
        _haversine_km,
    )
except ImportError:
    # fallback for direct script runs (uvicorn main:app inside backend/)
    from agents.fallback import (  # type: ignore
        COASTAL_PORTS,
        _parse_intent,
        _resolve_location,
        _parse_relative_offset,
        _is_inland,
        _parse_explicit_location,
        _distance_to_coastline_km,
        _haversine_km,
    )

# Shared formatting/degraded helpers (single source of truth: orchestrator).
try:
    from backend.agents.orchestrator import (
        _to_geojson_features,
        _badge_for_best,
        _degraded_sea,
        _degraded_weather,
        _degraded_danger,
        _unknown_danger,
        _chunk_text,
        TIMEOUT_S as ORCH_TIMEOUT,
        DEFAULT_CONFIDENCE,
        DEGRADED_CONFIDENCE,
    )
except ImportError:
    # fallback for direct script runs
    from orchestrator import (  # type: ignore
        _to_geojson_features,
        _badge_for_best,
        _degraded_sea,
        _degraded_weather,
        _degraded_danger,
        _unknown_danger,
        _chunk_text,
        TIMEOUT_S as ORCH_TIMEOUT,
        DEFAULT_CONFIDENCE,
        DEGRADED_CONFIDENCE,
    )
    TIMEOUT_S = ORCH_TIMEOUT

# ---------------------------------------------------------------------------
# Selective-dispatch helpers (ticket #32 — zero-latency passthrough)
# ---------------------------------------------------------------------------

# Planner tool ids (mirror backend/agents/planner_schema.py KNOWN_TOOLS).
# Kept local so graph stays importable even if planner_schema is missing.
TOOL_FIND_FISH = "find_fishing_zones"
TOOL_OCEAN = "check_ocean_state"
TOOL_WEATHER = "check_weather"
TOOL_GEOFENCE = "check_geofence"
_ALL_PLANNER_TOOLS: tuple[str, ...] = (
    TOOL_FIND_FISH,
    TOOL_OCEAN,
    TOOL_WEATHER,
    TOOL_GEOFENCE,
)


def _is_tool_selected(state: ORCAState, tool: str) -> bool:
    """True when the planner selected ``tool`` (or legacy run-all).

    ``selected_tools=None`` = deterministic/offline fallback → run all
    (preserves existing mock/offline paths). An explicit list (incl. [])
    is respected verbatim — non-selected specialists passthrough in <1ms
    with no tool I/O.
    """
    sel = state.get("selected_tools")
    if sel is None:
        return True
    try:
        return tool in sel
    except Exception:
        return True


def _needs_clarification_short_circuit(state: ORCAState) -> bool:
    """True when planner gated clarification — downstream must not run tools."""
    return bool(state.get("needs_clarification"))


def _intent_from_planner_intents(intents: list[str] | None) -> dict | None:
    """Map LLM intent vocabulary to {wants_fish, wants_safety}.

    Returns None when ``intents`` is empty/unknown so callers fall back
    to deterministic ``_parse_intent`` (never emit a dead both-False
    pipeline from an empty LLM list).
    """
    if not intents:
        return None
    lowered = [str(i).strip().lower() for i in intents if isinstance(i, str)]
    wants_fish = any(
        i in ("find_fish", "wants_fish", "find_fishing", "fish", "pfz")
        for i in lowered
    )
    wants_safety = any(
        i
        in (
            "check_safety",
            "wants_safety",
            "check_sea",
            "check_weather",
            "safety",
            "safe",
        )
        for i in lowered
    )
    if not wants_fish and not wants_safety:
        return None
    return {"wants_fish": bool(wants_fish), "wants_safety": bool(wants_safety)}


# ---------------------------------------------------------------------------
# Conversational router — chitchat vs marine subgraph (normal chatbot mode)
# ---------------------------------------------------------------------------

async def conversational_router_node(state: ORCAState) -> dict:
    """Fast deterministic gate (<1ms, no LLM): chitchat vs marine.

    - chitchat (hi/thanks/bye/who-are-you/help with NO marine keywords):
      route=chitchat + canned vernacular chitchat_reply. Downstream marine
      nodes short-circuit; chitchat_responder answers directly.
    - everything else: route=marine, existing planner pipeline runs unchanged.
    Marine keywords always win (e.g. 'hi, fish near Kochi?' -> marine).
    """
    query = state.get("query", "") or ""
    language = state.get("language", "en") or "en"
    try:
        try:
            from backend.agents.conversational_router import (  # type: ignore
                build_chitchat_reply,
                classify_route,
            )
        except ImportError:
            from agents.conversational_router import (  # type: ignore
                build_chitchat_reply,
                classify_route,
            )
        route = classify_route(query)
        chitchat_reply = build_chitchat_reply(query, language) if route == "chitchat" else None
    except Exception:
        route = "marine"
        chitchat_reply = None
    return {"route": route, "chitchat_reply": chitchat_reply, "language": language}


async def chitchat_responder_node(state: ORCAState) -> dict:
    """Direct chatbot answer — no PostGIS/OSF/IMD tools, no combiner.

    Returns POST /api/chat-shaped payload fragments: vernacular reply,
    empty map, no safety banner (None -> frontend hides it), explicit
    evidence that no marine data was used. Never invents coords/metrics.
    """
    reply = state.get("chitchat_reply") or "Hello! Ask me about fishing zones or sea safety."
    language = state.get("language") or "en"
    return {
        "reply": str(reply),
        "explanation": str(reply),
        "map": {"center": None, "pfz_features": [], "route": []},
        "safety": None,
        "evidence": ["conversational reply — no marine data queried"],
        "confidence": 0.99,
        "language": language,
        "combined": None,
        "best": None,
        "ranked_zones": [],
        "citation": "none (chitchat)",
        "synthesis_status": "skipped",
        "synthesis_error": None,
        "synthesis_elapsed_ms": 0,
        "masked_spans": 0,
    }


def route_after_conversational_router(state: ORCAState) -> str:
    """Conditional edge: chitchat -> chitchat_responder, else marine planner."""
    if state.get("route") == "chitchat":
        return "chitchat_responder"
    return "planner"


# ---------------------------------------------------------------------------
# Supervisor / Planner — decides intent + location, selects tools
# ---------------------------------------------------------------------------

async def planner_node(state: ORCAState) -> dict:
    """
    Supervisor/Planner sub-agent (ticket #32 — LLM supervisor wiring).

    Responsibilities (SIH26176: planning, reasoning, tool selection):
      - detect intent (wants_fish, wants_safety) — autonomous decision
      - resolve user_location via tools: explicit GPS > COASTAL_PORTS fast-path > Redis session reuse > relative offset
      - select which downstream agents to invoke (via selected_tools)
      - gate clarification (needs_clarification → short-circuit, no downstream tools)
    Tools conceptually used: _resolve_location (deterministic geocoding), redis.get_session

    Integration (map #30, #31 → #32):
      - Tries Gemini 2.5 Flash Structured Planner
        (backend/agents/planner_service.py :: plan_query, 500ms SLA) first.
      - On success: intent/location/language/selected_tools/reasoning_trace
        come from the LLM PlannerOutput (Code Trumps LLM still holds —
        PostGIS/combiner scoring downstream is never overridden here).
      - On PlannerTimeout/API/Config error: falls back to the deterministic
        baseline below (preserves mock/offline paths) AND surfaces the
        explicit SSE error event via ``planner_error`` (fallback:none) so
        #34 SSE can stream it — never a silent fallback. Non-streaming
        callers keep the deterministic result.
      - Clarification (needs_clarification=True): downstream nodes
        passthrough in <1ms (see _is_tool_selected) and decision_agent +
        orchestrate_via_graph return the vernacular clarification payload
        with explicit evidence.
    """
    query = state.get("query", "") or ""
    location = state.get("location")
    session_id = state.get("session_id") or uuid.uuid4().hex
    language = state.get("language", "en")

    # ---- Lazy deterministic baseline (MAJ-01: only on fallback path) ----
    # Eager baseline previously paid _resolve_location + 1.0s Redis on every
    # query even when plan_query succeeds with its own 50ms history. Now the
    # LLM is tried first; deterministic tools run only on ImportError /
    # plan_query exception, or when LLM coords are missing (fallback).
    async def _deterministic_baseline():
        intent_det = _parse_intent(query)
        # 1. try explicit + port lookup (tool: deterministic geocoding)
        resolved = _resolve_location(query, location)
        cached_session = None
        degraded = False

        # 2. tool: redis.get_session for multi-turn reuse (1.0s, fallback only)
        if resolved is None and session_id:
            try:
                from backend.db import redis as redis_mod  # type: ignore

                try:
                    cached_session = await asyncio.wait_for(redis_mod.get_session(session_id), timeout=1.0)
                except asyncio.TimeoutError:
                    logger.warning("graph.planner: get_session timeout %s", session_id)
                except Exception as exc:
                    logger.warning("graph.planner: get_session failed %s: %s", session_id, exc)
            except Exception:
                cached_session = None

            if isinstance(cached_session, dict) and cached_session.get("lat") is not None:
                try:
                    cached_lat = float(cached_session["lat"])
                    cached_lon = float(cached_session["lon"])
                    # tool: _parse_relative_offset
                    offset = _parse_relative_offset(query, cached_lat, cached_lon)
                    if offset is not None:
                        resolved = offset
                    else:
                        resolved = (cached_lat, cached_lon)
                except Exception as e:
                    logger.warning("graph.planner: cached coords invalid %s: %s", cached_session, e)
                    resolved = None

        user_location_det = {"lat": float(resolved[0]), "lon": float(resolved[1])} if resolved else None
        return intent_det, user_location_det, cached_session, degraded

    # ---- LLM supervisor attempt (500ms SLA, explicit errors) ----
    try:
        from backend.agents.planner_service import (  # type: ignore
            plan_query,
            planner_error_to_sse_event,
        )
    except ImportError as exc:
        logger.warning("graph.planner: planner_service unavailable, deterministic fallback (%s)", exc)
        intent_det, user_location_det, cached_session, degraded = await _deterministic_baseline()
        return {
            "intent": intent_det,
            "user_location": user_location_det,
            "cached_session": cached_session,
            "session_id": session_id,
            "degraded": degraded,
            "query": query,
            "language": language,
            "selected_tools": None,
            "reasoning_trace": [
                f"planner fallback: planner_service unavailable ({exc}) — using deterministic intent/location"
            ],
            "needs_clarification": False,
            "clarification_text": None,
            "planner_status": "fallback_deterministic",
            "planner_error": {
                "type": "error",
                "agent": "planner",
                "message": f"planner_service unavailable ({exc})",
                "fallback": "none",
            },
            "planner_elapsed_ms": 500,
            "planner_confidence": 0.0,
        }

    try:
        envelope = await asyncio.wait_for(
            plan_query(query, language, location, session_id),
            timeout=PLANNER_CALL_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        # Non-fatal planner fallback SSE event (type: status, state: fallback)
        try:
            from backend.agents.planner_service import PlannerTimeoutError as _PTE

            is_timeout = isinstance(exc, (asyncio.TimeoutError, _PTE))
        except ImportError:
            is_timeout = isinstance(exc, asyncio.TimeoutError)
        if is_timeout:
            logger.warning("graph.planner: plan_query timeout %.1fs — Kochi fallback armed", PLANNER_CALL_TIMEOUT_S)
        elapsed_ms = int(getattr(exc, "elapsed_ms", 0) or 500)
        sse_fallback = {
            "type": "status",
            "agent": "planner",
            "state": "fallback",
            "message": "LLM planner unavailable, using fallback advisory",
            "fallback": True,
            "elapsed_ms": elapsed_ms,
        }
        logger.warning("graph.planner: LLM planner failed, deterministic fallback (%s)", exc)
        try:
            intent_det, user_location_det, cached_session, degraded = await _deterministic_baseline()
        except Exception as fb_exc:
            logger.error("graph.planner: deterministic fallback failed (%s)", fb_exc)
            return {
                "intent": None,
                "user_location": location,
                "cached_session": None,
                "session_id": session_id,
                "degraded": True,
                "query": query,
                "language": language,
                "selected_tools": None,
                "reasoning_trace": [
                    f"planner fatal: {exc}; fallback failed: {fb_exc}"
                ],
                "needs_clarification": False,
                "clarification_text": None,
                "planner_status": "error",
                "planner_error": {
                    "type": "error",
                    "agent": "planner",
                    "message": f"planner failed and fallback unavailable ({exc})",
                    "fallback": "none",
                    "elapsed_ms": elapsed_ms,
                },
                "planner_elapsed_ms": elapsed_ms,
                "planner_confidence": 0.0,
            }
        # Inland GPS with no named port: ask for coastal GPS instead of a
        # misleading mid-land PFZ search / DO NOT SAIL.
        _needs_clar = False
        _clar_text = None
        try:
            _exp = _parse_explicit_location(location) if "_parse_explicit_location" in dir() else None
            if user_location_det is None and _exp is not None and _is_inland(float(_exp[0]), float(_exp[1])):
                try:
                    _dist = _distance_to_coastline_km(float(_exp[0]), float(_exp[1]))
                    _dist_s = f" (~{int(round(_dist))}km from the coast)"
                except Exception:
                    _dist_s = ""
                _needs_clar = True
                _clar_text = (
                    f"You're inland{_dist_s} — ORCA tracks marine fishing zones. "
                    "Please share a coastal GPS (latitude, longitude) or mention a nearby "
                    "coastal place like Kochi, Munambam, Beypore, Kollam, Vizag, Veraval, or "
                    "Chennai so I can find safe fishing zones near you."
                )
        except Exception:
            pass
        # US-ORCA-014: planner TIMEOUT with no resolvable location → Kochi
        # fallback (default fishing port) instead of a dead no-location run.
        # Non-timeout failures (e.g. missing API key offline) keep the
        # existing None → clarification-prompt contract. Inland-GPS
        # clarification above takes precedence (never masked).
        if user_location_det is None and not _needs_clar and is_timeout:
            user_location_det = dict(KOCHI_FALLBACK_LOCATION)
            degraded = True
        return {
            "intent": intent_det,
            "user_location": user_location_det,
            "cached_session": cached_session,
            "session_id": session_id,
            "degraded": degraded,
            "query": query,
            "language": language,
            "selected_tools": None,
            "reasoning_trace": [
                f"planner fallback: {exc} using deterministic intent/location"
            ],
            "needs_clarification": _needs_clar,
            "clarification_text": _clar_text,
            "planner_status": "fallback_deterministic",
            "planner_error": sse_fallback,
            "planner_elapsed_ms": elapsed_ms,
            "planner_confidence": 0.0,
        }

    # ---- LLM success: map PlannerOutput → graph state ----
    # MAJ-01: success path uses plan_query's 50ms history only — no 1.0s
    # Redis fetch. Deterministic baseline is computed lazily below only
    # when LLM coords are missing/invalid (fallback) or intent mapping needs
    # it. SEC-01: needs_clarification forces user_location=None (never
    # persist regex coords); clarification prompt still carries place names
    # via clarification_text.
    plan = envelope.get("plan")
    needs_clarification = bool(envelope.get("needs_clarification", False))
    clarification_text = envelope.get("clarification_text")
    elapsed_ms = int(envelope.get("elapsed_ms") or 0)
    try:
        plan_intents = list(getattr(plan, "intents", []) or [])
    except Exception:
        plan_intents = []
    mapped_intent = _intent_from_planner_intents(plan_intents)

    try:
        llm_lat = getattr(getattr(plan, "target_location", None), "lat", None)
        llm_lon = getattr(getattr(plan, "target_location", None), "lon", None)
    except Exception:
        llm_lat = llm_lon = None

    degraded = False
    cached_session = None
    _xcheck_notes: list[str] = []
    if needs_clarification:
        intent = mapped_intent if mapped_intent is not None else _parse_intent(query)
        user_location = None
    else:
        intent = mapped_intent if mapped_intent is not None else _parse_intent(query)
        if llm_lat is not None and llm_lon is not None:
            try:
                user_location = {"lat": float(llm_lat), "lon": float(llm_lon)}
            except (TypeError, ValueError):
                _, user_location_det, cached_det, _deg = await _deterministic_baseline()
                user_location = user_location_det
                cached_session = cached_det
                degraded = bool(_deg)
                if mapped_intent is None:
                    intent = _parse_intent(query)
            else:
                # Cross-check LLM coords vs deterministic port registry ground
                # truth. The LLM may geocode a named port to the wrong place
                # (e.g. Kochi, Japan) or echo stale session coords — a blind
                # trust yields 0 zones and a misleading "No fishing zones"
                # reply for coastal queries that do have data.
                try:
                    _det = _resolve_location(query, location)
                except Exception:
                    _det = None
                if _det is not None:
                    try:
                        _drift = _haversine_km(
                            float(user_location["lat"]), float(user_location["lon"]),
                            float(_det[0]), float(_det[1]),
                        )
                    except Exception:
                        _drift = 0.0
                    if _drift > 50.0:
                        user_location = {"lat": float(_det[0]), "lon": float(_det[1])}
                        _xcheck_notes.append(
                            f"planner cross-check: LLM coords drifted {_drift:.0f}km from "
                            f"registry port; snapped to deterministic fix (auditable)"
                        )
                    # Fuzzy did-you-mean note when deterministic fix came from
                    # a typo correction (e.g. mulambam -> Munambam).
                    try:
                        from backend.agents.fallback import match_port_name as _match_port
                    except ImportError:
                        try:
                            from agents.fallback import match_port_name as _match_port  # type: ignore
                        except ImportError:
                            _match_port = None  # type: ignore
                    if _match_port is not None:
                        try:
                            _fname, _fscore, _ffuzzy = _match_port(query)
                            if _fname and _ffuzzy and _fscore >= 0.8:
                                _xcheck_notes.append(
                                    f"fuzzy port match: did you mean {_fname}? "
                                    f"(score {_fscore:.2f}) — auto-resolved; please confirm"
                                )
                        except Exception:
                            pass
                # Inland LLM fix with no coastal grounding → clarify instead
                # of searching mid-land (0 zones + false DO NOT SAIL).
                try:
                    _inland = _is_inland(float(user_location["lat"]), float(user_location["lon"]))
                except Exception:
                    _inland = False
                if _inland and _det is None:
                    try:
                        _dist = _distance_to_coastline_km(float(user_location["lat"]), float(user_location["lon"]))
                        _dist_s = f" (~{int(round(_dist))}km from the coast)"
                    except Exception:
                        _dist_s = ""
                    needs_clarification = True
                    clarification_text = (
                        f"You're inland{_dist_s} — ORCA tracks marine fishing zones. "
                        "Please share a coastal GPS (latitude, longitude) or mention a nearby "
                        "coastal place like Kochi, Munambam, Beypore, Kollam, Vizag, Veraval, or "
                        "Chennai so I can find safe fishing zones near you."
                    )
                    user_location = None
                    _xcheck_notes.append(
                        "planner cross-check: LLM fix is inland; clarification requested (auditable)"
                    )
        else:
            _, user_location_det, cached_det, _deg = await _deterministic_baseline()
            user_location = user_location_det
            cached_session = cached_det
            degraded = bool(_deg)

    try:
        llm_lang = getattr(plan, "detected_language", None)
    except Exception:
        llm_lang = None
    final_language = llm_lang if isinstance(llm_lang, str) and llm_lang else language

    try:
        selected_tools: list[str] | None = list(getattr(plan, "selected_tools", []) or [])
    except Exception:
        selected_tools = None
    try:
        reasoning_trace: list[str] = list(getattr(plan, "reasoning_trace", []) or [])
    except Exception:
        reasoning_trace = []
    if _xcheck_notes:
        reasoning_trace = list(reasoning_trace) + list(_xcheck_notes)
    try:
        planner_confidence = float(getattr(plan, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        planner_confidence = 0.0

    # Guard: confident plan with empty toolset would deadlock the pipeline
    # (no fish → no decision). Default to full dispatch with an auditable note.
    if not needs_clarification and not selected_tools:
        selected_tools = list(_ALL_PLANNER_TOOLS)
        reasoning_trace = list(reasoning_trace) + [
            "planner note: empty selected_tools on confident plan — defaulted to full dispatch (auditable)"
        ]

    return {
        "intent": intent,
        "user_location": user_location,
        "cached_session": cached_session,
        "session_id": session_id,
        "degraded": degraded,
        "query": query,
        "language": final_language,
        "selected_tools": selected_tools,
        "reasoning_trace": reasoning_trace,
        "needs_clarification": needs_clarification,
        "clarification_text": clarification_text,
        "planner_status": "success",
        "planner_error": None,
        "planner_elapsed_ms": elapsed_ms,
        "planner_confidence": planner_confidence,
    }


# ---------------------------------------------------------------------------
# Specialized sub-agents — each decides + calls its own tools
# ---------------------------------------------------------------------------

async def fish_finder(state: ORCAState) -> dict:
    """
    Fish Finder Agent (SIH26176: marine data discovery).

    Tools:
      - find_pfz_near (PostGIS ST_DWithin) — primary
      - _geojson_fallback (haversine on data/pfz-today.geojson) — fallback
    Decision: radius expansion 80->120->160km autonomously until zones found.
    Selective dispatch (#32): skipped in <1ms (no I/O) when the LLM
    planner omitted ``find_fishing_zones`` (safety-only) or gated
    clarification. ``selected_tools=None`` = legacy run-all.
    """
    # Zero-latency passthrough — no tool I/O, no timeouts.
    if _needs_clarification_short_circuit(state):
        return {"fish_results": []}
    if not _is_tool_selected(state, TOOL_FIND_FISH):
        # MAJ-03: safety-only deadlock guard — sea/weather/danger early-return
        # on empty fish, so provide a synthetic current-location point when any
        # safety tool is selected and user_location is known. Synthetic zone is
        # non-empty so downstream nodes proceed; fish-only consumers never see
        # it (TOOL_FIND_FISH unselected means fish branch is intentionally off).
        try:
            _sel = state.get("selected_tools")
            _safety_on = isinstance(_sel, list) and any(
                t in _sel for t in (TOOL_OCEAN, TOOL_WEATHER, TOOL_GEOFENCE)
            )
        except Exception:
            _safety_on = False
        _ul = state.get("user_location")
        if _safety_on and isinstance(_ul, dict) and _ul.get("lat") is not None and _ul.get("lon") is not None:
            try:
                return {"fish_results": [{"zone_id": "current_location", "place": "Current Location", "lat": float(_ul["lat"]), "lon": float(_ul["lon"])}]}
            except (TypeError, ValueError):
                pass
        return {"fish_results": []}
    user_location = state.get("user_location")
    if not user_location:
        return {"fish_results": []}
    lat = float(user_location["lat"])
    lon = float(user_location["lon"])
    try:
        from backend.agents.subagents import fish_finder as ff  # type: ignore

        res = await asyncio.wait_for(ff.find_fishing_zones(lat=lat, lon=lon, radius_km=80.0), timeout=PER_AGENT_TIMEOUT_S)
        if not isinstance(res, list):
            res = []
        logger.info("graph.fish_finder: %d zones for %.2f,%.2f", len(res), lat, lon)
        return {"fish_results": res}
    except asyncio.TimeoutError:
        logger.warning("graph.fish_finder: timeout %.0fs (agent_progress: timeout, degraded)", PER_AGENT_TIMEOUT_S)
        return {"fish_results": [], "degraded": True}
    except Exception as exc:
        logger.warning("graph.fish_finder: %s", exc)
        return {"fish_results": [], "degraded": True}


async def sea_checker(state: ORCAState) -> dict:
    """
    Sea Checker Agent (SIH26176: ocean analytics).

    Tools:
      - fetch_osf_wave_current / get_wave_current (OSF 06Z Zarr + heuristic fallback)
    Decision: classifies wave <1.5 safe / 1.5-2.5 caution / >2.5 danger, current >2/>3.
    Selective dispatch (#32): skipped in <1ms when planner omitted
    ``check_ocean_state`` (fish-only) or gated clarification.
    """
    if _needs_clarification_short_circuit(state):
        return {"sea_results": []}
    if not _is_tool_selected(state, TOOL_OCEAN):
        # Deselected: shaped unknown (not []) so the combiner degrades to
        # caution instead of misreading absence as data.
        _fish = state.get("fish_results") or []
        if _fish:
            try:
                return {"sea_results": _degraded_sea(_fish)}
            except Exception:
                pass
        return {"sea_results": []}
    fish = state.get("fish_results") or []
    if not fish:
        return {"sea_results": []}
    try:
        from backend.agents.subagents import sea_checker as sc  # type: ignore

        res = await sc.check_sea_conditions(fish)
        return {"sea_results": res if isinstance(res, list) else _degraded_sea(fish)}
    except Exception as exc:
        logger.warning("graph.sea_checker: %s", exc)
        return {"sea_results": _degraded_sea(fish), "degraded": True}


async def weather_agent(state: ORCAState) -> dict:
    """
    Weather Agent (SIH26176: weather intelligence).

    Tools:
      - fetch_imd_wind, fetch_imd_cyclones / get_wind, get_cyclone_alert
    Decision: wind <15 safe / 15-25 caution / >25 danger, cyclone within 500km → danger.
    Selective dispatch (#32): skipped in <1ms when planner omitted
    ``check_weather`` (fish-only) or gated clarification.
    """
    if _needs_clarification_short_circuit(state):
        return {"weather_results": []}
    if not _is_tool_selected(state, TOOL_WEATHER):
        _fish = state.get("fish_results") or []
        if _fish:
            try:
                return {"weather_results": _degraded_weather(_fish)}
            except Exception:
                pass
        return {"weather_results": []}
    fish = state.get("fish_results") or []
    if not fish:
        return {"weather_results": []}
    try:
        from backend.agents.subagents import weather_agent as wa  # type: ignore

        res = await wa.check_weather(fish)
        return {"weather_results": res if isinstance(res, list) else _degraded_weather(fish)}
    except Exception as exc:
        logger.warning("graph.weather_agent: %s", exc)
        return {"weather_results": _degraded_weather(fish), "degraded": True}


async def danger_agent(state: ORCAState) -> dict:
    """
    Danger Agent (SIH26176: geospatial reasoning + risk).

    Tools:
      - check_geofence (PostGIS ST_Contains)
      - ray_cast_eez/mpa (fallback GeoJSON)
      - distance_to_imbl (2km buffer)
    Decision: inside_mpa / outside_eez → danger, within 2km IMBL → caution, emits warnings[].
    Selective dispatch (#32): skipped in <1ms when planner omitted
    ``check_geofence`` or gated clarification.
    """
    if _needs_clarification_short_circuit(state):
        return {"danger_results": []}
    if not _is_tool_selected(state, TOOL_GEOFENCE):
        # Deselected geofence: unknown (inside_eez=None), never a ban.
        _fish = state.get("fish_results") or []
        if _fish:
            try:
                return {"danger_results": _unknown_danger(_fish)}
            except Exception:
                pass
        return {"danger_results": []}
    fish = state.get("fish_results") or []
    if not fish:
        return {"danger_results": []}
    try:
        from backend.agents.subagents import danger_agent as da  # type: ignore

        # Use batch helper if available (preserves order, respects shared points)
        if hasattr(da, "check_safety_batch"):
            res = await da.check_safety_batch(fish)
        else:
            # per-point fallback: no per-agent wait_for — subagents have
            # internal 3.5s single-try fetchers, gather runs parallel.
            async def _one(pt: dict) -> dict:
                lat = pt.get("lat")
                lon = pt.get("lon")
                if lat is None or lon is None:
                    geom = pt.get("geometry") or {}
                    coords = geom.get("coordinates") or []
                    if len(coords) >= 2:
                        lon, lat = coords[0], coords[1]
                if lat is None or lon is None:
                    return {
                        "is_safe": False, "status": "unknown", "warnings": ["missing lat/lon"],
                        "inside_eez": True, "inside_mpa": False, "mpa_name": None,
                    }
                return await da.check_safety(float(lat), float(lon))

            res = list(await asyncio.gather(*(_one(pt) for pt in fish)))
        return {"danger_results": res if isinstance(res, list) else _degraded_danger(fish)}
    except Exception as exc:
        logger.warning("graph.danger_agent: %s", exc)
        return {"danger_results": _degraded_danger(fish), "degraded": True}


async def decision_agent(state: ORCAState) -> dict:
    """
    Decision / Reporting Agent (SIH26176: visualization, reporting, explainability).

    Tools:
      - combiner.combine_and_rank (weighted scoring + citation)
      - lexical_mask.MarineGlossaryMasker (metric masking pre-LLM)
      - synthesizer_service.synthesize_advisory (Gemini 2.5 Flash wording)
    Decision: picks best zone via closest*0.4+safe_sea*0.3+wind_ok*0.2+not_banned*0.1,
              tie-breaker wave→distance, all_unsafe→DO NOT SAIL, INCOIS citation.
    Synthesis (ticket #33, map #30): deterministic combiner scoring/veto is
              Code ground truth; Gemini 2.5 Flash only synthesizes wording
              from masked placeholders (__MBEARING_/__MKNOTS_/__MDIST_/
              __MCOORD_). LLM timeout/fail surfaces an explicit SSE error
              event (fallback:none) — never a silent regex fallback.
    """
    fish = state.get("fish_results") or []
    sea = state.get("sea_results") or []
    weather = state.get("weather_results") or []
    danger = state.get("danger_results") or []
    user_location = state.get("user_location") or {"lat": 0, "lon": 0}
    language = state.get("language") or "en"

    # ---- Clarification short-circuit (ticket #32) ----------------------
    # Planner gated needs_clarification → no downstream tools ran (all
    # passthrough <1ms). Return the vernacular GPS prompt directly with
    # explicit evidence (no silent fallback). Topology stays linear
    # (planner -> fish -> parallel -> decision); skipping is via
    # passthrough, not new edges.
    if bool(state.get("needs_clarification")):
        clarification_text = state.get("clarification_text") or (
            "Please share your GPS location (latitude, longitude) or mention a nearby "
            "coastal place like Kochi, Munambam, Beypore, Kollam, Vizag, Veraval, or "
            "Chennai so I can find safe fishing zones near you."
        )
        # Did-you-mean: ambiguous typo (score 0.6-0.8) gets a targeted ask-back
        # instead of the generic GPS prompt.
        try:
            from backend.agents.fallback import suggest_port as _suggest
        except ImportError:
            try:
                from agents.fallback import suggest_port as _suggest  # type: ignore
            except ImportError:
                _suggest = None  # type: ignore
        if _suggest is not None:
            try:
                _q = state.get("query", "") or ""
                _sname, _sscore = _suggest(_q)
                if _sname and 0.6 <= float(_sscore) < 0.8:
                    clarification_text = (
                        f"Did you mean {_sname}? {clarification_text}"
                    )
            except Exception:
                pass
        reasoning_trace = list(state.get("reasoning_trace") or [])
        evidence_clar: list[str] = ["Clarification requested — GPS/location required for PFZ search"]
        for line in reasoning_trace:
            if isinstance(line, str) and line and line not in evidence_clar:
                evidence_clar.append(line)
        return {
            "combined": None,
            "best": None,
            "ranked_zones": [],
            "citation": "INCOIS TextData (no zones — clarification requested)",
            "explanation": str(clarification_text),
            "reply": str(clarification_text),
            "map": {"center": None, "pfz_features": [], "route": []},
            "safety": {"waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber"},
            "evidence": evidence_clar,
            "confidence": DEGRADED_CONFIDENCE,
            "synthesis_status": "skipped",
            "synthesis_error": None,
            "synthesis_elapsed_ms": 0,
            "masked_spans": 0,
        }

    try:
        from backend.agents import combiner as cb  # type: ignore

        combined = cb.combine_and_rank(
            fish_results=fish, sea_results=sea, weather_results=weather,
            danger_results=danger, user_location=user_location,
        )
    except Exception as exc:
        logger.error("graph.decision: combiner failed %s", exc)
        combined = {
            "ranked_zones": [], "best": None,
            "explanation": f"Combiner error: {exc}",
            "citation": "INCOIS TextData", "all_unsafe": False, "score_breakdown": {},
        }

    best = combined.get("best")
    ranked = combined.get("ranked_zones") or []
    citation = combined.get("citation") or "INCOIS TextData"
    explanation = combined.get("explanation") or ""

    # Build payload fragments (mirrors orchestrator._to_geojson_features etc.)
    pfz_features = _to_geojson_features(ranked)
    if best and best.get("lat") is not None:
        try:
            center = [float(best["lon"]), float(best["lat"])]
            route = [[float(user_location["lon"]), float(user_location["lat"])], [float(best["lon"]), float(best["lat"])]]
        except Exception:
            center = [float(user_location["lon"]), float(user_location["lat"])]
            route = []
    else:
        center = [float(user_location["lon"]), float(user_location["lat"])] if user_location else None
        route = []

    # safety badge reasoning — autonomous decision per sub-agent outputs.
    # Empty result lists mean "unknown" (skipped/failed checks), never safe.
    if best:
        sea_s = "safe" if sea else "unknown"
        wind_s = "safe" if weather else "unknown"
        danger_s = "safe" if danger else "unknown"
        best_id = str(best.get("zone_id")) if best.get("zone_id") else None
        for r in sea:
            if str(r.get("zone_id")) == best_id:
                sea_s = str(r.get("status") or r.get("wave_status") or "safe").lower()
                break
        for r in weather:
            if str(r.get("zone_id")) == best_id:
                wind_s = str(r.get("status") or r.get("wind_status") or "safe").lower()
                break
        for r in danger:
            if best_id and str(r.get("zone_id")) == best_id:
                danger_s = str(r.get("status") or "safe").lower()
                break
        badge = _badge_for_best(best, sea_s, wind_s, danger_s)
        if "unknown" in (sea_s, wind_s, danger_s):
            badge = "amber"
        waves_m = best.get("wave_height_m")
        wind_kts = best.get("wind_kt") if best.get("wind_kt") is not None else best.get("wind_speed_kt")
        danger_field = "none" if danger_s == "safe" else danger_s
        if "unknown" in (sea_s, wind_s, danger_s):
            danger_field = "unknown" if danger_field == "none" else danger_field
        # Veto parity: combiner all_unsafe / banned (outside EEZ, inside MPA)
        # must force red+DANGER even when per-zone danger lookup missed
        # (e.g. zone_id mismatch) — badge previously stayed green vs DO NOT SAIL text.
        try:
            _veto = bool((combined or {}).get("all_unsafe"))
        except Exception:
            _veto = False
        _b = best or {}
        try:
            _banned = bool(_b.get("inside_mpa")) or (_b.get("inside_eez") is False)
        except Exception:
            _banned = False
        if _veto or _banned:
            badge = "red"
            danger_field = "danger"
        safety = {"waves_m": waves_m, "wind_kts": wind_kts, "danger": danger_field, "badge": badge}
    else:
        safety = {"waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber"}

    evidence: list[str] = []
    if citation:
        evidence.append(str(citation))
    if sea and isinstance(sea[0], dict):
        src = sea[0].get("source")
        if src and src != "unknown":
            evidence.append(f"Wave: {src}")
    if weather and isinstance(weather[0], dict):
        src = weather[0].get("source")
        if src and src != "unknown":
            evidence.append(f"Wind: {src}")
    if danger and isinstance(danger[0], dict):
        warnings = danger[0].get("warnings") or []
        for w in warnings:
            if "unavailable" not in w.lower():
                evidence.append(str(w))
        if not any("MPA" in e or "EEZ" in e for e in evidence):
            evidence.append("No EEZ/MPA violation")

    # Evidence & trace propagation (ticket #32): planner reasoning_trace
    # rides in graph state and is appended to final evidence citations
    # (after the INCOIS citation so evidence[0] stays stable for tests).
    try:
        _trace = state.get("reasoning_trace") or []
        for _line in _trace:
            if isinstance(_line, str) and _line and _line not in evidence:
                evidence.append(_line)
    except Exception:
        pass

    degraded = bool(state.get("degraded"))
    confidence = DEGRADED_CONFIDENCE if degraded or not best else DEFAULT_CONFIDENCE

    # ---- Masked LLM advisory synthesis (ticket #33) ---------------------
    # Req 1: explicit metric lexical masking in decision_agent using
    # lexical_mask.py (bearings/knots/distances/coords -> __M*__).
    # Req 2-4: Gemini 2.5 Flash wording via synthesizer_service with
    # strict DO NOT SAIL veto + unmask/post-validate + explicit error.
    # 12s SLA budget per call with a single bounded retry on timeout only.
    # Code Trumps LLM: deterministic `explanation` stays ground truth;
    # LLM output only becomes `reply` after validation. On LLM failure
    # reply falls back to the deterministic explanation BUT the failure
    # is surfaced explicitly via `synthesis_error` (SSE error event,
    # fallback:none) — never a silent regex swap.
    synthesis_status = "skipped"
    synthesis_error: dict | None = None
    synthesis_elapsed_ms = 0
    masked_spans = 0
    reply_text = explanation or "No fishing zones found nearby. Try expanding the search area."
    # ARCH-01: avoid double masking — the synthesis path reuses the envelope
    # table for masked_spans; preview-mask only the skipped path.
    if best is None or not explanation:
        try:
            from backend.agents.lexical_mask import MarineGlossaryMasker

            _masker = MarineGlossaryMasker()
            _masked_preview, _mask_table = _masker.mask(explanation or "")
            masked_spans = len(_mask_table)
        except Exception as exc:
            logger.warning("graph.decision: lexical mask preview failed %s", exc)
            masked_spans = 0
    if best is not None and explanation:
        try:
            from backend.agents import synthesizer_service as _synth
            from backend.agents.synthesizer_service import (
                SynthesizerTimeoutError as _SynthTimeout,
            )

            # Total synthesis budget envelope (initial + retry) so the
            # decision_agent node never blows NODE_TIMEOUT_S.  The first
            # call gets at most SYNTHESIZER_TIMEOUT_S; a retry gets only
            # the remaining budget — never a fresh 12s clock.
            _SYNTH_TOTAL_BUDGET_S = float(os.getenv(
                "ORCA_SYNTH_TOTAL_BUDGET_S",
                str(TIMEOUT_S),
            ))
            _SYNTH_TOTAL_BUDGET_S = min(_SYNTH_TOTAL_BUDGET_S, TIMEOUT_S)
            _initial_synth_budget = min(
                _SYNTH_TOTAL_BUDGET_S,
                _synth.SYNTHESIZER_TIMEOUT_S,
            )
            _synth_t0 = time.perf_counter()

            try:
                _envelope = await _synth.synthesize_advisory(
                    combined, language=language, user_location=user_location,
                    timeout_s=_initial_synth_budget,
                )
            except _SynthTimeout as _tmo:
                # Single bounded retry on synthesizer timeout only: one
                # immediate second call, same args — no loop, no sleep.
                # APIError/ConfigError are NOT retried.
                # Budget: retry gets ONLY the remaining envelope time.
                _retry_remaining = _SYNTH_TOTAL_BUDGET_S - (time.perf_counter() - _synth_t0)
                if _retry_remaining < 1.0:
                    raise  # no budget left for a meaningful retry
                logger.warning("graph.decision: synthesis timed out (%.1fs left), retrying once: %s", _retry_remaining, _tmo)
                _envelope = await _synth.synthesize_advisory(
                    combined, language=language, user_location=user_location,
                    timeout_s=min(_retry_remaining, _synth.SYNTHESIZER_TIMEOUT_S),
                )
            _llm_reply = str(_envelope.get("reply") or "").strip()
            if _llm_reply:
                reply_text = _llm_reply
            synthesis_status = "success"
            synthesis_elapsed_ms = int(_envelope.get("elapsed_ms") or 0)
            masked_spans = len(_envelope.get("table") or {})
        except Exception as exc:
            # No Silent Fallback: surface the explicit SSE error event.
            synthesis_status = "error"
            try:
                from backend.agents.synthesizer_service import (
                    SynthesizerError,
                    synthesizer_error_to_sse_event,
                )

                synthesis_error = synthesizer_error_to_sse_event(exc)
                if isinstance(exc, SynthesizerError):
                    synthesis_elapsed_ms = int(getattr(exc, "elapsed_ms", 0) or 0)
            except Exception:
                from backend.agents.synthesizer_service import _scrub_secrets as _scrub

                synthesis_error = {
                    "type": "error",
                    "agent": "decision_agent",
                    "message": _scrub(f"synthesizer failed: {exc}"),
                    "fallback": "none",
                }
            logger.warning("graph.decision: synthesis failed, keeping deterministic reply: %s", exc)

    # Did-you-mean confirmation on auto-resolved typos: surface in the reply
    # so the fisher can confirm (trace line already rides in evidence).
    try:
        _trace_all = list(state.get("reasoning_trace") or [])
        _fuzzy_canon: str | None = None
        for _ln in _trace_all:
            if isinstance(_ln, str) and _ln.startswith("fuzzy port match:"):
                import re as _re2

                _m = _re2.search(r"did you mean ([A-Za-z]+)", _ln)
                if _m:
                    _fuzzy_canon = _m.group(1)
                    break
                _m2 = _re2.search(r"~\s*([A-Za-z]+)", _ln)
                if _m2:
                    _fuzzy_canon = _m2.group(1)
                    break
        if _fuzzy_canon and best is not None:
            _prefix = f"Did you mean {_fuzzy_canon}? Showing zones for {_fuzzy_canon} - please confirm. "
            if _prefix.strip().lower() not in str(reply_text).lower():
                reply_text = _prefix + str(reply_text)
                explanation = _prefix + str(explanation)
    except Exception:
        pass

    return {
        "combined": combined,
        "best": best,
        "ranked_zones": ranked,
        "citation": citation,
        "explanation": explanation,
        "reply": reply_text,
        "map": {"center": center, "pfz_features": pfz_features, "route": route},
        "safety": safety,
        "evidence": evidence,
        "confidence": confidence,
        "synthesis_status": synthesis_status,
        "synthesis_error": synthesis_error,
        "synthesis_elapsed_ms": synthesis_elapsed_ms,
        "masked_spans": masked_spans,
    }


# ---------------------------------------------------------------------------
# Parallel collaborative analysis — sub-agents run concurrently via tools
# ---------------------------------------------------------------------------

async def parallel_analysis_node(state: ORCAState) -> dict:
    """
    Collaborative analysis node — DEPRECATED as a graph node (ticket #20).

    Kept as a direct-call helper (same ``asyncio.gather`` over the SAME
    fish_results, shared list per ORCA_GeoJSON_Architecture.md) for
    backward compatibility. The compiled graph no longer routes through
    this node — ``fish_finder`` fans out via LangGraph ``Send()`` to the
    ``sea_checker`` / ``weather_agent`` / ``danger_agent`` nodes instead
    (see :func:`route_after_fish_finder`), so each sub-agent is a discrete
    LangSmith span. Direct callers get identical merge semantics
    (``degraded`` OR-propagated).

    Each sub-agent decides autonomously and calls its own tools:
      sea_checker -> get_wave_current (OSF/heuristic)
      weather_agent -> get_wind / get_cyclone_alert
      danger_agent -> check_geofence / ray_cast

    Selective dispatch (#32): individual specialists already passthrough
    in <1ms when unselected; this node short-circuits immediately on
    clarification so no gather overhead is paid.
    """
    if _needs_clarification_short_circuit(state):
        return {"sea_results": [], "weather_results": [], "danger_results": []}
    # Run 3 agents concurrently — true parallel, not sequential Send.
    # Outer 10s budget (US-ORCA-014); each branch already carries its own
    # 6s per-agent wait_for (Send-level), surfacing degraded on timeout.
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                sea_checker(state),
                weather_agent(state),
                danger_agent(state),
            ),
            timeout=TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "graph.parallel_analysis: outer fan-out timeout %.0fs (agent_progress: timeout, degraded)",
            TIMEOUT_S,
        )
        return {
            "sea_results": _degraded_sea(state.get("fish_results") or []),
            "weather_results": _degraded_weather(state.get("fish_results") or []),
            "danger_results": _degraded_danger(state.get("fish_results") or []),
            "degraded": True,
        }
    merged: dict = {}
    for r in results:
        merged.update(r)
        # propagate degraded flag if any sub-agent degraded
        if r.get("degraded"):
            merged["degraded"] = True
    return merged


def route_after_fish_finder(state: ORCAState):
    """Conditional Send fan-out after ``fish_finder`` (ticket #20).

    True Agentic AI parallel dispatch in graph topology (visible as
    discrete ``sea_checker`` / ``weather_agent`` / ``danger_agent`` spans
    in the LangSmith trace) while preserving mock compatibility and the
    #32 selective-dispatch contract:

    - Clarification short-circuit (``needs_clarification``) routes
      straight to ``decision_agent`` (string route — full state preserved,
      zero tool I/O downstream).
    - Only the planner-selected tools are Sent to; unselected specialists
      are never invoked (zero I/O by construction, stronger than the
      <1ms in-node passthrough which remains as a direct-call guard).
    - ``selected_tools=None`` (legacy/offline run-all) Sends to all three.
    - No selection at all (empty after guards) routes to ``decision_agent``.

    Send isolation note (verified on langgraph 1.1.2): a ``Send`` target
    sees ONLY its ``arg`` payload, not the parent state — so the shared
    ``fish_results`` (+ selection/location/clarification flags the workers
    read) are forwarded explicitly. Worker outputs merge back into the
    main state; ``decision_agent`` (reached via static worker edges, or via
    the direct string route) always sees the full merged state.
    """
    if _needs_clarification_short_circuit(state):
        return "decision_agent"
    wants_ocean = _is_tool_selected(state, TOOL_OCEAN)
    wants_weather = _is_tool_selected(state, TOOL_WEATHER)
    wants_geofence = _is_tool_selected(state, TOOL_GEOFENCE)
    if not (wants_ocean or wants_weather or wants_geofence):
        return "decision_agent"
    if Send is None:  # pragma: no cover — langgraph unavailable
        return "decision_agent"
    _sel = state.get("selected_tools")
    base: dict = {
        "fish_results": list(state.get("fish_results") or []),
        "selected_tools": list(_sel) if isinstance(_sel, list) else None,
        "needs_clarification": bool(state.get("needs_clarification")),
        # Read-only for workers (lat/lon) — pass reference, never mutated.
        "user_location": state.get("user_location"),
    }
    sends: list = []
    if wants_ocean:
        sends.append(Send("sea_checker", dict(base)))
    if wants_weather:
        sends.append(Send("weather_agent", dict(base)))
    if wants_geofence:
        sends.append(Send("danger_agent", dict(base)))
    if not sends:  # defensive — never deadlock the pipeline
        return "decision_agent"
    return sends


def build_orca_graph():
    """
    Build and compile the ORCA StateGraph.

    Nodes (SIH26176): planner (supervisor, tool: redis + geocoding)
      -> fish_finder (tools: PostGIS + GeoJSON)
      -> Send fan-out to {sea_checker, weather_agent, danger_agent}
         (each with own tools, conditional on selected_tools)
      -> decision_agent (tool: combiner)

    Parallelism is true LangGraph ``Send()`` fan-out from ``fish_finder``
    (auditable per-agent LangSmith spans, mock-friendly, P95<2s).
    ``parallel_analysis_node`` is retained only as a direct-call helper;
    it is NOT part of the compiled topology.

    Returns:
      CompiledGraph or None if langgraph not installed.
    """
    if not _HAS_LANGGRAPH or StateGraph is None:
        logger.warning("build_orca_graph: langgraph not installed — returning None")
        return None

    graph = StateGraph(ORCAState)

    graph.add_node("conversational_router", conversational_router_node)
    graph.add_node("chitchat_responder", chitchat_responder_node)
    graph.add_node("planner", planner_node)
    graph.add_node("fish_finder", fish_finder)
    graph.add_node("sea_checker", sea_checker)
    graph.add_node("weather_agent", weather_agent)
    graph.add_node("danger_agent", danger_agent)
    graph.add_node("decision_agent", decision_agent)

    graph.add_edge(START, "conversational_router")
    graph.add_conditional_edges("conversational_router", route_after_conversational_router)
    graph.add_edge("chitchat_responder", END)
    graph.add_edge("planner", "fish_finder")
    graph.add_conditional_edges("fish_finder", route_after_fish_finder)
    graph.add_edge("sea_checker", "decision_agent")
    graph.add_edge("weather_agent", "decision_agent")
    graph.add_edge("danger_agent", "decision_agent")
    graph.add_edge("decision_agent", END)

    return graph.compile()


# Singleton compiled graph (lazy)
_compiled_graph = None

def get_orca_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_orca_graph()
    return _compiled_graph


# ---------------------------------------------------------------------------
# Convenience wrappers — mirror orchestrator.py API but via graph
# ---------------------------------------------------------------------------

async def orchestrate_via_graph(
    query: str,
    language: str = "en",
    location: dict | None = None,
    session_id: str | None = None,
) -> dict:
    """
    Run the full LangGraph pipeline and return POST /api/chat payload.

    No Silent Fallback (#35): when the compiled graph is unavailable
    (langgraph not installed) this raises transparently via the archived
    ``fallback.fallback_orchestrate`` (NotImplementedError) instead of
    recursing into orchestrator or masking the failure with regex heuristics.
    """
    graph = get_orca_graph()
    if graph is None:
        # Transparent failure — legacy gather is archived in fallback.py
        # (offline/edge only, raises NotImplementedError). Never recurse
        # into orchestrator.orchestrate (infinite loop) or regex heuristics.
        from backend.agents.fallback import fallback_orchestrate as _archived_fallback  # type: ignore

        return await _archived_fallback(query, language, location, session_id)

    sid = session_id or uuid.uuid4().hex
    init_state: ORCAState = {
        "query": query or "",
        "language": language or "en",
        "location": location,
        "session_id": sid,
    }

    meta_location = None
    if isinstance(location, dict):
        meta_location = {
            "has_coords": bool(location.get("lat") or location.get("latitude")),
            "port": location.get("port") or location.get("name"),
        }

    runnable_config: RunnableConfig = {
        "run_name": "orca_agentic_supervisor",
        "tags": ["orca", "marine-intelligence", "sih26176", language or "en"],
        "metadata": {
            "session_id": sid,
            "location": meta_location,
            "scenario": os.getenv("ORCA_SCENARIO", "normal"),
            "language": language or "en",
        },
    }

    # Handle no-location early (planner will set user_location=None)
    final = await graph.ainvoke(init_state, config=runnable_config)

    # ---- Chitchat short-circuit (conversational router) ---------------
    # Normal chatbot mode: direct vernacular reply, no marine tools ran.
    # Empty map + safety None (frontend hides map highlight + banner).
    if final.get("route") == "chitchat":
        sid = final.get("session_id") or init_state["session_id"]
        reply = str(final.get("chitchat_reply") or final.get("reply") or "")
        return {
            "reply": reply,
            "map": {"center": None, "pfz_features": [], "route": []},
            "safety": None,
            "evidence": ["conversational reply — no marine data queried"],
            "language": final.get("language") or language,
            "confidence": 0.99,
            "session_id": sid,
            "route": "chitchat",
            "intent": {"wants_fish": False, "wants_safety": False},
            "needs_clarification": False,
            "selected_tools": [],
            "reasoning_trace": ["conversational_router: chitchat — marine subgraph skipped"],
        }

    # ---- Clarification short-circuit (ticket #32) ---------------------
    # Planner gated needs_clarification → vernacular GPS prompt, no
    # downstream tools ran. Explicit evidence (no silent fallback).
    if bool(final.get("needs_clarification")):
        sid = final.get("session_id") or init_state["session_id"]
        clarification_text = final.get("clarification_text") or (
            "Please share your GPS location (latitude, longitude) or mention a nearby "
            "coastal place like Kochi, Munambam, Beypore, Kollam, Vizag, Veraval, or "
            "Chennai so I can find safe fishing zones near you."
        )
        reasoning_trace = list(final.get("reasoning_trace") or [])
        evidence_clar: list[str] = ["Clarification requested — GPS/location required for PFZ search"]
        for _line in reasoning_trace:
            if isinstance(_line, str) and _line and _line not in evidence_clar:
                evidence_clar.append(_line)
        # Merge decision_agent evidence when present (already includes trace).
        for _e in final.get("evidence") or []:
            if _e not in evidence_clar:
                evidence_clar.append(str(_e))
        return {
            "reply": str(clarification_text),
            "map": {"center": None, "pfz_features": [], "route": []},
            "safety": {"waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber"},
            "evidence": evidence_clar,
            "language": final.get("language") or language,
            "confidence": DEGRADED_CONFIDENCE,
            "session_id": sid,
            "intent": final.get("intent") or {"wants_fish": True, "wants_safety": True},
            "needs_clarification": True,
            "clarification_text": str(clarification_text),
            "selected_tools": final.get("selected_tools"),
            "reasoning_trace": reasoning_trace,
            "planner_status": final.get("planner_status"),
            "planner_error": final.get("planner_error"),
            "planner_elapsed_ms": final.get("planner_elapsed_ms"),
            "planner_confidence": final.get("planner_confidence"),
        }

    # If planner could not resolve location, return prompting payload (no fish branch)
    if not final.get("user_location"):
        sid = final.get("session_id") or init_state["session_id"]
        return {
            "reply": "Please share your GPS location or mention a coastal place like Kochi, Veraval, or Chennai to find nearby fishing zones.",
            "map": {"center": None, "pfz_features": [], "route": []},
            "safety": {"waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber"},
            "evidence": ["Location not provided — cannot search PFZ zones"],
            "language": final.get("language") or language,
            "confidence": DEGRADED_CONFIDENCE,
            "session_id": sid,
            "intent": final.get("intent") or {"wants_fish": True, "wants_safety": True},
            "needs_clarification": bool(final.get("needs_clarification", False)),
            "selected_tools": final.get("selected_tools"),
            "reasoning_trace": list(final.get("reasoning_trace") or []),
            "planner_status": final.get("planner_status"),
            "planner_error": final.get("planner_error"),
            "planner_elapsed_ms": final.get("planner_elapsed_ms"),
            "planner_confidence": final.get("planner_confidence"),
        }

    # Persist session (best-effort, mirrors orchestrator)
    try:
        from backend.db import redis as redis_mod  # type: ignore

        best = final.get("best")
        cached = final.get("cached_session")
        turn_history: list[dict] = []
        if isinstance(cached, dict) and isinstance(cached.get("turn_history"), list):
            turn_history = list(cached["turn_history"])
        turn_history.append({
            "query": query,
            "zone_id": best.get("zone_id") if isinstance(best, dict) else None,
            "place": best.get("place") if isinstance(best, dict) else None,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "reply_summary": (final.get("reply") or "")[:200],
        })
        if len(turn_history) > 20:
            turn_history = turn_history[-20:]
        session_data = {
            "lat": float(final["user_location"]["lat"]),
            "lon": float(final["user_location"]["lon"]),
            "zone_id": best.get("zone_id") if isinstance(best, dict) else None,
            "place": best.get("place") if isinstance(best, dict) else None,
            "last_advisory_summary": (final.get("reply") or "")[:500],
            "turn_history": turn_history,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if isinstance(cached, dict) and cached.get("vessel_type") is not None:
            session_data["vessel_type"] = cached.get("vessel_type")
        try:
            await asyncio.wait_for(redis_mod.save_session(final["session_id"], session_data, ttl_seconds=86400), timeout=1.0)
        except Exception:
            pass
    except Exception:
        pass

    return {
        "reply": final.get("reply") or final.get("explanation") or "",
        "map": final.get("map") or {"center": None, "pfz_features": [], "route": []},
        "safety": final.get("safety") or {"waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber"},
        "evidence": final.get("evidence") or [final.get("citation") or "INCOIS TextData"],
        "language": final.get("language") or language,
        "confidence": final.get("confidence") or (DEGRADED_CONFIDENCE if final.get("degraded") else DEFAULT_CONFIDENCE),
        "session_id": final.get("session_id"),
        "intent": final.get("intent"),
        "combined": final.get("combined"),  # for debugging
        "needs_clarification": bool(final.get("needs_clarification", False)),
        "selected_tools": final.get("selected_tools"),
        "reasoning_trace": list(final.get("reasoning_trace") or []),
        "planner_status": final.get("planner_status"),
        "planner_error": final.get("planner_error"),
        "planner_elapsed_ms": final.get("planner_elapsed_ms"),
        "planner_confidence": final.get("planner_confidence"),
    }


async def orchestrate_stream_via_graph(
    query: str,
    language: str = "en",
    location: dict | None = None,
    session_id: str | None = None,
):
    """
    SSE streaming via ``graph.astream_events`` v2 (wayfinder #34, map #30).

    Hooks the LLM Advisory Synthesizer
    (``backend/agents/synthesizer_service.py``) into the stream so advisory
    tokens flow real-time under strict SSE ordering.

    Intended event order (docs/API.md strict):
      status* -> map -> safety -> token+ -> evidence -> done
    (``error`` events may appear anywhere on timeout/failure and are ignored
    for ordering purposes.)

    Strategy:
      - Consume ``graph.astream_events(init_state, version='v2')``.
      - ``on_chat_model_stream`` (native, LangChain chat-model chunks) is
        parsed via ``synthesizer_service.extract_native_token_text`` and
        streamed directly. Chunks arriving before ``map``+``safety`` are
        BUFFERED in ``token_buf`` and flushed in order right after
        ``safety`` so strict ordering always holds.
      - ``on_chain_start`` for known nodes -> ``status/running`` (only while
        no ``map`` has been emitted yet, to preserve the strict order above).
      - ``on_chain_end`` for ``fish_finder`` -> ``status/done`` +
        immediate provisional ``map`` (early flyTo) built from raw fish
        results.
      - ``on_chain_end`` for ``parallel_analysis`` (current topology runs the
        3 sea/weather/danger sub-agents inside one node via
        ``asyncio.gather``, so per-sub-agent events do NOT exist) -> stash
        sea/weather/danger, then single provisional ``safety`` (via combiner).
      - ``on_chain_end`` for ``decision_agent`` -> flush buffered native
        tokens, then stream the VALIDATED synthesizer reply via
        ``synthesizer_service.iter_reply_tokens`` (word-boundary chunks over
        the validated ``reply``). Native path is primary when present;
        validated chunking is the graceful degrade when no native tokens
        arrived (no duplication — chunked replay is skipped if native
        tokens were already streamed).
      - After the stream drains -> ``evidence`` -> ``done``.
      - No-location path (planner yields no user_location) uses empty map /
        amber safety / location-prompt tokens, same order.
      - ``graph is None`` emits a transparent ``{type:error,
        fallback:unknown}`` event (#35, never a silent regex fallback).
        If the installed langgraph lacks ``astream_events`` (pre-1.x),
        degrade gracefully to non-streaming ``orchestrate_via_graph`` +
        validated chunk replay while preserving ordering + buffering.

    Timeouts (map decision #26: 1.4s sub-agent budget, P95<2.0s):
      per-node budget is OBSERVED only — an ``error`` event is emitted when a
      node exceeds 1.4s but the slow node is NOT preempted (LangGraph stream
       mode has no per-node cancel; true preemption needs Send fan-out +
       per-task wait_for like the archived fallback gather). Total P95 is logged,
      not enforced — early provisional ``map``/``safety`` keep TTFB <1.4s
      even when the synthesizer uses its full 1.4s SLA.

    Native-degrade note (ticket #34): ``astream_events`` v2 IS available
    (langgraph 1.1.2) and the ``on_chat_model_stream`` hook below is live.
    ``decision_agent`` synthesizes via the raw ``google-genai`` SDK (not a
    LangChain chat model), so no native token events fire today — verified
    on the installed version. Validated chunk replay
    (``iter_reply_tokens`` over the ``synthesize_advisory`` reply, which
    enforces veto/numbers/citation BEFORE any SSE token) therefore carries
    tokens with identical ordering + buffering semantics. The native hook
    activates automatically if a LangChain chat model is ever embedded
    inside ``decision_agent`` (no streaming-path change needed).

    Error preservation (#32/#33 — do NOT regress):
      - ``planner_error`` (``fallback:none``) is yielded verbatim right after
        the planner ``on_chain_end`` (surfacing, not blocking).
      - ``synthesis_error`` (``fallback:none``) is yielded verbatim right
        after decision tokens (deterministic combiner reply already streamed
        as tokens; the error explains the LLM failure, never a silent
        regex swap).

    Tradeoffs carried from the #27 prototype:
      1. Strict order vs full status coverage: statuses after the early ``map``
         are SUPPRESSED (parallel/decision dones) so the ``status* -> map``
         assertion holds.
      2. ``safety`` before ``decision_agent`` finishes is PROVISIONAL (own
         combiner call, duplicates decision work). Final decision safety may
         differ; we do not re-emit.
      3. Node names match docs/API.md SSE agent names
         (fish_finder/sea_checker/weather_agent/danger_agent).
      4. Streaming path persists Redis session best-effort (mirrors
         non-streaming path) before done.
    """
    graph = get_orca_graph()
    if graph is None:
        # Transparent error (#35): langgraph unavailable. Emit explicit SSE
        # error (fallback:unknown) — never recurse into
        # orchestrator.orchestrate_stream (infinite loop) or regex heuristics.
        logger.warning("graph.stream: langgraph not installed — emitting transparent error")
        yield {
            "type": "error",
            "agent": "orchestrator",
            "message": "stream failed: langgraph not installed (graph unavailable)",
            "fallback": "unknown",
        }
        return

    # Graceful degrade: very old langgraph without astream_events — replay
    # the non-streaming result as ordered SSE (map/safety/tokens/evidence).
    if not hasattr(graph, "astream_events"):
        logger.warning("graph.stream: astream_events unavailable, degrading to chunked replay")
        _fb = await orchestrate_via_graph(query, language, location, session_id)
        _fb_perr = _fb.get("planner_error")
        if isinstance(_fb_perr, dict) and (_fb_perr.get("state") == "fallback" or _fb_perr.get("type") == "error"):
            yield dict(_fb_perr)
        else:
            yield {"type": "status", "agent": "planner", "state": "done", "elapsed_ms": 0}
        _fb_map = _fb.get("map") if isinstance(_fb.get("map"), dict) else {}
        yield {
            "type": "map",
            "center": _fb_map.get("center"),
            "pfz_features": _fb_map.get("pfz_features") or [],
            "route": _fb_map.get("route") or [],
        }
        _fb_safety = _fb.get("safety") if isinstance(_fb.get("safety"), dict) else {}
        yield {
            "type": "safety",
            "waves_m": _fb_safety.get("waves_m"),
            "wind_kts": _fb_safety.get("wind_kts"),
            "danger": _fb_safety.get("danger", "unknown"),
            "badge": _fb_safety.get("badge", "amber"),
        }
        try:
            from backend.agents.synthesizer_service import iter_reply_tokens as _iter_tokens  # type: ignore
        except ImportError:
            _iter_tokens = None  # type: ignore
        _fb_reply = str(_fb.get("reply") or "")
        if _iter_tokens is not None:
            # iter_reply_tokens is delimiter-safe (fix 4: trailing
            # space on all but last) -> yield verbatim.
            _fb_chunks = _iter_tokens(_fb_reply)
            for _ch in _fb_chunks:
                yield {"type": "token", "text": _ch}
                await asyncio.sleep(0)
        else:
            _raw_fb2 = _chunk_text(_fb_reply)
            for _i2, _ch2 in enumerate(_raw_fb2):
                _suf2 = " " if _i2 < len(_raw_fb2) - 1 else ""
                yield {"type": "token", "text": _ch2 + _suf2}
                await asyncio.sleep(0)
        _fb_serr = _fb.get("synthesis_error") if "synthesis_error" in _fb else None
        if isinstance(_fb_serr, dict) and _fb_serr:
            yield dict(_fb_serr)
        _fb_ev = _fb.get("evidence") or ["INCOIS TextData"]
        if isinstance(_fb_ev, str):
            _fb_ev = [_fb_ev]
        yield {"type": "evidence", "items": [str(e) for e in _fb_ev if e] or ["INCOIS TextData"]}
        yield {
            "type": "done",
            "language": _fb.get("language") or language,
            "confidence": _fb.get("confidence") or DEGRADED_CONFIDENCE,
            "session_id": _fb.get("session_id") or session_id or "",
        }
        return

    # Budgets: configurable sub-agent budget (default 15.0s, accommodates
    # Gemini 2.5 Flash 12s SLA + combiner/mask overhead)
    NODE_TIMEOUT_S = float(os.getenv("ORCA_NODE_TIMEOUT_S", "15.0"))
    P95_BUDGET_S = float(os.getenv("ORCA_P95_BUDGET_S", "32.0"))
    # Current compiled topology: planner -> fish_finder ->
    # parallel_analysis -> decision_agent. Sub-agent names kept for
    # forward-compat (never emitted today — see parallel_analysis_node).
    KNOWN_NODES = (
        "conversational_router",
        "chitchat_responder",
        "planner",
        "fish_finder",
        "parallel_analysis",
        "decision_agent",
        "sea_checker",
        "weather_agent",
        "danger_agent",
    )

    sid = session_id or uuid.uuid4().hex
    t0 = time.perf_counter()
    node_start: dict[str, float] = {}

    # ---- Chitchat fast-path (conversational chatbot mode) --------------
    # Deterministic <1ms gate BEFORE the graph stream: pure chitchat gets
    # status -> token(s) -> evidence -> done with NO map/safety events, so
    # the frontend renders a normal chat bubble (no banner, no zone cards).
    try:
        try:
            from backend.agents.conversational_router import (  # type: ignore
                build_chitchat_reply as _chitchat_reply,
                is_chitchat as _is_chitchat,
            )
        except ImportError:
            from agents.conversational_router import (  # type: ignore
                build_chitchat_reply as _chitchat_reply,
                is_chitchat as _is_chitchat,
            )
        if _is_chitchat(query or ""):
            _reply = _chitchat_reply(query or "", language or "en")
            yield {"type": "status", "agent": "conversational_router", "state": "running"}
            yield {"type": "status", "agent": "conversational_router", "state": "done", "elapsed_ms": 1}
            try:
                from backend.agents.synthesizer_service import (  # type: ignore
                    iter_reply_tokens as _iter_toks,
                )

                _chunks = _iter_toks(str(_reply))
            except Exception:
                _raw_chunks = _chunk_text(str(_reply))
                _chunks = [
                    chunk + (" " if index < len(_raw_chunks) - 1 else "")
                    for index, chunk in enumerate(_raw_chunks)
                ]
            for _ch in _chunks:
                yield {"type": "token", "text": _ch}
                await asyncio.sleep(0)
            yield {"type": "evidence", "items": ["conversational reply — no marine data queried"]}
            yield {"type": "done", "language": language or "en", "confidence": 0.99, "session_id": sid}
            try:
                from backend.db import redis as _redis_mod  # type: ignore

                await asyncio.wait_for(
                    _redis_mod.append_message(sid, "user", query or ""), timeout=1.0,
                )
                await asyncio.wait_for(
                    _redis_mod.append_message(sid, "assistant", str(_reply)), timeout=1.0,
                )
            except Exception:
                pass
            return
    except Exception:
        pass

    user_location: dict | None = None
    fish_results: list[dict] | None = None
    sea_results: list[dict] | None = None
    weather_results: list[dict] | None = None
    danger_results: list[dict] | None = None
    decision_out: dict | None = None
    final_state: dict = {}
    token_buf: list[str] = []
    # #34 native-token accounting: True once any on_chat_model_stream text
    # was yielded live (primary path). Validated chunk replay is then skipped
    # to avoid duplication (graceful-degrade fallback only when no native).
    native_tokens_streamed = False

    map_emitted = False
    safety_emitted = False
    # Last emitted map center [lon, lat] (provisional or final) — used by
    # #34 fix 5 to detect provisional/final divergence.
    emitted_map_center: list | None = None

    def _centers_differ(c1: Any, c2: Any, tol: float = 1e-9) -> bool:
        """True when two [lon, lat] centers differ (lat/lon comparison)."""
        try:
            if c1 is None or c2 is None:
                return c1 is not c2 and not (c1 is None and c2 is None)
            if not isinstance(c1, (list, tuple)) or not isinstance(c2, (list, tuple)):
                return True
            if len(c1) < 2 or len(c2) < 2:
                return True
            return abs(float(c1[0]) - float(c2[0])) > tol or abs(float(c1[1]) - float(c2[1])) > tol
        except (TypeError, ValueError):
            return True

    def _provisional_map_payload() -> dict:
        # Provisional map from raw fish results (early flyTo).
        # Field names match docs/API.md exactly: center/pfz_features/route.
        # Early events carry provisional:true; final decision map does not.
        ul = user_location or final_state.get("user_location")
        feats = _to_geojson_features(fish_results or [])
        if not isinstance(ul, dict) or ul.get("lat") is None:
            return {"type": "map", "center": None, "pfz_features": [], "route": [], "provisional": True}
        try:
            ulat = float(ul["lat"])
            ulon = float(ul["lon"])
        except (TypeError, ValueError):
            return {"type": "map", "center": None, "pfz_features": [], "route": [], "provisional": True}
        lat0: float | None = None
        lon0: float | None = None
        for z in fish_results or []:
            try:
                if isinstance(z, dict) and z.get("lat") is not None and z.get("lon") is not None:
                    lat0, lon0 = float(z["lat"]), float(z["lon"])
                    break
            except (TypeError, ValueError):
                continue
        if lat0 is not None and lon0 is not None:
            return {
                "type": "map",
                "center": [lon0, lat0],
                "pfz_features": feats,
                "route": [[ulon, ulat], [lon0, lat0]],
                "provisional": True,
            }
        return {"type": "map", "center": [ulon, ulat], "pfz_features": feats, "route": [], "provisional": True}

    def _provisional_safety_payload() -> dict:
        # Provisional safety via own combiner call so safety can be
        # emitted at parallel_analysis end, before decision_agent finishes.
        # Field names match docs/API.md exactly: waves_m/wind_kts/danger/badge.
        # Early events carry provisional:true; final decision safety does not.
        ul = user_location or final_state.get("user_location") or {"lat": 0, "lon": 0}
        fish = fish_results or []
        if not fish:
            return {"type": "safety", "waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber", "provisional": True}
        combined: dict = {}
        try:
            from backend.agents import combiner as cb  # type: ignore

            combined = cb.combine_and_rank(
                fish_results=fish,
                sea_results=sea_results or [],
                weather_results=weather_results or [],
                danger_results=danger_results or [],
                user_location=ul if isinstance(ul, dict) else {"lat": 0, "lon": 0},
            )
            best = combined.get("best")
        except Exception as exc:
            logger.warning("graph.stream combiner failed: %s", exc)
            best = None
        if not isinstance(best, dict):
            return {"type": "safety", "waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber", "provisional": True}
        # Mirror decision_agent badge reasoning (duplicated for earliness).
        # Empty lists mean "unknown", never safe.
        best_id = str(best.get("zone_id")) if best.get("zone_id") else None
        sea_s = wind_s = danger_s = "safe"
        if not sea_results:
            sea_s = "unknown"
        if not weather_results:
            wind_s = "unknown"
        if not danger_results:
            danger_s = "unknown"
        for r in sea_results or []:
            if isinstance(r, dict) and str(r.get("zone_id")) == best_id:
                sea_s = str(r.get("status") or r.get("wave_status") or "safe").lower()
                break
        for r in weather_results or []:
            if isinstance(r, dict) and str(r.get("zone_id")) == best_id:
                wind_s = str(r.get("status") or r.get("wind_status") or "safe").lower()
                break
        for r in danger_results or []:
            if isinstance(r, dict) and best_id and str(r.get("zone_id")) == best_id:
                danger_s = str(r.get("status") or "safe").lower()
                break
        badge = _badge_for_best(best, sea_s, wind_s, danger_s)
        if "unknown" in (sea_s, wind_s, danger_s):
            badge = "amber"
        danger_field = "none" if danger_s == "safe" else danger_s
        if "unknown" in (sea_s, wind_s, danger_s) and danger_field == "none":
            danger_field = "unknown"
        # Veto parity (mirror decision_agent): combiner all_unsafe / banned
        # forces red+DANGER even on zone_id lookup miss.
        try:
            _veto = bool((combined or {}).get("all_unsafe"))
        except Exception:
            _veto = False
        try:
            _banned = bool(best.get("inside_mpa")) or (best.get("inside_eez") is False)
        except Exception:
            _banned = False
        if _veto or _banned:
            badge = "red"
            danger_field = "danger"
        waves_m = best.get("wave_height_m")
        wind_kts = best.get("wind_kt") if best.get("wind_kt") is not None else best.get("wind_speed_kt")
        return {"type": "safety", "waves_m": waves_m, "wind_kts": wind_kts, "danger": danger_field, "badge": badge, "provisional": True}

    init_state: ORCAState = {"query": query or "", "language": language or "en", "location": location, "session_id": sid}

    meta_location = None
    if isinstance(location, dict):
        meta_location = {
            "has_coords": bool(location.get("lat") or location.get("latitude")),
            "port": location.get("port") or location.get("name"),
        }

    runnable_config: RunnableConfig = {
        "run_name": "orca_agentic_supervisor",
        "tags": ["orca", "marine-intelligence", "sih26176", language or "en"],
        "metadata": {
            "session_id": sid,
            "location": meta_location,
            "scenario": os.getenv("ORCA_SCENARIO", "normal"),
            "language": language or "en",
        },
    }

    try:
        async for ev in graph.astream_events(init_state, version="v2", config=runnable_config):
            etype = ev.get("event")
            name = ev.get("name")
            now = time.perf_counter()

            # Native token streaming (#34): on_chat_model_stream from
            # astream_events v2, parsed via synthesizer_service helper.
            # Buffered until map+safety are out to keep strict
            # status->map->safety->tokens order; flushed live afterwards.
            # NOTE (fix 1): decision_agent synthesizes via raw google-genai
            # (not a LangChain chat model), so no native events fire today.
            # This hook is kept for a future chat-model with validation —
            # raw native text is NEVER yielded when it contains masked
            # placeholders (__M*__); only the validated iter_reply_tokens
            # path yields to the client.
            if etype == "on_chat_model_stream":
                try:
                    # Fix 2 — node origin filter: only decision_agent native
                    # tokens may stream; other nodes' model noise is skipped.
                    try:
                        _meta = ev.get("metadata") or {}
                        _origin = _meta.get("langgraph_node")
                    except Exception:
                        _origin = None
                    if _origin is not None and _origin != "decision_agent":
                        continue
                    data = ev.get("data") or {}
                    chunk = data.get("chunk")
                    try:
                        from backend.agents.synthesizer_service import (  # type: ignore
                            extract_native_token_text as _extract_text,
                        )

                        text = _extract_text(chunk)
                    except ImportError:
                        text = ""
                        if isinstance(chunk, str):
                            text = chunk
                        elif chunk is not None:
                            text = getattr(chunk, "content", "") or ""
                            if not isinstance(text, str):
                                text = str(text) if text else ""
                    if text:
                        # Fix 1 — placeholder guard: never yield raw masked
                        # spans. Buffer (don't yield live); flush sites also
                        # filter placeholders so they never reach the client.
                        if _NATIVE_PLACEHOLDER_RE.search(text):
                            logger.warning("graph.stream: dropping native chunk with masked placeholder")
                            continue
                        if safety_emitted and map_emitted:
                            # Fix 3 — drain buffered tokens in order before
                            # the new live token (FIFO).
                            while token_buf:
                                _b = token_buf.pop(0)
                                if _NATIVE_PLACEHOLDER_RE.search(_b):
                                    continue
                                native_tokens_streamed = True
                                yield {"type": "token", "text": _b}
                            native_tokens_streamed = True
                            yield {"type": "token", "text": text}
                        else:
                            token_buf.append(text)
                except Exception:
                    pass
                continue

            if etype == "on_chain_start" and name in KNOWN_NODES:
                node_start[name] = now
                # Suppress post-map statuses to hold strict order.
                if not map_emitted:
                    yield {"type": "status", "agent": name, "state": "running"}
                continue

            if etype != "on_chain_end" or name not in KNOWN_NODES:
                continue

            data = ev.get("data") or {}
            output = data.get("output")
            if isinstance(output, dict):
                final_state.update(output)
            start_t = node_start.get(name, now)
            elapsed_s = now - start_t
            elapsed_ms = int(elapsed_s * 1000)
            # Observed 1.4s sub-agent budget — emits error but does not
            # preempt the slow node (LangGraph stream has no per-node cancel).
            if elapsed_s > NODE_TIMEOUT_S:
                # US-ORCA-014: explicit agent_progress timeout event so the
                # client can render per-agent timeout progress (degraded).
                # The legacy error event is kept for backward compatibility;
                # ordering tests ignore error events per docs/API.md.
                yield {
                    "type": "agent_progress",
                    "agent": name,
                    "state": "timeout",
                    "message": f"sub-agent budget exceeded {elapsed_s:.2f}s > {NODE_TIMEOUT_S}s budget",
                    "elapsed_ms": elapsed_ms,
                    "degraded": True,
                }
                yield {
                    "type": "error",
                    "agent": name,
                    "message": f"sub-agent budget exceeded {elapsed_s:.2f}s > {NODE_TIMEOUT_S}s budget",
                    "fallback": "unknown",
                }

            if name == "planner":
                # CRIT-01: surface explicit planner_error (fallback)
                # Yield fallback status; pipeline continues
                try:
                    _perr = output.get("planner_error") if isinstance(output, dict) else None
                except Exception:
                    _perr = None
                if isinstance(_perr, dict) and _perr:
                    yield dict(_perr)
                ul = output.get("user_location") if isinstance(output, dict) else None
                if isinstance(ul, dict) and ul.get("lat") is not None and ul.get("lon") is not None:
                    try:
                        user_location = {"lat": float(ul["lat"]), "lon": float(ul["lon"])}
                    except (TypeError, ValueError):
                        user_location = None
                    if not map_emitted:
                        if not _perr:
                            yield {"type": "status", "agent": name, "state": "done", "elapsed_ms": elapsed_ms}

            elif name == "fish_finder":
                fr = output.get("fish_results") if isinstance(output, dict) else None
                fish_results = fr if isinstance(fr, list) else []
                final_state["fish_results"] = fish_results
                if final_state.get("user_location") and user_location is None:
                    ful = final_state.get("user_location")
                    if isinstance(ful, dict) and ful.get("lat") is not None:
                        try:
                            user_location = {"lat": float(ful["lat"]), "lon": float(ful["lon"])}
                        except (TypeError, ValueError):
                            pass
                if not map_emitted:
                    yield {"type": "status", "agent": name, "state": "done", "elapsed_ms": elapsed_ms}
                    # EARLY flyTo: map immediately from fish output.
                    _mp = _provisional_map_payload()
                    try:
                        emitted_map_center = _mp.get("center")
                    except Exception:
                        pass
                    yield _mp
                    map_emitted = True
                # Later statuses suppressed to hold strict status* -> map order.

            elif name == "parallel_analysis":
                if isinstance(output, dict):
                    if isinstance(output.get("sea_results"), list):
                        sea_results = output["sea_results"]
                    if isinstance(output.get("weather_results"), list):
                        weather_results = output["weather_results"]
                    if isinstance(output.get("danger_results"), list):
                        danger_results = output["danger_results"]
                if not map_emitted:
                    yield {"type": "status", "agent": name, "state": "done", "elapsed_ms": elapsed_ms}
                    _mp2 = _provisional_map_payload()
                    try:
                        emitted_map_center = _mp2.get("center")
                    except Exception:
                        pass
                    yield _mp2
                    map_emitted = True
                if not safety_emitted:
                    yield _provisional_safety_payload()
                    safety_emitted = True
                    # Fix 3 — provisional safety just completed map+safety:
                    # drain buffered native tokens in order (FIFO) before
                    # any later live token. Placeholder chunks are dropped.
                    while token_buf and map_emitted:
                        _b2 = token_buf.pop(0)
                        if _NATIVE_PLACEHOLDER_RE.search(_b2):
                            continue
                        native_tokens_streamed = True
                        yield {"type": "token", "text": _b2}

            elif name in ("sea_checker", "weather_agent", "danger_agent"):
                # Forward-compat: current topology never emits these (they run
                # inside parallel_analysis). If they ever become real nodes,
                # stash partials and emit safety once all three are present.
                if isinstance(output, dict):
                    if name == "sea_checker" and isinstance(output.get("sea_results"), list):
                        sea_results = output["sea_results"]
                    elif name == "weather_agent" and isinstance(output.get("weather_results"), list):
                        weather_results = output["weather_results"]
                    elif name == "danger_agent" and isinstance(output.get("danger_results"), list):
                        danger_results = output["danger_results"]
                if (
                    not safety_emitted
                    and map_emitted
                    and sea_results is not None
                    and weather_results is not None
                    and danger_results is not None
                ):
                    yield _provisional_safety_payload()
                    safety_emitted = True
                    # Fix 3 — drain buffered native tokens in order now that
                    # map+safety hold (FIFO, placeholders dropped).
                    while token_buf:
                        _b3 = token_buf.pop(0)
                        if _NATIVE_PLACEHOLDER_RE.search(_b3):
                            continue
                        native_tokens_streamed = True
                        yield {"type": "token", "text": _b3}

            elif name == "decision_agent":
                if isinstance(output, dict):
                    decision_out = output
                else:
                    decision_out = {}
                # Guarantee map/safety precede tokens (strict order).
                if not map_emitted:
                    if isinstance(decision_out.get("map"), dict):
                        dm = decision_out["map"]
                        try:
                            emitted_map_center = dm.get("center")
                        except Exception:
                            pass
                        yield {
                            "type": "map",
                            "center": dm.get("center"),
                            "pfz_features": dm.get("pfz_features") or [],
                            "route": dm.get("route") or [],
                        }
                    else:
                        _mpd = _provisional_map_payload()
                        try:
                            emitted_map_center = _mpd.get("center")
                        except Exception:
                            pass
                        yield _mpd
                    map_emitted = True
                if not safety_emitted:
                    if isinstance(decision_out.get("safety"), dict):
                        ds = decision_out["safety"]
                        yield {
                            "type": "safety",
                            "waves_m": ds.get("waves_m"),
                            "wind_kts": ds.get("wind_kts"),
                            "danger": ds.get("danger"),
                            "badge": ds.get("badge"),
                        }
                    else:
                        yield _provisional_safety_payload()
                    safety_emitted = True
                # Fix 5 — provisional map divergence: if the authoritative
                # decision map center differs (lat/lon) from the provisional
                # early flyTo, emit the final map (provisional:false) before
                # any tokens so the client highlights the correct zone.
                _dm_final: Any = None
                _final_center: Any = None
                try:
                    _dm_final = decision_out.get("map") if isinstance(decision_out, dict) else None
                    _final_center = _dm_final.get("center") if isinstance(_dm_final, dict) else None
                except Exception:
                    _dm_final = None
                    _final_center = None
                # Only when both centers are present (fix 5): a None
                # provisional (no-location) must stay None — never upgrade
                # to the decision default [0,0].
                if (
                    map_emitted
                    and emitted_map_center is not None
                    and _final_center is not None
                    and _centers_differ(emitted_map_center, _final_center)
                ):
                    try:
                        _pfz = _dm_final.get("pfz_features") or []
                    except Exception:
                        _pfz = []
                    try:
                        _route = _dm_final.get("route") or []
                    except Exception:
                        _route = []
                    yield {
                        "type": "map",
                        "center": _final_center,
                        "pfz_features": _pfz,
                        "route": _route,
                        "provisional": False,
                    }
                    emitted_map_center = _final_center
                # Flush early native tokens (buffered until map+safety) in
                # order — these are live LLM tokens streamed directly.
                # Placeholder chunks are dropped (fix 1); FIFO via pop(0).
                while token_buf:
                    buffered = token_buf.pop(0)
                    if _NATIVE_PLACEHOLDER_RE.search(buffered):
                        continue
                    native_tokens_streamed = True
                    yield {"type": "token", "text": buffered}
                # Validated chunk replay (#34 degrade path): the decision
                # reply is already post-validated by synthesize_advisory
                # (veto/numbers/citation). Skipped when native tokens already
                # streamed live to avoid duplication.
                # Only this validated path yields to the client (fix 1).
                if not native_tokens_streamed:
                    reply = decision_out.get("reply") or decision_out.get("explanation") or ""
                    try:
                        from backend.agents.synthesizer_service import (  # type: ignore
                            iter_reply_tokens as _iter_tokens,
                        )

                        chunks = _iter_tokens(reply)
                    except ImportError:
                        # Fallback delimiter-safe (fix 4 parity when the
                        # service import is unavailable).
                        _raw_fb = _chunk_text(reply)
                        chunks = [c + (" " if i < len(_raw_fb) - 1 else "") for i, c in enumerate(_raw_fb)]
                    for ch in chunks:
                        yield {"type": "token", "text": ch}
                        await asyncio.sleep(0)  # SSE flush point
                # CORR-04: explicit synthesis error — never silent (fallback:none).
                _synth_err = decision_out.get("synthesis_error")
                if isinstance(_synth_err, dict) and _synth_err:
                    yield dict(_synth_err)

    except Exception as exc:
        # Low (fix 7): sanitize — log internals, stream a generic message
        # so transport/API details never leak to the client.
        logger.warning("graph.stream failed: %s", exc, exc_info=True)
        yield {"type": "error", "agent": "decision_agent", "message": "stream failed (internal error)", "fallback": "unknown"}

    # ---- Tail: guarantee evidence -> done (and fill any gaps) ----
    resolved_ul = user_location or final_state.get("user_location")
    if not resolved_ul:
        # No-location early path (same payload shape as before, strict order).
        if not map_emitted:
            yield {"type": "map", "center": None, "pfz_features": [], "route": []}
            map_emitted = True
        if not safety_emitted:
            yield {"type": "safety", "waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber"}
            safety_emitted = True
        # If decision tokens never streamed (e.g. short-circuit), emit prompt.
        # Buffered native tokens (if any) flush first to preserve order
        # (FIFO, placeholder chunks dropped — fix 1).
        while token_buf:
            _bt = token_buf.pop(0)
            if _NATIVE_PLACEHOLDER_RE.search(_bt):
                continue
            native_tokens_streamed = True
            yield {"type": "token", "text": _bt}
        if decision_out is None and not native_tokens_streamed:
            prompt = "Please share your GPS location or mention a coastal place like Kochi, Veraval, or Chennai to find nearby fishing zones."
            _praw = _chunk_text(prompt)
            for _pi, chunk in enumerate(_praw):
                _psuf = " " if _pi < len(_praw) - 1 else ""
                yield {"type": "token", "text": chunk + _psuf}
                await asyncio.sleep(0)
        # MAJ-02: clarification tail surfaces decision evidence when present.
        _tail_ev = decision_out.get("evidence") if isinstance(decision_out, dict) else None
        if isinstance(_tail_ev, list) and any(_tail_ev):
            _tail_items = [str(e) for e in _tail_ev if e]
        elif isinstance(_tail_ev, str) and _tail_ev:
            _tail_items = [_tail_ev]
        else:
            _tail_items = ["Location not provided — cannot search PFZ zones"]
        yield {"type": "evidence", "items": _tail_items or ["Location not provided — cannot search PFZ zones"]}
        yield {"type": "done", "language": final_state.get("language") or language, "confidence": DEGRADED_CONFIDENCE, "session_id": final_state.get("session_id") or sid}
        return

    dout = decision_out or {}
    if not map_emitted:
        if isinstance(dout.get("map"), dict):
            dm = dout["map"]
            try:
                emitted_map_center = dm.get("center")
            except Exception:
                pass
            yield {
                "type": "map",
                "center": dm.get("center"),
                "pfz_features": dm.get("pfz_features") or [],
                "route": dm.get("route") or [],
            }
        elif isinstance(final_state.get("map"), dict):
            fm = final_state["map"]
            try:
                emitted_map_center = fm.get("center")
            except Exception:
                pass
            yield {
                "type": "map",
                "center": fm.get("center"),
                "pfz_features": fm.get("pfz_features") or [],
                "route": fm.get("route") or [],
            }
        else:
            _mpt = _provisional_map_payload()
            try:
                emitted_map_center = _mpt.get("center")
            except Exception:
                pass
            yield _mpt
        map_emitted = True
    if not safety_emitted:
        if isinstance(dout.get("safety"), dict):
            ds = dout["safety"]
            yield {
                "type": "safety",
                "waves_m": ds.get("waves_m"),
                "wind_kts": ds.get("wind_kts"),
                "danger": ds.get("danger"),
                "badge": ds.get("badge"),
            }
        elif isinstance(final_state.get("safety"), dict):
            fs = final_state["safety"]
            yield {
                "type": "safety",
                "waves_m": fs.get("waves_m"),
                "wind_kts": fs.get("wind_kts"),
                "danger": fs.get("danger"),
                "badge": fs.get("badge"),
            }
        else:
            yield _provisional_safety_payload()
        safety_emitted = True
    # Tail drain (fix 3): FIFO, placeholder chunks dropped (fix 1).
    while token_buf:
        _bt2 = token_buf.pop(0)
        if _NATIVE_PLACEHOLDER_RE.search(_bt2):
            continue
        native_tokens_streamed = True
        yield {"type": "token", "text": _bt2}

    # Session persist (best-effort, mirrors orchestrate_via_graph()).
    try:
        from backend.db import redis as redis_mod  # type: ignore

        _best = dout.get("best") if isinstance(dout.get("best"), dict) else final_state.get("best")
        _cached = final_state.get("cached_session")
        _reply = dout.get("reply") or dout.get("explanation") or final_state.get("reply") or final_state.get("explanation") or ""
        _turn_history: list[dict] = []
        if isinstance(_cached, dict) and isinstance(_cached.get("turn_history"), list):
            _turn_history = list(_cached["turn_history"])
        _turn_history.append({
            "query": query,
            "zone_id": _best.get("zone_id") if isinstance(_best, dict) else None,
            "place": _best.get("place") if isinstance(_best, dict) else None,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "reply_summary": (_reply or "")[:200],
        })
        if len(_turn_history) > 20:
            _turn_history = _turn_history[-20:]
        _session_data = {
            "lat": float(resolved_ul["lat"]),
            "lon": float(resolved_ul["lon"]),
            "zone_id": _best.get("zone_id") if isinstance(_best, dict) else None,
            "place": _best.get("place") if isinstance(_best, dict) else None,
            "last_advisory_summary": (_reply or "")[:500],
            "turn_history": _turn_history,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if isinstance(_cached, dict) and _cached.get("vessel_type") is not None:
            _session_data["vessel_type"] = _cached.get("vessel_type")
        try:
            await asyncio.wait_for(redis_mod.save_session(dout.get("session_id") or final_state.get("session_id") or sid, _session_data, ttl_seconds=86400), timeout=1.0)
        except Exception:
            pass
    except Exception:
        pass

    evidence = dout.get("evidence") or final_state.get("evidence") or [final_state.get("citation") or dout.get("citation") or "INCOIS TextData"]
    if isinstance(evidence, str):
        evidence = [evidence]
    evidence = [str(e) for e in evidence if e]
    yield {"type": "evidence", "items": evidence or ["INCOIS TextData"]}
    total_s = time.perf_counter() - t0
    if total_s > P95_BUDGET_S:
        # Observe P95<2.0s SLA, do not fail the stream (early map/safety
        # already kept TTFB low; tail latency is logged for SLO tracking).
        logger.warning("graph.stream total %.2fs exceeds P95 %.1fs budget", total_s, P95_BUDGET_S)
    confidence = dout.get("confidence") or final_state.get("confidence") or (DEGRADED_CONFIDENCE if final_state.get("degraded") else DEFAULT_CONFIDENCE)
    yield {
        "type": "done",
        "language": dout.get("language") or final_state.get("language") or language,
        "confidence": confidence,
        "session_id": dout.get("session_id") or final_state.get("session_id") or sid,
    }
