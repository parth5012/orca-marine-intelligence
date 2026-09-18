"""All-India port registry loader (Wayfinder #170 T1, issue #171).

Single source of truth for the /officer port selector + PFZ filtering
(consumed by T2 officer backend and T3 port selector). Zero third-party
deps: stdlib json/pathlib/functools only. No mutable global state: the
file read is memoized and every caller receives fresh copies.

Entry shape (see data/ports.json): {id, name, state, lat, lon,
incois_sector, sector_name, language, bbox_delta}. incois_sector is
always a real SEC code accepted by GET /api/pfz/today?sector= (the
pfz.py filter matches sector OR sector_name, uppercased); sector_name
is the matching name fallback. bbox_delta (1.0deg) is the MapInner
bbox half-width: bbox = lon+/-1.0, lat+/-1.0.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REQUIRED_KEYS = ("id", "name", "state", "lat", "lon", "incois_sector", "language")

BBOX_DELTA_DEG = 1.0


def _find_registry(start: Path) -> Path:
    for parent in (start, *start.parents):
        candidate = parent / "data" / "ports.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"data/ports.json not found above {start}")


def _is_valid_port(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    if any(key not in entry for key in REQUIRED_KEYS):
        return False
    try:
        lat, lon = float(entry["lat"]), float(entry["lon"])
    except (TypeError, ValueError):
        return False
    return (
        5.0 <= lat <= 25.0
        and 65.0 <= lon <= 95.0
        and bool(str(entry["incois_sector"]).strip())
    )


@lru_cache(maxsize=1)
def _read_registry(path_str: str) -> tuple:
    with open(path_str, encoding="utf-8") as fh:
        entries = json.load(fh)
    return tuple(dict(entry) for entry in entries if _is_valid_port(entry))


def get_ports() -> list[dict]:
    """Return fresh copies of all validated port entries."""
    path = _find_registry(Path(__file__).resolve().parent)
    return [dict(entry) for entry in _read_registry(str(path))]


def get_port(port_id: str) -> dict | None:
    """Return a copy of the port matching id (case-insensitive), else None."""
    target = str(port_id or "").strip().lower()
    for entry in get_ports():
        if str(entry["id"]).lower() == target:
            return entry
    return None
