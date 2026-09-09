"""
Sea Checker Agent — Wave and Current Conditions

Owner: M-A (Agents & Orchestration) — wave/current check
Module: backend/agents/sea_checker.py

The Sea Checker agent evaluates ocean conditions at PFZ zone coordinates.
It reports wave height and current speed to determine if a zone is safe
for small fishing vessels.

Data Sources:
    - W1 (Mock): Deterministic heuristic per point (zone_id/lat/lon hash)
    - W2 (Real): OSF/GOFS 06Z forecast data via xarray/Zarr (extensible wrapper)

Safety Thresholds:
    - Wave height < 1.5m -> safe
    - Wave height 1.5-2.5m -> caution
    - Wave height > 2.5m -> danger
    - Current > 2kt -> caution, > 3kt -> danger (overrides wave)

Extensible interface:
    - fetch_osf_wave_current(lat, lon) — W2 real OSF fetcher (stub, raises NotImplemented)
    - _heuristic_wave_height / _heuristic_current — W1 deterministic mock
    - get_wave_current(...) — wrapper that tries OSF then falls back to heuristic
"""

import hashlib
import logging
from pathlib import Path
from typing import Any
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (non-negotiable per ORCA_GeoJSON_Architecture.md + issue #13)
# ---------------------------------------------------------------------------
WAVE_SAFE_MAX = 1.5  # m, exclusive — <1.5 safe
WAVE_CAUTION_MAX = 2.5  # m, inclusive upper for caution — 1.5-2.5 caution, >2.5 danger
CURRENT_CAUTION_KT = 2.0  # >2 caution
CURRENT_DANGER_KT = 3.0  # >3 danger
_SEVERITY_RANK = {"safe": 0, "caution": 1, "danger": 2}


def _classify_wave(wave_m: float) -> str:
    """Classify wave height per spec: <1.5 safe, 1.5-2.5 caution, >2.5 danger."""
    if wave_m < WAVE_SAFE_MAX:
        return "safe"
    if wave_m <= WAVE_CAUTION_MAX:
        return "caution"
    return "danger"


def _classify_current(current_kt: float) -> str:
    """Classify current: <=2 safe, >2 caution, >3 danger."""
    if current_kt > CURRENT_DANGER_KT:
        return "danger"
    if current_kt > CURRENT_CAUTION_KT:
        return "caution"
    return "safe"


def _overall_status(wave_status: str, current_status: str) -> str:
    """Worst of wave/current wins."""
    if _SEVERITY_RANK[wave_status] >= _SEVERITY_RANK[current_status]:
        return wave_status
    return current_status


# ---------------------------------------------------------------------------
# Point normalisation — handle both flat and GeoJSON shapes
# ---------------------------------------------------------------------------

def _extract_point(point: dict, idx: int) -> tuple[str, float | None, float | None, str]:
    """
    Extract (zone_id, lat, lon, place) from diverse point shapes.

    Supports:
      - flat: {zone_id, place, lat, lon}
      - fish_finder normalized: {zone_id, place, lat, lon}
      - GeoJSON Feature: {properties:{zone_id,place}, geometry:{coordinates:[lon,lat]}}
      - mixed: {lat,lon, zone_id} at top-level
    """
    zone_id: str | None = None
    place: str | None = None
    lat: float | None = None
    lon: float | None = None

    # properties / top-level
    props = point.get("properties") if isinstance(point.get("properties"), dict) else None
    source = props if props is not None else point

    zone_id = source.get("zone_id") or point.get("zone_id") or point.get("id")
    place = source.get("place") or point.get("place") or source.get("name") or ""

    # Geometry — GeoJSON [lon, lat]
    geom = point.get("geometry")
    if isinstance(geom, dict):
        coords = geom.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lon = float(coords[0])
                lat = float(coords[1])
            except (TypeError, ValueError):
                pass

    # Flat lat/lon (also fallback if geometry missing)
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
        # Deterministic synthetic id so caller can still join results
        safe_place = str(place).replace(" ", "_") if place else f"zone_{idx}"
        zone_id = f"SEC000_{safe_place}_{idx}"

    return str(zone_id), lat, lon, str(place) if place else ""


# ---------------------------------------------------------------------------
# W1 deterministic heuristic (stable hash — not Python hash())
# ---------------------------------------------------------------------------

def _stable_int(seed: str) -> int:
    """Stable 32-bit int from seed string via MD5."""
    return int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:8], 16)


def _heuristic_wave_height(lat: float | None, lon: float | None, zone_id: str, idx: int) -> float:
    """
    Deterministic mock wave height in [0.3, 3.8] m.

    Distribution is intentionally spread so all three bands are exercised:
      hash % 320 -> 0.30 .. 3.50, plus small lat-offset for plausibility.
    Respects thresholds: values will fall into safe/caution/danger depending on seed.
    """
    # Use zone_id as primary seed for stability; lat/lon add variance if present
    base_seed = f"wave:{zone_id}:{lat}:{lon}:{idx}"
    h = _stable_int(base_seed)
    # 0 .. 319 -> 0.30 .. 3.49
    wave = 0.30 + (h % 320) / 100.0
    # Optional: slight north-south gradient (south slightly calmer) — bounded ±0.15
    if lat is not None:
        wave += ((lat - 10.0) * 0.01)  # near 8N slightly lower, 20N slightly higher
        wave = max(0.2, min(3.8, wave))
    return round(wave, 2)


def _heuristic_current(lat: float | None, lon: float | None, zone_id: str, idx: int) -> float:
    """Deterministic mock current in [0.4, 4.0] kt."""
    base_seed = f"current:{zone_id}:{lat}:{lon}:{idx}"
    h = _stable_int(base_seed)
    # 0 .. 359 -> 0.40 .. 3.99
    current = 0.40 + (h % 360) / 100.0
    return round(current, 2)


# ---------------------------------------------------------------------------
# Tier 3 Fallback: Marine Data Package (coastal_point_features.parquet)
# ---------------------------------------------------------------------------

_PARQUET_COASTAL_CACHE = None

def _find_parquet_features_file() -> Path | None:
    base = Path(__file__).resolve().parents[3]
    candidates = [
        base / "data" / "marine_data_package" / "marine-data" / "unified" / "marine_features" / "coastal_point_features.parquet",
        base / "data" / "coastal_point_features.parquet",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

def _get_coastal_parquet_data():
    global _PARQUET_COASTAL_CACHE
    if _PARQUET_COASTAL_CACHE is not None:
        return _PARQUET_COASTAL_CACHE
    p = _find_parquet_features_file()
    if not p:
        return None
    try:
        import pyarrow.parquet as pq
        tbl = pq.read_table(str(p), columns=["latitude", "longitude", "wave_height_m", "swell_wave_height_m"])
        lats = tbl["latitude"].to_numpy()
        lons = tbl["longitude"].to_numpy()
        waves = tbl["wave_height_m"].to_numpy()
        swells = tbl["swell_wave_height_m"].to_numpy() if "swell_wave_height_m" in tbl.column_names else None
        _PARQUET_COASTAL_CACHE = (lats, lons, waves, swells)
        return _PARQUET_COASTAL_CACHE
    except Exception as exc:
        logger.debug("Failed loading coastal_point_features.parquet: %s", exc)
        return None

def _fetch_parquet_wave_current(lat: float, lon: float) -> tuple[float, float] | None:
    data = _get_coastal_parquet_data()
    if not data:
        return None
    lats, lons, waves, swells = data
    dist_sq = (lats - lat) ** 2 + (lons - lon) ** 2
    idx = int(dist_sq.argmin())
    wave_val = waves[idx]
    wave = float(wave_val) if not (np.isnan(wave_val) if hasattr(wave_val, "dtype") else False) else 1.2
    swell_val = swells[idx] if swells is not None else 1.0
    swell = float(swell_val) if swells is not None and not (np.isnan(swell_val) if hasattr(swell_val, "dtype") else False) else 1.0
    current_kt = round(swell * 0.8, 2)
    return wave, current_kt


# ---------------------------------------------------------------------------
# W2 extensible interface — OSF 06Z forecast
# ---------------------------------------------------------------------------

async def fetch_osf_wave_current(lat: float, lon: float) -> tuple[float, float]:
    """
    Live real data fetcher: Open-Meteo Marine wave & current.
    Returns (wave_height_m, current_kt).
    """
    try:
        from backend.ingest.live_fetchers import fetch_open_meteo_wave_current
        data = fetch_open_meteo_wave_current(lat, lon)
        return float(data["wave_height_m"]), float(data["current_speed_kt"])
    except Exception as exc:
        logger.debug("Live ocean wave/current fetch failed for (%s, %s): %s", lat, lon, exc)
        raise NotImplementedError("Live ocean fetch unavailable") from exc


async def get_wave_current(
    lat: float | None,
    lon: float | None,
    zone_id: str,
    idx: int,
) -> tuple[float, float, str]:
    """
    Extensible wrapper: try OSF real data, fall back to Tier 3 Marine Data Package parquet,
    then deterministic heuristic.

    Returns:
        (wave_height_m, current_kt, source) where source in ("open_meteo_live", "marine_data_package", "mock_heuristic").
    """
    if lat is not None and lon is not None:
        try:
            wave, current = await fetch_osf_wave_current(lat, lon)
            return round(float(wave), 2), round(float(current), 2), "open_meteo_live"
        except NotImplementedError:
            pass
        except Exception as exc:
            logger.debug("sea_checker: OSF live fetch failed for %s (%s, %s): %s", zone_id, lat, lon, exc)

        # Tier 3 Fallback: Marine Data Package Parquet
        parquet_fallback = _fetch_parquet_wave_current(lat, lon)
        if parquet_fallback is not None:
            return round(float(parquet_fallback[0]), 2), round(float(parquet_fallback[1]), 2), "marine_data_package"

    # Fallback to deterministic mock
    wave = _heuristic_wave_height(lat, lon, zone_id, idx)
    current = _heuristic_current(lat, lon, zone_id, idx)
    return wave, current, "mock_heuristic"


# ---------------------------------------------------------------------------
# Public API — called via asyncio.gather by orchestrator
# ---------------------------------------------------------------------------

async def check_sea_conditions(points: list[dict]) -> list[dict]:
    """
    Evaluate wave height and ocean current per zone.

    Classification:
        wave < 1.5m -> safe, 1.5-2.5m -> caution, > 2.5m -> danger.
        current > 2kt -> caution, > 3kt -> danger (worst of wave/current wins).

    Args:
        points: List of dicts, each representing a PFZ zone. Accepted shapes:
            - Flat: {"zone_id": str, "place": str, "lat": float, "lon": float}
            - GeoJSON Feature: {"properties": {...}, "geometry": {"coordinates":[lon,lat]}}
            Order is preserved.

    Returns:
        List of dicts in the SAME order as input, each containing:
            {
              "zone_id": str,
              "place": str,
              "lat": float|None,
              "lon": float|None,
              "wave_height_m": float,
              "current_kt": float,
              "wave_status": "safe"|"caution"|"danger",
              "current_status": "safe"|"caution"|"danger",
              "status": "safe"|"caution"|"danger",  # overall (worst)
              "reason": str,                          # human-readable
              "source": "mock_heuristic"|"osf_06z"
            }
        Empty input -> [].
    """
    if not points:
        return []

    results: list[dict] = []
    for idx, pt in enumerate(points):
        if not isinstance(pt, dict):
            # Defensive: non-dict entry -> danger, never safe
            results.append({
                "zone_id": f"unknown_{idx}",
                "place": "",
                "lat": None,
                "lon": None,
                "wave_height_m": 0.0,
                "current_kt": 0.0,
                "wave_status": "danger",
                "current_status": "danger",
                "status": "danger",
                "reason": "invalid point — unknown location treated as danger",
                "source": "mock_heuristic",
            })
            continue

        zone_id, lat, lon, place = _extract_point(pt, idx)
        wave_m, current_kt, source = await get_wave_current(lat, lon, zone_id, idx)
        wave_status = _classify_wave(wave_m)
        current_status = _classify_current(current_kt)
        status = _overall_status(wave_status, current_status)

        if status == "danger":
            if current_status == "danger" and wave_status == "danger":
                reason = f"wave {wave_m}m danger + current {current_kt}kt danger"
            elif current_status == "danger":
                reason = f"current {current_kt}kt danger (>3kt)"
            else:
                reason = f"wave {wave_m}m danger (>2.5m)"
        elif status == "caution":
            if current_status == "caution" and wave_status == "caution":
                reason = f"wave {wave_m}m caution + current {current_kt}kt caution"
            elif current_status == "caution":
                reason = f"current {current_kt}kt caution (>2kt)"
            else:
                reason = f"wave {wave_m}m caution (1.5-2.5m)"
        else:
            reason = f"wave {wave_m}m safe, current {current_kt}kt safe"

        results.append({
            "zone_id": zone_id,
            "place": place,
            "lat": lat,
            "lon": lon,
            "wave_height_m": wave_m,
            "current_kt": current_kt,
            "wave_status": wave_status,
            "current_status": current_status,
            "status": status,
            "reason": reason,
            "source": source,
        })

    return results
