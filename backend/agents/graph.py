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
(wants_fish, wants_safety per orchestrator._parse_intent) and routes
via Send() for parallel tool-augmented execution.

The deterministic *.py helpers are preserved as TOOL layer so the graph
remains auditable, testable (tests/test_agents.py 41 tests), and
offline-capable. The graph merely demonstrates Agentic AI principles:
planning, reasoning, tool selection, collaboration, explainability.

LangGraph is optional at runtime — orchestrator.py falls back to
asyncio.gather if langgraph is not installed (P95<2s guarantee).

Refs:
  PS SIH26176 — ORCA Marine EcOsystem Reasoning with Collaborative Agents
  wayfinder:map#7 — Multi-Agent Orchestration System
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
import uuid
from typing import Any, TypedDict, Annotated

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ORCAState(TypedDict, total=False):
    # inputs
    query: str
    language: str
    location: dict | None  # explicit GPS
    session_id: str
    # supervisor outputs
    intent: dict  # {wants_fish, wants_safety}
    user_location: dict | None  # {lat, lon} resolved
    cached_session: dict | None
    degraded: bool
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

TIMEOUT_S = 10.0

# ---------------------------------------------------------------------------
# Lazy imports — keep graph importable even if langgraph not installed
# ---------------------------------------------------------------------------

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
    logger.info("graph: langgraph not installed — graph will be disabled, falling back to orchestrator gather")

# Reuse helpers from orchestrator (single source of truth)
try:
    from backend.agents.orchestrator import (
        COASTAL_PORTS,
        _parse_intent,
        _resolve_location,
        _parse_relative_offset,
        _to_geojson_features,
        _badge_for_best,
        _degraded_sea,
        _degraded_weather,
        _degraded_danger,
        _chunk_text,
        TIMEOUT_S as ORCH_TIMEOUT,
        DEFAULT_CONFIDENCE,
        DEGRADED_CONFIDENCE,
    )
except ImportError:
    # fallback for direct script runs
    from orchestrator import (  # type: ignore
        COASTAL_PORTS,
        _parse_intent,
        _resolve_location,
        _parse_relative_offset,
        _to_geojson_features,
        _badge_for_best,
        _degraded_sea,
        _degraded_weather,
        _degraded_danger,
        _chunk_text,
        TIMEOUT_S as ORCH_TIMEOUT,
        DEFAULT_CONFIDENCE,
        DEGRADED_CONFIDENCE,
    )
    TIMEOUT_S = ORCH_TIMEOUT

# ---------------------------------------------------------------------------
# Supervisor / Planner — decides intent + location, selects tools
# ---------------------------------------------------------------------------

async def planner_node(state: ORCAState) -> dict:
    """
    Supervisor/Planner sub-agent.

    Responsibilities (SIH26176: planning, reasoning, tool selection):
      - detect intent (wants_fish, wants_safety) — autonomous decision
      - resolve user_location via tools: explicit GPS > COASTAL_PORTS fast-path > Redis session reuse > relative offset
      - select which downstream agents to invoke (via returned intent)
    Tools conceptually used: _resolve_location (deterministic geocoding), redis.get_session
    """
    query = state.get("query", "") or ""
    location = state.get("location")
    session_id = state.get("session_id") or uuid.uuid4().hex
    language = state.get("language", "en")

    intent = _parse_intent(query)

    # 1. try explicit + port lookup (tool: deterministic geocoding)
    resolved = _resolve_location(query, location)
    cached_session = None
    degraded = False

    # 2. tool: redis.get_session for multi-turn reuse
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

    user_location = {"lat": float(resolved[0]), "lon": float(resolved[1])} if resolved else None

    return {
        "intent": intent,
        "user_location": user_location,
        "cached_session": cached_session,
        "session_id": session_id,
        "degraded": degraded,
        "query": query,
        "language": language,
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
    """
    user_location = state.get("user_location")
    if not user_location:
        return {"fish_results": []}
    lat = float(user_location["lat"])
    lon = float(user_location["lon"])
    try:
        from backend.agents.subagents import fish_finder as ff  # type: ignore

        res = await asyncio.wait_for(ff.find_fishing_zones(lat=lat, lon=lon, radius_km=80.0), timeout=TIMEOUT_S)
        if not isinstance(res, list):
            res = []
        logger.info("graph.fish_finder: %d zones for %.2f,%.2f", len(res), lat, lon)
        return {"fish_results": res}
    except asyncio.TimeoutError:
        logger.warning("graph.fish_finder: timeout 10s")
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
    """
    fish = state.get("fish_results") or []
    if not fish:
        return {"sea_results": []}
    try:
        from backend.agents.subagents import sea_checker as sc  # type: ignore

        res = await asyncio.wait_for(sc.check_sea_conditions(fish), timeout=TIMEOUT_S)
        return {"sea_results": res if isinstance(res, list) else _degraded_sea(fish)}
    except asyncio.TimeoutError:
        logger.warning("graph.sea_checker: timeout 10s")
        return {"sea_results": _degraded_sea(fish), "degraded": True}
    except Exception as exc:
        logger.warning("graph.sea_checker: %s", exc)
        return {"sea_results": _degraded_sea(fish), "degraded": True}


async def weather_agent(state: ORCAState) -> dict:
    """
    Weather Agent (SIH26176: weather intelligence).

    Tools:
      - fetch_imd_wind, fetch_imd_cyclones / get_wind, get_cyclone_alert
    Decision: wind <15 safe / 15-25 caution / >25 danger, cyclone within 500km → danger.
    """
    fish = state.get("fish_results") or []
    if not fish:
        return {"weather_results": []}
    try:
        from backend.agents.subagents import weather_agent as wa  # type: ignore

        res = await asyncio.wait_for(wa.check_weather(fish), timeout=TIMEOUT_S)
        return {"weather_results": res if isinstance(res, list) else _degraded_weather(fish)}
    except asyncio.TimeoutError:
        logger.warning("graph.weather_agent: timeout 10s")
        return {"weather_results": _degraded_weather(fish), "degraded": True}
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
    """
    fish = state.get("fish_results") or []
    if not fish:
        return {"danger_results": []}
    try:
        from backend.agents.subagents import danger_agent as da  # type: ignore

        # Use batch helper if available (preserves order, respects shared points)
        if hasattr(da, "check_safety_batch"):
            res = await asyncio.wait_for(da.check_safety_batch(fish), timeout=TIMEOUT_S)
        else:
            # per-point fallback
            res = []
            for pt in fish:
                lat = pt.get("lat")
                lon = pt.get("lon")
                if lat is None or lon is None:
                    geom = pt.get("geometry") or {}
                    coords = geom.get("coordinates") or []
                    if len(coords) >= 2:
                        lon, lat = coords[0], coords[1]
                r = await da.check_safety(float(lat), float(lon)) if lat is not None else {
                    "is_safe": False, "status": "unknown", "warnings": ["missing lat/lon"],
                    "inside_eez": True, "inside_mpa": False, "mpa_name": None,
                }
                res.append(r)
        return {"danger_results": res if isinstance(res, list) else _degraded_danger(fish)}
    except asyncio.TimeoutError:
        logger.warning("graph.danger_agent: timeout 10s")
        return {"danger_results": _degraded_danger(fish), "degraded": True}
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

    # safety badge reasoning — autonomous decision per sub-agent outputs
    if best:
        sea_s = "safe"
        wind_s = "safe"
        danger_s = "safe"
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

    degraded = bool(state.get("degraded"))
    confidence = DEGRADED_CONFIDENCE if degraded or not best else DEFAULT_CONFIDENCE

    # ---- Masked LLM advisory synthesis (ticket #33) ---------------------
    # Req 1: explicit metric lexical masking in decision_agent using
    # lexical_mask.py (bearings/knots/distances/coords -> __M*__).
    # Req 2-4: Gemini 2.5 Flash wording via synthesizer_service with
    # strict DO NOT SAIL veto + unmask/post-validate + explicit error.
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

            _envelope = await _synth.synthesize_advisory(
                combined, language=language, user_location=user_location,
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
                synthesis_error = {
                    "type": "error",
                    "agent": "decision_agent",
                    "message": f"synthesizer failed: {exc}",
                    "fallback": "none",
                }
            logger.warning("graph.decision: synthesis failed, keeping deterministic reply: %s", exc)

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
    Collaborative analysis node — invokes 3 specialized sub-agents
    *in parallel* via asyncio.gather on the SAME fish_results
    (shared list idea per ORCA_GeoJSON_Architecture.md).

    Each sub-agent decides autonomously and calls its own tools:
      sea_checker -> get_wave_current (OSF/heuristic)
      weather_agent -> get_wind / get_cyclone_alert
      danger_agent -> check_geofence / ray_cast

    This preserves LangGraph node topology (planner -> fish -> parallel
    -> decision) while guaranteeing P95<2s and mock compatibility
    (tests patch backend.agents.*.check_*).
    """
    # Run 3 agents concurrently — true parallel, not sequential Send
    results = await asyncio.gather(
        sea_checker(state),
        weather_agent(state),
        danger_agent(state),
    )
    merged: dict = {}
    for r in results:
        merged.update(r)
        # propagate degraded flag if any sub-agent degraded
        if r.get("degraded"):
            merged["degraded"] = True
    return merged


def build_orca_graph():
    """
    Build and compile the ORCA StateGraph.

    Nodes (SIH26176): planner (supervisor, tool: redis + geocoding)
      -> fish_finder (tools: PostGIS + GeoJSON)
      -> parallel_analysis_node (3 sub-agents in parallel, each with own tools)
      -> decision_agent (tool: combiner)

    Parallelism is via asyncio.gather inside parallel_analysis_node
    (auditable, mock-friendly, P95<2s). Alternative Send fan-out
    is reserved for future when langgraph Send semantics stabilize.

    Returns:
      CompiledGraph or None if langgraph not installed.
    """
    if not _HAS_LANGGRAPH or StateGraph is None:
        logger.warning("build_orca_graph: langgraph not installed — returning None")
        return None

    graph = StateGraph(ORCAState)

    graph.add_node("planner", planner_node)
    graph.add_node("fish_finder", fish_finder)
    graph.add_node("parallel_analysis", parallel_analysis_node)
    graph.add_node("decision_agent", decision_agent)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "fish_finder")
    graph.add_edge("fish_finder", "parallel_analysis")
    graph.add_edge("parallel_analysis", "decision_agent")
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

    Falls back to direct tool calls if graph is unavailable.
    """
    graph = get_orca_graph()
    if graph is None:
        # Fallback — import orchestrator at call time to avoid circular import
        from backend.agents.orchestrator import orchestrate as fallback_orchestrate  # type: ignore

        return await fallback_orchestrate(query, language, location, session_id)

    init_state: ORCAState = {
        "query": query or "",
        "language": language or "en",
        "location": location,
        "session_id": session_id or uuid.uuid4().hex,
    }

    # Handle no-location early (planner will set user_location=None)
    final = await graph.ainvoke(init_state)

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
    }


async def orchestrate_stream_via_graph(
    query: str,
    language: str = "en",
    location: dict | None = None,
    session_id: str | None = None,
):
    """
    PROTOTYPE — SSE streaming via graph.astream_events (wayfinder #27, map #22).

    ROUGH DRAFT for human review — NOT FINAL. Direction to react to, not a
    production implementation. Known shortcuts are marked PROTOTYPE below.

    Intended event order (docs/API.md strict):
      status* -> map -> safety -> token+ -> evidence -> done
    (``error`` events may appear anywhere on timeout/failure and are ignored
    for ordering purposes.)

    Strategy:
      - Consume ``graph.astream_events(init_state, version='v2')``.
      - ``on_chain_start`` for known nodes -> ``status/running`` (only while
        no ``map`` has been emitted yet, to preserve the strict order above).
      - ``on_chain_end`` for ``fish_finder`` -> ``status/done`` +
        immediate ``map`` (early flyTo, provisional) built from raw fish results.
      - ``on_chain_end`` for ``parallel_analysis`` (current topology runs the
        3 sea/weather/danger sub-agents inside one node via
        ``asyncio.gather``, so per-sub-agent events do NOT exist) -> stash
        sea/weather/danger, then single ``safety`` (provisional via combiner).
      - ``on_chain_end`` for ``decision_agent`` -> flush buffered chat-model
        tokens, then chunked ``token`` events from its reply.
      - After the stream drains -> ``evidence`` -> ``done``.
      - No-location path (planner yields no user_location) uses empty map /
        amber safety / location-prompt tokens, same order.
      - ``graph is None`` falls back to ``orchestrator.orchestrate_stream``.

    PROTOTYPE timeouts (map decision #26: 1.4s sub-agent budget, P95<2.0s):
      per-node budget is OBSERVED only — an ``error`` event is emitted when a
      node exceeds 1.4s but the slow node is NOT preempted (LangGraph stream
      mode has no per-node cancel; true preemption needs Send fan-out +
      per-task wait_for like the orchestrator fallback). Total P95 is logged,
      not enforced.

    PROTOTYPE tradeoffs for the human (see report):
      1. Strict order vs full status coverage: statuses after the early ``map``
         are SUPPRESSED (parallel/decision dones) so the ``status* -> map``
         assertion holds. Alternative is interleaved statuses (map truly early
         but statuses after map) — needs a contract decision.
      2. ``safety`` before ``decision_agent`` finishes is PROVISIONAL (own
         combiner call, duplicates decision work). Final decision safety may
         differ; we do not re-emit.
      3. No ``on_chat_model_stream`` exists today (decision_agent is a
         deterministic combiner, not an LLM) — chunked ``_chunk_text`` tokens
         are pseudo-streaming. A ``token_buf`` is kept for forward-compat.
      4. Node names now match docs/API.md SSE agent names
         (fish_finder/sea_checker/weather_agent/danger_agent).
      5. Streaming path persists Redis session best-effort (mirrors
         non-streaming path) before done.
    """
    graph = get_orca_graph()
    if graph is None:
        from backend.agents.orchestrator import orchestrate_stream as fallback_stream  # type: ignore

        async for evt in fallback_stream(query, language, location, session_id):
            yield evt
        return

    # PROTOTYPE budgets (map decision #26)
    PROTOTYPE_NODE_TIMEOUT_S = 1.4
    P95_BUDGET_S = 2.0
    # Current compiled topology: planner -> fish_finder ->
    # parallel_analysis -> decision_agent. Sub-agent names kept for
    # forward-compat (never emitted today — see parallel_analysis_node).
    KNOWN_NODES = (
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

    user_location: dict | None = None
    fish_results: list[dict] | None = None
    sea_results: list[dict] | None = None
    weather_results: list[dict] | None = None
    danger_results: list[dict] | None = None
    decision_out: dict | None = None
    final_state: dict = {}
    token_buf: list[str] = []

    map_emitted = False
    safety_emitted = False

    def _proto_map_payload() -> dict:
        # PROTOTYPE provisional map from raw fish results (early flyTo).
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

    def _proto_safety_payload() -> dict:
        # PROTOTYPE provisional safety via own combiner call so safety can be
        # emitted at parallel_analysis end, before decision_agent finishes.
        # Field names match docs/API.md exactly: waves_m/wind_kts/danger/badge.
        # Early events carry provisional:true; final decision safety does not.
        ul = user_location or final_state.get("user_location") or {"lat": 0, "lon": 0}
        fish = fish_results or []
        if not fish:
            return {"type": "safety", "waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber", "provisional": True}
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
            logger.warning("graph.stream PROTOTYPE combiner failed: %s", exc)
            best = None
        if not isinstance(best, dict):
            return {"type": "safety", "waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber", "provisional": True}
        # Mirror decision_agent badge reasoning (duplicated for earliness).
        best_id = str(best.get("zone_id")) if best.get("zone_id") else None
        sea_s = wind_s = danger_s = "safe"
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
        waves_m = best.get("wave_height_m")
        wind_kts = best.get("wind_kt") if best.get("wind_kt") is not None else best.get("wind_speed_kt")
        return {"type": "safety", "waves_m": waves_m, "wind_kts": wind_kts, "danger": danger_field, "badge": badge, "provisional": True}

    init_state: ORCAState = {"query": query or "", "language": language or "en", "location": location, "session_id": sid}

    try:
        async for ev in graph.astream_events(init_state, version="v2"):
            etype = ev.get("event")
            name = ev.get("name")
            now = time.perf_counter()

            # Forward-compat: stream LLM tokens if a chat model is ever added
            # inside decision_agent. Buffered until safety is out to keep
            # strict status->map->safety->tokens order.
            if etype == "on_chat_model_stream":
                try:
                    data = ev.get("data") or {}
                    chunk = data.get("chunk")
                    text = ""
                    if isinstance(chunk, str):
                        text = chunk
                    elif chunk is not None:
                        text = getattr(chunk, "content", "") or ""
                        if not isinstance(text, str):
                            text = str(text) if text else ""
                    if text:
                        if safety_emitted and map_emitted:
                            yield {"type": "token", "text": text}
                        else:
                            token_buf.append(text)
                except Exception:
                    pass
                continue

            if etype == "on_chain_start" and name in KNOWN_NODES:
                node_start[name] = now
                # PROTOTYPE: suppress post-map statuses to hold strict order.
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
            # PROTOTYPE observability only — does not preempt the slow node.
            if elapsed_s > PROTOTYPE_NODE_TIMEOUT_S:
                yield {
                    "type": "error",
                    "agent": name,
                    "message": f"PROTOTYPE timeout {elapsed_s:.2f}s > {PROTOTYPE_NODE_TIMEOUT_S}s budget",
                    "fallback": "unknown",
                }

            if name == "planner":
                ul = output.get("user_location") if isinstance(output, dict) else None
                if isinstance(ul, dict) and ul.get("lat") is not None and ul.get("lon") is not None:
                    try:
                        user_location = {"lat": float(ul["lat"]), "lon": float(ul["lon"])}
                    except (TypeError, ValueError):
                        user_location = None
                if not map_emitted:
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
                    yield _proto_map_payload()
                    map_emitted = True
                # PROTOTYPE: later statuses suppressed (see docstring tradeoff).

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
                    yield _proto_map_payload()
                    map_emitted = True
                if not safety_emitted:
                    yield _proto_safety_payload()
                    safety_emitted = True

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
                    yield _proto_safety_payload()
                    safety_emitted = True

            elif name == "decision_agent":
                if isinstance(output, dict):
                    decision_out = output
                else:
                    decision_out = {}
                # Guarantee map/safety precede tokens (strict order).
                if not map_emitted:
                    if isinstance(decision_out.get("map"), dict):
                        dm = decision_out["map"]
                        yield {
                            "type": "map",
                            "center": dm.get("center"),
                            "pfz_features": dm.get("pfz_features") or [],
                            "route": dm.get("route") or [],
                        }
                    else:
                        yield _proto_map_payload()
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
                        yield _proto_safety_payload()
                    safety_emitted = True
                for buffered in token_buf:
                    yield {"type": "token", "text": buffered}
                token_buf.clear()
                reply = decision_out.get("reply") or decision_out.get("explanation") or ""
                chunks = _chunk_text(reply)
                for idx, ch in enumerate(chunks):
                    suffix = " " if idx < len(chunks) - 1 else ""
                    yield {"type": "token", "text": ch + suffix}
                # CORR-04: explicit synthesis error — never silent (fallback:none).
                _synth_err = decision_out.get("synthesis_error")
                if isinstance(_synth_err, dict) and _synth_err:
                    yield _synth_err

    except Exception as exc:
        logger.warning("graph.stream PROTOTYPE failed: %s", exc)
        yield {"type": "error", "agent": "decision_agent", "message": f"PROTOTYPE stream failed: {exc}", "fallback": "unknown"}

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
        if decision_out is None:
            prompt = "Please share your GPS location or mention a coastal place like Kochi, Veraval, or Chennai to find nearby fishing zones."
            for chunk in _chunk_text(prompt):
                yield {"type": "token", "text": chunk + " "}
        yield {"type": "evidence", "items": ["Location not provided — cannot search PFZ zones"]}
        yield {"type": "done", "language": final_state.get("language") or language, "confidence": DEGRADED_CONFIDENCE, "session_id": final_state.get("session_id") or sid}
        return

    dout = decision_out or {}
    if not map_emitted:
        if isinstance(dout.get("map"), dict):
            dm = dout["map"]
            yield {
                "type": "map",
                "center": dm.get("center"),
                "pfz_features": dm.get("pfz_features") or [],
                "route": dm.get("route") or [],
            }
        elif isinstance(final_state.get("map"), dict):
            fm = final_state["map"]
            yield {
                "type": "map",
                "center": fm.get("center"),
                "pfz_features": fm.get("pfz_features") or [],
                "route": fm.get("route") or [],
            }
        else:
            yield _proto_map_payload()
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
            yield _proto_safety_payload()
        safety_emitted = True
    for buffered in token_buf:
        yield {"type": "token", "text": buffered}
    token_buf.clear()

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
        # PROTOTYPE: observe P95<2.0s SLA, do not fail the stream.
        logger.warning("graph.stream PROTOTYPE total %.2fs exceeds P95 %.1fs budget", total_s, P95_BUDGET_S)
    confidence = dout.get("confidence") or final_state.get("confidence") or (DEGRADED_CONFIDENCE if final_state.get("degraded") else DEFAULT_CONFIDENCE)
    yield {
        "type": "done",
        "language": dout.get("language") or final_state.get("language") or language,
        "confidence": confidence,
        "session_id": dout.get("session_id") or final_state.get("session_id") or sid,
    }
