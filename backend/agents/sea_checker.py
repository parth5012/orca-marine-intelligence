"""
Sea Checker Agent — Wave and Current Conditions

Owner: M5 (Safety & Geofencing)
Module: backend/agents/sea_checker.py

The Sea Checker agent evaluates ocean conditions at PFZ zone coordinates.
It reports wave height and current speed to determine if a zone is safe
for small fishing vessels.

Data Sources:
    - W1 (Mock): Returns hardcoded wave=0.8m, current=1.0kt for all points
    - W2 (Real): OSF/GOFS 06Z forecast data via xarray/Zarr

Safety Thresholds:
    - Wave height < 1.5m → SAFE
    - Wave height 1.5-2.5m → CAUTION
    - Wave height > 2.5m → DANGEROUS
    - Current > 3 knots → DANGEROUS regardless of wave

TODO:
    - [ ] Implement mock data source for W1
    - [ ] Add OSF/GOFS real data integration for W2
    - [ ] Join conditions to PFZ points by nearest lat/lon grid cell
    - [ ] Return safety classification per zone
"""

from typing import Any


async def check_sea_conditions(points: list[dict]) -> list[dict]:
    """
    Check wave height and current speed at each PFZ coordinate.

    Args:
        points: List of {"lat": float, "lon": float, "place": str}.

    Returns:
        List of dicts with wave_m, current_kt, safety_status per point.
    """
    # TODO: Implement — W1 mock, W2 real OSF
    raise NotImplementedError("Sea Checker not yet implemented")
