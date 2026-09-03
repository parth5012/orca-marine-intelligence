"""
Smart Combiner — Fusion Ranking Agent

Owner: M-A (Agents & Orchestration) — ranking & evidence
Module: backend/agents/combiner.py

The Smart Combiner receives results from all four specialist agents and
produces a single ranked list of safe fishing zones. It ensures that the
recommended spot is not just the closest, but the safest and most productive.

Scoring Formula:
    score = closest * 0.4 + safe_sea * 0.3 + wind_ok * 0.2 + not_banned * 0.1

    - closest:    1.0 - (distance_km / max_dist) normalized to [0,1]
    - safe_sea:   1.0 if wave < 1.5 else max(0.0, 1.0 - (wave-1.5)/1.5)
    - wind_ok:    1.0 if wind < 15 else max(0.0, 1.0 - (wind-15)/15)
    - not_banned: 0.0 if inside_mpa or not inside_eez else 1.0

Edge Cases:
    - All spots unsafe → return warning with all_unsafe=True, advisory DO NOT SAIL
    - No spots → empty ranked_zones, best=None
    - Tie in score → lower wave wins, then closer distance
"""

from datetime import datetime, timezone
from typing import Any


def _get_distance(fish: dict) -> float | None:
    for k in ("distance_from_user_km", "distance_km", "distance"):
        v = fish.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _get_wave(sea: dict | None) -> float | None:
    if not sea:
        return None
    for k in ("wave_height_m", "wave_m", "wave", "wave_height"):
        v = sea.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _get_wind(weather: dict | None) -> float | None:
    if not weather:
        return None
    for k in ("wind_kt", "wind_speed_kt", "wind_speed_kts", "wind", "wind_speed"):
        v = weather.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _get_sector(fish: dict) -> str:
    # fish_finder normalized uses sector_name as sector field
    s = fish.get("sector") or fish.get("sector_name") or fish.get("sector_code") or ""
    # if sector looks like human name (KERALA) keep, if SEC code keep
    return str(s).strip() if s else "UNKNOWN"


def _build_lookup(results: list[dict] | None) -> dict[str, dict]:
    if not results:
        return {}
    lookup: dict[str, dict] = {}
    for idx, r in enumerate(results):
        if not isinstance(r, dict):
            continue
        zid = r.get("zone_id") or r.get("id") or f"idx_{idx}"
        lookup[str(zid)] = r
    return lookup


def combine_and_rank(
    fish_results: list[dict],
    sea_results: list[dict],
    weather_results: list[dict],
    danger_results: list[dict],
    user_location: dict,
) -> dict:
    """
    Rank PFZ zones by composite safety and proximity score.

    Args:
        fish_results: Closest PFZ points from FishFinder agent.
        sea_results: Wave/current data from SeaChecker agent.
        weather_results: Wind/tide data from WeatherAgent.
        danger_results: Geofence/cyclone checks from DangerAgent.
        user_location: {"lat": float, "lon": float} of the fisherman.

    Returns:
        {
            "ranked_zones": [...],
            "best": {"place": str, "lat": float, "lon": float, "score": float},
            "explanation": str,
            "citation": str,
            "all_unsafe": bool,
            "score_breakdown": dict
        }
    """
    # Handle None inputs gracefully
    fish_results = fish_results or []
    sea_results = sea_results or []
    weather_results = weather_results or []
    danger_results = danger_results or []

    # Filter to valid dict entries
    fish_results = [f for f in fish_results if isinstance(f, dict)]

    # Date for citation: DD-Mmm-YYYY, use IST-aware current date (UTC+5:30)
    try:
        # Use current date in IST if possible
        from datetime import timedelta

        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(tz=ist)
    except Exception:
        now = datetime.now()
    date_str = now.strftime("%d-%b-%Y")

    # Empty case
    if not fish_results:
        citation = f"INCOIS TextData {date_str}"
        return {
            "ranked_zones": [],
            "best": None,
            "explanation": "No fishing zones found within search radius. Try expanding the search area or check back later.",
            "citation": citation,
            "all_unsafe": False,
            "score_breakdown": {},
        }

    # Build lookups by zone_id for cross-agent join; fallback to index alignment
    sea_lookup = _build_lookup(sea_results)
    weather_lookup = _build_lookup(weather_results)
    danger_lookup = _build_lookup(danger_results)

    # Compute max_dist for normalization
    distances: list[float] = []
    for f in fish_results:
        d = _get_distance(f)
        if d is not None:
            distances.append(d)
    max_dist = max(distances) if distances else 0.0
    # Avoid division by zero; all zero distance -> closest=1.0
    if max_dist == 0:
        max_dist = 1.0  # ensures 1 - 0/1 =1
    is_single = len(fish_results) == 1

    ranked: list[dict] = []

    for idx, fish in enumerate(fish_results):
        zone_id = str(fish.get("zone_id") or fish.get("id") or f"zone_{idx}")
        place = str(fish.get("place") or fish.get("name") or "Unknown")
        sector = _get_sector(fish)

        # Lat/lon - handle both flat and GeoJSON shapes gracefully
        lat = fish.get("lat")
        lon = fish.get("lon")
        # GeoJSON fallback
        if lat is None or lon is None:
            geom = fish.get("geometry")
            if isinstance(geom, dict):
                coords = geom.get("coordinates")
                if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    try:
                        lon = float(coords[0])
                        lat = float(coords[1])
                    except (TypeError, ValueError):
                        pass
        try:
            lat_f = float(lat) if lat is not None else None
        except (TypeError, ValueError):
            lat_f = None
        try:
            lon_f = float(lon) if lon is not None else None
        except (TypeError, ValueError):
            lon_f = None

        # Distance
        dist = _get_distance(fish)
        if dist is None:
            # If missing distance, assume 0 (closest)
            dist_val = 0.0
            closest = 1.0
        elif is_single:
            # Single zone should be maximally close
            dist_val = float(dist)
            closest = 1.0
        else:
            dist_val = float(dist)
            closest = 1.0 - (dist_val / max_dist)
            # Clamp [0,1]
            closest = max(0.0, min(1.0, closest))

        # Sea: wave
        sea_entry = sea_lookup.get(zone_id)
        # Fallback index alignment if zone_id not matched
        if sea_entry is None and idx < len(sea_results) and isinstance(sea_results[idx], dict):
            # Only use index fallback if lengths match fish_results
            if len(sea_results) == len(fish_results):
                sea_entry = sea_results[idx]
        wave = _get_wave(sea_entry)
        if wave is None:
            wave_val = 0.0  # missing -> assume safe
            safe_sea = 1.0
        else:
            wave_val = float(wave)
            if wave_val < 1.5:
                safe_sea = 1.0
            else:
                safe_sea = max(0.0, 1.0 - (wave_val - 1.5) / 1.5)

        # Weather: wind
        weather_entry = weather_lookup.get(zone_id)
        if weather_entry is None and idx < len(weather_results) and isinstance(weather_results[idx], dict):
            if len(weather_results) == len(fish_results):
                weather_entry = weather_results[idx]
        wind = _get_wind(weather_entry)
        if wind is None:
            wind_val = 0.0  # missing -> assume safe
            wind_ok = 1.0
        else:
            wind_val = float(wind)
            if wind_val < 15:
                wind_ok = 1.0
            else:
                wind_ok = max(0.0, 1.0 - (wind_val - 15) / 15)

        # Danger: inside_eez, inside_mpa
        danger_entry = danger_lookup.get(zone_id)
        if danger_entry is None and idx < len(danger_results) and isinstance(danger_results[idx], dict):
            if len(danger_results) == len(fish_results):
                danger_entry = danger_results[idx]
        if danger_entry is None:
            inside_eez = True
            inside_mpa = False
        else:
            # Defaults: inside_eez True, inside_mpa False if missing
            inside_eez_raw = danger_entry.get("inside_eez")
            inside_mpa_raw = danger_entry.get("inside_mpa")
            # Also handle alternative keys
            if inside_eez_raw is None:
                inside_eez_raw = danger_entry.get("insideEEZ")
            if inside_mpa_raw is None:
                inside_mpa_raw = danger_entry.get("insideMPA")
            inside_eez = bool(inside_eez_raw) if inside_eez_raw is not None else True
            inside_mpa = bool(inside_mpa_raw) if inside_mpa_raw is not None else False

        not_banned = 0.0 if (inside_mpa or not inside_eez) else 1.0

        score = closest * 0.4 + safe_sea * 0.3 + wind_ok * 0.2 + not_banned * 0.1
        score = round(float(score), 4)

        breakdown = {
            "closest": round(float(closest), 4),
            "safe_sea": round(float(safe_sea), 4),
            "wind_ok": round(float(wind_ok), 4),
            "not_banned": round(float(not_banned), 4),
            "score": score,
        }

        # Build ranked entry preserving original fish fields plus computed
        entry = {
            "zone_id": zone_id,
            "place": place,
            "sector": sector,
            "lat": lat_f,
            "lon": lon_f,
            "distance_km": round(float(dist_val), 2),
            "distance_from_user_km": round(float(dist_val), 2),
            "wave_height_m": round(float(wave_val), 2),
            "wind_kt": round(float(wind_val), 2),
            "wind_speed_kt": round(float(wind_val), 2),
            "inside_eez": inside_eez,
            "inside_mpa": inside_mpa,
            "score": score,
            "score_breakdown": breakdown,
            # preserve original fish props for map rendering
            "bearing": fish.get("bearing"),
            "direction": fish.get("direction") or fish.get("dir"),
            "depth_range": fish.get("depth_range") or fish.get("depth") or "",
        }
        ranked.append(entry)

    # Tie-breaker: sort descending score, then lower wave, then closer distance
    ranked.sort(key=lambda z: (-z["score"], z["wave_height_m"], z["distance_km"]))

    # All-unsafe detection: every zone exceeds at least one safety threshold
    # Thresholds: wave >=1.5 or wind >=15 or banned (not_banned==0)
    all_unsafe = False
    if ranked:
        unsafe_count = 0
        for z in ranked:
            bd = z["score_breakdown"]
            # safe_sea <1 means wave >=1.5, wind_ok <1 means wind >=15, not_banned==0 banned
            if bd["safe_sea"] < 1.0 or bd["wind_ok"] < 1.0 or bd["not_banned"] == 0.0:
                unsafe_count += 1
        if unsafe_count == len(ranked):
            all_unsafe = True

    best = ranked[0] if ranked else None

    # Generate citation: INCOIS TextData {sector} {place} {date}
    if best:
        # sector may be human name like KERALA; keep as is, uppercase sector code variant?
        # Use best sector and place
        citation_sector = best.get("sector") or "UNKNOWN"
        citation_place = best.get("place") or "Unknown"
        citation = f"INCOIS TextData {citation_sector} {citation_place} {date_str}"
    else:
        citation = f"INCOIS TextData {date_str}"

    # Generate human-readable explanation
    if best is None:
        explanation = "No fishing zones found within search radius. Try expanding the search area or check back later."
    elif all_unsafe:
        # Warning advisory recommending not sailing
        reasons = []
        bd = best["score_breakdown"]
        if bd["safe_sea"] < 1.0:
            reasons.append(f"wave {best['wave_height_m']}m exceeds safe limit 1.5m")
        if bd["wind_ok"] < 1.0:
            reasons.append(f"wind {best['wind_kt']}kt exceeds safe limit 15kt")
        if bd["not_banned"] == 0.0:
            if not best["inside_eez"]:
                reasons.append("outside Indian EEZ")
            if best["inside_mpa"]:
                reasons.append("inside Marine Protected Area (fishing banned)")
        reason_str = "; ".join(reasons) if reasons else "all zones exceed safety thresholds"
        explanation = (
            f"Warning: All {len(ranked)} zones exceed safety thresholds ({reason_str}). "
            f"Advisory: Do NOT sail — conditions are unsafe. "
            f"Nearest option {best['place']} ({best['distance_km']}km, wave {best['wave_height_m']}m, wind {best['wind_kt']}kt) "
            f"is also unsafe. Citation: {citation}."
        )
    else:
        bd = best["score_breakdown"]
        explanation = (
            f"Recommended: {best['place']} ({best['distance_km']}km away, "
            f"wave {best['wave_height_m']}m, wind {best['wind_kt']}kt) — "
            f"ranked #1 as the safest and closest option. "
            f"Score {best['score']} (closest {bd['closest']}, sea {bd['safe_sea']}, wind {bd['wind_ok']}, allowed {bd['not_banned']}). "
            f"Safe sea (<1.5m), safe wind (<15kt), and outside restricted zones."
        )
        # If best is banned or has caution, add note
        if bd["not_banned"] == 0.0:
            explanation += " Note: best zone is near restricted area — verify geofence."
        # Add citation hint
        # Keep explanation concise but informative

    # best dict shape: include place, lat, lon, score plus extra for map
    if best is not None:
        best_out = {
            "zone_id": best["zone_id"],
            "place": best["place"],
            "sector": best["sector"],
            "lat": best["lat"],
            "lon": best["lon"],
            "distance_km": best["distance_km"],
            "distance_from_user_km": best["distance_km"],
            "wave_height_m": best["wave_height_m"],
            "wind_kt": best["wind_kt"],
            "wind_speed_kt": best["wind_kt"],
            "inside_eez": best["inside_eez"],
            "inside_mpa": best["inside_mpa"],
            "score": best["score"],
            "score_breakdown": best["score_breakdown"],
            "bearing": best.get("bearing"),
            "direction": best.get("direction"),
            "depth_range": best.get("depth_range"),
        }
    else:
        best_out = None

    top_breakdown = best["score_breakdown"] if best else {}

    return {
        "ranked_zones": ranked,
        "best": best_out,
        "explanation": explanation,
        "citation": citation,
        "all_unsafe": all_unsafe,
        "score_breakdown": top_breakdown,
    }
