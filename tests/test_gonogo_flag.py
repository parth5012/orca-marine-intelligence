"""
Tests for Officer Go-No-Go flag + override validation (Wayfinder #170 T4, issue #174).

Covers ORCA_ENABLE_GONOGO kill switch (backend/routers/officer.py
is_gonogo_enabled, default true) and POST /api/officer/overrides
validation: 400 on empty/whitespace reason, 422 on non-GO/HOLD decision.
Runs without Postgres (in-memory stores). Must stay green with T2 tests.
"""

import os

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import officer as officer_mod

PORT_TOKEN = os.getenv("PORT_TOKEN", "test-port-token")


@pytest.fixture
def client():
    officer_mod.clear_officer_stores()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    officer_mod.clear_officer_stores()


def _headers():
    return {"X-Officer-Token": PORT_TOKEN}


# --- kill switch -------------------------------------------------------------

def test_gonogo_enabled_default_true(monkeypatch):
    monkeypatch.delenv("ORCA_ENABLE_GONOGO", raising=False)
    assert officer_mod.is_gonogo_enabled() is True


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off"])
def test_gonogo_enabled_false_values(monkeypatch, value):
    monkeypatch.setenv("ORCA_ENABLE_GONOGO", value)
    assert officer_mod.is_gonogo_enabled() is False


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes"])
def test_gonogo_enabled_true_values(monkeypatch, value):
    monkeypatch.setenv("ORCA_ENABLE_GONOGO", value)
    assert officer_mod.is_gonogo_enabled() is True


# --- override validation -----------------------------------------------------

@pytest.mark.parametrize("reason", ["", "   ", "\t\n"])
def test_override_empty_reason_400(client, reason):
    resp = client.post(
        "/api/officer/overrides",
        json={"port_id": "kochi", "date": "2026-09-18", "decision": "HOLD", "reason": reason},
        headers=_headers(),
    )
    assert resp.status_code == 400
    assert "reason" in resp.json()["detail"].lower()


def test_override_invalid_decision_422(client):
    resp = client.post(
        "/api/officer/overrides",
        json={"port_id": "kochi", "date": "2026-09-18", "decision": "MAYBE", "reason": "x"},
        headers=_headers(),
    )
    assert resp.status_code == 422


def test_override_valid_still_passes(client):
    resp = client.post(
        "/api/officer/overrides",
        json={"port_id": "kochi", "date": "2026-09-18", "decision": "GO", "reason": "Calm seas"},
        headers=_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reason"] == "Calm seas"
