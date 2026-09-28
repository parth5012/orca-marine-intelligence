"""
Snapshot timestamp contract tests (ADR-0008 / docs/API.md "Offline Advisory
Snapshot Contract", CodeRabbit PR #262 finding 4123719013 + decision A).

Owner: M-C (Backend API)
Module: backend/tests/test_snapshot_timestamps.py

Contract under test:
  - GET /api/pfz/today returns `timestamp` = the ingested dataset's capture
    time, carried through unchanged — never the request time.
  - When the dataset carries no capture time, `timestamp` is null (unknown),
    never "now".
  - GET /api/weather/current returns `timestamp` = when the readings were
    obtained; a cached response keeps the original fetch time.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import backend.ingest.tides as tides_module  # noqa: E402
import backend.routers.pfz as pfz_router  # noqa: E402
import backend.routers.weather as weather_router  # noqa: E402

DATASET_CAPTURED_AT = "2026-09-20T06:49:07.666863+00:00"


def _dataset(timestamp: Optional[str] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "type": "FeatureCollection",
        "source": "incois_textdata",
        "features": [
            {
                "type": "Feature",
                "properties": {"sector": "KERALA", "place": "Pallithottam"},
                "geometry": {"type": "Point", "coordinates": [76.167, 8.555]},
            }
        ],
    }
    if timestamp is not None:
        data["timestamp"] = timestamp
    return data


class TestPfzTimestamp:
    def test_pfz_timestamp_is_the_dataset_capture_time(self, monkeypatch):
        async def no_cache(_key):
            return None

        async def fake_ingest():
            return _dataset(DATASET_CAPTURED_AT)

        monkeypatch.setattr(pfz_router, "get_json", no_cache)
        monkeypatch.setattr(pfz_router, "ingest_textdata", fake_ingest)
        monkeypatch.setattr(pfz_router, "set_json", lambda *a, **k: None)

        before = datetime.now(timezone.utc)
        result = asyncio.run(pfz_router.get_today_pfz(sector=None, bbox=None, limit=1000))

        assert result["timestamp"] == DATASET_CAPTURED_AT
        assert result["metadata"]["timestamp"] == DATASET_CAPTURED_AT
        assert datetime.fromisoformat(result["timestamp"]) < before

    def test_pfz_timestamp_is_null_when_the_dataset_has_none(self, monkeypatch):
        async def cached_dataset(_key):
            return _dataset()

        monkeypatch.setattr(pfz_router, "get_json", cached_dataset)
        monkeypatch.setattr(pfz_router, "set_json", lambda *a, **k: None)

        result = asyncio.run(pfz_router.get_today_pfz(sector=None, bbox=None, limit=1000))

        assert result.get("timestamp") is None
        assert result["metadata"]["timestamp"] is None


class TestWeatherTimestamp:
    def _stub_upstream(self, monkeypatch):
        async def no_cache(_key):
            return None

        monkeypatch.setattr(weather_router, "get_json", no_cache)
        monkeypatch.setattr(weather_router, "set_json", lambda *a, **k: None)
        monkeypatch.setattr(
            weather_router,
            "fetch_live_weather",
            lambda lat, lon: {
                "wind_speed_kt": 8.0,
                "temperature_c": 28.0,
                "humidity_pct": 75.0,
                "pressure_hpa": 1012.0,
                "source": "openweathermap",
            },
        )
        monkeypatch.setattr(
            weather_router,
            "fetch_open_meteo_marine",
            lambda lat, lon: {
                "wave_height_m": 1.0,
                "wave_period_s": 6.0,
                "source": "open-meteo-marine",
            },
        )
        monkeypatch.setattr(tides_module, "get_tide", lambda lat, lon: {"tide_range_m": 0.4})

    def test_fresh_fetch_reports_a_capture_time(self, monkeypatch):
        self._stub_upstream(monkeypatch)

        result = asyncio.run(weather_router.get_current_weather(lat=9.9, lon=76.3))

        assert result["timestamp"] is not None
        captured = datetime.fromisoformat(result["timestamp"])
        assert captured.tzinfo is not None
        assert captured <= datetime.now(timezone.utc)

    def test_cached_response_keeps_the_original_fetch_time(self, monkeypatch):
        stored_time = "2026-09-28T04:00:00+00:00"

        async def hit(_key):
            return {"lat": 9.9, "lon": 76.3, "timestamp": stored_time}

        monkeypatch.setattr(weather_router, "get_json", hit)

        result = asyncio.run(weather_router.get_current_weather(lat=9.9, lon=76.3))

        assert result["timestamp"] == stored_time
        assert result["cached"] is True

    def test_cache_entry_without_timestamp_stays_unknown(self, monkeypatch):
        async def hit(_key):
            return {"lat": 9.9, "lon": 76.3, "cached": True}

        monkeypatch.setattr(weather_router, "get_json", hit)

        result = asyncio.run(weather_router.get_current_weather(lat=9.9, lon=76.3))

        assert result.get("timestamp") is None
