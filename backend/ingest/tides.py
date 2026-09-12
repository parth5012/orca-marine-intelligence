"""
Tide helper — nearest coastal tide estimate from Marine Data Package.

Owner: M-B (Data) / M-C (Backend API) — tide read path
Module: backend/ingest/tides.py

PS asks: "What are the tide, weather, and sea conditions near my fishing
location?" Tide data lives (when present) under
``data/marine_data_package/marine-data/processed/tides/`` but no agent read
it. This helper bridges that gap for ``GET /api/weather/current``,
``weather_agent.check_weather()`` and the combiner advisory text.

Contract:
    get_tide(lat, lon) -> {
        "tide_range_m": float | None,
        "next_high_tide_utc": str | None,
        "next_low_tide_utc": str | None,
        "tidal_state": "rising" | "falling" | "slack" | "unknown",
    }

Rules:
    - Must NEVER raise — any failure returns nulls + "unknown".
    - File load is cached in module-level cache (dir listing + records).
    - Supports CSV / JSON(+GeoJSON) / Parquet / netCDF when present;
      missing dir, empty dir, or unreadable files all degrade gracefully.
"""

from __future__ import annotations

import csv
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[2]
TIDE_DIR = ROOT_DIR / "data" / "marine_data_package" / "marine-data" / "processed" / "tides"

_VALID_STATES = ("rising", "falling", "slack", "unknown")

# Safety: nearest-point match beyond this is a cross-basin false match.
MAX_TIDE_DISTANCE_KM = 150.0
# Safety: cap expanded records so gridded products can't OOM the worker.
MAX_TIDE_RECORDS = 20_000

# Module-level cache: {"scanned": bool, "records": list[dict]}
_CACHE: dict[str, Any] = {"scanned": False, "records": []}


def _null_tide() -> dict[str, Any]:
    return {
        "tide_range_m": None,
        "next_high_tide_utc": None,
        "next_low_tide_utc": None,
        "tidal_state": "unknown",
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return r * 2 * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _pick(d: dict, *keys: str) -> Any:
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    # case-insensitive fallback
    if isinstance(d, dict):
        lowered = {str(k).lower(): v for k, v in d.items()}
        for k in keys:
            if lowered.get(k.lower()) is not None:
                return lowered[k.lower()]
    return None


def _to_float(v: Any) -> float | None:
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        f = float(v)
        if math.isnan(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _norm_state(v: Any) -> str:
    if not isinstance(v, str):
        return "unknown"
    s = v.strip().lower()
    if s in ("rising", "flood", "flooding", "incoming", "high"):
        return "rising"
    if s in ("falling", "ebb", "ebbing", "outgoing", "low"):
        return "falling"
    if s in ("slack", "slack_water", "slackwater", "still"):
        return "slack"
    if s in ("rising", "falling", "slack", "unknown"):
        return s
    return "unknown"


def _load_csv_records(path: Path, budget: int = MAX_TIDE_RECORDS) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return []
            out: list[dict] = []
            for r in reader:
                out.append(dict(r))
                if len(out) >= budget:
                    break
            return out
    except Exception as exc:
        logger.debug("tides: failed reading CSV %s: %s", path, exc)
        return []


def _load_json_records(path: Path) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
            out: list[dict] = []
            for feat in payload.get("features", []):
                if len(out) >= MAX_TIDE_RECORDS:
                    break
                if not isinstance(feat, dict):
                    continue
                props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
                rec: dict = dict(props) if isinstance(props, dict) else {}
                try:
                    geom = feat.get("geometry")
                    coords = geom.get("coordinates", []) if isinstance(geom, dict) else []
                    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                        rec.setdefault("longitude", float(coords[0]))  # type: ignore[arg-type]
                        rec.setdefault("latitude", float(coords[1]))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    pass
                out.append(rec)
            return out
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)][:MAX_TIDE_RECORDS]
        if isinstance(payload, dict):
            # single record or {records: [...]} / {data: [...]}
            for k in ("records", "data", "tides", "points"):
                if isinstance(payload.get(k), list):
                    return [r for r in payload[k] if isinstance(r, dict)][:MAX_TIDE_RECORDS]
            return [payload]
        return []
    except Exception as exc:
        logger.debug("tides: failed reading JSON %s: %s", path, exc)
        return []


def _load_parquet_records(path: Path) -> list[dict]:
    try:
        import pyarrow.parquet as pq  # type: ignore

        tbl = pq.read_table(str(path))
        if tbl.num_rows > MAX_TIDE_RECORDS:
            tbl = tbl.slice(0, MAX_TIDE_RECORDS)
        try:
            return tbl.to_pylist()  # type: ignore[no-any-return]
        except Exception:
            df = tbl.to_pandas()
            return [dict(r) for r in df.to_dict(orient="records")]
    except Exception as exc:
        logger.debug("tides: failed reading Parquet %s: %s", path, exc)
        return []


def _load_netcdf_records(path: Path) -> list[dict]:
    # Optional: xarray preferred, netCDF4 fallback. Absent deps -> [].
    try:
        import xarray as xr  # type: ignore

        ds = xr.open_dataset(str(path))
        try:
            df = ds.to_dataframe().reset_index()
            if len(df) > MAX_TIDE_RECORDS:
                df = df.head(MAX_TIDE_RECORDS)
            return [dict(r) for r in df.to_dict(orient="records")]
        finally:
            try:
                ds.close()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("tides: xarray read failed for %s: %s", path, exc)
    try:
        import netCDF4 as nc  # type: ignore
        import numpy as np  # type: ignore

        out: list[dict] = []
        ds2 = nc.Dataset(str(path))
        try:
            varnames = [v.lower() for v in ds2.variables.keys()]
            lat_k = next((v for v in ds2.variables.keys() if v.lower() in ("lat", "latitude", "y")), None)
            lon_k = next((v for v in ds2.variables.keys() if v.lower() in ("lon", "lng", "longitude", "x")), None)
            if lat_k is None or lon_k is None:
                return []
            lats = np.atleast_1d(ds2.variables[lat_k][:]).ravel()
            lons = np.atleast_1d(ds2.variables[lon_k][:]).ravel()
            # extra scalar/vector vars to carry along
            extras: dict[str, Any] = {}
            for v in ds2.variables.keys():
                if v in (lat_k, lon_k):
                    continue
                try:
                    arr = np.atleast_1d(ds2.variables[v][:]).ravel()
                    extras[v] = arr
                except Exception:
                    continue
            n = min(len(lats), len(lons))
            # Guard: 2D mesh grids would pair diagonal-only points; skip them.
            try:
                if getattr(lats, "ndim", 1) != 1 or getattr(lons, "ndim", 1) != 1:
                    return []
            except Exception:
                pass
            n = min(n, MAX_TIDE_RECORDS)
            for i in range(n):
                rec: dict = {"latitude": float(lats[i]), "longitude": float(lons[i])}  # type: ignore[arg-type]
                for k, arr in extras.items():
                    try:
                        if len(arr) == n:
                            val = arr[i]
                            rec[k] = float(val) if np.isscalar(val) or getattr(val, "ndim", 0) == 0 else val  # type: ignore[arg-type]
                        elif len(arr) == 1:
                            rec[k] = float(arr[0])  # type: ignore[arg-type]
                    except Exception:
                        continue
                out.append(rec)
            _ = varnames
            return out
        finally:
            try:
                ds2.close()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("tides: netCDF read failed for %s: %s", path, exc)
        return []


def _scan_dir() -> list[dict]:
    """List + load tide files once; cache records in _CACHE."""
    if _CACHE.get("scanned"):
        return list(_CACHE.get("records", []))
    records: list[dict] = []
    try:
        if not TIDE_DIR.is_dir():
            _CACHE["scanned"] = True
            _CACHE["records"] = []
            return []
        try:
            files = sorted([p for p in TIDE_DIR.iterdir() if p.is_file()])
        except Exception as exc:
            logger.debug("tides: dir listing failed for %s: %s", TIDE_DIR, exc)
            _CACHE["scanned"] = True
            _CACHE["records"] = []
            return []
        for p in files:
            if len(records) >= MAX_TIDE_RECORDS:
                break
            suf = p.suffix.lower()
            try:
                if suf == ".csv":
                    records.extend(_load_csv_records(p, MAX_TIDE_RECORDS - len(records)))
                elif suf in (".json", ".geojson"):
                    records.extend(_load_json_records(p))
                elif suf in (".parquet", ".pq"):
                    records.extend(_load_parquet_records(p))
                elif suf in (".nc", ".netcdf", ".cdf"):
                    records.extend(_load_netcdf_records(p))
                # ignore anything else (e.g. .txt README, .md)
            except Exception as exc:
                logger.debug("tides: skipping file %s: %s", p, exc)
                continue
        records = records[:MAX_TIDE_RECORDS]
    except Exception as exc:
        logger.debug("tides: scan failed: %s", exc)
        records = []
    _CACHE["scanned"] = True
    _CACHE["records"] = records
    return list(records)


def clear_cache() -> None:
    """Reset module cache (tests). Never raises."""
    try:
        _CACHE["scanned"] = False
        _CACHE["records"] = []
    except Exception:
        pass


def _record_to_tide(rec: dict) -> dict[str, Any]:
    """Map a nearest record to the tide contract (best-effort)."""
    try:
        tide_range = _to_float(_pick(rec, "tide_range_m", "tide_range", "range_m", "range", "tidal_range_m"))
        if tide_range is None:
            hi = _to_float(_pick(rec, "high_tide_m", "max_height_m", "max_tide_m", "mhhw_m", "highest_m"))
            lo = _to_float(_pick(rec, "low_tide_m", "min_height_m", "min_tide_m", "mllw_m", "lowest_m"))
            if hi is not None and lo is not None:
                tide_range = round(abs(hi - lo), 2)
            else:
                # Range only from true time-series arrays — never mix scalar
                # synonyms (e.g. height_m + height would fake 0.0m).
                heights: list[float] = []
                # series form: {"heights": [...]} or {"levels": [...]}
                for k in ("heights", "levels", "tide_heights"):
                    seq = rec.get(k) if isinstance(rec, dict) else None
                    if isinstance(seq, (list, tuple)) and seq:
                        nums = [_to_float(x) for x in seq]
                        nums = [x for x in nums if x is not None]
                        if nums:
                            heights.extend(nums)
                if len(heights) >= 2:
                    tide_range = round(max(heights) - min(heights), 2)
        if isinstance(tide_range, float):
            tide_range = round(tide_range, 2)

        next_high = _pick(rec, "next_high_tide_utc", "next_high_utc", "next_high", "high_tide_utc", "nextHigh")
        next_low = _pick(rec, "next_low_tide_utc", "next_low_utc", "next_low", "low_tide_utc", "nextLow")
        next_high_s = str(next_high) if next_high is not None else None
        next_low_s = str(next_low) if next_low is not None else None

        state = _norm_state(_pick(rec, "tidal_state", "tide_state", "state", "trend", "tide_trend"))
        if state == "unknown":
            # derive from consecutive heights when available
            try:
                seq = None
                for k in ("heights", "levels", "tide_heights", "series"):
                    v = rec.get(k) if isinstance(rec, dict) else None
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        seq = [_to_float(x) for x in v]
                        seq = [x for x in seq if x is not None]
                        break
                if seq and len(seq) >= 2:
                    delta = seq[-1] - seq[-2]
                    if abs(delta) < 0.02:
                        state = "slack"
                    elif delta > 0:
                        state = "rising"
                    else:
                        state = "falling"
            except Exception:
                pass
        return {
            "tide_range_m": tide_range,
            "next_high_tide_utc": next_high_s,
            "next_low_tide_utc": next_low_s,
            "tidal_state": state if state in _VALID_STATES else "unknown",
        }
    except Exception as exc:
        logger.debug("tides: record mapping failed: %s", exc)
        return _null_tide()


def get_tide(lat: float | None, lon: float | None) -> dict[str, Any]:
    """Return nearest-point tide dict for (lat, lon). Never raises.

    Missing/invalid coords or missing/unreadable data dir -> nulls + unknown.
    """
    try:
        if lat is None or lon is None:
            return _null_tide()
        try:
            flat = float(lat)
            flon = float(lon)
        except (TypeError, ValueError):
            return _null_tide()
        if not (-90.0 <= flat <= 90.0 and -180.0 <= flon <= 180.0):
            return _null_tide()

        records = _scan_dir()
        if not records:
            return _null_tide()

        best: dict | None = None
        best_dist: float | None = None
        for rec in records:
            if not isinstance(rec, dict):
                continue
            rlat = _to_float(_pick(rec, "latitude", "lat", "y"))
            rlon = _to_float(_pick(rec, "longitude", "lon", "lng", "long", "x"))
            if rlat is None or rlon is None:
                continue
            if not (-90.0 <= rlat <= 90.0 and -180.0 <= rlon <= 180.0):
                continue
            try:
                d = _haversine_km(flat, flon, rlat, rlon)
            except Exception:
                continue
            if best_dist is None or d < best_dist:
                best_dist = d
                best = rec
        if best is None or best_dist is None or best_dist > MAX_TIDE_DISTANCE_KM:
            return _null_tide()
        return _record_to_tide(best)
    except Exception as exc:
        logger.debug("tides: get_tide failed for (%s, %s): %s", lat, lon, exc)
        return _null_tide()
