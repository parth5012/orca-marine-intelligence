"""
Comprehensive Multi-Agent Test Suite — ORCA Marine Intelligence
Ticket #19 — covers fish_finder, sea_checker, weather_agent, danger_agent, combiner, orchestrator
"""
import asyncio
import json
import math
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

# ---------------------------------------------------------------------------
# Fish Finder — distance, radius expansion, offline GeoJSON fallback
# ---------------------------------------------------------------------------

class TestFishFinder:
    def test_haversine_zero(self):
        from backend.agents.fish_finder import _haversine_km
        assert _haversine_km(10.0, 76.0, 10.0, 76.0) == pytest.approx(0.0)

    def test_haversine_known_distance(self):
        from backend.agents.fish_finder import _haversine_km
        # 1 degree latitude ~111.19 km
        d = _haversine_km(0.0, 0.0, 1.0, 0.0)
        assert d == pytest.approx(111.19, abs=0.6)
        # Kochi (9.93,76.26) to nearby point 0.5 deg north ~55.6 km
        d2 = _haversine_km(9.93, 76.26, 10.43, 76.26)
        assert d2 == pytest.approx(55.6, abs=0.6)

    def test_haversine_symmetry(self):
        from backend.agents.fish_finder import _haversine_km
        a = _haversine_km(12.0, 77.0, 13.0, 78.0)
        b = _haversine_km(13.0, 78.0, 12.0, 77.0)
        assert a == pytest.approx(b)

    @pytest.mark.asyncio
    async def test_radius_expansion_80_to_120_to_160(self):
        from backend.agents import fish_finder

        # Mock find_pfz_near: empty at 80, zones at 120
        call_radii = []

        async def fake_find_pfz_near(lat, lon, radius_km, limit):
            call_radii.append(radius_km)
            if radius_km < 120:
                return []
            return [
                {
                    "zone_id": "SEC005_Pallithottam_0",
                    "place": "Pallithottam",
                    "sector": "KERALA",
                    "bearing": 180,
                    "direction": "S",
                    "depth_range": "20-30",
                    "lat": 10.0,
                    "lon": 76.3,
                    "distance_from_user_km": 12.0,
                }
            ]

        with patch("backend.db.postgis.find_pfz_near", side_effect=fake_find_pfz_near):
            zones = await fish_finder.find_fishing_zones(lat=9.93, lon=76.26, radius_km=80.0, limit=5)
        assert len(zones) == 1
        assert zones[0]["place"] == "Pallithottam"
        assert 80.0 in call_radii
        assert 120.0 in call_radii
        # Should stop after finding at 120, not call 160
        assert 160.0 not in call_radii

    @pytest.mark.asyncio
    async def test_radius_expansion_to_160_when_120_empty(self):
        from backend.agents import fish_finder

        async def fake_find_pfz_near(lat, lon, radius_km, limit):
            if radius_km < 160:
                return []
            return [
                {
                    "zone_id": "SEC005_Far_0",
                    "place": "FarZone",
                    "sector": "KERALA",
                    "bearing": 90,
                    "direction": "E",
                    "depth_range": "30-40",
                    "lat": 9.5,
                    "lon": 77.0,
                    "distance_from_user_km": 150.0,
                }
            ]

        with patch("backend.db.postgis.find_pfz_near", side_effect=fake_find_pfz_near):
            zones = await fish_finder.find_fishing_zones(lat=9.93, lon=76.26, radius_km=80.0)
        assert len(zones) == 1
        assert zones[0]["place"] == "FarZone"

    @pytest.mark.asyncio
    async def test_offline_geojson_fallback_on_db_failure(self):
        from backend.agents import fish_finder

        fake_features = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"place": "NearFish", "sector": "SEC005", "sector_name": "KERALA"},
                    "geometry": {"type": "Point", "coordinates": [76.26, 9.93]},
                },
                {
                    "type": "Feature",
                    "properties": {"place": "FarFish", "sector": "SEC005", "sector_name": "KERALA"},
                    "geometry": {"type": "Point", "coordinates": [76.26 + 1.0, 9.93]},
                },
            ],
        }

        async def failing_find(*args, **kwargs):
            raise ConnectionError("PostGIS down")

        with patch("backend.db.postgis.find_pfz_near", side_effect=failing_find):
            with patch.object(fish_finder, "_load_geojson_features", return_value=fake_features["features"]):
                zones = await fish_finder.find_fishing_zones(lat=9.93, lon=76.26, radius_km=80.0, limit=5)

        # NearFish at same coords distance 0 should be returned; sorted ascending
        assert len(zones) >= 1
        assert zones[0]["place"] == "NearFish"
        assert zones[0]["distance_from_user_km"] == pytest.approx(0.0, abs=0.2)

    @pytest.mark.asyncio
    async def test_geojson_fallback_no_data_returns_empty(self):
        from backend.agents import fish_finder

        async def failing_find(*args, **kwargs):
            raise RuntimeError("DB fail")

        with patch("backend.db.postgis.find_pfz_near", side_effect=failing_find):
            with patch.object(fish_finder, "_load_geojson_features", return_value=[]):
                zones = await fish_finder.find_fishing_zones(lat=9.93, lon=76.26, radius_km=80.0)
        assert zones == []

    def test_geojson_fallback_filters_by_sector_and_distance(self):
        from backend.agents.fish_finder import _geojson_fallback

        # Create features: one Kerala near, one Maharashtra far, one Kerala far beyond 80
        features = [
            {
                "type": "Feature",
                "properties": {"place": "KochiNear", "sector": "SEC005", "sector_name": "KERALA"},
                "geometry": {"type": "Point", "coordinates": [76.26, 9.93]},
            },
            {
                "type": "Feature",
                "properties": {"place": "MahaFar", "sector": "SEC002", "sector_name": "MAHARASHTRA"},
                "geometry": {"type": "Point", "coordinates": [72.3, 20.0]},
            },
        ]
        with patch("backend.agents.fish_finder._load_geojson_features", return_value=features):
            # Within 80km should return only KochiNear
            res = _geojson_fallback(lat=9.93, lon=76.26, radius_km=80.0, limit=5, sector=None)
            assert any(r["place"] == "KochiNear" for r in res)
            assert not any(r["place"] == "MahaFar" for r in res)

            # Sector filter KERALA
            res2 = _geojson_fallback(lat=9.93, lon=76.26, radius_km=2000, limit=5, sector="KERALA")
            assert all("KERALA" in r["sector"].upper() for r in res2)
            assert not any(r["place"] == "MahaFar" for r in res2)

    def test_geojson_fallback_respects_limit_and_sorting(self):
        from backend.agents.fish_finder import _geojson_fallback

        features = []
        for i in range(5):
            # Each 0.1 deg lon offset ~10km at equator approx
            features.append(
                {
                    "type": "Feature",
                    "properties": {"place": f"Zone{i}", "sector": "SEC005", "sector_name": "KERALA"},
                    "geometry": {"type": "Point", "coordinates": [76.26 + i * 0.1, 9.93]},
                }
            )
        with patch("backend.agents.fish_finder._load_geojson_features", return_value=features):
            res = _geojson_fallback(lat=9.93, lon=76.26, radius_km=500, limit=2, sector=None)
            assert len(res) == 2
            # Sorted by distance ascending
            assert res[0]["distance_from_user_km"] <= res[1]["distance_from_user_km"]
            assert res[0]["place"] == "Zone0"


# ---------------------------------------------------------------------------
# Sea Checker — thresholds
# ---------------------------------------------------------------------------

class TestSeaChecker:
    def test_classify_wave_thresholds(self):
        from backend.agents.sea_checker import _classify_wave, WAVE_SAFE_MAX, WAVE_CAUTION_MAX
        assert WAVE_SAFE_MAX == 1.5
        assert WAVE_CAUTION_MAX == 2.5
        assert _classify_wave(0.8) == "safe"
        assert _classify_wave(1.4) == "safe"
        assert _classify_wave(1.5) == "caution"
        assert _classify_wave(2.0) == "caution"
        assert _classify_wave(2.5) == "caution"
        assert _classify_wave(2.51) == "danger"
        assert _classify_wave(3.0) == "danger"

    def test_classify_current_thresholds(self):
        from backend.agents.sea_checker import _classify_current
        assert _classify_current(1.0) == "safe"
        assert _classify_current(2.0) == "safe"
        assert _classify_current(2.1) == "caution"
        assert _classify_current(2.9) == "caution"
        assert _classify_current(3.0) == "caution"
        assert _classify_current(3.01) == "danger"
        assert _classify_current(4.0) == "danger"

    def test_overall_status_worst_wins(self):
        from backend.agents.sea_checker import _overall_status
        assert _overall_status("safe", "safe") == "safe"
        assert _overall_status("safe", "caution") == "caution"
        assert _overall_status("caution", "safe") == "caution"
        assert _overall_status("caution", "danger") == "danger"
        assert _overall_status("danger", "safe") == "danger"

    @pytest.mark.asyncio
    async def test_check_sea_conditions_classifications(self):
        from backend.agents import sea_checker

        points = [
            {"zone_id": "z1", "place": "SafeZone", "lat": 10.0, "lon": 76.0},
            {"zone_id": "z2", "place": "CautionZone", "lat": 10.1, "lon": 76.1},
            {"zone_id": "z3", "place": "DangerZone", "lat": 10.2, "lon": 76.2},
        ]

        async def fake_get_wave_current(lat, lon, zone_id, idx):
            mapping = {
                "z1": (0.8, 1.0, "mock_heuristic"),   # safe wave, safe current -> safe
                "z2": (2.0, 1.0, "mock_heuristic"),   # caution wave -> caution
                "z3": (3.0, 1.0, "mock_heuristic"),   # danger wave -> danger
            }
            return mapping[zone_id]

        with patch.object(sea_checker, "get_wave_current", side_effect=fake_get_wave_current):
            results = await sea_checker.check_sea_conditions(points)

        assert len(results) == 3
        assert results[0]["status"] == "safe"
        assert results[0]["wave_status"] == "safe"
        assert results[1]["status"] == "caution"
        assert results[1]["wave_status"] == "caution"
        assert results[2]["status"] == "danger"
        assert results[2]["wave_status"] == "danger"

    @pytest.mark.asyncio
    async def test_check_sea_current_overrides_wave(self):
        from backend.agents import sea_checker

        points = [{"zone_id": "z1", "place": "CurrentDanger", "lat": 10.0, "lon": 76.0}]

        async def fake_get(lat, lon, zone_id, idx):
            return (0.8, 3.5, "mock_heuristic")  # safe wave but danger current

        with patch.object(sea_checker, "get_wave_current", side_effect=fake_get):
            results = await sea_checker.check_sea_conditions(points)
        assert results[0]["current_status"] == "danger"
        assert results[0]["status"] == "danger"

    @pytest.mark.asyncio
    async def test_check_sea_empty_and_invalid(self):
        from backend.agents import sea_checker
        assert await sea_checker.check_sea_conditions([]) == []
        # invalid point non-dict
        res = await sea_checker.check_sea_conditions([None])
        assert res[0]["status"] == "safe"
        assert "invalid" in res[0]["reason"].lower()


# ---------------------------------------------------------------------------
# Weather Agent — thresholds
# ---------------------------------------------------------------------------

class TestWeatherAgent:
    def test_classify_wind_thresholds(self):
        from backend.agents.weather_agent import _classify_wind, WIND_SAFE_MAX, WIND_CAUTION_MAX
        assert WIND_SAFE_MAX == 15.0
        assert WIND_CAUTION_MAX == 25.0
        assert _classify_wind(10.0) == "safe"
        assert _classify_wind(14.9) == "safe"
        assert _classify_wind(15.0) == "caution"
        assert _classify_wind(20.0) == "caution"
        assert _classify_wind(25.0) == "caution"
        assert _classify_wind(25.1) == "danger"
        assert _classify_wind(30.0) == "danger"

    def test_overall_status_cyclone_forces_danger(self):
        from backend.agents.weather_agent import _overall_status
        assert _overall_status("safe", False) == "safe"
        assert _overall_status("caution", False) == "caution"
        assert _overall_status("safe", True) == "danger"
        assert _overall_status("danger", True) == "danger"

    @pytest.mark.asyncio
    async def test_check_weather_cyclone_alert_forces_danger(self):
        from backend.agents import weather_agent

        points = [{"zone_id": "z1", "place": "CycloneZone", "lat": 10.0, "lon": 76.0}]

        async def fake_get_wind(lat, lon, zone_id, idx):
            return (10.0, "NE", 45, "mock_heuristic")  # safe wind

        async def fake_cyclone(lat, lon, cyclones=None):
            return (True, 100.0, "Tauktae", {"name": "Tauktae"})  # cyclone within 500km

        with patch.object(weather_agent, "get_wind", side_effect=fake_get_wind):
            with patch.object(weather_agent, "get_cyclone_alert", side_effect=fake_cyclone):
                with patch.object(weather_agent, "fetch_imd_cyclones", return_value=[{"name": "Tauktae", "lat": 10.0, "lon": 76.5}]):
                    results = await weather_agent.check_weather(points)
        assert results[0]["wind_status"] == "safe"
        assert results[0]["cyclone_alert"] is True
        assert results[0]["status"] == "danger"

    @pytest.mark.asyncio
    async def test_check_weather_wind_thresholds(self):
        from backend.agents import weather_agent

        points = [
            {"zone_id": "z1", "place": "SafeWind", "lat": 10.0, "lon": 76.0},
            {"zone_id": "z2", "place": "CautionWind", "lat": 10.1, "lon": 76.1},
            {"zone_id": "z3", "place": "DangerWind", "lat": 10.2, "lon": 76.2},
        ]

        async def fake_get_wind(lat, lon, zone_id, idx):
            mapping = {
                "z1": (10.0, "N", 0, "mock_heuristic"),
                "z2": (20.0, "E", 90, "mock_heuristic"),
                "z3": (30.0, "S", 180, "mock_heuristic"),
            }
            return mapping[zone_id]

        with patch.object(weather_agent, "get_wind", side_effect=fake_get_wind):
            with patch.object(weather_agent, "get_cyclone_alert", return_value=(False, None, None, None)):
                with patch.object(weather_agent, "fetch_imd_cyclones", return_value=[]):
                    results = await weather_agent.check_weather(points)
        assert results[0]["status"] == "safe"
        assert results[0]["wind_status"] == "safe"
        assert results[1]["status"] == "caution"
        assert results[1]["wind_status"] == "caution"
        assert results[2]["status"] == "danger"
        assert results[2]["wind_status"] == "danger"

    @pytest.mark.asyncio
    async def test_get_cyclone_alert_distance_logic(self):
        from backend.agents.weather_agent import get_cyclone_alert

        # Cyclone at 10.5,76.5 ~71km from 10.0,76.0 -> within 500 -> alert True
        cyclones = [{"name": "TestCyclone", "lat": 10.5, "lon": 76.5}]
        alert, dist, name, nearest = await get_cyclone_alert(10.0, 76.0, cyclones=cyclones)
        assert alert is True
        assert dist is not None and dist < 500
        assert name == "TestCyclone"

        # Far cyclone >500km
        far = [{"name": "FarCyclone", "lat": 20.0, "lon": 80.0}]
        alert2, dist2, _, _ = await get_cyclone_alert(10.0, 76.0, cyclones=far)
        assert alert2 is False


# ---------------------------------------------------------------------------
# Danger Agent — EEZ / MPA / 2km IMBL
# ---------------------------------------------------------------------------

class TestDangerAgent:
    @pytest.mark.asyncio
    async def test_inside_eez_safe(self):
        from backend.agents import danger_agent
        # Mock PostGIS success: inside EEZ, outside MPA
        async def mock_check_geofence(lat, lon):
            return {"inside_eez": True, "inside_mpa": False, "mpa_name": None, "status": "safe", "reason": "ok"}
        with patch("backend.db.postgis.check_geofence", side_effect=mock_check_geofence):
            with patch.object(danger_agent, "_fallback_distance_to_imbl", return_value=50.0):
                res = await danger_agent.check_safety(lat=9.93, lon=76.26)
        assert res["inside_eez"] is True
        assert res["inside_mpa"] is False
        assert res["status"] == "safe"
        assert res["is_safe"] is True

    @pytest.mark.asyncio
    async def test_inside_mpa_forbidden_danger(self):
        from backend.agents import danger_agent
        async def mock_check_geofence(lat, lon):
            return {"inside_eez": True, "inside_mpa": True, "mpa_name": "Gulf of Mannar", "status": "danger", "reason": "MPA"}
        with patch("backend.db.postgis.check_geofence", side_effect=mock_check_geofence):
            with patch.object(danger_agent, "_fallback_distance_to_imbl", return_value=10.0):
                res = await danger_agent.check_safety(lat=9.0, lon=79.0)
        assert res["inside_mpa"] is True
        assert res["mpa_name"] == "Gulf of Mannar"
        assert res["status"] == "danger"
        assert res["is_safe"] is False
        assert any("Marine Protected Area" in w for w in res["warnings"])

    @pytest.mark.asyncio
    async def test_outside_eez_danger(self):
        from backend.agents import danger_agent
        async def mock_check_geofence(lat, lon):
            return {"inside_eez": False, "inside_mpa": False, "mpa_name": None, "status": "danger", "reason": "Outside EEZ"}
        with patch("backend.db.postgis.check_geofence", side_effect=mock_check_geofence):
            with patch.object(danger_agent, "_fallback_distance_to_imbl", return_value=5.0):
                res = await danger_agent.check_safety(lat=25.0, lon=80.0)
        assert res["inside_eez"] is False
        assert res["status"] == "danger"
        assert res["is_safe"] is False
        assert any("Exclusive Economic Zone" in w for w in res["warnings"])

    @pytest.mark.asyncio
    async def test_2km_imbl_boundary_warning_caution(self):
        from backend.agents import danger_agent
        async def mock_check_geofence(lat, lon):
            return {"inside_eez": True, "inside_mpa": False, "mpa_name": None, "status": "safe", "reason": "ok"}
        # Distance 1.5km should trigger caution
        with patch("backend.db.postgis.check_geofence", side_effect=mock_check_geofence):
            with patch.object(danger_agent, "_fallback_distance_to_imbl", return_value=1.5):
                res = await danger_agent.check_safety(lat=9.93, lon=76.26, check_imbl=True)
        assert res["status"] == "caution"
        assert res["is_safe"] is False
        assert any("International Maritime Boundary" in w for w in res["warnings"])
        assert any("1.5km" in w for w in res["warnings"])

    @pytest.mark.asyncio
    async def test_imbl_caution_not_triggered_beyond_2km(self):
        from backend.agents import danger_agent
        async def mock_check_geofence(lat, lon):
            return {"inside_eez": True, "inside_mpa": False, "mpa_name": None, "status": "safe", "reason": "ok"}
        with patch("backend.db.postgis.check_geofence", side_effect=mock_check_geofence):
            with patch.object(danger_agent, "_fallback_distance_to_imbl", return_value=5.0):
                res = await danger_agent.check_safety(lat=9.93, lon=76.26, check_imbl=True)
        assert res["status"] == "safe"
        assert res["is_safe"] is True

    @pytest.mark.asyncio
    async def test_fallback_raycasting_when_postgis_down(self):
        from backend.agents import danger_agent
        # PostGIS raises, fallback should be used
        async def failing_check(lat, lon):
            raise ConnectionError("PostGIS down")

        # Mock fallback helpers to simulate inside EEZ but near boundary
        with patch("backend.db.postgis.check_geofence", side_effect=failing_check):
            with patch.object(danger_agent, "_fallback_check_eez", return_value=(True, 0.8)):
                with patch.object(danger_agent, "_fallback_check_mpa", return_value=(False, None)):
                    with patch.object(danger_agent, "_load_cached_geojson", return_value=([[[[76.0, 9.5], [76.5, 9.5], [76.5, 10.0], [76.0, 10.0], [76.0, 9.5]]]], [{}])):
                        # Actually we already mocked the helpers, so distance will be 0.8 which <2 -> caution
                        res = await danger_agent.check_safety(lat=9.93, lon=76.26)
        # Should not raise, and produce a result shape with required keys
        assert "is_safe" in res
        assert "status" in res
        assert "warnings" in res
        assert "inside_eez" in res
        assert "inside_mpa" in res
        assert "mpa_name" in res

    @pytest.mark.asyncio
    async def test_invalid_coordinates_danger(self):
        from backend.agents import danger_agent
        res = await danger_agent.check_safety(lat=999, lon=999)
        assert res["status"] == "danger"
        assert res["is_safe"] is False

    @pytest.mark.asyncio
    async def test_check_safety_batch_preserves_order(self):
        from backend.agents import danger_agent
        async def mock_check_geofence(lat, lon):
            return {"inside_eez": True, "inside_mpa": False, "mpa_name": None}
        with patch("backend.db.postgis.check_geofence", side_effect=mock_check_geofence):
            with patch.object(danger_agent, "_fallback_distance_to_imbl", return_value=10.0):
                pts = [{"lat": 9.93, "lon": 76.26}, {"lat": 10.0, "lon": 76.3}]
                results = await danger_agent.check_safety_batch(pts)
        assert len(results) == 2
        assert results[0]["lat"] == pytest.approx(9.93)
        assert results[1]["lat"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Combiner — scoring formula + benchmark case
# ---------------------------------------------------------------------------

class TestCombiner:
    def test_scoring_formula_exact(self):
        from backend.agents.combiner import combine_and_rank
        fish = [
            {"zone_id": "z1", "place": "A", "sector": "KERALA", "lat": 10.0, "lon": 76.0, "distance_from_user_km": 10.0},
        ]
        sea = [{"zone_id": "z1", "wave_height_m": 0.8}]
        weather = [{"zone_id": "z1", "wind_kt": 10.0}]
        danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}]
        result = combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
        best = result["best"]
        # closest = 1.0 (single zone), safe_sea=1.0 (<1.5), wind_ok=1.0 (<15), not_banned=1.0
        # score = 0.4*1 +0.3*1+0.2*1+0.1*1 =1.0
        assert best["score"] == pytest.approx(1.0, abs=0.0001)
        assert best["score_breakdown"]["closest"] == pytest.approx(1.0, abs=0.0001)
        assert best["score_breakdown"]["safe_sea"] == pytest.approx(1.0, abs=0.0001)
        assert best["score_breakdown"]["wind_ok"] == pytest.approx(1.0, abs=0.0001)
        assert best["score_breakdown"]["not_banned"] == 1.0

    def test_scoring_wave_and_wind_degradation(self):
        from backend.agents.combiner import combine_and_rank
        # wave 3.0 -> safe_sea = 1 - (3.0-1.5)/1.5 =0.0, wind 30 -> 0.0
        fish = [{"zone_id": "z1", "place": "Rough", "sector": "K", "lat": 10.0, "lon": 76.0, "distance_from_user_km": 10.0}]
        sea = [{"zone_id": "z1", "wave_height_m": 3.0}]
        weather = [{"zone_id": "z1", "wind_kt": 30.0}]
        danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}]
        result = combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
        bd = result["best"]["score_breakdown"]
        assert bd["safe_sea"] == pytest.approx(0.0, abs=0.0001)
        assert bd["wind_ok"] == pytest.approx(0.0, abs=0.0001)
        # banned
        danger2 = [{"zone_id": "z1", "inside_eez": False, "inside_mpa": False}]
        result2 = combine_and_rank(fish, sea, weather, danger2, {"lat": 9.93, "lon": 76.26})
        assert result2["best"]["score_breakdown"]["not_banned"] == 0.0

    def test_benchmark_pallithottam_beats_mampally(self):
        """Pallithottam 12km/0.8m calm beats closer Mampally 8km/2.8m rough."""
        from backend.agents.combiner import combine_and_rank
        fish = [
            {"zone_id": "mampally", "place": "Mampally", "sector": "KERALA", "lat": 10.05, "lon": 76.3, "distance_from_user_km": 8.0},
            {"zone_id": "pallithottam", "place": "Pallithottam", "sector": "KERALA", "lat": 9.9, "lon": 76.2, "distance_from_user_km": 12.0},
        ]
        sea = [
            {"zone_id": "mampally", "wave_height_m": 2.8},
            {"zone_id": "pallithottam", "wave_height_m": 0.8},
        ]
        weather = [
            {"zone_id": "mampally", "wind_kt": 10.0},
            {"zone_id": "pallithottam", "wind_kt": 10.0},
        ]
        danger = [
            {"zone_id": "mampally", "inside_eez": True, "inside_mpa": False},
            {"zone_id": "pallithottam", "inside_eez": True, "inside_mpa": False},
        ]
        result = combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
        ranked = result["ranked_zones"]
        # Pallithottam should be rank 0 despite being farther, because Mampally rough sea penalizes heavily
        assert ranked[0]["place"] == "Pallithottam"
        assert ranked[0]["zone_id"] == "pallithottam"
        assert ranked[1]["place"] == "Mampally"
        # Verify scoring: Mampally closest 0.333, safe_sea 0.133; Pallithottam closest 0.0, safe_sea 1.0 -> Pallithottam higher overall
        # max_dist=12, Mampally closest 1-8/12=0.333, Pallithottam 0.0
        # Mampally score 0.333*0.4 +0.133*0.3+1*0.2+0.1 =0.133+0.04+0.2+0.1=0.473
        # Pallithottam 0*0.4 +1*0.3+1*0.2+0.1=0.6
        assert ranked[0]["score"] > ranked[1]["score"]
        assert result["best"]["place"] == "Pallithottam"

    def test_all_unsafe_advisory_generation(self):
        from backend.agents.combiner import combine_and_rank
        fish = [
            {"zone_id": "z1", "place": "Rough1", "sector": "K", "lat": 10.0, "lon": 76.0, "distance_from_user_km": 8.0},
            {"zone_id": "z2", "place": "Rough2", "sector": "K", "lat": 10.1, "lon": 76.1, "distance_from_user_km": 12.0},
        ]
        sea = [{"zone_id": "z1", "wave_height_m": 3.0}, {"zone_id": "z2", "wave_height_m": 2.8}]
        weather = [{"zone_id": "z1", "wind_kt": 30.0}, {"zone_id": "z2", "wind_kt": 28.0}]
        danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}, {"zone_id": "z2", "inside_eez": True, "inside_mpa": False}]
        result = combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
        assert result["all_unsafe"] is True
        assert "DO NOT SAIL" in result["explanation"] or "Do NOT sail" in result["explanation"]
        assert result["best"] is not None

    def test_empty_fish_returns_no_best(self):
        from backend.agents.combiner import combine_and_rank
        result = combine_and_rank([], [], [], [], {"lat": 9.93, "lon": 76.26})
        assert result["ranked_zones"] == []
        assert result["best"] is None
        assert result["all_unsafe"] is False
        assert "No fishing zones" in result["explanation"]

    def test_tie_breaker_lower_wave_wins(self):
        from backend.agents.combiner import combine_and_rank
        # Two zones same distance and same other scores, tie breaker is lower wave
        # To force same closest, set same distance
        fish = [
            {"zone_id": "z1", "place": "A", "sector": "K", "lat": 10.0, "lon": 76.0, "distance_from_user_km": 10.0},
            {"zone_id": "z2", "place": "B", "sector": "K", "lat": 10.0, "lon": 76.0, "distance_from_user_km": 10.0},
        ]
        # Both wave <1.5 so safe_sea 1.0, but different wave values still safe but tie breaker wave
        sea = [{"zone_id": "z1", "wave_height_m": 0.5}, {"zone_id": "z2", "wave_height_m": 1.2}]
        weather = [{"zone_id": "z1", "wind_kt": 10.0}, {"zone_id": "z2", "wind_kt": 10.0}]
        danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}, {"zone_id": "z2", "inside_eez": True, "inside_mpa": False}]
        result = combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
        # Same score -> lower wave (0.5) should be first
        assert result["ranked_zones"][0]["place"] == "A"
        assert result["ranked_zones"][0]["wave_height_m"] == pytest.approx(0.5)

    def test_citation_contains_incois_and_date(self):
        from backend.agents.combiner import combine_and_rank
        fish = [{"zone_id": "z1", "place": "TestPlace", "sector": "KERALA", "lat": 10.0, "lon": 76.0, "distance_from_user_km": 5.0}]
        result = combine_and_rank(fish, [], [], [], {"lat": 9.93, "lon": 76.26})
        assert "INCOIS" in result["citation"]
        assert "TestPlace" in result["citation"]


# ---------------------------------------------------------------------------
# Orchestrator — parallel gather, 10s timeout resilience, Malayalam, all-unsafe
# ---------------------------------------------------------------------------

class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_parallel_gather_efficiency(self):
        """All three agents should run concurrently, not sequentially."""
        from backend.agents import orchestrator

        shared = [
            {"zone_id": "z1", "place": "A", "lat": 10.0, "lon": 76.0, "distance_from_user_km": 5.0, "bearing": 90, "direction": "E", "depth_range": "20-30", "sector": "KERALA"},
        ]
        # Each secondary agent sleeps 0.15s; sequential would be >0.45s, parallel ~0.15s
        async def mock_fish(lat, lon, radius_km=80.0, **kwargs):
            return shared

        async def mock_sea(points):
            await asyncio.sleep(0.15)
            return [{"zone_id": "z1", "place": "A", "lat": 10.0, "lon": 76.0, "wave_height_m": 0.8, "current_kt": 1.0, "wave_status": "safe", "current_status": "safe", "status": "safe", "reason": "ok", "source": "mock_heuristic"}]

        async def mock_weather(points):
            await asyncio.sleep(0.15)
            return [{"zone_id": "z1", "place": "A", "lat": 10.0, "lon": 76.0, "wind_kt": 10.0, "wind_speed_kt": 10.0, "wind_dir": "N", "wind_direction": "N", "wind_deg": 0, "wind_status": "safe", "cyclone_alert": False, "nearest_cyclone_km": None, "cyclone_name": None, "status": "safe", "reason": "ok", "source": "mock_heuristic"}]

        async def mock_danger(points, **kwargs):
            await asyncio.sleep(0.15)
            return [{"zone_id": "z1", "place": "A", "lat": 10.0, "lon": 76.0, "is_safe": True, "status": "safe", "warnings": [], "inside_eez": True, "inside_mpa": False, "mpa_name": None}]

        with patch("backend.agents.fish_finder.find_fishing_zones", side_effect=mock_fish):
            with patch("backend.agents.sea_checker.check_sea_conditions", side_effect=mock_sea):
                with patch("backend.agents.weather_agent.check_weather", side_effect=mock_weather):
                    with patch("backend.agents.danger_agent.check_safety_batch", side_effect=mock_danger):
                        with patch("backend.db.redis.get_session", new=AsyncMock(return_value=None)):
                            with patch("backend.db.redis.save_session", new=AsyncMock(return_value=None)):
                                import time
                                t0 = time.perf_counter()
                                result = await orchestrator.orchestrate(query="Where is fish?", language="en", location={"lat": 9.93, "lon": 76.26}, session_id="test-parallel")
                                elapsed = time.perf_counter() - t0

        # Parallel should be well under 0.4s (allowing overhead)
        assert elapsed < 0.40, f"Gather not parallel, elapsed {elapsed:.3f}s >0.40s"
        # Verify result has expected shape
        assert "reply" in result
        assert "map" in result
        assert "safety" in result
        assert len(result["map"]["pfz_features"]) == 1

    @pytest.mark.asyncio
    async def test_timeout_resilience_one_agent_fails(self):
        """If one agent times out, orchestrator degrades that agent to unknown but still returns."""
        from backend.agents import orchestrator

        shared = [
            {"zone_id": "z1", "place": "A", "lat": 10.0, "lon": 76.0, "distance_from_user_km": 5.0, "bearing": 90, "direction": "E", "depth_range": "20-30", "sector": "KERALA"},
        ]

        async def mock_fish(lat, lon, radius_km=80.0, **kwargs):
            return shared

        async def mock_sea_timeout(points):
            await asyncio.sleep(11)  # will exceed 10s wait_for
            return []

        async def mock_weather_ok(points):
            return [{"zone_id": "z1", "place": "A", "lat": 10.0, "lon": 76.0, "wind_kt": 10.0, "wind_speed_kt": 10.0, "wind_dir": "N", "wind_direction": "N", "wind_deg": 0, "wind_status": "safe", "cyclone_alert": False, "nearest_cyclone_km": None, "cyclone_name": None, "status": "safe", "reason": "ok", "source": "mock_heuristic"}]

        async def mock_danger_ok(points, **kwargs):
            return [{"zone_id": "z1", "place": "A", "lat": 10.0, "lon": 76.0, "is_safe": True, "status": "safe", "warnings": [], "inside_eez": True, "inside_mpa": False, "mpa_name": None}]

        with patch("backend.agents.fish_finder.find_fishing_zones", side_effect=mock_fish):
            with patch("backend.agents.sea_checker.check_sea_conditions", side_effect=mock_sea_timeout):
                with patch("backend.agents.weather_agent.check_weather", side_effect=mock_weather_ok):
                    with patch("backend.agents.danger_agent.check_safety_batch", side_effect=mock_danger_ok):
                        with patch("backend.db.redis.get_session", new=AsyncMock(return_value=None)):
                            with patch("backend.db.redis.save_session", new=AsyncMock(return_value=None)):
                                result = await orchestrator.orchestrate(query="Where is fish?", language="en", location={"lat": 9.93, "lon": 76.26}, session_id="test-timeout")

        # Should not raise, should return degraded confidence and amber badge due to unknown sea
        assert result is not None
        assert result["confidence"] == pytest.approx(0.62, abs=0.01)
        assert result["safety"]["badge"] == "amber"

    @pytest.mark.asyncio
    async def test_malayalam_query_handling(self):
        """Malayalam 'എവിടെ മത്സ്യം?' should be treated as wants_fish and location-resolved."""
        from backend.agents import orchestrator

        # Test intent parsing directly
        intent = orchestrator._parse_intent("എവിടെ മത്സ്യം?")
        assert intent["wants_fish"] is True

        # Full orchestrate with Malayalam query + explicit location should return normally (not prompt for location)
        shared = [
            {"zone_id": "z1", "place": "Pallithottam", "lat": 10.0, "lon": 76.0, "distance_from_user_km": 5.0, "bearing": 90, "direction": "E", "depth_range": "20-30", "sector": "KERALA"},
        ]

        async def mock_fish(lat, lon, radius_km=80.0, **kwargs):
            return shared

        async def mock_sea(points):
            return [{"zone_id": "z1", "place": "Pallithottam", "lat": 10.0, "lon": 76.0, "wave_height_m": 0.8, "current_kt": 1.0, "wave_status": "safe", "current_status": "safe", "status": "safe", "reason": "ok", "source": "mock_heuristic"}]

        async def mock_weather(points):
            return [{"zone_id": "z1", "place": "Pallithottam", "lat": 10.0, "lon": 76.0, "wind_kt": 10.0, "wind_speed_kt": 10.0, "wind_dir": "N", "wind_direction": "N", "wind_deg": 0, "wind_status": "safe", "cyclone_alert": False, "nearest_cyclone_km": None, "cyclone_name": None, "status": "safe", "reason": "ok", "source": "mock_heuristic"}]

        async def mock_danger(points, **kwargs):
            return [{"zone_id": "z1", "place": "Pallithottam", "lat": 10.0, "lon": 76.0, "is_safe": True, "status": "safe", "warnings": [], "inside_eez": True, "inside_mpa": False, "mpa_name": None}]

        with patch("backend.agents.fish_finder.find_fishing_zones", side_effect=mock_fish):
            with patch("backend.agents.sea_checker.check_sea_conditions", side_effect=mock_sea):
                with patch("backend.agents.weather_agent.check_weather", side_effect=mock_weather):
                    with patch("backend.agents.danger_agent.check_safety_batch", side_effect=mock_danger):
                        with patch("backend.db.redis.get_session", new=AsyncMock(return_value=None)):
                            with patch("backend.db.redis.save_session", new=AsyncMock(return_value=None)):
                                result = await orchestrator.orchestrate(query="എവിടെ മത്സ്യം?", language="ml", location={"lat": 9.93, "lon": 76.26}, session_id="test-ml")

        assert result["language"] == "ml"
        assert result["map"]["center"] is not None
        assert "Pallithottam" in result["reply"] or "INCOIS" in result["evidence"][0]

    @pytest.mark.asyncio
    async def test_all_unsafe_advisory_generation(self):
        """When combiner says all_unsafe, reply should contain DO NOT SAIL advisory."""
        from backend.agents import orchestrator

        shared = [
            {"zone_id": "z1", "place": "Rough1", "lat": 10.0, "lon": 76.0, "distance_from_user_km": 5.0, "bearing": 90, "direction": "E", "depth_range": "20-30", "sector": "KERALA"},
            {"zone_id": "z2", "place": "Rough2", "lat": 10.1, "lon": 76.1, "distance_from_user_km": 8.0, "bearing": 90, "direction": "E", "depth_range": "20-30", "sector": "KERALA"},
        ]

        async def mock_fish(lat, lon, radius_km=80.0, **kwargs):
            return shared

        # Force all zones unsafe: high wave + high wind
        async def mock_sea(points):
            return [
                {"zone_id": "z1", "place": "Rough1", "lat": 10.0, "lon": 76.0, "wave_height_m": 3.0, "current_kt": 1.0, "wave_status": "danger", "current_status": "safe", "status": "danger", "reason": "wave 3.0m danger", "source": "mock_heuristic"},
                {"zone_id": "z2", "place": "Rough2", "lat": 10.1, "lon": 76.1, "wave_height_m": 2.8, "current_kt": 1.0, "wave_status": "danger", "current_status": "safe", "status": "danger", "reason": "wave 2.8m danger", "source": "mock_heuristic"},
            ]

        async def mock_weather(points):
            return [
                {"zone_id": "z1", "place": "Rough1", "lat": 10.0, "lon": 76.0, "wind_kt": 30.0, "wind_speed_kt": 30.0, "wind_dir": "S", "wind_direction": "S", "wind_deg": 180, "wind_status": "danger", "cyclone_alert": False, "nearest_cyclone_km": None, "cyclone_name": None, "status": "danger", "reason": "wind 30kt danger", "source": "mock_heuristic"},
                {"zone_id": "z2", "place": "Rough2", "lat": 10.1, "lon": 76.1, "wind_kt": 28.0, "wind_speed_kt": 28.0, "wind_dir": "S", "wind_direction": "S", "wind_deg": 180, "wind_status": "danger", "cyclone_alert": False, "nearest_cyclone_km": None, "cyclone_name": None, "status": "danger", "reason": "wind 28kt danger", "source": "mock_heuristic"},
            ]

        async def mock_danger(points, **kwargs):
            return [
                {"zone_id": "z1", "place": "Rough1", "lat": 10.0, "lon": 76.0, "is_safe": True, "status": "safe", "warnings": [], "inside_eez": True, "inside_mpa": False, "mpa_name": None},
                {"zone_id": "z2", "place": "Rough2", "lat": 10.1, "lon": 76.1, "is_safe": True, "status": "safe", "warnings": [], "inside_eez": True, "inside_mpa": False, "mpa_name": None},
            ]

        with patch("backend.agents.fish_finder.find_fishing_zones", side_effect=mock_fish):
            with patch("backend.agents.sea_checker.check_sea_conditions", side_effect=mock_sea):
                with patch("backend.agents.weather_agent.check_weather", side_effect=mock_weather):
                    with patch("backend.agents.danger_agent.check_safety_batch", side_effect=mock_danger):
                        with patch("backend.db.redis.get_session", new=AsyncMock(return_value=None)):
                            with patch("backend.db.redis.save_session", new=AsyncMock(return_value=None)):
                                result = await orchestrator.orchestrate(query="Where is fish?", language="en", location={"lat": 9.93, "lon": 76.26}, session_id="test-unsafe")

        assert "DO NOT SAIL" in result["reply"] or "Do NOT sail" in result["reply"]
        # Badge should be red for all danger? Actually sea/weather danger -> badge red
        assert result["safety"]["badge"] in ("red", "amber")

    @pytest.mark.asyncio
    async def test_orchestrator_no_location_prompts_for_gps(self):
        from backend.agents import orchestrator
        with patch("backend.db.redis.get_session", new=AsyncMock(return_value=None)):
            result = await orchestrator.orchestrate(query="Where is fish?", language="en", location=None, session_id="no-loc")
        assert "GPS" in result["reply"] or "location" in result["reply"].lower()
        assert result["confidence"] == pytest.approx(0.62, abs=0.01)
        assert result["map"]["center"] is None

    @pytest.mark.asyncio
    async def test_orchestrator_coastal_port_lookup(self):
        from backend.agents import orchestrator
        shared = [{"zone_id": "z1", "place": "KochiZone", "lat": 9.93, "lon": 76.26, "distance_from_user_km": 1.0, "bearing": 90, "direction": "E", "depth_range": "20-30", "sector": "KERALA"}]

        async def mock_fish(lat, lon, radius_km=80.0, **kwargs):
            # Verify Kochi coords resolved
            assert lat == pytest.approx(9.93, abs=0.01)
            assert lon == pytest.approx(76.26, abs=0.01)
            return shared

        async def mock_sea(points):
            return [{"zone_id": "z1", "place": "KochiZone", "lat": 9.93, "lon": 76.26, "wave_height_m": 0.8, "current_kt": 1.0, "wave_status": "safe", "current_status": "safe", "status": "safe", "reason": "ok", "source": "mock_heuristic"}]

        async def mock_weather(points):
            return [{"zone_id": "z1", "place": "KochiZone", "lat": 9.93, "lon": 76.26, "wind_kt": 10.0, "wind_speed_kt": 10.0, "wind_dir": "N", "wind_direction": "N", "wind_deg": 0, "wind_status": "safe", "cyclone_alert": False, "nearest_cyclone_km": None, "cyclone_name": None, "status": "safe", "reason": "ok", "source": "mock_heuristic"}]

        async def mock_danger(points, **kwargs):
            return [{"zone_id": "z1", "place": "KochiZone", "lat": 9.93, "lon": 76.26, "is_safe": True, "status": "safe", "warnings": [], "inside_eez": True, "inside_mpa": False, "mpa_name": None}]

        with patch("backend.agents.fish_finder.find_fishing_zones", side_effect=mock_fish):
            with patch("backend.agents.sea_checker.check_sea_conditions", side_effect=mock_sea):
                with patch("backend.agents.weather_agent.check_weather", side_effect=mock_weather):
                    with patch("backend.agents.danger_agent.check_safety_batch", side_effect=mock_danger):
                        with patch("backend.db.redis.get_session", new=AsyncMock(return_value=None)):
                            with patch("backend.db.redis.save_session", new=AsyncMock(return_value=None)):
                                result = await orchestrator.orchestrate(query="Where is fish near Kochi?", language="en", location=None, session_id="test-kochi")
        assert result["map"]["center"] is not None
        assert result["confidence"] == pytest.approx(0.87, abs=0.01)
