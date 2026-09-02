# ORCA — GeoJSON-Centric Architecture

This document explains how ORCA works internally: the data pipeline from INCOIS satellites to fisherman's phone, the multi-agent architecture, and the shared GeoJSON data model that keeps all agents aligned.

**Live demo:** https://cron-system.vercel.app/orca/

**For the 2-week schedule, see** [ORCA_2Week_MPP_Plan.md](ORCA_2Week_MPP_Plan.md).
**For file locations and run instructions, see** [ORCA_Codebase_Guide.md](ORCA_Codebase_Guide.md).

---

## The Problem

Indian fishermen receive daily Potential Fishing Zone advisories from INCOIS as HTML tables published at 11:00 AM IST. These tables list zone names, compass directions, bearings, depths, and distances — but only as text. A fisherman in Kerala who reads "Pallithottam, SW, 232, 55-60, 645-650" has to mentally translate those numbers into a decision about where to sail, whether the sea is safe, and whether the route crosses any restricted zones.

ORCA turns this text into spatial intelligence by converting INCOIS tables into GeoJSON, running four specialist agents in parallel against the same coordinates, and presenting a single safe recommendation on an interactive map with evidence.

---

## The GeoJSON Pipeline

The core innovation of ORCA is a simple but powerful data pipeline that converts INCOIS's text-based advisories into a shared GeoJSON FeatureCollection that all agents can query.

### Step 1: Fetch TextData HTML

INCOIS publishes 14 sector pages (SEC001 through SEC014) covering the entire Indian coast. Each page contains an HTML table with seven columns: place name, compass direction, bearing, depth range, distance range, latitude in DMS, and longitude in DMS.

The fetch requires a valid session cookie obtained from the TextDataHome page. This cookie is refreshed daily before the 11:30 AM ingest window.

```
GET https://incois.gov.in/MarineFisheries/TextData?secid=SEC005
Cookie: JSESSIONID=<daily-session-id>
```

### Step 2: Parse HTML Tables

Each sector page is parsed to extract the seven-column table rows. The parser handles variations in HTML structure across sectors and gracefully skips malformed rows.

### Step 3: Convert DMS Coordinates

INCOIS uses Degrees-Minutes-Seconds format (for example, "8 33 18 N" for latitude). Each coordinate pair is converted to decimal degrees using the standard formula:

```
decimal = degrees + minutes/60 + seconds/3600
```

Negative values are applied for South and West hemispheres. The converted coordinates become the `coordinates` array in a GeoJSON Point geometry.

### Step 4: Build GeoJSON FeatureCollection

Each parsed row becomes a GeoJSON Feature with a Point geometry and a properties object containing the zone metadata:

```json
{
  "type": "Feature",
  "properties": {
    "zone_id": "SEC005_001",
    "place": "Pallithottam",
    "direction": "SW",
    "bearing": 232,
    "depth": "55-60",
    "distance_km": 645,
    "intensity": "high",
    "sector": "KERALA",
    "source": "incois_textdata",
    "timestamp": "2026-09-02T11:30:00+05:30"
  },
  "geometry": {
    "type": "Point",
    "coordinates": [76.167, 8.555]
  }
}
```

The full collection currently contains 437 features across all 14 sectors.

### Step 5: Store and Cache

The FeatureCollection is written to `data/pfz-today.geojson` on disk, upserted into PostGIS for spatial queries, and cached in Redis with a 6-hour TTL until the next daily fetch.

---

## Multi-Agent Architecture

ORCA uses four specialist agents that all read the same GeoJSON coordinates. This shared data model is critical — without it, agents would produce conflicting recommendations.

### The Orchestrator (Brain)

The Orchestrator receives a user query, detects the language, extracts or receives GPS coordinates, and dispatches sub-tasks to the four specialist agents in parallel. It uses a ReAct-style tool routing pattern to decide which agents to call.

### Fish Finder

Queries the GeoJSON collection for the closest productive zones within a configurable radius of the user's location. It ranks results by proximity and returns the top candidates with metadata.

### Sea Checker

For each candidate zone, the Sea Checker evaluates wave height and current speed. In the MVP it uses mock data (0.8 meters). In Week 2 it will pull real data from the Ocean State Forecast.

### Weather Agent

Evaluates wind speed and tide conditions at each candidate zone. In the MVP it uses mock data. In Week 2 it will integrate with IMD's marine weather API.

### Danger Agent

Checks each candidate zone against EEZ (Exclusive Economic Zone) boundaries from MarineRegions and MPA (Marine Protected Area) boundaries from WDPA using PostGIS spatial containment queries. It also checks for active cyclone warnings.

### Smart Combiner

After all four agents return their assessments, the Smart Combiner ranks the candidates using a weighted scoring formula:

- Closest zone: 40% weight
- Safe sea conditions: 30% weight
- Favorable wind: 20% weight
- No geofence violation: 10% weight

The Combiner produces a single safe recommendation with evidence citations (for example, "INCOIS TextData SEC005 KERALA 02-Sep-2026").

---

## Kochi Walkthrough

Here is the complete flow for a fisherman near Kochi asking in Malayalam:

1. The fisherman types "എവിടെ മത്സ്യം?" (Where is fish?) in the chat interface.

2. The system detects Malayalam and extracts GPS coordinates from the device or text context.

3. The Fish Finder queries the 437-point GeoJSON collection and finds Pallithottam at 8.555°N, 76.167°E — approximately 55 kilometers southwest, bearing 232.

4. The Sea Checker evaluates wave height at that point (0.8 meters — safe).

5. The Weather Agent evaluates wind speed (8 knots — favorable).

6. The Danger Agent confirms no EEZ or MPA violations and no active cyclone warnings.

7. The Smart Combiner ranks Pallithottam as the top recommendation with a confidence score of 0.87.

8. The Map View flies to the zone coordinates, displays a cyan circle with a popup showing bearing, distance, and citation, and draws a green route line from the fisherman's GPS position.

9. The reply is sent in Malayalam with the map reference and safety badge (green).

---

## Data Schema

### pfz_zones

| Column | Type | Description |
|--------|------|-------------|
| zone_id | VARCHAR(64) | Unique identifier (for example, SEC005_001) |
| zone_name | VARCHAR(256) | Place name from INCOIS |
| area_km2 | FLOAT | Estimated zone area in square kilometers |
| intensity | VARCHAR(32) | Fishing intensity: low, medium, or high |
| source | VARCHAR(64) | Data source: incois_textdata or copernicus |
| geom | GEOMETRY(Point, 4326) | WGS84 coordinates |
| created_at | TIMESTAMPTZ | First ingest timestamp |
| updated_at | TIMESTAMPTZ | Last update timestamp |

### eez_boundaries

| Column | Type | Description |
|--------|------|-------------|
| country | VARCHAR(128) | Sovereign state |
| eez_name | VARCHAR(256) | EEZ designation name |
| geom | GEOMETRY(MultiPolygon, 4326) | Boundary polygon |

### mpa_boundaries

| Column | Type | Description |
|--------|------|-------------|
| mpa_name | VARCHAR(256) | Protected area name |
| iucn_category | VARCHAR(32) | IUCN management category |
| area_km2 | FLOAT | Protected area size |
| geom | GEOMETRY(MultiPolygon, 4326) | Boundary polygon |

---

## Failure Modes

### INCOIS TextData Unavailable

If INCOIS returns a 404 or the session cookie expires, the system falls back to yesterday's cached GeoJSON from Redis. The user sees a warning that data may be up to 24 hours old. A Copernicus Marine fallback is planned for Week 5.

### Session Cookie Expiry

The JSESSIONID cookie expires periodically. The ingest script refreshes it by requesting the TextDataHome page before each sector fetch. If the refresh fails, the system retries with exponential backoff.

### PostGIS Unavailable

If PostGIS is unreachable, the system falls back to serving the GeoJSON file directly from disk. Spatial queries (geofence checks, proximity searches) will return errors, but basic PFZ display continues to work.

### Redis Unavailable

If Redis is unreachable, the system bypasses caching and queries PostGIS directly. Response times increase but functionality is preserved. Conversation memory for multi-turn chat is lost.

### Agent Timeout

If any individual agent takes longer than 10 seconds to respond, the Orchestrator proceeds with partial results and marks the missing agent's assessment as "unknown" in the combined response.

---

## Tech Stack Summary

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Data Source | INCOIS TextData | Daily PFZ advisories |
| Storage | PostGIS | Spatial queries and boundary containment |
| Cache | Redis | 6-hour PFZ cache, conversation memory |
| Backend | FastAPI (Python 3.11) | API server and agent orchestration |
| Frontend | Next.js 14, React Leaflet | Chat interface and map visualization |
| Language | Bhashini ULCA | 22-language translation and detection |
| Deployment | Docker, Vercel | Local development and production hosting |

---

*Architecture document for ORCA SIH26176. For the development schedule, see [ORCA_2Week_MPP_Plan.md](ORCA_2Week_MPP_Plan.md). For file locations and setup instructions, see [ORCA_Codebase_Guide.md](ORCA_Codebase_Guide.md).*
