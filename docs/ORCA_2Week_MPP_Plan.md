# ORCA — 2-Week Build Plan (4 Members)

This is your day-by-day plan for building the ORCA MVP in 14 days. Read this if you are on the team and want to know what you do each day, what you deliver, and what you depend on.

**Period:** 02 September to 16 September 2026 (2 weeks)
**Team size:** 4 members (A, B, C, D) — see who does what below
**Goal:** By 16 Sep, a fisherman in Kochi can type a question in Malayalam and get a safe fishing spot on a map with proof.
**Out of scope for this MVP:** Voice input/output (you type, not speak) and Copernicus satellite fallback data. Those come later.

> Other docs: [How ORCA works](ORCA_GeoJSON_Architecture.md) · [Files and how to run](ORCA_Codebase_Guide.md) · [API details](API.md)

---

## 1. What Success Looks Like

A fisherman near Kochi opens ORCA, types "Where is fish?" in Malayalam, and ORCA:
1. Detects the language is Malayalam
2. Looks up the closest fishing zones from today's 437 INCOIS points
3. Checks four things in parallel: how far, how rough the sea is, how strong the wind is, and whether it is inside a forbidden zone
4. Picks the single **safest** spot (not just the closest)
5. Shows it on a map with a popup: place name, bearing, distance, and a citation like "INCOIS TextData SEC005 KERALA 02-Sep"
6. Sends the route as SMS in Malayalam

This one flow proves all 8 SIH requirements (chat, multilingual, location, data discovery, reasoning, maps, geofencing, evidence).

**How we test it:**
- **W1 test — Fri 05 Sep 16:00 IST (everyone, on live Vercel):** Malayalam text near Kochi → map pin appears at correct place → safety badge is green → mock SMS sent. If this fails, W1 is not done.
- **W2 test — Fri 12 Sep 16:00 IST (everyone, on live Vercel):** 5 scenarios back to back: (1) find fish today, (2) safety check, (3) lightning alert, (4) route that avoids a forbidden zone, (5) refine the query in Malayalam. Log speed and distance. Then freeze code for SIH submission. Daily standup 10:00 IST (15 min), Friday tests (60 min).

---

## 2. Who Does What (4 Lanes)

We split the 6-person plan into 4 clean categories — one tech layer per person, no mixed files, no merge conflicts.

| Lane | Category | What they own (folder) | Files (see guide) |
|------|----------|------------------------|-------------------|
| **Member A** | **Agents & Orchestration** | `backend/agents/` — the intelligence | `orchestrator.py` (brain), `combiner.py` (ranking), `fish_finder.py`, `sea_checker.py`, `weather_agent.py`, `danger_agent.py` — all 6 agents |
| **Member B** | **Data Extractors & Storage** | `backend/ingest/` + `backend/db/` + `scripts/` — the data pipeline | `incois_textdata.py`, `boundaries.py`, `postgis.py`, `redis.py`, `schema.sql`, `extract_pfz.sh`, `dms_to_decimal.py` |
| **Member C** | **Backend API & Platform** | `backend/routers/` + `backend/main.py` + `infra/` — the server | `main.py`, `pfz.py`, `tiles.py`, `chat.py`, `geofence.py`, `weather.py`, `docker-compose.yml`, `vercel.json` |
| **Member D** | **Frontend & Maps** | `frontend/` + `diagrams/` — what the fisherman sees | `app/page.tsx` (shell), `app/map/page.tsx`, `app/api/pfz/route.ts`, `components/MapView, ChatPanel, SafetyBadge, LanguageSwitch`, `lib/bhashini.ts, geo.ts` — starts from live `https://cron-system.vercel.app/orca/map/` |

**Critical handover:** Member B must deliver the daily 437-point GeoJSON on **Tuesday 02 Sep**. Until that exists, A cannot rank, C cannot serve APIs, and D cannot draw dots. B is the single blocking dependency for the whole team.

---

## 3. Member A — Agents & Orchestration (detailed guide)

**You own the intelligence — all 6 agents. You make the chatbot understand, check safety, and rank.**

> **Category ownership:** `backend/agents/` only — `orchestrator.py`, `combiner.py`, `fish_finder.py`, `sea_checker.py`, `weather_agent.py`, `danger_agent.py`. You do NOT touch `frontend/` (M-D) or `backend/routers/` (M-C). Call M-B's `postgis.py` to query zones, call M-D's `bhashini.ts` for translation.

### Week 1 — Build the brain (by Tue 09 Sep)

You will create the central "orchestrator" that takes a user's message and figures out what to do.

**Task A1 — Understand the user's question**

*What to do:*
1. Open `backend/agents/orchestrator.py`. This file already has a docstring and TODOs.
2. Write a function that takes `message` (e.g., "Where is fish near Kochi?") and returns:
   - `language` — e.g., "ml" for Malayalam, "en" for English
   - `location` — lat/lon if the message contains a place name or if GPS was sent
   - `intent` — e.g., `{ "wants_fish": true, "wants_safety": true }`
3. For `language`, call the helper in `frontend/lib/bhashini.ts` (see guide) or a simple library like `fasttext` for detection. In W1, even a rule like "if message contains Malayalam unicode → ml" is enough.
4. For `location`, if `lat/lon` was sent from the phone, use it. Otherwise extract "Kochi" → lookup a small table `{ "Kochi": [9.93, 76.26] }`.

*How to know it works:* `curl POST /api/chat '{"message":"Where is fish near Kochi?"}'` returns `{"language":"en","location":[9.93,76.26]}`.

**Task A2 — Send work to 4 helpers in parallel**

1. After you know the location, call the 4 safety helpers at the same time (not one by one — that is too slow). In Python, use `asyncio.gather(...)`.
2. Each helper reads the same GeoJSON points (shared location list). If one helper fails or is slow (>10 sec), proceed with the others and mark that check as "unknown" — don't crash the whole answer.

**Task A3 — Rank and explain**

1. Open `backend/agents/combiner.py`. It has the scoring formula written down:
   - **Closest = 40%** — nearer is better. Convert distance to a 0-1 score: `1 - (distance / max_distance)`. E.g., 5 km away = 0.9, 80 km = 0.1.
   - **Sea safe = 30%** — 1.0 if wave < 1.5 meters, slide to 0 at 3 meters.
   - **Wind ok = 20%** — 1.0 if wind < 15 knots, slide to 0 at 30 knots.
   - **Not forbidden = 10%** — 1 if outside forbidden zone, 0 if inside. Simple yes/no.
2. Add them up. Highest total wins. Return that winner plus a short explanation string: "Picked Pallithottam because it is closest (12 km) and sea is calm (0.8m)."
3. Always include a citation: `"INCOIS TextData SEC005 KERALA 02-Sep-2026"`.

**Task A4 — Chat wiring**

1. Open `backend/routers/chat.py` and `frontend/components/ChatPanel.tsx`.
2. `ChatPanel` sends `POST /api/chat { message, lat, lon, session_id }` and `chat.py` calls your orchestrator, then returns `{ reply, map, safety, evidence, language }` (format is in `docs/API.md`).
3. Language: detect → process → translate answer back to the same language. In W1, text only — no microphone/speaker.

### Week 2 — Polish

- Remember the conversation: store `location`, `boat type`, `risk preference` in Redis (key = `session_id`) so a follow-up like "and is it safe tomorrow?" works.
- Build the "Why this zone?" panel in the frontend — show the 4 scores with bars.
- Member B will give you real IMD wind data; swap your mock wind for it.

*Deliverable:* The ranking algorithm and evidence format. Member D needs your `evidence` shape for the PDF advisory.

---

## 4. Member B — Data Extractors & Storage (detailed guide)

**You fetch the data and fill the database. You are the blocking path — deliver Tue or everyone is blocked.**

> **Category ownership:** `backend/ingest/` + `backend/db/` + `scripts/` — you produce `data/pfz-today.geojson` and fill PostGIS/Redis. You do NOT write agents (M-A) or routers (M-C). Your output is the shared list everyone reads.

### Week 1 — Get the data flowing (most urgent)

**Task B1 — Fetch INCOIS TextData (do this Tuesday 02 Sep)**

*What INCOIS is:* A government website that publishes a table of fishing zones per coastal sector. 14 sectors (SEC001 Gujarat … SEC014 Lakshadweep). Each page is an HTML table with 7 columns: place name, compass direction, bearing, depth, distance, latitude in DMS, longitude in DMS. DMS looks like "8 33 18 N".

*Step by step:*

1. Open `scripts/extract_pfz.sh` — it already has the loop. Make it do:
   ```bash
   # 1. Get a session cookie (JSESSIONID) — required by INCOIS
   curl -c cookies.txt https://incois.gov.in/MarineFisheries/TextDataHome?mfid=1 -o /tmp/home.html
   # 2. For each sector SEC001..SEC014, fetch with that cookie
   for id in SEC001 SEC002 ... SEC014; do
     curl -b cookies.txt "https://incois.gov.in/MarineFisheries/TextData?secid=$id" -o "data/raw_${id}.html"
   done
   ```
   The cookie expires — refresh it daily before 11:30 AM.

2. Open `backend/ingest/incois_textdata.py`. For each `data/raw_*.html`:
   - Parse the `<table>` rows (use Python's `BeautifulSoup` or `html.parser`).
   - For each row, read the 7 columns.
   - Convert DMS to decimal:
     ```
     8 33 18 N → 8 + 33/60 + 18/3600 = 8.555
     76 10 02 E → 76 + 10/60 + 2/3600 = 76.167
     ```
     South/West are negative. Save as `[longitude, latitude]` (note order for GeoJSON).
   - Build a GeoJSON Feature (example shape is in the Architecture doc) and push to a list.
   - You should end with ~437 features today (count will change daily).

3. Write to two places:
   - File: `data/pfz-today.geojson` (so a new teammate can run without a DB)
   - Database: `backend/db/postgis.py` — call `INSERT INTO pfz_zones` (schema is in `backend/db/schema.sql`). Also cache in Redis: key `pfz:today`, expire 6 hours.

*How to know it works:* `ls data/pfz-today.geojson` exists and `jq '.features | length'` shows ~437. `curl http://localhost:8000/api/pfz/today | jq '.metadata.count'` shows same number.

**Task B2 — Database setup**

1. Open `backend/db/schema.sql` and `backend/db/postgis.py`.
2. Run `docker compose -f infra/docker-compose.yml up -d` — it starts PostGIS on 5432 and Redis on 6379.
3. The compose file auto-runs `schema.sql`. Verify: `docker exec postgis psql -U orca -c "\d pfz_zones"`.
4. Spatial index: `CREATE INDEX ON pfz_zones USING GIST(geom)` — makes "near me" queries fast. Already in `schema.sql`.

**Task B3 — Download forbidden zones**

1. Open `backend/ingest/boundaries.py`:
   - **EEZ** (India's sea border): download from MarineRegions `https://geo.vliz.be/.../eez.geojson` → save `data/eez.geojson` → load into PostGIS table `eez_boundaries`.
   - **MPA** (Marine Protected Areas): download from WDPA `https://www.protectedplanet.net/downloads` → save `data/mpa.geojson` → load into `mpa_boundaries`.

2. These files are static (don't change daily). Just do it once in W1.

**Task B4 — 4 safety helpers**

Open `backend/agents/fish_finder.py`, `sea_checker.py`, `weather_agent.py`, `danger_agent.py`. Each has a TODO.

- **Fish Finder** — given lat/lon, find closest zones within 80 km:
  ```sql
  SELECT * FROM pfz_zones
  WHERE ST_DWithin(geom::geography, ST_MakePoint(:lon,:lat)::geography, 80000)
  ORDER BY ST_Distance(geom, ST_MakePoint(:lon,:lat))
  LIMIT 5;
  ```
  If no zones within 80 km, try 120 km, then 160 km.

- **Sea Checker** — for W1, just return fixed `wave_m=0.8` for every zone (mock). In W2 you'll replace with real OSF data.

- **Weather Checker** — W1 mock `wind_kts=8`, no cyclone. W2 = real IMD data.

- **Danger Checker** — for each zone, check:
  ```sql
  -- inside EEZ? (must be yes)
  SELECT ST_Contains(eez.geom, ST_MakePoint(:lon,:lat)) FROM eez_boundaries;
  -- within 2 km of border? (warn)
  SELECT ST_DWithin(geom::geography, ST_MakePoint(:lon,:lat)::geography, 2000);
  -- inside MPA? (forbidden)
  SELECT ST_Contains(mpa.geom, ST_MakePoint(:lon,:lat)) FROM mpa_boundaries;
  ```

### Week 2 — Harden

- Make a GeoJSON → map tiles server: `backend/routers/tiles.py` using `ST_AsMVT` (PostGIS knows how to slice tiles). Member C's map will fetch these instead of the whole 437-point file.
- Cron job: add `infra/cron_ingest.sh` that runs daily 11:30 AM IST: refresh cookie → fetch 14 sectors → rebuild GeoJSON → upsert PostGIS → refresh Redis. Log count and errors.
- Replace mocks: Sea Checker → real OSF 06Z wave data, Weather → real IMD wind/cyclone. Add lightning.

*Deliverables:* `data/pfz-today.geojson` + PostGIS with 437 points + `ST_DWithin` logic + tile server + daily cron. This unlocks A, C, D.

---

## 5. Member C — Backend API & Platform (detailed guide)

**You expose everything as correct URLs and make it run locally + live. The glue between agents (M-A), data (M-B), and the screen (M-D).**

> **Category ownership:** `backend/main.py` + `backend/routers/` + `infra/` — you own the 5 API routers (`pfz`, `tiles`, `chat`, `geofence`, `weather`) and Docker/Vercel. You call M-A's agents from your routers, you do NOT write the agents or the map UI.

### Week 1 — Expose the 5 APIs (CORS fix is your #1 job)

**Task C1 — FastAPI proxy (fixes CORS)**

*Problem:* Browsers block direct INCOIS requests because INCOIS doesn't set CORS headers. So the frontend cannot `fetch https://incois.gov.in/...`.

*Fix:*
1. Open `backend/main.py` and `backend/routers/pfz.py`.
2. `main.py` already has `FastAPI()` + `/health` endpoint. Add CORS middleware:
   ```python
   app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000","https://cron-system.vercel.app"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
   ```
3. In `routers/pfz.py`, create `GET /api/pfz/today` that **server-side** does `requests.get("https://incois.gov.in/...")` (server is not blocked), converts to GeoJSON (call Member B's ingest), and returns it. Frontend then does same-origin `fetch("/api/pfz/today")` — no CORS error.
4. Wire all 5 routers in `main.py`: `pfz.py`, `tiles.py`, `chat.py` (calls M-A's orchestrator), `geofence.py`, `weather.py`. Test: `curl http://localhost:8000/api/pfz/today | jq .metadata.count` → 437.
5. Next.js proxy `frontend/app/api/pfz/route.ts` is owned by M-D, not you — you just make sure your FastAPI is the source it proxies to.

**Task C2 — Chat + tiles + geofence wrappers**

1. `routers/chat.py`: `POST /api/chat {message, lat, lon, session_id}` → call `M-A's orchestrator.orchestrate()` → return `{reply, map, safety, evidence, language}` (format in `API.md`). Don't write the brain, just wrap it.
2. `routers/tiles.py`: `GET /api/tiles/{z}/{x}/{y}.pbf` → `SELECT ST_AsMVT(...)` from PostGIS (data from M-B). W1 can return 501 "not yet" — M-D will fetch whole GeoJSON in W1, tiles in W2.
3. `routers/geofence.py` + `weather.py`: thin wrappers that call `M-A's danger_agent / weather_agent` and return JSON. M-A writes the check, you expose it as an API.

**Task C3 — Docker**

1. Open `infra/docker-compose.yml`. It has:
   ```yaml
   services:
     postgis: image: postgis/postgis:15-3.3  ports: ["5432:5432"]  env_file: .env
     redis:   image: redis:7                 ports: ["6379:6379"]
   ```
   FastAPI runs locally in W1 (`uvicorn main:app --reload`). In W2 you can add it as a third service.
2. One command should work: `docker compose -f infra/docker-compose.yml up -d`. Verify: `docker ps` + `curl http://localhost:8000/health`.

**Task C4 — Vercel**

`infra/vercel.json` tells Vercel how to deploy to `cron-system` (temporary). Push to `main` → auto-deploys to `https://cron-system.vercel.app/orca/*`. Friday live tests are on this URL, not localhost — that's how you catch CORS/JSESSIONID drift.

### Week 2 — Polish

- Add 6h Redis caching in your routers (`get_cached_pfz` from M-B's `redis.py`).
- Add rate limiting + error format from `API.md`.
- Own Global Tests script: you run Fri 16:00 — script the 5 scenarios, log P50 latency + geofence distances (M-D triggers SMS/offline, you log the API side).

*Deliverable:* One-command `docker compose up`, live Vercel, 5 APIs working (pfz, chat, tiles 501 in W1, geofence, weather mocks).

---

## 6. Member D — Frontend & Maps (detailed guide)

**You build what the fisherman sees — chat, map, safety badge, language — the whole screen. You have a head start: live sample at https://cron-system.vercel.app/orca/map/.**

> **Category ownership:** `frontend/` + `diagrams/` — `app/page.tsx` (full shell), `MapView`, `ChatPanel`, `SafetyBadge`, `LanguageSwitch`, `bhashini.ts`, `geo.ts`, map proxy `app/api/pfz/route.ts`. You call M-C's APIs (`/api/chat`, `/api/pfz/today`), you do NOT write backend agents or routers.

### Week 1 — Make the map live (you have a head start)

**Task D1 — Show 437 zones**

1. Open `frontend/components/MapView.tsx` and `frontend/app/map/page.tsx`. Your starter is already live: `https://cron-system.vercel.app/orca/map/` renders the 437 points — open `diagrams/map-prototype.html` and copy the Leaflet logic.
2. Install map libraries: `npm install leaflet react-leaflet` (already in `frontend/package.json`). Leaflet is a map library — think Google Maps but open-source.
3. Render a base map (use **Bhuvan WMS** — India's satellite map, URL is in `infra/vercel.json` — or fallback to OpenStreetMap `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` if Bhuvan is slow).
4. Fetch `GET /api/pfz/today` (Member C exposes it, Member B fills it) → loop `features` → draw a **cyan circle** for each point:
   ```tsx
   features.map(f => <CircleMarker center={[f.geometry.coordinates[1], f.geometry.coordinates[0]]} color="cyan" />)
   ```
   Highlight top picks within 60 km (Member A's ranking will tell you which).

5. Add popup on tap:
   ```
   Pallithottam
   Bearing 232  Distance 12 km  Depth 55-60m
   Source: INCOIS TextData SEC005 02-Sep
   [Green route line]
   ```

**Task D2 — React to recommendations**

When Member A's answer comes back with `map.center` (e.g., `[8.555, 76.167]`), call `map.flyTo(center, 12)` so the map smoothly zooms to the recommended zone. Draw a green route line from user's GPS `[lat,lon]` to the zone using a simple straight line in W1; Member C's `pgRouting` tiles will make it avoid forbidden zones in W2.

**Task D3 — Shell + chat wiring + safety badge**

1. Own the full shell `frontend/app/page.tsx` — left `ChatPanel` + right `MapView`, responsive (mobile stacked `flex-col`, desktop split `flex-row`), wire `ChatPanel onRecommend → MapView.flyTo`, GPS blue dot via `navigator.geolocation.getCurrentPosition`.
2. `frontend/components/ChatPanel.tsx` — text input + send → `fetch POST /api/chat` (M-C's API) → show reply + evidence + call `onMapFlyTo`. Calls `frontend/lib/bhashini.ts` (you own it) for 22-language detect (`ml` vs `en` unicode check) → process → translate back.
3. `frontend/components/SafetyBadge.tsx` — `props: {wave_m, wind_kts, danger}` → green (<1.5m, <15kt, not forbidden) / yellow / red. Read values from M-A's checks; in W1 they are mocks (always green).
4. `frontend/app/api/pfz/route.ts` — Next.js proxy with 6h `unstable_cache` + offline fallback: if fetch fails, serve `data/pfz-today.geojson` from `public/` via service worker. Fisherman at sea with no signal still sees yesterday's map.

### Week 2 — Make it navigable + offline + polished

- Replace whole-file GeoJSON fetch with tile fetch: `GET /api/tiles/{z}/{x}/{y}.pbf` from Member C's `tiles.py`. Tiles load fast on slow 2G at sea.
- GPS pin: `navigator.geolocation.getCurrentPosition` → blue dot "you are here".
- Route with avoidance: `pgRouting` cost = `wave*0.5 + wind*0.3 + forbidden_penalty (big)`. Makes route go around rough/forbidden areas.
- Fly-to animation polish + `diagrams/*` polish for SIH video screenshots — update `architecture.html` and `geojson-pipeline.html` colors/labels.
- SMS display: `POST /api/chat` also returns `sms_text` in Malayalam — show it in ChatPanel and trigger Member C's SMS gateway (you just display the button).

*Deliverable:* Live map at `https://cron-system.vercel.app/orca/map/` + responsive shell `https://cron-system.vercel.app/orca/` (W1 on mock data, W2 on tiles + real route + offline). You start from a working sample — convert `diagrams/map-prototype.html` → `MapView.tsx`.

---

## 7. Daily Schedule

| Day | Member A (Agents) | Member B (Data) | Member C (Backend API) | Member D (Frontend) |
|-----|-------------------|-----------------|------------------------|---------------------|
| **Tue 02 Sep** | Brain stub + 6 agents stubs | **pfz-today.geojson 437 POINTS (blocks all)** | FastAPI proxy `GET /api/pfz/today` + `/api/chat` stub | Map renders cyan circles from sample |
| **Wed 03 Sep** | Fish Finder + parallel `gather` | PostGIS ingest + EEZ/MPA load | 5 routers wired in `main.py`, Docker up | Bhuvan WMS + ChatPanel Bhashini `ml` detect |
| **Thu 04 Sep** | Combiner scoring `0.4/0.3/0.2/0.1` + citation | 11:30 AM cron skeleton | Tiles 501 + geofence/weather wrappers | Popup citation + SafetyBadge + shell `page.tsx` + offline proxy |
| **Fri 05 Sep 16:00** | **Global Test #1 (everyone live)** | **Global Test #1** | **Global Test #1** | **Global Test #1** |

**W2:** Mon M-B real IMD + M-A memory, Tue M-C tiles+geofence APIs real, Wed M-D SMS display + offline service worker + route avoidance, Thu freeze, **Fri 12 Sep 16:00 Global Test #2** (5 scenarios).

---

## 8. Risks and What to Do

- **INCOIS down / 404:** Use yesterday's `data/pfz-today.geojson` from Redis/disk. Warn user "data up to 24h old". Copernicus fallback comes Week 5.
- **JSESSIONID cookie expires:** `scripts/extract_pfz.sh` re-fetches TextDataHome before each sector. Retry with backoff. Member B owns this.
- **Browser CORS blocked:** Never call INCOIS directly from the browser — always go through Member D's FastAPI proxy.
- **Vercel drift:** Friday live tests catch local vs prod mismatches.

---

## 9. Where Your Work Lives

After you implement, your code lives here:

| You are | You edit | Judges see at |
|---------|----------|---------------|
| Member A | `backend/agents/*` (all 6 agents) | Agent ranking + `curl POST /api/chat` |
| Member B | `backend/ingest/*`, `backend/db/*`, `scripts/*` | `data/pfz-today.geojson` + `docker ps` |
| Member C | `backend/main.py`, `backend/routers/*` (5 routers), `infra/*` | `curl /api/pfz/today`, `/api/chat`, `/health` |
| Member D | `frontend/*` (all 9 files) + `diagrams/*` | `https://cron-system.vercel.app/orca/map/` + `https://cron-system.vercel.app/orca/` shell |

**Next read:** For the pipeline detail, see [ORCA_GeoJSON_Architecture.md](ORCA_GeoJSON_Architecture.md). For running locally, see steps in [ORCA_Codebase_Guide.md](ORCA_Codebase_Guide.md).

---

*Plan for 4 members — each lane has step-by-step tasks. If stuck, start with Week 1 Tasks for your lane and ask in standup 10:00 IST.*
