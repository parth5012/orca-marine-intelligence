"""
Unit & Integration Tests for Officer Overview & RBAC

Tests:
  - GET /api/officer/overview with X-User-Role: official returns 200 with command metrics
  - GET /api/officer/overview with role=official query param returns 200
  - GET /api/officer/overview with public / missing role returns 403 Forbidden
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_officer_overview_authorized_header(client):
    resp = client.get("/api/officer/overview", headers={"X-User-Role": "official"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_vessels_monitored"] > 0
    assert data["fleet_compliance_pct"] > 0
    assert data["incois_bulletins_active"] > 0
    assert data["system_health"] == "optimal"


def test_officer_overview_authorized_query(client):
    resp = client.get("/api/officer/overview?role=official")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_vessels_monitored"] > 0


def test_officer_overview_forbidden_public(client):
    resp = client.get("/api/officer/overview", headers={"X-User-Role": "public"})
    assert resp.status_code == 403
    assert "restricted" in resp.json()["detail"].lower()


def test_officer_overview_forbidden_no_auth(client):
    resp = client.get("/api/officer/overview")
    assert resp.status_code == 403
