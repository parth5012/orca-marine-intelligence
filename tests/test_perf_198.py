"""
Perf hardening regression tests (wayfinder #198).

Offline, fast, no network: pins the fail-fast / single-scan / combiner-once /
batch-write / bbox / telemetry behavior without touching live endpoints.
"""

import copy
from unittest.mock import MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# 1. Shared pooled client + fail-fast single-try (live_fetchers)
# ---------------------------------------------------------------------------

class TestSharedHttpPool:
    def test_shared_client_singleton(self):
        from backend.ingest import live_fetchers as lf

        lf._close_shared_client()
        try:
            assert lf._get_shared_client() is lf._get_shared_client()
        finally:
            lf._close_shared_client()

    def test_default_single_try_no_sleep(self):
        """Default path: exactly 1 pooled GET, no blocking sleep, RuntimeError on fail."""
        from backend.ingest import live_fetchers as lf

        lf._close_shared_client()
        try:
            with patch("httpx.Client.get", side_effect=httpx.ConnectError("down")) as mock_get, \
                 patch("time.sleep") as mock_sleep:
                with pytest.raises(RuntimeError):
                    lf._http_get_with_retry("https://example.com/x", timeout_s=0.1)
                assert mock_get.call_count == 1
                mock_sleep.assert_not_called()
        finally:
            lf._close_shared_client()

    def test_default_success_single_pooled_call(self):
        from backend.ingest import live_fetchers as lf

        lf._close_shared_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        try:
            with patch("httpx.Client.get", return_value=mock_resp) as mock_get:
                resp = lf._http_get_with_retry("https://example.com/x", timeout_s=0.1)
                assert resp is mock_resp
                assert mock_get.call_count == 1
        finally:
            lf._close_shared_client()


# ---------------------------------------------------------------------------
# 2. GeoJSON single-scan staged fallback == sequential per-radius results
# ---------------------------------------------------------------------------

def _synthetic_features():
    # Near (0km), mid (~100km east), far (~150km east) of Kochi.
    return [
        {
            "type": "Feature",
            "properties": {"place": "Near", "sector": "SEC005", "sector_name": "KERALA"},
            "geometry": {"type": "Point", "coordinates": [76.26, 9.93]},
        },
        {
            "type": "Feature",
            "properties": {"place": "Mid", "sector": "SEC005", "sector_name": "KERALA"},
            "geometry": {"type": "Point", "coordinates": [77.2, 9.93]},
        },
        {
            "type": "Feature",
            "properties": {"place": "Far", "sector": "SEC005", "sector_name": "KERALA"},
            "geometry": {"type": "Point", "coordinates": [77.65, 9.93]},
        },
    ]


class TestSingleScanFallback:
    def test_staged_matches_sequential(self):
        from backend.agents.subagents import fish_finder as ff

        feats = _synthetic_features()
        with patch.object(ff, "_load_geojson_features", return_value=copy.deepcopy(feats)):
            radii = [80.0, 120.0, 160.0]
            # Sequential reference (old behavior): first non-empty radius wins.
            expected = []
            for r in radii:
                got = ff._geojson_fallback(lat=9.93, lon=76.26, radius_km=r, limit=5, sector=None)
                if got:
                    expected = got
                    break
            staged = ff._geojson_fallback_staged(
                lat=9.93, lon=76.26, radii_km=radii, limit=5, sector=None
            )
        assert [z["place"] for z in staged] == [z["place"] for z in expected]
        assert staged == expected

    def test_staged_expands_to_mid_radius(self):
        from backend.agents.subagents import fish_finder as ff

        feats = _synthetic_features()[1:]  # only Mid (~100km) + Far
        with patch.object(ff, "_load_geojson_features", return_value=copy.deepcopy(feats)):
            staged = ff._geojson_fallback_staged(
                lat=9.93, lon=76.26, radii_km=[80.0, 120.0, 160.0], limit=5, sector=None
            )
        # First non-empty stage (120km) wins — same as sequential expansion.
        assert [z["place"] for z in staged] == ["Mid"]

    def test_staged_empty(self):
        from backend.agents.subagents import fish_finder as ff

        with patch.object(ff, "_load_geojson_features", return_value=[]):
            assert ff._geojson_fallback_staged(
                lat=9.93, lon=76.26, radii_km=[80.0, 120.0, 160.0], limit=5, sector=None
            ) == []


# ---------------------------------------------------------------------------
# 3. Combiner-once cache (graph)
# ---------------------------------------------------------------------------

class TestCombinerOnce:
    def test_hash_stable_and_sensitive(self):
        from backend.agents import graph as g

        fish = [{"zone_id": "z1", "place": "A", "lat": 10.0, "lon": 76.0}]
        h1 = g._combined_inputs_hash(fish, [], [], [], {"lat": 9.9, "lon": 76.2}, "en", None)
        h2 = g._combined_inputs_hash(copy.deepcopy(fish), [], [], [], {"lat": 9.9, "lon": 76.2}, "en", None)
        assert h1 == h2
        h3 = g._combined_inputs_hash(fish, [{"zone_id": "z1"}], [], [], {"lat": 9.9, "lon": 76.2}, "en", None)
        assert h3 != h1

    def test_store_take_roundtrip_and_miss(self):
        from backend.agents import graph as g

        g._clear_provisional_combined()
        try:
            combined = {"best": {"zone_id": "z1"}, "ranked_zones": [{"zone_id": "z1"}]}
            g._store_provisional_combined("abc123", combined)
            taken = g._take_provisional_combined("abc123")
            assert taken == combined
            assert taken is not combined  # deep copy: decision veto mutates safely
            taken["ranked_zones"].append({"zone_id": "z2"})
            assert g._take_provisional_combined("abc123") == combined
            assert g._take_provisional_combined("other-hash") is None
        finally:
            g._clear_provisional_combined()


# ---------------------------------------------------------------------------
# 4. Per-node P50/P95 telemetry (graph)
# ---------------------------------------------------------------------------

class TestNodeLatencyStats:
    def test_p50_p95_math(self):
        from backend.agents import graph as g

        g._clear_node_timings()
        try:
            for v in (0.1, 0.2, 0.3, 0.4, 0.5):
                g.record_node_timing("fish_finder", v)
            stats = g.get_node_latency_stats()
            assert stats["fish_finder"]["count"] == 5
            assert stats["fish_finder"]["p50_s"] == pytest.approx(0.3)
            assert stats["fish_finder"]["p95_s"] == pytest.approx(0.48)
            assert stats["fish_finder"]["max_s"] == pytest.approx(0.5)
        finally:
            g._clear_node_timings()

    def test_record_never_raises(self):
        from backend.agents import graph as g

        g.record_node_timing("x", float("nan"))  # must not raise
        g._clear_node_timings()


# ---------------------------------------------------------------------------
# 5. Redis single-save turn batch (halves get+set vs 2x append)
# ---------------------------------------------------------------------------

class TestSaveTurnBatch:
    @pytest.mark.asyncio
    async def test_batch_single_get_single_set(self):
        from backend.db import redis as r

        monkey_calls = {"get": 0, "set": 0}
        store: dict = {}

        async def fake_get(key):
            monkey_calls["get"] += 1
            return copy.deepcopy(store.get(key))

        async def fake_set(key, value, ttl_seconds=3600):
            monkey_calls["set"] += 1
            store[key] = copy.deepcopy(value)

        with patch.object(r, "get_json", side_effect=fake_get), \
             patch.object(r, "set_json", side_effect=fake_set):
            await r.save_turn_batch("sess-batch-1", "hello", "hi there")
            assert monkey_calls == {"get": 1, "set": 1}
            sess = store["session:sess-batch-1"]
            roles = [m["role"] for m in sess["turn_history"]]
            assert roles == ["user", "assistant"]
            assert sess["turn_history"][0]["content"] == "hello"
            assert sess["turn_history"][1]["content"] == "hi there"

    @pytest.mark.asyncio
    async def test_two_appends_cost_double(self):
        """Pins the contrast: 2x append_message = 2 gets + 2 sets."""
        from backend.db import redis as r

        monkey_calls = {"get": 0, "set": 0}
        store: dict = {}

        async def fake_get(key):
            monkey_calls["get"] += 1
            return copy.deepcopy(store.get(key))

        async def fake_set(key, value, ttl_seconds=3600):
            monkey_calls["set"] += 1
            store[key] = copy.deepcopy(value)

        with patch.object(r, "get_json", side_effect=fake_get), \
             patch.object(r, "set_json", side_effect=fake_set):
            await r.append_message("sess-batch-2", "user", "hello")
            await r.append_message("sess-batch-2", "assistant", "hi there")
            assert monkey_calls == {"get": 2, "set": 2}


# ---------------------------------------------------------------------------
# 6. Danger bbox gating == exact legacy results
# ---------------------------------------------------------------------------

# GeoJSON MultiPolygon coords: MP=[polygon], polygon=[ring], ring=[pos].
_SQUARE_RING = [[76.0, 9.5], [76.5, 9.5], [76.5, 10.0], [76.0, 10.0], [76.0, 9.5]]
_SQUARE_MP = [[_SQUARE_RING]]  # one multipolygon
_SQUARE_MPS = [_SQUARE_MP]  # multipolygons list, as _load_cached_geojson returns


class TestDangerBboxExactness:
    def test_eez_inside_and_outside_match(self):
        from backend.agents.subagents import danger_agent as da

        da._clear_geojson_cache()
        mps = copy.deepcopy(_SQUARE_MPS)
        try:
            with patch.object(
                da, "_load_cached_geojson", return_value=(mps, [{"multipolygon": mps[0], "properties": {}}])
            ):
                inside, dist_in = da._fallback_check_eez(9.75, 76.25)   # inside square
                outside, dist_out = da._fallback_check_eez(9.0, 76.0)    # far outside
                # Second call hits the cached bbox index — must agree exactly.
                inside2, dist_in2 = da._fallback_check_eez(9.75, 76.25)
                outside2, dist_out2 = da._fallback_check_eez(9.0, 76.0)
            assert inside is True
            assert (inside2, dist_in2) == (inside, dist_in)
            assert outside is False
            assert (outside2, dist_out2) == (outside, dist_out)
            assert dist_out is not None and dist_out > 50.0
        finally:
            da._clear_geojson_cache()

    def test_mpa_gate_matches_direct_raycast(self):
        from backend.agents.subagents import danger_agent as da

        da._clear_geojson_cache()
        mps = copy.deepcopy(_SQUARE_MPS)
        feats = [{"multipolygon": mps[0], "properties": {"name": "TestMPA"}}]
        try:
            with patch.object(da, "_load_cached_geojson", return_value=(mps, copy.deepcopy(feats))):
                hit = da._fallback_check_mpa(9.75, 76.25)
                miss = da._fallback_check_mpa(9.0, 76.0)
                hit2 = da._fallback_check_mpa(9.75, 76.25)  # cached-bbox path
            assert hit == (True, "TestMPA")
            assert hit2 == hit
            assert miss == (False, None)
        finally:
            da._clear_geojson_cache()
