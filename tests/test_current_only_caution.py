"""
Option 1 — current-only breach is CAUTION, never a sole DO NOT SAIL veto.

Regression for: Kochi/Munambam always answered DO NOT SAIL because every
nearby PFZ zone shared one Open-Meteo grid cell with ocean current
~4.28kt (>3.0kt danger band) while wave/wind/geofence were all safe.

Canonical rule (backend/agents/safety_thresholds.py):
  - Veto (DANGER / all_unsafe / DO NOT SAIL) requires wave danger,
    wind danger, geofence ban, cyclone, or all_unsafe from those.
  - Current >3.0kt ALONE → CAUTION (strong current, proceed with care).
  - Current 2.0–3.0kt → CAUTION (unchanged).
  - Wave/wind danger combined with current danger still → DANGER.
"""

import pytest

from backend.agents import safety_thresholds as st


# ---------------------------------------------------------------------------
# derive_safety_tier — current alone never reaches DANGER
# ---------------------------------------------------------------------------


def test_current_only_danger_is_caution_tier():
    # Live repro: Kochi zones wave 1.42m, wind 14.6kt, current 4.28kt.
    assert st.derive_safety_tier(1.42, 14.6, current_kt=4.28) == "CAUTION"
    assert st.derive_safety_tier(1.4, 14.6, current_kt=3.1) == "CAUTION"
    assert st.derive_safety_tier(0.8, 8.0, current_kt=10.0) == "CAUTION"


def test_current_caution_band_still_caution():
    assert st.derive_safety_tier(1.0, 10.0, current_kt=2.5) == "CAUTION"


def test_wave_danger_with_current_danger_still_danger():
    assert st.derive_safety_tier(3.6, 14.6, current_kt=4.28) == "DANGER"


def test_wind_danger_with_current_danger_still_danger():
    assert st.derive_safety_tier(1.4, 30.0, current_kt=4.28) == "DANGER"


def test_banned_with_calm_current_still_danger():
    assert st.derive_safety_tier(1.0, 10.0, banned=True, current_kt=1.0) == "DANGER"


def test_all_unsafe_flag_still_danger_even_with_safe_current():
    assert st.derive_safety_tier(1.0, 10.0, all_unsafe=True, current_kt=1.0) == "DANGER"


def test_missing_wave_with_current_breach_is_caution_not_danger():
    # Missing wave fails open to CAUTION; current alone must not escalate.
    assert st.derive_safety_tier(None, 10.0, current_kt=4.28) == "CAUTION"
    assert st.derive_safety_tier(1.0, None, current_kt=4.28) == "CAUTION"


# ---------------------------------------------------------------------------
# apply_safety_veto / veto_safety — zone annotation follows the same rule
# ---------------------------------------------------------------------------


def test_apply_safety_veto_current_only_is_caution():
    zone = {
        "wave_height_m": 1.42,
        "wind_kt": 14.6,
        "current_kt": 4.28,
        "inside_eez": True,
        "inside_mpa": False,
    }
    assert st.apply_safety_veto(zone) == "caution"


def test_apply_safety_veto_wave_danger_still_danger():
    zone = {
        "wave_height_m": 3.8,
        "wind_kt": 14.6,
        "current_kt": 4.28,
        "inside_eez": True,
        "inside_mpa": False,
    }
    assert st.apply_safety_veto(zone) == "danger"


def test_veto_safety_current_only_is_caution():
    safety, _conf = st.veto_safety(1.42, 14.6, True, False, False, current_kt=4.28)
    assert safety == "caution"


# ---------------------------------------------------------------------------
# Combiner — current_exceeded alone never sets all_unsafe / DO NOT SAIL
# ---------------------------------------------------------------------------


def _kochi_like_zones():
    """Three zones: safe wave/wind/geofence, current over danger band."""
    places = [("Kuzhuppilly", 49.5), ("Kodungallur", 50.5), ("Ernakulam", 50.8)]
    fish, sea, weather, danger = [], [], [], []
    for i, (name, dist) in enumerate(places):
        zid = f"z{i}"
        fish.append(
            {
                "zone_id": zid,
                "place": name,
                "sector": "SEC005",
                "lat": 10.05,
                "lon": 75.83,
                "distance_from_user_km": dist,
            }
        )
        sea.append({"zone_id": zid, "wave_height_m": 1.42, "current_kt": 4.28})
        weather.append({"zone_id": zid, "wind_kt": 14.6})
        danger.append({"zone_id": zid, "inside_eez": True, "inside_mpa": False})
    return fish, sea, weather, danger


def test_combiner_current_only_never_all_unsafe():
    from backend.agents.combiner import combine_and_rank

    fish, sea, weather, danger = _kochi_like_zones()
    result = combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
    assert result["all_unsafe"] is False
    assert "DO NOT SAIL" not in result["explanation"].upper()
    assert result["best"] is not None
    assert len(result["ranked_zones"]) == 3
    # Strong current still surfaces as per-zone caution, not safe.
    assert all(z["safety"] == "caution" for z in result["ranked_zones"])
    # Scoring still records the breach for transparency.
    assert all(
        z["score_breakdown"]["current_exceeded"] is True
        for z in result["ranked_zones"]
    )


def test_combiner_wave_danger_still_all_unsafe():
    from backend.agents.combiner import combine_and_rank

    fish, sea, weather, danger = _kochi_like_zones()
    for s in sea:
        s["wave_height_m"] = 3.8
    result = combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
    assert result["all_unsafe"] is True
    assert "DO NOT SAIL" in result["explanation"]


def test_combiner_banned_still_all_unsafe_despite_calm_metrics():
    from backend.agents.combiner import combine_and_rank

    fish, sea, weather, danger = _kochi_like_zones()
    for s in sea:
        s["current_kt"] = 1.0
    for d in danger:
        d["inside_eez"] = False
    result = combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
    assert result["all_unsafe"] is True
    assert "DO NOT SAIL" in result["explanation"]


# ---------------------------------------------------------------------------
# sea_checker — overall status: current-only danger caps at caution
# ---------------------------------------------------------------------------


def test_sea_checker_overall_current_only_caps_at_caution():
    from backend.agents.subagents.sea_checker import _overall_status

    assert _overall_status("safe", "danger") == "caution"
    assert _overall_status("caution", "danger") == "caution"
    # Wave danger still wins as danger.
    assert _overall_status("danger", "danger") == "danger"
    assert _overall_status("danger", "safe") == "danger"
    assert _overall_status("safe", "safe") == "safe"
    assert _overall_status("safe", "caution") == "caution"


@pytest.mark.asyncio
async def test_sea_checker_check_current_only_status_caution():
    from unittest.mock import patch

    from backend.agents.subagents import sea_checker

    points = [{"zone_id": "z1", "place": "StrongCurrent", "lat": 10.0, "lon": 76.0}]

    async def fake_get(lat, lon, zone_id, idx):
        return (1.42, 4.28, "open_meteo_live")  # safe wave, danger current

    with patch.object(sea_checker, "get_wave_current", side_effect=fake_get):
        results = await sea_checker.check_sea_conditions(points)

    # Raw metric classification stays danger for observability...
    assert results[0]["current_status"] == "danger"
    # ...but overall status (badge / DO NOT SAIL inputs) is caution.
    assert results[0]["status"] == "caution"


@pytest.mark.asyncio
async def test_sea_checker_wave_danger_still_overall_danger():
    from unittest.mock import patch

    from backend.agents.subagents import sea_checker

    points = [{"zone_id": "z1", "place": "Rough", "lat": 10.0, "lon": 76.0}]

    async def fake_get(lat, lon, zone_id, idx):
        return (3.8, 4.28, "open_meteo_live")

    with patch.object(sea_checker, "get_wave_current", side_effect=fake_get):
        results = await sea_checker.check_sea_conditions(points)

    assert results[0]["status"] == "danger"
