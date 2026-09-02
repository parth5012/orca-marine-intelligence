# ORCA — 2-Week MPP Development Plan

This document covers the development schedule, team assignments, and milestone deliverables for the ORCA MVP. It is the "when and who" companion to the architecture document.

**Period:** 02 September to 16 September 2026
**Scope:** INCOIS TextData to GeoJSON pipeline, Map View with 437 points, Smart Combiner, multilingual text in 22 languages, EEZ/MPA geofencing.
**Out of scope for MVP:** Voice input/output (STT/TTS), Copernicus Marine fallback data.

**For the system architecture, see** [ORCA_GeoJSON_Architecture.md](ORCA_GeoJSON_Architecture.md).
**For file locations and setup, see** [ORCA_Codebase_Guide.md](ORCA_Codebase_Guide.md).

---

## Goal

A fisherman in Kochi types a question in Malayalam. ORCA detects the language, searches 437 PFZ zones from today's INCOIS advisory, runs four specialist agents in parallel to check sea conditions, wind, and restricted zones, and returns a single safe recommendation on an interactive map with evidence citations. The entire loop demonstrates FR1 Chat, FR2 Multilingual, FR3 Location, FR4 Data Discovery, FR5 Spatio-Temporal Reasoning, FR6 Explainable Maps, FR7 Geofencing, and FR8 Evidence.

---

## Timeline

| Week | Dates | Focus | Exit Criteria |
|------|-------|-------|---------------|
| **W1 Build** | 02 to 09 Sep | TextData pipeline, Map View, Brain, Combiner, EEZ/MPA geofencing, Bhashini text integration | **Friday 05 Sep 16:00 IST — Global Test #1:** All six members run the full flow on the live Vercel deployment. Malayalam text query near Kochi produces a map pin at the correct coordinates with safety check and mock SMS. |
| **W2 Harden** | 09 to 16 Sep | Real IMD wind and cyclone data, multi-turn conversation memory, route planning, offline caching, evidence schema, polish | **Friday 12 Sep 16:00 IST — Global Test #2:** Five SIH scenarios tested end-to-end: PFZ lookup, safety assessment, lightning alert, EEZ route avoidance, and Malayalam refinement. Latency and geofence distance logged. Repository frozen for submission. |

Global tests run on the live Vercel deployment at https://cron-system.vercel.app/orca/, not on local machines. This catches CORS issues, session expiry, and deployment drift. Daily standups at 10:00 IST last 15 minutes. Friday global tests last 60 minutes.

---

## Team Assignments

### M1 — Orchestrator and Reasoning

**Responsibility:** FR1 Chat, FR5 Spatio-Temporal, FR6 Explainable Maps, FR8 Evidence.

**Week 1 deliverables:**
- Orchestrator stub with Intent detection, Planner, and Tool Router
- Smart Combiner that ranks zone candidates using weighted scoring: closest at 40%, safe sea at 30%, favorable wind at 20%, no geofence violation at 10%
- Evidence citation generation linking back to INCOIS TextData source

**Week 2 deliverables:**
- Multi-turn conversation memory using Redis (storing location, boat type, risk preference)
- Explain panel in the frontend showing "Why this zone?" with dataset citations
- Integration with all four specialist agents

**Handover artifact:** The Smart Combiner ranking algorithm and evidence schema.

### M2 — Marine Data and Ocean Analytics

**Responsibility:** FR4 Data Discovery.

**Week 1 deliverables:**
- INCOIS TextData parser: fetch SEC001 through SEC014, parse HTML tables, convert DMS coordinates to decimal, build GeoJSON FeatureCollection with 437 points
- PostGIS ingestion with spatial indexes
- Redis caching with 6-hour TTL

**Week 2 deliverables:**
- Vector tile generation using PostGIS ST_AsMVT
- Daily 11:30 AM cron job for automated ingestion
- Ingest logging and monitoring

**Handover artifact:** The `pfz-today.geojson` file with 437 live points and the PostGIS schema.

### M3 — Geospatial Visualization

**Responsibility:** FR3 Location, FR6 Explainable Maps, FR7 Geofencing display.

**Week 1 deliverables:**
- Map View using React Leaflet with 437 cyan circles for PFZ zones
- Zones within 60 kilometers highlighted as top recommendations
- Click-to-popup showing bearing, distance, and INCOIS citation
- Bhuvan WMS base layer

**Week 2 deliverables:**
- Route planning using pgRouting with cost function: wave multiplied by 0.5 plus wind multiplied by 0.3 plus forbidden zone penalty
- GPS location pin with WGS84 coordinates
- Fly-to animation when agent recommends a zone

**Handover artifact:** The live Map View at https://cron-system.vercel.app/orca/map/.

### M4 — Language Integration

**Responsibility:** FR2 Multilingual.

**Week 1 deliverables:**
- Bhashini ULCA Translate integration supporting 22 Indian languages
- Language auto-detection from input text
- "Talk to ORCA" chat interface with detect-and-respond-same-language flow
- Text-only MVP (no voice)

**Week 2 deliverables:**
- Language glossary for Hindi, Tamil, Telugu, and Malayalam
- Mixed transliteration support for Hinglish and similar patterns
- UI polish for language switch component

**Handover artifact:** The Bhashini integration and language detection pipeline. Voice STT/TTS deferred to Week 5.

### M5 — Safety and Geofencing

**Responsibility:** FR7 Geofencing, FR8 Evidence.

**Week 1 deliverables:**
- MarineRegions EEZ boundary download and PostGIS loading
- WDPA MPA boundary download and PostGIS loading
- ST_DWithin containment queries for geofence checks
- Mock wave height (0.8 meters) and mock wind data for all 437 zones

**Week 2 deliverables:**
- Real IMD wind and cyclone data from https://mausam.imd.gov.in
- Lightning alert integration
- Danger zone visualization on the map

**Handover artifact:** The geofence boundary datasets and ST_DWithin query logic. Real wave data from OSF deferred to Week 2.

### M6 — Platform and Deployment

**Responsibility:** Non-functional requirements, FR4 proxy, FR6 deployment.

**Week 1 deliverables:**
- FastAPI proxy endpoint that fetches from INCOIS server-side (bypassing browser CORS restrictions)
- Vercel deployment configuration for the cron-system project
- Docker Compose setup for PostGIS and Redis

**Week 2 deliverables:**
- SMS gateway integration for advisory delivery
- Offline GeoJSON caching using mbtiles
- Redis configuration for 6-hour PFZ cache and multi-turn memory
- PDF advisory generation for reporting

**Handover artifact:** The Docker Compose configuration and Vercel deployment pipeline.

---

## Daily Schedule — Week 1

| Day | M1 | M2 | M3 | M4 | M5 | M6 |
|-----|----|----|----|----|----|----|
| **Tue 02 Sep** | Brain stub with intent detection | pfz-today.geojson 437 points delivered | Map renders GeoJSON circles | Bhashini en-to-ml translation test | EEZ boundary download | FastAPI proxy endpoint |
| **Wed 03 Sep** | Tool Router for agent dispatch | PostGIS ingest pipeline | Bhuvan WMS base layer | "Talk to ORCA" chat UI | MPA boundary ingestion | Vercel deployment |
| **Thu 04 Sep** | Smart Combiner ranking logic | 11:30 AM automated cron | Popup with citation details | 22-language switch component | ST_DWithin geofence queries | Redis cache layer |
| **Fri 05 Sep** | Global Test #1 | Global Test #1 | Global Test #1 | Global Test #1 | Global Test #1 | Global Test #1 |

Week 2 daily plan: Monday adds real IMD wind data (M5) and conversation memory (M1). Tuesday adds route planning (M3). Wednesday adds SMS and offline caching (M6). Thursday freezes the repository. Friday runs Global Test #2 with five SIH scenarios.

---

## Dependency Chain

The critical path runs through M2. When M2 delivers the GeoJSON pipeline on Tuesday of Week 1, it unblocks M1 (agent queries), M3 (map rendering), and M5 (geofence checks). All four agents read the same GeoJSON coordinates, so M2's delivery is the single point of coordination for the entire system.

---

## Risks and Mitigations

**INCOIS TextData unavailable:** If INCOIS returns errors, the system falls back to yesterday's cached GeoJSON from Redis. The Copernicus Marine fallback is planned for Week 5.

**Session cookie expiry:** The JSESSIONID cookie expires periodically. The ingest script refreshes it by requesting TextDataHome before each sector fetch, with exponential backoff on failure.

**CORS restrictions:** INCOIS does not set CORS headers. The FastAPI backend proxies requests server-side, and the frontend fetches from the same origin.

**Vercel deployment drift:** The weekly global tests on the live deployment catch any mismatches between local and production configurations.

---

## Deliverables for Submission

- **Prototype:** Live demo at https://cron-system.vercel.app/orca/map/
- **Data:** 437 PFZ points in GeoJSON format
- **Documentation:** Architecture, MPP Plan, Codebase Guide, API Endpoints
- **Evaluation:** Five end-to-end scenarios tested and logged
- **Video:** Screen recording of the Malayalam-to-Map flow

---

*2-week MPP plan for ORCA SIH26176. For the architecture, see [ORCA_GeoJSON_Architecture.md](ORCA_GeoJSON_Architecture.md). For file locations, see [ORCA_Codebase_Guide.md](ORCA_Codebase_Guide.md).*
