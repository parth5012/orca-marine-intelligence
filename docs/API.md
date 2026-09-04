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
| 1 | `GET` | `/health` | `system` | App shell (`frontend/app/page.tsx`), Render/Vercel probe · `backend/main.py:56` | **P0** |
| 2 | `GET` | `/api/pfz/today` | `pfz` | `frontend/app/api/pfz/route.ts:22` → `MapView.tsx:28` + `frontend/app/map/page.tsx:13` · `backend/routers/pfz.py:30` | **P0** |
| 3 | `GET` | `/api/pfz/history` | `pfz` | History slider (post-MVP) · `backend/routers/pfz.py:37` | P2 |
| 4 | `GET` | `/api/tiles/{z}/{x}/{y}.pbf` | `tiles` | `MapView.tsx:29` EEZ/MPA layers (MapLibre/Leaflet) · `backend/routers/tiles.py:29` | **P0** (W2) |
| 5 | `POST` | `/api/chat` | `chat` | `ChatPanel.tsx:24` fallback / curl / tests · `backend/routers/chat.py:49` | **P0** |
| 6 | `POST` | `/api/chat/stream` | `chat` | `ChatPanel.tsx:14` **primary SSE** · `backend/routers/chat.py` (new) | **P0** |
| 7 | `GET` | `/api/chat/history` | `chat` | `ChatPanel.tsx:27` multi-turn (`session_id`) · `backend/routers/chat.py:56` | **P0** |
| 8 | `GET` | `/api/weather/current` | `weather` | `SafetyBadge.tsx:24` · `backend/routers/weather.py:30` | P1 |
| 9 | `GET` | `/api/weather/cyclone` | `weather` | `SafetyBadge.tsx` + `DangerAgent` · `backend/routers/weather.py:37` | P1 |
| 10 | `POST` | `/api/geofence/check` | `geofence` | `SafetyBadge.tsx:20` + chat `danger` · `backend/routers/geofence.py:31` | P1 |
| 11 | `POST` | `/api/geofence/route` | `geofence` | `MapView.tsx:32` route safety · `backend/routers/geofence.py:39` | P1 |

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

**File:** `backend/routers/pfz.py:37`

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `days` | integer | No | Last N days (default: 7) |
| `sector` | string | No | Filter by sector |
| `page` / `limit` | integer | No | Pagination |

**Response `200`:**

```json
{
  "days": [
    { "date": "2026-09-02", "type": "FeatureCollection", "features": [...] }
  ],
  "total": 7
}
```

---

## GET /api/tiles/{z}/{x}/{y}.pbf

Returns vector tiles (Mapbox Vector Tile format) for map rendering. Used by MapLibre/Leaflet on the frontend for efficient spatial data display. W1 `MapView` fetches full GeoJSON; W2 switches to tiles (critical for 2G at sea).

**File:** `backend/routers/tiles.py:29`

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

**Response:** `application/x-protobuf` (MVT format), `Cache-Control: public, max-age=3600`, `Access-Control-Allow-Origin: *`

**Impl:** `SELECT ST_AsMVT(...)` from PostGIS + Redis tile cache 1h.

**Status Codes:**
- `200` — Success
- `400` — Invalid tile coordinates
- `503` — PostGIS unavailable

---

## POST /api/chat

Send a conversational query to the ORCA multi-agent system (non-streaming fallback for tests/curl/non-SSE clients). The orchestrator detects intent, dispatches to specialist agents, and returns a unified advisory.

**File:** `backend/routers/chat.py:49`

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
| `lat` | number | No | GPS latitude (WGS84). If omitted, extracted from text via `frontend/map/geo.ts:47` or place table |
| `lon` | number | No | GPS longitude (WGS84). If omitted, extracted from text |
| `session_id` | string | No | Multi-turn session ID for conversation memory (Redis) |

**Response `200`:**

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
  "confidence": 0.87,
  "session_id": "abc-123"
}
```

`safety.badge`: `green` (wave <1.5m, wind <15kt, allowed), `amber` (1.5-2.5m or 15-25kt), `red` (>2.5m or >30kt or forbidden). On agent timeout, `confidence` downgrades 0.87→0.62 with partial result.

**Status Codes:**
- `200` — Success
- `400` — Invalid request (missing message)
- `422` — Validation error
- `500` — Agent processing error (partial results still returned)

---

## POST /api/chat/stream

**Primary endpoint for `ChatPanel.tsx:14` SSE streaming. Without it, UI blocks 2-8s until `orchestrator.py:34` `asyncio.gather` (4 agents) + `combiner.py:12` ranking completes, and `onMapHighlight` never fires early.**

**File:** `backend/routers/chat.py` (new — add `stream` handler alongside `POST /api/chat`)

**Request:** Same JSON as `POST /api/chat`.

**Headers:**
```
Content-Type: application/json
Accept: text/event-stream
```

**Response headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**SSE Event Schema** — each frame is `data: <JSON>\n\n` (optionally `event: <type>\n`):

| `type` | When | Payload | Frontend Action |
|--------|------|---------|-----------------|
| `status` | Agent start/done | `{"type":"status","agent":"planner|fish_finder|sea_checker|weather_agent|danger_agent|parallel_analysis|decision_agent","state":"running|done|timeout","elapsed_ms":123}` | Show spinner in `ChatPanel` |
| `token` | Reply chunk (Bhashini-translated) | `{"type":"token","text":"Pallithottam "}` | Append to streaming bubble |
| `map` | Combiner picks winner | `{"type":"map","center":[76.167,8.555],"pfz_features":[...],"route":[[76.27,9.93],[76.167,8.555]]}` | `onMapHighlight(features)` → `MapView.tsx:30` flyTo + draw route |
| `safety` | After sea/weather/danger | `{"type":"safety","waves_m":0.8,"wind_kts":8,"danger":"none","badge":"green"}` | Update `SafetyBadge.tsx` |
| `evidence` | Final citations | `{"type":"evidence","items":["INCOIS SEC005 KERALA 02-Sep-2026"]}` | Render citation footer |
| `done` | Stream end | `{"type":"done","language":"ml","confidence":0.87,"session_id":"abc-123"}` | Close stream, persist `session_id` to `localStorage` |
| `error` | Agent timeout/fail | `{"type":"error","agent":"sea_checker","message":"timeout 10s","fallback":"unknown"}` | Downgrade badge to amber, show warning |

**Example stream:**

```
data: {"type":"status","agent":"fish_finder","state":"running"}

data: {"type":"status","agent":"sea_checker","state":"running"}

data: {"type":"token","text":"Fish found "}

data: {"type":"token","text":"12km SW of Kochi."}

data: {"type":"map","center":[76.167,8.555],"pfz_features":[...],"route":[[76.27,9.93],[76.167,8.555]]}

data: {"type":"safety","waves_m":0.8,"wind_kts":8,"danger":"none","badge":"green"}

data: {"type":"done","language":"ml","confidence":0.87,"session_id":"abc-123"}

```

**Frontend consumption** — `EventSource` cannot POST, so use `fetch` + `ReadableStream`:

```ts
const res = await fetch('/api/chat/stream', {
  method: 'POST',
  body: JSON.stringify({ message, lat, lon, session_id }),
  headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' }
});
const reader = res.body!.getReader();
const decoder = new TextDecoder();
let buf = '';
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });
  for (const part of buf.split('\n\n')) {
    if (part.startsWith('data:')) handle(JSON.parse(part.slice(5)));
  }
}
```

**Backend impl sketch:**

```python
from fastapi.responses import StreamingResponse
import json

@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def gen():
        async for event in orchestrator.orchestrate_stream(req.message, req.lat, req.lon, req.session_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

`orchestrator.py:41` must change from `async def orchestrate() -> dict` to `async def orchestrate_stream() -> AsyncGenerator[dict]` yielding `status/token/map/safety/done`.

**Status Codes:**
- `200` — Stream opened (individual agent failures sent as `error` events, not HTTP errors)
- `400` / `422` — Same validation as `POST /api/chat` (before stream starts)

---

## GET /api/chat/history

Retrieve conversation history for a session (PS mandates multi-turn refinement).

**File:** `backend/routers/chat.py:56`

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session ID |
| `limit` | integer | No | Page size (default: 20) |
| `offset` | integer | No | Offset (default: 0) |

**Response `200`:**

```json
{
  "session_id": "abc-123",
  "messages": [
    {"role":"user","message":"എവിടെ മത്സ്യം?","lat":9.93,"lon":76.27,"ts":"2026-09-02T11:30:00+05:30"},
    {"role":"assistant","reply":"...","map":{...},"safety":{...},"ts":"..."}
  ],
  "total": 12
}
```

**Backend:** Redis `save_session`/`get_session` (`backend/db/redis.py`). If Redis down, `503` with hint to resend location.

**Status Codes:**
- `200` — Success
- `400` — Missing session_id
- `503` — Redis unavailable

---

## GET /api/weather/current

Returns current weather conditions at a marine point. Data sourced from IMD (Week 2+) with mock data for MVP.

**File:** `backend/routers/weather.py:30`

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `lat` | number | Yes | Latitude (WGS84) |
| `lon` | number | Yes | Longitude (WGS84) |

**Response `200`:**

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

W1 `source: mock` (0.8m/8kt), W2 IMD `https://mausam.imd.gov.in` + OSF 06Z.

**Status Codes:**
- `200` — Success (may return mock data in MVP)
- `400` — Missing lat/lon parameters
- `502` — IMD upstream unavailable

---

## GET /api/weather/cyclone

Active cyclone warnings within 500km (used by `DangerAgent` and `SafetyBadge`).

**File:** `backend/routers/weather.py:37`

**Response `200` (no cyclone):**

```json
{ "active": false, "warnings": [], "nearest_cyclone_km": null }
```

**Response `200` (active):**

```json
{
  "active": true,
  "warnings": [{ "name": "Asna", "center": [12.5, 65.0], "distance_km": 320, "severity": "danger" }]
}
```

**Status Codes:**
- `200` — Success
- `502` — IMD upstream unavailable

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
| `frontend/chat/ChatPanel.tsx:24` | `POST /api/chat/stream` (primary), `POST /api/chat` (fallback), `GET /api/chat/history` |
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
