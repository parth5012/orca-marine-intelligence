# ORCA — API Endpoints

**Base URL:** `http://localhost:8000` (development) or `https://orca-marine-intelligence-api.onrender.com` (production)

**Spec version:** 0.1.0 · **Framework:** FastAPI (`backend/main.py`) · **Mounted** `backend/main.py:48-53`

**Authentication:** None for MVP. API key authentication planned for production.

**CORS:** Configured via `ALLOWED_ORIGINS` environment variable. Default allows `http://localhost:3000` and `https://cron-system.vercel.app`.

**Content Types:** All endpoints accept and return `application/json` unless noted otherwise (`GET /api/tiles/*.pbf` → `application/x-protobuf`, `POST /api/chat/stream` → `text/event-stream`).

---

## Route Summary

| # | Method | Path | Tag | Frontend Consumer | Priority |
|---|--------|------|-----|-------------------|----------|
| 1 | `GET` | `/health` | `system` | App shell (`frontend/app/page.tsx`) Render/Vercel probe · `backend/main.py:56` | **P0** |
| 2 | `GET` | `/api/pfz/today` | `pfz` | `frontend/app/api/pfz/route.ts:22` → `MapView.tsx:28` + `frontend/app/map/page.tsx:13` · `backend/routers/pfz.py:30` | **P0** |
| 3 | `GET` | `/api/pfz/history` | `pfz` | History slider (post-MVP) · `backend/routers/pfz.py:125` | P2 |
| 4 | `GET` | `/api/tiles/{z}/{x}/{y}.pbf` | `tiles` | `MapView.tsx:29` EEZ/MPA layers (MapLibre/Leaflet) · `backend/routers/tiles.py:29` | **P0** (W2) |
| 5 | `POST` | `/api/chat` | `chat` | `ChatPanel.tsx:24`, `useSSEChat.ts:270` **primary SSE stream** · `backend/routers/chat.py:53` | **P0** |
| 6 | `POST` | `/api/chat/stream` | `chat` | `ChatPanel.tsx:14` alias for `POST /api/chat` (SSE stream) · `backend/routers/chat.py:54` | **P0** |
| 7 | `GET` | `/api/chat/history` | `chat` | `ChatPanel.tsx:27` multi-turn (`session_id`) · `backend/routers/chat.py:137` | **P0** |
| 8 | `POST` | `/api/chat/voice` | `chat` | `useSSEChat.ts:587` Vernacular voice transcription (Groq Whisper) · `backend/routers/chat.py:152` | P1 |
| 9 | `GET` | `/api/weather/current` | `weather` | `SafetyBadge.tsx:24` · `backend/routers/weather.py:79` | P1 |
| 10 | `GET` | `/api/weather/cyclone` | `weather` | `SafetyBadge.tsx` + `DangerAgent` · `backend/routers/weather.py:167` | P1 |
| 11 | `POST` | `/api/geofence/check` | `geofence` | `SafetyBadge.tsx:20` chat `danger` · `backend/routers/geofence.py:31` | P1 |
| 12 | `POST` | `/api/geofence/route` | `geofence` | `MapView.tsx:32` route safety · `backend/routers/geofence.py:39` | P1 |

P0 = app broken without it. P1 = safety/UX degraded. P2 = post-MVP.

> **Next.js proxy (not FastAPI but required):** `GET /api/pfz` `frontend/app/api/pfz/route.ts:22` — server-side fetch of `GET /api/pfz/today`, cached 6h via `unstable_cache`, serves stale `data/pfz-today.geojson` on backend down. Fixes INCOIS CORS.

---

## GET /health

Health check endpoint for monitoring and deployment verification. Frontend calls on mount in `frontend/app/page.tsx` (30s interval); shows degraded banner on `503`.

**File:** `backend/main.py:56`

**Response `200`:**

```json
{
  "status": "ok",
  "service": "orca-marine-intelligence"
}
```

**Status Codes:**
- `200` — Service is healthy
- `503` — Service is unhealthy (PostGIS or Redis unreachable — TODO: add checks)

---

## GET /api/pfz/today

Returns today's Potential Fishing Zone data as a GeoJSON FeatureCollection. Single shared list all 4 agents read (`docs/ORCA_GeoJSON_Architecture.md:99`). Data is sourced from INCOIS TextData and cached in Redis for 6 hours. Never call INCOIS from browser — this proxy fixes CORS.

**File:** `backend/routers/pfz.py:30`

**Cache:** Redis `pfz:today` 6h TTL → PostGIS → `data/pfz-today.geojson` fallback.

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sector` | string | No | Filter by sector name (e.g., "KERALA", "GUJARAT" / SEC005) |
| `max_distance_km` | number | No | Maximum distance from coast in km (default: 100) |
| `bbox` | string | No | Viewport culling: `minLon,minLat,maxLon,maxLat` |

**Response `200` (`application/geo+json`):**

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

**Frontend:** `MapView.tsx:28` draws `CircleMarker` per feature, popup shows `place/bearing/distance/depth/citation`.

**Status Codes:**
- `200` — Success
- `502` — INCOIS upstream unavailable (returns cached data if available)
- `503` — Database unavailable

---

## GET /api/pfz/history

Historical PFZ data for slider (post-MVP).

**File:** `backend/routers/pfz.py:125`

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `days` | integer | No | Last N days, 1-30 (default: 7, max: 30) |
| `sector` | string | No | Optional INCOIS sector code or name filter (e.g. SEC005 or KERALA) |
| `limit` | integer | No | Max number of historical features to return (default: 500, max: 5000) |

**Response `200` (PostGIS Real History):**

```json
{
  "type": "FeatureCollection",
  "days": 7,
  "sector": "SEC005",
  "start_date": "2026-08-31",
  "end_date": "2026-09-07",
  "source": "postgis",
  "snapshots": [
    {
      "date": "2026-09-07",
      "count": 2,
      "features": [...]
    }
  ],
  "features": [...],
  "count": 2
}
```

**Response `200` (DB-Empty — no synthetic data):**

```json
{
  "type": "FeatureCollection",
  "days": 7,
  "sector": null,
  "start_date": "2026-08-31",
  "end_date": "2026-09-07",
  "source": "postgis-empty",
  "warning": "No historical records found in database; returning empty history (no synthetic data).",
  "snapshots": [],
  "features": [],
  "count": 0
}
```

---

## GET /api/tiles/{z}/{x}/{y}.pbf

Returns vector tiles (Mapbox Vector Tile format) for map rendering. Used by MapLibre/Leaflet on the frontend for efficient spatial data display. W1 `MapView` fetches full GeoJSON; W2 switches to tiles (critical for 2G at sea).

**File:** `backend/routers/tiles.py:29`

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `z` | integer | Zoom level (0-24) |
| `x` | integer | Tile x coordinate |
| `y` | integer | Tile y coordinate |

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `layer` | string | No | Tile layer: "pfz", "eez", "mpa", or "recommendation" (default: "pfz") |

**Response:** `application/x-protobuf` (MVT format), `Cache-Control: public, max-age=3600`, `Access-Control-Allow-Origin: *`, `X-Tile-Fallback: true` (on DB/Redis fallback)

**Impl:** `SELECT ST_AsMVT(...)` from PostGIS + Redis tile cache 1h (`tiles:{layer}:{z}/{x}/{y}`).

**Status Codes:**
- `200` — Success
- `400` — Invalid tile coordinates
- `503` — PostGIS unavailable

---

## POST /api/chat

Send a conversational query to the ORCA multi-agent system and receive a live Server-Sent Events (`text/event-stream`) stream. The orchestrator detects intent, coordinates specialist agents (planner, fish finder, sea checker, weather agent, danger agent), streams reasoning updates and token chunks, and delivers unified advisory with map features, safety evaluations, and citations.

*Note: `POST /api/chat/stream` is a direct alias for `POST /api/chat` with identical streaming behavior.*

**File:** `backend/routers/chat.py:53`

**Headers:**
```
Content-Type: application/json
Accept: text/event-stream
```

**Request Body:**

```json
{
  "message": "എവിടെ മത്സ്യം?",
  "lat": 9.9312,
  "lon": 76.2673,
  "session_id": "abc-123",
  "language": "ml"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | Yes | User query in any of the 22 supported languages |
| `lat` | number | No | GPS latitude (WGS84) |
| `lon` | number | No | GPS longitude (WGS84) |
| `session_id` | string | No | Multi-turn session ID for conversation memory (Redis). Generated if omitted. |
| `language` | string | No | Preferred response language code (default: `"en"`) |

**Response Headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**SSE Event Framing:**

Each frame is emitted as:
```
event: <type>
data: <JSON>

```

| `type` | When | Payload | Frontend Action |
|--------|------|---------|-----------------|
| `status` | Agent start/step | `{"type":"status","agent":"planner","state":"running","elapsed_ms":123}` | Show agent progress indicator |
| `token` | Text reply chunk | `{"type":"token","text":"Fish found "}` | Append streaming text bubble |
| `map` | Spatial analysis | `{"type":"map","center":[76.26,9.93],"pfz_features":[...],"route":[[76.27,9.93],[76.38,9.95]]}` | `onMapHighlight` → flyTo and draw route |
| `safety` | Marine evaluation | `{"type":"safety","waves_m":0.8,"wind_kts":8,"danger":"none","badge":"green"}` | Update `SafetyBadge` (green/amber/red) |
| `evidence` | Data citations | `{"type":"evidence","items":["INCOIS SEC005 KERALA 02-Sep-2026"]}` | Render citation footer |
| `done` | Stream complete | `{"type":"done","language":"ml","confidence":0.87,"session_id":"abc-123","reply":"..."}` | Close stream, persist `session_id` |
| `error` | Agent error | `{"type":"error","agent":"orchestrator","message":"error description"}` | Show error state |

`safety.badge` is `green` (wave <1.5m, wind <15kt, allowed), `amber` (1.5-2.5m / 15-25kt), `red` (>2.5m / >30kt forbidden).

**Status Codes:**
- `200` — Stream initiated (`text/event-stream`)
- `422` — Validation error (missing required `message` field)

---

## POST /api/chat/stream

Alias for `POST /api/chat`. Maintained for explicit SSE client routing.

**File:** `backend/routers/chat.py:54`

Accepts identical request body, headers, and emits identical SSE frames as `POST /api/chat`.

---

## GET /api/chat/history

Retrieve conversation history for a session from Redis (mandated for multi-turn refinement).

**File:** `backend/routers/chat.py:137`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Multi-turn conversation session ID |
| `limit` | integer | No | Max number of conversation turns (default: 10, min: 1, max: 100) |

**Response `200`:**

```json
{
  "session_id": "abc-123",
  "messages": [
    {
      "role": "user",
      "content": "Where is fish today?",
      "timestamp": "2026-09-02T11:30:00Z"
    },
    {
      "role": "assistant",
      "content": "Fish found 12km off Kochi...",
      "timestamp": "2026-09-02T11:30:05Z"
    }
  ]
}
```

**Status Codes:**
- `200` — Success
- `422` — Validation error (missing `session_id` or invalid `limit`)

---

## POST /api/chat/voice

Ingest vernacular voice audio, transcribe via Groq Whisper (`whisper-large-v3`), and return transcription with session continuity. When `GROQ_API_KEY` is not configured or upstream fails, gracefully falls back to mock transcription with `mock: true`.

**File:** `backend/routers/chat.py:152`

**Content-Type:** `multipart/form-data`

**Form Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file` | File | Required* | Audio file (`.wav`, `.m4a`, `.mp3`, etc.). *Either `file` or `audio` must be provided. |
| `audio` | File | Required* | Alternative form field for audio file. |
| `session_id` | string | No | Multi-turn session ID for conversation continuity. Generated if omitted. |
| `lat` | number | No | GPS latitude (WGS84). |
| `lon` | number | No | GPS longitude (WGS84). |
| `language` | string | No | Language hint for Whisper transcription (default: `"en"`). |

**Response `200` (live transcription):**

```json
{
  "transcription": "എവിടെ മത്സ്യം കിട്ടും? (Where is fish available?)",
  "session_id": "voice-sess-1",
  "mock": false
}
```

**Response `200` (fallback / missing GROQ_API_KEY):**

```json
{
  "transcription": "Transcribed vernacular query from voice.wav",
  "session_id": "voice-sess-1",
  "mock": true
}
```

**Status Codes:**
- `200` — Transcription successful (or mock fallback)
- `413` — Payload Too Large: Audio file exceeds maximum limit of 25MB (`25 * 1024 * 1024` bytes)
- `422` — Unprocessable Entity: Missing audio file (neither `file` nor `audio` provided)

---
## GET /api/weather/current

Returns current live weather and marine conditions for a point. Combines OpenWeatherMap API / Open-Meteo Weather with Open-Meteo Marine API, cached in Redis with a 30-minute TTL.

**File:** `backend/routers/weather.py:79`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `lat` | number | Yes | Latitude in degrees (-90.0 to 90.0) |
| `lon` | number | Yes | Longitude in degrees (-180.0 to 180.0) |

**Cache:** Redis 30-minute TTL (`weather:current:{round(lat, 2)}:{round(lon, 2)}`)

**Response `200`:**

```json
{
  "lat": 9.93,
  "lon": 76.26,
  "temperature_c": 28.0,
  "humidity_pct": 75.0,
  "pressure_hpa": 1012.0,
  "wind_speed_kt": 10.0,
  "wind_speed_kts": 10.0,
  "wind_gust_kt": 13.0,
  "wind_direction": "NW",
  "wave_height_m": 1.2,
  "wave_period_s": 7.0,
  "swell_wave_height_m": 0.8,
  "swell_wave_period_s": 6.5,
  "current_speed_kt": 1.0,
  "status": "safe",
  "source": "live+live",
  "cached": false
}
```

Composite safety `status` classification:
- `danger`: `wind_speed_kt > 25.0` or `wave_height_m > 2.5` or `current_speed_kt > 2.5` or `pressure_hpa < 995.0`
- `caution`: `wind_speed_kt > 15.0` or `wave_height_m > 1.5` or `current_speed_kt > 1.5` or `pressure_hpa < 1005.0`
- `safe`: otherwise

**Status Codes:**
- `200` — Success (`cached: true` if served from Redis 30m cache)
- `400` — Invalid coordinates: `lat` must be in [-90, 90] and `lon` in [-180, 180]
- `422` — Validation error: Missing `lat`/`lon` or non-numeric parameter
- `502` — Bad Gateway: Failed retrieving live weather data from upstream providers

---

## GET /api/weather/cyclone

Returns active cyclone warnings and coastal barometric pressure anomalies. Evaluates IMD bulletins and coastal pressure thresholds (<995 hPa).

**File:** `backend/routers/weather.py:167`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `lat` | number | No | Optional latitude for point-specific cyclone evaluation (-90.0 to 90.0) |
| `lon` | number | No | Optional longitude for point-specific cyclone evaluation (-180.0 to 180.0) |

*Note: If checking a specific location, both `lat` and `lon` must be provided together.*

**Cache:** Redis 30-minute TTL (`weather:cyclone:{round(lat, 2)}:{round(lon, 2)}` or `weather:cyclone:coastal`)

**Response `200` (safe / no cyclone):**

```json
{
  "alert_level": "safe",
  "nearest_cyclone_distance_km": null,
  "max_wind_speed_kt": null,
  "description": "No active cyclone alerts or pressure anomalies detected in Indian coastal waters.",
  "regions_affected": [],
  "last_updated": "2026-09-07T12:00:00Z",
  "active": false,
  "nearest_cyclone_km": null
}
```

**Response `200` (active warning):**

```json
{
  "alert_level": "warning",
  "nearest_cyclone_distance_km": 120.0,
  "max_wind_speed_kt": 45.0,
  "description": "Deep depression intensifying into cyclonic storm off Odisha coast.",
  "regions_affected": ["Odisha", "West Bengal"],
  "last_updated": "2026-09-07T12:00:00Z",
  "active": true,
  "nearest_cyclone_km": 120.0
}
```

`alert_level` values: `safe`, `advisory`, `warning`, `severe`.

**Status Codes:**
- `200` — Success (cached in Redis with 30m TTL)
- `400` — Invalid coordinates (out of range, NaN, or only one of `lat`/`lon` provided)
- `422` — Validation error: Non-numeric parameter
- `502` — Bad Gateway: Failed retrieving cyclone warnings from upstream providers

---

## POST /api/geofence/check

Check if a geographic point falls within restricted zones (EEZ or MPA boundaries).

**File:** `backend/routers/geofence.py:31`

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

**Response `200`:**

```json
{
  "inside_eez": true,
  "inside_mpa": false,
  "eez_country": "India",
  "nearest_mpa": null,
  "distance_to_mpa_km": null,
  "near_imbl": false,
  "distance_to_imbl_km": 12.4,
  "restricted": false
}
```

`restricted = inside_mpa || near_imbl(<2km) || cyclone`. Impl: PostGIS `ST_Contains(eez_boundaries.geom, point)` + `ST_DWithin(mpa, 0)` + `ST_Distance(IMBL)`.

**Status Codes:**
- `200` — Success
- `400` — Missing lat/lon
- `503` — PostGIS unavailable

---

## POST /api/geofence/route

Check if a route crosses any restricted zones. Used to draw warning on `MapView` polyline.

**File:** `backend/routers/geofence.py:39`

**Request Body:**

```json
{ "route": [[76.27, 9.93], [76.38, 9.95]], "format": "lonlat" }
```
or GeoJSON `{"type":"LineString","coordinates":[[76.27,9.93],...]}`

**Response `200`:**

```json
{ "crosses_mpa": false, "crosses_eez_boundary": false, "crosses_imbl": false, "intersections": [], "safe": true }
```

If not safe: `"intersections": [{"zone":"Vembanad MPA","at":[76.3,9.94]}]`.

**Status Codes:**
- `200` — Success
- `400` — Invalid GeoJSON
- `503` — PostGIS unavailable

---

## Frontend Call Map

| Frontend File | Calls |
|---------------|-------|
| `frontend/app/page.tsx:32` | `GET /health`, `POST /api/chat/stream`, `GET /api/pfz/today` (via proxy) |
| `frontend/chat/ChatPanel.tsx:24` | `POST /api/chat/stream` (primary), `POST /api/chat` (fallback), `GET /api/chat/history`, `POST /api/chat/voice` |
| `frontend/chat/bhashini.ts:41` | **Direct** to Bhashini ULCA (not via backend) |
| `frontend/map/MapView.tsx:28` | `GET /api/pfz/today` via `frontend/app/api/pfz/route.ts:22`, `GET /api/tiles/{z}/{x}/{y}.pbf?layer=` |
| `frontend/map/SafetyBadge.tsx` | Props from chat `safety` + direct `GET /api/weather/current`, `POST /api/geofence/check` |
| `frontend/app/map/page.tsx:13` | `GET /api/pfz/today` standalone |

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

Codes: `invalid_request`, `validation_error`, `upstream_unavailable`, `db_unavailable`, `agent_timeout`.

---

## Wiring Checklist for `backend/main.py`

```python
from backend.routers import pfz, tiles, chat, weather, geofence
app.include_router(pfz.router, prefix="/api")
app.include_router(tiles.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(geofence.router, prefix="/api")
# CORS
app.add_middleware(CORSMiddleware,
  allow_origins=os.getenv("ALLOWED_ORIGINS","http://localhost:3000,https://cron-system.vercel.app").split(","),
  allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
```

---

## Rate Limiting

Not implemented in MVP. Production deployment will add rate limiting per API key.

## Versioning

API version is embedded in the URL path (`/api/...`). Breaking changes will increment the version prefix.

---

*Merged from `docs/BACKEND_ROUTES.md` — covers 11 backend routes (10 FastAPI + 1 Next.js proxy) required for full frontend operation. `POST /api/chat/stream` is the only route not yet scaffolded and must be added before `ChatPanel` SSE works. See also `docs/ORCA_GeoJSON_Architecture.md`, `docs/ORCA_Codebase_Guide.md`.*
