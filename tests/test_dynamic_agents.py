"""
Dynamic Agentic Reasoning Verification Suite — ORCA Marine Intelligence.

Ticket: M-A: Build Dynamic Agentic Reasoning Verification Suite
Link: https://github.com/parth5012/orca-marine-intelligence/issues/29
Map context: https://github.com/parth5012/orca-marine-intelligence/issues/22

All tests are mock-backed, offline, no API keys:
  - backend/ingest/mock_fetchers.py (SimulationScenario + mock_fetch_all
    shared-candidate fan-out)
  - backend/agents/planner_schema.py (PlannerOutput, 0.6 gate, registry)
  - backend/agents/graph.py (SSE order, node names)
  - backend/agents/combiner.py + lexical_mask.py (veto, localized advisory)

Map invariants covered:
  - P95<2.0s (generous <2.0s asserts only; no sub-second thresholds —
    machine is slow, test_parallel_gather_efficiency 0.60s fails here)
  - degradation 0.87 -> 0.62 (DEFAULT/DEGRADED_CONFIDENCE)
  - shared-candidate invariant (same PFZ features fanned to sea/weather/danger)

Redis note (Test 5): does NOT require live Redis. Uses backend.db.redis
in-memory fallback (fakeredis-style stub via unittest.mock when needed).
Marked clearly in TestMultiTurnSession.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from backend.agents import combiner as cb
from backend.agents import lexical_mask as lm
from backend.agents import orchestrator
from backend.agents import planner_schema as ps
from backend.ingest.mock_fetchers import (
    SimulationScenario,
    mock_check_geofence_boundaries,
    mock_fetch_all,
    mock_fetch_imd_marine_weather,
    mock_fetch_incois_pfz,
    mock_fetch_osf_ocean_state,
    set_mock_scenario,
)

# ---------------------------------------------------------------------------
# Constants + helpers (offline, deterministic)
# ---------------------------------------------------------------------------

KOCHI_LAT = 9.93
KOCHI_LON = 76.26


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(math.sqrt(a))


def _flat_fish_from_pfz(pfz_features: list[dict], user_lat: float, user_lon: float) -> list[dict]:
    """Normalize mock PFZ GeoJSON Features -> combiner flat fish_results.

    Preserves zone_id join keys so ocean/weather/geofence results (keyed by
    the same zone_id via mock _extract_point) align by zone_id.
    """
    flat: list[dict] = []
    for f in pfz_features:
        props = f.get("properties", {}) if isinstance(f, dict) else {}
        geom = f.get("geometry", {}) if isinstance(f, dict) else {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        lat = props.get("lat", props.get("latitude"))
        lon = props.get("lon", props.get("longitude", props.get("lng")))
        if lat is None and isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lat = float(coords[1])
            except (TypeError, ValueError):
                lat = None
        if lon is None and isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lon = float(coords[0])
            except (TypeError, ValueError):
                lon = None
        zone_id = str(props.get("zone_id", f.get("zone_id", "unknown")))
        place = str(props.get("place", "Unknown"))
        dist = _haversine_km(user_lat, user_lon, float(lat), float(lon))
        flat.append(
            {
                "zone_id": zone_id,
                "place": place,
                "sector": str(props.get("sector", props.get("sector_name", "SEC005"))),
                "lat": float(lat),
                "lon": float(lon),
                "distance_km": round(dist, 2),
                "distance_from_user_km": round(dist, 2),
                "bearing": props.get("bearing"),
                "direction": props.get("direction"),
                "depth_range": str(props.get("depth", props.get("depth_range", ""))),
            }
        )
    flat.sort(key=lambda z: z["distance_from_user_km"])
    return flat


def _run_mock_pipeline(
    scenario: SimulationScenario | str,
    center_lat: float = KOCHI_LAT,
    center_lon: float = KOCHI_LON,
    count: int = 5,
    detected_language: str = "en",
) -> dict:
    """Full mock pipeline: mock_fetch_all -> flat fish -> combiner + badge.

    Returns dict with batch, fish, ocean/weather/geofence results, combined,
    best, badge + per-agent statuses for the best zone.
    """
    batch = mock_fetch_all(
        sector="SEC005",
        center_lat=center_lat,
        center_lon=center_lon,
        count=count,
        scenario=scenario,
    )
    pfz_features: list[dict] = batch["pfz"]["features"]
    fish = _flat_fish_from_pfz(pfz_features, center_lat, center_lon)
    ocean = batch["ocean"]["results"]
    weather = batch["weather"]["results"]
    geofence = batch["geofence"]["results"]
    combined = cb.combine_and_rank(
        fish,
        ocean,
        weather,
        geofence,
        {"lat": center_lat, "lon": center_lon},
        detected_language=detected_language,
    )
    best = combined.get("best")
    badge = "amber"
    sea_s = wind_s = danger_s = "unknown"
    if best is not None:
        bid = str(best.get("zone_id"))
        for r in ocean:
            if str(r.get("zone_id")) == bid:
                sea_s = str(r.get("status", "safe")).lower()
                break
        else:
            sea_s = "safe"
        for r in weather:
            if str(r.get("zone_id")) == bid:
                wind_s = str(r.get("status", "safe")).lower()
                break
        else:
            wind_s = "safe"
        for r in geofence:
            if str(r.get("zone_id")) == bid:
                danger_s = str(r.get("status", "safe")).lower()
                break
        else:
            danger_s = "safe"
        badge = orchestrator._badge_for_best(best, sea_s, wind_s, danger_s)
    return {
        "batch": batch,
        "fish": fish,
        "ocean": ocean,
        "weather": weather,
        "geofence": geofence,
        "combined": combined,
        "best": best,
        "badge": badge,
        "sea_s": sea_s,
        "wind_s": wind_s,
        "danger_s": danger_s,
    }


@pytest.fixture(autouse=True)
def _reset_mock_scenario():
    set_mock_scenario(SimulationScenario.NORMAL)
    yield
    set_mock_scenario(SimulationScenario.NORMAL)


# ---------------------------------------------------------------------------
# 1. Malayalam Kochi NORMAL — PFZ<=80km, green badge, Malayalam, INCOIS
# ---------------------------------------------------------------------------


class TestMalayalamKochiNormal:
    def test_malayalam_kochi_normal_green_malayalam_incois(self):
        out = _run_mock_pipeline(SimulationScenario.NORMAL, detected_language="ml")
        fish = out["fish"]
        assert len(fish) >= 1, "NORMAL mock must yield >=1 PFZ candidate"

        # PFZ within 80km (independent haversine check, not mock distance field)
        for z in fish:
            d = _haversine_km(KOCHI_LAT, KOCHI_LON, z["lat"], z["lon"])
            assert d <= 80.0, f"{z['zone_id']} {d:.1f}km exceeds 80km radius"
        assert out["best"] is not None
        assert out["best"]["distance_km"] <= 80.0

        # Green badge: NORMAL seas are calm (waves 0.7-1.4, wind 7-14, geofence safe)
        assert out["sea_s"] == "safe", f"sea {out['sea_s']}"
        assert out["wind_s"] == "safe", f"wind {out['wind_s']}"
        assert out["danger_s"] == "safe", f"danger {out['danger_s']}"
        assert out["badge"] == "green", (
            f"badge {out['badge']} statuses sea={out['sea_s']} wind={out['wind_s']} danger={out['danger_s']}"
        )

        # Combiner veto not tripped on calm seas
        assert out["combined"]["all_unsafe"] is False

        # Malayalam advisory: non-ASCII native script, Arabic numerals preserved
        explanation: str = out["combined"]["explanation"]
        assert any(ord(c) > 127 for c in explanation), "advisory must be non-ASCII (Malayalam)"
        assert lm.contains_native_script(explanation, "ml"), f"no Malayalam script in {explanation!r}"
        assert not lm.has_regional_digits(explanation), "regional digits forbidden (Arabic 0-9 only)"
        assert re.search(r"[0-9]", explanation), "numerals must be preserved in advisory"
        # English audit trail preserved
        assert "explanation_en" in out["combined"]
        assert "Recommended:" in out["combined"]["explanation_en"]

        # INCOIS citation preserved verbatim
        citation: str = out["combined"]["citation"]
        assert "INCOIS" in citation, f"citation missing INCOIS: {citation!r}"
        assert "INCOIS" in explanation, "localized advisory must carry INCOIS citation"

        # Shared-candidate invariant for this batch
        pfz_ids = [f["properties"]["zone_id"] for f in out["batch"]["pfz"]["features"]]
        assert [r["zone_id"] for r in out["ocean"]] == pfz_ids
        assert [r["zone_id"] for r in out["weather"]] == pfz_ids
        assert [r["zone_id"] for r in out["geofence"]] == pfz_ids


# ---------------------------------------------------------------------------
# 2. CYCLONE_WARNING within 300km — weather Danger, DO NOT SAIL, red badge
# ---------------------------------------------------------------------------


class TestCycloneWarning:
    def test_cyclone_warning_danger_do_not_sail_red(self):
        out = _run_mock_pipeline(SimulationScenario.CYCLONE_WARNING)
        weather = out["weather"]
        assert len(weather) >= 1

        # Weather Danger on every point, cyclone alert within buffer
        for r in weather:
            assert r["status"] == "danger", f"{r['zone_id']} status {r['status']}"
            assert r["cyclone_alert"] is True
            assert r["nearest_cyclone_km"] is not None
            assert r["nearest_cyclone_km"] <= 500.0, "cyclone must be within 500km buffer"

        # Batch-level cyclone entry within 80-300km per mock contract
        cyclones = out["batch"]["weather"]["cyclones"]
        assert len(cyclones) >= 1, "CYCLONE_WARNING must list >=1 active cyclone"
        assert cyclones[0]["buffer_km"] == 500
        assert 80.0 <= cyclones[0]["distance_km"] <= 300.0, (
            f"cyclone distance {cyclones[0]['distance_km']} outside 80-300km spec"
        )
        # Per-point nearest within 300km nominal (allow PFZ spread slack to 500)
        assert any(r["nearest_cyclone_km"] <= 300.0 for r in weather), (
            "at least one point must see cyclone within ticket-spec 300km"
        )

        # Combiner veto: all_unsafe + DO NOT SAIL (code trumps LLM)
        assert out["combined"]["all_unsafe"] is True
        explanation: str = out["combined"]["explanation"]
        assert "do not sail" in explanation.lower(), f"veto missing in {explanation!r}"

        # Red badge (danger present)
        assert out["wind_s"] == "danger"
        assert out["badge"] == "red", f"badge {out['badge']} expected red for cyclone danger"


# ---------------------------------------------------------------------------
# 3. MPA spot — danger agent flags/rejects (BORDER_VIOLATION)
# ---------------------------------------------------------------------------


class TestMpaGeofenceVeto:
    def test_border_violation_mpa_flagged_and_vetoed(self):
        out = _run_mock_pipeline(SimulationScenario.BORDER_VIOLATION)
        geo = out["geofence"]
        assert len(geo) >= 3, "need >=3 points to cover rotating MPA/IMBL/EEZ modes"

        # Rotating violations per mock contract: i%3==0 MPA danger, 1 IMBL caution, 2 EEZ danger
        assert geo[0]["inside_mpa"] is True
        assert geo[0]["status"] == "danger"
        assert any("Protected Area" in w or "MPA" in w for w in geo[0]["warnings"]), geo[0]["warnings"]

        assert geo[1]["near_imbl"] is True
        assert geo[1]["status"] == "caution"
        assert any("Boundary" in w for w in geo[1]["warnings"]), geo[1]["warnings"]

        assert geo[2]["inside_eez"] is False
        assert geo[2]["status"] == "danger"
        assert any("Exclusive Economic Zone" in w for w in geo[2]["warnings"]), geo[2]["warnings"]

        assert out["batch"]["geofence"]["restricted_count"] > 0

        # Combiner hard veto: banned (MPA / outside-EEZ) zones never win.
        # Calm seas here, so the winner must be a legal zone (inside EEZ, outside MPA).
        best = out["combined"]["best"]
        assert best is not None
        assert best["inside_mpa"] is False, f"veto failed: MPA zone won {best!r}"
        assert best["inside_eez"] is True, f"veto failed: outside-EEZ zone won {best!r}"

        # MPA zones score strictly lower than the winner (veto via not_banned=0)
        mpa_ids = {r.get("zone_id") for r in geo if r.get("inside_mpa")}
        assert mpa_ids, "BORDER_VIOLATION must contain >=1 MPA zone"
        ranked = {z["zone_id"]: z for z in out["combined"]["ranked_zones"]}
        for mid in mpa_ids:
            assert mid in ranked
            assert ranked[mid]["score"] < best["score"], (
                f"MPA {mid} score {ranked[mid]['score']} not below best {best['score']}"
            )

    def test_direct_geofence_mock_flags_mpa(self):
        """Direct mock geofence call (no pipeline) also flags MPA — offline."""
        pts = [{"zone_id": "x0", "place": "Test", "lat": KOCHI_LAT, "lon": KOCHI_LON}]
        res = mock_check_geofence_boundaries(pts, SimulationScenario.BORDER_VIOLATION)
        assert res["status"] == "success"
        assert res["results"][0]["inside_mpa"] is True
        assert res["results"][0]["status"] == "danger"


# ---------------------------------------------------------------------------
# 4. No GPS/port — planner needs_clarification + GPS prompt (confidence<0.6)
# ---------------------------------------------------------------------------


class TestPlannerClarification:
    def test_planner_output_clarification_gate(self):
        # Gate constant per planner_schema contract
        assert ps.CLARIFICATION_THRESHOLD == pytest.approx(0.6)
        assert set(ps.KNOWN_TOOLS) == {
            "find_fishing_zones",
            "check_ocean_state",
            "check_weather",
            "check_geofence",
        }

        # confidence<0.6 -> clarify (never fabricate coords)
        low = ps.PlannerOutput(
            detected_language="en",
            target_location=ps.TargetLocation(lat=None, lon=None, confidence=0.0),
            intents=[],
            confidence=0.4,
            reasoning_trace=[],
            selected_tools=[],
        )
        assert low.needs_clarification() is True

        # missing lat/lon clarifies even at high overall confidence
        no_loc = ps.PlannerOutput(
            detected_language="en",
            target_location=ps.TargetLocation(lat=None, lon=None, confidence=0.9),
            intents=["find_fish"],
            confidence=0.9,
            reasoning_trace=[],
            selected_tools=[],
        )
        assert no_loc.needs_clarification() is True

        # low location confidence clarifies
        low_loc = ps.PlannerOutput(
            detected_language="en",
            target_location=ps.TargetLocation(lat=KOCHI_LAT, lon=KOCHI_LON, confidence=0.5),
            intents=["find_fish"],
            confidence=0.9,
            reasoning_trace=[],
            selected_tools=[],
        )
        assert low_loc.needs_clarification() is True

        # confident + located -> dispatch
        ok = ps.PlannerOutput(
            detected_language="en",
            target_location=ps.TargetLocation(
                lat=KOCHI_LAT, lon=KOCHI_LON, port_name="Kochi", confidence=0.95
            ),
            intents=["find_fish", "check_safety"],
            confidence=0.9,
            reasoning_trace=["find_fishing_zones selected: fish intent"],
            selected_tools=["find_fishing_zones"],
        )
        assert ok.needs_clarification() is False

    def test_coastal_ports_registry_present(self):
        # Registry extends orchestrator.COASTAL_PORTS with draft ports
        for port in ("Munambam", "Beypore", "Kollam", "Veraval"):
            assert port in ps.COASTAL_PORTS_REGISTRY, f"{port} missing from registry"
        lat, lon = ps.COASTAL_PORTS_REGISTRY["Munambam"]
        assert -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0

    @pytest.mark.asyncio
    async def test_no_location_returns_gps_prompt_degraded(self):
        """No GPS/port -> GPS prompt, degraded confidence 0.62, amber badge.

        Offline: planner short-circuits before any PostGIS/OSF/IMD call;
        Redis get_session uses in-memory fallback (no live server needed).
        """
        from backend.agents.graph import orchestrate_via_graph

        assert orchestrator.DEFAULT_CONFIDENCE == pytest.approx(0.87)
        assert orchestrator.DEGRADED_CONFIDENCE == pytest.approx(0.62)

        result = await orchestrate_via_graph(
            query="Where is fish?",
            language="en",
            location=None,
            session_id=f"test-noloc-{uuid.uuid4().hex[:8]}",
        )
        reply = result.get("reply", "")
        assert ("GPS" in reply) or ("location" in reply.lower()), f"no GPS prompt in {reply!r}"
        assert result.get("confidence") == pytest.approx(0.62)
        assert result.get("map", {}).get("center") is None
        assert result.get("safety", {}).get("badge") == "amber"


# ---------------------------------------------------------------------------
# 5. Multi-turn — Redis session reuse + 10km-south offset (NO live Redis)
# ---------------------------------------------------------------------------


class TestMultiTurnSession:
    """Mock-Redis multi-turn: in-memory fallback / fakeredis-style stub only.

    Does NOT require a live Redis server. backend.db.redis falls back to an
    in-process dict when REDIS_URL is unreachable, and planner_node tests
    below additionally stub get_session with AsyncMock (clearly marked).
    """

    @pytest.mark.asyncio
    async def test_redis_session_reuse_and_10km_south_offset(self):
        from backend.db import redis as redis_mod

        sid = f"test-multiturn-{uuid.uuid4().hex[:8]}"
        # Seed session (in-memory fallback when no live Redis — acceptable per ticket)
        await redis_mod.save_session(
            sid,
            {
                "lat": KOCHI_LAT,
                "lon": KOCHI_LON,
                "zone_id": "z1",
                "place": "Pallithottam",
                "turn_history": [{"query": "fish near Kochi?", "zone_id": "z1"}],
            },
            ttl_seconds=86400,
        )
        cached = await redis_mod.get_session(sid)
        assert cached is not None, "session reuse failed (in-memory fallback expected offline)"
        assert float(cached["lat"]) == pytest.approx(KOCHI_LAT)
        assert float(cached["lon"]) == pytest.approx(KOCHI_LON)

        # 10km-south relative offset reuses cached coords
        new_loc = orchestrator._parse_relative_offset(
            "fish 10km south of last spot",
            float(cached["lat"]),
            float(cached["lon"]),
        )
        assert new_loc is not None, "relative offset '10km south' not parsed"
        new_lat, new_lon = new_loc
        assert new_lat < float(cached["lat"]), "south must decrease latitude"
        assert new_lon == pytest.approx(float(cached["lon"]), abs=0.01)
        moved_km = _haversine_km(float(cached["lat"]), float(cached["lon"]), new_lat, new_lon)
        assert moved_km == pytest.approx(10.0, abs=1.5), f"offset {moved_km:.2f}km != 10km"

    @pytest.mark.asyncio
    async def test_planner_node_reuses_stubbed_session_with_offset(self):
        """planner_node with fakeredis-style stubbed get_session (marked stub)."""
        from backend.agents.graph import planner_node

        stub_session = {"lat": KOCHI_LAT, "lon": KOCHI_LON, "place": "Kochi"}
        # STUB: fakeredis-style — replaces real Redis call, no server needed
        with patch(
            "backend.db.redis.get_session", new=AsyncMock(return_value=dict(stub_session))
        ):
            state = await planner_node(
                {
                    "query": "10km south of here?",
                    "language": "en",
                    "location": None,
                    "session_id": "stub-session",
                }
            )
        assert state["user_location"] is not None
        assert state["user_location"]["lat"] == pytest.approx(KOCHI_LAT - 0.09, abs=0.02)
        assert state["user_location"]["lon"] == pytest.approx(KOCHI_LON, abs=0.02)


# ---------------------------------------------------------------------------
# 6. Latency + map contracts (P95<2.0s, shared candidates, SSE order, nodes)
# ---------------------------------------------------------------------------


class TestLatencyAndContracts:
    def test_full_mock_pipeline_under_2s(self):
        """Full mock pipeline (PFZ+OSF+IMD+geofence+combiner+localize) <2.0s.

        Generous-but-meaningful per ticket: single <2.0s assert, no
        sub-second thresholds (slow hardware safe).
        """
        t0 = time.perf_counter()
        out = _run_mock_pipeline(SimulationScenario.NORMAL, detected_language="ml")
        elapsed = time.perf_counter() - t0
        assert out["best"] is not None
        assert elapsed < 2.0, f"mock pipeline {elapsed:.3f}s exceeds P95<2.0s budget"

    def test_localization_overhead_within_budget(self):
        fish = [
            {
                "zone_id": "z1",
                "place": "Pallithottam",
                "sector": "KERALA",
                "lat": 10.0,
                "lon": 76.0,
                "distance_from_user_km": 12.0,
                "bearing": 232,
                "direction": "SW",
            }
        ]
        sea = [{"zone_id": "z1", "wave_height_m": 0.8}]
        weather = [{"zone_id": "z1", "wind_kt": 8.0}]
        danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}]
        t0 = time.perf_counter()
        for lang in ("ml", "ta", "te", "hi"):
            cb.combine_and_rank(
                fish, sea, weather, danger,
                {"lat": KOCHI_LAT, "lon": KOCHI_LON},
                detected_language=lang,
            )
        assert time.perf_counter() - t0 < 2.0

    def test_shared_candidate_invariant_all_scenarios(self):
        """Same PFZ features fanned to sea/weather/danger, order preserved."""
        for scenario in (
            SimulationScenario.NORMAL,
            SimulationScenario.ROUGH_SEAS,
            SimulationScenario.CYCLONE_WARNING,
            SimulationScenario.BORDER_VIOLATION,
        ):
            batch = mock_fetch_all(
                sector="SEC005",
                center_lat=KOCHI_LAT,
                center_lon=KOCHI_LON,
                count=5,
                scenario=scenario,
            )
            pfz_ids = [f["properties"]["zone_id"] for f in batch["pfz"]["features"]]
            assert len(pfz_ids) == 5
            assert [r["zone_id"] for r in batch["ocean"]["results"]] == pfz_ids
            assert [r["zone_id"] for r in batch["weather"]["results"]] == pfz_ids
            assert [r["zone_id"] for r in batch["geofence"]["results"]] == pfz_ids

    def test_rough_seas_shifts_into_caution_danger(self):
        """ROUGH_SEAS scenario sanity: waves/wind leave the safe band."""
        batch = mock_fetch_all(
            sector="SEC005",
            center_lat=KOCHI_LAT,
            center_lon=KOCHI_LON,
            count=5,
            scenario=SimulationScenario.ROUGH_SEAS,
        )
        ocean = batch["ocean"]["results"]
        weather = batch["weather"]["results"]
        assert all(r["wave_height_m"] >= 2.6 for r in ocean), "ROUGH_SEAS waves 2.6-4.0m"
        assert all(r["status"] in ("caution", "danger") for r in ocean)
        assert all(16.0 <= r["wind_kt"] <= 24.0 for r in weather), "ROUGH_SEAS wind 16-24kt"
        assert all(r["status"] == "caution" for r in weather)
        assert batch["weather"]["cyclones"] == []

    def test_graph_node_names_present(self):
        """Node names fish_finder/sea_checker/weather_agent/danger_agent exist."""
        from backend.agents import graph as g

        for name in ("fish_finder", "sea_checker", "weather_agent", "danger_agent"):
            assert callable(getattr(g, name, None)), f"graph.{name} missing"
        assert callable(getattr(g, "orchestrate_stream_via_graph", None))
        assert callable(getattr(g, "build_orca_graph", None))

    def test_mock_fetcher_envelopes_observable(self):
        """Every mock fetcher returns status+summary+next_actions+artifacts."""
        pts = [{"zone_id": "z1", "place": "A", "lat": KOCHI_LAT, "lon": KOCHI_LON}]
        for env in (
            mock_fetch_incois_pfz("SEC005", KOCHI_LAT, KOCHI_LON, 2),
            mock_fetch_osf_ocean_state(pts, "normal"),
            mock_fetch_imd_marine_weather(pts, "normal"),
            mock_check_geofence_boundaries(pts, "normal"),
            mock_fetch_all("SEC005", KOCHI_LAT, KOCHI_LON, 2),
        ):
            assert {"status", "summary", "next_actions", "artifacts"} <= set(env)
            assert env["status"] == "success"

    @pytest.mark.asyncio
    async def test_sse_event_order_mock_backed(self):
        """SSE strict order status* -> map -> safety -> token+ -> evidence -> done.

        Mock-backed agents (no PostGIS/IMD/Redis servers); generous <2.0s
        is NOT asserted here (slow hardware) — order only. Error events
        ignored for ordering per docs/API.md.
        """
        from backend.agents.graph import orchestrate_stream_via_graph

        batch = mock_fetch_all(
            sector="SEC005",
            center_lat=KOCHI_LAT,
            center_lon=KOCHI_LON,
            count=3,
            scenario=SimulationScenario.NORMAL,
        )
        flat = _flat_fish_from_pfz(batch["pfz"]["features"], KOCHI_LAT, KOCHI_LON)
        ocean = batch["ocean"]["results"]
        weather = batch["weather"]["results"]
        geofence = batch["geofence"]["results"]

        async def _fish(lat, lon, radius_km=80.0, **kw):
            return list(flat)

        async def _sea(points):
            return list(ocean)

        async def _weather(points):
            return list(weather)

        async def _danger(points, **kw):
            return list(geofence)

        with patch(
            "backend.agents.fish_finder.find_fishing_zones", side_effect=_fish
        ), patch(
            "backend.agents.sea_checker.check_sea_conditions", side_effect=_sea
        ), patch(
            "backend.agents.weather_agent.check_weather", side_effect=_weather
        ), patch(
            "backend.agents.danger_agent.check_safety_batch", side_effect=_danger
        ), patch(
            "backend.db.redis.get_session", new=AsyncMock(return_value=None)
        ), patch(
            "backend.db.redis.save_session", new=AsyncMock(return_value=None)
        ):
            events: list[dict] = []
            async for evt in orchestrate_stream_via_graph(
                query="fish near Kochi?",
                language="en",
                location={"lat": KOCHI_LAT, "lon": KOCHI_LON},
                session_id=f"test-sse-{uuid.uuid4().hex[:8]}",
            ):
                events.append(evt)

        types = [e.get("type") for e in events if e.get("type") != "error"]
        assert types, "stream emitted no events"
        # Required stages present
        for required in ("map", "safety", "token", "evidence", "done"):
            assert required in types, f"{required} missing from stream {types!r}"
        # Strict order: statuses first, then map, safety, tokens, evidence, done
        first_map = types.index("map")
        first_safety = types.index("safety")
        first_token = types.index("token")
        first_evidence = types.index("evidence")
        first_done = types.index("done")
        assert first_map < first_safety < first_token < first_evidence < first_done, (
            f"SSE order violated: {types!r}"
        )
        # No status after map (prototype contract: post-map statuses suppressed)
        assert all(
            t != "status" for t in types[first_map + 1 :]
        ), f"status after map in {types!r}"
