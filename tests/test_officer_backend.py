"""
Tests for Officer Register Backend (Wayfinder #170 T2, issue #172).

Covers POST/GET /api/officer/departures|overrides|broadcasts:
CRUD per port, cross-port isolation for port role, watch read-all,
401 on missing/wrong X-Officer-Token, 400 on unknown port_id, and the
computed (never stored) overdue_mins / overdue_status fields.

Runs without Postgres: the router uses in-memory stores backed by the
schema.sql §7 tables in prod. Token defaults (test-port-token /
test-watch-token) match backend/routers/officer.py; env overrides respected.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import officer as officer_mod

PORT_TOKEN = os.getenv("PORT_TOKEN", "test-port-token")
WATCH_TOKEN = os.getenv("WATCH_TOKEN", "test-watch-token")


@pytest.fixture
def client():
    officer_mod.clear_officer_stores()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    officer_mod.clear_officer_stores()


def _port_headers():
    return {"X-Officer-Token": PORT_TOKEN}


def _watch_headers():
    return {"X-Officer-Token": WATCH_TOKEN}


def _departure_payload(port="kochi", boat="KL-07-MM-1234", hours_out=8):
    now = datetime.now(timezone.utc)
    return {
        "port_id": port,
        "boat_id": boat,
        "crew": 5,
        "time_out": (now - timedelta(hours=1)).isoformat(),
        "expected_in": (now + timedelta(hours=hours_out)).isoformat(),
        "dest_lat": 9.5,
        "dest_lon": 76.0,
        "dest_zone": "SEC005",
    }


# --- departures CRUD per port ------------------------------------------------

def test_departures_crud_per_port(client):
    created = client.post("/api/officer/departures", json=_departure_payload(), headers=_port_headers())
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["port_id"] == "kochi"
    assert body["status"] == "at_sea"
    assert body["id"]

    listed = client.get("/api/officer/departures?port_id=kochi", headers=_port_headers())
    assert listed.status_code == 200
    data = listed.json()
    assert data["count"] == 1
    assert data["departures"][0]["boat_id"] == "KL-07-MM-1234"


def test_departures_cross_port_isolation_for_port_role(client):
    client.post("/api/officer/departures", json=_departure_payload(port="kochi"), headers=_port_headers())
    client.post("/api/officer/departures", json=_departure_payload(port="chennai", boat="TN-01-XX-999"), headers=_port_headers())

    kochi = client.get("/api/officer/departures?port_id=kochi", headers=_port_headers())
    assert kochi.json()["count"] == 1
    assert all(d["port_id"] == "kochi" for d in kochi.json()["departures"])

    chennai = client.get("/api/officer/departures?port_id=chennai", headers=_port_headers())
    assert chennai.json()["count"] == 1
    assert all(d["port_id"] == "chennai" for d in chennai.json()["departures"])


def test_departures_watch_sees_all(client):
    client.post("/api/officer/departures", json=_departure_payload(port="kochi"), headers=_port_headers())
    client.post("/api/officer/departures", json=_departure_payload(port="chennai", boat="TN-01-XX-999"), headers=_port_headers())

    resp = client.get("/api/officer/departures", headers=_watch_headers())
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_departures_port_role_requires_port_id(client):
    resp = client.get("/api/officer/departures", headers=_port_headers())
    assert resp.status_code == 400


def test_departures_unknown_port_400(client):
    resp = client.post("/api/officer/departures", json=_departure_payload(port="atlantis"), headers=_port_headers())
    assert resp.status_code == 400
    assert client.get("/api/officer/departures?port_id=atlantis", headers=_watch_headers()).status_code == 400


# --- overdue computed, never stored ------------------------------------------

def test_overdue_computed_not_stored(client):
    now = datetime.now(timezone.utc)
    payload = _departure_payload()
    payload["expected_in"] = (now - timedelta(hours=7)).isoformat()  # 420 min overdue -> red
    created = client.post("/api/officer/departures", json=payload, headers=_port_headers())
    assert created.status_code == 200
    assert created.json()["overdue_status"] == "red"
    assert created.json()["overdue_mins"] >= 400

    # Raw store carries no computed fields
    assert all("overdue_mins" not in r and "overdue_status" not in r for r in officer_mod._departures)

    listed = client.get("/api/officer/departures?port_id=kochi", headers=_port_headers()).json()
    assert listed["departures"][0]["overdue_status"] == "red"


def test_overdue_bands(client):
    now = datetime.now(timezone.utc)

    fresh = _departure_payload(boat="FRESH-1")
    fresh["expected_in"] = (now + timedelta(hours=2)).isoformat()
    assert client.post("/api/officer/departures", json=fresh, headers=_port_headers()).json()["overdue_status"] == "none"

    amber = _departure_payload(boat="AMBER-1")
    amber["expected_in"] = (now - timedelta(hours=3)).isoformat()  # ~180 min
    assert client.post("/api/officer/departures", json=amber, headers=_port_headers()).json()["overdue_status"] == "amber"


# --- overrides ----------------------------------------------------------------

def test_overrides_crud_and_date_filter(client):
    r1 = client.post(
        "/api/officer/overrides",
        json={"port_id": "kochi", "date": "2026-09-18", "decision": "HOLD", "reason": "Rough seas"},
        headers=_port_headers(),
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["by_role"] == "port"

    r2 = client.post(
        "/api/officer/overrides",
        json={"port_id": "kochi", "date": "2026-09-19", "decision": "GO", "reason": "Calm"},
        headers=_watch_headers(),
    )
    assert r2.json()["by_role"] == "watch"

    all_rows = client.get("/api/officer/overrides?port_id=kochi", headers=_port_headers()).json()
    assert all_rows["count"] == 2

    one_day = client.get("/api/officer/overrides?port_id=kochi&date=2026-09-18", headers=_port_headers()).json()
    assert one_day["count"] == 1
    assert one_day["overrides"][0]["decision"] == "HOLD"


def test_overrides_invalid_decision_422(client):
    resp = client.post(
        "/api/officer/overrides",
        json={"port_id": "kochi", "date": "2026-09-18", "decision": "MAYBE", "reason": "x"},
        headers=_port_headers(),
    )
    assert resp.status_code == 422


def test_overrides_cross_port_isolation(client):
    client.post("/api/officer/overrides", json={"port_id": "kochi", "date": "2026-09-18", "decision": "GO", "reason": "ok"}, headers=_port_headers())
    client.post("/api/officer/overrides", json={"port_id": "chennai", "date": "2026-09-18", "decision": "HOLD", "reason": "wind"}, headers=_port_headers())
    kochi = client.get("/api/officer/overrides?port_id=kochi", headers=_port_headers()).json()
    assert kochi["count"] == 1 and kochi["overrides"][0]["port_id"] == "kochi"


# --- broadcasts ---------------------------------------------------------------

def test_broadcasts_crud_per_port(client):
    created = client.post(
        "/api/officer/broadcasts",
        json={"port_id": "kochi", "text_en": "Stay within 12nm", "text_local": "12 നോട്ടിക്കൽ മൈലിനുള്ളിൽ", "lang": "ml"},
        headers=_port_headers(),
    )
    assert created.status_code == 200, created.text
    assert created.json()["lang"] == "ml"

    listed = client.get("/api/officer/broadcasts?port_id=kochi", headers=_port_headers()).json()
    assert listed["count"] == 1
    assert listed["broadcasts"][0]["text_en"] == "Stay within 12nm"


def test_broadcasts_watch_sees_all(client):
    client.post("/api/officer/broadcasts", json={"port_id": "kochi", "text_en": "A"}, headers=_port_headers())
    client.post("/api/officer/broadcasts", json={"port_id": "chennai", "text_en": "B"}, headers=_port_headers())
    assert client.get("/api/officer/broadcasts", headers=_watch_headers()).json()["count"] == 2


# --- auth ---------------------------------------------------------------------

@pytest.mark.parametrize("method,url", [
    ("GET", "/api/officer/departures?port_id=kochi"),
    ("POST", "/api/officer/departures"),
    ("GET", "/api/officer/overrides?port_id=kochi"),
    ("POST", "/api/officer/overrides"),
    ("GET", "/api/officer/broadcasts?port_id=kochi"),
    ("POST", "/api/officer/broadcasts"),
])
def test_401_missing_and_wrong_token(client, method, url):
    payload: dict = {}
    if method == "POST":
        if "departures" in url:
            payload = _departure_payload()
        elif "overrides" in url:
            payload = {"port_id": "kochi", "date": "2026-09-18", "decision": "GO", "reason": "ok"}
        else:
            payload = {"port_id": "kochi", "text_en": "hi"}

    missing = client.request(method, url, json=payload or None)
    assert missing.status_code == 401
    assert "detail" in missing.json()

    wrong = client.request(method, url, json=payload or None, headers={"X-Officer-Token": "nope"})
    assert wrong.status_code == 401
