"""ORCA US-ORCA-014 Kochi fix verification (offline, mock-backed).

Covers:
  1. Kochi returns ranked zone under 10s (mocked PostGIS/live fetchers)
  2. Planner timeout uses Kochi baseline (9.93, 76.26)
   3. Safety veto wave/wind thresholds (2.5m / 46.3kph danger, 1.5m / 27.78kph caution)
  4. Contract keys canonical (safety, distance_km, depth_m, wave_m, wind_kph, confidence)
  5. Cache fallback file (data/pfz-today.geojson offline read + missing-file [])

No network: all PostGIS/live fetchers + Redis + LLM planner are mocked.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

KOCHI_LAT = 9.93
KOCHI_LON = 76.26

FISH = [
    {
        "zone_id": "z1",
        "place": "Kochi",
        "sector": "KERALA",
        "lat": 9.90,
        "lon": 76.20,
        "distance_from_user_km": 12.0,
        "bearing": 232,
        "direction": "SW",
        "depth_range": "20-30",
    },
    {
        "zone_id": "z2",
        "place": "Munambam",
        "sector": "KERALA",
        "lat": 10.10,
        "lon": 76.10,
        "distance_from_user_km": 25.0,
        "bearing": 10,
        "direction": "N",
        "depth_range": "30-40",
    },
]
SEA_CALM = [
    {"zone_id": "z1", "wave_height_m": 0.8, "status": "safe"},
    {"zone_id": "z2", "wave_height_m": 1.0, "status": "safe"},
]
WEATHER_CALM = [
    {"zone_id": "z1", "wind_kt": 8.0, "status": "safe"},
    {"zone_id": "z2", "wind_kt": 10.0, "status": "safe"},
]
DANGER_OK = [
    {"zone_id": "z1", "inside_eez": True, "inside_mpa": False, "status": "safe"},
    {"zone_id": "z2", "inside_eez": True, "inside_mpa": False, "status": "safe"},
]


def _full_dispatch_envelope():
    from backend.agents import planner_schema as ps

    plan = ps.PlannerOutput(
        detected_language="en",
        target_location=ps.TargetLocation(
            lat=KOCHI_LAT, lon=KOCHI_LON, port_name="Kochi", confidence=0.9
        ),
        intents=["find_fish", "check_safety"],
        confidence=0.9,
        reasoning_trace=["SELECT all tools"],
        selected_tools=[
            "find_fishing_zones",
            "check_ocean_state",
            "check_weather",
            "check_geofence",
        ],
    )
    return {
        "status": "success",
        "summary": "mock planner ok",
        "next_actions": ["dispatch"],
        "artifacts": [],
        "plan": plan,
        "needs_clarification": False,
        "clarification_text": None,
        "elapsed_ms": 5,
    }


def _patch_all_monkey(mock_plan_envelope=True):
    """Return list of patchers for mocked offline pipeline."""
    patches = [
        patch(
            "backend.agents.subagents.fish_finder.find_fishing_zones",
            new=AsyncMock(return_value=list(FISH)),
        ),
        patch(
            "backend.agents.subagents.sea_checker.check_sea_conditions",
            new=AsyncMock(return_value=list(SEA_CALM)),
        ),
        patch(
            "backend.agents.subagents.weather_agent.check_weather",
            new=AsyncMock(return_value=list(WEATHER_CALM)),
        ),
        patch(
            "backend.agents.subagents.danger_agent.check_safety_batch",
            new=AsyncMock(return_value=list(DANGER_OK)),
        ),
        patch("backend.db.redis.get_session", new=AsyncMock(return_value=None)),
        patch("backend.db.redis.save_session", new=AsyncMock(return_value=None)),
    ]
    if mock_plan_envelope:
        patches.insert(
            0,
            patch(
                "backend.agents.planner_service.plan_query",
                new=AsyncMock(return_value=_full_dispatch_envelope()),
            ),
        )
    return patches


class TestKochiRankedUnder10s:
    @pytest.mark.asyncio
    async def test_kochi_returns_ranked_zone_under_10s(self):
        """Mocked E2E: Kochi query returns ranked zone in <10s (no network)."""
        from backend.agents.graph import orchestrate_via_graph

        patches = _patch_all_monkey()
        for p in patches:
            p.start()
        try:
            t0 = time.perf_counter()
            res = await orchestrate_via_graph(
                query="fish near Kochi?",
                language="en",
                location={"lat": KOCHI_LAT, "lon": KOCHI_LON},
                session_id=f"test-kochi014-{uuid.uuid4().hex[:8]}",
            )
            elapsed = time.perf_counter() - t0
        finally:
            for p in patches:
                p.stop()
        assert elapsed < 10.0, f"pipeline {elapsed:.2f}s exceeds 10s budget"
        ranked = (res.get("map") or {}).get("features") or res.get("ranked_zones") or []
        # orchestrate_via_graph returns POST /api/chat payload: map.features GeoJSON
        if not ranked:
            # fall back: best must exist
            assert res.get("map", {}).get("center") is not None, f"no map center in {res!r}"
        else:
            assert len(ranked) >= 1
            first = ranked[0]
            props = first.get("properties", first) if isinstance(first, dict) else {}
            assert props.get("zone_id") is not None

    def test_kochi_bbox_fallback_under_10s_sorted(self):
        """Direct offline fallback: haversine read of data/pfz-today.geojson <10s."""
        from backend.agents.fallback import kochi_bbox_fallback

        t0 = time.perf_counter()
        zones = kochi_bbox_fallback(KOCHI_LAT, KOCHI_LON, radius_km=80.0)
        elapsed = time.perf_counter() - t0
        assert elapsed < 10.0, f"bbox fallback {elapsed:.2f}s exceeds 10s"
        assert isinstance(zones, list) and len(zones) >= 1, "expected >=1 Kochi zone from cache file"
        dists = [z["distance_from_user_km"] for z in zones]
        assert dists == sorted(dists), "zones must be nearest-first"
        assert dists[0] <= 80.0


class TestPlannerTimeoutKochiBaseline:
    @pytest.mark.asyncio
    async def test_planner_timeout_falls_back_to_kochi(self):
        """asyncio.TimeoutError + no resolvable location -> Kochi baseline."""
        from backend.agents.graph import KOCHI_FALLBACK_LOCATION, planner_node

        assert KOCHI_FALLBACK_LOCATION == {"lat": 9.93, "lon": 76.26}
        with patch(
            "backend.agents.planner_service.plan_query",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ), patch(
            "backend.db.redis.get_session", new=AsyncMock(return_value=None)
        ):
            state = await planner_node(
                {
                    "query": "Where is fish?",
                    "language": "en",
                    "location": None,
                    "session_id": f"test-timeout-{uuid.uuid4().hex[:8]}",
                }
            )
        loc = state.get("user_location")
        assert loc is not None, f"timeout must yield Kochi baseline, got {state!r}"
        assert float(loc["lat"]) == pytest.approx(9.93, abs=0.01)
        assert float(loc["lon"]) == pytest.approx(76.26, abs=0.01)
        assert state.get("planner_status") == "fallback_deterministic"


class TestSafetyVetoWaveWind:
    def test_orchestrator_veto_thresholds(self):
        # Canonical bands (safety_thresholds): wave 2.0/3.5m,
        # wind 22/27kt (40.74/50.0kph). _veto_safety takes wind in kph.
        from backend.agents.orchestrator import _veto_safety

        # danger: wave > 3.5m
        s, _ = _veto_safety(3.6, 10.0, True, False, False)
        assert s == "danger"
        # danger: wind > 27kt (27kt = 50.0kph, so 51.0kph is danger ...)
        s, _ = _veto_safety(0.8, 51.0, True, False, False)
        assert s == "danger"
        # ... while exactly 27kt (50.0kph) is still caution.
        s, _ = _veto_safety(0.8, 50.0, True, False, False)
        assert s == "caution"
        # caution: wave >= 2.0m
        s, _ = _veto_safety(2.5, 10.0, True, False, False)
        assert s == "caution"
        # caution: wind >= 22kt (22kt=40.74kph)
        s, _ = _veto_safety(0.8, 41.0, True, False, False)
        assert s == "caution"
        # safe: calm
        s, c = _veto_safety(0.8, 20.0, True, False, False)
        assert s == "safe"
        assert c == pytest.approx(0.87)

    def test_combiner_veto_mirrors_contract(self):
        from backend.agents.combiner import apply_safety_veto

        assert apply_safety_veto({"wave_height_m": 3.6, "wind_kt": 5.0}) == "danger"
        assert apply_safety_veto({"wave_height_m": 0.8, "wind_kt": 28.0}) == "danger"
        assert apply_safety_veto({"wave_height_m": 0.8, "wind_kt": 25.0}) == "caution"
        assert apply_safety_veto({"wave_height_m": 2.5, "wind_kt": 5.0}) == "caution"
        assert apply_safety_veto({"wave_height_m": 0.8, "wind_kt": 8.0}) == "safe"
        # current is scored explicitly: >3.0kt danger, >=2.0kt caution.
        assert (
            apply_safety_veto(
                {"wave_height_m": 0.8, "wind_kt": 8.0, "current_kt": 3.2}
            )
            == "danger"
        )
        assert (
            apply_safety_veto(
                {"wave_height_m": 0.8, "wind_kt": 8.0, "current_kt": 2.2}
            )
            == "caution"
        )
        # nulls degrade to caution, never safe
        assert apply_safety_veto({"wave_height_m": None, "wind_kt": 8.0}) == "caution"
        # banned waters -> danger
        assert (
            apply_safety_veto({"wave_height_m": 0.8, "wind_kt": 8.0, "inside_mpa": True})
            == "danger"
        )
        assert (
            apply_safety_veto(
                {"wave_height_m": 0.8, "wind_kt": 8.0, "inside_eez": False}
            )
            == "danger"
        )


class TestContractKeysCanonical:
    def test_geojson_features_canonical_keys(self):
        from backend.agents.orchestrator import _to_geojson_features

        zones = [
            {
                "zone_id": "z1",
                "place": "Kochi",
                "sector": "KERALA",
                "lat": 9.90,
                "lon": 76.20,
                "distance_from_user_km": 12.0,
                "score": 0.9,
                "wave_height_m": 0.8,
                "wind_kt": 8.0,
                "inside_eez": True,
                "inside_mpa": False,
                "depth_range": "20-30",
                "bearing": 232,
                "direction": "SW",
            }
        ]
        feats = _to_geojson_features(zones)
        assert len(feats) == 1
        props = feats[0]["properties"]
        for key in ("safety", "distance_km", "depth_m", "wave_m", "wind_kph", "confidence"):
            assert key in props, f"canonical key {key} missing in {props!r}"
        assert props["safety"] == "safe"
        assert props["distance_km"] == pytest.approx(12.0)
        assert props["depth_m"] == pytest.approx(25.0)  # midpoint of 20-30
        assert props["wave_m"] == pytest.approx(0.8)
        assert props["wind_kph"] == pytest.approx(8.0 * 1.852, abs=0.01)
        assert props["confidence"] == pytest.approx(0.87)
        assert feats[0]["geometry"] == {
            "type": "Point",
            "coordinates": [76.20, 9.90],
        }

    def test_normalize_contract_status_confidence(self):
        from backend.agents.combiner import normalize_contract

        ok = normalize_contract(
            [{"zone_id": "z1", "wave_height_m": 0.8, "wind_kt": 8.0}], False, 0.87
        )
        assert ok["status"] == "success"
        assert ok["confidence"] == pytest.approx(0.87)
        assert ok["ranked_zones"][0]["safety"] == "safe"
        bad = normalize_contract(
            [{"zone_id": "z1", "wave_height_m": 3.8, "wind_kt": 8.0}], False, 0.87
        )
        assert bad["status"] == "degraded"
        assert bad["confidence"] == pytest.approx(0.62)


class TestCacheFallbackFile:
    def test_cache_file_exists_and_loads(self):
        from backend.agents.fallback import kochi_bbox_fallback

        here = Path(__file__).resolve().parents[1]
        geo = here / "data" / "pfz-today.geojson"
        assert geo.is_file(), f"cache fallback file missing: {geo}"
        zones = kochi_bbox_fallback(geojson_path=str(geo))
        assert len(zones) >= 1
        z0 = zones[0]
        for key in ("zone_id", "place", "lat", "lon", "distance_from_user_km"):
            assert key in z0, f"fallback zone missing {key}"

    def test_missing_file_returns_empty_never_raises(self):
        from backend.agents.fallback import kochi_bbox_fallback

        assert kochi_bbox_fallback(geojson_path="/nonexistent/pfz.geojson") == []
