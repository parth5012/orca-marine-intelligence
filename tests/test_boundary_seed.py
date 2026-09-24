"""
Boundary seeding + false "outside EEZ" regression.

Production symptom fixed here (2026-09-23): the deployed PostGIS had an
EMPTY ``eez_boundaries`` table, so ``check_geofence`` succeeded and reported
every point as outside India's EEZ. DangerAgent turned that into
"Outside Indian Exclusive Economic Zone — fishing not permitted", the
combiner marked all zones unsafe (DO NOT SAIL), and the chat's danger veto
wiped the zone cards ~2s after they rendered — i.e. the "Show on Map"
button appeared then vanished with no click.

Run: pytest tests/test_boundary_seed.py
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ---------------------------------------------------------------------------
# 1. init_db must seed eez/mpa when empty (mirrors seed_initial_pfz_if_empty)
# ---------------------------------------------------------------------------
class _FakeConn:
    async def execute(self, *_args, **_kwargs):
        return None

    async def run_sync(self, *_args, **_kwargs):
        return None


class _FakeBegin:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, *_args):
        return False


class _FakeEngine:
    def begin(self):
        return _FakeBegin()


class TestSeedBoundariesIfEmpty:
    @pytest.mark.asyncio
    async def test_seeds_when_empty(self):
        """Empty tables -> ingest_boundaries() runs."""
        from backend.db import session as db_session

        with patch.object(db_session, "_boundary_counts", AsyncMock(return_value=(0, 0))), patch(
            "backend.ingest.boundaries.ingest_boundaries",
            AsyncMock(return_value={"eez_count": 2, "mpa_count": 6, "status": "loaded", "db_synced": True}),
        ) as ingest:
            seeded = await db_session.seed_boundaries_if_empty()

        ingest.assert_awaited_once()
        assert seeded == 8

    @pytest.mark.asyncio
    async def test_skips_when_populated(self):
        """Already-seeded tables -> ingest must NOT run (no duplicate rows)."""
        from backend.db import session as db_session

        with patch.object(db_session, "_boundary_counts", AsyncMock(return_value=(2, 6))), patch(
            "backend.ingest.boundaries.ingest_boundaries",
            AsyncMock(return_value={"eez_count": 2, "mpa_count": 6, "status": "loaded", "db_synced": True}),
        ) as ingest:
            seeded = await db_session.seed_boundaries_if_empty()

        ingest.assert_not_awaited()
        assert seeded == 0

    @pytest.mark.asyncio
    async def test_half_seeded_still_ingests(self):
        """EEZ present but MPA missing -> still ingest so both are populated."""
        from backend.db import session as db_session

        with patch.object(db_session, "_boundary_counts", AsyncMock(return_value=(2, 0))), patch(
            "backend.ingest.boundaries.ingest_boundaries",
            AsyncMock(return_value={"eez_count": 2, "mpa_count": 6, "status": "loaded", "db_synced": True}),
        ) as ingest:
            await db_session.seed_boundaries_if_empty()

        ingest.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_init_db_calls_boundary_seed(self):
        """init_db() must chain the boundary seed alongside the PFZ seed."""
        from backend.db import session as db_session

        with patch.object(db_session, "engine", _FakeEngine()), patch.object(
            db_session, "seed_initial_pfz_if_empty", AsyncMock(return_value=0)
        ) as pfz_seed, patch.object(
            db_session, "seed_boundaries_if_empty", AsyncMock(return_value=8)
        ) as boundary_seed:
            await db_session.init_db()

        pfz_seed.assert_awaited_once()
        boundary_seed.assert_awaited_once()


# ---------------------------------------------------------------------------
# 2. Empty eez_boundaries must not flip an in-EEZ point to "outside EEZ"
# ---------------------------------------------------------------------------
def _postgis_says_outside():
    return AsyncMock(
        return_value={
            "inside_eez": False,
            "inside_mpa": False,
            "mpa_name": None,
            "status": "danger",
            "reason": "Outside Indian Exclusive Economic Zone!",
        }
    )


class TestPostISEmptyTableCrossCheck:
    @pytest.mark.asyncio
    async def test_in_eez_point_is_not_false_banned(self):
        """PostGIS says outside, local GeoJSON says inside -> trust GeoJSON."""
        from backend.agents.subagents import danger_agent as da

        with patch("backend.db.postgis.check_geofence", _postgis_says_outside()):
            res = await da.check_safety(9.93, 76.27)

        assert res["inside_eez"] is True
        assert res["status"] != "danger"
        assert not any("Outside Indian" in w for w in res["warnings"])

    @pytest.mark.asyncio
    async def test_genuinely_outside_point_still_banned(self):
        """Open Arabian Sea (60E) stays outside EEZ -> ban is preserved."""
        from backend.agents.subagents import danger_agent as da

        with patch("backend.db.postgis.check_geofence", _postgis_says_outside()):
            res = await da.check_safety(10.0, 60.0)

        assert res["inside_eez"] is False
        assert res["status"] == "danger"
        assert any("Outside Indian" in w for w in res["warnings"])

    @pytest.mark.asyncio
    async def test_postgis_agreeing_inside_is_left_alone(self):
        """Healthy table path unchanged: PostGIS inside -> inside."""
        from backend.agents.subagents import danger_agent as da

        healthy = AsyncMock(
            return_value={
                "inside_eez": True,
                "inside_mpa": False,
                "mpa_name": None,
                "status": "safe",
                "reason": "ok",
            }
        )
        with patch("backend.db.postgis.check_geofence", healthy):
            res = await da.check_safety(9.93, 76.27)

        assert res["inside_eez"] is True
        assert res["status"] != "danger"
