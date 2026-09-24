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
    - safe_sea:   worst of wave/current components, each
                  1.0 if value < safe-max else max(0.0, 1.0 - (v-safe)/(danger-safe))
                  (canonical bands in safety_thresholds: wave 1.5/2.5m,
                  current 1.5/2.5kt). Missing current is informational and
                  does NOT penalize ranking — the wave component carries
                  safe_sea alone (safety veto still fail-opens on missing
                  wave/wind, never SAFE).
    - wind_ok:    1.0 if wind < 15kt else max(0.0, 1.0 - (wind-15)/10)
    - not_banned: 0.0 if inside_mpa or explicitly outside EEZ,
                  0.5 if geofence unknown (inside_eez=None), else 1.0

Edge Cases:
    - All spots unsafe → return warning with all_unsafe=True, advisory DO NOT SAIL
    - No spots → empty ranked_zones, best=None
    - Tie in score → lower wave wins, then closer distance

Multilingual (wayfinder #28, M-A & M-E):
    - ``combine_and_rank(..., detected_language="ml"|"ta"|"te"|"hi")``
      renders a same-language grounded advisory OFFLINE via
      ``backend/agents/lexical_mask.py`` (MarineGlossaryMasker +
      vernacular templates ported from research 02 §4 + 03 §3-§5).
    - Masking is applied pre-stream at this combiner level with cheap
      regex (no external calls, P95<2.0s); placeholders are token-safe
      (no spaces) so graph.py SSE ``_chunk_text`` never splits them.
      graph.py is intentionally NOT modified.
    - Code trumps LLM: the deterministic all_unsafe DO NOT SAIL veto is
      preserved — only its *rendering* is localized, never overridden.
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


# ---------------------------------------------------------------------------
# US-ORCA-014 canonical safety contract — SINGLE SOURCE OF TRUTH is
# backend/agents/safety_thresholds.py (wayfinder #196). All bands,
# conversions, and the veto live there; this module only re-exports.
# ---------------------------------------------------------------------------

from backend.agents.safety_thresholds import (
    CONFIDENCE_SUCCESS_FLOOR,
    CURRENT_DANGER_MIN_KT,
    CURRENT_SAFE_MAX_KT,
    DEGRADED_CONFIDENCE,
    SUCCESS_CONFIDENCE,
    WAVE_DANGER_MIN_M,
    WAVE_SAFE_MAX_M,
    WIND_DANGER_MIN_KT,
    WIND_SAFE_MAX_KT,
    apply_safety_veto,
    is_banned,
)


def _get_current(sea: dict | None) -> float | None:
    if not sea:
        return None
    for k in ("current_kt", "current_speed_kt", "current", "current_kts"):
        v = sea.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def normalize_contract(
    ranked_zones: list[dict],
    all_unsafe: bool = False,
    base_confidence: float = SUCCESS_CONFIDENCE,
) -> dict:
    """Normalize ranked zones to the canonical contract (US-ORCA-014).

    Annotates each zone with ``safety`` (apply_safety_veto) and returns
    ``{"status", "confidence", "ranked_zones"}`` where status is
    "success" only when confidence >= 0.80 (else "degraded" at 0.62).
    Any danger zone or all_unsafe forces degraded.
    """
    zones = [z for z in (ranked_zones or []) if isinstance(z, dict)]
    for z in zones:
        try:
            z["safety"] = apply_safety_veto(z)
        except Exception:
            z["safety"] = "caution"
    try:
        conf = float(base_confidence)
    except (TypeError, ValueError):
        conf = SUCCESS_CONFIDENCE
    if all_unsafe or any(z.get("safety") == "danger" for z in zones):
        return {"status": "degraded", "confidence": DEGRADED_CONFIDENCE, "ranked_zones": zones}
    if conf >= CONFIDENCE_SUCCESS_FLOOR:
        return {"status": "success", "confidence": round(conf, 4), "ranked_zones": zones}
    return {"status": "degraded", "confidence": DEGRADED_CONFIDENCE, "ranked_zones": zones}


_SUPPORTED_LANGS = ("en", "ml", "ta", "te", "hi")

# Offline canned "no zones" advisories (native script, Arabic digits n/a).
# Used when fish_results is empty but the query language is non-English,
# so Global Test queries still get same-language responses offline.
_EMPTY_ADVISORIES: dict[str, str] = {
    "ml": "സമീപത്ത് മീൻപിടിത്ത മേഖലകൾ കണ്ടെത്തിയില്ല. തിരച്ചിൽ പരിധി വർദ്ധിപ്പിച്ച് വീണ്ടും ശ്രമിക്കുക.",
    "ta": "அருகில் மீன்பிடி மண்டலங்கள் எதுவும் கிடைக்கவில்லை. தேடல் எல்லையை விரிவுபடுத்தி மீண்டும் முயலுங்கள்.",
    "te": "సమీపంలో చేపల మండలాలు కనుగొనబడలేదు. శోధన పరిధిని పెంచి మళ్లీ ప్రయత్నించండి.",
    "hi": "आस-पास कोई मत्स्य क्षेत्र नहीं मिला। खोज दायरा बढ़ाकर पुनः प्रयास करें।",
}


def _normalize_lang_code(lang: Any) -> str:
    """Normalize to en|ml|ta|te|hi (unknown/None → en)."""
    if not lang or not isinstance(lang, str):
        return "en"
    code = lang.strip().lower().split("-")[0].split("_")[0]
    return code if code in _SUPPORTED_LANGS else "en"


def _localize_empty_advisory(lang: Any) -> str | None:
    """Native-script no-zone advisory, or None when English/fallback."""
    code = _normalize_lang_code(lang)
    if code == "en":
        return None
    return _EMPTY_ADVISORIES.get(code)


def combine_and_rank(
    fish_results: list[dict],
    sea_results: list[dict],
    weather_results: list[dict],
    danger_results: list[dict],
    user_location: dict,
    detected_language: str = "en",
    port_name: str | None = None,
    species_list: list | None = None,
    forecast: dict | None = None,
    intent: dict | None = None,
) -> dict:
    """
    Rank PFZ zones by composite safety and proximity score.

    Args:
        fish_results: Closest PFZ points from FishFinder agent.
        sea_results: Wave/current data from SeaChecker agent.
        weather_results: Wind/tide data from WeatherAgent.
        danger_results: Geofence/cyclone checks from DangerAgent.
        user_location: {"lat": float, "lon": float} of the fisherman.
        detected_language: BCP-47-ish code from planner_schema
            (en|ml|ta|te|hi). Non-English renders ``explanation`` in the
            target native script OFFLINE via lexical_mask grounding
            templates; English source is preserved as ``explanation_en``.
            Unknown codes fall back to "en". Token-safe: applied here
            pre-stream so graph.py SSE needs no change.
        port_name: Optional canonical port for grounding (defaults to
            best place).
        species_list: Optional commercial species names to localize via
            the coastal fish glossary (research 03 §2).

    Returns:
        {
            "ranked_zones": [...],
            "best": {"place": str, "lat": float, "lon": float, "score": float},
            "explanation": str,          # localized when non-en (streamed)
            "explanation_en": str,       # English source (non-en only)
            "localized_reply": str,      # alias of explanation
            "detected_language": str,    # normalized code
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

    # Dedup: same physical zone must not rank twice — duplicate rows in
    # the data source (e.g. PostGIS yesterday+today rows with different
    # zone_ids, or synthetic SEC005_Chillickal_123 vs dated variants)
    # would otherwise render as twin cards. Canonical key is normalized
    # place + rounded coords; keep first occurrence (nearest input order).
    try:
        from backend.agents.zone_dedup import dedup_zones as _dedup_zones

        fish_results = _dedup_zones(fish_results)
    except Exception:
        _seen_ids: set[str] = set()
        _deduped: list[dict] = []
        for _f in fish_results:
            try:
                _place = str(_f.get("place") or "").strip().lower()
                _lat_raw = _f.get("lat")
                _lon_raw = _f.get("lon")
                _lat = round(float(str(_lat_raw)), 4)
                _lon = round(float(str(_lon_raw)), 4)
                _key = f"{_place}|{_lat:.4f}|{_lon:.4f}"
            except (TypeError, ValueError):
                _key = str(_f.get("zone_id") or _f.get("id") or "")
                if not _key:
                    _key = f"{_f.get('place')}|{_f.get('lat')}|{_f.get('lon')}"
            if _key in _seen_ids:
                continue
            _seen_ids.add(_key)
            _deduped.append(_f)
        fish_results = _deduped

    # Date for citation: DD-Mmm-YYYY, use IST-aware current date (UTC+5:30)
    try:
        # Use current date in IST if possible
        from datetime import timedelta

        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(tz=ist)
    except Exception:
        now = datetime.now()
    date_str = now.strftime("%d-%b-%Y")

    # Determine if user requested fishing zones or pure marine weather/safety
    wants_fish = True
    if isinstance(intent, dict):
        wants_fish = bool(intent.get("wants_fish", True))
    elif fish_results and all(f.get("source") == "synthetic_safety_anchor" for f in fish_results if isinstance(f, dict)):
        wants_fish = False

    # Weather / Safety only advisory (no fish intent)
    if not wants_fish:
        citation = f"INCOIS TextData {date_str}"
        lat = float(user_location.get("lat", 0.0)) if isinstance(user_location, dict) and user_location.get("lat") is not None else 0.0
        lon = float(user_location.get("lon", 0.0)) if isinstance(user_location, dict) and user_location.get("lon") is not None else 0.0

        place_str = port_name
        if not place_str:
            for source_list in (weather_results, sea_results, fish_results):
                for item in source_list:
                    if isinstance(item, dict) and item.get("place"):
                        p = str(item.get("place")).strip()
                        if p.lower() not in ("unknown", "current location", "current_location", "none"):
                            place_str = p
                            break
                if place_str:
                    break
        if not place_str:
            place_str = "your area"

        s0 = sea_results[0] if (sea_results and isinstance(sea_results[0], dict)) else {}
        w0 = weather_results[0] if (weather_results and isinstance(weather_results[0], dict)) else {}
        d0 = danger_results[0] if (danger_results and isinstance(danger_results[0], dict)) else {}

        wave = _get_wave(s0)
        wind = _get_wind(w0)
        current = _get_current(s0)
        wave_status = str(s0.get("wave_status") or s0.get("status") or "unknown").lower()
        wind_status = str(w0.get("wind_status") or w0.get("status") or "unknown").lower()

        cyclone_alert = False
        cyclone_name = None
        nearest_cyclone_km = None
        for w in weather_results:
            if isinstance(w, dict) and bool(w.get("cyclone_alert", w.get("cyclone", False))):
                cyclone_alert = True
                if w.get("cyclone_name"):
                    cyclone_name = w.get("cyclone_name")
                if w.get("nearest_cyclone_km") is not None:
                    nearest_cyclone_km = w.get("nearest_cyclone_km")

        unsafe_reasons = []
        if cyclone_alert:
            cyc_desc = f"cyclone alert active ({cyclone_name})" if cyclone_name else "cyclone alert active"
            if nearest_cyclone_km is not None:
                cyc_desc += f" within {nearest_cyclone_km:.0f}km"
            unsafe_reasons.append(cyc_desc)
        if wave is not None and wave >= WAVE_SAFE_MAX_M:
            unsafe_reasons.append(f"wave {wave}m exceeds safe limit {WAVE_SAFE_MAX_M}m")
        if wind is not None and wind >= WIND_SAFE_MAX_KT:
            unsafe_reasons.append(f"wind {wind}kt exceeds safe limit {WIND_SAFE_MAX_KT:g}kt")
        if current is not None and current >= CURRENT_SAFE_MAX_KT:
            unsafe_reasons.append(f"current {current}kt exceeds safe limit {CURRENT_SAFE_MAX_KT}kt")
        if wave_status == "danger" and wave is not None and not any("wave" in r for r in unsafe_reasons):
            unsafe_reasons.append("hazardous wave conditions")
        if wind_status == "danger" and wind is not None and not any("wind" in r for r in unsafe_reasons):
            unsafe_reasons.append("dangerous wind conditions")

        all_unsafe = bool(unsafe_reasons or cyclone_alert)
        wave_str = f"wave {wave}m" if wave is not None else "wave data unavailable"
        wind_str = f"wind {wind}kt" if wind is not None else "wind data unavailable"

        if all_unsafe:
            reason_str = ", ".join(unsafe_reasons)
            explanation = (
                f"Marine weather warning for {place_str}: {reason_str}. "
                f"Recommendation: DO NOT SAIL. Current conditions: {wave_str}, {wind_str}. "
                f"Citation: {citation}."
            )
        elif wave is None and wind is None:
            explanation = (
                f"Marine weather advisory for {place_str}: Live sea and weather data currently unavailable. "
                f"Treat conditions with caution before sailing. Citation: {citation}."
            )
        elif wave is None or wind is None or "caution" in (wave_status, wind_status):
            explanation = (
                f"Marine weather and sea conditions for {place_str}: {wave_str}, {wind_str}. "
                f"Use caution before sailing outside restricted zones. Citation: {citation}."
            )
        else:
            explanation = (
                f"Marine weather and sea conditions for {place_str}: {wave_str}, {wind_str}. "
                f"Conditions are safe for sailing outside restricted zones. Citation: {citation}."
            )

        if isinstance(forecast, dict):
            _fs = forecast.get("forecast_summary")
            _dw = forecast.get("best_window_utc") or "Tomorrow morning"
            _w6 = forecast.get("wind_kts_6h")
            _v6 = forecast.get("wave_m_6h")
            _ds = forecast.get("departure_safe")
            if _w6 is not None and _v6 is not None:
                _ss = "safe to depart" if _ds is True else ("conditions unsafe / caution" if _ds is False else "conditions uncertain")
                explanation += f" Departure advisory ({_dw}): wind {_w6} kt, waves {_v6}m ({_ss})."
            elif _fs and _fs != "Forecast unavailable":
                explanation += f" Departure advisory: {_fs}."

        best_out = {
            "id": "current_loc",
            "place": place_str,
            "lat": lat,
            "lon": lon,
            "distance_km": 0.0,
            "score": 0.0 if all_unsafe else 1.0,
            "wave_height_m": wave,
            "wind_kt": wind,
            "current_kt": current,
            "wave_status": wave_status,
            "wind_status": wind_status,
            "cyclone_alert": cyclone_alert,
            "cyclone_name": cyclone_name,
            "nearest_cyclone_km": nearest_cyclone_km,
            "all_unsafe": all_unsafe,
            "inside_eez": d0.get("inside_eez", True),
            "inside_mpa": d0.get("inside_mpa", False),
            "score_breakdown": {
                "closest": 1.0,
                "safe_sea": 0.0 if (wave is not None and wave > WAVE_SAFE_MAX_M) else 1.0,
                "wind_ok": 0.0 if (wind is not None and wind > WIND_SAFE_MAX_KT) else 1.0,
                "not_banned": 1.0,
            },
        }

        lang_code = _normalize_lang_code(detected_language)
        return {
            "ranked_zones": [],
            "best": None if all_unsafe else best_out,
            "explanation": explanation,
            "explanation_en": explanation,
            "localized_reply": explanation,
            "detected_language": lang_code,
            "citation": citation,
            "all_unsafe": all_unsafe,
            "score_breakdown": best_out["score_breakdown"],
            "forecast": forecast,
        }

    # Empty case: carry departure forecast advisory when present.
    if not fish_results:
        citation = f"INCOIS TextData {date_str}"
        _empty_en = "No fishing zones found within search radius. Try expanding the search area or check back later."
        _fc_suffix = ""
        if isinstance(forecast, dict):
            _fs = forecast.get("forecast_summary")
            _dw = forecast.get("best_window_utc") or "Tomorrow morning"
            _w6 = forecast.get("wind_kts_6h")
            _v6 = forecast.get("wave_m_6h")
            _ds = forecast.get("departure_safe")
            if _w6 is not None and _v6 is not None:
                _ss = "safe to depart" if _ds is True else ("conditions unsafe / caution" if _ds is False else "conditions uncertain")
                _fc_suffix = f" Departure advisory ({_dw}): wind {_w6} kt, waves {_v6}m - {_ss}."
            elif _fs and _fs != "Forecast unavailable":
                _fc_suffix = f" Departure advisory: {_fs}"
            elif _fs:
                _fc_suffix = " Departure advisory: Forecast unavailable."
        _empty_loc = _localize_empty_advisory(detected_language)
        if _empty_loc is not None:
            return {
                "ranked_zones": [],
                "best": None,
                "explanation": f"{_empty_loc}{_fc_suffix}".strip(),
                "explanation_en": f"{_empty_en}{_fc_suffix}".strip(),
                "localized_reply": f"{_empty_loc}{_fc_suffix}".strip(),
                "detected_language": _normalize_lang_code(detected_language),
                "citation": citation,
                "all_unsafe": False,
                "score_breakdown": {},
                "forecast": forecast,
            }
        return {
            "ranked_zones": [],
            "best": None,
            "explanation": f"{_empty_en}{_fc_suffix}".strip(),
            "localized_reply": f"{_empty_en}{_fc_suffix}".strip(),
            "detected_language": "en",
            "citation": citation,
            "all_unsafe": False,
            "score_breakdown": {},
            "forecast": forecast,
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
        # Fallback to index alignment if zone_id not matched
        if sea_entry is None and idx < len(sea_results) and isinstance(sea_results[idx], dict):
            # Only use index fallback if lengths match fish_results
            if len(sea_results) == len(fish_results):
                sea_entry = sea_results[idx]
        wave = _get_wave(sea_entry)
        current = _get_current(sea_entry)
        if wave is None:
            wave_val = None
            safe_sea = 0.4  # uncertainty penalty in score, but not a threshold violation
            wave_exceeded = False
        else:
            wave_val = float(wave)
            if wave_val < WAVE_SAFE_MAX_M:
                _wave_comp = 1.0
                wave_exceeded = False
            else:
                _wave_comp = max(
                    0.0,
                    1.0 - (wave_val - WAVE_SAFE_MAX_M) / (WAVE_DANGER_MIN_M - WAVE_SAFE_MAX_M),
                )
                wave_exceeded = True
            safe_sea = _wave_comp
        # Current is scored explicitly: folded into safe_sea as the worst
        # of wave/current (documented in the module docstring). Missing
        # current is informational — wave alone carries safe_sea.
        if current is None:
            current_val = None
            current_exceeded = False
        else:
            current_val = float(current)
            if current_val < CURRENT_SAFE_MAX_KT:
                _cur_comp = 1.0
                current_exceeded = False
            else:
                _cur_comp = max(
                    0.0,
                    1.0 - (current_val - CURRENT_SAFE_MAX_KT)
                    / (CURRENT_DANGER_MIN_KT - CURRENT_SAFE_MAX_KT),
                )
                current_exceeded = True
            if wave_val is not None:
                safe_sea = min(safe_sea, _cur_comp)

        # Weather: wind
        weather_entry = weather_lookup.get(zone_id)
        if weather_entry is None and idx < len(weather_results) and isinstance(weather_results[idx], dict):
            if len(weather_results) == len(fish_results):
                weather_entry = weather_results[idx]
        wind = _get_wind(weather_entry)
        if wind is None:
            wind_val = None
            wind_ok = 0.4  # uncertainty penalty in score, but not a threshold violation
            wind_exceeded = False
        else:
            wind_val = float(wind)
            if wind_val < WIND_SAFE_MAX_KT:
                wind_ok = 1.0
                wind_exceeded = False
            else:
                wind_ok = max(
                    0.0,
                    1.0 - (wind_val - WIND_SAFE_MAX_KT)
                    / (WIND_DANGER_MIN_KT - WIND_SAFE_MAX_KT),
                )
                wind_exceeded = True

        # Tide (T2 #117): passthrough from weather_agent; missing -> None/unknown.
        tide_range_val: float | None = None
        tidal_state_val: str = "unknown"
        next_high_val: str | None = None
        next_low_val: str | None = None
        if isinstance(weather_entry, dict):
            try:
                _tr = weather_entry.get("tide_range_m")
                tide_range_val = round(float(_tr), 2) if _tr is not None else None
            except (TypeError, ValueError):
                tide_range_val = None
            try:
                _ts = str(weather_entry.get("tidal_state") or "unknown")
                tidal_state_val = _ts if _ts in ("rising", "falling", "slack", "unknown") else "unknown"
            except Exception:
                tidal_state_val = "unknown"
            try:
                _nh = weather_entry.get("next_high_tide_utc")
                next_high_val = str(_nh) if _nh is not None else None
                _nl = weather_entry.get("next_low_tide_utc")
                next_low_val = str(_nl) if _nl is not None else None
            except Exception:
                next_high_val, next_low_val = None, None

        # Danger: inside_eez, inside_mpa
        danger_entry = danger_lookup.get(zone_id)
        if danger_entry is None and idx < len(danger_results) and isinstance(danger_results[idx], dict):
            if len(danger_results) == len(fish_results):
                danger_entry = danger_results[idx]
        if danger_entry is None:
            # Unknown (skipped/failed check) is NOT a ban — fail-open to
            # caution. A missing geofence must never read as "outside EEZ".
            inside_eez = None
            inside_mpa = False
        else:
            # Defaults: inside_eez None (unknown, never a ban), inside_mpa
            # False if missing. A missing geofence must never read as
            # "outside EEZ" (fail-open to caution, #196).
            inside_eez_raw = danger_entry.get("inside_eez")
            inside_mpa_raw = danger_entry.get("inside_mpa")
            # Also handle alternative keys
            if inside_eez_raw is None:
                inside_eez_raw = danger_entry.get("insideEEZ")
            if inside_mpa_raw is None:
                inside_mpa_raw = danger_entry.get("insideMPA")
            inside_eez = bool(inside_eez_raw) if inside_eez_raw is not None else None
            inside_mpa = bool(inside_mpa_raw) if inside_mpa_raw is not None else False

        # Explicit ban (inside MPA / explicitly outside EEZ) scores 0.
        # Unknown geofence (inside_eez=None) scores 0.5 (uncertainty, never
        # a ban) so skipped checks degrade to caution instead of a false
        # "outside Indian EEZ" DO NOT SAIL. Canonical is_banned() (#196).
        if is_banned(inside_mpa, inside_eez):
            not_banned = 0.0
        elif inside_eez is None:
            not_banned = 0.5
        else:
            not_banned = 1.0

        score = closest * 0.4 + safe_sea * 0.3 + wind_ok * 0.2 + not_banned * 0.1
        score = round(float(score), 4)

        breakdown = {
            "closest": round(float(closest), 4),
            "safe_sea": round(float(safe_sea), 4),
            "wind_ok": round(float(wind_ok), 4),
            "not_banned": round(float(not_banned), 4),
            "wave_exceeded": wave_exceeded,
            "wind_exceeded": wind_exceeded,
            "current_exceeded": current_exceeded,
            "wave_available": wave_val is not None,
            "wind_available": wind_val is not None,
            "current_available": current_val is not None,
            "score": score,
        }

        # Lightning risk (T8 #124)
        l_risk = None
        l_desc = None
        if isinstance(danger_entry, dict):
            l_risk = danger_entry.get("lightning_risk")
            l_desc = danger_entry.get("lightning_description") or danger_entry.get("description")
            if not l_risk:
                for w in danger_entry.get("warnings", []):
                    if "lightning" in str(w).lower():
                        l_risk = "high"
                        l_desc = str(w)
                        break

        # Build ranked entry preserving original fish fields plus computed
        entry = {
            "zone_id": zone_id,
            "place": place,
            "sector": sector,
            "lat": lat_f,
            "lon": lon_f,
            "distance_km": round(float(dist_val), 2),
            "distance_from_user_km": round(float(dist_val), 2),
            "wave_height_m": round(float(wave_val), 2) if wave_val is not None else None,
            "wind_kt": round(float(wind_val), 2) if wind_val is not None else None,
            "wind_speed_kt": round(float(wind_val), 2) if wind_val is not None else None,
            "current_kt": round(float(current_val), 2) if current_val is not None else None,
            "current_speed_kt": round(float(current_val), 2) if current_val is not None else None,
            "tide_range_m": tide_range_val,
            "tidal_state": tidal_state_val,
            "next_high_tide_utc": next_high_val,
            "next_low_tide_utc": next_low_val,
            "wave_available": wave_val is not None,
            "wind_available": wind_val is not None,
            "current_available": current_val is not None,
            "inside_eez": inside_eez,
            "inside_mpa": inside_mpa,
            "lightning_risk": l_risk,
            "lightning_description": l_desc,
            "score": score,
            "score_breakdown": breakdown,
            # preserve original fish props for map rendering
            "bearing": fish.get("bearing"),
            "direction": fish.get("direction") or fish.get("dir"),
            "depth_range": fish.get("depth_range") or fish.get("depth") or "",
            "sst_c": fish.get("sst_c"),
            "chlorophyll_mg_m3": fish.get("chlorophyll_mg_m3"),
        }
        ranked.append(entry)

    # US-ORCA-014: canonical safety annotation (additive — scoring untouched).
    for z in ranked:
        try:
            z["safety"] = apply_safety_veto(z)
        except Exception:
            z["safety"] = "caution"

    # Tie-breaker: sort by descending score, then lower wave, then closer distance
    ranked.sort(key=lambda z: (-z["score"], z["wave_height_m"] if z["wave_height_m"] is not None else 999.0, z["distance_km"]))

    # All-unsafe detection: every zone exceeds a VETO threshold.
    # Canonical bands (safety_thresholds): wave >= 2.0m, wind >= 22kt,
    # or banned (not_banned == 0.0).
    # Option 1: current_exceeded ALONE never sets all_unsafe — a shared
    # strong-current grid cell must not force DO NOT SAIL on calm
    # wave/wind/geofence (Kochi/Munambam bug). Current still scores
    # (safe_sea) and annotates per-zone safety as caution.
    # Missing measurements (wave/wind unavailable) do not count as violations.
    all_unsafe = False
    if ranked:
        unsafe_count = 0
        for z in ranked:
            bd = z["score_breakdown"]
            if bd.get("wave_exceeded") or bd.get("wind_exceeded") or bd.get("not_banned") == 0.0:
                unsafe_count += 1
        if unsafe_count == len(ranked):
            all_unsafe = True

    best = ranked[0] if ranked else None

    # Veto (#197 choice a): banned best forces DO NOT SAIL even when not
    # every zone breaches. Canonical is_banned (#196) — do not redefine.
    if best is not None and not all_unsafe:
        try:
            if is_banned(best.get("inside_mpa"), best.get("inside_eez")):
                all_unsafe = True
        except Exception:
            pass

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
        explanation = (
            "No fishing zones found within search radius. "
            "If you're inland, share a coastal GPS (latitude, longitude) or mention a nearby "
            "coastal place like Kochi, Munambam, Beypore, Kollam, Vizag, Veraval, or Chennai. "
            "Otherwise try expanding the search area or check back later."
        )
    elif all_unsafe:
        # Warning advisory recommending not to sail
        reasons = []
        bd = best["score_breakdown"]
        if bd.get("wave_exceeded") and best.get("wave_height_m") is not None:
            reasons.append(f"wave {best['wave_height_m']}m exceeds safe limit {WAVE_SAFE_MAX_M}m")
        if bd.get("wind_exceeded") and best.get("wind_kt") is not None:
            reasons.append(f"wind {best['wind_kt']}kt exceeds safe limit {WIND_SAFE_MAX_KT:g}kt")
        if bd.get("current_exceeded") and best.get("current_kt") is not None:
            reasons.append(f"current {best['current_kt']}kt exceeds safe limit {CURRENT_SAFE_MAX_KT}kt")
        if bd.get("not_banned") == 0.0:
            if best.get("inside_eez") is False:
                reasons.append("outside Indian EEZ")
            if best.get("inside_mpa"):
                reasons.append("inside Marine Protected Area (fishing banned)")
        reason_str = ", ".join(reasons) if reasons else "all zones exceed safety thresholds"
        wave_str = f"wave {best['wave_height_m']}m" if best.get("wave_height_m") is not None else "wave unavailable"
        wind_str = f"wind {best['wind_kt']}kt" if best.get("wind_kt") is not None else "wind unavailable"
        explanation = (
            f"Warning: All {len(ranked)} zones exceed safety thresholds ({reason_str}). "
            f"Advisory: DO NOT SAIL as conditions are unsafe. "
            f"Nearest option {best['place']} ({best['distance_km']}km, {wave_str}, {wind_str}) "
            f"is unsafe. Citation: {citation}."
        )
    else:
        bd = best["score_breakdown"]
        wave_str = f"wave {best['wave_height_m']}m" if best.get("wave_height_m") is not None else "wave data unavailable"
        wind_str = f"wind {best['wind_kt']}kt" if best.get("wind_kt") is not None else "wind data unavailable"
        explanation = (
            f"Recommended: {best['place']} ({best['distance_km']}km away, "
            f"{wave_str}, {wind_str}) "
            f"ranked #1 as safest and closest option. "
            f"Score {best['score']} (closest {bd['closest']}, sea {bd['safe_sea']}, wind {bd['wind_ok']}, allowed {bd['not_banned']}). "
            f"Safe sea (<{WAVE_SAFE_MAX_M}m) and safe wind (<{WIND_SAFE_MAX_KT:g}kt) outside restricted zones."
        )
        # If best is banned or caution, add note
        if bd["not_banned"] == 0.0:
            explanation += " Note: best zone near restricted area, verify geofence."
        elif bd["not_banned"] == 0.5:
            explanation += " Note: geofence unverified (check skipped) — confirm legality before sailing."
        if not bd.get("wave_available") or not bd.get("wind_available"):
            explanation += " Sea/wind data unavailable — treat conditions with caution."

    forecast_text = ""
    if forecast and isinstance(forecast, dict):
        f_summary = forecast.get("forecast_summary")
        dep_safe = forecast.get("departure_safe")
        window = forecast.get("best_window_utc") or "Tomorrow morning"
        wind_6h = forecast.get("wind_kts_6h")
        wave_6h = forecast.get("wave_m_6h")
        if wind_6h is not None and wave_6h is not None:
            f_safe_str = "safe to depart" if dep_safe is True else ("conditions unsafe / caution" if dep_safe is False else "conditions uncertain")
            forecast_text = f"Departure advisory ({window}): wind {wind_6h} kt, waves {wave_6h}m — {f_safe_str}."
        elif f_summary and f_summary != "Forecast unavailable":
            forecast_text = f"Departure advisory: {f_summary}"
        elif f_summary == "Forecast unavailable":
            forecast_text = "Departure advisory: Forecast unavailable."

    if forecast_text:
        explanation = f"{explanation} {forecast_text}".strip()

    # Tide (T2 #117): advisory suffix from best zone's weather passthrough.
    # Only when data exists (range known or state known); never overrides veto.
    tide_text = ""
    if best is not None:
        try:
            _btr = best.get("tide_range_m")
            _bts = str(best.get("tidal_state") or "unknown")
            if _bts not in ("rising", "falling", "slack", "unknown"):
                _bts = "unknown"
            if _btr is not None:
                try:
                    _rv = round(float(_btr), 2)
                    tide_text = f"Tide: {_bts}, range {_rv}m." if _bts != "unknown" else f"Tidal range {_rv}m."
                except (TypeError, ValueError):
                    tide_text = f"Tide: {_bts}." if _bts != "unknown" else ""
            elif _bts != "unknown":
                tide_text = f"Tide: {_bts}."
        except Exception:
            tide_text = ""
    if tide_text:
        explanation = f"{explanation} {tide_text}".strip()

    # Satellite SST / chlorophyll advisory (T3 #118)
    # When SST/chlorophyll data present, include advisory:
    # "SST: 28.5C, Chlorophyll: 0.6 mg/m3 productive waters."
    satellite_text = ""
    if best is not None:
        try:
            _sst = best.get("sst_c")
            _chlo = best.get("chlorophyll_mg_m3")
            _sat_parts = []
            if _sst is not None:
                try:
                    _sat_parts.append(f"SST: {round(float(_sst), 1)}C")
                except (TypeError, ValueError):
                    pass
            if _chlo is not None:
                try:
                    _sat_parts.append(f"Chlorophyll: {round(float(_chlo), 2)} mg/m3")
                except (TypeError, ValueError):
                    pass
            if _sat_parts:
                satellite_text = f"{', '.join(_sat_parts)} productive waters."
        except Exception:
            satellite_text = ""
        if satellite_text:
            explanation = f"{explanation} {satellite_text}".strip()

        # Lightning advisory (T8 #124)
        # When lightning risk is high or notable, mention in advisory
        lightning_text = ""
        if best is not None:
            try:
                _l_risk = str(best.get("lightning_risk") or "").lower()
                _l_desc = best.get("lightning_description") or ""
                if _l_risk == "high":
                    lightning_text = f"Lightning advisory: High convective storm risk ({_l_desc or 'avoid open sea'})."
                elif _l_risk == "moderate":
                    lightning_text = "Lightning advisory: Moderate convective activity; stay alert for thunderstorms."
                elif _l_risk == "low":
                    lightning_text = "Lightning risk: Low."
            except Exception:
                lightning_text = ""
        if lightning_text:
            explanation = f"{explanation} {lightning_text}".strip()

        # best dict shape: must include place, lat, lon, score plus extra for map
        if best is not None:
            best_out = {
                "zone_id": best["zone_id"],
                "place": best["place"],
                "sector": best["sector"],
                "lat": best["lat"],
                "lon": best["lon"],
                "distance_km": best["distance_km"],
                "distance_from_user_km": best["distance_km"],
                "wave_height_m": best.get("wave_height_m"),
                "wind_kt": best.get("wind_kt"),
                "wind_speed_kt": best.get("wind_kt"),
                "current_kt": best.get("current_kt"),
                "current_speed_kt": best.get("current_kt"),
                "tide_range_m": best.get("tide_range_m"),
                "tidal_state": best.get("tidal_state", "unknown"),
                "next_high_tide_utc": best.get("next_high_tide_utc"),
                "next_low_tide_utc": best.get("next_low_tide_utc"),
                "wave_available": best.get("wave_available", True),
                "wind_available": best.get("wind_available", True),
                "current_available": best.get("current_available", False),
                "inside_eez": best["inside_eez"],
                "inside_mpa": best["inside_mpa"],
                "lightning_risk": best.get("lightning_risk"),
                "lightning_description": best.get("lightning_description"),
                "score": best["score"],
                "score_breakdown": best["score_breakdown"],
                "safety": best.get("safety", "caution"),
                "bearing": best.get("bearing"),
                "direction": best.get("direction"),
                "depth_range": best.get("depth_range"),
                "sst_c": best.get("sst_c"),
                "chlorophyll_mg_m3": best.get("chlorophyll_mg_m3"),
            }
    else:
        best_out = None

    top_breakdown = best["score_breakdown"] if best else {}

    lang_code = _normalize_lang_code(detected_language)
    if lang_code != "en" and best_out is not None:
        # Same-language grounded rendering (offline, token-safe, pre-stream).
        # Code trumps LLM: all_unsafe veto is computed above; the
        # renderer only localizes the lexical_mask (never overrides).
        try:
            from backend.agents import lexical_mask as _lm

            _metrics = {
                "place": port_name or best_out.get("place"),
                "lat": best_out.get("lat"),
                "lon": best_out.get("lon"),
                "distance_km": best_out.get("distance_km"),
                "bearing_deg": best_out.get("bearing"),
                "direction": best_out.get("direction"),
                "wave_height_m": best_out.get("wave_height_m"),
                "wind_kts": best_out.get("wind_kt"),
                "current_kt": best_out.get("current_kt"),
                "cyclone_alert": best_out.get("cyclone_alert", False),
                "all_unsafe": all_unsafe,
                "citation": citation,
                "inside_eez": best_out.get("inside_eez"),
                "inside_mpa": best_out.get("inside_mpa"),
                "species_list": species_list or [],
            }
            _localized = _lm.render_grounded_advisory(_metrics, lang_code)
            if forecast_text:
                _localized = f"{_localized} {forecast_text}".strip()
            if tide_text:
                _localized = f"{_localized} {tide_text}".strip()
            if satellite_text:
                _localized = f"{_localized} {satellite_text}".strip()
            return {
                "ranked_zones": [] if all_unsafe else ranked,
                "best": None if all_unsafe else best_out,
                "explanation": _localized,
                "explanation_en": explanation,
                "localized_reply": _localized,
                "detected_language": lang_code,
                "citation": citation,
                "all_unsafe": all_unsafe,
                "score_breakdown": top_breakdown,
                "forecast": forecast,
            }
        except Exception:
            pass  # fall through to English explanation (graceful degrade)

    # Veto (#197 choice a): DO NOT SAIL never ships fish zones — empty
    # ranked/best but keep explanation (reason) + citation + all_unsafe.
    return {
        "ranked_zones": [] if all_unsafe else ranked,
        "best": None if all_unsafe else best_out,
        "explanation": explanation,
        "localized_reply": explanation,
        "detected_language": lang_code,
        "citation": citation,
        "all_unsafe": all_unsafe,
        "score_breakdown": top_breakdown,
        "forecast": forecast,
    }


def build_localized_advisory(
    best: dict | None,
    detected_language: str = "en",
    citation: str = "INCOIS TextData",
    all_unsafe: bool = False,
    port_name: str | None = None,
    species_list: list | None = None,
) -> dict:
    """Render a same-language grounded advisory (offline canned).

    Thin combiner-level hook over ``lexical_mask.render_grounded_advisory``
    so M-E chat / tests get an envelope without touching graph.py.

    Args:
        best: combiner ``best`` zone dict (or None for empty search).
        detected_language: en|ml|ta|te|hi (unknown → en).
        citation: INCOIS citation string preserved verbatim in the reply.
        all_unsafe: deterministic veto flag — forces DANGER closing.
        port_name: override display place (defaults to best place).
        species_list: commercial species names for glossary localization.

    Returns:
        Envelope ``{"status","summary","next_actions","artifacts",
        "reply","detected_language","safety_tier","elapsed_ms"}``.
        Never raises: falls back to English with status "warning".
    """
    import time as _time

    t0 = _time.perf_counter()
    lang_code = _normalize_lang_code(detected_language)
    try:
        from backend.agents import lexical_mask as _lm

        if best is None:
            empty = _localize_empty_advisory(lang_code)
            reply = empty if empty is not None else (
                "No fishing zones found within search radius. "
                "Try expanding the search area or check back later."
            )
            tier = "UNKNOWN"
        else:
            from backend.agents.safety_thresholds import is_banned as _is_banned

            metrics = {
                "place": port_name or best.get("place"),
                "lat": best.get("lat"),
                "lon": best.get("lon"),
                "distance_km": best.get("distance_km", best.get("distance_from_user_km")),
                "bearing_deg": best.get("bearing_deg", best.get("bearing")),
                "direction": best.get("direction", best.get("dir")),
                "wave_height_m": best.get("wave_height_m", best.get("wave_m")),
                "wind_kts": best.get("wind_kts", best.get("wind_kt", best.get("wind_speed_kt"))),
                "current_kt": best.get("current_kt", best.get("current_speed_kt")),
                "cyclone_alert": best.get("cyclone_alert", best.get("cyclone", False)),
                "all_unsafe": all_unsafe,
                "citation": citation,
                "inside_eez": best.get("inside_eez"),
                "inside_mpa": best.get("inside_mpa"),
                "species_list": species_list or best.get("species_list") or [],
            }
            reply = _lm.render_grounded_advisory(metrics, lang_code)
            tier = _lm.derive_safety_tier(
                metrics.get("wave_height_m"),
                metrics.get("wind_kts"),
                all_unsafe,
                _is_banned(metrics.get("inside_mpa"), metrics.get("inside_eez")),
                metrics.get("current_kt"),
                bool(metrics.get("cyclone_alert", False)),
            )
        elapsed_ms = int((_time.perf_counter() - t0) * 1000)
        return {
            "status": "success",
            "summary": f"grounded {lang_code} advisory ({tier}) in {elapsed_ms}ms",
            "next_actions": ["stream reply tokens via graph.py (unchanged)"],
            "artifacts": [],
            "reply": reply,
            "detected_language": lang_code,
            "safety_tier": tier,
            "elapsed_ms": elapsed_ms,
        }
    except Exception as exc:
        elapsed_ms = int((_time.perf_counter() - t0) * 1000)
        fallback = (
            "No fishing zones found within search radius."
            if best is None
            else f"Recommended: {(best or {}).get('place', 'Unknown')} — see map for details."
        )
        return {
            "status": "warning",
            "summary": f"localization fallback to en ({exc})",
            "next_actions": ["serve English advisory + warn"],
            "artifacts": [],
            "reply": fallback,
            "detected_language": "en",
            "safety_tier": "UNKNOWN",
            "elapsed_ms": elapsed_ms,
        }


# Backwards-compatible alias (map #22 wording: multilingual synthesis).
synthesize_multilingual_advisory = build_localized_advisory
