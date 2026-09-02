# M-C — Backend API & Platform (Copy to Notion → "M-C Backend API")

> **Paste tip:** Create Notion page under "ORCA Core" → paste this markdown.

**You own:** `backend/routers/` + `backend/main.py` + `infra/` — the server. **The glue between agents (M-A), data (M-B), and the screen (M-D).**  
**Official PS:** [SIH26176 — ISRO](https://github.com/vedantchalke36/sih-2026-problem-statements/blob/main/ps_2026/SIH26176.md) — 5 APIs must wrap the 6 agents.  
**Depends on:** M-A's agents + M-B's DB. **Used by:** M-D's `ChatPanel` + `MapView` call your URLs.

---

## 1) Your 8 files (one stack: FastAPI + Docker + Vercel)

| File | What it does in plain words |
|------|-----------------------------|
| `backend/main.py` | **Server startup.** Creates the FastAPI app, adds CORS, mounts 5 routers, `/health`. |
| `backend/routers/pfz.py` | **Zones URL (the CORS fix).** `GET /api/pfz/today` — frontend asks you, you ask INCOIS server-side where CORS doesn't apply. |
| `backend/routers/chat.py` | **Chat wrapper.** `POST /api/chat` → calls M-A's `orchestrator.orchestrate()` → returns reply+map+evidence. |
| `backend/routers/tiles.py` | **Map tile server.** `GET /api/tiles/{z}/{x}/{y}.pbf` → `ST_AsMVT` from PostGIS. |
| `backend/routers/geofence.py` | **Forbidden check API.** `POST /api/geofence/check` → calls M-A's `danger_agent`. |
| `backend/routers/weather.py` | **Weather API.** `GET /api/weather/current` → calls M-A's `weather_agent + sea_checker`. |
| `infra/docker-compose.yml` | **One-command dev env.** Starts PostGIS + Redis. |
| `infra/vercel.json` | **Deploy.** Push to `main` → live at `https://cron-system.vercel.app/orca/*`. |

Every file has `Owner: M-C (Backend API & Platform)` + TODOs — open it.

---

## 2) Week 1 — Expose the 5 APIs (CORS fix is #1)

### Task C1 — FastAPI proxy (fixes CORS)

*Browsers block direct INCOIS requests.* Fix:

1. Open `backend/main.py` (already has `FastAPI() + /health`). Add:
   ```python
   from fastapi.middleware.cors import CORSMiddleware
   app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000","https://cron-system.vercel.app"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
   ```
2. In `routers/pfz.py`, create `GET /api/pfz/today`:
   ```python
   # 1. Try Redis (M-B's redis.get_cached_pfz), if hit → return
   # 2. Else call M-B's incois_textdata.fetch_today() → GeoJSON → cache 6h → return
   ```
   Frontend does same-origin `fetch("/api/pfz/today")` — no CORS error because frontend and API are same domain. Browser never calls INCOIS directly.

3. Wire all routers in `main.py`:
   ```python
   app.include_router(pfz.router, prefix="/api")
   app.include_router(chat.router, prefix="/api")
   app.include_router(tiles.router, prefix="/api")
   app.include_router(geofence.router, prefix="/api")
   app.include_router(weather.router, prefix="/api")
   ```
*Verify:* `uvicorn main:app --reload` → `curl http://localhost:8000/api/pfz/today | jq .metadata.count` → 437.

### Task C2 — Chat + tiles + geofence wrappers (thin wrappers, M-A writes logic)

1. **`routers/chat.py`:** `POST /api/chat {message, lat, lon, session_id}` → `await orchestrator.orchestrate(message, lat, lon)` (M-A) → return `{reply, map:{center, route}, safety, evidence, language, confidence}` (see `docs/API.md`). You don't write the brain, you wrap it.

2. **`routers/tiles.py`:** `GET /api/tiles/{z}/{x}/{y}.pbf` → `SELECT ST_AsMVT(...)` from PostGIS (M-B's data). W1 can return `501 "tiles W2"` — M-D fetches whole GeoJSON in W1, tiles in W2.

3. **`routers/geofence.py` + `weather.py`:** Thin wrappers:
   ```python
   # geofence.py: POST /api/geofence/check {lat,lon} → await danger_agent.check_dangers(pts) → {inside_eez, inside_mpa, restricted}
   # weather.py: GET /api/weather/current?lat=&lon= → await weather_agent.check_weather(pts) → {wind_speed_kts, wave_height_m}
   ```

### Task C3 — Docker

1. Open `infra/docker-compose.yml`:
   ```yaml
   services:
     postgis: image: postgis/postgis:15-3.3  ports: ["5432:5432"]  env_file: .env
     redis:   image: redis:7                 ports: ["6379:6379"]
   ```
2. `docker compose -f infra/docker-compose.yml up -d` → `docker ps` + `curl http://localhost:8000/health` → `{"status":"ok"}`.
3. FastAPI runs locally in W1 (`uvicorn`), add as 3rd service in W2 if needed.

### Task C4 — Vercel

`infra/vercel.json` already points to `frontend/.next` and rewrites `/api/:path*` to your API. Push to `main` → auto-deploys to `https://cron-system.vercel.app/orca/*`. Friday live tests are on this URL, not localhost — catches CORS/JSESSIONID drift.

---

## 3) Week 2 — Polish

- **6h cache:** Add `redis.get_cached_pfz` check in `pfz.py`, `chat.py`, `weather.py` via `M-B's redis.py`.
- **Error format:** All errors return `{error, message, details}` per `docs/API.md`. Add 502 for INCOIS down (serve cached), 503 for DB down.
- **Rate limiting + CORS headers:** Add per `API.md` Versioning section.
- **Global Tests script:** You run Fri 16:00 — script the 5 SIH scenarios (PFZ today → safety → lightning → avoid forbidden → Malayalam refinement), log P50 latency + geofence distances. M-D handles SMS/offline display, you log the API side.

---

## 4) Who you talk to

- **You call:** M-A's 6 agents (orchestrator, fish_finder etc.) + M-B's `postgis.py` + `redis.py`
- **You are called by:** M-D's `ChatPanel.tsx` (`POST /api/chat`), `MapView.tsx` (`GET /api/pfz/today`, `/api/tiles`), `SafetyBadge`
- **Handover:** W2 — your tiles switch makes M-D's map fast on 2G

---

## 5) Verify checklist

- [ ] `docker compose -f infra/docker-compose.yml up -d` → `docker ps` 2 containers
- [ ] `curl http://localhost:8000/health` → 200
- [ ] `curl http://localhost:8000/api/pfz/today` → 437 features
- [ ] `curl -X POST http://localhost:8000/api/chat -d '{"message":"Where is fish near Kochi?","lat":9.93,"lon":76.26}'` → reply + map.center
- [ ] `curl -X POST http://localhost:8000/api/geofence/check -d '{"lat":9.93,"lon":76.26}'` → inside_eez true
- [ ] Fri 05 Sep live Vercel test passes

---

*Source of truth: `docs/API.md` (all 6 endpoints with examples), `docs/ORCA_GeoJSON_Architecture.md` (CORS fix), `backend/routers/` TODOs.*
