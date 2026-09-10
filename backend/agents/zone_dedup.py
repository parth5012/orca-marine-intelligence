"""
Zone dedup helper — single source of truth for duplicate fishing-zone detection.

Owner: M-A (Agents & Orchestration)
Module: backend/agents/zone_dedup.py

Root cause: PostGIS keeps one row per (place, valid_date) because
zone_id = {base}_{date}. find_pfz_near had no valid_date filter, so
yesterday + today rows for the same landing centre both entered the
top-5 with different zone_ids. Combiner/frontend guards compared only
exact zone_id, so twins rendered as two cards.

Canonical key: normalized place + rounded coords (4dp ≈ 11m).
Two rows with the same place (case/space-insensitive) and coords within
rounding tolerance are the same physical zone, regardless of zone_id
suffixes, float string formatting, or ingest date.
"""


from typing import Any


def _norm_place(place: Any) -> str:
    try:
        return str(place or "").strip().lower()
    except Exception:
        return ""


def _round_coord(value: Any, ndigits: int = 4) -> str:
    try:
        if value is None:
            return ""
        return f"{round(float(value), ndigits):.{ndigits}f}"
    except (TypeError, ValueError):
        return str(value or "")


def zone_key(zone: dict, ndigits: int = 4) -> str:
    """Canonical identity for a zone dict.

    Prefers normalized place+coords. Falls back to zone_id only when
    place AND coords are both missing (should be rare).
    """
    if not isinstance(zone, dict):
        return str(zone)
    place = _norm_place(zone.get("place"))
    lat = _round_coord(zone.get("lat"), ndigits)
    lon = _round_coord(zone.get("lon"), ndigits)
    if place or (lat and lon):
        return f"{place}|{lat}|{lon}"
    zid = zone.get("zone_id") or zone.get("id") or ""
    return f"id:{zid}"


def dedup_zones(zones: list[dict], ndigits: int = 4) -> list[dict]:
    """Remove duplicate zones, keeping first occurrence (nearest / best-ranked)."""
    seen: set[str] = set()
    out: list[dict] = []
    for z in zones or []:
        if not isinstance(z, dict):
            continue
        key = zone_key(z, ndigits)
        if key in seen:
            continue
        seen.add(key)
        out.append(z)
    return out


def feature_key(feature: dict, ndigits: int = 4) -> str:
    """Canonical identity for a GeoJSON Feature (properties + geometry)."""
    if not isinstance(feature, dict):
        return str(feature)
    props = feature.get("properties", {}) or {}
    geom = feature.get("geometry", {}) or {}
    coords = geom.get("coordinates") or []
    lat = lon = None
    try:
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lon = float(coords[0])
            lat = float(coords[1])
    except (TypeError, ValueError):
        pass
    if lat is None:
        lat = props.get("lat")
    if lon is None:
        lon = props.get("lon")
    place = _norm_place(props.get("place") or props.get("name") or props.get("zone_name"))
    lat_s = _round_coord(lat, ndigits)
    lon_s = _round_coord(lon, ndigits)
    if place or (lat_s and lon_s):
        return f"{place}|{lat_s}|{lon_s}"
    zid = props.get("zone_id") or props.get("id") or ""
    return f"id:{zid}"


def dedup_features(features: list[dict], ndigits: int = 4) -> list[dict]:
    """Remove duplicate GeoJSON Features, keeping first occurrence."""
    seen: set[str] = set()
    out: list[dict] = []
    for f in features or []:
        if not isinstance(f, dict):
            continue
        key = feature_key(f, ndigits)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out
