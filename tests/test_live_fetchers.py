"""
Tests for Live Data Fetching Layer (Open-Meteo, INCOIS PFZ, Marine Regions).
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from backend.ingest.live_fetchers import (
    fetch_open_meteo_wave_current,
    fetch_open_meteo_weather,
    fetch_open_meteo_marine,
    compute_departure_window_advisory,
    fetch_live_incois_pfz,
    fetch_live_ocean_state,
    fetch_live_marine_weather,
    fetch_live_geofence_boundaries,
    fetch_live_all,
    IST_TZ,
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

    def test_ist_tz_definition(self):
        assert IST_TZ.utcoffset(None) == timedelta(hours=5, minutes=30)

    def test_compute_departure_window_fallback_on_failure(self):
        with patch("httpx.Client.get", side_effect=RuntimeError("Connection timeout")):
            res = compute_departure_window_advisory(9.93, 76.26)
            assert res["status"] == "fallback"
            assert res["is_safe_to_depart"] is None
            assert res["departure_window"] == "UNAVAILABLE"
            assert res["expected_waves_m"] == "N/A"
            assert res["expected_wind_kmh"] == "N/A"
            assert res["deterioration_alert"] is None
            assert "Advisory unavailable" in res["bulletin_text"]

    def test_compute_departure_window_missing_series_fallback(self):
        # When wave_height or wind series is missing/empty, it should NOT claim severe weather UNSAFE
        mock_marine = MagicMock()
        mock_marine.json.return_value = {"hourly": {"time": ["2026-09-06T06:00"]}}  # missing wave_height
        mock_weather = MagicMock()
        mock_weather.json.return_value = {"hourly": {"time": ["2026-09-06T06:00"], "wind_speed_10m": [10.0]}}

        with patch("httpx.Client.get", side_effect=[mock_marine, mock_weather]):
            res = compute_departure_window_advisory(9.93, 76.26)
            assert res["status"] == "fallback"
            assert res["is_safe_to_depart"] is None
            assert res["departure_window"] == "UNAVAILABLE"

    def test_compute_departure_window_contiguous_safe_run(self):
        # 06:00 (safe), 07:00 (safe), 08:00 (unsafe wave=3.0), 09:00 (safe), 10:00 (safe), 11:00 (safe), 12:00 (unsafe wave=2.0)
        times = [
            "2026-09-06T06:00",
            "2026-09-06T07:00",
            "2026-09-06T08:00",
            "2026-09-06T09:00",
            "2026-09-06T10:00",
            "2026-09-06T11:00",
            "2026-09-06T12:00",
        ]
        waves = [1.0, 1.1, 3.0, 0.9, 1.0, 1.1, 2.0]
        winds = [10.0, 10.0, 10.0, 8.0, 8.0, 9.0, 15.0]
        gusts = [12.0, 12.0, 12.0, 10.0, 10.0, 12.0, 20.0]

        mock_marine = MagicMock()
        mock_marine.json.return_value = {"hourly": {"time": times, "wave_height": waves}}
        mock_weather = MagicMock()
        mock_weather.json.return_value = {
            "hourly": {
                "time": times,
                "wind_speed_10m": winds,
                "wind_gusts_10m": gusts,
            }
        }

        fixed_now = datetime(2026, 9, 6, 6, 0, tzinfo=IST_TZ)
        with patch("httpx.Client.get", side_effect=[mock_marine, mock_weather]):
            with patch("backend.ingest.live_fetchers.datetime") as mock_dt:
                mock_dt.now.return_value = fixed_now
                mock_dt.fromisoformat = datetime.fromisoformat
                mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
                res = compute_departure_window_advisory(9.93, 76.26, hours=7)

        assert res["status"] == "success"
        assert res["is_safe_to_depart"] is True
        # Longest contiguous run is 09:00 to 11:00 (length 3), NOT 06:00 to 11:00!
        assert "09:00–11:00" in res["departure_window"]
        assert res["deterioration_alert"] is not None
        assert "12:00" in res["deterioration_alert"]

    def test_fetch_open_meteo_marine_lead_hours(self):
        # Deterministically test forecast_lead_hours when target_dt is 6 hours ahead of now
        fixed_now = datetime(2026, 9, 6, 6, 0, tzinfo=IST_TZ)
        target = fixed_now + timedelta(hours=6)
        times = [
            (fixed_now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
            for i in range(12)
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hourly": {
                "time": times,
                "wave_height": [1.0] * 12,
                "wave_direction": [180] * 12,
                "wave_period": [8.0] * 12,
                "swell_wave_height": [0.5] * 12,
                "swell_wave_period": [7.0] * 12,
                "ocean_current_velocity": [0.5] * 12,
                "ocean_current_direction": [90] * 12,
            }
        }

        with patch("httpx.Client.get", return_value=mock_resp):
            with patch("backend.ingest.live_fetchers.datetime") as mock_dt:
                mock_dt.now.return_value = fixed_now
                mock_dt.fromisoformat = datetime.fromisoformat
                mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
                res = fetch_open_meteo_marine(9.93, 76.26, target_dt=target)

        assert res["status"] in ("safe", "caution", "danger")
        assert "data_freshness" in res
        lead = res["data_freshness"]["forecast_lead_hours"]
        assert lead == 6.0

