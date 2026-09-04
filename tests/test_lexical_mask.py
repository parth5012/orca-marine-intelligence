"""
Marine Lexical Masking & Vernacular Advisory Grounding — Verification Suite.

Ticket: wayfinder #28 (M-A & M-E).
Refs: docs/research/02-provider-agnostic-translation-layer.md §4,
      docs/research/03-coastal-marine-dictionary-spec.md §3-§5.

Offline only (no external calls). Masking must be cheap regex (P95<2.0s).
Does NOT touch graph.py / mock_fetchers / planner_schema.
"""

import re
import time

import pytest

from backend.agents import combiner as cb
from backend.agents import lexical_mask as lm


def _sample_fish():
    return [
        {
            "zone_id": "z1", "place": "Pallithottam", "sector": "KERALA",
            "lat": 10.0, "lon": 76.0, "distance_from_user_km": 12.0,
            "bearing": 232, "direction": "SW",
        }
    ]


def _sample_inputs():
    fish = _sample_fish()
    sea = [{"zone_id": "z1", "wave_height_m": 0.8}]
    weather = [{"zone_id": "z1", "wind_kt": 8.0}]
    danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}]
    return fish, sea, weather, danger


def _sample_metrics(**over):
    m = {
        "place": "Pallithottam", "lat": 9.9312, "lon": 76.2673,
        "distance_km": 14.0, "bearing_deg": 232, "direction": "SW",
        "wave_height_m": 0.8, "wind_kts": 8,
        "overall_safety": "SAFE", "all_unsafe": False,
        "citation": "INCOIS TextData KERALA Pallithottam 04-Sep-2026",
    }
    m.update(over)
    return m


# ---------------------------------------------------------------------------
# MarineGlossaryMasker — mandated mask patterns
# ---------------------------------------------------------------------------


class TestMarineGlossaryMasker:
    def test_bearing_mask_pattern(self):
        masker = lm.MarineGlossaryMasker()
        masked, table = masker.mask("Bearing 232 deg near Kochi")
        assert "__MBEARING_0__" in masked
        assert "232" not in masked  # number hidden pre-translation
        assert table["__MBEARING_0__"] == "Bearing 232 deg"

    def test_bearing_degree_symbol_variant(self):
        masker = lm.MarineGlossaryMasker()
        masked, table = masker.mask("Bearing 232° SW")
        assert "__MBEARING_0__" in masked
        assert masker.unmask(masked, table) == "Bearing 232° SW"

    def test_knots_mask_pattern(self):
        masker = lm.MarineGlossaryMasker()
        masked, table = masker.mask("wind 8 knots gusting 12 knots")
        assert "__MKNOTS_0__" in masked and "__MKNOTS_1__" in masked
        assert table["__MKNOTS_0__"] == "8 knots"
        assert masker.unmask(masked, table) == "wind 8 knots gusting 12 knots"

    def test_dist_km_mask_pattern(self):
        masker = lm.MarineGlossaryMasker()
        masked, table = masker.mask("zone 14 km away")
        assert "__MDIST_0__" in masked
        assert table["__MDIST_0__"] == "14 km"
        assert masker.unmask(masked, table) == "zone 14 km away"

    def test_roundtrip_preserves_everything(self):
        src = "Bearing 232 deg, wind 8 knots, 14 km, wave 1.2 m, PFZ at 9.9312, 76.2673"
        masker = lm.MarineGlossaryMasker()
        masked, table = masker.mask(src)
        assert masker.unmask(masked, table) == src

    def test_placeholders_are_token_safe_no_spaces(self):
        """SSE _chunk_text splits on spaces — placeholders must stay whole."""
        masker = lm.MarineGlossaryMasker()
        masked, _ = masker.mask("Bearing 232 deg and 8 knots over 14 km")
        for token in re.findall(r"__M[A-Z]+_\d+__", masked):
            assert " " not in token
        # every placeholder survives word-splitting intact
        words = masked.split(" ")
        for token in re.findall(r"__M[A-Z]+_\d+__", masked):
            assert token in words

    def test_mask_envelope_shape(self):
        env = lm.MarineGlossaryMasker().mask_envelope("Bearing 232 deg, 8 knots")
        assert env["status"] == "success"
        assert "summary" in env and "next_actions" in env and "artifacts" in env
        assert "__MBEARING_0__" in env["masked"]

    def test_masking_is_cheap(self):
        """200 mask+unmask ops must complete well under the 2.0s P95 budget."""
        masker = lm.MarineGlossaryMasker()
        src = "Bearing 232 deg, wind 8 knots, 14 km, wave 1.2 m at 9.9312, 76.2673"
        t0 = time.perf_counter()
        for _ in range(200):
            masked, table = masker.mask(src)
            masker.unmask(masked, table)
        assert time.perf_counter() - t0 < 2.0


# ---------------------------------------------------------------------------
# Mask → translate → unmask: 0 corrupted coordinates / broken compass degrees
# ---------------------------------------------------------------------------


def _mock_aggressive_mt(masked_en: str) -> str:
    """Simulate a generic MT engine that corrupts nautical terms.

    Operates on MASKED text (placeholders pass through verbatim) and adds a
    Malayalam wrapper — mirrors Direct-LLM/Sarvam/Bhashini behaviour when
    placeholders are respected.
    """
    corrupted = masked_en.replace("Bearing", "load-bearing").replace("knots", "rope-knots")
    return "മലയാളം പരിഭാഷ: " + corrupted


def _mock_naive_mt(raw_en: str) -> str:
    """Same engine WITHOUT masking — demonstrates the corruption we avoid."""
    return (
        raw_en.replace("Bearing", "load-bearing")
        .replace("knots", "rope-knots")
        .replace("°", "o")
    )


class TestMaskTranslateUnmask:
    def test_masked_pipeline_zero_corrupted_numbers(self):
        """REQUIRED: translated replies contain 0 corrupted coords/degrees."""
        src = (
            "Recommended: Pallithottam (14 km away, Bearing 232°, "
            "wave 1.2 m, wind 8 knots) at 9.9312, 76.2673. PFZ citation INCOIS."
        )
        expected = ["232", "8", "14", "1.2", "9.9312", "76.2673"]
        final = lm.translate_with_masking(src, _mock_aggressive_mt)
        missing = lm.verify_numbers_preserved(expected, final)
        assert missing == [], f"corrupted numbers: {missing} in {final!r}"
        assert "__M" not in final  # no placeholder leaked
        assert "മലയാളം" in final  # target language wrapper present

    def test_masked_pipeline_preserves_degree_symbol(self):
        src = "Bearing 232° SW of Kochi, 14 km out"
        final = lm.translate_with_masking(src, _mock_aggressive_mt)
        assert "232°" in final
        assert "14 km" in final

    def test_naive_unmasked_translation_corrupts(self):
        """Contrast: without masking the same engine breaks nautical terms."""
        src = "Bearing 232° with 8 knots"
        naive = _mock_naive_mt(src)
        assert "load-bearing" in naive and "rope-knots" in naive
        assert "232°" not in naive  # degree symbol destroyed
        # ...while the masked pipeline keeps them intact
        final = lm.translate_with_masking(src, _mock_aggressive_mt)
        assert "232°" in final and "8 knots" in final

    def test_coordinates_never_split(self):
        src = "Target 9.9312, 76.2673 bearing 45 deg"
        final = lm.translate_with_masking(src, _mock_aggressive_mt)
        assert "9.9312, 76.2673" in final


# ---------------------------------------------------------------------------
# Vernacular grounding — pure native-script offline advisories
# ---------------------------------------------------------------------------


_VETO_PHRASE = {"ml": "പോകരുത്", "ta": "வேண்டாம்", "te": "వెళ్లవద్దు", "hi": "न जाएँ"}
_BEARING_WORD = {"ml": "ബെയറിംഗ്", "ta": "திசைக்கோணம்", "te": "బేరింగ్", "hi": "दिशा कोण"}


class TestVernacularGrounding:
    @pytest.mark.parametrize("lang", ["ml", "ta", "te", "hi"])
    def test_canned_advisory_pure_native_script_offline(self, lang):
        reply = lm.render_grounded_advisory(_sample_metrics(), lang)
        assert lm.contains_native_script(reply, lang), f"no native script in {reply!r}"
        assert not lm.has_regional_digits(reply), f"regional digits in {reply!r}"

    @pytest.mark.parametrize("lang", ["ml", "ta", "te", "hi"])
    def test_canned_advisory_preserves_all_numbers(self, lang):
        reply = lm.render_grounded_advisory(_sample_metrics(), lang)
        for num in ["14", "232", "0.8", "9.9312", "76.2673"]:
            assert num in reply, f"{num!r} missing in {lang}: {reply!r}"
        assert "°" in reply and "km" in reply and " m" in reply

    @pytest.mark.parametrize("lang", ["ml", "ta", "te", "hi"])
    def test_canned_advisory_grounding_tags(self, lang):
        reply = lm.render_grounded_advisory(_sample_metrics(), lang)
        assert lm.SAFETY_TAGS[lang]["SAFE"] in reply
        assert _BEARING_WORD[lang] in reply
        assert lm.CLOSING_SENTENCES[lang]["SAFE"] in reply

    @pytest.mark.parametrize("lang", ["ml", "ta", "te", "hi"])
    def test_all_unsafe_veto_localized_not_overridden(self, lang):
        """Code trumps LLM: all_unsafe forces DANGER closing in every lang."""
        reply = lm.render_grounded_advisory(
            _sample_metrics(all_unsafe=True, overall_safety="SAFE"), lang
        )
        assert lm.SAFETY_TAGS[lang]["DANGER"] in reply
        assert lm.CLOSING_SENTENCES[lang]["DANGER"] in reply
        assert _VETO_PHRASE[lang] in reply

    def test_unknown_lang_falls_back_to_english(self):
        reply = lm.render_grounded_advisory(_sample_metrics(), "xx")
        assert "Bearing 232°" in reply
        assert not lm.contains_native_script(reply, "ml")

    def test_localize_envelope_shape(self):
        env = lm.localize_advisory_envelope(_sample_metrics(), "ta")
        assert env["status"] == "success"
        assert {"summary", "next_actions", "artifacts", "reply", "detected_language"} <= set(env)
        assert env["detected_language"] == "ta"
        assert lm.contains_native_script(env["reply"], "ta")


# ---------------------------------------------------------------------------
# Combiner hook — detected_language wiring (graph.py untouched)
# ---------------------------------------------------------------------------


class TestCombinerMultilingualHook:
    @pytest.mark.parametrize("lang", ["ml", "ta", "te", "hi"])
    def test_combine_and_rank_same_language_response(self, lang):
        fish, sea, weather, danger = _sample_inputs()
        res = cb.combine_and_rank(
            fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26},
            detected_language=lang,
        )
        assert res["detected_language"] == lang
        assert lm.contains_native_script(res["explanation"], lang)
        assert not lm.has_regional_digits(res["explanation"])
        for num in ["12", "232", "0.8"]:
            assert num in res["explanation"], f"{num} lost in {lang}"
        # English audit trail preserved alongside
        assert "Recommended:" in res["explanation_en"]
        assert res["localized_reply"] == res["explanation"]
        # ranking itself untouched
        assert res["best"]["place"] == "Pallithottam"
        assert res["best"]["score"] == pytest.approx(1.0, abs=0.0001)

    def test_combine_and_rank_english_unchanged(self):
        """Backward compat: default path keeps English explanation."""
        fish, sea, weather, danger = _sample_inputs()
        res = cb.combine_and_rank(
            fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26}
        )
        assert res["detected_language"] == "en"
        assert res["explanation"].startswith("Recommended:")
        assert "explanation_en" not in res
        assert res["localized_reply"] == res["explanation"]

    def test_combine_all_unsafe_ml_keeps_veto(self):
        fish = [
            {"zone_id": "z1", "place": "Rough1", "sector": "K", "lat": 10.0, "lon": 76.0,
             "distance_from_user_km": 8.0},
        ]
        sea = [{"zone_id": "z1", "wave_height_m": 3.0}]
        weather = [{"zone_id": "z1", "wind_kt": 30.0}]
        danger = [{"zone_id": "z1", "inside_eez": True, "inside_mpa": False}]
        res = cb.combine_and_rank(
            fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26},
            detected_language="ml",
        )
        assert res["all_unsafe"] is True
        assert "പോകരുത്" in res["explanation"]  # localized veto
        assert "DO NOT SAIL" in res["explanation_en"] or "Do NOT sail" in res["explanation_en"]

    def test_combine_empty_ml_same_language(self):
        res = cb.combine_and_rank([], [], [], [], {"lat": 9.93, "lon": 76.26},
                                   detected_language="ml")
        assert res["best"] is None
        assert lm.contains_native_script(res["explanation"], "ml")
        assert "No fishing zones" in res["explanation_en"]

    def test_combine_invalid_lang_falls_back_en(self):
        fish, sea, weather, danger = _sample_inputs()
        res = cb.combine_and_rank(
            fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26},
            detected_language="xx",
        )
        assert res["detected_language"] == "en"
        assert res["explanation"].startswith("Recommended:")

    def test_build_localized_advisory_envelope(self):
        fish, sea, weather, danger = _sample_inputs()
        res = cb.combine_and_rank(
            fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26}
        )
        env = cb.build_localized_advisory(
            res["best"], detected_language="te",
            citation=res["citation"], all_unsafe=res["all_unsafe"],
        )
        assert env["status"] == "success"
        assert {"summary", "next_actions", "artifacts", "reply"} <= set(env)
        assert env["detected_language"] == "te"
        assert lm.contains_native_script(env["reply"], "te")
        assert "232" in env["reply"] and "0.8" in env["reply"]
        # alias parity
        env2 = cb.synthesize_multilingual_advisory(res["best"], detected_language="hi")
        assert env2["detected_language"] == "hi"

    def test_localization_overhead_within_budget(self):
        """40 full localized rankings must stay well under P95<2.0s."""
        fish, sea, weather, danger = _sample_inputs()
        t0 = time.perf_counter()
        for lang in ["ml", "ta", "te", "hi"] * 10:
            cb.combine_and_rank(
                fish, sea, weather, danger, {"lat": 9.93, "lon": 76.26},
                detected_language=lang,
            )
        assert time.perf_counter() - t0 < 2.0


# ---------------------------------------------------------------------------
# Review fixes (issue #28): explicit-SAFE veto, mask gaps, digits, leak guard
# ---------------------------------------------------------------------------


class TestReviewFixes:
    @pytest.mark.parametrize("over", [
        {"inside_mpa": True, "inside_eez": True},
        {"inside_mpa": False, "inside_eez": False},
        {"wave_height_m": 5.0},
        {"wind_kts": 30},
    ])
    def test_explicit_safe_veto_forces_danger(self, over):
        reply = lm.render_grounded_advisory(
            _sample_metrics(overall_safety="SAFE", all_unsafe=False, **over), "en"
        )
        assert lm.SAFETY_TAGS["en"]["DANGER"] in reply
        assert lm.CLOSING_SENTENCES["en"]["DANGER"] in reply

    def test_bearing_uppercase_masked(self):
        masked, table = lm.mask_text("BEARING 232 deg near Kochi")
        assert "__MBEARING_0__" in masked
        assert "232" not in masked
        assert table["__MBEARING_0__"] == "BEARING 232 deg"

    @pytest.mark.parametrize("src", ["232 deg SW", "45 degrees"])
    def test_standalone_deg_degrees_masked(self, src):
        masked, table = lm.mask_text(src)
        assert "__MDEG_0__" in masked
        assert lm.unmask_text(masked, table) == src

    def test_kms_plural_masked(self):
        masked, table = lm.mask_text("zone 14 kms away")
        assert "__MDIST_0__" in masked
        assert table["__MDIST_0__"] == "14 kms"
        assert lm.unmask_text(masked, table) == "zone 14 kms away"

    def test_kannada_vowels_not_digits_but_digits_flagged(self):
        assert not lm.has_regional_digits(chr(0x0C86))
        assert not lm.has_regional_digits(chr(0x0C8F))
        assert lm.has_regional_digits(chr(0x0CE6))
        assert lm.has_regional_digits(chr(0x0CEF))

    def test_placeholder_leak_guard_falls_back(self):
        final = lm.translate_with_masking(
            "hello world", lambda s: s + " __MFAKE_99__"
        )
        assert "__M" not in final
        assert final == "hello world"
        env = lm.localize_advisory_envelope(
            _sample_metrics(), "ml", translator_fn=lambda s: "__MFAKE_99__"
        )
        assert "__M" not in env["reply"]
