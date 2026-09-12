"""T2 tide helper tests — get_tide never raises, distance ceiling, combiner passthrough."""

from backend.ingest import tides as tides_mod


class TestGetTideFallback:
    def test_missing_dir_returns_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tides_mod, "TIDE_DIR", tmp_path / "nope")
        tides_mod.clear_cache()
        out = tides_mod.get_tide(9.93, 76.26)
        assert out["tide_range_m"] is None
        assert out["tidal_state"] == "unknown"

    def test_invalid_coords_never_raise(self):
        tides_mod.clear_cache()
        assert tides_mod.get_tide(None, None)["tidal_state"] == "unknown"
        assert tides_mod.get_tide(999.0, 999.0)["tidal_state"] == "unknown"

    def test_far_station_rejected_by_distance_ceiling(self, tmp_path, monkeypatch):
        p = tmp_path / "t.csv"
        p.write_text(
            "latitude,longitude,tide_range_m,tidal_state,next_high_tide_utc,next_low_tide_utc\n"
            "21.6,69.6,3.0,rising,2026-01-01T08:00:00Z,2026-01-01T14:00:00Z\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(tides_mod, "TIDE_DIR", tmp_path)
        tides_mod.clear_cache()
        # Tamil Nadu query ~1500km from Gujarat station -> unknown
        out = tides_mod.get_tide(13.08, 80.27)
        assert out["tidal_state"] == "unknown"
        assert out["tide_range_m"] is None

    def test_nearby_station_matches(self, tmp_path, monkeypatch):
        p = tmp_path / "t.csv"
        p.write_text(
            "latitude,longitude,tide_range_m,tidal_state,next_high_tide_utc,next_low_tide_utc\n"
            "9.93,76.26,1.2,rising,2026-01-01T08:00:00Z,2026-01-01T14:00:00Z\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(tides_mod, "TIDE_DIR", tmp_path)
        tides_mod.clear_cache()
        out = tides_mod.get_tide(9.93, 76.26)
        assert out["tide_range_m"] == 1.2
        assert out["tidal_state"] == "rising"
        assert out["next_high_tide_utc"] == "2026-01-01T08:00:00Z"

    def test_scalar_synonyms_do_not_fake_zero_range(self):
        rec = {"latitude": 9.9, "longitude": 76.2, "height_m": 1.5, "height": 1.5}
        out = tides_mod._record_to_tide(rec)
        assert out["tide_range_m"] is None


class TestCombinerTide:
    def test_combiner_passes_all_four_fields_and_suffix(self):
        from backend.agents import combiner as cb

        fish = [{"zone_id": "z1", "place": "A", "lat": 9.93, "lon": 76.26,
                 "distance_from_user_km": 5.0, "bearing": 90, "direction": "E",
                 "depth_range": "20-30", "sector": "KERALA"}]
        sea = [{"zone_id": "z1", "wave_height_m": 0.8, "current_kt": 1.0,
                "wave_status": "safe", "current_status": "safe", "status": "safe"}]
        weather = [{"zone_id": "z1", "wind_kt": 10.0, "wind_status": "safe", "status": "safe",
                    "tide_range_m": 1.2, "tidal_state": "rising",
                    "next_high_tide_utc": "2026-01-01T08:00:00Z",
                    "next_low_tide_utc": "2026-01-01T14:00:00Z"}]
        danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}]
        out = cb.combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
        assert out["best"]["tide_range_m"] == 1.2
        assert out["best"]["next_high_tide_utc"] == "2026-01-01T08:00:00Z"
        assert "Tide: rising, range 1.2m." in out["explanation"]

    def test_unknown_state_uses_tidal_range_wording(self):
        from backend.agents import combiner as cb

        fish = [{"zone_id": "z1", "place": "A", "lat": 9.93, "lon": 76.26,
                 "distance_from_user_km": 5.0, "bearing": 90, "direction": "E",
                 "depth_range": "20-30", "sector": "KERALA"}]
        sea = [{"zone_id": "z1", "wave_height_m": 0.8, "current_kt": 1.0,
                "wave_status": "safe", "current_status": "safe", "status": "safe"}]
        weather = [{"zone_id": "z1", "wind_kt": 10.0, "wind_status": "safe", "status": "safe",
                    "tide_range_m": 1.2, "tidal_state": "unknown"}]
        danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}]
        out = cb.combine_and_rank(fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26})
        assert "Tidal range 1.2m." in out["explanation"]
