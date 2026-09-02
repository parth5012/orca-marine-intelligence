"""
Copernicus Marine Fallback Ingest

Owner: M-B (Data + Safety)
Module: backend/ingest/copernicus_fallback.py

Fallback data source for when INCOIS TextData is unavailable.
Uses Copernicus Marine API for sea surface temperature (SST) and
chlorophyll concentration to estimate productive zones.

This is a Week 5+ backlog item — not needed for MVP.

Flow:
    1. Query Copernicus Marine API for SST and chl-a grids
    2. Apply simple threshold-based zone identification
    3. Convert to GeoJSON features matching PFZ schema
    4. Merge with primary INCOIS data (conflict: INCOIS wins)

Dependencies:
    - copernicusmarine Python package
    - GeoPandas for spatial processing

TODO:
    - [ ] Implement Copernicus Marine API client (Week 5+)
    - [ ] Define SST/chl-a thresholds for productive zone detection
    - [ ] Add merge logic with INCOIS primary data
    - [ ] Cache results in PostGIS with provenance metadata
"""

from typing import Any


async def fetch_copernicus_fallback() -> dict:
    """
    Fetch fallback PFZ estimates from Copernicus Marine.

    Returns:
        dict with "features" (list of GeoJSON Features) and "source" (str).
    """
    # TODO: Implement Copernicus Marine fallback (Week 5+)
    raise NotImplementedError("Copernicus fallback not yet implemented — backlog for W5")
