"""
Tests for T3 M-B: freeze_golden.py one-time Bhashini freeze to golden_v1.json.
Ticket: #179
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from scripts.freeze_golden import (
    TARGET_LANGS,
    freeze_dataset,
    verify_golden_file,
)
from backend.core.bhashini import TranslationResult


@pytest.fixture
def mock_translate_success():
    async def _mock_trans(text: str, target_lang: str, redis_client=None):
        return TranslationResult(
            text=f"[{target_lang}] {text}",
            source_lang="en",
            target_lang=target_lang,
            translated=True,
            cached=False,
        )
    return _mock_trans


@pytest.fixture
def mock_translate_failure():
    async def _mock_trans(text: str, target_lang: str, redis_client=None):
        # On failure, Bhashini returns translated=False with original text
        return TranslationResult(
            text=text,
            source_lang="en",
            target_lang=target_lang,
            translated=False,
            cached=False,
        )
    return _mock_trans


def test_target_languages_count():
    assert len(TARGET_LANGS) == 22
    assert "ml" in TARGET_LANGS
    assert "ta" in TARGET_LANGS
    assert "hi" in TARGET_LANGS


@pytest.mark.asyncio
async def test_freeze_dataset_creates_66_records(tmp_path: Path, mock_translate_success):
    out_file = tmp_path / "golden_v1.json"
    with patch("scripts.freeze_golden.translate_from_english", side_effect=mock_translate_success):
        count = await freeze_dataset(output_path=str(out_file), force_retranslate=True)

    assert count == 66
    assert out_file.exists()

    with open(out_file, "r", encoding="utf-8") as f:
        records = json.load(f)

    assert len(records) == 66
    lang_counts = {}
    for r in records:
        assert "example_id" in r
        assert "language" in r
        assert "query_vernacular" in r
        assert "frozen_reply" in r
        assert "invariants" in r
        assert "needs_human_fix" in r
        assert "inputs" in r
        assert "reference" in r
        assert "expected_safety_tier" in r["reference"]
        assert "mandate_do_not_sail" in r["reference"]
        lang_counts[r["language"]] = lang_counts.get(r["language"], 0) + 1

    assert len(lang_counts) == 22
    for lang, c in lang_counts.items():
        assert c == 3, f"Expected 3 records for {lang}, got {c}"


@pytest.mark.asyncio
async def test_freeze_dataset_fallback_on_translation_failure(tmp_path: Path, mock_translate_failure):
    out_file = tmp_path / "golden_v1.json"
    with patch("scripts.freeze_golden.translate_from_english", side_effect=mock_translate_failure):
        count = await freeze_dataset(output_path=str(out_file), force_retranslate=True, use_templates=False)

    assert count == 66
    with open(out_file, "r", encoding="utf-8") as f:
        records = json.load(f)

    for r in records:
        assert r["needs_human_fix"] is True


@pytest.mark.asyncio
async def test_freeze_dataset_skips_human_fixed_records(tmp_path: Path):
    out_file = tmp_path / "golden_v1.json"
    # Seed file with a human-fixed record
    fixed_record = {
        "example_id": "GOLDEN_V1_ML_01",
        "language": "ml",
        "query_vernacular": "കൊച്ചിയിൽ മീൻ പിടിക്കാമോ?",
        "frozen_reply": "കൊച്ചിയിൽ മീൻപിടുത്തം സുരക്ഷിതമാണ്.",
        "invariants": {"safety_tier_same": True, "arabic_numerals_only": True, "do_not_sail_preserved": True},
        "needs_human_fix": False,
        "inputs": {"lat": 9.93, "lon": 76.26, "latitude": 9.93, "longitude": 76.26},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False},
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump([fixed_record], f)

    mock_translate = AsyncMock(return_value=TranslationResult(
        text="OVERWRITTEN",
        source_lang="en",
        target_lang="ml",
        translated=True,
    ))

    with patch("scripts.freeze_golden.translate_from_english", mock_translate):
        await freeze_dataset(output_path=str(out_file), force_retranslate=False)

    with open(out_file, "r", encoding="utf-8") as f:
        records = json.load(f)

    ml_01 = next(r for r in records if r["example_id"] == "GOLDEN_V1_ML_01")
    assert ml_01["frozen_reply"] == "കൊച്ചിയിൽ മീൻപിടുത്തം സുരക്ഷിതമാണ്."
    assert ml_01["needs_human_fix"] is False


def test_verify_golden_file(tmp_path: Path):
    test_file = tmp_path / "test_golden.json"
    records = []
    for lang in TARGET_LANGS:
        for q_idx in range(1, 4):
            records.append({
                "example_id": f"GOLDEN_V1_{lang.upper()}_{q_idx:02d}",
                "language": lang,
                "landing_center": "Kochi",
                "query_vernacular": f"Query {q_idx}",
                "frozen_reply": f"Reply {q_idx}",
                "invariants": {},
                "needs_human_fix": False,
                "inputs": {"lat": 9.93, "lon": 76.26},
                "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False},
            })
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(records, f)

    valid, err = verify_golden_file(str(test_file))
    assert valid is True
    assert err == ""


def test_verify_golden_file_failures(tmp_path: Path):
    # 1. Missing file
    valid, err = verify_golden_file(str(tmp_path / "missing.json"))
    assert valid is False
    assert "does not exist" in err

    # 2. Corrupted JSON
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{bad json", encoding="utf-8")
    valid, err = verify_golden_file(str(corrupt))
    assert valid is False

    # 3. Wrong record count
    wrong_count = tmp_path / "wrong_count.json"
    wrong_count.write_text("[]", encoding="utf-8")
    valid, err = verify_golden_file(str(wrong_count))
    assert valid is False
    assert "Expected 66 records" in err
