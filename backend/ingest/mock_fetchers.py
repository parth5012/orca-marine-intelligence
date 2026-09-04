"""
Pluggable Mock Data Fetching Layer — INCOIS / OSF / IMD / Boundaries.

Owner: M-B (Data & Mocking) + M-A (Agents & Orchestration)
Module: backend/ingest/mock_fetchers.py
Ticket: #23 (AFK) — parent map #22

Provides a complete, deterministic, scenario-controllable mock data
fetching engine so dynamic agents run end-to-end when external
government servers (INCOIS/OSF/IMD) or local PostGIS are offline.

Design principles (per AGENTS.md harness):
  - Deterministic: same inputs -> same outputs (stable MD5 hash, no RNG;
    wall-clock ``timestamp`` fields via _ist_now_iso are excluded from this
    contract and vary per call).
  - Scenario-controllable: SimulationScenario shifts wave/wind/cyclone/
    geofence values into known safety bands.
  - Pluggable: ORCA_DATA_SOURCE=mock|live selects mock vs real fetchers.
  - Observable: every function returns
    {status, summary, next_actions, artifacts, ...} plus a deterministic
    payload compatible with concurrent safety agents.

Scenario -> value mapping:
  - NORMAL:           waves 0.7-1.4m safe,  current 0.5-1.8kt safe,
                      wind 7-14kt safe,     no cyclone,
                      inside EEZ, outside MPA, IMBL >2km.
  - ROUGH_SEAS:       waves 2.6-4.0m danger, current 2.5-4.0kt caution/danger,
                      wind 16-24kt caution,  no cyclone,
                      geofence same as NORMAL.
  - CYCLONE_WARNING:  waves 2.0-3.5m caution/danger, current 2.0-3.5kt,
                      wind 28-35kt danger,  cyclone ACTIVE within 500km
                      (nearest 80-300km, 500km buffer circle),
                      geofence same as NORMAL.
  - BORDER_VIOLATION: ocean/weather same as NORMAL (sea is calm),
                      geofence rotates per-point violations:
                        i%3==0 -> inside MPA (danger, banned),
                        i%3==1 -> within 2km IMBL (caution),
                        i%3==2 -> outside EEZ (danger).

Thresholds (match agents, non-negotiable):
  - wave <1.5 safe, 1.5-2.5 caution, >2.5 danger
  - current >2 caution, >3 danger (worst of wave/current wins)
  - wind <15 safe, 15-25 caution, >25 danger
  - cyclone within 500km -> danger regardless of wind
  - inside MPA / outside EEZ -> danger; within 2km IMBL -> caution
"""

from __future__ import annotations

import hashlib
import math
import os
import warnings
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Scenario controllers
# ---------------------------------------------------------------------------


class SimulationScenario(str, Enum):
    """Scenario controllers for deterministic simulation."""

    NORMAL = "normal"
    ROUGH_SEAS = "rough_seas"
    CYCLONE_WARNING = "cyclone_warning"
    BORDER_VIOLATION = "border_violation"


_SCENARIO_ALIASES: dict[str, SimulationScenario] = {
    "normal": SimulationScenario.NORMAL,
    "rough_seas": SimulationScenario.ROUGH_SEAS,
    "rough": SimulationScenario.ROUGH_SEAS,
    "roughseas": SimulationScenario.ROUGH_SEAS,
    "cyclone_warning": SimulationScenario.CYCLONE_WARNING,
    "cyclone": SimulationScenario.CYCLONE_WARNING,
    "border_violation": SimulationScenario.BORDER_VIOLATION,
    "border": SimulationScenario.BORDER_VIOLATION,
    "violation": SimulationScenario.BORDER_VIOLATION,
}

# Module-global override (set_mock_scenario). Env ORCA_SCENARIO is fallback.
_CURRENT_SCENARIO: SimulationScenario = SimulationScenario.NORMAL


def set_mock_scenario(scenario: SimulationScenario | str) -> SimulationScenario:
    """Set the global mock scenario controller. Returns the resolved enum."""
    global _CURRENT_SCENARIO
    _CURRENT_SCENARIO = coerce_scenario(scenario, default=SimulationScenario.NORMAL)
    return _CURRENT_SCENARIO


def get_mock_scenario() -> SimulationScenario:
    """Return the current global mock scenario (default NORMAL)."""
    return _CURRENT_SCENARIO


def coerce_scenario(
    scenario: SimulationScenario | str | None,
    default: SimulationScenario | None = None,
) -> SimulationScenario:
    """Coerce a string/enum/None into a SimulationScenario.

    Unrecognized strings fall back to ``default`` (or NORMAL) with a
    ``warnings.warn`` so silent typos never go unnoticed.
    """
    if isinstance(scenario, SimulationScenario):
        return scenario
    if isinstance(scenario, str):
        key = scenario.strip().lower().replace("-", "_").replace(" ", "_")
        if key in _SCENARIO_ALIASES:
            return _SCENARIO_ALIASES[key]
        # Try enum value directly
        for member in SimulationScenario:
            if member.value == key:
                return member
        # Unrecognized string — warn on fallback (no silent bogus -> NORMAL).
        fallback = default if default is not None else SimulationScenario.NORMAL
        warnings.warn(
            f"Unrecognized scenario {scenario!r} — falling back to {fallback.value!r}.",
            stacklevel=3,
        )
        return fallback
    if default is not None:
        return default
    return SimulationScenario.NORMAL


def _is_unrecognized_scenario_input(scenario: SimulationScenario | str | None) -> bool:
    """True when ``scenario`` is a string that maps to no known scenario."""
    if scenario is None or isinstance(scenario, SimulationScenario):
        return False
    if not isinstance(scenario, str):
        return True
    key = scenario.strip().lower().replace("-", "_").replace(" ", "_")
    if key in _SCENARIO_ALIASES:
        return False
    return not any(member.value == key for member in SimulationScenario)


def resolve_scenario(scenario: SimulationScenario | str | None = None) -> SimulationScenario:
    """Resolve effective scenario: explicit arg > global > ORCA_SCENARIO env > NORMAL.

    ``coerce_scenario`` never raises — unrecognized strings warn and fall
    back (no dead try/except).
    """
    if scenario is not None:
        return coerce_scenario(scenario, default=_CURRENT_SCENARIO)
    env = os.getenv("ORCA_SCENARIO", "").strip()
    if env:
        return coerce_scenario(env, default=_CURRENT_SCENARIO)
    return _CURRENT_SCENARIO


# ---------------------------------------------------------------------------
# Data-source flag: ORCA_DATA_SOURCE=mock|live
# ---------------------------------------------------------------------------

_PLACEHOLDER_VALUES = {"", "your_session_id_here", "your_api_key_here", "changeme", "placeholder"}


def _is_missing(value: str | None) -> bool:
    if value is None:
        return True
    v = value.strip()
    if not v:
        return True
    return v.lower() in _PLACEHOLDER_VALUES


def get_data_source() -> str:
    """Return 'mock' or 'live'.

    Fail-safe: defaults to 'mock' unless ORCA_DATA_SOURCE is exactly
    'live' (case-insensitive). Empty/unset/'auto'/typos never silently
    go live — even when DATABASE_URL + INCOIS_JSESSIONID are present.
    """
    explicit = os.getenv("ORCA_DATA_SOURCE", "").strip().lower()
    if explicit == "live":
        return "live"
    return "mock"


def is_mock_mode() -> bool:
    """True when get_data_source() == 'mock'."""
    return get_data_source() == "mock"


def should_use_mock() -> bool:
    """Alias for is_mock_mode (pluggable switch for routers/agents)."""
    return is_mock_mode()


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

_SECTOR_NAMES: dict[str, str] = {
    "SEC001": "GUJARAT",
    "SEC002": "MAHARASHTRA",
    "SEC003": "GOA",
    "SEC004": "KARNATAKA",
    "SEC005": "KERALA",
    "SEC006": "TAMILNADU_WEST",
    "SEC007": "TAMILNADU_EAST",
    "SEC008": "ANDHRA",
    "SEC009": "ODISHA",
    "SEC010": "WESTBENGAL",
    "SEC011": "ANDAMAN",
    "SEC012": "NICOBAR",
    "SEC013": "LAKSHADWEEP",
    "SEC014": "LAKSHADWEEP",
}

_PLACE_POOL = [
    "Pallithottam", "Mampally", "Vypin Bank", "Munambam", "Chellanam",
    "Fort Kochi", "Kannur Bank", "Kollam Outer", "Vizhinjam", "Poonmani",
    "Muttom Bank", "Colachel", "Tuticorin Outer", "Rameswaram Bank",
    "Nagapattinam", "Karaikal", "Chennai Outer", "Pulicat Bank",
]

_COMPASS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_COMPASS_DEG = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}

_DEPTH_BANDS = ["20-30", "30-40", "40-50", "55-60", "60-70"]

_CYCLONE_NAMES = ["Asna", "Tauktae", "Biparjoy", "Remal"]


def _stable_int(seed: str) -> int:
    try:
        digest = hashlib.md5(seed.encode("utf-8"), usedforsecurity=False).hexdigest()
    except TypeError:
        # Python < 3.9: hashlib.md5 has no usedforsecurity kwarg
        digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _coords_valid(lat: float | None, lon: float | None) -> bool:
    """Fail-safe GPS check: not None, finite, lat in [-90,90], lon in [-180,180]."""
    if lat is None or lon is None:
        return False
    try:
        flat = float(lat)
        flon = float(lon)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(flat) or not math.isfinite(flon):
        return False
    return -90.0 <= flat <= 90.0 and -180.0 <= flon <= 180.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km (haversine)."""
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(math.sqrt(a))


def _bearing_to_compass(bearing: int) -> str:
    return _COMPASS_8[int(((bearing % 360) + 22.5) // 45) % 8]


def _dest_point(lat: float, lon: float, bearing_deg: float, distance_km: float) -> tuple[float, float]:
    """Destination point from (lat, lon) along bearing for distance_km (spherical)."""
    r = 6371.0088
    br = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    d = distance_km / r
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(br))
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return round(math.degrees(lat2), 5), round(math.degrees(lon2), 5)


def _extract_point(point: dict, idx: int) -> tuple[str, float | None, float | None, str]:
    """Extract (zone_id, lat, lon, place) from flat or GeoJSON point shapes."""
    zone_id: str | None = None
    place: str | None = None
    lat: float | None = None
    lon: float | None = None

    props = point.get("properties") if isinstance(point.get("properties"), dict) else None
    source = props if props is not None else point
    zone_id = source.get("zone_id") or point.get("zone_id") or point.get("id")
    place = source.get("place") or point.get("place") or source.get("name") or ""

    geom = point.get("geometry")
    if isinstance(geom, dict):
        coords = geom.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lon = float(coords[0])
                lat = float(coords[1])
            except (TypeError, ValueError):
                pass

    if lat is None:
        for k in ("lat", "latitude", "y"):
            if point.get(k) is not None:
                try:
                    lat = float(point[k])
                    break
                except (TypeError, ValueError):
                    continue
        if lat is None and props is not None:
            for k in ("lat", "latitude"):
                if props.get(k) is not None:
                    try:
                        lat = float(props[k])
                        break
                    except (TypeError, ValueError):
                        continue

    if lon is None:
        for k in ("lon", "lng", "longitude", "x"):
            if point.get(k) is not None:
                try:
                    lon = float(point[k])
                    break
                except (TypeError, ValueError):
                    continue
        if lon is None and props is not None:
            for k in ("lon", "lng", "longitude"):
                if props.get(k) is not None:
                    try:
                        lon = float(props[k])
                        break
                    except (TypeError, ValueError):
                        continue

    if zone_id is None:
        safe_place = str(place).replace(" ", "_") if place else f"zone_{idx}"
        zone_id = f"SEC000_{safe_place}_{idx}"

    return str(zone_id), lat, lon, str(place) if place else ""


def _classify_wave(wave_m: float) -> str:
    if wave_m < 1.5:
        return "safe"
    if wave_m <= 2.5:
        return "caution"
    return "danger"


def _classify_current(current_kt: float) -> str:
    if current_kt > 3.0:
        return "danger"
    if current_kt > 2.0:
        return "caution"
    return "safe"


def _classify_wind(wind_kt: float) -> str:
    if wind_kt < 15.0:
        return "safe"
    if wind_kt <= 25.0:
        return "caution"
    return "danger"


def _ist_now_iso() -> str:
    """Current IST time as ISO string.

    Wall-clock helper — excluded from the determinism contract (same
    inputs otherwise give identical outputs; only ``timestamp`` varies).
    """
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(tz=ist).isoformat()


def _ist_today_str() -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(tz=ist).strftime("%d-%b-%Y")


# ---------------------------------------------------------------------------
# 1. INCOIS PFZ mock — 7-column features
# ---------------------------------------------------------------------------


def mock_fetch_incois_pfz(
    sector: str = "SEC005",
    center_lat: float = 9.93,
    center_lon: float = 76.26,
    count: int = 5,
    scenario: SimulationScenario | str | None = None,
) -> dict:
    """Generate deterministic mock INCOIS PFZ features.

    Args:
        sector: INCOIS sector code (e.g. 'SEC005'). Unknown codes are
            upper-cased as-is; human names map to KERALA sector name.
        center_lat: Latitude to distribute mock zones around.
        center_lon: Longitude to distribute mock zones around.
        count: Number of features to generate (>=0).
        scenario: Reserved for future PFZ variation; currently PFZ
            geometry is scenario-independent (safety varies in OSF/IMD/
            geofence layers). Accepted and echoed for API uniformity.

    Returns:
        dict with {status, summary, next_actions, artifacts, features,
        feature_collection, count, sector, sector_name, scenario, source,
        timestamp}. ``features`` is a list of GeoJSON Point Features with
        7-column PFZ properties: place, direction, bearing, depth,
        distance, latitude, longitude (plus zone_id/sector/source).
        Deterministic: same inputs -> identical outputs, excluding the
        wall-clock ``timestamp`` field (see _ist_now_iso).
    """
    sc = resolve_scenario(scenario)
    scenario_warned = _is_unrecognized_scenario_input(scenario)
    sector_code = (sector or "SEC005").strip().upper()
    sector_name = _SECTOR_NAMES.get(sector_code, sector_code)
    try:
        n = max(0, int(count))
    except (TypeError, ValueError):
        n = 5
    try:
        clat = float(center_lat)
        clon = float(center_lon)
    except (TypeError, ValueError):
        clat, clon = 9.93, 76.26

    base = _stable_int(f"pfz:{sector_code}:{clat}:{clon}")
    timestamp = _ist_now_iso()
    features: list[dict] = []
    for i in range(n):
        h = _stable_int(f"pfz:{sector_code}:{clat}:{clon}:{i}")
        bearing = (base + i * 47 + (h % 360)) % 360
        direction = _bearing_to_compass(bearing)
        depth = _DEPTH_BANDS[(h // 7) % len(_DEPTH_BANDS)]
        # Realistic offshore distance 5.0-60.0 km so 80km radius finds them
        distance_km = round(5.0 + ((h // 13) % 550) / 10.0, 1)
        dist_range = f"{distance_km:.0f}-{distance_km + 5:.0f}"
        place = _PLACE_POOL[(base + i * 3 + (h % len(_PLACE_POOL))) % len(_PLACE_POOL)]
        zone_id = f"{sector_code}_{place.replace(' ', '')}_{i + 1:03d}"
        plat, plon = _dest_point(clat, clon, float(bearing), distance_km)
        intensity = ["low", "medium", "high"][(h // 29) % 3]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "zone_id": zone_id,
                    "place": place,
                    "direction": direction,
                    "bearing": int(bearing),
                    "depth": depth,
                    "distance": dist_range,
                    "distance_km": distance_km,
                    "latitude": plat,
                    "longitude": plon,
                    "lat": plat,
                    "lon": plon,
                    "sector": sector_code,
                    "sector_name": sector_name,
                    "intensity": intensity,
                    "source": "mock_incois",
                    "timestamp": timestamp,
                },
                "geometry": {"type": "Point", "coordinates": [plon, plat]},
            }
        )

    next_actions = ["pass features to safety sub-agents", "call combiner"]
    summary = f"Mock INCOIS PFZ: {n} zones for {sector_code} ({sector_name}) around ({clat},{clon})"
    if scenario_warned:
        summary += f" [warning: unrecognized scenario {scenario!r}, fell back to {sc.value!r}]"
        next_actions = next_actions + [f"check scenario spelling — {scenario!r} unrecognized, used {sc.value!r}"]
    return {
        "status": "success",
        "summary": summary,
        "next_actions": next_actions,
        "artifacts": ["data/pfz-today.geojson"],
        "features": features,
        "feature_collection": {"type": "FeatureCollection", "features": features},
        "count": n,
        "sector": sector_code,
        "sector_name": sector_name,
        "scenario": sc.value,
        "source": "mock_incois",
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# 2. OSF ocean-state mock — waves 0.7-4.0m, currents 0.5-4.0kt (SWAN)
# ---------------------------------------------------------------------------


def mock_fetch_osf_ocean_state(
    points: list[dict],
    scenario: SimulationScenario | str | None = None,
) -> dict:
    """Generate deterministic mock OSF wave/current per point.

    Fail-safe: unknown/invalid points (non-dict, missing coords, or
    out-of-range lat/lon) return ``danger`` (never ``safe``) with a
    reason asking for valid GPS. No safe PFZ values are fabricated for
    unknown locations.

    Args:
        points: Shared candidate points (flat {zone_id,place,lat,lon} or
            GeoJSON Features). Order is preserved in ``results``.
        scenario: NORMAL (0.7-1.4m/0.5-1.8kt) | ROUGH_SEAS (2.6-4.0m/
            2.5-4.0kt) | CYCLONE_WARNING (2.0-3.5m/2.0-3.5kt + surge flag)
            | BORDER_VIOLATION (same as NORMAL).

    Returns:
        dict with {status, summary, next_actions, artifacts, results,
        scenario, source, metadata}. Each result matches
        sea_checker.check_sea_conditions item shape:
        {zone_id, place, lat, lon, wave_height_m, current_kt,
        wave_status, current_status, status, reason, source}.
        ``metadata`` carries SWAN simulation info
        {model:'SWAN', cycle:'06Z', grid:'0.05deg', storm_surge: bool}.
        Deterministic excluding wall-clock ``metadata.timestamp``.
    """
    sc = resolve_scenario(scenario)
    scenario_warned = _is_unrecognized_scenario_input(scenario)
    points = points or []
    results: list[dict] = []
    has_invalid = False

    for idx, pt in enumerate(points):
        if not isinstance(pt, dict):
            has_invalid = True
            results.append(
                {
                    "zone_id": f"unknown_{idx}",
                    "place": "",
                    "lat": None,
                    "lon": None,
                    "wave_height_m": 0.0,
                    "current_kt": 0.0,
                    "wave_status": "danger",
                    "current_status": "danger",
                    "status": "danger",
                    "reason": "invalid point (non-dict) — unknown location treated as danger; provide valid GPS lat/lon",
                    "source": "mock_osf",
                }
            )
            continue
        zone_id, lat, lon, place = _extract_point(pt, idx)
        if not _coords_valid(lat, lon):
            has_invalid = True
            results.append(
                {
                    "zone_id": zone_id,
                    "place": place,
                    "lat": lat,
                    "lon": lon,
                    "wave_height_m": 0.0,
                    "current_kt": 0.0,
                    "wave_status": "danger",
                    "current_status": "danger",
                    "status": "danger",
                    "reason": (
                        f"invalid GPS lat={lat} lon={lon} (missing/out-of-range) — "
                        "unknown location treated as danger; provide valid GPS lat/lon"
                    ),
                    "source": "mock_osf",
                }
            )
            continue
        hw = _stable_int(f"osf-wave:{zone_id}:{lat}:{lon}:{idx}:{sc.value}")
        hc = _stable_int(f"osf-current:{zone_id}:{lat}:{lon}:{idx}:{sc.value}")

        if sc == SimulationScenario.ROUGH_SEAS:
            wave = round(2.6 + (hw % 141) / 100.0, 2)  # 2.60-4.00
            current = round(2.5 + (hc % 151) / 100.0, 2)  # 2.50-4.00
        elif sc == SimulationScenario.CYCLONE_WARNING:
            wave = round(2.0 + (hw % 151) / 100.0, 2)  # 2.00-3.50
            current = round(2.0 + (hc % 151) / 100.0, 2)  # 2.00-3.50
        else:  # NORMAL / BORDER_VIOLATION — calm seas
            wave = round(0.7 + (hw % 71) / 100.0, 2)  # 0.70-1.40
            current = round(0.5 + (hc % 131) / 100.0, 2)  # 0.50-1.80

        wave_status = _classify_wave(wave)
        current_status = _classify_current(current)
        rank = {"safe": 0, "caution": 1, "danger": 2}
        status = wave_status if rank[wave_status] >= rank[current_status] else current_status
        if status == "danger":
            if current_status == "danger" and wave_status == "danger":
                reason = f"wave {wave}m danger + current {current}kt danger"
            elif current_status == "danger":
                reason = f"current {current}kt danger (>3kt)"
            else:
                reason = f"wave {wave}m danger (>2.5m)"
        elif status == "caution":
            if current_status == "caution" and wave_status == "caution":
                reason = f"wave {wave}m caution + current {current}kt caution"
            elif current_status == "caution":
                reason = f"current {current}kt caution (>2kt)"
            else:
                reason = f"wave {wave}m caution (1.5-2.5m)"
        else:
            reason = f"wave {wave}m safe, current {current}kt safe"

        results.append(
            {
                "zone_id": zone_id,
                "place": place,
                "lat": lat,
                "lon": lon,
                "wave_height_m": wave,
                "current_kt": current,
                "wave_status": wave_status,
                "current_status": current_status,
                "status": status,
                "reason": reason,
                "source": "mock_osf",
            }
        )

    metadata = {
        "model": "SWAN",
        "cycle": "06Z",
        "grid": "0.05deg",
        "source": "mock_osf",
        "scenario": sc.value,
        "storm_surge": sc == SimulationScenario.CYCLONE_WARNING,
        "timestamp": _ist_now_iso(),
    }
    summary = f"Mock OSF ocean state ({sc.value}): {len(results)} points, SWAN 06Z"
    next_actions: list[str] = ["call combiner", "use wave/current status for badge"]
    if has_invalid:
        summary += " [warning: invalid GPS points treated as danger]"
        next_actions = next_actions + ["provide valid GPS lat/lon for invalid points"]
    if scenario_warned:
        summary += f" [warning: unrecognized scenario {scenario!r}, fell back to {sc.value!r}]"
        next_actions = next_actions + [f"check scenario spelling — {scenario!r} unrecognized, used {sc.value!r}"]
    return {
        "status": "success",
        "summary": summary,
        "next_actions": next_actions,
        "artifacts": [],
        "results": results,
        "count": len(results),
        "scenario": sc.value,
        "source": "mock_osf",
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# 3. IMD marine-weather mock — winds 7-35kt + 500km cyclone circles
# ---------------------------------------------------------------------------


def _cyclone_circle(lat: float, lon: float, radius_km: float = 500.0, steps: int = 32) -> list[list[float]]:
    """Approximate 500km buffer circle as GeoJSON LinearRing [lon, lat]."""
    ring: list[list[float]] = []
    for s in range(steps):
        br = 360.0 * s / steps
        clat, clon = _dest_point(lat, lon, br, radius_km)
        ring.append([clon, clat])
    ring.append(ring[0])
    return ring


def mock_fetch_imd_marine_weather(
    points: list[dict],
    scenario: SimulationScenario | str | None = None,
) -> dict:
    """Generate deterministic mock IMD wind + cyclone alerts per point.

    Fail-safe: unknown/invalid points (non-dict, missing coords, or
    out-of-range lat/lon) return ``danger`` (never ``safe``) with a
    reason asking for valid GPS. No safe wind values are fabricated for
    unknown locations.

    Cyclones: a single shared cyclone center is computed per batch call
    (anchored on the first valid point); every valid point in
    CYCLONE_WARNING references that same center, and ``cyclones`` exposes
    exactly that center so per-point ``nearest_cyclone_km`` matches the
    listed entry.

    Args:
        points: Shared candidate points (flat or GeoJSON). Order preserved.
        scenario: NORMAL (7-14kt, no cyclone) | ROUGH_SEAS (16-24kt,
            no cyclone) | CYCLONE_WARNING (28-35kt + ACTIVE cyclone
            within 500km, 500km buffer circle) | BORDER_VIOLATION
            (same as NORMAL).

    Returns:
        dict with {status, summary, next_actions, artifacts, results,
        cyclones, scenario, source, metadata}. Each result matches
        weather_agent.check_weather item shape plus ``cyclone_alert``,
        ``nearest_cyclone_km``, ``cyclone_name``. ``cyclones`` lists
        active warnings with {name, center:[lat,lon], distance_km,
        severity, buffer_km:500, circle: GeoJSON Feature}.
        Deterministic excluding wall-clock ``metadata.timestamp``.
    """
    sc = resolve_scenario(scenario)
    scenario_warned = _is_unrecognized_scenario_input(scenario)
    points = points or []

    # Deterministic cyclone anchor per batch (same for all points in call)
    batch_seed = _stable_int(f"imd-batch:{len(points)}:{sc.value}")
    cyclone_name = _CYCLONE_NAMES[batch_seed % len(_CYCLONE_NAMES)]

    results: list[dict] = []
    cyclones: list[dict] = []
    has_invalid = False

    # Anchor the single shared cyclone center on the first valid point so
    # all per-point nearest distances reference the same center.
    anchor_lat: float | None = None
    anchor_lon: float | None = None
    if sc == SimulationScenario.CYCLONE_WARNING:
        for pt in points:
            if isinstance(pt, dict):
                _, alat, alon, _ = _extract_point(pt, 0)
                if alat is not None and alon is not None and _coords_valid(alat, alon):
                    anchor_lat, anchor_lon = float(alat), float(alon)
                    break
    shared_cyc: tuple[float, float] | None = None
    shared_dist: float | None = None
    if sc == SimulationScenario.CYCLONE_WARNING and anchor_lat is not None and anchor_lon is not None:
        hc_shared = _stable_int(f"imd-cyc-shared:{batch_seed}:{anchor_lat}:{anchor_lon}")
        shared_dist = round(80.0 + (hc_shared % 2201) / 10.0, 1)  # 80.0-300.0
        brg_shared = (hc_shared // 7) % 360
        cyc_lat, cyc_lon = _dest_point(anchor_lat, anchor_lon, float(brg_shared), shared_dist)
        shared_cyc = (cyc_lat, cyc_lon)
        cyclones.append(
            {
                "name": cyclone_name,
                "center": [cyc_lat, cyc_lon],
                "distance_km": shared_dist,
                "severity": "danger",
                "buffer_km": 500,
                "circle": {
                    "type": "Feature",
                    "properties": {"name": cyclone_name, "buffer_km": 500},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [_cyclone_circle(cyc_lat, cyc_lon, 500.0)],
                    },
                },
            }
        )

    for idx, pt in enumerate(points):
        if not isinstance(pt, dict):
            has_invalid = True
            results.append(
                {
                    "zone_id": f"unknown_{idx}",
                    "place": "",
                    "lat": None,
                    "lon": None,
                    "wind_kt": 0.0,
                    "wind_speed_kt": 0.0,
                    "wind_dir": "N",
                    "wind_direction": "N",
                    "wind_deg": 0,
                    "wind_status": "danger",
                    "cyclone_alert": False,
                    "nearest_cyclone_km": None,
                    "cyclone_name": None,
                    "status": "danger",
                    "reason": "invalid point (non-dict) — unknown location treated as danger; provide valid GPS lat/lon",
                    "source": "mock_imd",
                }
            )
            continue
        zone_id, lat, lon, place = _extract_point(pt, idx)
        if not _coords_valid(lat, lon):
            has_invalid = True
            results.append(
                {
                    "zone_id": zone_id,
                    "place": place,
                    "lat": lat,
                    "lon": lon,
                    "wind_kt": 0.0,
                    "wind_speed_kt": 0.0,
                    "wind_dir": "N",
                    "wind_direction": "N",
                    "wind_deg": 0,
                    "wind_status": "danger",
                    "cyclone_alert": False,
                    "nearest_cyclone_km": None,
                    "cyclone_name": None,
                    "status": "danger",
                    "reason": (
                        f"invalid GPS lat={lat} lon={lon} (missing/out-of-range) — "
                        "unknown location treated as danger; provide valid GPS lat/lon"
                    ),
                    "source": "mock_imd",
                }
            )
            continue
        hw = _stable_int(f"imd-wind:{zone_id}:{lat}:{lon}:{idx}:{sc.value}")
        hd = _stable_int(f"imd-wdir:{zone_id}:{lat}:{lon}:{idx}:{sc.value}")

        if sc == SimulationScenario.ROUGH_SEAS:
            wind = round(16.0 + (hw % 81) / 10.0, 1)  # 16.0-24.0 caution
        elif sc == SimulationScenario.CYCLONE_WARNING:
            wind = round(28.0 + (hw % 71) / 10.0, 1)  # 28.0-35.0 danger
        else:  # NORMAL / BORDER_VIOLATION
            wind = round(7.0 + (hw % 71) / 10.0, 1)  # 7.0-14.0 safe

        wind_dir = _COMPASS_8[hd % len(_COMPASS_8)]
        wind_deg = _COMPASS_DEG[wind_dir]
        wind_status = _classify_wind(wind)

        cyclone_alert = False
        nearest_km: float | None = None
        cname: str | None = None
        if sc == SimulationScenario.CYCLONE_WARNING and shared_cyc is not None:
            # All valid points reference the single shared batch center so
            # cyclones[] matches per-point nearest.
            assert lat is not None and lon is not None  # narrowed by _coords_valid above
            nearest_km = round(_haversine_km(float(lat), float(lon), shared_cyc[0], shared_cyc[1]), 1)
            cyclone_alert = True
            cname = cyclone_name

        status = "danger" if cyclone_alert else wind_status
        if cyclone_alert:
            reason = f"cyclone {cname or 'alert'} nearest {nearest_km}km (shared 500km buffer) -> danger"
        elif status == "danger":
            reason = f"wind {wind}kt danger (>25kt) dir {wind_dir}"
        elif status == "caution":
            reason = f"wind {wind}kt caution (15-25kt) dir {wind_dir}"
        else:
            reason = f"wind {wind}kt safe dir {wind_dir}"

        results.append(
            {
                "zone_id": zone_id,
                "place": place,
                "lat": lat,
                "lon": lon,
                "wind_kt": wind,
                "wind_speed_kt": wind,
                "wind_dir": wind_dir,
                "wind_direction": wind_dir,
                "wind_deg": wind_deg,
                "wind_status": wind_status,
                "cyclone_alert": cyclone_alert,
                "nearest_cyclone_km": nearest_km,
                "cyclone_name": cname,
                "status": status,
                "reason": reason,
                "source": "mock_imd",
            }
        )

    if sc == SimulationScenario.CYCLONE_WARNING and not cyclones and results:
        # Fallback single cyclone entry when points list had no valid coords
        cyclones.append(
            {
                "name": cyclone_name,
                "center": [10.5, 74.5],
                "distance_km": 150.0,
                "severity": "danger",
                "buffer_km": 500,
                "circle": {
                    "type": "Feature",
                    "properties": {"name": cyclone_name, "buffer_km": 500},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [_cyclone_circle(10.5, 74.5, 500.0)],
                    },
                },
            }
        )

    summary = (
        f"Mock IMD marine weather ({sc.value}): {len(results)} points, "
        + ("CYCLONE ACTIVE 500km buffer" if sc == SimulationScenario.CYCLONE_WARNING else "no cyclone")
    )
    next_actions: list[str] = ["call combiner", "use wind/cyclone status for badge"]
    if has_invalid:
        summary += " [warning: invalid GPS points treated as danger]"
        next_actions = next_actions + ["provide valid GPS lat/lon for invalid points"]
    if scenario_warned:
        summary += f" [warning: unrecognized scenario {scenario!r}, fell back to {sc.value!r}]"
        next_actions = next_actions + [f"check scenario spelling — {scenario!r} unrecognized, used {sc.value!r}"]
    return {
        "status": "success",
        "summary": summary,
        "next_actions": next_actions,
        "artifacts": [],
        "results": results,
        "cyclones": cyclones,
        "count": len(results),
        "scenario": sc.value,
        "source": "mock_imd",
        "metadata": {
            "provider": "IMD mausam",
            "cyclone_radius_km": 500.0,
            "scenario": sc.value,
            "timestamp": _ist_now_iso(),
        },
    }


# ---------------------------------------------------------------------------
# 4. Geofence mock — EEZ containment, MPA bans, 2km IMBL buffers
# ---------------------------------------------------------------------------


def mock_check_geofence_boundaries(
    points: list[dict],
    scenario: SimulationScenario | str | None = None,
) -> dict:
    """Validate mock EEZ/MPA/IMBL geofences per point.

    Fail-safe: unknown/invalid points (non-dict, missing coords, or
    out-of-range lat/lon) return ``danger``/restricted (never ``safe``)
    with a warning asking for valid GPS.

    Args:
        points: Shared candidate points (flat or GeoJSON). Order preserved.
        scenario: NORMAL/ROUGH_SEAS/CYCLONE_WARNING (inside EEZ, outside
            MPA, IMBL 8-25km -> safe) | BORDER_VIOLATION (rotating
            violations: i%3==0 inside MPA danger, i%3==1 within 2km IMBL
            caution, i%3==2 outside EEZ danger).

    Returns:
        dict with {status, summary, next_actions, artifacts, results,
        scenario, source}. Each result matches POST /api/geofence/check
        plus agent fields: {lat, lon, inside_eez, inside_mpa, mpa_name,
        eez_country, nearest_mpa, distance_to_mpa_km, near_imbl,
        distance_to_imbl_km, restricted, status, warnings, is_safe}.
    """
    sc = resolve_scenario(scenario)
    scenario_warned = _is_unrecognized_scenario_input(scenario)
    points = points or []
    results: list[dict] = []
    has_invalid = False

    for idx, pt in enumerate(points):
        if not isinstance(pt, dict):
            has_invalid = True
            results.append(
                {
                    "lat": None,
                    "lon": None,
                    "inside_eez": False,
                    "inside_mpa": False,
                    "mpa_name": None,
                    "eez_country": "India",
                    "nearest_mpa": None,
                    "distance_to_mpa_km": None,
                    "near_imbl": False,
                    "distance_to_imbl_km": None,
                    "restricted": True,
                    "status": "danger",
                    "warnings": ["Invalid point — missing lat/lon; provide valid GPS lat/lon"],
                    "is_safe": False,
                    "source": "mock_geofence",
                }
            )
            continue
        zone_id, lat, lon, place = _extract_point(pt, idx)
        if not _coords_valid(lat, lon):
            has_invalid = True
            results.append(
                {
                    "zone_id": zone_id,
                    "place": place,
                    "lat": lat,
                    "lon": lon,
                    "inside_eez": False,
                    "inside_mpa": False,
                    "mpa_name": None,
                    "eez_country": "India",
                    "nearest_mpa": None,
                    "distance_to_mpa_km": None,
                    "near_imbl": False,
                    "distance_to_imbl_km": None,
                    "restricted": True,
                    "status": "danger",
                    "warnings": [
                        f"Invalid GPS lat={lat} lon={lon} (missing/out-of-range) — treated as restricted; provide valid GPS lat/lon"
                    ],
                    "is_safe": False,
                    "source": "mock_geofence",
                }
            )
            continue
        h = _stable_int(f"geofence:{zone_id}:{lat}:{lon}:{idx}:{sc.value}")

        if sc == SimulationScenario.BORDER_VIOLATION:
            mode = idx % 3
            if mode == 0:
                # Inside MPA — strictly banned
                mpa_name = "Vembanad MPA" if idx % 2 == 0 else "Gulf of Mannar MPA"
                results.append(
                    {
                        "zone_id": zone_id,
                        "place": place,
                        "lat": lat,
                        "lon": lon,
                        "inside_eez": True,
                        "inside_mpa": True,
                        "mpa_name": mpa_name,
                        "eez_country": "India",
                        "nearest_mpa": mpa_name,
                        "distance_to_mpa_km": 0.0,
                        "near_imbl": False,
                        "distance_to_imbl_km": round(8.0 + (h % 100) / 10.0, 1),
                        "restricted": True,
                        "status": "danger",
                        "warnings": [f"Inside Marine Protected Area: {mpa_name} — fishing strictly banned"],
                        "is_safe": False,
                        "source": "mock_geofence",
                    }
                )
            elif mode == 1:
                # Within 2km IMBL buffer — caution
                dist_imbl = round(0.5 + (h % 15) / 10.0, 1)  # 0.5-1.9
                results.append(
                    {
                        "zone_id": zone_id,
                        "place": place,
                        "lat": lat,
                        "lon": lon,
                        "inside_eez": True,
                        "inside_mpa": False,
                        "mpa_name": None,
                        "eez_country": "India",
                        "nearest_mpa": None,
                        "distance_to_mpa_km": round(10.0 + (h % 100) / 10.0, 1),
                        "near_imbl": True,
                        "distance_to_imbl_km": dist_imbl,
                        "distance_to_imbl": dist_imbl,
                        "restricted": False,
                        "status": "caution",
                        "warnings": [
                            f"Within 2km of International Maritime Boundary Line — risk of crossing ({dist_imbl:.1f}km to boundary)"
                        ],
                        "is_safe": False,
                        "source": "mock_geofence",
                    }
                )
            else:
                # Outside EEZ — danger
                results.append(
                    {
                        "zone_id": zone_id,
                        "place": place,
                        "lat": lat,
                        "lon": lon,
                        "inside_eez": False,
                        "inside_mpa": False,
                        "mpa_name": None,
                        "eez_country": "India",
                        "nearest_mpa": None,
                        "distance_to_mpa_km": round(15.0 + (h % 100) / 10.0, 1),
                        "near_imbl": False,
                        "distance_to_imbl_km": round(5.0 + (h % 50) / 10.0, 1),
                        "restricted": True,
                        "status": "danger",
                        "warnings": ["Outside Indian Exclusive Economic Zone — fishing not permitted"],
                        "is_safe": False,
                        "source": "mock_geofence",
                    }
                )
        else:
            # NORMAL / ROUGH_SEAS / CYCLONE_WARNING — calm legal waters
            dist_imbl = round(8.0 + (h % 171) / 10.0, 1)  # 8.0-25.0
            results.append(
                {
                    "zone_id": zone_id,
                    "place": place,
                    "lat": lat,
                    "lon": lon,
                    "inside_eez": True,
                    "inside_mpa": False,
                    "mpa_name": None,
                    "eez_country": "India",
                    "nearest_mpa": None,
                    "distance_to_mpa_km": round(12.0 + (h % 150) / 10.0, 1),
                    "near_imbl": False,
                    "distance_to_imbl_km": dist_imbl,
                    "distance_to_imbl": dist_imbl,
                    "restricted": False,
                    "status": "safe",
                    "warnings": [],
                    "is_safe": True,
                    "source": "mock_geofence",
                }
            )

    n_restricted = sum(1 for r in results if r.get("restricted"))
    summary = f"Mock geofence ({sc.value}): {len(results)} points, {n_restricted} restricted"
    next_actions: list[str] = ["call combiner", "apply hard veto if restricted"]
    if has_invalid:
        summary += " [warning: invalid GPS points treated as danger]"
        next_actions = next_actions + ["provide valid GPS lat/lon for invalid points"]
    if scenario_warned:
        summary += f" [warning: unrecognized scenario {scenario!r}, fell back to {sc.value!r}]"
        next_actions = next_actions + [f"check scenario spelling — {scenario!r} unrecognized, used {sc.value!r}"]
    return {
        "status": "success",
        "summary": summary,
        "next_actions": next_actions,
        "artifacts": ["data/eez.geojson", "data/mpa.geojson"],
        "results": results,
        "count": len(results),
        "restricted_count": n_restricted,
        "scenario": sc.value,
        "source": "mock_geofence",
    }


# ---------------------------------------------------------------------------
# Convenience: run the full mock pipeline for one query
# ---------------------------------------------------------------------------


def mock_fetch_all(
    sector: str = "SEC005",
    center_lat: float = 9.93,
    center_lon: float = 76.26,
    count: int = 5,
    scenario: SimulationScenario | str | None = None,
) -> dict:
    """Run PFZ + OSF + IMD + geofence mocks on shared coordinates.

    Returns envelope {status, summary, next_actions, artifacts, pfz,
    ocean, weather, geofence, scenario, source}. The same PFZ ``features``
    are passed concurrently to the three safety mocks (shared-candidate
    invariant per map #22). Deterministic excluding wall-clock
    ``timestamp``.
    """
    sc = resolve_scenario(scenario)
    pfz = mock_fetch_incois_pfz(sector, center_lat, center_lon, count, sc)
    shared = pfz["features"]
    ocean = mock_fetch_osf_ocean_state(shared, sc)
    weather = mock_fetch_imd_marine_weather(shared, sc)
    geofence = mock_check_geofence_boundaries(shared, sc)
    return {
        "status": "success",
        "summary": f"Mock pipeline ({sc.value}): {pfz['count']} PFZ + ocean/weather/geofence",
        "next_actions": ["call combiner", "stream SSE map->safety->tokens->evidence->done"],
        "artifacts": ["data/eez.geojson", "data/mpa.geojson", "data/pfz-today.geojson"],
        "pfz": pfz,
        "ocean": ocean,
        "weather": weather,
        "geofence": geofence,
        "scenario": sc.value,
        "source": "mock",
        "timestamp": _ist_now_iso(),
    }


__all__ = [
    "SimulationScenario",
    "set_mock_scenario",
    "get_mock_scenario",
    "coerce_scenario",
    "resolve_scenario",
    "get_data_source",
    "is_mock_mode",
    "should_use_mock",
    "mock_fetch_incois_pfz",
    "mock_fetch_osf_ocean_state",
    "mock_fetch_imd_marine_weather",
    "mock_check_geofence_boundaries",
    "mock_fetch_all",
]
