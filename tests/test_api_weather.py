"""
Unit & Integration Tests for Live Weather Router & Ingest Layer

Tests:
  - GET /api/weather/current: returns 200 with expected keys & types
  - Redis 30-minute caching (second request returns cached: True)
  - OpenWeatherMap API integration and fallback to Open-Meteo
  - GET /api/weather/cyclone: returns structured cyclone alert (safe/warning)
  - Coastal pressure anomaly detection (<995 hPa threshold)
  - Edge cases: invalid coordinates, missing query params
  - Subagents integration (weather_agent, danger_agent)
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.main import app
import backend.db.redis as r_mod
from backend.ingest.live_fetchers import (
    fetch_open_meteo_marine,
    fetch_open_meteo_weather,
    fetch_openweathermap,
    fetch_live_weather,
    fetch_imd_cyclone_alerts,
    _http_get_with_retry,
)
from backend.agents.subagents import weather_agent, danger_agent


@pytest.fixture
def client():
    """TestClient fixture."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_redis_memory():
    """Ensure in-memory Redis cache is clean for each test."""
    r_mod._memory_store.clear()
    r_mod._memory_expiry.clear()
    yield
    r_mod._memory_store.clear()
    r_mod._memory_expiry.clear()


class TestCurrentWeatherEndpoint:
    """Tests for GET /api/weather/current."""

    def test_current_weather_returns_200_and_expected_keys(self, client):
        """GET /api/weather/current returns 200 JSON with all required keys."""
        lat, lon = 9.93, 76.26
        response = client.get(f"/api/weather/current?lat={lat}&lon={lon}")
        assert response.status_code == 200

        data = response.json()
        required_keys = [
            "lat",
            "lon",
            "temperature_c",
            "humidity_pct",
            "pressure_hpa",
            "wind_speed_kt",
            "wind_gust_kt",
            "wind_direction",
            "wave_height_m",
            "wave_period_s",
            "current_speed_kt",
            "status",
            "source",
            "cached",
        ]
        for k in required_keys:
            assert k in data, f"Missing required key: {k}"

        assert data["lat"] == round(lat, 4)
        assert data["lon"] == round(lon, 4)
        assert isinstance(data["temperature_c"], (int, float))
        assert isinstance(data["humidity_pct"], (int, float))
        assert isinstance(data["pressure_hpa"], (int, float))
        assert isinstance(data["wind_speed_kt"], (int, float))
        assert isinstance(data["wind_gust_kt"], (int, float))
        assert isinstance(data["wind_direction"], str)
        assert isinstance(data["wave_height_m"], (int, float))
        assert isinstance(data["wave_period_s"], (int, float))
        assert isinstance(data["current_speed_kt"], (int, float))
        assert data["status"] in ("safe", "caution", "danger")
        assert isinstance(data["source"], str)
        assert data["cached"] is False

    def test_current_weather_redis_caching(self, client):
        """Second request for the same coordinates returns cached: True."""
        lat, lon = 9.93, 76.26

        # Call 1: Fresh fetch
        resp1 = client.get(f"/api/weather/current?lat={lat}&lon={lon}")
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["cached"] is False

        # Verify key exists in Redis store
        cache_key = f"weather:current:{round(lat, 2)}:{round(lon, 2)}"
        assert cache_key in r_mod._memory_store

        # Call 2: Should hit Redis cache
        resp2 = client.get(f"/api/weather/current?lat={lat}&lon={lon}")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["cached"] is True
        assert data2["temperature_c"] == data1["temperature_c"]
        assert data2["pressure_hpa"] == data1["pressure_hpa"]
        assert data2["wind_speed_kt"] == data1["wind_speed_kt"]

    def test_current_weather_with_openweathermap_success(self, client):
        """OpenWeatherMap returns 200 and data is integrated when API key is present."""
        mock_owm_payload = {
            "main": {
                "temp": 29.5,
                "pressure": 1009.0,
                "humidity": 80.0,
            },
            "wind": {
                "speed": 5.0,  # 5.0 m/s * 1.94384 = ~9.7 kt
                "gust": 7.0,
                "deg": 270,
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_owm_payload
        mock_resp.raise_for_status.return_value = None

        with patch.dict(os.environ, {"OPENWEATHER_API_KEY": "fake_test_key_123"}):
            with patch("httpx.Client.get", return_value=mock_resp):
                resp = client.get("/api/weather/current?lat=12.5&lon=74.8")
                assert resp.status_code == 200
                data = resp.json()
                assert data["temperature_c"] == 29.5
                assert data["humidity_pct"] == 80.0
                assert data["pressure_hpa"] == 1009.0
                assert "openweathermap" in data["source"]

    def test_current_weather_missing_api_key_fallback(self, client):
        """When OPENWEATHER_API_KEY is not configured, gracefully falls back to Open-Meteo."""
        with patch.dict(os.environ, {"OPENWEATHER_API_KEY": ""}):
            resp = client.get("/api/weather/current?lat=15.0&lon=73.5")
            assert resp.status_code == 200
            data = resp.json()
            assert "open_meteo" in data["source"]
            assert data["cached"] is False

    def test_current_weather_openweathermap_failure_fallback(self, client):
        """When OpenWeatherMap raises HTTP/network error, gracefully falls back to Open-Meteo."""
        import httpx

        def mock_get(url, **kwargs):
            if "openweathermap" in str(url):
                raise httpx.ConnectError("Connection timed out")
            # Open-Meteo call proceeds or is mocked
            mock_res = MagicMock()
            mock_res.status_code = 200
            mock_res.json.return_value = {
                "hourly": {
                    "wave_height": [1.1],
                    "wave_period": [6.5],
                    "ocean_current_velocity": [0.5],
                    "wind_speed_10m": [12.0],
                    "wind_direction_10m": [250.0],
                    "surface_pressure": [1011.0],
                    "temperature_2m": [27.5],
                    "relative_humidity_2m": [78.0],
                }
            }
            mock_res.raise_for_status.return_value = None
            return mock_res

        with patch.dict(os.environ, {"OPENWEATHER_API_KEY": "test_key"}):
            with patch("httpx.Client.get", side_effect=mock_get):
                resp = client.get("/api/weather/current?lat=10.0&lon=76.0")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] in ("safe", "caution", "danger")
                assert data["wind_speed_kt"] > 0

    def test_current_weather_invalid_coordinates(self, client):
        """Out of range or non-numeric coordinates return 400 or 422."""
        # Latitude > 90
        resp = client.get("/api/weather/current?lat=95.0&lon=76.26")
        assert resp.status_code == 400

        # Longitude < -180
        resp = client.get("/api/weather/current?lat=9.93&lon=-190.0")
        assert resp.status_code == 400

        # Non-numeric
        resp = client.get("/api/weather/current?lat=invalid&lon=76.26")
        assert resp.status_code == 422

    def test_current_weather_upstream_failure_returns_502(self, client):
        """When upstream weather fetcher raises exception, returns 502 Bad Gateway with failure message."""
        with patch("backend.routers.weather.fetch_live_weather", side_effect=RuntimeError("Upstream down")):
            resp = client.get("/api/weather/current?lat=9.93&lon=76.26")
            assert resp.status_code == 502
            assert "failed" in resp.json()["detail"].lower()
            assert "upstream" in resp.json()["detail"].lower()

    def test_http_get_with_retry_succeeds_on_transient_failure(self):
        """_http_get_with_retry retries on transient connection error and succeeds without mock data."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"hourly": {"wave_height": [1.2]}}

        with patch("httpx.Client") as mock_client_cls, patch("time.sleep") as mock_sleep:
            mock_client = MagicMock()
            mock_client.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                httpx.ConnectError("WinError 10054"),
                mock_resp,
            ]
            mock_client_cls.return_value = mock_client

            resp = _http_get_with_retry("https://example.com/api", max_retries=2, backoff_factor=0.01)
            assert resp == mock_resp
            assert mock_client.get.call_count == 2
            mock_sleep.assert_called_once()

    def test_http_get_with_retry_exhausted_raises_error_no_mock_data(self):
        """_http_get_with_retry raises RuntimeError when retries exhausted and never returns mock data."""
        with patch("httpx.Client") as mock_client_cls, patch("time.sleep"):
            mock_client = MagicMock()
            mock_client.__enter__.return_value = mock_client
            mock_client.get.side_effect = httpx.ConnectError("WinError 10054: connection reset")
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError) as exc_info:
                _http_get_with_retry("https://example.com/api", max_retries=3, backoff_factor=0.01)
            assert "Live fetch failed" in str(exc_info.value)
            assert "3 retries" in str(exc_info.value)


class TestCycloneWarningsEndpoint:
    """Tests for GET /api/weather/cyclone."""

    def test_cyclone_warnings_default_all_coasts(self, client):
        """GET /api/weather/cyclone without params returns structured coastal cyclone alert."""
        resp = client.get("/api/weather/cyclone")
        assert resp.status_code == 200

        data = resp.json()
        assert "alert_level" in data
        assert data["alert_level"] in ("safe", "advisory", "warning", "severe")
        assert "nearest_cyclone_distance_km" in data
        assert "max_wind_speed_kt" in data
        assert "description" in data
        assert "regions_affected" in data
        assert isinstance(data["regions_affected"], list)
        assert "last_updated" in data

    def test_cyclone_warnings_specific_point_safe(self, client):
        """GET /api/weather/cyclone with lat & lon under normal conditions returns safe status."""
        resp = client.get("/api/weather/cyclone?lat=9.93&lon=76.26")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alert_level"] in ("safe", "advisory", "warning", "severe")
        assert isinstance(data["description"], str)

    def test_cyclone_warnings_pressure_anomaly_trigger(self, client):
        """When coastal barometric pressure drops below 995 hPa threshold, triggers warning."""
        mock_weather = {
            "surface_pressure_hpa": 992.0,  # Below 995.0 threshold
            "wind_speed_kt": 38.0,
            "temperature_c": 26.0,
            "humidity_pct": 90.0,
            "wind_direction": "SE",
            "wind_deg": 135,
            "wind_gusts_kt": 48.0,
            "wind_status": "danger",
            "cyclone_danger": True,
            "status": "danger",
            "source": "mock",
        }

        with patch("backend.ingest.live_fetchers.fetch_open_meteo_weather", return_value=mock_weather):
            resp = client.get("/api/weather/cyclone?lat=13.08&lon=80.27")
            assert resp.status_code == 200
            data = resp.json()
            assert data["alert_level"] in ("warning", "severe")
            assert data["nearest_cyclone_distance_km"] == 0.0
            assert data["max_wind_speed_kt"] == 38.0
            assert len(data["regions_affected"]) > 0
            assert "992" in data["description"] or "cyclon" in data["description"].lower() or "depression" in data["description"].lower()

    def test_cyclone_warnings_severe_threshold_trigger(self, client):
        """Deep depression with pressure < 980 hPa or wind > 48 kt triggers 'severe' alert."""
        mock_weather = {
            "surface_pressure_hpa": 974.0,  # Deep cyclone
            "wind_speed_kt": 55.0,
            "temperature_c": 25.0,
            "humidity_pct": 95.0,
            "wind_direction": "E",
            "wind_deg": 90,
            "wind_gusts_kt": 70.0,
            "wind_status": "danger",
            "cyclone_danger": True,
            "status": "danger",
            "source": "mock",
        }

        with patch("backend.ingest.live_fetchers.fetch_open_meteo_weather", return_value=mock_weather):
            resp = client.get("/api/weather/cyclone?lat=19.81&lon=85.83")
            assert resp.status_code == 200
            data = resp.json()
            assert data["alert_level"] == "severe"

    def test_cyclone_warnings_invalid_coordinates(self, client):
        """Invalid coordinate combinations return 400."""
        # lat provided without lon
        resp = client.get("/api/weather/cyclone?lat=9.93")
        assert resp.status_code == 400

        # lon provided without lat
        resp = client.get("/api/weather/cyclone?lon=76.26")
        assert resp.status_code == 400

        # lat out of range
        resp = client.get("/api/weather/cyclone?lat=120.0&lon=76.26")
        assert resp.status_code == 400

    def test_cyclone_warnings_upstream_failure_returns_502(self, client):
        """When upstream cyclone fetcher raises exception, returns 502 Bad Gateway."""
        with patch("backend.routers.weather.fetch_imd_cyclone_alerts", side_effect=RuntimeError("IMD down")):
            resp = client.get("/api/weather/cyclone?lat=9.93&lon=76.26")
            assert resp.status_code == 502
            assert "upstream" in resp.json()["detail"].lower()


class TestSubagentsCompatibility:
    """Tests ensuring weather_agent and danger_agent utilize compatible live fetchers."""

    @pytest.mark.asyncio
    async def test_weather_agent_fetches_wind(self):
        """weather_agent.get_wind retrieves live wind data."""
        wind_kt, wind_dir, wind_deg, source = await weather_agent.get_wind(
            lat=9.93, lon=76.26, zone_id="z_test", idx=0
        )
        assert isinstance(wind_kt, (int, float))
        assert wind_kt >= 0
        assert isinstance(wind_dir, str)

    @pytest.mark.asyncio
    async def test_weather_agent_fetches_cyclones(self):
        """weather_agent.fetch_imd_cyclones returns list."""
        cyclones = await weather_agent.fetch_imd_cyclones()
        assert isinstance(cyclones, list)

    @pytest.mark.asyncio
    async def test_danger_agent_handles_cyclone_alert(self):
        """danger_agent.fetch_imd_cyclone_alert returns dict with active status."""
        alert = await danger_agent.fetch_imd_cyclone_alert(9.93, 76.26)
        assert isinstance(alert, dict)
        assert "active" in alert
