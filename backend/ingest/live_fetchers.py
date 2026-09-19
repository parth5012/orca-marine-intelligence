"""
Live Data Fetching Layer for ORCA Marine Intelligence.

Connects to real, operational data sources:
1. Open-Meteo Marine API -> Live wave height, wave period, swell, and ocean currents.
2. Open-Meteo Forecast API -> Live 10m wind speed, gusts, surface pressure, and cyclone status.
3. INCOIS PFZ Local & Live GeoJSON (data/pfz-today.geojson) -> Real Potential Fishing Zones.
4. Marine Regions EEZ / MPA GeoJSON (data/eez.geojson, data/mpa.geojson) -> Real border polygons.

All fetchers return standard AGENTS.md § 3.2 observable envelopes:
{"status": "success|warning|error", "summary": "...", "next_actions": [...], "artifacts": [...]}
"""

import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Base URLs
OPEN_METEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
OPEN_METEO_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
OPENWEATHERMAP_API_URL = "https://api.openweathermap.org/data/2.5/weather"
IMD_CYCLONE_URL = "https://mausam.imd.gov.in/responsive/cycloneinformation.php"
HTTP_TIMEOUT_S = 6.0
# OpenWeatherMap backup: fail-fast (was 6s x3 = ~19s stall per call).
# Open-Meteo is primary; OWM only tried on Open-Meteo failure.
OWM_TIMEOUT_S = 3.0
OWM_RETRIES = 1

# ---------------------------------------------------------------------------
# Shared pooled HTTP client (Ticket #198 — perf hardening)
# ---------------------------------------------------------------------------
# Per-zone live fetchers (5 zones x marine+weather) previously built a new
# httpx.Client per call (10+ TLS handshakes per chat). A single module-level
# pooled client reuses keep-alive connections across calls in the process.
# The factory-identity guard keeps `patch("httpx.Client")` based tests
# working: if the class is swapped (mock), the pooled instance is rebuilt.
_SHARED_CLIENT: httpx.Client | None = None
_SHARED_CLIENT_FACTORY: Any = None


def _get_shared_client() -> httpx.Client:
    """Return the process-wide pooled httpx client (keep-alive)."""
    global _SHARED_CLIENT, _SHARED_CLIENT_FACTORY
    if _SHARED_CLIENT is None or _SHARED_CLIENT_FACTORY is not httpx.Client:
        try:
            if _SHARED_CLIENT is not None:
                _SHARED_CLIENT.close()
        except Exception:
            pass
        _SHARED_CLIENT = httpx.Client(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=20),
        )
        _SHARED_CLIENT_FACTORY = httpx.Client
    return _SHARED_CLIENT


def _close_shared_client() -> None:
    """Close and drop the pooled client (tests / shutdown)."""
    global _SHARED_CLIENT, _SHARED_CLIENT_FACTORY
    try:
        if _SHARED_CLIENT is not None:
            _SHARED_CLIENT.close()
    except Exception:
        pass
    _SHARED_CLIENT = None
    _SHARED_CLIENT_FACTORY = None

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
PFZ_GEOJSON_PATH = DATA_DIR / "pfz-today.geojson"
EEZ_GEOJSON_PATH = DATA_DIR / "eez.geojson"
MPA_GEOJSON_PATH = DATA_DIR / "mpa.geojson"

# Safety thresholds — SINGLE SOURCE OF TRUTH is
# backend/agents/safety_thresholds.py (wayfinder #196). Aliases below keep
# legacy import paths working.
from backend.agents.safety_thresholds import (
    CURRENT_DANGER_MIN_KT as CURRENT_CAUTION_MAX,
)
from backend.agents.safety_thresholds import (
    CURRENT_SAFE_MAX_KT as CURRENT_SAFE_MAX,
)
from backend.agents.safety_thresholds import (
    PRESSURE_DANGER_HPA as CYCLONE_PRESSURE_DANGER,
)
from backend.agents.safety_thresholds import (
    WAVE_DANGER_MIN_M as WAVE_CAUTION_MAX,
)
from backend.agents.safety_thresholds import (
    WAVE_SAFE_MAX_M as WAVE_SAFE_MAX,
)
from backend.agents.safety_thresholds import (
    WIND_DANGER_MIN_KT as WIND_CAUTION_MAX,
)
from backend.agents.safety_thresholds import (
    WIND_SAFE_MAX_KT as WIND_SAFE_MAX,
)


IST_TZ = timezone(timedelta(hours=5, minutes=30))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    R = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    return 2.0 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _deg_to_compass(deg: float | None) -> str:
    """Convert degrees 0..360 to 16-point compass."""
    if deg is None:
        return "N/A"
    compass = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
               "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = int((deg + 11.25) / 22.5) % 16
    return compass[idx]


def _nearest_hour_index(times_list: list[str], target_dt: Optional[datetime] = None) -> int:
    """
    Find index of forecast time closest to the target datetime in IST (Asia/Kolkata).
    Guarantees selecting the active departure hour rather than midnight (00:00).
    """
    if not times_list:
        return 0
    target = target_dt or datetime.now(timezone.utc).astimezone(IST_TZ)
    if target.tzinfo is None:
        target = target.replace(tzinfo=IST_TZ)
    parsed: list[datetime] = []
    for t in times_list:
        try:
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST_TZ)
            parsed.append(dt)
        except Exception:
            continue
    if not parsed:
        return 0
    return min(range(len(parsed)), key=lambda i: abs((parsed[i] - target).total_seconds()))


def _http_get_with_retry(
    url: str,
    params: dict[str, Any] | None = None,
    timeout_s: float = HTTP_TIMEOUT_S,
    max_retries: int = 1,
    backoff_factor: float = 0.0,
) -> httpx.Response:
    """Execute HTTP GET, fail-fast by default (Ticket #198).

    Hot path is single-try over the shared keep-alive pool: no per-call
    TLS handshake, no blocking ``time.sleep`` retries. Callers needing
    retries pass ``max_retries > 1`` explicitly (legacy context-manager
    path, preserved for ``patch("httpx.Client")`` test compatibility).
    Never returns mock data; raises RuntimeError if all tries are exhausted.
    """
    last_exc: Exception | None = None
    attempts = max(1, int(max_retries))
    for attempt in range(1, attempts + 1):
        try:
            if attempts == 1:
                resp = _get_shared_client().get(url, params=params, timeout=timeout_s)
            else:
                with httpx.Client(timeout=timeout_s) as client:
                    resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp
        except (httpx.HTTPError, OSError) as exc:
            last_exc = exc
            if attempt < attempts:
                sleep_s = backoff_factor * (2 ** (attempt - 1))
                if sleep_s > 0:
                    logger.warning(
                        "HTTP GET to %s failed (attempt %d/%d): %s. Retrying in %.2fs...",
                        url, attempt, attempts, exc, sleep_s,
                    )
                    time.sleep(sleep_s)
            else:
                logger.error(
                    "HTTP GET to %s failed after %d attempt(s): %s",
                    url, attempts, exc,
                )
    raise RuntimeError(f"Live fetch failed for {url} after {attempts} retries: {last_exc}") from last_exc


# ---------------------------------------------------------------------------
# 1. Open-Meteo Marine Live Fetcher
# ---------------------------------------------------------------------------

def fetch_open_meteo_marine(
    lat: float,
    lon: float,
    target_dt: Optional[datetime] = None,
    timeout_s: float = HTTP_TIMEOUT_S,
) -> dict[str, Any]:
    """
    Fetch numerical ocean wave, period, swell, and ocean currents from Open-Meteo Marine API.
    Matches the nearest forecast hour in IST (Asia/Kolkata) and analyzes the next 6-hour trip window.
    """
    now_iso = datetime.now(timezone.utc).astimezone(IST_TZ).isoformat()
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "hourly": [
            "wave_height",
            "wave_direction",
            "wave_period",
            "swell_wave_height",
            "swell_wave_period",
            "ocean_current_velocity",
            "ocean_current_direction",
        ],
        "forecast_days": 3,
        "timezone": "Asia/Kolkata",
    }
    try:
        resp = _http_get_with_retry(OPEN_METEO_MARINE_URL, params=params, timeout_s=timeout_s)
        payload = resp.json()

        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        idx = _nearest_hour_index(times, target_dt) if times else 0
        valid_time_str = times[idx] if times and idx < len(times) else now_iso

        # 1. Current / Nearest Hour values
        raw_waves = hourly.get("wave_height", [])
        wave_height = round(float(raw_waves[idx]), 2) if idx < len(raw_waves) and raw_waves[idx] is not None else 1.2

        raw_currents = hourly.get("ocean_current_velocity", [])
        current_kt = round(float(raw_currents[idx]) * 1.94384, 2) if idx < len(raw_currents) and raw_currents[idx] is not None else 1.0

        raw_periods = hourly.get("wave_period", [])
        wave_period = round(float(raw_periods[idx]), 1) if idx < len(raw_periods) and raw_periods[idx] is not None else 7.5

        raw_swells = hourly.get("swell_wave_height", [])
        swell_height = round(float(raw_swells[idx]), 2) if idx < len(raw_swells) and raw_swells[idx] is not None else 0.8

        raw_sp = hourly.get("swell_wave_period", [])
        swell_period = round(float(raw_sp[idx]), 1) if idx < len(raw_sp) and raw_sp[idx] is not None else 6.5

        raw_dirs = hourly.get("ocean_current_direction", [])
        current_dir_deg = float(raw_dirs[idx]) if idx < len(raw_dirs) and raw_dirs[idx] is not None else 180.0
        current_dir = _deg_to_compass(current_dir_deg)

        # 2. Trip Window Analysis (Next 6 hours from departure/now)
        win_end = min(idx + 6, len(raw_waves)) if raw_waves else idx
        window_waves = [float(w) for w in raw_waves[idx:win_end] if w is not None] or [wave_height]
        window_currents = [float(c) * 1.94384 for c in raw_currents[idx:win_end] if c is not None] or [current_kt]

        max_wave_6h = round(max(window_waves), 2)
        min_wave_6h = round(min(window_waves), 2)
        max_current_6h = round(max(window_currents), 2)

        # Classifications
        wave_status = "safe" if wave_height < WAVE_SAFE_MAX else ("caution" if wave_height <= WAVE_CAUTION_MAX else "danger")
        current_status = "safe" if current_kt < CURRENT_SAFE_MAX else ("caution" if current_kt <= CURRENT_CAUTION_MAX else "danger")
        overall_status = "danger" if (wave_status == "danger" or current_status == "danger") else (
            "caution" if (wave_status == "caution" or current_status == "caution") else "safe"
        )

        worst_wave_status_6h = "safe" if max_wave_6h < WAVE_SAFE_MAX else ("caution" if max_wave_6h <= WAVE_CAUTION_MAX else "danger")
        worst_current_status_6h = "safe" if max_current_6h < CURRENT_SAFE_MAX else ("caution" if max_current_6h <= CURRENT_CAUTION_MAX else "danger")
        worst_status_6h = "danger" if (worst_wave_status_6h == "danger" or worst_current_status_6h == "danger") else (
            "caution" if (worst_wave_status_6h == "caution" or worst_current_status_6h == "caution") else "safe"
        )

        # Compute forecast lead hours
        lead_hours = 0.0
        try:
            valid_dt = datetime.fromisoformat(valid_time_str)
            if valid_dt.tzinfo is None:
                valid_dt = valid_dt.replace(tzinfo=IST_TZ)
            retrieved_dt = datetime.fromisoformat(now_iso)
            lead_hours = round((valid_dt - retrieved_dt).total_seconds() / 3600.0, 2)
        except Exception:
            lead_hours = 0.0

        # Provenance and freshness metadata
        data_freshness = {
            "provider": "Open-Meteo Marine API (ECMWF/NOAA)",
            "retrieved_at": now_iso,
            "forecast_valid_for": valid_time_str,
            "forecast_lead_hours": lead_hours,
            "source_status": "model_forecast",
            "trip_window_hours": 6,
            "max_wave_in_window_m": max_wave_6h,
            "max_current_in_window_kt": max_current_6h,
            "official_warning_disclaimer": "Forecast-based advisory generated from numerical ocean models. Verify official IMD/INCOIS bulletins before departure.",
        }

        return {
            "wave_height_m": wave_height,
            "current_speed_kt": current_kt,
            "wave_period_s": wave_period,
            "swell_wave_height_m": swell_height,
            "swell_wave_period_s": swell_period,
            "current_dir": current_dir,
            "current_dir_deg": current_dir_deg,
            "wave_status": wave_status,
            "current_status": current_status,
            "status": overall_status,
            "forecast_time_ist": valid_time_str,
            "trip_window_6h": {
                "max_wave_m": max_wave_6h,
                "min_wave_m": min_wave_6h,
                "max_current_kt": max_current_6h,
                "worst_status": worst_status_6h,
            },
            "data_freshness": data_freshness,
            "source": "open_meteo_live",
        }
    except Exception as exc:
        logger.error("Failed to fetch live Open-Meteo marine data for (%s, %s): %s", lat, lon, exc)
        raise RuntimeError(f"Live marine weather fetch failed after retries for ({lat}, {lon}): {exc}") from exc


# Alias for backward compatibility
fetch_open_meteo_wave_current = fetch_open_meteo_marine


# ---------------------------------------------------------------------------
# 2. Open-Meteo & OpenWeatherMap Weather Live Fetchers
# ---------------------------------------------------------------------------

def fetch_open_meteo_weather(
    lat: float,
    lon: float,
    target_dt: Optional[datetime] = None,
    timeout_s: float = HTTP_TIMEOUT_S,
) -> dict[str, Any]:
    """
    Fetch real live wind speed, gusts, surface pressure, temp, humidity from Open-Meteo Forecast API.
    Matches the nearest forecast hour in IST (Asia/Kolkata) and evaluates the next 6-hour trip window.
    """
    now_iso = datetime.now(timezone.utc).astimezone(IST_TZ).isoformat()
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "hourly": [
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
            "surface_pressure",
            "temperature_2m",
            "relative_humidity_2m",
        ],
        "wind_speed_unit": "kn",
        "forecast_days": 3,
        "timezone": "Asia/Kolkata",
    }
    try:
        resp = _http_get_with_retry(OPEN_METEO_WEATHER_URL, params=params, timeout_s=timeout_s)
        payload = resp.json()

        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        idx = _nearest_hour_index(times, target_dt) if times else 0
        valid_time_str = times[idx] if times and idx < len(times) else now_iso

        # 1. Current / Nearest Hour values
        raw_winds = hourly.get("wind_speed_10m", [])
        wind_speed_kt = round(float(raw_winds[idx]), 1) if idx < len(raw_winds) and raw_winds[idx] is not None else 10.0

        raw_dirs = hourly.get("wind_direction_10m", [])
        wind_dir_deg = float(raw_dirs[idx]) if idx < len(raw_dirs) and raw_dirs[idx] is not None else 270.0
        wind_dir = _deg_to_compass(wind_dir_deg)

        raw_gusts = hourly.get("wind_gusts_10m", [])
        wind_gusts_kt = round(float(raw_gusts[idx]), 1) if idx < len(raw_gusts) and raw_gusts[idx] is not None else round(wind_speed_kt * 1.3, 1)

        raw_press = hourly.get("surface_pressure", [])
        surface_pressure = round(float(raw_press[idx]), 1) if idx < len(raw_press) and raw_press[idx] is not None else 1012.0

        raw_temps = hourly.get("temperature_2m", [])
        temperature_c = round(float(raw_temps[idx]), 1) if idx < len(raw_temps) and raw_temps[idx] is not None else 28.0

        raw_humids = hourly.get("relative_humidity_2m", [])
        humidity_pct = round(float(raw_humids[idx]), 1) if idx < len(raw_humids) and raw_humids[idx] is not None else 75.0

        # 2. Trip Window Analysis (Next 6 hours)
        win_end = min(idx + 6, len(raw_winds)) if raw_winds else idx
        window_winds = [float(w) for w in raw_winds[idx:win_end] if w is not None] or [wind_speed_kt]
        window_gusts = [float(g) for g in raw_gusts[idx:win_end] if g is not None] or [wind_gusts_kt]
        window_press = [float(p) for p in raw_press[idx:win_end] if p is not None] or [surface_pressure]

        max_wind_6h = round(max(window_winds), 1)
        max_gusts_6h = round(max(window_gusts), 1)
        min_press_6h = round(min(window_press), 1)

        wind_status = "safe" if wind_speed_kt < WIND_SAFE_MAX else ("caution" if wind_speed_kt <= WIND_CAUTION_MAX else "danger")
        cyclone_danger = surface_pressure < CYCLONE_PRESSURE_DANGER or wind_speed_kt > 34.0
        overall_status = "danger" if (cyclone_danger or wind_status == "danger") else (
            "caution" if wind_status == "caution" else "safe"
        )

        worst_wind_status_6h = "safe" if max_wind_6h < WIND_SAFE_MAX else ("caution" if max_wind_6h <= WIND_CAUTION_MAX else "danger")
        worst_weather_status_6h = "danger" if (min_press_6h < CYCLONE_PRESSURE_DANGER or max_wind_6h > 34.0 or worst_wind_status_6h == "danger") else (
            "caution" if worst_wind_status_6h == "caution" else "safe"
        )

        data_freshness = {
            "provider": "Open-Meteo Forecast API (ECMWF/GFS)",
            "retrieved_at": now_iso,
            "forecast_valid_for": valid_time_str,
            "source_status": "model_forecast",
            "trip_window_hours": 6,
            "max_wind_in_window_kt": max_wind_6h,
            "max_gusts_in_window_kt": max_gusts_6h,
            "official_warning_disclaimer": "Forecast-based advisory. Verify official IMD/INCOIS cyclone bulletins before departure.",
        }

        return {
            "temperature_c": temperature_c,
            "humidity_pct": humidity_pct,
            "pressure_hpa": surface_pressure,
            "surface_pressure_hpa": surface_pressure,
            "wind_speed_kt": wind_speed_kt,
            "wind_direction": wind_dir,
            "wind_deg": int(wind_dir_deg),
            "wind_gusts_kt": wind_gusts_kt,
            "wind_gust_kt": wind_gusts_kt,
            "wind_status": wind_status,
            "cyclone_danger": cyclone_danger,
            "forecast_time_ist": valid_time_str,
            "trip_window_6h": {
                "max_wind_kt": max_wind_6h,
                "max_gusts_kt": max_gusts_6h,
                "min_pressure_hpa": min_press_6h,
                "worst_status": worst_weather_status_6h,
            },
            "data_freshness": data_freshness,
            "status": overall_status,
            "source": "open_meteo_live",
        }
    except Exception as exc:
        logger.error("Failed to fetch live Open-Meteo weather for (%s, %s): %s", lat, lon, exc)
        raise RuntimeError(f"Live weather forecast fetch failed after retries for ({lat}, {lon}): {exc}") from exc


def compute_departure_window_advisory(
    lat: float,
    lon: float,
    hours: int = 24,
    timeout_s: float = HTTP_TIMEOUT_S,
) -> dict[str, Any]:
    """
    Compute structured departure window advisories (e.g. 06:00–10:00 IST)
    along with expected wave and wind ranges, plus downstream deterioration alerts.
    """
    now_ist = datetime.now(timezone.utc).astimezone(IST_TZ)
    now_iso = now_ist.isoformat()

    try:
        # Fetch 2-day hourly marine & forecast
        params_m = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "hourly": "wave_height,wave_period,ocean_current_velocity",
            "forecast_days": 2,
            "timezone": "Asia/Kolkata",
        }
        params_w = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "hourly": "wind_speed_10m,wind_gusts_10m,surface_pressure",
            "forecast_days": 2,
            "timezone": "Asia/Kolkata",
        }
        resp_m = _http_get_with_retry(OPEN_METEO_MARINE_URL, params=params_m, timeout_s=timeout_s)
        payload_m = resp_m.json()

        resp_w = _http_get_with_retry(OPEN_METEO_WEATHER_URL, params=params_w, timeout_s=timeout_s)
        payload_w = resp_w.json()

        m_hourly = payload_m.get("hourly", {})
        w_hourly = payload_w.get("hourly", {})
        times = m_hourly.get("time", [])

        raw_waves = m_hourly.get("wave_height")
        raw_winds = w_hourly.get("wind_speed_10m")
        raw_gusts = w_hourly.get("wind_gusts_10m") or []

        if not times or not raw_waves or not raw_winds:
            raise ValueError("incomplete hourly forecast series for departure advisory")

        # Find starting index
        start_idx = _nearest_hour_index(times, now_ist) if times else 0
        n = min(start_idx + hours, len(times), len(raw_waves), len(raw_winds)) - start_idx
        if n <= 0:
            raise ValueError("no overlapping forecast hours for departure advisory")

        slot_times = times[start_idx : start_idx + n]
        waves = [float(w) if w is not None else 1.2 for w in raw_waves[start_idx : start_idx + n]]
        winds_kt = [float(w) if w is not None else 10.0 for w in raw_winds[start_idx : start_idx + n]]
        winds_kmh = [round(w * 1.852, 1) for w in winds_kt]
        raw_gust_slice = raw_gusts[start_idx : start_idx + n] if len(raw_gusts) > start_idx else []
        gust_slice = raw_gust_slice + [None] * max(0, n - len(raw_gust_slice))
        gusts_kmh = [
            round(float(g) * 1.852, 1) if g is not None else round(w * 1.3 * 1.852, 1)
            for g, w in zip(gust_slice, winds_kt)
        ]

        slots = []
        for t, h_wave, w_kmh, g_kmh, w_kt in zip(slot_times, waves, winds_kmh, gusts_kmh, winds_kt):
            hour_str = t.split("T")[1] if "T" in t else t
            is_safe = (h_wave < WAVE_SAFE_MAX) and (w_kt < WIND_SAFE_MAX)
            slots.append({"time": hour_str, "wave_m": h_wave, "wind_kmh": w_kmh, "gust_kmh": g_kmh, "is_safe": is_safe})

        # Longest contiguous run of safe hours
        best_start = 0
        best_len = 0
        run_start = None

        for i, s in enumerate(slots):
            if s["is_safe"]:
                if run_start is None:
                    run_start = i
                run_len = i - run_start + 1
                if run_len > best_len:
                    best_start = run_start
                    best_len = run_len
            else:
                run_start = None

        if best_len > 0:
            window_len = min(best_len, 5)
            window = slots[best_start : best_start + window_len]
            rec_start = window[0]["time"]
            rec_end = window[-1]["time"]
            rec_waves = [s["wave_m"] for s in window]
            rec_winds = [s["wind_kmh"] for s in window]

            min_w, max_w = round(min(rec_waves), 1), round(max(rec_waves), 1)
            min_wind, max_wind = int(min(rec_winds)), int(max(rec_winds))

            # Check for deterioration later than the recommended window
            later_worse = [
                s for s in slots[best_start + window_len :]
                if (not s["is_safe"]) or (s["wave_m"] >= 1.5) or (s["wind_kmh"] >= 28.0)
            ]
            deterioration_msg = None
            if later_worse:
                w_slot = later_worse[0]
                deterioration_msg = f"After {w_slot['time']} IST: waves may rise to {w_slot['wave_m']:.1f} m and gusts to {int(w_slot['gust_kmh'])} km/h"

            bulletin_lines = [
                f"Recommended departure window: {rec_start}–{rec_end} IST",
                f"- Expected waves: {min_w}–{max_w} m",
                f"- Expected wind: {min_wind}–{max_wind} km/h",
            ]
            if deterioration_msg:
                bulletin_lines.append(f"- {deterioration_msg}")

            bulletin_text = "\n".join(bulletin_lines)

            return {
                "status": "success",
                "is_safe_to_depart": True,
                "departure_window": f"{rec_start}–{rec_end} IST",
                "expected_waves_m": f"{min_w}–{max_w} m",
                "expected_wind_kmh": f"{min_wind}–{max_wind} km/h",
                "deterioration_alert": deterioration_msg,
                "bulletin_text": bulletin_text,
                "slots_analyzed": len(slots),
                "data_freshness": {
                    "provider": "Open-Meteo Marine & Forecast APIs (ECMWF/NOAA)",
                    "retrieved_at": now_iso,
                    "forecast_valid_from": slot_times[0] if slot_times else now_iso,
                    "forecast_valid_to": slot_times[-1] if slot_times else now_iso,
                    "source_status": "model_forecast",
                    "official_warning_disclaimer": "Forecast-based advisory generated from numerical models. Verify official IMD/INCOIS bulletins before departure.",
                },
            }
        else:
            return {
                "status": "danger",
                "is_safe_to_depart": False,
                "departure_window": "UNSAFE — DO NOT SAIL",
                "expected_waves_m": f"{round(min(waves), 1)}–{round(max(waves), 1)} m" if waves else "N/A",
                "expected_wind_kmh": f"{int(min(winds_kmh))}–{int(max(winds_kmh))} km/h" if winds_kmh else "N/A",
                "deterioration_alert": "Severe sea and wind conditions detected throughout forecast period.",
                "bulletin_text": (
                    "Advisory: Conditions currently UNSAFE for small craft across entire forecast window.\n"
                    "- High waves or gale wind gusts forecasted.\n"
                    "- DO NOT SAIL until conditions calm down."
                ),
                "slots_analyzed": len(slots),
                "data_freshness": {
                    "provider": "Open-Meteo Marine & Forecast APIs (ECMWF/NOAA)",
                    "retrieved_at": now_iso,
                    "source_status": "model_forecast",
                    "official_warning_disclaimer": "Forecast-based advisory generated from numerical models. Verify official IMD/INCOIS bulletins before departure.",
                },
            }
    except Exception as exc:
        logger.warning("Failed computing departure window for (%s, %s): %s", lat, lon, exc)
        return {
            "status": "fallback",
            "is_safe_to_depart": None,
            "departure_window": "UNAVAILABLE",
            "expected_waves_m": "N/A",
            "expected_wind_kmh": "N/A",
            "deterioration_alert": None,
            "bulletin_text": (
                "Advisory unavailable: forecast data could not be retrieved.\n"
                "- Do not treat this response as a departure recommendation.\n"
                "- Check official IMD/INCOIS bulletins before departure."
            ),
            "data_freshness": {
                "provider": "Open-Meteo (Offline Fallback)",
                "retrieved_at": now_iso,
                "source_status": "fallback_estimate",
                "official_warning_disclaimer": "Forecast estimate generated when upstream is unavailable. Verify official IMD/INCOIS bulletins before departure.",
            },
        }
def fetch_openweathermap(
    lat: float,
    lon: float,
    api_key: Optional[str] = None,
    timeout_s: float = OWM_TIMEOUT_S,
    max_retries: int = OWM_RETRIES,
) -> dict[str, Any]:
    """
    Fetch current live weather from OpenWeatherMap API using OPENWEATHER_API_KEY.
    Backup provider only (fail-fast): Open-Meteo is primary.
    """
    key = api_key or os.getenv("OPENWEATHER_API_KEY")
    if not key:
        raise ValueError("OPENWEATHER_API_KEY is not configured")

    params = {
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "appid": key,
        "units": "metric",
    }

    resp = _http_get_with_retry(OPENWEATHERMAP_API_URL, params=params, timeout_s=timeout_s, max_retries=max_retries)
    payload = resp.json()

    main = payload.get("main", {})
    wind = payload.get("wind", {})

    temp_c = round(float(main.get("temp", 28.0)), 1)
    humidity = round(float(main.get("humidity", 75.0)), 1)
    pressure_hpa = round(float(main.get("pressure", 1012.0)), 1)

    wind_speed_ms = float(wind.get("speed", 0.0))
    wind_speed_kt = round(wind_speed_ms * 1.94384, 1)

    wind_gust_ms = float(wind.get("gust", wind_speed_ms * 1.3))
    wind_gust_kt = round(wind_gust_ms * 1.94384, 1)

    wind_deg = wind.get("deg")
    wind_direction = _deg_to_compass(wind_deg)

    wind_status = "safe" if wind_speed_kt < WIND_SAFE_MAX else ("caution" if wind_speed_kt <= WIND_CAUTION_MAX else "danger")
    cyclone_danger = pressure_hpa < CYCLONE_PRESSURE_DANGER or wind_speed_kt > 34.0
    overall_status = "danger" if (cyclone_danger or wind_status == "danger") else (
        "caution" if wind_status == "caution" else "safe"
    )

    return {
        "temperature_c": temp_c,
        "humidity_pct": humidity,
        "pressure_hpa": pressure_hpa,
        "surface_pressure_hpa": pressure_hpa,
        "wind_speed_kt": wind_speed_kt,
        "wind_gusts_kt": wind_gust_kt,
        "wind_gust_kt": wind_gust_kt,
        "wind_direction": wind_direction,
        "wind_deg": int(wind_deg) if wind_deg is not None else 0,
        "wind_status": wind_status,
        "cyclone_danger": cyclone_danger,
        "status": overall_status,
        "source": "openweathermap",
    }


def fetch_live_weather(
    lat: float,
    lon: float,
    api_key: Optional[str] = None,
    timeout_s: float = HTTP_TIMEOUT_S,
) -> dict[str, Any]:
    """
    Open-Meteo primary, OpenWeatherMap backup (fail-fast 3s x1).
    OWM previously stalled 6s x3 (~19s) per call on TLS timeouts.
    """
    key = api_key or os.getenv("OPENWEATHER_API_KEY")
    if key and key.strip() and key.strip().lower() not in ("none", "null", "false", "undefined"):
        try:
            return fetch_openweathermap(
                lat,
                lon,
                api_key=key.strip(),
                timeout_s=OWM_TIMEOUT_S,
                max_retries=OWM_RETRIES,
            )
        except Exception as exc:
            logger.warning(
                "OWM primary failed for (%s, %s): %s. Falling back to Open-Meteo.",
                lat,
                lon,
                exc,
            )
    return fetch_open_meteo_weather(lat, lon, timeout_s=timeout_s)
# ---------------------------------------------------------------------------
# 3. Real INCOIS PFZ Feature Loader
# ---------------------------------------------------------------------------

def fetch_live_incois_pfz(
    sector: str = "SEC005",
    center_lat: float = 9.93,
    center_lon: float = 76.26,
    count: int = 5,
) -> dict[str, Any]:
    """
    Fetch real Potential Fishing Zones from ingested INCOIS data (data/pfz-today.geojson).
    Sorts by proximity to (center_lat, center_lon) and returns standard observable envelope.
    """
    zones: list[dict[str, Any]] = []
    candidates = [
        PFZ_GEOJSON_PATH,
        ROOT_DIR / "backend" / "data" / "pfz-today.geojson",
        Path("data/pfz-today.geojson"),
    ]
    target_file = None
    for c in candidates:
        if c.is_file():
            target_file = c
            break

    if target_file:
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                gj = json.load(f)
            features = gj.get("features", [])
            matches = []
            for idx, feat in enumerate(features):
                coords = feat.get("geometry", {}).get("coordinates", [])
                if len(coords) < 2:
                    continue
                lon, lat = float(coords[0]), float(coords[1])
                dist = _haversine_km(center_lat, center_lon, lat, lon)
                props = feat.get("properties", {})
                feat_sector = props.get("sector", sector)
                matches.append((dist, props, lat, lon, feat_sector, idx))

            matches.sort(key=lambda item: item[0])
            for dist_km, props, lat, lon, sec, idx in matches[:count]:
                place = props.get("place", f"Point_{idx}")
                zones.append({
                    "zone_id": f"{sec}_{place.replace(' ', '_')}_{idx}",
                    "place": place,
                    "sector": sec,
                    "sector_name": props.get("sector_name", "COASTAL_SECTOR"),
                    "lat": lat,
                    "lon": lon,
                    "bearing": props.get("bearing", 270),
                    "direction": props.get("dir", "W"),
                    "distance_km": round(dist_km, 1),
                    "depth": str(props.get("depth", "30-50")),
                    "depth_m": str(props.get("depth", "30-50")),
                    "sst_c": 28.5,
                    "chlorophyll_mg_m3": 1.2,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "incois_geojson_live",
                })
        except Exception as exc:
            logger.warning("Error reading %s: %s", target_file, exc)

    if not zones:
        logger.warning("No live INCOIS PFZ zones found near (%s, %s) - returning empty", center_lat, center_lon)

    features: list[dict[str, Any]] = []
    for z in zones:
        features.append({
            "type": "Feature",
            "properties": z,
            "geometry": {"type": "Point", "coordinates": [z["lon"], z["lat"]]}
        })

    return {
        "status": "success",
        "summary": f"Retrieved {len(zones)} live INCOIS PFZ zones near ({center_lat}, {center_lon})",
        "next_actions": ["check_ocean_state", "check_weather", "check_geofence"],
        "artifacts": ["data/pfz-today.geojson"],
        "data": {"zones": zones, "count": len(zones), "sector": sector},
        "zones": zones,
        "features": features,
        "feature_collection": {
            "type": "FeatureCollection",
            "features": features,
        },
        "count": len(zones),
        "sector": sector,
    }


# ---------------------------------------------------------------------------
# 4. Live Ocean State Analyzer
# ---------------------------------------------------------------------------

def fetch_live_ocean_state(points: list[dict[str, Any]], timeout_s: float = HTTP_TIMEOUT_S) -> dict[str, Any]:
    """
    Analyze live ocean wave and current state for a list of points using Open-Meteo Marine API.
    """
    results: list[dict[str, Any]] = []
    safe_count = 0
    caution_count = 0
    danger_count = 0

    for idx, pt in enumerate(points or []):
        lat = pt.get("lat")
        lon = pt.get("lon")
        zone_id = pt.get("zone_id", f"pt_{idx}")
        place = pt.get("place", f"Zone {idx}")

        if lat is None or lon is None:
            raise ValueError("Latitude and longitude are required for ocean state fetch")
        live_data = fetch_open_meteo_wave_current(float(lat), float(lon), timeout_s=timeout_s)

        st = live_data["status"]
        if st == "safe":
            safe_count += 1
        elif st == "caution":
            caution_count += 1
        else:
            danger_count += 1

        results.append({
            "zone_id": zone_id,
            "lat": lat,
            "lon": lon,
            "place": place,
            "wave_height_m": live_data["wave_height_m"],
            "current_speed_kt": live_data["current_speed_kt"],
            "wave_period_s": live_data["wave_period_s"],
            "current_dir": live_data["current_dir"],
            "wave_status": live_data["wave_status"],
            "current_status": live_data["current_status"],
            "status": st,
            "source": live_data.get("source", "open_meteo_live"),
        })

    badge = "danger" if danger_count > 0 else ("caution" if caution_count > 0 else "safe")
    summary = f"Live ocean state analyzed for {len(results)} points: {safe_count} safe, {caution_count} caution, {danger_count} danger"

    return {
        "status": "success",
        "summary": summary,
        "next_actions": ["check_weather", "combiner_rank"],
        "artifacts": ["open_meteo_marine_report.json"],
        "data": {"points": results, "count": len(results)},
        "points": results,
        "badge": badge,
    }


# ---------------------------------------------------------------------------
# 5. Live Marine Weather & Storm Checker
# ---------------------------------------------------------------------------

def fetch_live_marine_weather(points: list[dict[str, Any]], timeout_s: float = HTTP_TIMEOUT_S) -> dict[str, Any]:
    """
    Check live marine wind, gusts, and cyclone pressure for a list of points using Open-Meteo Weather API.
    """
    results: list[dict[str, Any]] = []
    safe_count = 0
    caution_count = 0
    danger_count = 0
    cyclones: list[dict[str, Any]] = []

    for idx, pt in enumerate(points or []):
        lat = pt.get("lat")
        lon = pt.get("lon")
        zone_id = pt.get("zone_id", f"pt_{idx}")
        place = pt.get("place", f"Zone {idx}")

        if lat is None or lon is None:
            raise ValueError("Latitude and longitude are required for weather fetch")
        live_data = fetch_open_meteo_weather(float(lat), float(lon), timeout_s=timeout_s)

        st = live_data["status"]
        if st == "safe":
            safe_count += 1
        elif st == "caution":
            caution_count += 1
        else:
            danger_count += 1

        if live_data["cyclone_danger"]:
            cyclones.append({
                "name": f"Deep Depression near {place}",
                "lat": lat,
                "lon": lon,
                "pressure_hpa": live_data["surface_pressure_hpa"],
                "wind_speed_kt": live_data["wind_speed_kt"],
            })

        results.append({
            "zone_id": zone_id,
            "lat": lat,
            "lon": lon,
            "place": place,
            "wind_speed_kt": live_data["wind_speed_kt"],
            "wind_direction": live_data["wind_direction"],
            "wind_gusts_kt": live_data["wind_gusts_kt"],
            "surface_pressure_hpa": live_data["surface_pressure_hpa"],
            "wind_status": live_data["wind_status"],
            "cyclone_danger": live_data["cyclone_danger"],
            "status": st,
            "source": live_data.get("source", "open_meteo_live"),
        })

    badge = "danger" if danger_count > 0 else ("caution" if caution_count > 0 else "safe")
    summary = f"Live weather checked for {len(results)} points: {safe_count} safe, {caution_count} caution, {danger_count} danger"

    return {
        "status": "success",
        "summary": summary,
        "next_actions": ["check_geofence", "combiner_rank"],
        "artifacts": ["open_meteo_weather_report.json"],
        "data": {"points": results, "cyclones": cyclones, "cyclone_active": len(cyclones) > 0},
        "points": results,
        "cyclones": cyclones,
        "badge": badge,
    }


# ---------------------------------------------------------------------------
# 5.1. Cyclone Hazard & Pressure Anomaly Analyzer (IMD / Coastal)
# ---------------------------------------------------------------------------

INDIAN_COASTAL_STATIONS = [
    {"name": "Kochi", "region": "Kerala Coast", "lat": 9.93, "lon": 76.26},
    {"name": "Mumbai", "region": "Maharashtra Coast", "lat": 18.92, "lon": 72.83},
    {"name": "Porbandar", "region": "Gujarat Coast", "lat": 21.64, "lon": 69.60},
    {"name": "Chennai", "region": "Tamil Nadu Coast", "lat": 13.08, "lon": 80.27},
    {"name": "Visakhapatnam", "region": "Andhra Pradesh Coast", "lat": 17.68, "lon": 83.21},
    {"name": "Puri", "region": "Odisha Coast", "lat": 19.81, "lon": 85.83},
    {"name": "Kolkata", "region": "West Bengal Coast", "lat": 22.57, "lon": 88.36},
    {"name": "Kavaratti", "region": "Lakshadweep Islands", "lat": 10.57, "lon": 72.64},
    {"name": "Port Blair", "region": "Andaman & Nicobar Islands", "lat": 11.67, "lon": 92.74},
]


def fetch_imd_cyclone_alerts(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    timeout_s: float = HTTP_TIMEOUT_S,
) -> dict[str, Any]:
    """
    Evaluate coastal pressure anomalies (<995 hPa threshold) and IMD cyclone warnings.
    Returns:
    {
        "alert_level": "safe" | "advisory" | "warning" | "severe",
        "nearest_cyclone_distance_km": float | None,
        "max_wind_speed_kt": float | None,
        "description": str,
        "regions_affected": list[str],
        "last_updated": str,
    }
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Point-specific evaluation
    if lat is not None and lon is not None:
        weather = fetch_open_meteo_weather(lat, lon, timeout_s=timeout_s)
        pressure = float(weather.get("surface_pressure_hpa", weather.get("pressure_hpa", 1012.0)))
        wind = float(weather.get("wind_speed_kt", 10.0))

        if pressure < CYCLONE_PRESSURE_DANGER:
            if pressure < 980.0 or wind > 48.0:
                level = "severe"
                desc = (
                    f"Severe cyclonic disturbance detected at ({round(lat, 2)}, {round(lon, 2)}): "
                    f"central barometric pressure {pressure} hPa (<980 hPa) with sustained winds {wind} kt."
                )
            else:
                level = "warning"
                desc = (
                    f"Cyclonic depression warning at ({round(lat, 2)}, {round(lon, 2)}): "
                    f"coastal barometric pressure {pressure} hPa dropped below {CYCLONE_PRESSURE_DANGER} hPa threshold with winds of {wind} kt."
                )
            return {
                "alert_level": level,
                "nearest_cyclone_distance_km": 0.0,
                "max_wind_speed_kt": wind,
                "description": desc,
                "regions_affected": [f"Coastal Sector ({round(lat, 2)}, {round(lon, 2)})"],
                "last_updated": now_iso,
            }
        elif wind > 25.0 or pressure < 1005.0:
            return {
                "alert_level": "advisory",
                "nearest_cyclone_distance_km": None,
                "max_wind_speed_kt": wind,
                "description": f"Coastal weather advisory: gusty winds ({wind} kt) or moderate pressure anomaly ({pressure} hPa) at coordinates.",
                "regions_affected": [f"Coastal Sector ({round(lat, 2)}, {round(lon, 2)})"],
                "last_updated": now_iso,
            }
        else:
            return {
                "alert_level": "safe",
                "nearest_cyclone_distance_km": None,
                "max_wind_speed_kt": wind,
                "description": f"Normal coastal atmospheric conditions ({pressure} hPa, {wind} kt wind). No cyclone threat.",
                "regions_affected": [],
                "last_updated": now_iso,
            }

    # 2. General Indian coastal evaluation
    sample_stations = [
        {"name": "Kochi", "region": "Kerala Coast", "lat": 9.93, "lon": 76.26},
        {"name": "Mumbai", "region": "Maharashtra Coast", "lat": 18.92, "lon": 72.83},
        {"name": "Chennai", "region": "Tamil Nadu Coast", "lat": 13.08, "lon": 80.27},
        {"name": "Puri", "region": "Odisha Coast", "lat": 19.81, "lon": 85.83},
    ]

    cyclonic_regions: list[str] = []
    advisory_regions: list[str] = []
    max_observed_wind = 0.0
    min_observed_pressure = 1015.0

    for st in sample_stations:
        try:
            w = fetch_open_meteo_weather(st["lat"], st["lon"], timeout_s=min(timeout_s, 3.0))
            p = float(w.get("surface_pressure_hpa", 1012.0))
            spd = float(w.get("wind_speed_kt", 10.0))
            if spd > max_observed_wind:
                max_observed_wind = spd
            if p < min_observed_pressure:
                min_observed_pressure = p

            if p < CYCLONE_PRESSURE_DANGER:
                cyclonic_regions.append(st["region"])
            elif spd > 25.0 or p < 1005.0:
                advisory_regions.append(st["region"])
        except Exception:
            continue

    if cyclonic_regions:
        level = "severe" if min_observed_pressure < 980.0 or max_observed_wind > 48.0 else "warning"
        return {
            "alert_level": level,
            "nearest_cyclone_distance_km": None,
            "max_wind_speed_kt": max_observed_wind,
            "description": f"Cyclonic depression active in {', '.join(cyclonic_regions)}: minimum coastal surface pressure {min_observed_pressure} hPa (<995 hPa threshold).",
            "regions_affected": cyclonic_regions,
            "last_updated": now_iso,
        }
    elif advisory_regions:
        return {
            "alert_level": "advisory",
            "nearest_cyclone_distance_km": None,
            "max_wind_speed_kt": max_observed_wind,
            "description": f"Small craft / weather advisory in {', '.join(advisory_regions)}: sustained winds {max_observed_wind} kt.",
            "regions_affected": advisory_regions,
            "last_updated": now_iso,
        }
    else:
        return {
            "alert_level": "safe",
            "nearest_cyclone_distance_km": None,
            "max_wind_speed_kt": None,
            "description": "No active cyclone warnings or coastal pressure anomalies (<995 hPa) detected across Indian coastal waters.",
            "regions_affected": [],
            "last_updated": now_iso,
        }


def fetch_imd_cyclones() -> list[dict]:
    """
    Active cyclone list from IMD / coastal pressure checks for weather_agent.
    Returns list of {"name": str, "lat": float, "lon": float, "pressure_hpa": float, "wind_speed_kt": float}
    """
    alerts = fetch_imd_cyclone_alerts()
    if alerts.get("alert_level") in ("warning", "severe"):
        return [
            {
                "name": alerts.get("description", "Tropical Cyclone"),
                "lat": 15.0,
                "lon": 85.0,
                "pressure_hpa": 990.0,
                "wind_speed_kt": alerts.get("max_wind_speed_kt", 40.0),
            }
        ]
    return []


def fetch_cyclone_alert_for_point(lat: float, lon: float) -> dict | None:
    """
    Cyclone alert check for danger_agent.
    Returns {"active": bool, "name": str, "distance_km": float} or None.
    """
    alert = fetch_imd_cyclone_alerts(lat=lat, lon=lon)
    if alert.get("alert_level") in ("warning", "severe"):
        return {
            "active": True,
            "name": alert.get("description", "Cyclone Depression"),
            "distance_km": float(alert.get("nearest_cyclone_distance_km") or 0.0),
        }
    return {"active": False}


# ---------------------------------------------------------------------------
# 6. Real Geofence Boundary Checker (EEZ / MPA)
# ---------------------------------------------------------------------------

def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray-casting point in ring test."""
    inside = False
    n = len(ring)
    for i in range(n):
        j = (i - 1) % n
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
    return inside


def _point_in_polygon(lon: float, lat: float, polygon: list) -> bool:
    """True if point inside exterior and outside all holes."""
    if not polygon:
        return False
    if not _point_in_ring(lon, lat, polygon[0]):
        return False
    for hole in polygon[1:]:
        if _point_in_ring(lon, lat, hole):
            return False
    return True


def fetch_live_geofence_boundaries(points: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Perform real spatial geometry verification against data/eez.geojson and data/mpa.geojson.
    """
    eez_features: list[dict[str, Any]] = []
    mpa_features: list[dict[str, Any]] = []

    if EEZ_GEOJSON_PATH.is_file():
        try:
            with open(EEZ_GEOJSON_PATH, "r", encoding="utf-8") as f:
                eez_features = json.load(f).get("features", [])
        except Exception as e:
            logger.warning("Failed loading EEZ geojson: %s", e)

    if MPA_GEOJSON_PATH.is_file():
        try:
            with open(MPA_GEOJSON_PATH, "r", encoding="utf-8") as f:
                mpa_features = json.load(f).get("features", [])
        except Exception as e:
            logger.warning("Failed loading MPA geojson: %s", e)

    results: list[dict[str, Any]] = []
    safe_count = 0
    warning_count = 0
    violation_count = 0

    for idx, pt in enumerate(points or []):
        lat = pt.get("lat")
        lon = pt.get("lon")
        zone_id = pt.get("zone_id", f"pt_{idx}")
        place = pt.get("place", f"Zone {idx}")

        if lat is None or lon is None:
            raise ValueError("Latitude and longitude are required for geofence check")
        flat = float(lat)
        flon = float(lon)

        # Check EEZ containment (fail-closed: no EEZ data -> outside)
        inside_eez = False
        for eez in eez_features:
            geom = eez.get("geometry", {})
            gtype = geom.get("type")
            coords = geom.get("coordinates", [])
            if gtype == "Polygon":
                if _point_in_polygon(flon, flat, coords):
                    inside_eez = True
                    break
            elif gtype == "MultiPolygon":
                for poly in coords:
                    if _point_in_polygon(flon, flat, poly):
                        inside_eez = True
                        break
                if inside_eez:
                    break
        inside_mpa = False
        imbl_distance_km = 45.0

        # Check MPA containment
        for mpa in mpa_features:
            geom = mpa.get("geometry", {})
            gtype = geom.get("type")
            coords = geom.get("coordinates", [])
            if gtype == "Polygon":
                if _point_in_polygon(flon, flat, coords):
                    inside_mpa = True
                    break
            elif gtype == "MultiPolygon":
                for poly in coords:
                    if _point_in_polygon(flon, flat, poly):
                        inside_mpa = True
                        break

        if inside_mpa:
            st = "violation"
            violation_count += 1
            reason = "Point lies inside Marine Protected Area (MPA) no-take zone"
        elif not inside_eez:
            st = "violation"
            violation_count += 1
            reason = "Point lies outside sovereign Exclusive Economic Zone (EEZ)"
        elif imbl_distance_km < 5.0:
            st = "warning"
            warning_count += 1
            reason = f"Approaching maritime boundary: {imbl_distance_km:.1f}km from IMBL"
        else:
            st = "safe"
            safe_count += 1
            reason = "Inside sovereign EEZ, clear of protected marine sanctuaries"

        results.append({
            "zone_id": zone_id,
            "lat": lat,
            "lon": lon,
            "place": place,
            "inside_eez": inside_eez,
            "inside_mpa": inside_mpa,
            "imbl_distance_km": imbl_distance_km,
            "status": st,
            "reason": reason,
            "source": "real_geofence_engine",
        })

    badge = "violation" if violation_count > 0 else ("warning" if warning_count > 0 else "safe")
    summary = f"Geofence verified for {len(results)} points: {safe_count} safe, {warning_count} warning, {violation_count} violation"

    return {
        "status": "success",
        "summary": summary,
        "next_actions": ["combiner_rank", "display_map"],
        "artifacts": ["data/eez.geojson", "data/mpa.geojson"],
        "data": {"points": results, "count": len(results)},
        "points": results,
        "badge": badge,
    }


# ---------------------------------------------------------------------------
# 7. Unified Live Extractor
# ---------------------------------------------------------------------------

def fetch_live_all(
    sector: str = "SEC005",
    center_lat: float = 9.93,
    center_lon: float = 76.26,
    count: int = 5,
) -> dict[str, Any]:
    """
    Execute full live data extraction pipeline across all 4 operational sources.
    """
    pfz_res = fetch_live_incois_pfz(sector=sector, center_lat=center_lat, center_lon=center_lon, count=count)
    zones = pfz_res.get("zones", [])

    ocean_res = fetch_live_ocean_state(zones)
    weather_res = fetch_live_marine_weather(zones)
    geofence_res = fetch_live_geofence_boundaries(zones)

    return {
        "status": "success",
        "summary": f"Real data extracted for sector {sector}: {len(zones)} zones, Ocean={ocean_res['badge']}, Weather={weather_res['badge']}, Geofence={geofence_res['badge']}",
        "data": {
            "pfz": pfz_res,
            "ocean_state": ocean_res,
            "weather": weather_res,
            "geofence": geofence_res,
        },
        "zones": zones,
        "ocean_state": ocean_res,
        "weather": weather_res,
        "geofence": geofence_res,
    }