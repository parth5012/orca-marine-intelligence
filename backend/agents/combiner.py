"""
Smart Combiner — Fusion Ranking Agent

Owner: M-A (Agents & Orchestration) � ranking & evidence
Module: backend/agents/combiner.py

The Smart Combiner receives results from all four specialist agents and
produces a single ranked list of safe fishing zones. It ensures that the
recommended spot is not just the closest, but the safest and most productive.

Scoring Formula:
    score = closest * 0.4 + safe_sea * 0.3 + wind_ok * 0.2 + not_banned * 0.1

    - closest:    Inverse distance normalized to [0, 1]. Nearer = higher score.
    - safe_sea:   1.0 if wave < 1.5m and current < 2 knots, else decays linearly.
    - wind_ok:    1.0 if wind < 15 knots, else decays linearly to 0 at 30 knots.
    - not_banned: 1.0 if outside EEZ exclusion / MPA / IMBL, else 0.0 (binary).

Edge Cases:
    - All spots unsafe → return warning with nearest safe alternative beyond radius.
    - No spots within radius → expand radius incrementally (80km → 120km → 160km).
    - Tie in score → prefer the spot with lower wave height.

Output includes:
    - Ranked list of zones with scores and safety status
    - Explanation string (why this spot was chosen)
    - Citation to INCOIS TextData source (sector, date)
    - Map reference (lat/lon for MapView to fly to)

TODO:
    - [ ] Implement scoring with configurable weights
    - [ ] Add input normalization for distance, wave, wind
    - [ ] Define safety thresholds (wave < 1.5m, wind < 15kt, current < 2kt)
    - [ ] Handle edge cases (all unsafe, no spots, ties)
    - [ ] Generate human-readable explanation string
    - [ ] Include INCOIS citation in output
"""

from typing import Any


def combine_and_rank(
    fish_results: list[dict],
    sea_results: list[dict],
    weather_results: list[dict],
    danger_results: list[dict],
    user_location: dict,
) -> dict:
    """
    Rank PFZ zones by composite safety and proximity score.

    Args:
        fish_results: Closest PFZ points from FishFinder agent.
        sea_results: Wave/current data from SeaChecker agent.
        weather_results: Wind/tide data from WeatherAgent.
        danger_results: Geofence/cyclone checks from DangerAgent.
        user_location: {"lat": float, "lon": float} of the fisherman.

    Returns:
        {
            "ranked_zones": [...],
            "best": {"place": str, "lat": float, "lon": float, "score": float},
            "explanation": str,
            "citation": str,
            "all_unsafe": bool
        }
    """
    # TODO: Implement ranking logic
    raise NotImplementedError("Smart Combiner not yet implemented")
