"""
Single safety truth — threshold table + EEZ double-talk regression (#196).

Canonical bands (backend/agents/safety_thresholds.py):
  wave <2.0 safe / 2.0–3.5 caution / >3.5 danger
  wind <22kt safe / 22–27kt caution / >27kt danger
  current <2.0kt safe / 2.0–3.0kt caution / >3.0kt danger
Missing wave/wind → caution (fail-open, never SAFE).
Missing geofence (inside_eez=None) → unknown/caution, never a ban.
"""

import pytest

from backend.agents import safety_thresholds as st


# ---------------------------------------------------------------------------
# Threshold table — every importer must agree with canonical
# ---------------------------------------------------------------------------

WAVE_CASES = [
    (0.8, "safe"),
    (1.9, "safe"),
    (2.0, "caution"),
    (2.8, "caution"),
    (3.5, "caution"),
    (3.6, "danger"),
    (4.2, "danger"),
]

WIND_CASES = [
    (8.0, "safe"),
    (21.9, "safe"),
    (22.0, "caution"),
    (25.0, "caution"),
    (27.0, "caution"),
    (27.1, "danger"),
    (32.0, "danger"),
]

CURRENT_CASES = [
    (1.0, "safe"),
    (1.9, "safe"),
    (2.0, "caution"),
    (2.5, "caution"),
    (3.0, "caution"),
    (3.1, "danger"),
    (3.8, "danger"),
]


def test_canonical_constants():
    assert (st.WAVE_SAFE_MAX_M, st.WAVE_DANGER_MIN_M) == (2.0, 3.5)
    assert (st.WIND_SAFE_MAX_KT, st.WIND_DANGER_MIN_KT) == (22.0, 27.0)
    assert (st.CURRENT_SAFE_MAX_KT, st.CURRENT_DANGER_MIN_KT) == (2.0, 3.0)


@pytest.mark.parametrize("value,expected", WAVE_CASES)
def test_classify_wave_table(value, expected):
    assert st.classify_wave(value) == expected


@pytest.mark.parametrize("value,expected", WIND_CASES)
def test_classify_wind_table(value, expected):
    assert st.classify_wind(value) == expected


@pytest.mark.parametrize("value,expected", CURRENT_CASES)
def test_classify_current_table(value, expected):
    assert st.classify_current(value) == expected


@pytest.mark.parametrize("value,expected", WAVE_CASES)
def test_sea_checker_wave_parity(value, expected):
    from backend.agents.subagents import sea_checker

    assert sea_checker._classify_wave(value) == expected


@pytest.mark.parametrize("value,expected", CURRENT_CASES)
def test_sea_checker_current_parity(value, expected):
    from backend.agents.subagents import sea_checker

    assert sea_checker._classify_current(value) == expected


@pytest.mark.parametrize("value,expected", WIND_CASES)
def test_weather_agent_wind_parity(value, expected):
    from backend.agents.subagents import weather_agent

    assert weather_agent._classify_wind(value) == expected


def test_live_fetchers_constants_parity():
    from backend.ingest import live_fetchers as lf

    assert (lf.WAVE_SAFE_MAX, lf.WAVE_CAUTION_MAX) == (2.0, 3.5)
    assert (lf.WIND_SAFE_MAX, lf.WIND_CAUTION_MAX) == (22.0, 27.0)
    assert (lf.CURRENT_SAFE_MAX, lf.CURRENT_CAUTION_MAX) == (2.0, 3.0)


@pytest.mark.parametrize("value,expected", WIND_CASES)
def test_lexical_derive_wind_parity(value, expected):
    from backend.agents.lexical_mask import derive_safety_tier

    assert derive_safety_tier(0.8, value) == expected.upper()


@pytest.mark.parametrize("value,expected", WAVE_CASES)
def test_lexical_derive_wave_parity(value, expected):
    from backend.agents.lexical_mask import derive_safety_tier

    assert derive_safety_tier(value, 8.0) == expected.upper()


@pytest.mark.parametrize("value,expected", CURRENT_CASES)
def test_lexical_derive_current_parity(value, expected):
    from backend.agents.lexical_mask import derive_safety_tier

    # current breaches escalate even when wave/wind are calm
    assert derive_safety_tier(0.8, 8.0, current_kt=value) == expected.upper()


@pytest.mark.parametrize("value,expected", WIND_CASES)
def test_combiner_veto_wind_parity(value, expected):
    from backend.agents.combiner import apply_safety_veto

    zone = {"wave_height_m": 0.8, "wind_kt": value, "inside_eez": True, "inside_mpa": False}
    assert apply_safety_veto(zone) == expected


@pytest.mark.parametrize("value,expected", WAVE_CASES)
def test_combiner_veto_wave_parity(value, expected):
    from backend.agents.combiner import apply_safety_veto

    zone = {"wave_height_m": value, "wind_kt": 8.0, "inside_eez": True, "inside_mpa": False}
    assert apply_safety_veto(zone) == expected


@pytest.mark.parametrize("value,expected", WIND_CASES)
def test_orchestrator_veto_wind_parity(value, expected):
    from backend.agents.orchestrator import _veto_safety

    wind_kph = round(value * st.KT_TO_KPH, 2)
    safety, _ = _veto_safety(0.8, wind_kph, True, False, False)
    assert safety == expected


def test_officer_danger_rule_parity():
    from backend.routers.officer import is_danger_sea_state

    assert is_danger_sea_state(wind_kt=28.0) is True
    assert is_danger_sea_state(wave_m=3.6) is True
    assert is_danger_sea_state(current_kt=3.1) is True
    assert is_danger_sea_state(wind_kt=27.0, wave_m=3.5, current_kt=3.0) is False
    assert is_danger_sea_state(wind_kt=8.0, wave_m=0.8, current_kt=1.0) is False


def test_missing_wave_wind_fail_open_caution():
    # Missing measurements never read SAFE (map invariant).
    assert st.derive_safety_tier(None, 8.0) == "CAUTION"
    assert st.derive_safety_tier(0.8, None) == "CAUTION"
    assert st.derive_safety_tier(None, None) == "CAUTION"
    assert st.apply_safety_veto({"wave_height_m": None, "wind_kt": 8.0}) == "caution"
    # ...but a measured breach still reads DANGER when the other is missing.
    assert st.derive_safety_tier(4.0, None) == "DANGER"
    assert st.derive_safety_tier(None, 30.0) == "DANGER"


# ---------------------------------------------------------------------------
# Geofence: None = unknown = caution, never a ban
# ---------------------------------------------------------------------------


def test_is_banned_explicit_only():
    assert st.is_banned(False, True) is False
    assert st.is_banned(False, None) is False  # unknown, never a ban
    assert st.is_banned(None, None) is False
    assert st.is_banned(False, False) is True  # explicitly outside EEZ
    assert st.is_banned(True, True) is True  # inside MPA
    assert st.is_banned(True, None) is True


def test_combiner_missing_geofence_unknown_not_banned():
    from backend.agents.combiner import combine_and_rank

    fish = [
        {
            "zone_id": "z1",
            "place": "Chillickal",
            "sector": "KERALA",
            "lat": 9.79,
            "lon": 75.81,
            "distance_from_user_km": 52.7,
        }
    ]
    sea = [{"zone_id": "z1", "wave_height_m": 1.2}]
    weather = [{"zone_id": "z1", "wind_kt": 8.2}]
    # Entry present but flags missing → unknown, not a ban.
    danger = [{"zone_id": "z1"}]
    result = combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
    best = result["best"]
    assert best["inside_eez"] is None
    assert best["score_breakdown"]["not_banned"] == 0.5
    assert result["all_unsafe"] is False


def test_orchestrator_degraded_danger_unknown_not_banned():
    from backend.agents.orchestrator import _degraded_danger

    out = _degraded_danger([{"zone_id": "z1", "place": "P", "lat": 1.0, "lon": 2.0}])
    assert out[0]["inside_eez"] is None
    assert st.is_banned(out[0]["inside_mpa"], out[0]["inside_eez"]) is False


# ---------------------------------------------------------------------------
# EEZ double-talk: spelled-out warning must suppress "No violation"
# ---------------------------------------------------------------------------

SPELLED_OUT = "Outside Indian Exclusive Economic Zone — fishing not permitted"
ABBREVIATED = "Outside EEZ — fishing not permitted"


def test_violation_text_matches_both_spellings():
    assert st.is_geofence_violation_text(SPELLED_OUT) is True
    assert st.is_geofence_violation_text(ABBREVIATED) is True
    assert st.is_geofence_violation_text("Inside Marine Protected Area: X — fishing strictly banned") is True
    assert st.is_geofence_violation_text("No EEZ/MPA violation") is True
    assert st.is_geofence_violation_text("Wave: live model") is False
    assert st.is_geofence_violation_text("") is False


@pytest.mark.parametrize("warning", [SPELLED_OUT, ABBREVIATED])
def test_no_double_talk_when_violation_present(warning):
    # Banned or not, a violation warning must NEVER sit next to "No violation".
    for banned in (True, False):
        ev = st.resolve_geofence_evidence(banned, [warning])
        assert warning in ev
        assert "No EEZ/MPA violation" not in ev


def test_banned_without_warning_still_reports_violation():
    ev = st.resolve_geofence_evidence(True, [])
    assert "No EEZ/MPA violation" not in ev
    assert any(st.is_geofence_violation_text(e) for e in ev)


def test_clean_waters_report_no_violation_once():
    ev = st.resolve_geofence_evidence(False, [])
    assert ev == ["No EEZ/MPA violation"]


def test_skipped_check_notes_never_become_verdicts():
    ev = st.resolve_geofence_evidence(False, ["geofence check skipped by planner"])
    assert "geofence check skipped by planner" not in ev
