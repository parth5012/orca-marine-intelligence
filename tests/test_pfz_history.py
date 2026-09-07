"""
Tests for PFZ History Snapshots Endpoint (GET /api/pfz/history).

Verifies:
1. Real PostGIS history snapshots query (seeded 3 days -> 3 snapshots).
2. Grouping by valid_date into snapshots [{date, count, features}].
3. Sector filtering on history snapshots.
4. Retention policy enforcement (1-30 days, max 30).
5. Pagination limit parameter (default 500).
6. DB-empty fallback clearly flagged with source='synthetic-duplicate' and warning field.
7. Contract locking matching docs/API.md.
"""

import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.main import app


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class DummyPFZZone:
    """Mock PFZZone model instance matching backend.db.models.PFZZone."""

    def __init__(
        self,
        id: int,
        zone_id: str,
        place: str,
        sector: str,
        sector_name: str,
        direction: str,
        bearing: int,
        distance_km: float,
        depth_range: str,
        lat: float,
        lon: float,
        valid_date: date,
        source: str = "incois_textdata",
    ):
        self.id = id
        self.zone_id = zone_id
        self.place = place
        self.sector = sector
        self.sector_name = sector_name
        self.direction = direction
        self.bearing = bearing
        self.distance_km = distance_km
        self.depth_range = depth_range
        self.lat = lat
        self.lon = lon
        self.valid_date = valid_date
        self.source = source


class MockQueryResult:
    def __init__(self, rows: List[Any]):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class MockAsyncSession:
    """Simulates SQLAlchemy AsyncSession filtering on PFZZone records."""

    def __init__(self, zones: List[DummyPFZZone]):
        self.zones = zones

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def execute(self, stmt):
        filtered = list(self.zones)
        params = stmt.compile().params

        start_date = None
        sector_param = None
        for k, v in params.items():
            if isinstance(v, (date, datetime)):
                start_date = v if isinstance(v, date) else v.date()
            elif isinstance(v, str):
                sector_param = v

        if start_date is not None:
            filtered = [z for z in filtered if z.valid_date >= start_date]

        if sector_param is not None:
            sec = sector_param.strip().upper()
            filtered = [
                z
                for z in filtered
                if z.sector.upper() == sec or z.sector_name.upper() == sec
            ]

        filtered.sort(key=lambda z: (z.valid_date, z.id), reverse=True)

        limit_val = getattr(stmt, "_limit", None)
        limit_clause = getattr(stmt, "_limit_clause", None)
        target_limit = None
        for candidate in [limit_val, limit_clause]:
            if candidate is not None:
                try:
                    target_limit = int(candidate)
                    break
                except (TypeError, ValueError):
                    val = getattr(candidate, "value", None)
                    if val is not None:
                        try:
                            target_limit = int(val)
                            break
                        except (TypeError, ValueError):
                            pass

        if target_limit is not None:
            filtered = filtered[:target_limit]

        return MockQueryResult(filtered)


def build_seeded_3_day_zones() -> List[DummyPFZZone]:
    """Seed 6 zones spanning 3 distinct dates (2 zones per date)."""
    today = date.today()
    zones = []
    zone_idx = 1
    for day_offset in range(3):
        cur_date = today - timedelta(days=day_offset)
        # Zone 1: SEC005 (KERALA)
        zones.append(
            DummyPFZZone(
                id=zone_idx,
                zone_id=f"SEC005_Kochi_{zone_idx}_{cur_date}",
                place=f"Kochi_{day_offset}",
                sector="SEC005",
                sector_name="KERALA",
                direction="SW",
                bearing=225,
                distance_km=15.0 + day_offset,
                depth_range="40-50",
                lat=9.93 + (day_offset * 0.05),
                lon=76.26 + (day_offset * 0.05),
                valid_date=cur_date,
                source="incois_textdata",
            )
        )
        zone_idx += 1
        # Zone 2: SEC002 (MAHARASHTRA)
        zones.append(
            DummyPFZZone(
                id=zone_idx,
                zone_id=f"SEC002_Mumbai_{zone_idx}_{cur_date}",
                place=f"Mumbai_{day_offset}",
                sector="SEC002",
                sector_name="MAHARASHTRA",
                direction="W",
                bearing=270,
                distance_km=25.0 + day_offset,
                depth_range="50-60",
                lat=18.92 + (day_offset * 0.05),
                lon=72.83 + (day_offset * 0.05),
                valid_date=cur_date,
                source="incois_textdata",
            )
        )
        zone_idx += 1
    return zones


# ==============================================================================
# 1. Real PostGIS Snapshots & Grouping Tests
# ==============================================================================


def test_history_seeded_3_days_returns_3_snapshots(client):
    """Verify seeded 3 days of PostGIS records returns exactly 3 grouped snapshots."""
    seeded_zones = build_seeded_3_day_zones()
    mock_session_factory = lambda: MockAsyncSession(seeded_zones)

    with patch("backend.routers.pfz.AsyncSessionLocal", side_effect=mock_session_factory):
        response = client.get("/api/pfz/history?days=7")

    assert response.status_code == 200
    data = response.json()

    assert data["type"] == "FeatureCollection"
    assert data["days"] == 7
    assert data["source"] == "postgis"
    assert "warning" not in data or data.get("warning") is None

    # Contract fields
    for field in ["type", "days", "sector", "start_date", "end_date", "snapshots", "features", "count"]:
        assert field in data, f"Missing locked contract field: {field}"

    # Exactly 3 snapshots for 3 seeded days
    snapshots = data["snapshots"]
    assert len(snapshots) == 3, f"Expected 3 snapshots, got {len(snapshots)}"

    # Check snapshots ordered by date descending
    dates = [s["date"] for s in snapshots]
    assert dates == sorted(dates, reverse=True), "Snapshots must be ordered descending by date"

    # Each snapshot has date, count, and features
    total_feature_count = 0
    for snapshot in snapshots:
        assert "date" in snapshot
        assert "count" in snapshot
        assert "features" in snapshot
        assert snapshot["count"] == len(snapshot["features"])
        assert snapshot["count"] == 2  # 2 zones per day seeded
        total_feature_count += snapshot["count"]

    assert data["count"] == total_feature_count == 6
    assert len(data["features"]) == 6


# ==============================================================================
# 2. Sector Filtering Tests
# ==============================================================================


def test_history_sector_filter_code(client):
    """Verify sector filter by code (e.g. SEC005) only returns matching sector features."""
    seeded_zones = build_seeded_3_day_zones()
    mock_session_factory = lambda: MockAsyncSession(seeded_zones)

    with patch("backend.routers.pfz.AsyncSessionLocal", side_effect=mock_session_factory):
        response = client.get("/api/pfz/history?days=7&sector=SEC005")

    assert response.status_code == 200
    data = response.json()

    assert data["sector"] == "SEC005"
    assert data["source"] == "postgis"
    assert data["count"] == 3  # 1 SEC005 feature per day for 3 days

    for feat in data["features"]:
        assert feat["properties"]["sector"] == "SEC005"

    for snapshot in data["snapshots"]:
        assert snapshot["count"] == 1
        for feat in snapshot["features"]:
            assert feat["properties"]["sector"] == "SEC005"


def test_history_sector_filter_name_case_insensitive(client):
    """Verify sector filter by name is case-insensitive (e.g. kerala -> KERALA)."""
    seeded_zones = build_seeded_3_day_zones()
    mock_session_factory = lambda: MockAsyncSession(seeded_zones)

    with patch("backend.routers.pfz.AsyncSessionLocal", side_effect=mock_session_factory):
        response = client.get("/api/pfz/history?days=7&sector=kerala")

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 3
    for feat in data["features"]:
        assert feat["properties"]["sector_name"].upper() == "KERALA"


# ==============================================================================
# 3. DB-Empty Fallback Tests
# ==============================================================================


def test_history_fallback_flag_when_db_empty(client):
    """When PostGIS returns no records, fallback must be clearly flagged with source and warning."""
    empty_session_factory = lambda: MockAsyncSession([])

    with patch("backend.routers.pfz.AsyncSessionLocal", side_effect=empty_session_factory):
        response = client.get("/api/pfz/history?days=5")

    assert response.status_code == 200
    data = response.json()

    # DB-empty fallback clearly flagged
    assert data["source"] == "synthetic-duplicate", "Fallback must set source: synthetic-duplicate"
    assert "warning" in data, "Fallback must include warning field"
    assert data["warning"] is not None and len(data["warning"]) > 0

    # Contract locked
    for field in ["type", "days", "sector", "start_date", "end_date", "snapshots", "features", "count"]:
        assert field in data

    assert data["days"] == 5
    assert len(data["snapshots"]) == 5
    assert data["count"] == len(data["features"])

    for s in data["snapshots"]:
        assert "date" in s
        assert "count" in s
        assert "features" in s
        assert s["count"] == len(s["features"])


def test_history_fallback_when_db_disconnected(client):
    """When PostGIS raises connection error, fallback must gracefully activate with warning."""
    class FailingSession:
        async def __aenter__(self):
            raise ConnectionRefusedError("PostGIS connection refused")

        async def __aexit__(self, *args):
            pass

    with patch("backend.routers.pfz.AsyncSessionLocal", side_effect=FailingSession):
        response = client.get("/api/pfz/history?days=3")

    assert response.status_code == 200
    data = response.json()

    assert data["source"] == "synthetic-duplicate"
    assert "warning" in data
    assert len(data["snapshots"]) == 3


def test_history_fallback_with_sector_filter(client):
    """Fallback mode with sector filter must filter features to that sector."""
    empty_session_factory = lambda: MockAsyncSession([])

    with patch("backend.routers.pfz.AsyncSessionLocal", side_effect=empty_session_factory):
        response = client.get("/api/pfz/history?days=3&sector=SEC005")

    assert response.status_code == 200
    data = response.json()

    assert data["source"] == "synthetic-duplicate"
    assert "warning" in data
    assert data["sector"] == "SEC005"
    assert len(data["snapshots"]) == 3
    for feat in data["features"]:
        assert feat["properties"]["sector"] == "SEC005"


# ==============================================================================
# 4. Retention & Validation Policy Tests (30 Days Max)
# ==============================================================================


def test_history_retention_30_days_max(client):
    """Enforce retention max 30 days: days > 30 returns 422, days <= 30 succeeds."""
    # > 30 days must fail with 422
    resp_31 = client.get("/api/pfz/history?days=31")
    assert resp_31.status_code == 422

    # < 1 day must fail with 422
    resp_0 = client.get("/api/pfz/history?days=0")
    assert resp_0.status_code == 422

    # Exactly 30 days is allowed
    empty_session_factory = lambda: MockAsyncSession([])
    with patch("backend.routers.pfz.AsyncSessionLocal", side_effect=empty_session_factory):
        resp_30 = client.get("/api/pfz/history?days=30")
    assert resp_30.status_code == 200
    assert resp_30.json()["days"] == 30


# ==============================================================================
# 5. Pagination & Limit Tests
# ==============================================================================


def test_history_limit_pagination(client):
    """Verify limit parameter caps the total number of features returned."""
    seeded_zones = build_seeded_3_day_zones()  # 6 zones total
    mock_session_factory = lambda: MockAsyncSession(seeded_zones)

    with patch("backend.routers.pfz.AsyncSessionLocal", side_effect=mock_session_factory):
        response = client.get("/api/pfz/history?days=7&limit=2")

    assert response.status_code == 200
    data = response.json()

    assert data["count"] <= 2
    assert len(data["features"]) <= 2
    total_snapshot_features = sum(s["count"] for s in data["snapshots"])
    assert total_snapshot_features <= 2
