# ORCA — Codebase Guide

This document describes the project structure, what each file does, and how to run the system locally.

> **Current Status (02 Sep 2026):** The repository contains documentation, data files (437 PFZ points), and scaffold stubs with TODOs. The agents, routers, and frontend components are defined but not yet implemented. This guide covers both the current files and the proposed structure for the full MVP.

**For the architecture and data flow, see** [ORCA_GeoJSON_Architecture.md](ORCA_GeoJSON_Architecture.md).
**For the development schedule, see** [ORCA_2Week_MPP_Plan.md](ORCA_2Week_MPP_Plan.md).
**For API endpoint details, see** [API.md](API.md).

---

## Project Structure

```
orca-marine-intelligence/
├── README.md                          # Project overview and quick start
├── CONTRIBUTING.md                    # Branch conventions and PR workflow
├── .env.example                       # Environment variable template
├── .gitignore                         # Git ignore rules
├── docs/
│   ├── ORCA_GeoJSON_Architecture.md   # How the system works
│   ├── ORCA_Codebase_Guide.md         # This file
│   ├── ORCA_2Week_MPP_Plan.md        # Development schedule
│   └── API.md                         # API endpoint catalog
├── data/
│   ├── pfz-today.geojson              # Today's 437 PFZ points (live data)
│   └── pfz-all.json                   # Full PFZ dataset with DMS coordinates
├── frontend/                          # Next.js 14 application
│   ├── app/
│   │   ├── page.tsx                   # Root layout (Chat + Map split view)
│   │   ├── map/page.tsx               # Standalone map view
│   │   └── api/pfz/route.ts           # Server-side PFZ proxy
│   ├── components/
│   │   ├── ChatPanel.tsx              # Conversational chat interface
│   │   ├── MapView.tsx                # Interactive map with PFZ overlays
│   │   ├── SafetyBadge.tsx            # Safety status indicator
│   │   └── LanguageSwitch.tsx         # 22-language selector
│   ├── lib/
│   │   ├── bhashini.ts                # Bhashini ULCA language services
│   │   └── geo.ts                     # Geographic calculation utilities
│   ├── package.json                   # Node.js dependencies
│   └── tsconfig.json                  # TypeScript configuration
├── backend/                           # FastAPI application
│   ├── main.py                        # Application entry point and CORS
│   ├── agents/
│   │   ├── orchestrator.py            # Multi-agent coordinator (Brain)
│   │   ├── fish_finder.py             # PFZ zone proximity search
│   │   ├── sea_checker.py             # Wave height and current evaluation
│   │   ├── weather_agent.py           # Wind speed and tide assessment
│   │   ├── danger_agent.py            # EEZ/MPA geofence and cyclone checks
│   │   └── combiner.py                # Smart ranking and evidence generation
│   ├── ingest/
│   │   ├── incois_textdata.py         # INCOIS TextData HTML parser
│   │   ├── copernicus_fallback.py     # Copernicus Marine fallback (Week 5)
│   │   └── boundaries.py              # EEZ/MPA boundary loader
│   ├── routers/
│   │   ├── pfz.py                     # PFZ data endpoints
│   │   ├── tiles.py                   # Vector tile server
│   │   ├── chat.py                    # Chat endpoint for the Brain
│   │   ├── weather.py                 # Weather data endpoints
│   │   └── geofence.py               # Geofence check endpoints
│   ├── db/
│   │   ├── postgis.py                 # PostGIS connection and queries
│   │   ├── redis.py                   # Redis cache and session management
│   │   └── schema.sql                 # Database table definitions
│   ├── requirements.txt               # Python dependencies
│   └── Dockerfile                     # Backend container definition
├── infra/
│   ├── docker-compose.yml             # PostGIS + Redis + Backend services
│   └── vercel.json                    # Vercel deployment configuration
└── scripts/
    ├── extract_pfz.sh                 # PFZ data extraction shell script
    └── dms_to_decimal.py              # DMS coordinate converter
```

---

## Key Files — What Each Does

### Backend Agents

**orchestrator.py** — The central coordinator that receives user queries, detects intent, and dispatches sub-tasks to the four specialist agents. It uses a ReAct-style pattern to decide which tools to call and handles multi-turn conversation memory via Redis.

**fish_finder.py** — Queries the PostGIS database for PFZ zones within a configurable radius of the user's location. Returns the closest zones ranked by proximity with metadata like sector, bearing, and depth.

**sea_checker.py** — Evaluates wave height and current speed at each candidate zone. Returns a safety assessment (safe, caution, or danger) based on configurable thresholds.

**weather_agent.py** — Assesses wind speed and tide conditions at each candidate zone. In the MVP it returns mock data; in Week 2 it will integrate with IMD's marine weather API.

**danger_agent.py** — Checks candidate zones against EEZ and MPA boundaries using PostGIS spatial containment queries. Also monitors active cyclone warnings from IMD.

**combiner.py** — After all agents return their assessments, the Combiner ranks candidates using a weighted scoring formula and produces a single safe recommendation with evidence citations.

### Backend Routers

**pfz.py** — Serves PFZ data to the frontend. The `GET /api/pfz/today` endpoint returns today's GeoJSON FeatureCollection, cached in Redis for 6 hours.

**tiles.py** — Generates Mapbox Vector Tiles from PostGIS using `ST_AsMVT`. The frontend map fetches these tiles for efficient rendering of large datasets.

**chat.py** — The conversational interface endpoint. Accepts user queries, dispatches them to the Orchestrator, and returns advisory responses with map references and safety information.

**weather.py** — Serves weather data for marine advisory, including wind speed, wave height, and cyclone warnings.

**geofence.py** — Provides geofence checking endpoints for points and routes against EEZ and MPA boundaries.

### Backend Data Layer

**postgis.py** — Connection pooling and query helpers for PostGIS. Provides functions for upserting PFZ features, spatial proximity searches, and boundary containment checks.

**redis.py** — Redis connection management and caching helpers. Handles PFZ data caching, tile caching, and multi-turn conversation memory.

**schema.sql** — PostGIS table definitions for pfz_zones, eez_boundaries, mpa_boundaries, and ingest_log, with spatial indexes for fast queries.

### Frontend Components

**ChatPanel.tsx** — The conversational chat interface where users type or speak queries in any of 22 supported languages. Displays agent responses with map references and safety badges.

**MapView.tsx** — An interactive map built with React Leaflet that displays PFZ zones as colored circles, EEZ/MPA boundaries, and agent recommendation overlays. Supports fly-to animations and popup details.

**SafetyBadge.tsx** — A color-coded safety indicator showing wave height, wind speed, and danger status at a glance. Green means safe, amber means caution, red means danger.

**LanguageSwitch.tsx** — A language selector supporting 22 Indian languages via the Bhashini ULCA API. Auto-detects input language and allows manual override.

### Frontend Library

**bhashini.ts** — Client for the Bhashini ULCA API providing language detection, translation, and (in Week 3) speech-to-text and text-to-speech.

**geo.ts** — Client-side geographic utilities for haversine distance, bearing calculation, DMS formatting, and location extraction from text.

### Data Files

**pfz-today.geojson** — The live GeoJSON FeatureCollection containing 437 PFZ zone points. This is the shared data model that all agents query. Updated daily at 11:30 AM IST from INCOIS TextData.

**pfz-all.json** — The full PFZ dataset including DMS coordinates and all metadata fields. Used for development and testing.

---

## How to Run Locally

### Prerequisites

- Docker and Docker Compose
- Node.js 18 or later
- Python 3.11 or later

### Step 1: Clone and Configure

Clone the repository and create your environment file:

```bash
git clone https://github.com/yourteam/orca-marine-intelligence.git
cd orca-marine-intelligence
cp .env.example .env
```

Edit `.env` and fill in your INCOIS JSESSIONID and Bhashini API key. The PostGIS and Redis URLs can stay as-is for Docker development.

### Step 2: Start Infrastructure

Launch PostGIS and Redis with Docker Compose:

```bash
docker compose -f infra/docker-compose.yml up -d
```

This starts PostGIS on port 5432 (with the schema auto-loaded) and Redis on port 6379.

### Step 3: Ingest PFZ Data

Fetch today's PFZ data from INCOIS:

```bash
INCOIS_JSESSIONID=<your-session-id> bash scripts/extract_pfz.sh
```

This creates `data/pfz-today.geojson` with today's 437 PFZ points.

### Step 4: Start the Backend

Install Python dependencies and start the FastAPI server:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Verify it works: `curl http://localhost:8000/health`

### Step 5: Start the Frontend

Install Node.js dependencies and start the Next.js development server:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 to see the Chat + Map split view. The standalone map is at http://localhost:3000/map.

---

## Running with Docker (Full Stack)

To run everything in containers:

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

This builds and starts PostGIS, Redis, and the FastAPI backend. The frontend runs separately with `npm run dev` during development.

---

## Team Ownership

Each file has an owner responsible for its implementation. See the `Owner` comment at the top of each file for the assigned team member (M1 through M6).

| Milestone | Owner | Scope |
|-----------|-------|-------|
| M1 | Orchestrator Lead | Orchestrator, Combiner, reasoning logic |
| M2 | Data Engineer | TextData ingestion, PostGIS, tiles |
| M3 | AI Engineer | Chat endpoint, Bhashini integration |
| M4 | Maps Engineer | MapView, Leaflet, vector tiles |
| M5 | Safety Engineer | Geofencing, weather, danger assessment |
| M6 | Platform Engineer | FastAPI, Docker, Vercel, deployment |

---

*Codebase guide for ORCA SIH26176. For the architecture, see [ORCA_GeoJSON_Architecture.md](ORCA_GeoJSON_Architecture.md). For the schedule, see [ORCA_2Week_MPP_Plan.md](ORCA_2Week_MPP_Plan.md).*
