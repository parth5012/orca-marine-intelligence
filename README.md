# ORCA — Agentic Marine Intelligence for Coastal Fishermen

[![SIH-26176](https://img.shields.io/badge/SIH-26176-blue.svg)](https://www.sih.gov.in/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-140%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Autonomous multi-agent intelligence platform transforming raw satellite and oceanographic data into safe, verified, multilingual voice and visual navigation advisories for 4+ million artisanal coastal fishermen.**

---

## 🌊 Problem & Mission

Indian artisanal fishermen rely on daily satellite-derived **Potential Fishing Zone (PFZ)** advisories published by **INCOIS** (Indian National Centre for Ocean Information Services). However, these advisories exist as complex HTML tables and raw satellite charts that are difficult to interpret offshore.

Fishermen urgently need:
1. **Spatial Proximity Reasoning**: *"Where is the closest productive fishing zone relative to my harbor or current GPS coordinates?"*
2. **Multi-Factor Marine Safety Checks**: Simultaneous cross-referencing against real-time waves, ocean current velocity, wind gusts, and barometric cyclone depression indicators.
3. **International Geofence Protection**: Sub-kilometer warnings before approaching the 200nm Exclusive Economic Zone (EEZ) boundaries, the 2km International Maritime Boundary Line (IMBL) buffer, or Marine Protected Areas (MPAs).
4. **Vernacular Voice Interaction**: Hands-free voice queries and audio advisories across 22 scheduled Indian languages (Malayalam, Tamil, Telugu, Bengali, Hindi, Gujarati, Marathi, Odia).

---

## 🤖 Multi-Agent Swarm Architecture

ORCA dispatches a coordinated team of specialized subagents concurrently reading shared GeoJSON spatial coordinates:

```
                          [Fisherman Voice / GPS Query]
                                       │
                                       ▼
                         [Orchestrator Agent Brain]
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
   [FishFinder]                  [SeaChecker]                 [WeatherAgent]
  • INCOIS PFZ points           • Open-Meteo Marine          • Open-Meteo Forecast
  • Distance & Bearing          • Real wave height (m)       • 10m wind speed (kt)
  • Depth & Commercial catch    • Ocean current speed (kt)   • Cyclone pressure drops
         │                             │                             │
         └─────────────────────────────┼─────────────────────────────┘
                                       ▼
                                 [DangerAgent]
                                • MarineRegions EEZ border
                                • MPA sanctuary check
                                • 2km IMBL buffer distance
                                       │
                                       ▼
                           [Smart Combiner & Veto]
                          • Multi-criteria safety rank
                          • Transparent evidence citations
                          • Bhashini 22-language TTS
```

### Agent Roles

| Agent | Module | Data Source | Primary Role |
| :--- | :--- | :--- | :--- |
| **FishFinder** | `backend/agents/subagents/fish_finder.py` | INCOIS PFZ (`data/pfz-today.geojson`) | Computes haversine proximity to 437 verified PFZ points, bearings, commercial depths. |
| **SeaChecker** | `backend/agents/subagents/sea_checker.py` | Open-Meteo Marine API | Analyzes live wave height, wave period, swell waves, and ocean current velocity/direction. |
| **WeatherAgent** | `backend/agents/subagents/weather_agent.py` | Open-Meteo Forecast API | Monitors 10m wind speed, wind gusts, and barometric depression (<995 hPa cyclone flag). |
| **DangerAgent** | `backend/agents/subagents/danger_agent.py` | MarineRegions & WDPA Polygons | Raycasting polygon containment for sovereign EEZ, MPA sanctuaries, and 2km IMBL buffers. |
| **Synthesizer** | `backend/agents/synthesizer_service.py` | Groq Llama 3.3 / Gemini Flash | Sub-second advisory synthesis, lexical secret scrubbing, and bilingual translation. |

---

## 📡 Data Infrastructure & Licensing

ORCA operates a resilient **4-tier data pipeline** combining real-time open APIs, authoritative government datasets, and offline fallback heuristics.

### 1. Open-Meteo Marine & Forecast APIs (Live Telemetry)
* **What it powers**: Live wave heights, ocean current speed/direction, 10m wind speed, gusts, and surface barometric pressure in `SeaChecker` and `WeatherAgent`.
* **Endpoints**:
  * Marine API: `https://marine-api.open-meteo.com/v1/marine`
  * Weather API: `https://api.open-meteo.com/v1/forecast`
* **Licensing & Usage Terms**:
  * **Non-Commercial / Open Source / Research**: **100% Free with NO API key required** (up to 10,000 daily requests per IP). Ideal for academic research, hackathons, and public welfare pilots.
  * **Commercial Deployments**: Open-Meteo **requires a paid commercial subscription** for commercial business operations, high-throughput enterprise SLAs, or dedicated API keys. See [Open-Meteo Pricing](https://open-meteo.com/en/pricing) for details.

### 2. INCOIS PFZ Bulletins
* **What it powers**: Satellite-derived sea surface temperature (SST) and chlorophyll-a frontal intersections indicating fish schooling zones.
* **Storage**: Ingested and normalized to standard WGS84 GeoJSON in `data/pfz-today.geojson` (437 verified coastal zones).

### 3. Marine Regions & WDPA Boundaries
* **What it powers**: Authoritative maritime boundaries for the Indian Ocean (India, Sri Lanka, Maldives EEZ 200nm polygons) and Marine Protected Areas (MPAs).
* **Storage**: Local vector boundaries in `data/eez.geojson` and `data/mpa.geojson` with PostGIS spatial indexing.

### 4. Bhashini ULCA (Digital India)
* **What it powers**: Real-time neural machine translation, Automatic Speech Recognition (ASR), and Text-to-Speech (TTS) across 22 scheduled Indian languages.

---

## ⚡ Redis Architecture: Upstash vs. Local Docker

ORCA uses Redis for **6-hour PFZ caching**, **multi-turn conversational memory**, and **cross-agent request deduplication**.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      REDIS DEPLOYMENT STRATEGY                          │
├────────────────────────────────────┬────────────────────────────────────┤
│ ☁️ CLOUD / STAGING (UPSTASH)        │ 🐳 LOCAL DEV / TESTING (DOCKER)    │
│ • Serverless, fully managed        │ • Zero-network latency (<1ms)      │
│ • Permanent Free Tier: 256 MB      │ • Unlimited throughput             │
│ • 10,000 commands / day            │ • Offline capable                  │
│ • Native TLS rediss:// protocol    │ • redis:7-alpine container         │
│ • Perfect for Vercel & Render      │ • Ideal for rapid test runs        │
└────────────────────────────────────┴────────────────────────────────────┘
```

### Upstash Redis Free Tier Specifications
* **Storage Limit**: **256 MB** (ORCA's full PFZ cache takes <150 KB; 256 MB comfortably holds over **1,500 daily PFZ snapshots** and **50,000+ active chat sessions**).
* **Daily Command Cap**: **10,000 commands/day** free forever.
* **Max Concurrent Connections**: 1,000.
* **Credit Card Required**: **No**.
* **Configuration**: Set in `.env`:
  ```env
  REDIS_URL=rediss://default:<YOUR_PASSWORD>@<YOUR_UPSTASH_ENDPOINT>.upstash.io:6379
  ```

### Local Docker Redis Setup
To run Redis locally:
```bash
# Using Docker directly
docker run -d --name orca-redis -p 6379:6379 redis:7-alpine

# Or using the repository compose file
docker compose -f infra/docker-compose.yml up -d redis
```
Set in `.env`:
```env
REDIS_URL=redis://localhost:6379/0
```

---

## 🛡️ Marine Safety Decision Matrix

Every candidate point is evaluated across strict physical and legal safety bands:

| Parameter | 🟢 Safe | 🟡 Caution | 🔴 Danger (Veto) |
| :--- | :--- | :--- | :--- |
| **Significant Wave Height** | `< 1.5 m` | `1.5 m — 2.5 m` | `> 2.5 m` |
| **Ocean Current Speed** | `< 1.5 kt` | `1.5 kt — 2.5 kt` | `> 2.5 kt` |
| **10m Sustained Wind** | `< 15 kt` | `15 kt — 25 kt` (Small craft warning) | `> 25 kt` (Gale warning) |
| **Barometric Pressure** | `> 1005 hPa` | `995 — 1005 hPa` (Depression) | `< 995 hPa` (Cyclone alert) |
| **EEZ Maritime Boundary** | `> 10 km` inside | `2 km — 10 km` from border | `< 2 km` / Beyond border |
| **Marine Protected Area** | Outside | Buffer zone | Inside no-take sanctuary |

---

## 🚀 Quick Start

### Prerequisites
* **Python 3.11+**
* **Docker Desktop** (or an **Upstash Redis** account)
* **Node.js 18+** (for frontend map & chat interface)

### 1. Clone & Configure
```bash
git clone https://github.com/parth5012/orca-marine-intelligence.git
cd orca-marine-intelligence

# Copy environment template
cp .env.example .env
```

Edit `.env` with your settings:
```env
# Choose data source: live (real Open-Meteo & GeoJSON) or mock (deterministic offline simulation)
ORCA_DATA_SOURCE=live

# Redis connection (Upstash or local Docker)
REDIS_URL=redis://localhost:6379/0

# Optional keys for LLM and multilingual voice
BHASHINI_API_KEY=your_bhashini_key_here
GROQ_API_KEY=your_groq_api_key_here
```

### 2. Start Redis & Infrastructure
```bash
# Start local Redis (or point .env to Upstash)
docker compose -f infra/docker-compose.yml up -d redis
```

### 3. Run Backend API
```bash
# Install Python dependencies (prefer using uv or pip)
pip install -r backend/requirements.txt

# Start FastAPI server on port 8000
python -m uvicorn backend.main:app --reload --port 8000
```
API Documentation will be available at `http://localhost:8000/docs`.

### 4. Run Frontend (Map & Vernacular Chat)
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:3000` in your browser.

---

## 🧪 Testing & Verification

ORCA separates **unit/integration tests** (CI gate — must be green to merge)
from **LLM quality evals** (measure-only LangSmith harness — tracks baselines,
never blocks). See [`evals/README.md`](evals/README.md) for the eval guide.

```bash
# Unit + API + integration tests (35 files, fully mocked, fast)
python -m pytest tests -q

# LLM quality evals (5 files, offline, 7 evaluators over 146+ examples)
python -m pytest evals -q

# Everything
python -m pytest tests evals -q

# Full offline scorecard (14 buckets × 23 languages matrix)
python -m backend.evals.runner --out reports/golden_v1_scorecard.md
```

---

## 📊 Visual Platform Research

For a deep comparison of **30+ free marine, atmospheric, satellite, and geospatial data sources**, open our self-contained interactive dashboard:
* **Interactive Findings Dashboard**: `diagrams/free-data-platforms/index.html` (Master-detail layout with complete quota, protocol, and code snippets).

---

## 📜 Data Attribution & Acknowledgements

* **INCOIS (Ministry of Earth Sciences, Govt. of India)**: Potential Fishing Zone (PFZ) advisory data and ocean state bulletins.
* **Open-Meteo**: High-resolution global marine wave and atmospheric forecasts.
* **Marine Regions (VLIZ Flanders Marine Institute)**: Global Maritime Boundaries (EEZ 200nm, Territorial Waters).
* **WDPA (UNEP-WCMC / IUCN)**: World Database on Protected Areas (MPA sanctuaries).
* **Bhashini (MeitY, Govt. of India)**: National Language Translation Mission for 22 scheduled Indian languages.
* **Upstash**: Serverless Redis caching infrastructure.

---

## 📄 License

Distributed under the **MIT License**. Third-party datasets and APIs retain their respective open-access licenses as detailed in [DATA_LICENSES.md](DATA_LICENSES.md).
