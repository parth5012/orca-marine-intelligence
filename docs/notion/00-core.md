# ORCA — Core Overview (Copy this to Notion → "ORCA Core")

> **Paste tip:** In Notion, type `/import` → paste this markdown, or create a page and press `Ctrl+Shift+V`.

**Project:** ORCA Marine EcOsystem Reasoning with Collaborative Agents — ISRO  
**Official PS:** [SIH26176 — sih.gov.in](https://github.com/vedantchalke36/sih-2026-problem-statements/blob/main/ps_2026/SIH26176.md) — Software · Disaster Management · Idea due **20 Sep 2026**  
**Repo:** https://github.com/parth5012/orca-marine-intelligence  
**Live demo (temporary):** https://cron-system.vercel.app/orca/ · Map: https://cron-system.vercel.app/orca/map/ · Data: https://cron-system.vercel.app/orca/map/data/pfz-today.geojson  
**Team:** 4 members — [M-A Agents](#team), [M-B Data](#team), [M-C Backend API](#team), [M-D Frontend](#team)  
**Period:** 02 Sep → 16 Sep 2026 (14 days, code freeze 12 Sep, 8-day buffer to submission)

---

## 1) What we are building (in one paragraph)

A fisherman in Kochi types **"എവിടെ മത്സ്യം?"** (Where is fish?) in Malayalam. ORCA detects the language, looks up today's **437 INCOIS fishing zones**, runs **6 agents in parallel** on the same dots (closest + wave + wind + forbidden zones + ranking), and returns **one safest spot on a map with proof** (place, bearing, distance, citation `INCOIS TextData SEC005 KERALA 02-Sep`) + a green route + SMS in Malayalam. This proves ISRO's Expected Solution: same-language reply, multi-turn refinement, data discovery, spatial-temporal reasoning, explainable maps/evidence, safety alerts, geofencing, and route optimization.

**Sample queries directly from ISRO PS we must handle:**
PFZ today, safety tomorrow morning, tide/weather at location, lightning/cyclone alerts, chlorophyll/SST hotspots, safest route, productivity decline, avoid hazardous/geofenced zones.

---

## 2) MVP scope (what is IN vs OUT)

**IN for MVP (must work by 12 Sep):**
- Table → GeoJSON pipeline (INCOIS SEC001-014 → `data/pfz-today.geojson` 437 pts)
- Map with 437 cyan circles + popup + fly-to + green route
- 6 agents + ranking `closest*0.4 + sea*0.3 + wind*0.2 + not_forbidden*0.1` with citation
- **Multilingual text (22 Indian languages via Bhashini) — same-language reply is MVP per ISRO PS, not W2 polish**
- Multi-turn refinement (`session_id` → Redis)
- Explainable evidence + safety badge (green/yellow/red)
- Geofencing (EEZ, MPA, 2km IMBL warning) + basic cyclone/wind checks
- Backend APIs (5 routers) + Docker + Vercel live deploy + offline fallback

**OUT for MVP (deferred):**
- Voice input/output (STT/TTS) — W5
- Copernicus Marine fallback (chlorophyll/SST satellite) — W5
- Tiles `ST_AsMVT` is W2 (W1 fetches whole GeoJSON file)

---

## 3) How it works (pipeline → shared list → helpers → decider)

```
[INCOIS SEC001-014 HTML 7-col] --JSESSIONID--> parse DMS "8 33 18 N → 8.555" → GeoJSON 437 Points → PostGIS + Redis (6h)
                                                                              ↓
                              Fish Finder  Sea Checker  Weather  Danger Watch  (M-A, same lat/lon)
                                                                              ↓
                                    Smart Combiner (M-A)  closest*0.4 + sea*0.3 + wind*0.2 + not_forbidden*0.1
                                                                              ↓
                                           MapView (M-D) + SafetyBadge  ←  Backend APIs (M-C)  →  ChatPanel (M-D)
```

**Shared list idea:** Without one shared GeoJSON, helpers would disagree ("fish here but storm here"). With shared dots, the decider sees all 4 scores per dot and picks the safest.

**Full plain-English architecture:** [`docs/ORCA_GeoJSON_Architecture.md`](../ORCA_GeoJSON_Architecture.md)

---

## 4) Team — category split (one stack per person, no mixed files)

| Member | Category | Folder you own | Files | Your Week 1 head start |
|--------|----------|----------------|-------|------------------------|
| **M-A** | **Agents & Orchestration** | `backend/agents/` | `orchestrator.py`, `combiner.py`, `fish_finder.py`, `sea_checker.py`, `weather_agent.py`, `danger_agent.py` | All intelligence, parallel `asyncio.gather` |
| **M-B** | **Data Extractors & Storage** | `backend/ingest/` + `backend/db/` + `scripts/` | `incois_textdata.py`, `boundaries.py`, `postgis.py`, `redis.py`, `schema.sql`, `extract_pfz.sh`, `dms_to_decimal.py` | **Tue blocking deliverable** — `pfz-today.geojson` 437 |
| **M-C** | **Backend API & Platform** | `backend/routers/` + `backend/main.py` + `infra/` | `main.py`, `pfz.py`, `tiles.py`, `chat.py`, `geofence.py`, `weather.py`, `docker-compose.yml`, `vercel.json` | Wraps M-A's agents as URLs, fixes CORS |
| **M-D** | **Frontend Map** | `frontend/map/` + `frontend/app/map/` + `diagrams/` | `map/MapView.tsx`, `map/SafetyBadge.tsx`, `map/geo.ts`, `map/index.ts`, `app/map/page.tsx`, `app/api/pfz/route.ts` (map proxy) | Has live sample at `https://cron-system.vercel.app/orca/map/` — convert `diagrams/map-prototype.html` → `map/MapView.tsx` |
| **M-E** | **Frontend Chat & App Shell** | `frontend/chat/` + `frontend/app/page.tsx` | `chat/ChatPanel.tsx`, `chat/LanguageSwitch.tsx`, `chat/bhashini.ts`, `chat/index.ts`, `app/page.tsx` (shell wires chat→map) | Owns shell (left ChatPanel + right MapView + flyTo) — the app UI |

Each member's detailed page (paste to Notion as sub-pages):
- **M-A:** [`01-m1-agents.md`](01-m1-agents.md)
- **M-B:** [`02-m2-data.md`](02-m2-data.md)
- **M-C:** [`03-m3-backend-api.md`](03-m3-backend-api.md)
- **M-D:** [`04-m4-frontend-map.md`](04-m4-frontend-map.md) (Map)
- **M-E:** [`05-m5-frontend-chat.md`](05-m5-frontend-chat.md) (Chat & App Shell)

---

## 5) Timeline — 2 weekly milestones

| Week | Dates | Focus | Exit criteria (must pass on live Vercel) |
|------|-------|-------|-------------------------------------------|
| **W1 Build** | 02–09 Sep | Pipeline + brain + map + APIs + geofencing + Bhashini text | **Fri 05 Sep 16:00 IST — Global Test #1:** All 4 run live. Malayalam near Kochi → correct map pin + green badge + evidence citation + mock SMS. |
| **W2 Harden** | 09–16 Sep | Real IMD data, memory, tiles, route, offline, polish | **Fri 12 Sep 16:00 IST — Global Test #2:** 5 scenarios: PFZ today → safety → lightning → avoid forbidden via route → Malayalam refinement. Log P50 + geofence distance. Freeze for SIH. |

**Daily:** Tue delivers 437 (M-B blocks all). Wed ingest+routers+map, Thu scoring+popup+cache, Fri everyone tests. Daily standup 10:00 IST (15m), Fri test 60m.

---

## 6) Daily schedule (4 lanes)

| Day | M-A (Agents) | M-B (Data) | M-C (Backend API) | M-D (Frontend) |
|-----|--------------|------------|-------------------|----------------|
| **Tue 02 Sep** | Brain stub + 6 agents stubs | **pfz-today.geojson 437 (blocks all)** | FastAPI proxy `/api/pfz/today` + `/api/chat` stub | Map renders cyan circles from sample |
| **Wed 03 Sep** | Fish Finder + parallel `gather` | PostGIS ingest + EEZ/MPA load | 5 routers wired in `main.py`, Docker up | Bhuvan WMS + ChatPanel `ml` detect |
| **Thu 04 Sep** | Combiner `0.4/0.3/0.2/0.1` + citation | 11:30 AM cron skeleton | Tiles 501 + geofence/weather wrappers | Popup citation + SafetyBadge + shell `page.tsx` + offline proxy |
| **Fri 05 Sep** | **Global Test #1** | **Global Test #1** | **Global Test #1** | **Global Test #1** |

**W2:** Mon M-B IMD + M-A memory, Tue M-C tiles real, Wed M-D SMS display + offline + route avoidance, Thu freeze, **Fri 12 Sep Global Test #2**.

---

## 7) Dependencies & risks

- **B is critical path Tue** → A cannot rank, C cannot serve `/api/pfz/today`, D cannot draw dots until B delivers.
- **INCOIS 404 / JSESSIONID expiry:** M-B re-fetches `TextDataHome` for new cookie before each SEC, retry 3× backoff. Fallback to yesterday's `data/pfz-today.geojson` from Redis/disk, warn "data up to 24h old".
- **CORS blocked:** Never call INCOIS from browser — always `GET /api/pfz/today` via M-C's FastAPI proxy.
- **Vercel drift:** Friday live tests catch local vs prod.

---

## 8) How to run (any member, 4 steps)

```bash
git clone https://github.com/parth5012/orca-marine-intelligence.git
cd orca-marine-intelligence
cp .env.example .env   # fill INCOIS_JSESSIONID, BHASHINI_API_KEY

docker compose -f infra/docker-compose.yml up -d   # PostGIS 5432 + Redis 6379
bash scripts/extract_pfz.sh                       # 437 points → data/pfz-today.geojson

cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000  # /health
# new terminal:
cd frontend && npm install && npm run dev  # http://localhost:3000  +  /map
```

**Docs:** [How ORCA works](../ORCA_GeoJSON_Architecture.md) · [Files & run](../ORCA_Codebase_Guide.md) · [API details](../API.md) · [CONTRIBUTING](../CONTRIBUTING.md) (branch `feat/m-a-agents` etc., PR needs 1 review)

---

*Paste this as Notion parent page. Create 4 child pages and paste M-A..M-D files below.*
