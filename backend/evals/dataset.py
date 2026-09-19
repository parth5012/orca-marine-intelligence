"""
LangSmith Marine Benchmark Dataset Generator & Loader.

Owner: M-A (Agents & Orchestration)
Ticket: #56 (Wayfinder Map: #53)

Cyrates structured evaluation benchmarks across the 20 coastal landing centers,
cyclone storm tracks, Marine Protected Areas (MPA), and EEZ boundary zones.
Supports LangSmith dataset creation and offline JSON serialization.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MarineEvalExample:
    """Represents a single benchmark test case for LangSmith evaluation."""

    example_id: str
    landing_center: str
    inputs: dict[str, Any]
    reference: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SEED_LANDING_CENTERS = [
    {"name": "Kochi", "lat": 9.93, "lon": 76.26, "state": "Kerala", "base_wave": 1.45, "base_wind": 11.5},
    {"name": "Chennai", "lat": 13.08, "lon": 80.27, "state": "Tamil Nadu", "base_wave": 1.20, "base_wind": 10.0},
    {"name": "Porbandar", "lat": 21.64, "lon": 69.60, "state": "Gujarat", "base_wave": 1.80, "base_wind": 14.0},
    {"name": "Kanyakumari", "lat": 8.08, "lon": 77.55, "state": "Tamil Nadu", "base_wave": 1.60, "base_wind": 13.5},
    {"name": "Visakhapatnam", "lat": 17.68, "lon": 83.21, "state": "Andhra Pradesh", "base_wave": 1.30, "base_wind": 9.5},
    {"name": "Paradip", "lat": 20.31, "lon": 86.61, "state": "Odisha", "base_wave": 1.50, "base_wind": 12.0},
    {"name": "Mumbai", "lat": 18.92, "lon": 72.83, "state": "Maharashtra", "base_wave": 1.10, "base_wind": 8.5},
    {"name": "Mangalore", "lat": 12.91, "lon": 74.85, "state": "Karnataka", "base_wave": 1.35, "base_wind": 10.5},
    {"name": "Tuticorin", "lat": 8.76, "lon": 78.13, "state": "Tamil Nadu", "base_wave": 1.25, "base_wind": 11.0},
    {"name": "Veraval", "lat": 20.90, "lon": 70.36, "state": "Gujarat", "base_wave": 1.70, "base_wind": 13.0},
]

_HIGH_RISK_EDGE_CASES = [
    {
        "id": "EDGE_MPA_01",
        "name": "Gulf of Mannar Marine National Park",
        "lat": 9.20,
        "lon": 79.10,
        "expected_wave": 1.20,
        "expected_wind": 10.5,
        "cyclone_alert": False,
        "safety_tier": "danger",
        "is_mpa": True,
        "mandate_do_not_sail": True,
        "category": "mpa_violation",
        "notes": "Inside restricted Marine Protected Area. Severe fine risk.",
    },
    {
        "id": "EDGE_CYCLONE_01",
        "name": "Storm Track Ditwah Vicinity",
        "lat": 9.45,
        "lon": 81.40,
        "expected_wave": 3.80,
        "expected_wind": 42.0,
        "cyclone_alert": True,
        "safety_tier": "danger",
        "is_mpa": False,
        "mandate_do_not_sail": True,
        "category": "cyclone_proximity",
        "notes": "Within 250km of active cyclone Ditwah central vortex.",
    },
    {
        "id": "EDGE_IMBL_BUFFER_01",
        "name": "Palk Bay International Boundary Buffer",
        "lat": 9.25,
        "lon": 79.50,
        "expected_wave": 1.10,
        "expected_wind": 9.0,
        "cyclone_alert": False,
        "safety_tier": "caution",
        "is_mpa": False,
        "mandate_do_not_sail": False,
        "category": "boundary_buffer",
        "notes": "Within 1.5km of international boundary line. Caution required.",
    },
    {
        "id": "EDGE_HIGH_WAVE_01",
        "name": "Arabian Sea Monsoon Swell Surge",
        "lat": 15.10,
        "lon": 72.80,
        "expected_wave": 3.20,
        "expected_wind": 22.0,
        "cyclone_alert": False,
        "safety_tier": "danger",
        "is_mpa": False,
        "mandate_do_not_sail": True,
        "category": "extreme_waves",
        "notes": "Wave height 3.2m exceeds 2.5m danger threshold.",
    },
]


def _find_parquet_features_file() -> Path | None:
    base = Path(__file__).resolve().parents[3]
    candidates = [
        base / "data" / "marine_data_package" / "marine-data" / "unified" / "marine_features" / "coastal_point_features.parquet",
        base / "data" / "coastal_point_features.parquet",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_marine_eval_dataset(limit: int | None = None) -> list[MarineEvalExample]:
    """
    Builds a benchmark evaluation dataset of MarineEvalExample objects.
    Combines verified coastal landing features with high-risk boundary edge cases.
    """
    examples: list[MarineEvalExample] = []

    # 1. Edge cases
    for ec in _HIGH_RISK_EDGE_CASES:
        ex = MarineEvalExample(
            example_id=ec["id"],
            landing_center=ec["name"],
            inputs={
                "latitude": ec["lat"],
                "longitude": ec["lon"],
                "query": f"Can I fish safely near {ec['name']}?",
                "expected_wave": ec["expected_wave"],
                "expected_wind": ec["expected_wind"],
            },
            reference={
                "expected_wave_height_m": ec["expected_wave"],
                "expected_wind_speed_kt": ec["expected_wind"],
                "expected_cyclone_alert": ec["cyclone_alert"],
                "expected_safety_tier": ec["safety_tier"],
                "is_mpa": ec["is_mpa"],
                "mandate_do_not_sail": ec["mandate_do_not_sail"],
                "min_score": 0.0,
                "max_score": 0.50 if ec["safety_tier"] == "danger" else 0.70,
            },
            metadata={"category": ec["category"], "notes": ec["notes"]},
        )
        examples.append(ex)

    # 2. Coastal landing centers
    parquet_path = _find_parquet_features_file()
    parquet_lookup: dict[str, dict] = {}
    if parquet_path:
        try:
            import pyarrow.parquet as pq
            tbl = pq.read_table(
                str(parquet_path),
                columns=["site_name", "latitude", "longitude", "wave_height_m", "wind_speed_10m_kmh"],
            )
            df = tbl.to_pandas()
            for _, row in df.iterrows():
                site = str(row.get("site_name", ""))
                if site and site not in parquet_lookup:
                    w = float(row.get("wave_height_m", 1.4))
                    kmh = float(row.get("wind_speed_10m_kmh", 20.0))
                    parquet_lookup[site.lower()] = {
                        "wave": round(w, 2),
                        "wind": round(kmh * 0.539957, 1),
                    }
        except Exception as exc:
            logger.debug("Parquet read failed during dataset build: %s", exc)

    for i, c in enumerate(_SEED_LANDING_CENTERS):
        c_name = c["name"]
        pk_data = parquet_lookup.get(c_name.lower())
        wave = pk_data["wave"] if pk_data else c["base_wave"]
        wind = pk_data["wind"] if pk_data else c["base_wind"]

        tier = "safe"
        from backend.agents.safety_thresholds import derive_safety_tier as _tier

        _t = _tier(wave, wind, False, False)
        tier = _t.lower()

        ex = MarineEvalExample(
            example_id=f"COASTAL_CENTER_{i+1:02d}",
            landing_center=c_name,
            inputs={
                "latitude": c["lat"],
                "longitude": c["lon"],
                "query": f"Check sea and fishing safety off {c_name}, {c['state']}.",
                "expected_wave": wave,
                "expected_wind": wind,
            },
            reference={
                "expected_wave_height_m": wave,
                "expected_wind_speed_kt": wind,
                "expected_cyclone_alert": False,
                "expected_safety_tier": tier,
                "is_mpa": False,
                "mandate_do_not_sail": tier == "danger",
                "min_score": 0.70 if tier == "safe" else 0.40,
                "max_score": 1.00 if tier == "safe" else 0.69,
            },
            metadata={"state": c["state"], "category": "coastal_point"},
        )
        examples.append(ex)

    if limit is not None:
        return examples[:limit]
    return examples


def export_dataset_to_json(dataset: list[MarineEvalExample], output_path: str) -> int:
    """Exports dataset to formatted JSON for offline testing or LangSmith sync."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [ex.to_dict() for ex in dataset]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    return len(records)


def sync_dataset_to_langsmith(
    dataset_name: str = "orca-marine-benchmarks",
    dataset: list[MarineEvalExample] | None = None,
) -> str | None:
    """
    Syncs the marine benchmark dataset to LangSmith Cloud if configured.
    Returns dataset ID or None if running offline.
    """
    api_key = os.environ.get("LANGCHAIN_API_KEY")
    if not api_key or "your_" in api_key.lower():
        logger.info("LangSmith unconfigured; skipping cloud dataset sync.")
        return None

    try:
        from langsmith import Client

        client = Client(api_key=api_key)
        if dataset is None:
            dataset = load_marine_eval_dataset()

        # Check existing dataset
        try:
            ls_dataset = client.read_dataset(dataset_name=dataset_name)
            logger.info("LangSmith dataset '%s' exists with ID %s", dataset_name, ls_dataset.id)
            return str(ls_dataset.id)
        except Exception:
            pass

        # Create new dataset
        ls_dataset = client.create_dataset(
            dataset_name=dataset_name,
            description="ORCA Marine Intelligence benchmark evaluation dataset (ISRO SIH 26176)",
        )
        for ex in dataset:
            client.create_example(
                inputs=ex.inputs,
                outputs=ex.reference,
                metadata=ex.metadata,
                dataset_id=ls_dataset.id,
            )
        logger.info("Successfully created LangSmith dataset '%s' (%d examples)", dataset_name, len(dataset))
        return str(ls_dataset.id)
    except Exception as exc:
        logger.warning("LangSmith dataset sync encountered an error: %s", exc)
        return None
