# ORCA Marine Data Package — Integration & Multi-Agent Architecture Summary

## 1. Overview
The Marine Data Package (`data/marine_data_package/marine-data/`) provides validated oceanographic, meteorological, and geospatial intelligence across the Indian EEZ (bounds: lat -5° to 25°N, lon 65° to 100°E) for SIH 2026 Problem Statement 26176.

---

## 2. Available Datasets & Structure
- **Unified Features (`unified/marine_features/coastal_point_features.parquet`)**:
  - Daily time series across 20 coastal landing centers (Kochi, Chennai, Porbandar, Kanyakumari, etc.).
  - Parameters: SST (°C), SST anomaly, Chlorophyll-a (mg/m³), depth (m), wave height (m), wave period (s), wind speed (kt), tide range, nearest cyclone distance (km), lightning/convective proxy.
- **Hazards & Events (`unified/marine_hazards/`, `unified/marine_events/`)**:
  - `cyclone_events.parquet`: 198 North Indian Ocean cyclones (IBTrACS, 2006–2025) with tracks, wind radii, and central pressures.
  - `marine_hazards.parquet`: Sourced INCOIS High Wave Advisories (HWA) and Swell Surge Advisories (SSA).
- **Geospatial & Boundaries (`processed/gis/`, `data/eez.geojson`, `data/mpa.geojson`)**:
  - Boundary vectors for Indian EEZ (exclusive economic zone), Marine Protected Areas (WDPA), and 10m Natural Earth coastlines.
- **Gridded Rasters (`processed/sst/`, `processed/chlorophyll/`, `processed/bathymetry/`)**:
  - 0.25° NOAA OISST daily grids, 4km VIIRS monthly chlorophyll grids, 30 arc-sec ETOPO2022 bathymetry.

---

## 3. How It Powers the Multi-Agent Architecture
| Agent | W1 Heuristic / Stub | Marine Data Package Integration |
|---|---|---|
| **Fish Finder (`fish_finder.py`)** | Static search on `data/pfz-today.geojson` | Validates PFZ coordinates against real SST fronts, Chlorophyll-a gradients, and bathymetric shelf breaks. |
| **Sea Checker (`sea_checker.py`)** | Deterministic zone-hash wave mock | Ingests ERA5-Ocean significant wave height (`wave_height_m`) and swell period into `fetch_osf_wave_current()`. |
| **Weather Agent (`weather_agent.py`)** | Deterministic zone-hash wind mock | Feeds ERA5 wind speeds (`wind_speed_kt`) and IBTrACS storm centers into `fetch_imd_wind()` and `fetch_imd_cyclones()`. |
| **Danger Agent (`danger_agent.py`)** | Ray-casting fallback on GeoJSON | Evaluates spatial containment against real EEZ (`eez.geojson`) and MPA (`mpa.geojson`) boundaries with 2km international border safety buffers. |
| **Smart Combiner (`combiner.py`)** | Fixed synthetic weights | Calibrates multi-factor scoring formula (`0.4*distance + 0.3*sea + 0.2*wind + 0.1*geofence`) against verified historical safety outcomes. |
| **Synthesizer Agent (`synthesizer_service.py`)** | Generic templated text | Enriches vernacular responses with exact metric grounding (e.g., exact wave height, wind gust, cyclone distance). |

---

## 4. Live API vs. Offline Fallback (3-Tier Ingestion Strategy)
Live scraping directly during user prompts fails due to high latency (>3s), INCOIS `JSESSIONID` session expiration, and rate limits. The system uses a 3-tier approach:

1. **Tier 1 (Cron Ingestion)**: Scheduled worker (`backend/ingest/incois_textdata.py`) runs at 11:30 AM IST to fetch daily INCOIS HTML bulletins and store to database.
2. **Tier 2 (Fast Cache & Spatial DB)**: PostGIS stores spatial tables (`pfz_zones`, `eez_boundaries`, `mpa_boundaries`); Redis caches active daily features with 6-hour TTL (<10ms access).
3. **Tier 3 (Marine Data Package Fallback)**: If live ingestion fails (network failure, government portal 503), agents gracefully degrade to data package snapshots (`coastal_point_features.parquet` / `pfz-today.geojson`) and attach a data-freshness warning.

---

## 5. Concrete Integration Code Examples

### A. Sea Checker (`backend/agents/subagents/sea_checker.py`)
```python
import pyarrow.parquet as pq

_FEATURES_PATH = "D:/work/projects/orca-marine-intelligence/data/marine_data_package/marine-data/unified/marine_features/coastal_point_features.parquet"

async def fetch_osf_wave_current(lat: float, lon: float) -> tuple[float, float]:
    table = pq.read_table(_FEATURES_PATH, columns=["latitude", "longitude", "wave_height_m"])
    lats = table["latitude"].to_numpy()
    lons = table["longitude"].to_numpy()
    dist_sq = (lats - lat) ** 2 + (lons - lon) ** 2
    nearest_idx = int(dist_sq.argmin())
    
    wave_height = float(table["wave_height_m"][nearest_idx].as_py() or 1.2)
    current_kt = 1.0
    return wave_height, current_kt
```

### B. Weather Agent (`backend/agents/subagents/weather_agent.py`)
```python
import pyarrow.parquet as pq

_CYCLONE_PATH = "D:/work/projects/orca-marine-intelligence/data/marine_data_package/marine-data/unified/marine_events/cyclone_events.parquet"

async def fetch_imd_cyclones() -> list[dict]:
    table = pq.read_table(_CYCLONE_PATH)
    cyclones = []
    for row in table.to_pylist()[-5:]:
        cyclones.append({
            "name": row.get("storm_name", "UNKNOWN"),
            "lat": row.get("lat"),
            "lon": row.get("lon"),
            "wind_speed_kt": row.get("max_wind_kt", 0.0),
            "pressure_hpa": row.get("min_pressure_hpa", 1000.0)
        })
    return cyclones
```

### C. PostGIS Database Preload
```sql
-- Seed EEZ boundary polygons
INSERT INTO eez_boundaries (name, geom)
SELECT 'Indian EEZ', ST_GeomFromGeoJSON(feat->>'geometry')
FROM json_array_elements((pg_read_file('D:/work/projects/orca-marine-intelligence/data/eez.geojson')::json)->'features') AS feat;

-- Seed MPA marine reserve polygons
INSERT INTO mpa_boundaries (name, geom)
SELECT feat->'properties'->>'NAME', ST_GeomFromGeoJSON(feat->>'geometry')
FROM json_array_elements((pg_read_file('D:/work/projects/orca-marine-intelligence/data/mpa.geojson')::json)->'features') AS feat;
```

---

## 6. Implementation Checklist
- [ ] Connect `backend/agents/subagents/sea_checker.py:fetch_osf_wave_current()` to parquet/PostGIS.
- [ ] Connect `backend/agents/subagents/weather_agent.py:fetch_imd_cyclones()` to `cyclone_events.parquet`.
- [ ] Ensure `data/eez.geojson` and `data/mpa.geojson` are loaded in PostGIS via `backend/db/schema.sql`.
- [ ] Implement retry and stale-data flags in `backend/ingest/incois_textdata.py` using data package as offline fallback.
