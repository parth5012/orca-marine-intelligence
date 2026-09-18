"""
Tests for Officer Register Alerts (Wayfinder #170 T5, issue #175).

Covers the three deterministic alert rules computed (never stored) per
departure row by GET /api/officer/departures:
- overdue amber/red boundaries (amber>120min, red>360min — T2 compute_overdue)
- risky destination: inside MPA / <2km IMBL / outside EEZ
  (thresholds from backend/ingest/boundaries.py via geofence.py:58)
- weather flip: status at log (safe|caution) -> danger now
  (red rule mirrors weather.py:136)

No network: geofence reads local data/*.geojson; weather comparisons use
injected statuses / DEST_STATUS_PROVIDER fakes.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import officer as officer_mod

PORT_TOKEN = os.getenv("PORT_TOKEN", "test-port-token")
WATCH_TOKEN = os.getenv("WATCH_TOKEN", "test-watch-token")

# Real-data points (data/mpa.geojson + data/eez.geojson + canonical IMBL).
MPA_INSIDE = {"lat": 9.05, "lon": 79.05}  # Gulf of Mannar MPA box
OPEN_SEA = {"lat": 9.5, "lon": 76.0}  # inside West EEZ, outside all MPAs, far from IMBL
IMBL_ON_LINE = {"lat": 8.0, "lon": 78.5}  # canonical IMBL waypoint, outside EEZ+MPAs


@pytest.fixture
def client():
    officer_mod.clear_officer_stores()
    old_provider = officer_mod.DEST_STATUS_PROVIDER
    officer_mod.DEST_STATUS_PROVIDER = None
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    officer_mod.DEST_STATUS_PROVIDER = old_provider
    officer_mod.clear_officer_stores()


def _headers():
    return {"X-Officer-Token": PORT_TOKEN}


def _payload(**over):
    now = datetime.now(timezone.utc)
    body = {
        "port_id": "kochi",
        "boat_id": "KL-07-MM-1",
        "crew": 4,
        "time_out": (now - timedelta(hours=1)).isoformat(),
        "expected_in": (now + timedelta(hours=6)).isoformat(),
        "dest_lat": OPEN_SEA["lat"],
        "dest_lon": OPEN_SEA["lon"],
    }
    body.update(over)
    return body


def _expected(delta_min: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=delta_min)


# --- overdue boundaries (pure) ------------------------------------------------

@pytest.mark.parametrize(
    "mins,band",
    [(119, "none"), (120, "none"), (121, "amber"), (359, "amber"), (360, "amber"), (361, "red")],
)
def test_overdue_boundaries(mins, band):
    got_mins, got_band = officer_mod.compute_overdue(_expected(mins), datetime.now(timezone.utc))
    assert got_band == band
    assert got_mins == mins


# --- geofence classifier (pure, 2km IMBL threshold) ----------------------------

@pytest.mark.parametrize(
    "mpa_hit,imbl_km,inside_eez,flag",
    [
        (True, 50.0, True, "mpa"),
        (True, 0.0, False, "mpa"),  # mpa wins over imbl/outside_eez
        (False, 1.9, True, "imbl"),
        (False, 0.0, False, "imbl"),  # imbl wins over outside_eez
        (False, 2.0, True, "none"),  # strict <2km
        (False, 2.1, True, "none"),
        (False, 50.0, False, "outside_eez"),
        (False, 50.0, True, "none"),
    ],
)
def test_classify_geofence(mpa_hit, imbl_km, inside_eez, flag):
    assert officer_mod.classify_geofence(mpa_hit, imbl_km, inside_eez) == flag


def test_imbl_threshold_value_matches_geofence():
    assert float(officer_mod.IMBL_BUFFER_KM) == 2.0


# --- geofence against real boundary data ---------------------------------------

def test_geofence_mpa_hit_real_data():
    assert officer_mod.compute_geofence_flag(MPA_INSIDE["lat"], MPA_INSIDE["lon"]) == "mpa"


def test_geofence_open_sea_none():
    assert officer_mod.compute_geofence_flag(OPEN_SEA["lat"], OPEN_SEA["lon"]) == "none"


def test_geofence_imbl_on_line_beats_outside_eez():
    assert officer_mod.compute_geofence_flag(IMBL_ON_LINE["lat"], IMBL_ON_LINE["lon"]) == "imbl"


def test_imbl_distance_boundary_real_segments():
    from backend.ingest.boundaries import distance_to_imbl_km

    near = distance_to_imbl_km(IMBL_ON_LINE["lat"] + 0.0171, IMBL_ON_LINE["lon"])  # ~1.5km
    far = distance_to_imbl_km(IMBL_ON_LINE["lat"] + 0.025, IMBL_ON_LINE["lon"])  # ~2.2km
    assert near < 2.0
    assert far > 2.0


# --- weather flag (pure) + red rule mirror -------------------------------------

@pytest.mark.parametrize(
    "at_log,now,flag",
    [
        ("safe", "danger", "flip"),
        ("caution", "danger", "flip"),
        ("safe", "safe", "none"),
        ("safe", "caution", "none"),
        ("danger", "danger", "none"),
        (None, "danger", "none"),
        ("safe", None, "none"),
        ("bogus", "danger", "none"),
    ],
)
def test_compute_weather_flag(at_log, now, flag):
    assert officer_mod.compute_weather_flag(at_log, now) == flag


@pytest.mark.parametrize(
    "kwargs,danger",
    [
        ({"wind_kt": 25.1}, True),
        ({"wind_kt": 25.0}, False),
        ({"wave_m": 2.6}, True),
        ({"wave_m": 2.5}, False),
        ({"current_kt": 2.6}, True),
        ({"current_kt": 2.5}, False),
        ({"pressure_hpa": 994.9}, True),
        ({"pressure_hpa": 995.0}, False),
        ({"wind_kt": 10, "wave_m": 1.0, "current_kt": 1.0, "pressure_hpa": 1013}, False),
    ],
)
def test_danger_sea_state_mirrors_weather_thresholds(kwargs, danger):
    assert officer_mod.is_danger_sea_state(**kwargs) is danger


# --- endpoint: alerts computed, never stored ------------------------------------

def test_departures_rows_carry_alerts_not_stored(client):
    created = client.post(
        "/api/officer/departures",
        json=_payload(dest_lat=MPA_INSIDE["lat"], dest_lon=MPA_INSIDE["lon"], weather_at_log="safe"),
        headers=_headers(),
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["geofence_flag"] == "mpa"
    assert body["weather_flag"] == "none"  # no provider -> unknown now -> none
    assert body["overdue_status"] == "none"

    stored = officer_mod._departures[0]
    assert "overdue_mins" not in stored
    assert "overdue_status" not in stored
    assert "geofence_flag" not in stored
    assert "weather_flag" not in stored
    assert stored["weather_at_log"] == "safe"  # input baseline kept, not computed

    listed = client.get("/api/officer/departures?port_id=kochi", headers=_headers()).json()
    assert listed["departures"][0]["geofence_flag"] == "mpa"


def test_weather_flip_via_provider(client):
    officer_mod.DEST_STATUS_PROVIDER = lambda lat, lon: "danger"
    created = client.post(
        "/api/officer/departures", json=_payload(weather_at_log="safe"), headers=_headers()
    )
    assert created.json()["weather_flag"] == "flip"

    officer_mod.DEST_STATUS_PROVIDER = lambda lat, lon: "safe"
    listed = client.get("/api/officer/departures?port_id=kochi", headers=_headers()).json()
    assert listed["departures"][0]["weather_flag"] == "none"


def test_provider_failure_degrades_to_none(client):
    def _boom(lat, lon):
        raise RuntimeError("weather down")

    officer_mod.DEST_STATUS_PROVIDER = _boom
    created = client.post(
        "/api/officer/departures", json=_payload(weather_at_log="safe"), headers=_headers()
    )
    assert created.status_code == 200
    assert created.json()["weather_flag"] == "none"


def test_overdue_red_row_still_flags(client):
    now = datetime.now(timezone.utc)
    payload = _payload(
        dest_lat=MPA_INSIDE["lat"],
        dest_lon=MPA_INSIDE["lon"],
        expected_in=(now - timedelta(hours=7)).isoformat(),
    )
    body = client.post("/api/officer/departures", json=payload, headers=_headers()).json()
    assert body["overdue_status"] == "red"
    assert body["geofence_flag"] == "mpa"
