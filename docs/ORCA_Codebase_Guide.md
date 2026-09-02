# ORCA — Codebase Guide (Where Every File Lives)

This guide tells you where every file is, what it does in plain words, and how to run ORCA on your laptop.

> **Current status (02 Sep 2026):** The repo has the docs, live data (437 fishing zones), and scaffold files with TODO instructions. The server, map, and agents are not yet coded — each file tells you exactly what to build there.

> See also: [How ORCA works](ORCA_GeoJSON_Architecture.md) · [2-week plan](ORCA_2Week_MPP_Plan.md) · [API endpoints](API.md) · [Team workflow](CONTRIBUTING.md)

---

## 1. Project Structure

```
orca-marine-intelligence/
├── README.md                          ← What ORCA is + quick start (5 min read)
├── CONTRIBUTING.md                    ← How 4 members work together (branch + review rules)
├── .env.example                       ← Copy to .env and fill secrets (template)
├── .gitignore                         ← Tells git what NOT to save
│
├── docs/
│   ├── ORCA_GeoJSON_Architecture.md   ← How ORCA works inside (pipeline + agents)
│   ├── ORCA_Codebase_Guide.md         ← You are here — where files live
│   ├── ORCA_2Week_MPP_Plan.md         ← Who does what each day
│   └── API.md                         ← Every API endpoint with examples
│
├── data/                              ← Live data (today's fishing zones)
│   ├── pfz-today.geojson              ← 437 fishing zone points (the shared list everyone reads)
│   └── pfz-all.json                   ← Full raw data with original DMS coordinates
│   # eez.geojson + mpa.geojson will be added by Member B in W1 (India's sea borders + protected parks)
│
├── frontend/                          ← What the fisherman sees (website)
│   ├── app/
│   │   ├── page.tsx                   ← Home page: chat on left, map on right
│   │   ├── map/page.tsx               ← Full-screen map page
│   │   └── api/pfz/route.ts           ← Trick to avoid CORS: frontend asks here, this asks the server
│   ├── components/
│   │   ├── ChatPanel.tsx              ← Chat box where fisherman types (and sees answers)
│   │   ├── MapView.tsx                ← Interactive map that draws 437 zone circles
│   │   ├── SafetyBadge.tsx            ← Green / yellow / red safety dot
│   │   └── LanguageSwitch.tsx         ← Button to pick one of 22 Indian languages
│   ├── lib/
│   │   ├── bhashini.ts                ← Talks to Bhashini (translates between languages)
│   │   └── geo.ts                     ← Helper math: distance, bearing, DMS→decimal
│   ├── package.json                   ← List of frontend libraries (Next.js, Leaflet, etc.)
│   └── tsconfig.json                  ← Settings for TypeScript (the language Next.js uses)
│
├── backend/                           ← What runs on the server (behind the website)
│   ├── main.py                        ← Server startup file — creates the FastAPI app
│   ├── agents/                        ← 4 helpers + the brain that coordinates them
│   │   ├── orchestrator.py            ← The brain: understands the question, sends work to 4 helpers
│   │   ├── fish_finder.py             ← Helper 1: finds closest fishing zones
│   │   ├── sea_checker.py             ← Helper 2: checks wave height
│   │   ├── weather_agent.py           ← Helper 3: checks wind
│   │   ├── danger_agent.py            ← Helper 4: checks forbidden zones + cyclones
│   │   └── combiner.py                ← The decider: ranks all zones, picks the safest
│   ├── ingest/                        ← Code that fetches fresh data every day
│   │   ├── incois_textdata.py         ← Goes to INCOIS at 11:30 AM, parses the table, builds GeoJSON
│   │   ├── boundaries.py              ← Downloads sea borders + protected parks
│   │   └── copernicus_fallback.py     ← Backup data (only if INCOIS is down) — later, not W1
│   ├── routers/                       ← API endpoints — URLs the frontend calls
│   │   ├── pfz.py                     ← GET /api/pfz/today → today's zones (proxy to INCOIS)
│   │   ├── tiles.py                   ← GET /api/tiles/{z}/{x}/{y} → map tiles (small squares)
│   │   ├── chat.py                    ← POST /api/chat → talk to the brain
│   │   ├── weather.py                 ← GET /api/weather → wind + tide for a point
│   │   └── geofence.py               ← POST /api/geofence/check → is this point forbidden?
│   ├── db/                            ← How we talk to databases
│   │   ├── postgis.py                 ← Helper for the map database (PostGIS)
│   │   ├── redis.py                   ← Helper for fast cache (Redis)
│   │   └── schema.sql                 ← Creates tables: zones, sea borders, parks, logs
│   ├── requirements.txt               ← List of Python libraries to install
│   └── Dockerfile                     ← Recipe to build the backend container
│
├── infra/                             ← How we run the whole system
│   ├── docker-compose.yml             ← One command starts database + cache: `docker compose up`
│   └── vercel.json                    ← Tells Vercel how to show the site on the internet
│
└── scripts/                           ← Small helper scripts
    ├── extract_pfz.sh                 ← Fetches the 14 INCOIS sectors (needs JSESSIONID cookie)
    └── dms_to_decimal.py              ← Converts "8 33 18 N" → 8.555 (math helper)
```

---

## 2. What Each File Does (and Who Builds It)

### Member A — Brain + Language

| File | In plain words | What you implement |
|------|---------------|--------------------|
| `backend/agents/orchestrator.py` | **The brain.** Understands "Where is fish near Kochi?" → pulls out language + location → asks 4 helpers at once. | Step 1: detect language (use Bhashini or simple check). Step 2: get lat/lon from GPS or place name table. Step 3: `asyncio.gather(fish, sea, weather, danger)` — parallel calls. Step 4: hand results to Combiner. Handle one helper timing out (>10s) as "unknown", don't crash. |
| `backend/agents/combiner.py` | **The decider.** Gets 4 helpers' reports for each zone, scores them, picks one winner with proof. | Implement the formula: `closest*0.4 + sea_safe*0.3 + wind_ok*0.2 + not_forbidden*0.1`. Closest: `1 - distance/max_distance`. Sea: 1.0 if wave<1.5m else slide to 0. Wind: 1.0 if <15kt else slide. Forbidden: 0 or 1. Return `{ best_zone, explanation, citation }`. Citation: `INCOIS TextData SEC005 KERALA 02-Sep`. |
| `backend/routers/chat.py` | **The chat URL.** Frontend posts a message here, gets back reply + map data. | `POST /api/chat { message, lat, lon, session_id }` → call orchestrator → return `{ reply, map: {center, route}, safety, evidence, language }` (see `API.md`). In W1, `reply` is text; W2 add Redis memory via `session_id`. |
| `frontend/components/ChatPanel.tsx` | **The chat box.** Where the fisherman types and sees answers. | Text input + send button. On send, `fetch("/api/chat")`. Show reply, evidence citations, and call `onMapFlyTo(center)` to move the map. TypeScript + React state (`useState` for messages). |
| `frontend/lib/bhashini.ts` | **The translator.** Talks to Bhashini server to detect and translate among 22 Indian languages. | Export `detectLanguage(text)` and `translate(text, from, to)`. For W1, even simple mapping works: if text has Malayalam characters → `ml`, else `en`. Real Bhashini URL is in `.env.example`. |

### Member B — Data + Safety

| File | In plain words | What you implement |
|------|---------------|--------------------|
| `backend/ingest/incois_textdata.py` | **The daily fetcher.** Go to INCOIS every 11:30 AM, read 14 HTML pages, convert to zones list. | Loop SEC001..SEC014 with `requests` + `BeautifulSoup`. Parse 7-column rows. Call `scripts/dms_to_decimal.py` logic: `8 33 18 N → 8.555`. Build GeoJSON features. Write `data/pfz-today.geojson`, then `INSERT` into PostGIS via `backend/db/postgis.py`, then `SET pfz:today` in Redis with 6h expiry. Handle cookie expiry — re-fetch TextDataHome first. |
| `backend/ingest/boundaries.py` | **Download sea borders once.** | Download `eez.geojson` (MarineRegions) and `mpa.geojson` (WDPA) → save `data/eez.geojson`, `data/mpa.geojson` → load into PostGIS (`eez_boundaries`, `mpa_boundaries`). Run once in W1, not daily. |
| `backend/ingest/copernicus_fallback.py` | **Backup data** — only if INCOIS is down. Skip in W1 (do Week 5). | Left as TODO + docstring. |
| `backend/db/schema.sql` | **Creates tables.** | Already written with `CREATE TABLE pfz_zones, eez_boundaries, mpa_boundaries, ingest_log + GIST index on geom`. If you change columns, update here first, then run `docker compose up` again. |
| `backend/db/postgis.py` | **Talks to the map database.** | Functions: `upsert_zones(features)`, `find_nearest(lon, lat, radius=80000)`, `check_contains(lon,lat, table)`. Use `psycopg` + `ST_DWithin` / `ST_Contains`. |
| `backend/db/redis.py` | **Talks to fast memory.** | Functions: `cache_pfz(data, ttl=6h)`, `get_cached_pfz()`, `save_session(session_id, {lat,lon,boat})`, `get_session()`. Use `redis-py`. If Redis is down, just query PostGIS directly (don't crash). |
| `backend/agents/fish_finder.py` | **Closest zones.** | SQL: `SELECT * FROM pfz_zones WHERE ST_DWithin(geom::geography, ST_MakePoint(lon,lat)::geography, 80000) ORDER BY ST_Distance LIMIT 5`. If 0 results at 80km, retry 120km, then 160km. |
| `backend/agents/sea_checker.py` | **Wave check.** | W1: return `wave_m=0.8` for every zone (mock). W2: replace with OSF 06Z data joined by lat/lon. Return `{ wave_m, current_kt, status: "safe"|"caution"|"danger"}`. |
| `backend/agents/weather_agent.py` | **Wind check.** | W1: mock `wind_kts=8`. W2: fetch IMD at `https://mausam.imd.gov.in`. Same status thresholds: safe <15kt, caution 15-25kt, danger >25kt. |
| `backend/agents/danger_agent.py` | **Forbidden check.** | For each zone: `ST_Contains(eez)`, `ST_DWithin(border,2000)` for IMBL warning 2km, `ST_Contains(mpa)` for forbidden. Also check IMD cyclone within 500km. Return `{ inside_eez, near_imbl, in_mpa, cyclone_alert }`. |
| `backend/routers/geofence.py` | **Check my point URL.** | `POST /api/geofence/check {lat,lon}` → call `danger_agent` checks → `{ inside_eez, inside_mpa, restricted }` (see `API.md`). |
| `backend/routers/weather.py` | **Weather URL.** | `GET /api/weather/current?lat=&lon=` → call `weather_agent` + `sea_checker` → `{ wind_speed_kts, wave_height_m, ... }`. |
| `scripts/extract_pfz.sh` | **Shell helper for B.** | Already has the 14-sector loop with `curl -b cookies.txt`. Just make it executable: `chmod +x scripts/extract_pfz.sh`. |
| `scripts/dms_to_decimal.py` | **Math helper.** | Already has `def dms_to_decimal(deg, min, sec, hemi)` with `South/West → negative`. Call from `incois_textdata.py`. |

### Member C — Maps

| File | In plain words | What you implement |
|------|---------------|--------------------|
| `frontend/components/MapView.tsx` | **The map.** Draw base map + 437 zone circles + popups + route line. | Use `react-leaflet`: `<MapContainer>` + `<TileLayer url={bhuvanOrOSM}>` + `features.map(f => <CircleMarker color="cyan">)`. Highlight top recommendations (<60km) in brighter cyan. Highlight safe zones with green border. `onClick` on marker → popup with `place, bearing, distance, depth, citation`. Draw `<Polyline positions={route}>` for green route. |
| `frontend/components/SafetyBadge.tsx` | **Safety dot.** Green/yellow/red badge for a zone. | `props: { wave_m, wind_kts, danger }` → if forbidden or wave>2.5m or wind>25kt → red, else if wave>1.5m or wind>15kt → yellow, else green. Small pill with text. |
| `frontend/app/map/page.tsx` | **Full map page.** | Wraps `MapView` full-screen. Same fetch as `page.tsx` but no chat. Used for `https://cron-system.vercel.app/orca/map/`. |
| `frontend/app/page.tsx` | **Home page.** | Layout: left 30% `ChatPanel`, right 70% `MapView`. Wire: when chat returns `map.center`, call `mapRef.current.flyTo(center)`. Pass `mapRef` via React `useRef`. |
| `frontend/lib/geo.ts` | **Map math.** | `haversine(lon1,lat1,lon2,lat2) → km`, `bearing(...) → degrees`, `dmsToDecimal(...)` (reuse), `parseLocation(text) → {lat,lon}` small lookup. |
| `backend/routers/tiles.py` | **Map tile server.** | W2 task: `GET /api/tiles/{z}/{x}/{y}.pbf` → `SELECT ST_AsMVT(...)` from PostGIS. W1: tiles not needed — frontend can fetch the whole GeoJSON file. Member C owns this. |

### Member D — Platform

| File | In plain words | What you implement |
|------|---------------|--------------------|
| `backend/main.py` | **Server startup.** | Already has `FastAPI() + /health`. Add CORS: `app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000","https://cron-system.vercel.app"], ...)`. Include 5 routers: `app.include_router(pfz.router)`, etc. |
| `backend/routers/pfz.py` | **Zones URL (the CORS fix).** | `GET /api/pfz/today` → try Redis (`get_cached_pfz`), if hit return it, else call `incois_textdata.py` → fetch today → cache + return. Browser never calls INCOIS directly — always this proxy, so CORS error disappears. |
| `frontend/app/api/pfz/route.ts` | **Next.js proxy** (extra safety). | `export async function GET() { return fetch("http://localhost:8000/api/pfz/today").then(r=>r.json()) }` — same-origin for Vercel. |
| `frontend/package.json` | **Frontend libraries list.** | `npm install` after clone. Already has Next 14 + Leaflet + Tailwind. Add `bhashini` or `fasttext` if needed. |
| `infra/docker-compose.yml` | **One-command dev env.** | `postgis:15-3.3` on 5432, `redis:7` on 6379. Run `docker compose -f infra/docker-compose.yml up -d`. In W2 you can add `backend` as third service. |
| `infra/vercel.json` | **Deploy settings.** | Tells Vercel where `static/orca` lives. Push to `main` → auto deploys to `https://cron-system.vercel.app/orca/*`. Don't change unless Vercel path changes. |
| `.env.example` | **Secrets template.** | Copy to `.env` → fill `INCOIS_JSESSIONID, BHASHINI_API_KEY`. `DATABASE_URL, REDIS_URL` stay as-is for Docker. Never commit `.env`. |
| `docs/API.md` | **Endpoint docs** (D owns keeping it updated). | Lists all 6 endpoints with request/response examples. Update it when you change a URL. |

---

## 3. Tech Stack (plain words)

| What it is | We use | Why |
|------------|--------|-----|
| **Data source** | INCOIS TextData (government HTML tables at 11 AM daily) | Gives fishing zone clues from satellite |
| **We store maps in** | PostGIS (a database that understands lat/lon) | So we can ask "what's near Kochi within 80km?" quickly |
| **We remember for a bit in** | Redis (super fast sticky note, erases after 6 hours) | So we don't re-fetch the same data every click |
| **Server language** | Python + FastAPI (modern Python web framework) | Easy for the same team to write data code and server code |
| **Website** | Next.js 14 (React) + Leaflet (open map) + Tailwind (styling) | User types, map moves — familiar for web devs |
| **Language translation** | Bhashini ULCA (government translation for 22 Indian languages) | Detect Malayalam → answer in Malayalam |
| **We deploy on** | Docker (boxes that run the same everywhere) + Vercel (shows it on the internet) | One command locally, push to show live |

---

## 4. How to Run on Your Laptop (4 steps, ~10 minutes)

### Before you start — you need:

- **Docker Desktop** (to run database + cache) — download from docker.com
- **Node.js 18 or newer** — `node -v` to check
- **Python 3.11 or newer** — `python --version` to check

### Step 1 — Get the code and fill secrets

```bash
# Download the repo
git clone https://github.com/parth5012/orca-marine-intelligence.git
cd orca-marine-intelligence

# Copy the template file, then open .env and paste your keys
cp .env.example .env
# Now edit .env in VS Code:
#   INCOIS_JSESSIONID=   (get with: curl -c cookies.txt https://incois.gov.in/MarineFisheries/TextDataHome?mfid=1)
#   BHASHINI_API_KEY=    (from Bhashini ULCA console)
# The other two (DATABASE_URL, REDIS_URL) stay as-is for Docker
```

### Step 2 — Start the database + cache (one command)

```bash
docker compose -f infra/docker-compose.yml up -d
# Check they're running:
docker ps
# Check tables exist:
docker exec -it orca-postgis psql -U orca -c "\dt"
```

What this did: started PostGIS on `5432` (with `db/schema.sql` already loaded) and Redis on `6379`.

### Step 3 — Get today's fishing zones + start the server

```bash
# A) Fetch today's 437 points (needs JSESSIONID in .env)
bash scripts/extract_pfz.sh
# Verify:
ls -lh data/pfz-today.geojson
cat data/pfz-today.geojson | python -m json.tool | head -20

# B) Install Python libraries
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# C) Start the server
uvicorn main:app --reload --port 8000
# Leave this terminal running. Test in a new terminal:
curl http://localhost:8000/health
# You should see: {"status":"ok","service":"orca-marine-intelligence"}
curl "http://localhost:8000/api/pfz/today" | python -m json.tool | head -30
# You should see 437 features
```

### Step 4 — Start the website

Open a **new terminal** (keep the server running):

```bash
cd frontend
npm install
npm run dev
# Open: http://localhost:3000  → Chat on left, Map on right
# Full map: http://localhost:3000/map  → Shows 437 cyan circles
```

**Full stack with Docker (alternative):**

```bash
docker compose -f infra/docker-compose.yml up -d --build
# Builds backend container + PostGIS + Redis all at once
```

---

## 5. Where to Ask for Help

| If you are ... | Read this first | Then ask |
|----------------|-----------------|---------|
| Member A (Brain+Language) | `docs/API.md` (the `/api/chat` format), `ORCA_GeoJSON_Architecture.md` (how agents work) | Member B for real wave/wind data shape |
| Member B (Data+Safety) | `backend/ingest/incois_textdata.py` docstring, `backend/db/schema.sql` | Member D for `/health` verify |
| Member C (Maps) | `frontend/components/MapView.tsx` docstring, `docs/API.md` (tile format) | Member B for tile URL once `tiles.py` is ready |
| Member D (Platform) | `infra/docker-compose.yml`, `backend/main.py` | Everyone at standup 10:00 IST |

---

*This guide covers both current files and the promised structure. Files you haven't built yet have TODO instructions inside. If a TODO says "Week 5", leave it — it's not for this MVP.*

*See [ORCA_GeoJSON_Architecture.md](ORCA_GeoJSON_Architecture.md) for how ORCA works. See [ORCA_2Week_MPP_Plan.md](ORCA_2Week_MPP_Plan.md) for who does what when.*
