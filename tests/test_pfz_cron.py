"""
Tests for PFZ daily cron (Stage 4: ParallelEngineering output).

Owner: M-C (Backend API & Platform)
Module: tests/test_pfz_cron.py

Covers:
  - backend.cron.fetch_pfz.run_fetch envelope (mocked ingest)
  - POST /api/pfz/refresh auth gate + success path
"""

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.cron.fetch_pfz import _parse_sectors, run_fetch
from backend.main import app


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_parse_sectors():
    assert _parse_sectors(None) is None
    assert _parse_sectors("") is None
    assert _parse_sectors("sec005, sec002 ") == ["SEC005", "SEC002"]


@pytest.mark.asyncio
async def test_run_fetch_success_envelope():
    fake_doc = {
        "type": "FeatureCollection",
        "source": "incois_textdata",
        "sector_count": 2,
        "artifacts": ["data/pfz-today.geojson", "redis:pfz:today"],
        "features": [
            {"type": "Feature", "properties": {"sector": "SEC005", "sector_name": "KERALA"}},
            {"type": "Feature", "properties": {"sector": "SEC002", "sector_name": "MAHARASHTRA"}},
        ],
    }
    with patch("backend.ingest.incois_textdata.ingest_textdata", new=AsyncMock(return_value=fake_doc)):
        result = await run_fetch()
    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["source"] == "incois_textdata"
    # Artifacts must be passed through from ingest (per-sink), not hard-coded
    assert result["artifacts"] == ["data/pfz-today.geojson", "redis:pfz:today"]
    assert result["sector_count"] == 2
    assert isinstance(result["next_actions"], list) and result["next_actions"]


@pytest.mark.asyncio
async def test_run_fetch_sector_filter():
    fake_doc = {
        "type": "FeatureCollection",
        "source": "incois_textdata",
        "sector_count": 2,
        "features": [
            {"type": "Feature", "properties": {"sector": "SEC005", "sector_name": "KERALA"}},
            {"type": "Feature", "properties": {"sector": "SEC002", "sector_name": "MAHARASHTRA"}},
        ],
    }
    with patch("backend.ingest.incois_textdata.ingest_textdata", new=AsyncMock(return_value=fake_doc)):
        result = await run_fetch(sectors=["SEC005"])
    assert result["count"] == 1
    # sector_count must reflect the filtered set, not the unfiltered document
    assert result["sector_count"] == 1


@pytest.mark.asyncio
async def test_run_fetch_empty_is_warning_not_crash():
    fake_doc = {"type": "FeatureCollection", "source": "incois_textdata", "sector_count": 0, "features": []}
    with patch("backend.ingest.incois_textdata.ingest_textdata", new=AsyncMock(return_value=fake_doc)):
        result = await run_fetch()
    assert result["status"] == "warning"
    assert result["count"] == 0


def test_refresh_requires_secret_when_configured(client, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_REFRESH", raising=False)
    resp = client.post("/api/pfz/refresh")
    assert resp.status_code == 401
    resp_bad = client.post("/api/pfz/refresh", headers={"Authorization": "Bearer wrong"})
    assert resp_bad.status_code == 403


def test_refresh_fails_closed_without_secret(client, monkeypatch):
    """No CRON_SECRET + no local-dev flag → 503, never an open trigger."""
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_REFRESH", raising=False)
    resp = client.post("/api/pfz/refresh")
    assert resp.status_code == 503


def test_refresh_success_open_in_dev(client, monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED_REFRESH", "true")
    fake_doc = {
        "type": "FeatureCollection",
        "source": "copernicus_fallback",
        "sector_count": 1,
        "artifacts": ["redis:pfz:today"],
        "features": [{"type": "Feature", "properties": {"sector": "SEC005"}}],
    }
    with patch("backend.routers.pfz.ingest_textdata", new=AsyncMock(return_value=fake_doc)):
        resp = client.post("/api/pfz/refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["count"] == 1
    assert data["source"] == "copernicus_fallback"
    assert data["artifacts"] == ["redis:pfz:today"]
