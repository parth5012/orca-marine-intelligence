"""
Tests for T1: Extend MarineEvalExample with frozen multilingual fields.
Ticket: #177
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from backend.evals.dataset import (
    MarineEvalExample,
    export_dataset_to_json,
    load_golden_v1,
    load_marine_eval_dataset,
)


def test_marine_eval_example_multilingual_defaults():
    e = MarineEvalExample(
        example_id="X",
        landing_center="Kochi",
        inputs={},
        reference={},
    )
    assert e.language == "en"
    assert e.query_vernacular == ""
    assert e.frozen_reply == ""
    assert e.invariants == {
        "safety_tier_same": True,
        "arabic_numerals_only": True,
        "do_not_sail_preserved": True,
    }


def test_load_marine_eval_dataset_returns_english_defaults():
    dataset = load_marine_eval_dataset()
    assert len(dataset) == 14
    for ex in dataset:
        assert ex.language == "en"
        assert ex.frozen_reply == ""
        assert "safety_tier_same" in ex.invariants


def test_export_dataset_to_json_includes_new_keys(tmp_path: Path):
    ex = MarineEvalExample(
        example_id="TEST_ML_01",
        landing_center="Kochi",
        inputs={"latitude": 9.93, "longitude": 76.26},
        reference={"expected_safety_tier": "safe"},
        language="ml",
        query_vernacular="കൊച്ചിയിൽ കാലാവസ്ഥ എങ്ങനെയുണ്ട്?",
        frozen_reply="കടൽ ശാന്തമാണ്. കാറ്റിന്റെ വേഗത കുറവാണ്.",
        invariants={"safety_tier_same": True, "arabic_numerals_only": True, "do_not_sail_preserved": True},
    )
    out_file = tmp_path / "export_test.json"
    count = export_dataset_to_json([ex], str(out_file))
    assert count == 1
    assert out_file.exists()

    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 1
    record = data[0]
    assert record["language"] == "ml"
    assert record["query_vernacular"] == "കൊച്ചിയിൽ കാലാവസ്ഥ എങ്ങനെയുണ്ട്?"
    assert record["frozen_reply"] == "കടൽ ശാന്തമാണ്. കാറ്റിന്റെ വേഗത കുറവാണ്."
    assert record["invariants"]["safety_tier_same"] is True


def test_load_golden_v1_fallback_when_missing():
    # If file doesn't exist, must log warning and fall back to load_marine_eval_dataset()
    with patch("backend.evals.dataset.Path.exists", return_value=False):
        examples = load_golden_v1("non_existent_golden.json")
        assert len(examples) == 14
        assert examples[0].language == "en"


def test_load_golden_v1_loads_from_json(tmp_path: Path):
    golden_file = tmp_path / "golden_v1.json"
    sample_data = [
        {
            "example_id": "GOLDEN_01",
            "landing_center": "Kochi",
            "inputs": {"latitude": 9.93, "longitude": 76.26},
            "reference": {"expected_safety_tier": "safe"},
            "metadata": {"category": "pfz"},
            "language": "hi",
            "query_vernacular": "क्या मैं कोच्चि के पास मछली पकड़ने जा सकता हूँ?",
            "frozen_reply": "हाँ, समुद्र शांत है।",
            "invariants": {"safety_tier_same": True, "arabic_numerals_only": True, "do_not_sail_preserved": True},
        }
    ]
    with open(golden_file, "w", encoding="utf-8") as f:
        json.dump(sample_data, f)

    loaded = load_golden_v1(str(golden_file))
    assert len(loaded) == 1
    assert loaded[0].example_id == "GOLDEN_01"
    assert loaded[0].language == "hi"
    assert loaded[0].query_vernacular == "क्या मैं कोच्चि के पास मछली पकड़ने जा सकता हूँ?"
    assert loaded[0].frozen_reply == "हाँ, समुद्र शांत है।"


def test_load_golden_v1_fallback_when_corrupted(tmp_path: Path):
    corrupt_file = tmp_path / "corrupted_golden.json"
    corrupt_file.write_text("{ invalid json ...", encoding="utf-8")
    examples = load_golden_v1(str(corrupt_file))
    assert len(examples) == 14
    assert examples[0].language == "en"
