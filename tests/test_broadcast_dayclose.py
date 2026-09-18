"""
Tests for Officer Broadcast draft + Day-close audit (Wayfinder #170 T6, issue #176).

Covers backend/routers/officer.py T6 additions:
- build_broadcast_draft template vars (GO|HOLD, port, date, sea status,
  PFZ place/bearing/distance, INCOIS sector citation).
- build_broadcast_local translation fallback flag (EN passthrough + warning
  when port language != en; no server translate endpoint for officer, no SMS
  gateway — officer edits the textarea manually).
- GET /api/officer/dayclose?port_id=&date= JSON shape (locked columns:
  port_id,date,departures,holds,overdues_resolved,mpa_hits,broadcasts).
- ?format=csv returns text/csv whose header + row exactly match the JSON.
- 401 on missing/wrong token, 400 for port role without ?port_id=.

Runs without Postgres (in-memory stores). Must stay green with T2/T4 tests.
"""

import csv
import io
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import officer as officer_mod

PORT_TOKEN = os.getenv("PORT_TOKEN", "test-port-token")
WATCH_TOKEN = os.getenv("WATCH_TOKEN", "test-watch-token")
TODAY = datetime.now(timezone.utc).date().isoformat()


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


def _departure(port="kochi", boat="KL-07-MM-1", status="at_sea"):
    now = datetime.now(timezone.utc)
    return {
        "port_id": port,
        "boat_id": boat,
        "crew": 4,
        "time_out": now.isoformat(),
        "expected_in": (now + timedelta(hours=6)).isoformat(),
        "dest_lat": 9.5,
        "dest_lon": 76.0,
        "dest_zone": "SEC005",
        "status": status,
    }


def _seed_day(client):
    client.post("/api/officer/departures", json=_departure("kochi", "KL-07-MM-1"), headers=_port_headers())
    client.post(
        "/api/officer/departures",
        json=_departure("kochi", "KL-07-MM-2", status="returned"),
        headers=_port_headers(),
    )
    client.post("/api/officer/departures", json=_departure("chennai", "TN-01-XX-9"), headers=_port_headers())
    client.post(
        "/api/officer/overrides",
        json={"port_id": "kochi", "date": TODAY, "decision": "HOLD", "reason": "Rough seas"},
        headers=_port_headers(),
    )
    client.post(
        "/api/officer/broadcasts",
        json={"port_id": "kochi", "text_en": "HOLD: Kochi seas rough", "lang": "ml"},
        headers=_port_headers(),
    )


# --- broadcast draft template ------------------------------------------------

def test_draft_template_vars():
    draft = officer_mod.build_broadcast_draft(
        decision="GO",
        port_name="Kochi",
        date_str="2026-09-18",
        sea_status="safe",
        place="Pallithottam",
        bearing="120",
        distance="12km",
        sector="SEC005",
    )
    assert draft == "GO: Kochi 2026-09-18. Sea safe. PFZ Pallithottam 120° 12km (INCOIS SEC005)."


def test_draft_hold_and_invalid_decision_defaults_hold():
    hold = officer_mod.build_broadcast_draft(
        decision="HOLD", port_name="Kochi", date_str="2026-09-18", sea_status="danger",
        place="P", bearing="90", distance="5km", sector="SEC005",
    )
    assert hold.startswith("HOLD:")
    maybe = officer_mod.build_broadcast_draft(
        decision="MAYBE", port_name="Kochi", date_str="2026-09-18", sea_status="safe",
        place="P", bearing="90", distance="5km", sector="SEC005",
    )
    assert maybe.startswith("HOLD:")


def test_broadcast_local_fallback_flag():
    en = "GO: Kochi 2026-09-18. Sea safe."
    same = officer_mod.build_broadcast_local(en, "en")
    assert same == {"text_local": en, "translation_warning": False}
    local = officer_mod.build_broadcast_local(en, "ml")
    assert local["text_local"] == en
    assert local["translation_warning"] is True


# --- day-close JSON ----------------------------------------------------------

def test_dayclose_columns_locked():
    assert officer_mod.DAYCLOSE_COLUMNS == [
        "port_id", "date", "departures", "holds",
        "overdues_resolved", "mpa_hits", "broadcasts",
    ]


def test_dayclose_json_counts(client):
    _seed_day(client)
    resp = client.get(f"/api/officer/dayclose?port_id=kochi&date={TODAY}", headers=_port_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert list(body.keys()) == officer_mod.DAYCLOSE_COLUMNS
    assert body["port_id"] == "kochi"
    assert body["date"] == TODAY
    assert body["departures"] == 2
    assert body["holds"] == 1
    assert body["overdues_resolved"] == 1  # one departure with status == returned
    assert body["broadcasts"] == 1
    expected_mpa = sum(
        1 for r in officer_mod._departures
        if r["port_id"] == "kochi"
        and officer_mod.compute_geofence_flag(float(r["dest_lat"]), float(r["dest_lon"])) == "mpa"
    )
    assert body["mpa_hits"] == expected_mpa


def test_dayclose_cross_port_isolation(client):
    _seed_day(client)
    chennai = client.get(f"/api/officer/dayclose?port_id=chennai&date={TODAY}", headers=_port_headers()).json()
    assert chennai["departures"] == 1
    assert chennai["holds"] == 0
    assert chennai["broadcasts"] == 0


def test_dayclose_empty_day_zeros(client):
    resp = client.get("/api/officer/dayclose?port_id=kochi&date=2020-01-01", headers=_port_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert [body[k] for k in ("departures", "holds", "overdues_resolved", "mpa_hits", "broadcasts")] == [0, 0, 0, 0, 0]


# --- day-close CSV matches JSON ----------------------------------------------

def test_dayclose_csv_matches_json(client):
    _seed_day(client)
    qs = f"/api/officer/dayclose?port_id=kochi&date={TODAY}"
    js = client.get(qs, headers=_port_headers()).json()
    csv_resp = client.get(f"{qs}&format=csv", headers=_port_headers())
    assert csv_resp.status_code == 200, csv_resp.text
    assert csv_resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(csv_resp.text)))
    assert rows[0] == officer_mod.DAYCLOSE_COLUMNS
    assert rows[1] == [str(js[k]) for k in officer_mod.DAYCLOSE_COLUMNS]


# --- auth --------------------------------------------------------------------

def test_dayclose_401_and_port_scope(client):
    assert client.get(f"/api/officer/dayclose?port_id=kochi&date={TODAY}").status_code == 401
    wrong = client.get(
        f"/api/officer/dayclose?port_id=kochi&date={TODAY}",
        headers={"X-Officer-Token": "nope"},
    )
    assert wrong.status_code == 401
    assert client.get(f"/api/officer/dayclose?date={TODAY}", headers=_port_headers()).status_code == 400
    watch_all = client.get(f"/api/officer/dayclose?date={TODAY}", headers=_watch_headers())
    assert watch_all.status_code == 200
