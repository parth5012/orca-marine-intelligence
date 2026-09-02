# ORCA — API Endpoints

**Base URL:** `http://localhost:8000` (development) or `https://orca-marine-intelligence-api.onrender.com` (production)

**Authentication:** None for MVP. API key authentication planned for production.

**CORS:** Configured via `ALLOWED_ORIGINS` environment variable. Default allows `http://localhost:3000` and `https://cron-system.vercel.app`.

**Content Types:** All endpoints accept and return `application/json` unless noted otherwise.

---

## GET /health

Health check endpoint for monitoring and deployment verification.

**Response:**

```json
{
  "status": "ok",
  "service": "orca-marine-intelligence"
}
```

**Status Codes:**
- `200` — Service is healthy
- `503` — Service is unhealthy (PostGIS or Redis unreachable)

---

## GET /api/pfz/today

Returns today's Potential Fishing Zone data as a GeoJSON FeatureCollection. Data is sourced from INCOIS TextData and cached in Redis for 6 hours.

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sector` | string | No | Filter by sector name (e.g., "KERALA", "GUJARAT") |
| `max_distance_km` | number | No | Maximum distance from coast in km (default: 100) |

**Response:**

```json
{
  "type": "FeatureCollection",
  "features": [
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
        "source": "incois_textdata",
        "sector": "KERALA"
      },
      "geometry": {
        "type": "Point",
        "coordinates": [76.167, 8.555]
      }
    }
  ],
  "metadata": {
    "count": 437,
    "timestamp": "2026-09-02T11:30:00+05:30",
    "source": "incois_textdata"
  }
}
```

**Status Codes:**
- `200` — Success
- `502` — INCOIS upstream unavailable (returns cached data if available)
- `503` — Database unavailable

---

## GET /api/tiles/{z}/{x}/{y}.pbf

Returns vector tiles (Mapbox Vector Tile format) for map rendering. Used by MapLibre/Leaflet on the frontend for efficient spatial data display.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `z` | integer | Zoom level (0-18) |
| `x` | integer | Tile x coordinate |
| `y` | integer | Tile y coordinate |

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `layer` | string | No | Tile layer: "pfz", "eez", "mpa", or "recommend" (default: "pfz") |

**Response:** `application/x-protobuf` (MVT format)

**Status Codes:**
- `200` — Success
- `400` — Invalid tile coordinates
- `503` — PostGIS unavailable

---

## POST /api/chat

Send a conversational query to the ORCA multi-agent system. The orchestrator detects intent, dispatches to specialist agents, and returns a unified advisory.

**Request Body:**

```json
{
  "message": "എവിടെ മത്സ്യം?",
  "lat": 9.9312,
  "lon": 76.2673,
  "session_id": "abc-123"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | Yes | User query in any of 22 supported languages |
| `lat` | number | No | GPS latitude (WGS84). If omitted, extracted from text |
| `lon` | number | No | GPS longitude (WGS84). If omitted, extracted from text |
| `session_id` | string | No | Multi-turn session ID for conversation memory |

**Response:**

```json
{
  "reply": "Fish found 12km NE of Kochi at Pallithottam. Wave height 0.8m, wind 8 knots — safe to go.",
  "map": {
    "center": [76.38, 9.95],
    "pfz_features": [...],
    "route": [[76.27, 9.93], [76.38, 9.95]]
  },
  "safety": {
    "waves_m": 0.8,
    "wind_kts": 8,
    "danger": "none",
    "badge": "green"
  },
  "evidence": [
    "INCOIS TextData SEC005 KERALA 02-Sep-2026",
    "Wave: OSF 06Z forecast",
    "No EEZ/MPA violation"
  ],
  "language": "ml",
  "confidence": 0.87
}
```

**Status Codes:**
- `200` — Success
- `400` — Invalid request (missing message)
- `422` — Validation error
- `500` — Agent processing error

---

## GET /api/weather/current

Returns current weather conditions at a marine point. Data sourced from IMD (Week 2+) with mock data for MVP.

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `lat` | number | Yes | Latitude (WGS84) |
| `lon` | number | Yes | Longitude (WGS84) |

**Response:**

```json
{
  "lat": 9.93,
  "lon": 76.27,
  "wind_speed_kts": 8,
  "wind_direction": "NW",
  "wave_height_m": 0.8,
  "wave_period_s": 6,
  "visibility_km": 10,
  "source": "mock",
  "timestamp": "2026-09-02T12:00:00+05:30"
}
```

**Status Codes:**
- `200` — Success (may return mock data in MVP)
- `400` — Missing lat/lon parameters
- `502` — IMD upstream unavailable

---

## POST /api/geofence/check

Check if a geographic point falls within restricted zones (EEZ or MPA boundaries).

**Request Body:**

```json
{
  "lat": 9.93,
  "lon": 76.27
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `lat` | number | Yes | Latitude (WGS84) |
| `lon` | number | Yes | Longitude (WGS84) |

**Response:**

```json
{
  "inside_eez": true,
  "inside_mpa": false,
  "eez_country": "India",
  "nearest_mpa": null,
  "distance_to_mpa_km": null,
  "restricted": false
}
```

**Status Codes:**
- `200` — Success
- `400` — Missing lat/lon
- `503` — PostGIS unavailable

---

## Error Response Format

All error responses follow this format:

```json
{
  "error": "descriptive_error_code",
  "message": "Human-readable description of what went wrong",
  "details": {}
}
```

---

## Rate Limiting

Not implemented in MVP. Production deployment will add rate limiting per API key.

## Versioning

API version is embedded in the URL path (`/api/...`). Breaking changes will increment the version prefix.
