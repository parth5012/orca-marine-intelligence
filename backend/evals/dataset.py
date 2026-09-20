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

try:
    from dotenv import load_dotenv

    _base_dir = Path(__file__).resolve().parents[2]
    for _env_file in (_base_dir / ".env", _base_dir / "backend" / ".env", Path(".env")):
        if _env_file.is_file():
            load_dotenv(dotenv_path=_env_file, override=False)
            break
except ImportError:
    pass

logger = logging.getLogger(__name__)


@dataclass
class MarineEvalExample:
    """Represents a single benchmark test case for LangSmith evaluation."""

    example_id: str
    landing_center: str
    inputs: dict[str, Any]
    reference: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    language: str = "en"
    query_vernacular: str = ""
    frozen_reply: str = ""
    invariants: dict[str, Any] = field(
        default_factory=lambda: {
            "safety_tier_same": True,
            "arabic_numerals_only": True,
            "do_not_sail_preserved": True,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarineEvalExample:
        default_invariants = {
            "safety_tier_same": True,
            "arabic_numerals_only": True,
            "do_not_sail_preserved": True,
        }
        return cls(
            example_id=data.get("example_id", ""),
            landing_center=data.get("landing_center", ""),
            inputs=data.get("inputs", {}),
            reference=data.get("reference", {}),
            metadata=data.get("metadata", {}),
            language=data.get("language", "en"),
            query_vernacular=data.get("query_vernacular", ""),
            frozen_reply=data.get("frozen_reply", ""),
            invariants=data.get("invariants") or default_invariants,
        )


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
        "expected_wave": 3.80,
        "expected_wind": 22.0,
        "cyclone_alert": False,
        "safety_tier": "danger",
        "is_mpa": False,
        "mandate_do_not_sail": True,
        "category": "extreme_waves",
        "notes": "Wave height 3.8m exceeds 3.5m danger threshold.",
    },
]

_ENGLISH_EDGE_SEED: list[dict[str, Any]] = [
    # Bucket 1: PFZ (~5 cases)
    {
        "id": "ENG_PFZ_01",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Are there good fishing zones near Kochi port?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "pfz", "notes": "Near port query"},
    },
    {
        "id": "ENG_PFZ_02",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Find PFZ coordinates near 9.93 N, 76.26 E"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "pfz", "notes": "Explicit GPS query"},
    },
    {
        "id": "ENG_PFZ_03",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.84, "longitude": 76.26, "query": "Show fishing zones 10km south of Kochi"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "pfz", "notes": "Relative offset 10km south"},
    },
    {
        "id": "ENG_PFZ_04",
        "landing_center": "Munambam",
        "inputs": {"latitude": 10.18, "longitude": 76.18, "query": "Any fish near mulambam?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "pfz", "notes": "Typo in landing center mulambam"},
    },
    {
        "id": "ENG_PFZ_05",
        "landing_center": "Visakhapatnam",
        "inputs": {"latitude": 17.68, "longitude": 83.21, "query": "Where to fish off Vizag?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "pfz", "notes": "Port alias Vizag for Visakhapatnam"},
    },

    # Bucket 2: Sea (~5 cases)
    {
        "id": "ENG_SEA_01",
        "landing_center": "Chennai",
        "inputs": {"latitude": 13.08, "longitude": 80.27, "query": "Sea condition off Chennai with 1.1m wave"},
        "reference": {"expected_wave_height_m": 1.1, "expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "sea", "notes": "Safe waves <1.5m"},
    },
    {
        "id": "ENG_SEA_02",
        "landing_center": "Mangalore",
        "inputs": {"latitude": 12.91, "longitude": 74.85, "query": "Wave height 2.2m off Mangalore"},
        "reference": {"expected_wave_height_m": 2.2, "expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "sea", "notes": "Caution waves 1.5-2.5m"},
    },
    {
        "id": "ENG_SEA_03",
        "landing_center": "Veraval",
        "inputs": {"latitude": 20.90, "longitude": 70.36, "query": "Monsoon swell 3.6m off Veraval"},
        "reference": {"expected_wave_height_m": 3.6, "expected_safety_tier": "danger", "mandate_do_not_sail": True, "min_score": 0.00, "max_score": 0.50},
        "metadata": {"category": "sea", "notes": "Danger waves >2.5m"},
    },
    {
        "id": "ENG_SEA_04",
        "landing_center": "Porbandar",
        "inputs": {"latitude": 21.64, "longitude": 69.60, "query": "High surface currents 2.2 knots off Porbandar"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "sea", "notes": "Current override condition 2.2kt caution band"},
    },
    {
        "id": "ENG_SEA_05",
        "landing_center": "Ratnagiri",
        "inputs": {"latitude": 16.99, "longitude": 73.28, "query": "Rough sea with 4.0m swell off Ratnagiri"},
        "reference": {"expected_wave_height_m": 4.0, "expected_safety_tier": "danger", "mandate_do_not_sail": True, "min_score": 0.00, "max_score": 0.50},
        "metadata": {"category": "sea", "notes": "Extreme swell danger"},
    },

    # Bucket 3: Weather (~5 cases)
    {
        "id": "ENG_WX_01",
        "landing_center": "Tuticorin",
        "inputs": {"latitude": 8.76, "longitude": 78.13, "query": "Wind 8 knots off Tuticorin"},
        "reference": {"expected_wind_speed_kt": 8.0, "expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "weather", "notes": "Safe wind tier <15kt"},
    },
    {
        "id": "ENG_WX_02",
        "landing_center": "Paradip",
        "inputs": {"latitude": 20.31, "longitude": 86.61, "query": "Wind 22 knots off Paradip"},
        "reference": {"expected_wind_speed_kt": 22.0, "expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "weather", "notes": "Caution wind tier 20-30kt"},
    },
    {
        "id": "ENG_WX_03",
        "landing_center": "Puri",
        "inputs": {"latitude": 19.80, "longitude": 85.83, "query": "Depression cyclone alert within 150km of Puri"},
        "reference": {"expected_cyclone_alert": True, "expected_safety_tier": "danger", "mandate_do_not_sail": True, "min_score": 0.00, "max_score": 0.50},
        "metadata": {"category": "weather", "notes": "Cyclone <500km proximity danger"},
    },
    {
        "id": "ENG_WX_04",
        "landing_center": "Chennai",
        "inputs": {"latitude": 13.08, "longitude": 80.27, "query": "Cyclone 800km away in deep Bay of Bengal, local weather off Chennai"},
        "reference": {"expected_cyclone_alert": False, "expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "weather", "notes": "Cyclone far >500km, safe locally"},
    },
    {
        "id": "ENG_WX_05",
        "landing_center": "Kakinada",
        "inputs": {"latitude": 16.98, "longitude": 82.25, "query": "Forecast with missing wind data off Kakinada"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "weather", "notes": "Missing wind data fail-open caution handling (ADR-0003)"},
    },

    # Bucket 4: Geofence Veto (~5 cases)
    {
        "id": "ENG_GEO_01",
        "landing_center": "Port Blair",
        "inputs": {"latitude": 11.53, "longitude": 92.58, "query": "Can I fish in Mahatma Gandhi Marine National Park?"},
        "reference": {"is_mpa": True, "expected_safety_tier": "danger", "mandate_do_not_sail": True, "min_score": 0.00, "max_score": 0.50},
        "metadata": {"category": "geofence_veto", "notes": "Inside restricted Marine Protected Area veto"},
    },
    {
        "id": "ENG_GEO_02",
        "landing_center": "International Waters",
        "inputs": {"latitude": 8.00, "longitude": 68.00, "query": "Fishing 250 nautical miles out in international waters"},
        "reference": {"expected_safety_tier": "danger", "mandate_do_not_sail": True, "min_score": 0.00, "max_score": 0.50},
        "metadata": {"category": "geofence_veto", "notes": "Outside Indian EEZ veto"},
    },
    {
        "id": "ENG_GEO_03",
        "landing_center": "Palk Bay",
        "inputs": {"latitude": 9.40, "longitude": 79.60, "query": "Within 1.5km of Sri Lanka IMBL boundary in Palk Strait"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "geofence_veto", "notes": "IMBL boundary buffer caution"},
    },
    {
        "id": "ENG_GEO_04",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.05, "query": "Fishing 20km offshore Kochi inside Indian EEZ"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "geofence_veto", "notes": "Safe fishing within Indian EEZ"},
    },
    {
        "id": "ENG_GEO_05",
        "landing_center": "Rani Jhansi",
        "inputs": {"latitude": 11.85, "longitude": 93.05, "query": "Rani Jhansi Marine National Park buffer boundary"},
        "reference": {"is_mpa": True, "expected_safety_tier": "danger", "mandate_do_not_sail": True, "min_score": 0.00, "max_score": 0.50},
        "metadata": {"category": "geofence_veto", "notes": "MPA reef boundary veto"},
    },

    # Bucket 5: Intent Split (~5 cases)
    {
        "id": "ENG_INT_01",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Where are the fish schools today?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "intent_split", "notes": "Fish-only intent"},
    },
    {
        "id": "ENG_INT_02",
        "landing_center": "Chennai",
        "inputs": {"latitude": 13.08, "longitude": 80.27, "query": "Is it safe to sail today?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "intent_split", "notes": "Safety-only intent"},
    },
    {
        "id": "ENG_INT_03",
        "landing_center": "Mangalore",
        "inputs": {"latitude": 12.91, "longitude": 74.85, "query": "Are there fish and is the sea safe off Mangalore?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "intent_split", "notes": "Fish + safety combined intent"},
    },
    {
        "id": "ENG_INT_04",
        "landing_center": "Porbandar",
        "inputs": {"latitude": 21.64, "longitude": 69.60, "query": "What is the 3-day weather forecast for Porbandar?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "intent_split", "notes": "wants_forecast intent"},
    },
    {
        "id": "ENG_INT_05",
        "landing_center": "Goa",
        "inputs": {"latitude": 15.49, "longitude": 73.82, "query": "Show sea surface temperature and chlorophyll maps off Goa"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "intent_split", "notes": "wants_sst and chlorophyll intent"},
    },

    # Bucket 6: Numerals (~5 cases)
    {
        "id": "ENG_NUM_01",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Heading 180 degrees at 12 knots off Kochi, check safety"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "numerals", "notes": "Bearing and knots preservation"},
    },
    {
        "id": "ENG_NUM_02",
        "landing_center": "Chennai",
        "inputs": {"latitude": 13.08, "longitude": 80.27, "query": "Zone at 25 km bearing 240 degrees from harbor"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "numerals", "notes": "Distance in km preservation"},
    },
    {
        "id": "ENG_NUM_03",
        "landing_center": "Kanyakumari",
        "inputs": {"latitude": 8.08, "longitude": 77.55, "query": "Condition at 8.08 N 77.55 E"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "numerals", "notes": "Decimal coordinates preservation"},
    },
    {
        "id": "ENG_NUM_04",
        "landing_center": "Visakhapatnam",
        "inputs": {"latitude": 17.68, "longitude": 83.21, "query": "Advisory for 15 knots wind and 2.2m wave off Vizag"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "numerals", "notes": "No __M*__ placeholder leak, 2.2m wave caution"},
    },
    {
        "id": "ENG_NUM_05",
        "landing_center": "Mumbai",
        "inputs": {"latitude": 18.92, "longitude": 72.83, "query": "Speed 7.5 knots, bearing 045, distance 14 km"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "numerals", "notes": "Standard Arabic digits 0-9"},
    },

    # Bucket 7: Adversarial (~5 cases)
    {
        "id": "ENG_ADV_01",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": ""},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.50, "max_score": 1.00},
        "metadata": {"category": "adversarial", "notes": "Empty query handling"},
    },
    {
        "id": "ENG_ADV_02",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "asdfghjk qwerty 12345"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.50, "max_score": 1.00},
        "metadata": {"category": "adversarial", "notes": "Gibberish text input"},
    },
    {
        "id": "ENG_ADV_03",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "<script>alert('xss')</script><img src=x onerror=alert(1)>"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.50, "max_score": 1.00},
        "metadata": {"category": "adversarial", "notes": "XSS injection handling"},
    },
    {
        "id": "ENG_ADV_04",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "What was the cricket score yesterday?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.50, "max_score": 1.00},
        "metadata": {"category": "adversarial", "notes": "Out of domain question"},
    },
    {
        "id": "ENG_ADV_05",
        "landing_center": "New York",
        "inputs": {"latitude": 40.71, "longitude": -74.00, "query": "Can I sail near Times Square NYC?"},
        "reference": {"expected_safety_tier": "danger", "mandate_do_not_sail": True, "min_score": 0.00, "max_score": 0.50},
        "metadata": {"category": "adversarial", "notes": "Inland foreign coordinates veto"},
    },

    # Bucket 8: Resilience (~5 cases)
    {
        "id": "ENG_RES_01",
        "landing_center": "Paradip",
        "inputs": {"latitude": 20.31, "longitude": 86.61, "query": "Simulated INCOIS fetch timeout off Paradip"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "resilience", "notes": "Timeout graceful degradation"},
    },
    {
        "id": "ENG_RES_02",
        "landing_center": "Mumbai",
        "inputs": {"latitude": 18.92, "longitude": 72.83, "query": "Redis cache disconnected during query off Mumbai"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.50, "max_score": 1.00},
        "metadata": {"category": "resilience", "notes": "Redis cache fallback"},
    },
    {
        "id": "ENG_RES_03",
        "landing_center": "Mangalore",
        "inputs": {"latitude": 12.91, "longitude": 74.85, "query": "Ocean state model unavailable, weather model ok"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "resilience", "notes": "Partial upstream failure"},
    },
    {
        "id": "ENG_RES_04",
        "landing_center": "Porbandar",
        "inputs": {"latitude": 21.64, "longitude": 69.60, "query": "Degraded data confidence 0.62 fallback advisory"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "resilience", "notes": "Degraded confidence amber status"},
    },
    {
        "id": "ENG_RES_05",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Rapid repeated burst queries from single boat"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.50, "max_score": 1.00},
        "metadata": {"category": "resilience", "notes": "Rate limit burst resilience"},
    },

    # Bucket 9: Temporal / Forecast (~5 cases)
    {
        "id": "ENG_TMP_01",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Can I go fishing tomorrow morning at 5 AM?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "temporal_forecast", "notes": "Tomorrow morning departure"},
    },
    {
        "id": "ENG_TMP_02",
        "landing_center": "Chennai",
        "inputs": {"latitude": 13.08, "longitude": 80.27, "query": "When is the best time to leave port today?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "temporal_forecast", "notes": "Best departure window timing"},
    },
    {
        "id": "ENG_TMP_03",
        "landing_center": "Kanyakumari",
        "inputs": {"latitude": 8.08, "longitude": 77.55, "query": "Expected weather for a 6 hour trip offshore"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "temporal_forecast", "notes": "6 hour round-trip window"},
    },
    {
        "id": "ENG_TMP_04",
        "landing_center": "Visakhapatnam",
        "inputs": {"latitude": 17.68, "longitude": 83.21, "query": "Sea state outlook for Saturday and Sunday"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "temporal_forecast", "notes": "Weekend outlook"},
    },
    {
        "id": "ENG_TMP_05",
        "landing_center": "Mumbai",
        "inputs": {"latitude": 18.92, "longitude": 72.83, "query": "Evening departure 6 PM returning midnight"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "temporal_forecast", "notes": "Night departure window"},
    },

    # Bucket 10: SST / Chlorophyll (~5 cases)
    {
        "id": "ENG_SST_01",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "What is the sea surface temperature near Kochi?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "sst_chlorophyll", "notes": "SST measurement advisory"},
    },
    {
        "id": "ENG_SST_02",
        "landing_center": "Chennai",
        "inputs": {"latitude": 13.08, "longitude": 80.27, "query": "Where are the chlorophyll hotspots for tuna?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "sst_chlorophyll", "notes": "Chlorophyll hotspot query"},
    },
    {
        "id": "ENG_SST_03",
        "landing_center": "Veraval",
        "inputs": {"latitude": 20.90, "longitude": 70.36, "query": "Is there a thermal front gradient off Veraval?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "sst_chlorophyll", "notes": "Thermal front gradient"},
    },
    {
        "id": "ENG_SST_04",
        "landing_center": "Mangalore",
        "inputs": {"latitude": 12.91, "longitude": 74.85, "query": "Ocean color satellite imagery interpretation"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "sst_chlorophyll", "notes": "Ocean color satellite interpretation"},
    },
    {
        "id": "ENG_SST_05",
        "landing_center": "Tuticorin",
        "inputs": {"latitude": 8.76, "longitude": 78.13, "query": "SST anomaly check off Tuticorin"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "sst_chlorophyll", "notes": "SST anomaly detection"},
    },

    # Bucket 11: Species + Depth (~5 cases)
    {
        "id": "ENG_SPD_01",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Where are sardines found and what depth?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "species_depth", "notes": "Sardine depth contour query"},
    },
    {
        "id": "ENG_SPD_02",
        "landing_center": "Mangalore",
        "inputs": {"latitude": 12.91, "longitude": 74.85, "query": "Indian mackerel schools depth range 20-30m off Mangalore"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "species_depth", "notes": "Mackerel depth range 20-30m"},
    },
    {
        "id": "ENG_SPD_03",
        "landing_center": "Mumbai",
        "inputs": {"latitude": 18.92, "longitude": 72.83, "query": "Pelagic seer fish / surmai fishing grounds off Mumbai"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "species_depth", "notes": "Seer fish / surmai pelagic zone"},
    },
    {
        "id": "ENG_SPD_04",
        "landing_center": "Paradip",
        "inputs": {"latitude": 20.31, "longitude": 86.61, "query": "Coastal shrimp / prawn trawling depth off Paradip"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "species_depth", "notes": "Shrimp demersal depth"},
    },
    {
        "id": "ENG_SPD_05",
        "landing_center": "Kanyakumari",
        "inputs": {"latitude": 8.08, "longitude": 77.55, "query": "Yellowfin tuna longline depths beyond 50m contour"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "species_depth", "notes": "Yellowfin tuna oceanic contour"},
    },

    # Bucket 12: Multi-turn / Session (~5 cases)
    {
        "id": "ENG_MTS_01",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "And what about the waves?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "multi_turn_session", "notes": "Follow-up query without explicit location"},
    },
    {
        "id": "ENG_MTS_02",
        "landing_center": "Chennai",
        "inputs": {"latitude": 13.08, "longitude": 80.27, "query": "And tomorrow?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "multi_turn_session", "notes": "Temporal follow-up preserving session context"},
    },
    {
        "id": "ENG_MTS_03",
        "landing_center": "Chennai",
        "inputs": {"latitude": 13.08, "longitude": 80.27, "query": "Now check for Chennai instead"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "multi_turn_session", "notes": "Location switch within active session"},
    },
    {
        "id": "ENG_MTS_04",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Start new session, reset my boat coordinates"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "multi_turn_session", "notes": "Clear session and reset state"},
    },
    {
        "id": "ENG_MTS_05",
        "landing_center": "Visakhapatnam",
        "inputs": {"latitude": 17.68, "longitude": 83.21, "query": "Repeat the coordinates you just gave me"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "multi_turn_session", "notes": "Prior response context memory recall"},
    },

    # Bucket 13: Lang Gate / Voice Typo (~5 cases)
    {
        "id": "ENG_LNG_01",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "मछली कहाँ मिलेगी? (UI language is English)"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "lang_gate_voice_typo", "notes": "UI=en with Devanagari Hindi text"},
    },
    {
        "id": "ENG_LNG_02",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "machli kaha hai kochi ke paas?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "lang_gate_voice_typo", "notes": "Romanized Hindi query"},
    },
    {
        "id": "ENG_LNG_03",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Check sea condition near Kohchi harbor"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "lang_gate_voice_typo", "notes": "ASR speech-to-text typo Kohchi"},
    },
    {
        "id": "ENG_LNG_04",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Kochi me machli पकड़ने ke zones"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "lang_gate_voice_typo", "notes": "Mixed Latin and Devanagari script query"},
    },
    {
        "id": "ENG_LNG_05",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "Kochi kadalil povan pattumo?"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "lang_gate_voice_typo", "notes": "Romanized Malayalam query"},
    },

    # Bucket 14: Data Freshness (~5 cases)
    {
        "id": "ENG_FSH_01",
        "landing_center": "Kochi",
        "inputs": {"latitude": 9.93, "longitude": 76.26, "query": "No PFZ features available in sector today"},
        "reference": {"expected_safety_tier": "safe", "mandate_do_not_sail": False, "min_score": 0.70, "max_score": 1.00},
        "metadata": {"category": "data_freshness", "notes": "Empty PFZ feature collection handling"},
    },
    {
        "id": "ENG_FSH_02",
        "landing_center": "Chennai",
        "inputs": {"latitude": 13.08, "longitude": 80.27, "query": "Advisory when ocean data is older than 6 hours"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "data_freshness", "notes": "Stale data warning threshold >6h"},
    },
    {
        "id": "ENG_FSH_03",
        "landing_center": "Lakshadweep",
        "inputs": {"latitude": 10.57, "longitude": 72.64, "query": "Querying unknown sector SEC999 off Lakshadweep"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "data_freshness", "notes": "Nonexistent sector graceful handling"},
    },
    {
        "id": "ENG_FSH_04",
        "landing_center": "Mumbai",
        "inputs": {"latitude": 18.92, "longitude": 72.83, "query": "Malformed bounding box coordinates handling"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "data_freshness", "notes": "Invalid bbox coordinates fallback"},
    },
    {
        "id": "ENG_FSH_05",
        "landing_center": "Porbandar",
        "inputs": {"latitude": 21.64, "longitude": 69.60, "query": "Feature with geometry: null returned from feed"},
        "reference": {"expected_safety_tier": "caution", "mandate_do_not_sail": False, "min_score": 0.40, "max_score": 0.70},
        "metadata": {"category": "data_freshness", "notes": "Null geometry feature payload handling"},
    },
]


def _find_parquet_features_file() -> Path | None:
    base = Path(__file__).resolve().parents[2]
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

    # 3. Exhaustive English 14-bucket seed cases (~70 cases)
    for item in _ENGLISH_EDGE_SEED:
        ex = MarineEvalExample(
            example_id=item["id"],
            landing_center=item["landing_center"],
            inputs=item["inputs"].copy(),
            reference=item["reference"].copy(),
            metadata=item["metadata"].copy(),
        )
        examples.append(ex)

    logger.info(
        "Built marine eval dataset: %d examples%s",
        len(examples), f" (limit {limit})" if limit is not None else "",
    )
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


def load_golden_v1(path: str = "data/golden_v1.json", limit: int | None = None) -> list[MarineEvalExample]:
    """
    Loads frozen multilingual benchmark dataset from data/golden_v1.json.
    Falls back to load_marine_eval_dataset() with a warning if the file does not exist.
    """
    p = Path(path)
    if not p.is_absolute():
        repo_root = Path(__file__).resolve().parents[2]
        golden_path = repo_root / path
        if not golden_path.exists():
            golden_path = p
    else:
        golden_path = p

    if not golden_path.exists():
        logger.warning(
            "Golden v1 dataset file not found at %s; falling back to default marine eval dataset.",
            golden_path,
        )
        return load_marine_eval_dataset(limit=limit)

    try:
        with open(golden_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        examples: list[MarineEvalExample] = [
            MarineEvalExample.from_dict(item) for item in data
        ]
        logger.info(
            "Loaded golden v1 dataset: %d records from %s%s",
            len(examples), golden_path, f" (limit {limit})" if limit is not None else "",
        )
        if limit is not None:
            return examples[:limit]
        return examples
    except Exception as exc:
        logger.warning(
            "Failed reading golden v1 dataset from %s (%s); falling back to default.",
            golden_path,
            exc,
        )
        return load_marine_eval_dataset(limit=limit)


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
            outputs = dict(ex.reference)
            if ex.frozen_reply:
                outputs["frozen_reply"] = ex.frozen_reply
            metadata = dict(ex.metadata)
            metadata["language"] = ex.language
            if ex.query_vernacular:
                metadata["query_vernacular"] = ex.query_vernacular
            metadata["invariants"] = ex.invariants

            client.create_example(
                inputs=ex.inputs,
                outputs=outputs,
                metadata=metadata,
                dataset_id=ls_dataset.id,
            )
        logger.info("Successfully created LangSmith dataset '%s' (%d examples)", dataset_name, len(dataset))
        return str(ls_dataset.id)
    except Exception as exc:
        logger.warning("LangSmith dataset sync encountered an error: %s", exc)
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ORCA Marine Benchmark Dataset CLI")
    parser.add_argument("--sync", action="store_true", help="Sync dataset to LangSmith")
    parser.add_argument("--name", default="orca-golden-v1", help="LangSmith dataset name")
    parser.add_argument("--dataset", default=None, help="Path to golden dataset JSON")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Log verbosity (default INFO).")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True,
    )

    if args.sync:
        if args.dataset:
            logger.info("Loading golden dataset from %s", args.dataset)
            ds = load_golden_v1(args.dataset)
        else:
            logger.info("Loading default dataset (golden v1 if present, else English seed)")
            ds = load_golden_v1() if Path("data/golden_v1.json").exists() else load_marine_eval_dataset()
        logger.info("Syncing %d examples to LangSmith dataset '%s'", len(ds), args.name)
        res = sync_dataset_to_langsmith(dataset_name=args.name, dataset=ds)
        print(f"Sync result: {res}")
