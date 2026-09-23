# ORCA — API Endpoints

**Base URL:** `http://localhost:8000` (development) or `https://orca-marine-intelligence-api.onrender.com` (production)

**Spec version:** 0.1.0 · **Framework:** FastAPI (`backend/main.py`) · **Mounted** `backend/main.py:226-230`

**Authentication:** None for MVP. API key authentication planned for production.

**CORS:** Configured via `ALLOWED_ORIGINS` environment variable (`backend/main.py:55,211`). Default allows `http://localhost:3000` and `https://cron-system.vercel.app`.

**Content Types:** All endpoints accept and return `application/json` unless noted otherwise (`GET /api/tiles/*.pbf` returns `application/x-protobuf`, `POST /api/chat` returns `text/event-stream`).

**Fetch strategy (T5 rule, map #92):** reads that must survive backend-down go through Next.js proxies; only PFZ has a local-file fallback (`data/pfz-today.geojson`). The chat proxies are transport-only — the Next.js `POST /api/chat` proxy returns 504 when the backend is unavailable (the FastAPI route itself returns 200/422 as documented below). Live-only telemetry (weather/current, geofence/status) calls the backend directly. Direct calls rely on `ALLOWED_ORIGINS`; proxies sidestep CORS.

---

## Route Summary

| # | Method | Path | Tag | Frontend Consumer | Priority |
|---|--------|------|-----|-------------------|----------|
| 1 | `GET` | `/health` | `system` | No in-app caller (Render/Vercel probe only) · `backend/main.py:243` | **P0** |
| 2 | `GET` | `/api/pfz/today` | `pfz` | `MapInner.tsx:200` via proxy `GET /api/pfz` · `backend/routers/pfz.py:29` | **P0** |
| 3 | `GET` | `/api/tiles/config` | `tiles` | No UI caller yet (deferred to W2 MVT cutover, T3) · `backend/routers/tiles.py:30` | P2 |
| 4 | `GET` | `/api/tiles/{z}/{x}/{y}.pbf` | `tiles` | No UI caller yet (`MapView` uses raster today; W2 MVT) · `backend/routers/tiles.py:107` | P1 |
| 5 | `POST` | `/api/chat` | `chat` | `useSSEChat.ts:273` direct + `:298` proxy fallback (via `ChatPanel`) · `backend/routers/chat.py:54` | **P0** |
| 6 | `POST` | `/api/chat/voice` | `chat` | `useSSEChat.ts:625` direct + `:644` proxy fallback (via `ChatPanel`) · `backend/routers/chat.py:137` | P1 |
| 7 | `GET` | `/api/weather/current` | `weather` | `MapInner.tsx:227` direct · `backend/routers/weather.py:79` | P1 |
| 8 | `GET` | `/api/weather/cyclone` | `weather` | `DangerAgent` internal only (no UI caller, T3) · `backend/routers/weather.py:170` | P2 |
| 9 | `GET` | `/api/geofence/status` | `geofence` | `frontend/app/map/page.tsx:94` direct · `backend/routers/geofence.py:58` | P1 |
| 10 | `GET` | `/api/officer/overview` | `officer` | `/officer` command view (RBAC `X-User-Role: official`) · `backend/routers/officer.py` | P1 |
| 11 | `POST` | `/api/officer/departures` | `officer` | `/officer` register form · `backend/routers/officer.py` | P1 |
| 12 | `GET` | `/api/officer/departures` | `officer` | `/officer` register table + overdue alerts · `backend/routers/officer.py` | P1 |
| 13 | `POST` | `/api/officer/overrides` | `officer` | `/officer` go-no-go override · `backend/routers/officer.py` | P1 |
| 14 | `GET` | `/api/officer/overrides` | `officer` | `/officer` override log · `backend/routers/officer.py` | P1 |
| 15 | `POST` | `/api/officer/broadcasts` | `officer` | `/officer` broadcast composer · `backend/routers/officer.py` | P1 |
| 16 | `GET` | `/api/officer/broadcasts` | `officer` | `/officer` broadcast history · `backend/routers/officer.py` | P1 |
| 17 | `GET` | `/api/officer/dayclose` | `officer` | `/officer` day-close audit (JSON + CSV) · `backend/routers/officer.py` | P1 |
| 18 | `GET` | `/api/chat/history` | `chat` | No UI caller yet (T6 proxy + T7 hydrate pending) · `backend/routers/chat.py` | P1 |

P0 = app broken without it. P1 = safety/UX degraded. P2 = deferred/internal.

> **Next.js proxies (not FastAPI but required):** `GET /api/pfz` (`frontend/app/api/pfz/route.ts:39`) proxies `GET /api/pfz/today` with 3s timeout, `revalidate: 3600`, and `data/pfz-today.geojson` local fallback (503 when backend and file both unavailable). `POST /api/chat` (`frontend/app/api/chat/route.ts:45`) proxies with 3s timeout and unbuffered SSE passthrough (504 on timeout/unavailable). `POST /api/chat/voice` (`frontend/app/api/chat/voice/route.ts:27`) proxies multipart upload with 10s timeout (504 on timeout/unavailable).

> **Removed in T3 (map #92, human grill):** `POST /api/chat/stream` (unused alias), `GET /api/pfz/history` (post-MVP slider), `GET`+`POST /api/geofence/check`, `POST /api/geofence/route`. All return 404. Tests assert removal. `GET /api/chat/history` (also pruned in T3) **returned in multi-turn map #232 T1** (partial reversal — history returns, `/chat/stream` alias stays deleted).

---

## GET /health

Readiness probe. Returns `ok` only when database AND Redis are connected, otherwise `degraded`. There is no in-app caller (`frontend/app/page.tsx` performs no fetch); Render/Vercel probes hit it directly.

**File:** `backend/main.py:243`

**Response `200` (healthy):**

```json
{
  "status": "ok",
  "service": "orca-marine-intelligence",
  "version": "0.1.0",
  "uptime": 12.5,
  "database": "connected",
  "redis": "connected",
  "data_source": "live",
  "telemetry": { "langsmith": { "enabled": false } }
}
```

`status` is `"degraded"` when either dependency is down. Always HTTP 200 (no 503).

---

## GET /api/pfz/today

Today's Potential Fishing Zone data as a GeoJSON FeatureCollection. Never call INCOIS from the browser — use the `GET /api/pfz` proxy (fixes CORS, adds offline fallback).

**File:** `backend/routers/pfz.py:29`

**Cache:** Redis `pfz:today` 6h TTL, then live INCOIS ingest with Copernicus Marine fallback.

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sector` | string | No | Filter by sector code or name (e.g. `SEC005` or `KERALA`) |
| `bbox` | string | No | Viewport culling: `minLon,minLat,maxLon,maxLat` |
| `limit` | integer | No | Max features (default: 1000, 1-5000) |

**Response `200` (`application/geo+json`):**

```json
{
  "type": "FeatureCollection",
  "valid_until": "2026-09-09T14:00:00+00:00",
  "source": "incois_textdata",
  "sector_count": 4,
  "count": 2,
  "metadata": {
    "valid_until": "2026-09-09T14:00:00+00:00",
    "source": "incois_textdata",
    "sector_count": 4,
    "count": 2
  },
  "features": [
    {
      "type": "Feature",
      "properties": { "zone_id": "SEC005_001", "place": "Pallithottam", "sector": "KERALA" },
      "geometry": { "type": "Point", "coordinates": [76.167, 8.555] }
    }
  ]
}
```

**Frontend:** `MapInner.tsx:200` fetches the `/api/pfz` proxy and draws one `CircleMarker` per feature.

**Status Codes:**
- `200` — Success (empty `features` when upstream and cache both miss)
- `400` — Invalid `bbox` (expected 4 numbers, min <= max)

---

## GET /api/tiles/config

Raster basemap catalog for map clients (CARTO + OSM URL templates, attribution, zoom ranges). No UI caller yet — deferred to the W2 MVT cutover (T3).

**File:** `backend/routers/tiles.py:30`

**Response `200` (`application/json`, `Cache-Control: public, max-age=3600`):**

```json
{
  "status": "success",
  "default_style": "dark_all",
  "carto_key_configured": false,
  "layers": {
    "carto_dark": { "id": "carto_dark", "type": "raster", "url": "https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png" },
    "carto_voyager": { "id": "carto_voyager", "type": "raster", "url": "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png" },
    "carto_positron": { "id": "carto_positron", "type": "raster", "url": "https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png" },
    "osm": { "id": "osm", "type": "raster", "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" }
  },
  "cache": { "max_age_seconds": 3600 }
}
```

---

## GET /api/tiles/{z}/{x}/{y}.pbf

Mapbox Vector Tiles from PostGIS (`ST_AsMVT`) with Redis 1h cache (`tiles:{layer}:{z}/{x}/{y}`). No UI caller yet — `MapView` uses raster today; W2 switches to tiles (critical for 2G at sea).

**File:** `backend/routers/tiles.py:107`

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `z` | integer | Zoom level (0-24, else 400) |
| `x` | integer | Tile x (0 <= x < 2^z, else 400) |
| `y` | integer | Tile y (0 <= y < 2^z, else 400) |

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `layer` | string | No | `pfz` (default), `eez`, `mpa`, or `recommendation`. Unknown values fall back to `pfz` (not an error). |

**Response:** `application/x-protobuf` with `Cache-Control: public, max-age=3600`, `X-Tile-Layer`, `X-Tile-Coords`.

**Status Codes:**
- `200` — Tile bytes (live or Redis-cached)
- `400` — Invalid zoom or tile coordinates
- `503` — PostGIS offline (`text/plain`, `Cache-Control: no-store`, `X-Tile-Fallback: true`; emptiness is never cached)

---

## POST /api/chat

Conversational query to the ORCA multi-agent system as a live Server-Sent Events (`text/event-stream`) stream. Single primary endpoint (the old `/api/chat/stream` alias was deleted in T3).

**File:** `backend/routers/chat.py:54`

**Headers:**
```
Content-Type: application/json
Accept: text/event-stream
```

**Request Body:**

```json
{
  "message": "Where is fish today?",
  "lat": 9.9312,
  "lon": 76.2673,
  "session_id": "abc-123",
  "language": "en"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | Yes | User query |
| `lat` | number | No | GPS latitude (WGS84) |
| `lon` | number | No | GPS longitude (WGS84) |
| `session_id` | string | No | Multi-turn session ID (Redis). Generated if omitted. |
| `language` | string | No | Response language code (default: `"en"`) |

**Response Headers:**
```
Content-Type: text/event-stream
Cache-Control: no-store
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
| `done` | Stream complete | `{"type":"done","language":"en","confidence":0.87,"session_id":"abc-123"}` | Close stream, persist `session_id` |
| `error` | Agent error | `{"type":"error","agent":"orchestrator","message":"error description"}` | Show error state |

`safety.badge` follows `backend/routers/weather.py`: `green` requires wave <1.5m and wind <15kt; `amber` covers wave 1.5-2.5m or wind 15-25kt (boundary values 1.5m, 2.5m, 15kt, 25kt are `amber`); `red` covers wave >2.5m or wind >25kt (including 26-30kt).

### Language & Translation

- **`language`** (string, ISO 639-1): Detected language code from the frontend (`bhashini.ts detectLanguage()`). Default: `"en"`.
- When `language != "en"`, the backend automatically:
  1. Translates the user query from `language` → English (Bhashini Dhruva API)
  2. Runs all agents in English
  3. Translates the final reply from English → `language` in the `done` SSE event
- **Language detection** uses **offline Unicode script-block analysis** in the browser (`frontend/chat/bhashini.ts detectLanguage()`). NOT Bhashini NLP. This is intentional: zero-latency, offline-capable, and sufficient for the 10 distinct Indian scripts supported.
- Translation results are cached in Redis for 1 hour.
- **Fallback**: If Bhashini is unavailable, the English response is served with a `translation_warning` field in the `done` event. The SSE stream never crashes.

#### SSE done event shape (with translation)
```json
{
  "type": "done",
  "reply": "ഏറ്റവും അടുത്ത PFZ സോൺ...",
  "translated": true,
  "original_reply_en": "The nearest PFZ zone is...",
  "session_id": "abc123"
}
```

#### SSE done event shape (translation fallback)
```json
{
  "type": "done",
  "reply": "The nearest PFZ zone is...",
  "translation_warning": "Bhashini translation unavailable — showing English response",
  "session_id": "abc123"
}
```

**Frontend:** `useSSEChat.ts:273` posts direct to the backend, falling back to the `POST /api/chat` Next.js proxy (`:298`) when the direct fetch fails (HTTPS deployments).

**Status Codes:**
- `200` — Stream initiated (`text/event-stream`)
- `422` — Validation error (missing/empty `message`, `message` > 2000 chars, `session_id` > 128 chars)
- `429` — Per-IP rate limit exceeded (`30/min` chat; `Retry-After` header)

**Security notes (#199):** `session_id` is client-controlled but format-validated
(`^[A-Za-z0-9_.-]{1,128}$`; invalid → fresh `uuid4` server-issued). Tradeoff:
no server matching-secret, so a guessed ID could read that session's 24h-TTL
history — mitigated by unguessable `uuid4` defaults + short TTL; full
server-issued secret deferred post-MVP to avoid breaking existing clients.
SSE `error` events carry a generic message only (`Internal chat error; please
retry.`); full tracebacks stay in server logs. Access logs redact
`lat`/`lon`/`session_id` values (PII).

---

## POST /api/chat/voice

Vernacular voice audio transcribed via Bhashini ULCA ASR (2-call Config → Compute flow, `taskType=asr`, 16kHz mono WAV). The backend converts browser `webm/opus` recordings with ffmpeg (`-ac 1 -ar 16000 -sample_fmt s16`); the deploy image must include ffmpeg, otherwise uploads pass through unconverted. There is **no mock fallback**: when Bhashini credentials are missing (`BHASHINI_API_KEY` / `BHASHINI_ULCA_USER_ID`), upstream fails, or no speech is detected, the endpoint returns 503. `GROQ_API_KEY` is planner-only and never used in the voice path.

**File:** `backend/routers/chat.py:137`

**Content-Type:** `multipart/form-data`

**Form Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file` | File | Required* | Audio file (`.wav`, `.m4a`, `.mp3`, etc.). *Either `file` or `audio` must be provided. |
| `audio` | File | Required* | Alternative form field for audio file. |
| `session_id` | string | No | Multi-turn session ID. Generated if omitted. |
| `lat` | number | No | GPS latitude (WGS84). |
| `lon` | number | No | GPS longitude (WGS84). |
| `language` | string | No | Source-language hint for ASR, ISO-639-1 (default: `"en"`; `ml-IN` → `ml`). |

**Response `200`:**

```json
{
  "transcription": "Where is fish available?",
  "session_id": "voice-sess-1",
  "mock": false
}
```

**Frontend:** `useSSEChat.ts:625` posts direct to the backend, falling back to the `POST /api/chat/voice` Next.js proxy (`:644`, 10s timeout, multipart passthrough).

**Status Codes:**
- `200` — Transcription successful (`mock` is always `false`)
- `413` — Audio file exceeds 25MB (`25 * 1024 * 1024` bytes)
- `422` — Missing audio file (neither `file` nor `audio` provided)
- `429` — Per-IP rate limit exceeded (`10/min` voice; `Retry-After` header)
- `503` — Transcription unavailable (missing Bhashini keys, upstream failure, or no speech detected)

**Security notes (#199):** voice is public (no auth — fishing-community
kiosks); abuse contained by the `10/min` per-IP limit + 25MB cap + 255-char
filename sanitization. `language` is normalized (`ml-IN` → `ml`); unknown
codes fall back to `en`.

---

## GET /api/chat/history

Multi-turn conversation history for a session (T1-locked, multi-turn map #232;
partial reversal of the T3 prune — history returns, `POST /api/chat/stream`
stays deleted). Text-only turns for thread reload (T7 hydrate); voice turns
are stored as user text so they appear on reload.

**File:** `backend/routers/chat.py`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Multi-turn session ID (`^[A-Za-z0-9_.-]{1,64}$`; malformed → `400`) |
| `limit` | integer | No | Max turns returned (default `20`, clamped `1..20` backend) |

**Response `200`:**

```json
{
  "session_id": "ab12cd34ef56",
  "count": 2,
  "turns": [
    {"role": "user", "content": "fish near Kochi", "ts": 1758600000.0, "place": "Kochi"},
    {"role": "assistant", "content": "Nearest zone ...", "ts": 1758600001.0}
  ]
}
```

Turns are `{role, content, ts}` plus optional `place`/`zone_id` when stored
(minimal+place). Content is returned verbatim (no re-translate); clarification
turns are plain text. T3 GPS redaction: `lat`/`lon`/`center` numbers are never
included in the payload (place names only); access logs redact `session_id`.

**Frontend:** no UI caller yet (`ChatPanel` has no history fetch; T6 Next.js
`GET /api/chat/history` proxy + T7 `useSSEChat` hydrate pending).

**Status Codes:**
- `200` — Success, including `{count: 0, turns: []}` for unknown/expired sessions (silent empty, 24h Redis TTL)
- `400` — Malformed `session_id` (sanitize fail: missing, empty, or outside `^[A-Za-z0-9_.-]{1,64}$`)
- `429` — Per-IP rate limit exceeded (reuses the `chat` bucket: `30/min`; `Retry-After` header)

---

## GET /api/weather/current

Live weather and marine conditions for a point. Combines OpenWeatherMap / Open-Meteo Weather with Open-Meteo Marine, cached in Redis with a 30-minute TTL.

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

**Frontend:** `MapInner.tsx:227` fetches direct (live telemetry per T5 rule) with a synthetic offline estimate fallback.

**Status Codes:**
- `200` — Success (`cached: true` if served from Redis 30m cache)
- `400` — Invalid coordinates: `lat` must be in [-90, 90] and `lon` in [-180, 180]
- `422` — Validation error: Missing `lat`/`lon` or non-numeric parameter
- `502` — Bad Gateway: upstream providers unavailable after retries

---

## GET /api/weather/cyclone

Active cyclone warnings and coastal pressure anomalies (IMD bulletins, <995 hPa threshold). `DangerAgent` internal only — no UI caller (T3 grill decision).

**File:** `backend/routers/weather.py:170`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `lat` | number | No | Optional latitude (-90.0 to 90.0). Must be provided together with `lon`. |
| `lon` | number | No | Optional longitude (-180.0 to 180.0). Must be provided together with `lat`. |

**Cache:** Redis 30-minute TTL (`weather:cyclone:{round(lat, 2)}:{round(lon, 2)}` or `weather:cyclone:coastal`)

**Response `200` (no cyclone):**

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

`alert_level` values: `safe`, `advisory`, `warning`, `severe`. `active` is true for `warning`/`severe`; `nearest_cyclone_km` mirrors `nearest_cyclone_distance_km`.

**Status Codes:**
- `200` — Success (cached in Redis with 30m TTL)
- `400` — Invalid coordinates (out of range, NaN, or only one of `lat`/`lon` provided)
- `422` — Validation error: Non-numeric parameter
- `502` — Bad Gateway: upstream providers unavailable

---

## GET /api/geofence/status

Active Marine Protected Areas, sovereign EEZ zones, and IMBL buffer thresholds with boundary counts.

**File:** `backend/routers/geofence.py:58`

**Response `200` (`GeofenceStatusResponse`):**

```json
{
  "status": "ok",
  "active_mpas": ["Vembanad", "Gulf of Mannar"],
  "eez_zones": ["West Coast EEZ", "East Coast EEZ"],
  "imbl_buffer_km": 2.0,
  "imbl_caution_threshold_km": 5.0,
  "eez_caution_threshold_km": 10.0,
  "count_protected_boundaries": 4,
  "protected_boundaries_count": 4,
  "boundary_counts": { "eez": 2, "mpa": 2, "total": 4 }
}
```

**Frontend:** `frontend/app/map/page.tsx:94` fetches direct (fire-and-forget; backend offline keeps local boundaries). Per-point checks and route validation were deleted in T3 — the drawer shows static clearance copy.

---

## Officer Register (Map #170 T2)

Manual departure register, GO/HOLD overrides, and advisory broadcasts for `/officer`. **File:** `backend/routers/officer.py` (mounted `backend/main.py`, same `/api` prefix + CORS as all routers). Runtime store is in-memory (green without Postgres); prod tables in `backend/db/schema.sql` §7 + `backend/db/models.py` §6. Identical under `ORCA_DATA_SOURCE` live/mock (local-first, no upstream fetch).

**Auth:** shared tokens, no user table. `PORT_TOKEN` = port-officer role (every read must scope `?port_id=`; writes must include `port_id`). `WATCH_TOKEN` = enforcement/watch role (read-all; writes allowed with `by_role: "watch"`). Sent as `X-Officer-Token` header (the Next.js password screen keeps `officer_role` in an httpOnly cookie — see `OFFICER_COOKIE` in `.env.example` — and the proxy forwards it as the header). `port_id` is validated against `data/ports.json` via `backend/core/ports.py`; unknown ids return 400.

**`401` shape (missing/wrong token, all 6 endpoints):**

```json
{ "detail": "Invalid or missing X-Officer-Token." }
```

**`400` shapes:** `{ "detail": "port_id query param required for port role." }` (port role read without `?port_id=`), `{ "detail": "Unknown port_id: <id>." }`.

### POST /api/officer/departures

```json
{ "port_id": "kochi", "boat_id": "KL-07-MM-1234", "crew": 5, "time_out": "2026-09-18T06:00:00+00:00", "expected_in": "2026-09-18T14:00:00+00:00", "dest_lat": 9.5, "dest_lon": 76.0, "dest_zone": "SEC005", "status": "at_sea" }
```

Response `200`: created row (`id`, `created_at`) plus computed `overdue_mins` (int) and `overdue_status` (`none`/`amber` >120min/`red` >360min).

### GET /api/officer/departures?port_id=kochi

Response `200`: `{ "count": 1, "departures": [{ ...row, "overdue_mins": 0, "overdue_status": "none" }] }`. `overdue_*` is computed per read, never stored. Watch role may omit `port_id` (returns all ports).

### POST /api/officer/overrides

```json
{ "port_id": "kochi", "date": "2026-09-18", "decision": "GO", "reason": "Seas calm, PFZ active" }
```

`decision` is `GO`/`HOLD` (else 422). `by_role` is derived from the token, never the client. Response `200`: created row with `id`, `by_role`, `created_at`.

### GET /api/officer/overrides?port_id=kochi&date=2026-09-18

Both filters optional for watch (`port_id` required for port role). Response `200`: `{ "count": 1, "overrides": [...] }`.

### POST /api/officer/broadcasts

```json
{ "port_id": "kochi", "text_en": "Stay within 12nm today", "text_local": "ഇന്ന് 12 നോട്ടിക്കൽ മൈലിനുള്ളിൽ", "lang": "ml" }
```

Response `200`: created row with `id`, `created_at`.

### GET /api/officer/broadcasts?port_id=kochi

Response `200`: `{ "count": 1, "broadcasts": [...] }`. Watch role may omit `port_id` (returns all ports). History returns the 20 latest (newest first); `count` is the total. Postgres is the source of truth (no Redis history, no auto-send).

### GET /api/officer/dayclose?port_id=kochi&date=2026-09-18

Per-port per-date audit summary for the `/officer` day-close card (T6 #176). **File:** `backend/routers/officer.py`. Auth is the same `X-Officer-Token` scheme (port role requires `?port_id=`; watch may omit it and gets `port_id: "all"` aggregated). `date` defaults to today (UTC); invalid `YYYY-MM-DD` returns 400.

Response `200` (`application/json`, locked keys — CSV header is exactly these):

```json
{
  "port_id": "kochi",
  "date": "2026-09-18",
  "departures": 2,
  "holds": 1,
  "overdues_resolved": 1,
  "mpa_hits": 0,
  "broadcasts": 1
}
```

Semantics: `departures` counts rows whose `time_out` falls on `date`; `holds` counts overrides with `decision: HOLD` on `date`; `overdues_resolved` counts in-scope departures with `status: returned`; `mpa_hits` reuses the T5 `compute_geofence_flag` helper (`mpa` priority); `broadcasts` counts broadcasts created on `date`.

`?format=csv` returns the same summary as `text/csv` (header row + one data row, EN header, `Content-Disposition: attachment`):

```csv
port_id,date,departures,holds,overdues_resolved,mpa_hits,broadcasts
kochi,2026-09-18,2,1,1,0,1
```

**Status Codes:** `200` (JSON or CSV) · `400` (port role without `?port_id=`, unknown `port_id`, invalid `date`) · `401` (`{ "detail": "Invalid or missing X-Officer-Token." }`).

---

## Frontend Call Map (verified against code)

| Frontend File | Calls |
|---------------|-------|
| `frontend/map/MapInner.tsx:200` | `GET /api/pfz` proxy → draws PFZ `CircleMarker`s |
| `frontend/map/MapInner.tsx:227` | `GET /api/weather/current` direct (+ synthetic offline estimate) |
| `frontend/app/map/page.tsx:94` | `GET /api/geofence/status` direct (fire-and-forget) |
| `frontend/chat/useSSEChat.ts:273,298` | `POST /api/chat` direct, fallback to `POST /api/chat` proxy |
| `frontend/chat/useSSEChat.ts:625,644` | `POST /api/chat/voice` direct, fallback to `POST /api/chat/voice` proxy |
| `frontend/chat/ChatPanel.tsx` | Via `useSSEChat` hook only (no direct fetches; no history fetch) |
| `frontend/map/SafetyBadge.tsx` | Presentational props only (no fetches) |
| `frontend/app/page.tsx` | No fetches (no health poll) |
| `frontend/chat/bhashini.ts` | **Direct** to Bhashini ULCA (not via backend) |

---

## Error Response Format

FastAPI `HTTPException` responses (422, 413, 503 — e.g. `POST /api/chat/voice`) use FastAPI's native envelope; there is no custom exception handler:

```json
{
  "detail": "Audio file required as 'file' or 'audio' in multipart form data"
}
```

In-stream agent failures use the SSE error event instead (`{"type":"error","agent":"orchestrator","message":"..."}`); they do not close the HTTP response with an error status.

---

## Wiring Checklist for `backend/main.py`

```python
from backend.routers import pfz, tiles, chat, weather, geofence
app.include_router(pfz.router, prefix="/api")
app.include_router(tiles.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(geofence.router, prefix="/api")
# CORS (backend/main.py:55,211)
app.add_middleware(CORSMiddleware,
  allow_origins=os.getenv("ALLOWED_ORIGINS","http://localhost:3000,https://cron-system.vercel.app").split(","),
  allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
```

---

## Rate Limiting

Not implemented in MVP. Production deployment will add rate limiting per API key.

## Versioning

API version is embedded in the URL path (`/api/...`). Breaking changes will increment the version prefix.

## Evaluation & Benchmarking

- **Dataset**: `data/golden_v1.json` (66 multilingual cases across 22 languages) + `backend/evals/dataset.py` (84 English coastal/edge cases; 150 total)
- **LangSmith Sync**: `orca-golden-v1` (`python -m backend.evals.dataset --sync`)
- **Scorecard Report**: `reports/golden_v1_scorecard.md` (`python -m backend.evals.runner`)

---

*Rewritten for Wayfinder map #92 (T4): routes validated against `backend/routers/*.py` Pydantic models, callers verified by code read, T3 pruned routes removed, T5 fetch rule recorded. See also `docs/ORCA_GeoJSON_Architecture.md`, `docs/ORCA_Codebase_Guide.md`.*
