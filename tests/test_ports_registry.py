"""ORCA officer ports registry verification (offline, no network).

Covers (Wayfinder #170 T1, issue #171):
  1. data/ports.json holds exactly the 12 officer ports
  2. ids unique; lat 5-25 / lon 65-95 (India coastal ranges)
  3. incois_sector non-empty and a real value accepted by the existing
     GET /api/pfz/today?sector= filter (backend/routers/pfz.py matches
     sector OR sector_name, uppercased) — verified against the live
     sector set in data/pfz-today.geojson, never an invented SEC code
  4. backend.core.ports get_ports()/get_port() loader contract
     (zero-dep stdlib loader, fresh copies, unknown id -> None)

No network: stdlib-only loader + local JSON file reads.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.core.ports import BBOX_DELTA_DEG, get_port, get_ports

EXPECTED_IDS = {
    "kochi",
    "munambam",
    "vizhinjam",
    "chennai",
    "cuddalore",
    "visakhapatnam",
    "paradip",
    "digha",
    "porbandar",
    "okha",
    "mangalore",
    "tuticorin",
}

# Real SEC codes present in data/pfz-today.geojson today; the registry
# must only use these (pfz.py accepts any string, but T1 requires a
# value the live filter actually matches).
KNOWN_SECTORS = {
    "SEC002",
    "SEC003",
    "SEC004",
    "SEC005",
    "SEC007",
    "SEC008",
    "SEC012",
    "SEC013",
    "SEC014",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


class TestPortsFile:
    def test_twelve_expected_ports(self):
        ports = get_ports()
        assert len(ports) == 12, f"expected 12 ports, got {len(ports)}"
        assert {p["id"] for p in ports} == EXPECTED_IDS

    def test_ids_unique(self):
        ids = [p["id"] for p in get_ports()]
        assert len(set(ids)) == len(ids), f"duplicate port ids: {ids}"

    def test_required_keys_present(self):
        required = {"id", "name", "state", "lat", "lon", "incois_sector", "language"}
        for port in get_ports():
            missing = required - set(port)
            assert not missing, f"port {port.get('id')} missing keys {missing}"

    def test_lat_lon_in_india_coastal_range(self):
        for port in get_ports():
            assert 5.0 <= float(port["lat"]) <= 25.0, f"{port['id']} lat out of range"
            assert 65.0 <= float(port["lon"]) <= 95.0, f"{port['id']} lon out of range"

    def test_sector_non_empty_and_known(self):
        for port in get_ports():
            sector = str(port["incois_sector"]).strip().upper()
            assert sector, f"{port['id']} has empty incois_sector"
            assert sector in KNOWN_SECTORS, f"{port['id']} sector {sector} not a real SEC code"

    def test_sectors_match_live_pfz_file(self):
        """Each incois_sector must occur in data/pfz-today.geojson (what ?sector= filters)."""
        geo_path = _repo_root() / "data" / "pfz-today.geojson"
        doc = json.loads(geo_path.read_text(encoding="utf-8"))
        live_sectors = {
            str(f.get("properties", {}).get("sector", "")).upper()
            for f in doc.get("features", [])
        }
        for port in get_ports():
            sector = str(port["incois_sector"]).strip().upper()
            assert sector in live_sectors, f"{port['id']} sector {sector} absent from live file"

    def test_bbox_delta_documented(self):
        assert BBOX_DELTA_DEG == 1.0
        for port in get_ports():
            assert float(port.get("bbox_delta", BBOX_DELTA_DEG)) == 1.0


class TestPortsLoader:
    def test_get_port_known(self):
        kochi = get_port("kochi")
        assert kochi is not None
        assert kochi["name"] == "Kochi"
        assert kochi["incois_sector"] == "SEC005"
        assert float(kochi["lat"]) == 9.93
        assert float(kochi["lon"]) == 76.26

    def test_get_port_case_insensitive(self):
        assert get_port("Kochi")["id"] == "kochi"

    def test_get_port_unknown_returns_none(self):
        assert get_port("atlantis") is None
        assert get_port("") is None

    def test_get_ports_returns_fresh_copies(self):
        first = get_ports()
        first[0]["name"] = "MUTATED"
        assert get_ports()[0]["name"] != "MUTATED"
