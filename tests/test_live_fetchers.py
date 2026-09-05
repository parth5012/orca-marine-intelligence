"""
Tests for Live Data Fetching Layer (Open-Meteo, INCOIS PFZ, Marine Regions).
"""

import pytest
from backend.ingest.live_fetchers import (
    fetch_open_meteo_wave_current,
    fetch_open_meteo_weather,
    fetch_live_incois_pfz,
    fetch_live_ocean_state,
    fetch_live_marine_weather,
    fetch_live_geofence_boundaries,
    fetch_live_all,
)
from backend.agents.planner_schema import (
    find_fishing_zones,
    check_ocean_state,
    check_weather,
    check_geofence,
)


class TestLiveFetchers:
    def test_fetch_live_incois_pfz_from_geojson(self):
        res = fetch_live_incois_pfz(sector="SEC005", center_lat=9.93, center_lon=76.26, count=3)
        assert res["status"] == "success"
        assert len(res["zones"]) == 3
        assert len(res["features"]) == 3
        assert res["feature_collection"]["type"] == "FeatureCollection"

        first = res["zones"][0]
        assert "place" in first
        assert "lat" in first and "lon" in first
        assert "bearing" in first
        assert "depth" in first
        assert "distance_km" in first
        assert first["source"] == "incois_geojson_live"

    def test_fetch_open_meteo_wave_current_live(self):
        data = fetch_open_meteo_wave_current(9.93, 76.26)
        assert "wave_height_m" in data
        assert "current_speed_kt" in data
        assert "wave_period_s" in data
        assert data["wave_status"] in ("safe", "caution", "danger")
        assert data["current_status"] in ("safe", "caution", "danger")
        assert data["status"] in ("safe", "caution", "danger")

    def test_fetch_open_meteo_weather_live(self):
        data = fetch_open_meteo_weather(9.93, 76.26)
        assert "wind_speed_kt" in data
        assert "wind_direction" in data
        assert "surface_pressure_hpa" in data
        assert isinstance(data["cyclone_danger"], bool)
        assert data["wind_status"] in ("safe", "caution", "danger")
        assert data["status"] in ("safe", "caution", "danger")

    def test_fetch_live_ocean_state(self):
        pts = [
            {"zone_id": "z1", "place": "Kochi Offshore", "lat": 9.93, "lon": 76.26},
            {"zone_id": "z2", "place": "Munambam", "lat": 10.18, "lon": 76.17},
        ]
        res = fetch_live_ocean_state(pts)
        assert res["status"] == "success"
        assert len(res["points"]) == 2
        assert res["badge"] in ("safe", "caution", "danger")
        assert res["points"][0]["wave_height_m"] > 0

    def test_fetch_live_marine_weather(self):
        pts = [
            {"zone_id": "z1", "place": "Kochi Offshore", "lat": 9.93, "lon": 76.26},
            {"zone_id": "z2", "place": "Munambam", "lat": 10.18, "lon": 76.17},
        ]
        res = fetch_live_marine_weather(pts)
        assert res["status"] == "success"
        assert len(res["points"]) == 2
        assert res["badge"] in ("safe", "caution", "danger")
        assert res["points"][0]["wind_speed_kt"] >= 0

    def test_fetch_live_geofence_boundaries(self):
        pts = [
            {"zone_id": "z1", "place": "Kochi Territorial Waters", "lat": 9.93, "lon": 76.26},
        ]
        res = fetch_live_geofence_boundaries(pts)
        assert res["status"] == "success"
        assert len(res["points"]) == 1
        assert res["points"][0]["inside_eez"] is True
        assert res["points"][0]["inside_mpa"] is False
        assert res["badge"] == "safe"

    def test_fetch_live_all_pipeline(self):
        res = fetch_live_all("SEC005", 9.93, 76.26, 3)
        assert res["status"] == "success"
        assert len(res["zones"]) == 3
        assert "ocean_state" in res
        assert "weather" in res
        assert "geofence" in res

    def test_planner_schema_live_delegation(self):
        pfz = find_fishing_zones(9.93, 76.26, 50.0)
        assert pfz["status"] == "success"
        assert len(pfz["zones"]) > 0

        ocean = check_ocean_state(pfz["zones"])
        assert ocean["status"] == "success"
        assert len(ocean["points"]) == len(pfz["zones"])

        weather = check_weather(pfz["zones"])
        assert weather["status"] == "success"
        assert len(weather["points"]) == len(pfz["zones"])

        geofence = check_geofence(pfz["zones"])
        assert geofence["status"] == "success"
        assert len(geofence["points"]) == len(pfz["zones"])
