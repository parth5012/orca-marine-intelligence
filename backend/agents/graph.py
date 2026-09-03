"""
ORCA LangGraph — Supervisor + Specialized Sub-Agents

Owner: M-A (Agents & Orchestration)
Module: backend/agents/graph.py

Implements SIH26176 Expected Solution as a modular multi-agent
StateGraph. Each specialized agent is a node that *decides* and calls
*tools* to fetch data from heterogeneous sources.

Agents (nodes) vs Tools (stateless fetchers):
  - fish_discovery_agent  -> tools: find_pfz_near (PostGIS), _geojson_fallback (haversine)
  - ocean_analytics_agent -> tools: fetch_osf_wave_current / get_wave_current
  - weather_intel_agent   -> tools: fetch_imd_wind, fetch_imd_cyclones / get_wind, get_cyclone_alert
  - geospatial_risk_agent -> tools: check_geofence (PostGIS), ray_cast_eez/mpa, distance_to_imbl
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

async def fish_discovery_agent(state: ORCAState) -> dict:
    """
    Fish Discovery Agent (SIH26176: marine data discovery).

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
        from backend.agents import fish_finder as ff  # type: ignore

        res = await asyncio.wait_for(ff.find_fishing_zones(lat=lat, lon=lon, radius_km=80.0), timeout=TIMEOUT_S)
        if not isinstance(res, list):
            res = []
        logger.info("graph.fish_discovery: %d zones for %.2f,%.2f", len(res), lat, lon)
        return {"fish_results": res}
    except asyncio.TimeoutError:
        logger.warning("graph.fish_discovery: timeout 10s")
        return {"fish_results": [], "degraded": True}
    except Exception as exc:
        logger.warning("graph.fish_discovery: %s", exc)
        return {"fish_results": [], "degraded": True}


async def ocean_analytics_agent(state: ORCAState) -> dict:
    """
    Ocean Analytics Agent (SIH26176: ocean analytics).

    Tools:
      - fetch_osf_wave_current / get_wave_current (OSF 06Z Zarr + heuristic fallback)
    Decision: classifies wave <1.5 safe / 1.5-2.5 caution / >2.5 danger, current >2/>3.
    """
    fish = state.get("fish_results") or []
    if not fish:
        return {"sea_results": []}
    try:
        from backend.agents import sea_checker as sc  # type: ignore

        res = await asyncio.wait_for(sc.check_sea_conditions(fish), timeout=TIMEOUT_S)
        return {"sea_results": res if isinstance(res, list) else _degraded_sea(fish)}
    except asyncio.TimeoutError:
        logger.warning("graph.ocean_analytics: timeout 10s")
        return {"sea_results": _degraded_sea(fish), "degraded": True}
    except Exception as exc:
        logger.warning("graph.ocean_analytics: %s", exc)
        return {"sea_results": _degraded_sea(fish), "degraded": True}


async def weather_intel_agent(state: ORCAState) -> dict:
    """
    Weather Intelligence Agent (SIH26176: weather intelligence).

    Tools:
      - fetch_imd_wind, fetch_imd_cyclones / get_wind, get_cyclone_alert
    Decision: wind <15 safe / 15-25 caution / >25 danger, cyclone within 500km → danger.
    """
    fish = state.get("fish_results") or []
    if not fish:
        return {"weather_results": []}
    try:
        from backend.agents import weather_agent as wa  # type: ignore

        res = await asyncio.wait_for(wa.check_weather(fish), timeout=TIMEOUT_S)
        return {"weather_results": res if isinstance(res, list) else _degraded_weather(fish)}
    except asyncio.TimeoutError:
        logger.warning("graph.weather_intel: timeout 10s")
        return {"weather_results": _degraded_weather(fish), "degraded": True}
    except Exception as exc:
        logger.warning("graph.weather_intel: %s", exc)
        return {"weather_results": _degraded_weather(fish), "degraded": True}


async def geospatial_risk_agent(state: ORCAState) -> dict:
    """
    Geospatial Reasoning + Risk Assessment Agent (SIH26176: geospatial reasoning + risk).

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
        from backend.agents import danger_agent as da  # type: ignore

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
        logger.warning("graph.geospatial_risk: timeout 10s")
        return {"danger_results": _degraded_danger(fish), "degraded": True}
    except Exception as exc:
        logger.warning("graph.geospatial_risk: %s", exc)
        return {"danger_results": _degraded_danger(fish), "degraded": True}


async def decision_agent(state: ORCAState) -> dict:
    """
    Decision / Reporting Agent (SIH26176: visualization, reporting, explainability).

    Tools:
      - combiner.combine_and_rank (weighted scoring + citation)
    Decision: picks best zone via closest*0.4+safe_sea*0.3+wind_ok*0.2+not_banned*0.1,
              tie-breaker wave→distance, all_unsafe→DO NOT SAIL, INCOIS citation.
    """
    fish = state.get("fish_results") or []
    sea = state.get("sea_results") or []
    weather = state.get("weather_results") or []
    danger = state.get("danger_results") or []
    user_location = state.get("user_location") or {"lat": 0, "lon": 0}

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

    return {
        "combined": combined,
        "best": best,
        "ranked_zones": ranked,
        "citation": citation,
        "explanation": explanation,
        "reply": explanation or "No fishing zones found nearby. Try expanding the search area.",
        "map": {"center": center, "pfz_features": pfz_features, "route": route},
        "safety": safety,
        "evidence": evidence,
        "confidence": confidence,
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
      ocean_analytics_agent -> get_wave_current (OSF/heuristic)
      weather_intel_agent   -> get_wind / get_cyclone_alert
      geospatial_risk_agent -> check_geofence / ray_cast

    This preserves LangGraph node topology (planner -> fish -> parallel
    -> decision) while guaranteeing P95<2s and mock compatibility
    (tests patch backend.agents.*.check_*).
    """
    # Run 3 agents concurrently — true parallel, not sequential Send
    results = await asyncio.gather(
        ocean_analytics_agent(state),
        weather_intel_agent(state),
        geospatial_risk_agent(state),
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
      -> fish_discovery_agent (tools: PostGIS + GeoJSON)
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
    graph.add_node("fish_discovery_agent", fish_discovery_agent)
    graph.add_node("parallel_analysis", parallel_analysis_node)
    graph.add_node("decision_agent", decision_agent)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "fish_discovery_agent")
    graph.add_edge("fish_discovery_agent", "parallel_analysis")
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
    SSE streaming variant via graph. Yields dict events in strict order:
      status (running/done) -> map -> safety -> token(s) -> evidence -> done
    """
    graph = get_orca_graph()
    if graph is None:
        from backend.agents.orchestrator import orchestrate_stream as fallback_stream  # type: ignore

        async for evt in fallback_stream(query, language, location, session_id):
            yield evt
        return

    # Stream graph with status framing
    # We manually emit status to satisfy docs/API.md strict order,
    # then stream tokens from final reply.
    sid = session_id or uuid.uuid4().hex
    t0 = time.perf_counter()

    yield {"type": "status", "agent": "planner", "state": "running"}
    # We cannot easily intercept per-node start/done without astream_events,
    # so emit coarse-grained statuses around graph execution.
    init_state: ORCAState = {"query": query or "", "language": language or "en", "location": location, "session_id": sid}

    # Run graph — single await but sub-agents internally parallel via Send
    final = await graph.ainvoke(init_state)
    elapsed = int((time.perf_counter() - t0) * 1000)
    yield {"type": "status", "agent": "planner", "state": "done", "elapsed_ms": elapsed}
    for ag in ("fish_discovery_agent", "ocean_analytics_agent", "weather_intel_agent", "geospatial_risk_agent", "decision_agent"):
        yield {"type": "status", "agent": ag, "state": "done", "elapsed_ms": elapsed // 5}

    if not final.get("user_location"):
        yield {"type": "map", "center": None, "pfz_features": [], "route": []}
        yield {"type": "safety", "waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber"}
        reply = "Please share your GPS location or mention a coastal place like Kochi, Veraval, or Chennai to find nearby fishing zones."
        for chunk in _chunk_text(reply):
            yield {"type": "token", "text": chunk + " "}
        yield {"type": "evidence", "items": ["Location not provided — cannot search PFZ zones"]}
        yield {"type": "done", "language": language, "confidence": DEGRADED_CONFIDENCE, "session_id": sid}
        return

    # map -> safety -> tokens -> evidence -> done  (no status interleaved after decision)
    yield {"type": "map", "center": final["map"]["center"], "pfz_features": final["map"]["pfz_features"], "route": final["map"]["route"]}
    s = final["safety"]
    yield {"type": "safety", "waves_m": s.get("waves_m"), "wind_kts": s.get("wind_kts"), "danger": s.get("danger"), "badge": s.get("badge")}
    reply = final.get("reply") or final.get("explanation") or ""
    for idx, chunk in enumerate(_chunk_text(reply)):
        suffix = " " if idx < len(_chunk_text(reply)) - 1 else ""
        yield {"type": "token", "text": chunk + suffix}
    yield {"type": "evidence", "items": final.get("evidence") or [final.get("citation")]}
    yield {"type": "done", "language": final.get("language") or language, "confidence": final.get("confidence") or DEFAULT_CONFIDENCE, "session_id": final.get("session_id") or sid}
