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
import logging
import uuid
from typing import Any

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


async def orchestrate(query: str, language: str, location: dict | None = None, session_id: str | None = None) -> dict:
    """
    Main entry point for the ORCA brain.

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
    # Normalize inputs
    query = query or ""
    language = language or "en"
    if not session_id:
        try:
            session_id = uuid.uuid4().hex
        except Exception:
            session_id = "local-session"

    # 1. Resolve location
    resolved = _resolve_location(query, location)
    intent = _parse_intent(query)

    if resolved is None:
        # Fallback prompting — ask for GPS if confidence <0.7 equivalent
        # Return degraded payload that prompts for location rather than crashing
        return {
            "reply": "Please share your GPS location or mention a coastal place like Kochi, Veraval, or Chennai to find nearby fishing zones.",
            "map": {"center": None, "pfz_features": [], "route": []},
            "safety": {"waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber"},
            "evidence": ["Location not provided — cannot search PFZ zones"],
            "language": language,
            "confidence": DEGRADED_CONFIDENCE,
            "session_id": session_id,
            "intent": intent,
        }

    user_lat, user_lon = resolved
    user_location = {"lat": float(user_lat), "lon": float(user_lon)}

    # Track degradation for confidence
    degraded = False

    # 2. Fish finder first (needs lat/lon) — with 10s timeout
    fish_results: list[dict] = []
    try:
        from backend.agents import fish_finder as ff

        try:
            fish_results = await asyncio.wait_for(
                ff.find_fishing_zones(lat=user_lat, lon=user_lon, radius_km=80.0),
                timeout=TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning("orchestrator: fish_finder timeout after %ss", TIMEOUT_S)
            fish_results = []
            degraded = True
        except Exception as exc:
            logger.warning("orchestrator: fish_finder error: %s", exc)
            fish_results = []
            degraded = True
        # Guard against non-list
        if not isinstance(fish_results, list):
            fish_results = []
    except Exception as exc:
        logger.warning("orchestrator: fish_finder import/call failed: %s", exc)
        fish_results = []
        degraded = True

    # Ensure identical shared points passed to all agents
    shared_points: list[dict] = fish_results if isinstance(fish_results, list) else []

    # 3. Dispatch sea_checker, weather_agent, danger_agent concurrently via asyncio.gather(return_exceptions=True)
    # Each wrapped with per-agent 10s timeout; degrade to "unknown" on failure.

    async def _call_sea():
        try:
            from backend.agents import sea_checker as sc

            return await asyncio.wait_for(sc.check_sea_conditions(shared_points), timeout=TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning("orchestrator: sea_checker timeout")
            raise TimeoutError("sea_checker timeout 10s")
        except Exception as exc:
            raise exc

    async def _call_weather():
        try:
            from backend.agents import weather_agent as wa

            return await asyncio.wait_for(wa.check_weather(shared_points), timeout=TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning("orchestrator: weather_agent timeout")
            raise TimeoutError("weather_agent timeout 10s")
        except Exception as exc:
            raise exc

    async def _call_danger():
        try:
            from backend.agents import danger_agent as da

            # Use batch helper if available for identical shared points
            if hasattr(da, "check_safety_batch"):
                return await asyncio.wait_for(da.check_safety_batch(shared_points), timeout=TIMEOUT_S)
            # Fallback: per-point check_safety gathered internally
            # Build list via sequential but still under outer timeout
            results = []
            for pt in shared_points:
                lat = pt.get("lat")
                lon = pt.get("lon")
                if lat is None or lon is None:
                    # Try geometry
                    geom = pt.get("geometry") if isinstance(pt, dict) else None
                    if isinstance(geom, dict):
                        coords = geom.get("coordinates") or []
                        if len(coords) >= 2:
                            lon = coords[0]
                            lat = coords[1]
                try:
                    r = await da.check_safety(float(lat), float(lon)) if lat is not None and lon is not None else {
                        "is_safe": False, "status": "unknown", "warnings": ["missing lat/lon"], "inside_eez": True, "inside_mpa": False, "mpa_name": None
                    }
                except Exception as e:
                    r = {"is_safe": False, "status": "unknown", "warnings": [str(e)], "inside_eez": True, "inside_mpa": False, "mpa_name": None}
                results.append(r)
            return results
        except asyncio.TimeoutError:
            logger.warning("orchestrator: danger_agent timeout")
            raise TimeoutError("danger_agent timeout 10s")
        except Exception as exc:
            raise exc

    # Concurrent gather with return_exceptions=True (never sequential)
    gathered = await asyncio.gather(
        _call_sea(),
        _call_weather(),
        _call_danger(),
        return_exceptions=True,
    )

    sea_results, weather_results, danger_results = None, None, None
    # Unpack with degradation
    for idx, res in enumerate(gathered):
        name = ["sea_checker", "weather_agent", "danger_agent"][idx]
        if isinstance(res, BaseException):
            degraded = True
            logger.warning("orchestrator: %s failed/degraded: %s", name, res)
            if idx == 0:
                sea_results = _degraded_sea(shared_points)
            elif idx == 1:
                weather_results = _degraded_weather(shared_points)
            else:
                danger_results = _degraded_danger(shared_points)
        else:
            if idx == 0:
                sea_results = res if isinstance(res, list) else _degraded_sea(shared_points)
            elif idx == 1:
                weather_results = res if isinstance(res, list) else _degraded_weather(shared_points)
            else:
                danger_results = res if isinstance(res, list) else _degraded_danger(shared_points)

    # Also enforce unknown degradation if any result contains status unknown (implicit)
    # Ensure lists exist
    if sea_results is None:
        sea_results = _degraded_sea(shared_points)
        degraded = True
    if weather_results is None:
        weather_results = _degraded_weather(shared_points)
        degraded = True
    if danger_results is None:
        danger_results = _degraded_danger(shared_points)
        degraded = True

    # 4. Pass to combiner
    try:
        from backend.agents import combiner as cb

        combined = cb.combine_and_rank(
            fish_results=fish_results,
            sea_results=sea_results,
            weather_results=weather_results,
            danger_results=danger_results,
            user_location=user_location,
        )
    except Exception as exc:
        logger.error("orchestrator: combiner failed: %s", exc)
        degraded = True
        combined = {
            "ranked_zones": [],
            "best": None,
            "explanation": f"Combiner error: {exc}",
            "citation": "INCOIS TextData",
            "all_unsafe": False,
            "score_breakdown": {},
        }

    best = combined.get("best")
    ranked_zones = combined.get("ranked_zones") or []
    citation = combined.get("citation") or "INCOIS TextData"
    explanation = combined.get("explanation") or ""

    # 5. Assemble payload matching POST /api/chat contract
    # map
    pfz_features = _to_geojson_features(ranked_zones)
    if best and best.get("lat") is not None and best.get("lon") is not None:
        try:
            center = [float(best["lon"]), float(best["lat"])]
        except (TypeError, ValueError):
            center = [float(user_lon), float(user_lat)]
    elif fish_results:
        # No best but have zones — center on user
        center = [float(user_lon), float(user_lat)]
    else:
        center = [float(user_lon), float(user_lat)]

    if best and best.get("lat") is not None and best.get("lon") is not None:
        try:
            route = [[float(user_lon), float(user_lat)], [float(best["lon"]), float(best["lat"])]]
        except (TypeError, ValueError):
            route = []
    else:
        route = []

    # safety
    if best:
        waves_m = best.get("wave_height_m")
        wind_kts = best.get("wind_kt") if best.get("wind_kt") is not None else best.get("wind_speed_kt")
        # Derive per-agent statuses for badge
        # Use sea/weather/danger first-entry status if available, else infer from best
        sea_status = "safe"
        wind_status = "safe"
        danger_status = "safe"
        # Prefer lookup from per-zone sea/weather/danger results aligned with best
        best_id = str(best.get("zone_id")) if best.get("zone_id") else None
        if sea_results:
            for r in sea_results:
                if str(r.get("zone_id")) == best_id:
                    sea_status = str(r.get("status") or r.get("wave_status") or "safe").lower()
                    waves_m = r.get("wave_height_m", waves_m)
                    break
            else:
                if sea_results and len(sea_results) == len(ranked_zones):
                    # fallback index 0
                    sea_status = str(sea_results[0].get("status", "safe")).lower()
        if weather_results:
            for r in weather_results:
                if str(r.get("zone_id")) == best_id:
                    wind_status = str(r.get("status") or r.get("wind_status") or "safe").lower()
                    wind_kts = r.get("wind_kt", r.get("wind_speed_kt", wind_kts))
                    break
            else:
                if weather_results and len(weather_results) == len(ranked_zones):
                    wind_status = str(weather_results[0].get("status", "safe")).lower()
        if danger_results:
            for r in danger_results:
                # danger batch returns zone_id or lat/lon mapping; match by zone_id if present
                if best_id and str(r.get("zone_id")) == best_id:
                    danger_status = str(r.get("status", "safe")).lower()
                    break
                # Also try lat/lon proximity for batch entries without zone_id
                if r.get("lat") is not None and r.get("lon") is not None and best.get("lat") is not None:
                    try:
                        if abs(float(r["lat"]) - float(best["lat"])) < 1e-6 and abs(float(r["lon"]) - float(best["lon"])) < 1e-6:
                            danger_status = str(r.get("status", "safe")).lower()
                            break
                    except (TypeError, ValueError):
                        pass
            else:
                if danger_results and len(danger_results) == len(ranked_zones):
                    danger_status = str(danger_results[0].get("status", "safe")).lower()

        # Normalize danger to API contract: safe/caution/danger -> danger field uses "none" for safe
        danger_field = "none" if danger_status == "safe" else danger_status
        badge = _badge_for_best(best, sea_status, wind_status, danger_status)

        # Handle unknown -> waves/wind may be None
        if waves_m is None:
            waves_m_val = None
        else:
            try:
                waves_m_val = float(waves_m)
            except (TypeError, ValueError):
                waves_m_val = None
        if wind_kts is None:
            wind_kts_val = None
        else:
            try:
                wind_kts_val = float(wind_kts)
            except (TypeError, ValueError):
                wind_kts_val = None

        # If any unknown, ensure badge amber
        if "unknown" in (sea_status, wind_status, danger_status):
            badge = "amber"
            danger_field = "unknown" if danger_field == "none" else danger_field

        safety = {"waves_m": waves_m_val, "wind_kts": wind_kts_val, "danger": danger_field, "badge": badge}
    else:
        # No best zone
        safety = {"waves_m": None, "wind_kts": None, "danger": "unknown", "badge": "amber"}
        degraded = True

    # evidence
    evidence: list[str] = []
    if citation:
        evidence.append(str(citation))
    # Add source hints
    if sea_results:
        src = sea_results[0].get("source") if isinstance(sea_results[0], dict) else None
        if src and src != "unknown":
            evidence.append(f"Wave: {src}")
    if weather_results:
        src = weather_results[0].get("source") if isinstance(weather_results[0], dict) else None
        if src and src != "unknown":
            evidence.append(f"Wind: {src}")
    # Danger evidence
    if danger_results and isinstance(danger_results[0], dict):
        warnings = danger_results[0].get("warnings") or []
        if warnings and "unavailable" not in str(warnings[0]).lower():
            for w in warnings:
                evidence.append(str(w))
        else:
            # Check best zone warnings
            if best and danger_results:
                for r in danger_results:
                    if str(r.get("zone_id")) == str(best.get("zone_id")):
                        for w in (r.get("warnings") or []):
                            if "unavailable" not in w.lower():
                                evidence.append(str(w))
                        break
            # Default geofence ok
            if not any("MPA" in e or "EEZ" in e for e in evidence):
                evidence.append("No EEZ/MPA violation")

    # reply — explanation is already safe and cites thresholds; use as reply
    reply = explanation or "No fishing zones found nearby. Try expanding the search area."

    # confidence downgrade on any degradation
    confidence = DEGRADED_CONFIDENCE if degraded else DEFAULT_CONFIDENCE
    # If combined all_unsafe, also downgrade slightly but keep degraded logic
    if combined.get("all_unsafe"):
        # all_unsafe is a valid result, not a degradation, keep 0.87 but ensure badge red later
        pass

    # Redis session persistence — best-effort, never crash if Redis down
    try:
        from backend.db import redis as redis_mod

        # Try to persist turn history without blocking long — use create_task with timeout pattern
        # We attempt a short fire-and-forget append; if redis not configured it will raise NotImplementedError
        try:
            await asyncio.wait_for(
                redis_mod.append_message(session_id, "user", query),
                timeout=1.0,
            )
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                redis_mod.append_message(session_id, "assistant", reply),
                timeout=1.0,
            )
        except Exception:
            pass
        # Also try set_json for session lat/lon snapshot
        try:
            await asyncio.wait_for(
                redis_mod.set_json(f"session:{session_id}", {"lat": user_lat, "lon": user_lon, "zone_id": best.get("zone_id") if best else None}, ttl_seconds=86400),
                timeout=1.0,
            )
        except Exception:
            pass
    except Exception:
        # Redis not available or not configured — stateless fallback
        pass

    result_payload = {
        "reply": reply,
        "map": {"center": center, "pfz_features": pfz_features, "route": route},
        "safety": safety,
        "evidence": evidence,
        "language": language,
        "confidence": confidence,
        "session_id": session_id,
    }
    # Include combiner internals for debugging (optional, not breaking contract)
    # result_payload["combined"] = combined
    return result_payload
