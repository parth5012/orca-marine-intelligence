# Contributing to ORCA — Agentic Marine Intelligence (SIH26176)

Thank you for contributing! This guide explains how to work on ORCA without breaking `main`, how our 5-member category split works, and how to create a Pull Request to the central repository.

**Central repo:** `https://github.com/parth5012/orca-marine-intelligence` — `main` branch is protected.  
**Official PS:** [SIH26176 — ISRO](https://github.com/vedantchalke36/sih-2026-problem-statements/blob/main/ps_2026/SIH26176.md)

---

## 1) Quick Start (first time)

```bash
# 1. Clone the central repo (or your fork — see §2)
git clone https://github.com/parth5012/orca-marine-intelligence.git
cd orca-marine-intelligence

# 2. Never work on main — create your feature branch (see §3)
git checkout main
git pull origin main
git checkout -b feat/m-a-orchestrator   # use your member prefix (see table below)

# 3. Set up env + infra (one-time)
cp .env.example .env   # fill INCOIS_JSESSIONID, BHASHINI_API_KEY (see README)
docker compose -f infra/docker-compose.yml up -d   # PostGIS 5432 + Redis 6379

# 4. Install deps (when you touch backend or frontend)
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
```

---

## 2) Fork vs. Branch (choose one workflow)

**If you are a team member with write access:** Branch directly on the central repo (simplest).

**If you are an external contributor (no write access):**

```bash
# 1. Fork on GitHub: open https://github.com/parth5012/orca-marine-intelligence → Fork (top right)
# 2. Clone YOUR fork
git clone https://github.com/YOUR_USERNAME/orca-marine-intelligence.git
cd orca-marine-intelligence

# 3. Add central repo as upstream (so you can pull latest main)
git remote add upstream https://github.com/parth5012/orca-marine-intelligence.git
git fetch upstream
git checkout main
git merge upstream/main   # keep your fork in sync
git push origin main
```

When you create a PR, the base will be `parth5012:main` and the head will be `YOUR_USERNAME:your-branch`. GitHub shows this automatically when you push a fork.

---

## 3) Who Works Where (5-member category split — no mixed files)

One tech stack per person → no merge conflicts. Don't edit files outside your lane without asking in standup.

| You are | Category | Branch prefix | You own (folder) |
|---------|----------|---------------|------------------|
| **M-A** | **Agents & Orchestration** | `feat/m-a-` | `backend/agents/` — 6 agents (orchestrator, combiner, fish_finder, sea_checker, weather_agent, danger_agent) |
| **M-B** | **Data Extractors & Storage** | `feat/m-b-` | `backend/ingest/` + `backend/db/` + `scripts/` + `data/` |
| **M-C** | **Backend API & Platform** | `feat/m-c-` | `backend/routers/` + `backend/main.py` + `infra/` |
| **M-D** | **Frontend Map** | `feat/m-d-` | `frontend/map/` + `frontend/app/map/` + `frontend/app/api/pfz/` + `diagrams/` |
| **M-E** | **Frontend Chat & App Shell** | `feat/m-e-` | `frontend/chat/` + `frontend/app/page.tsx` |

Also:
- `docs/notion/` — anyone, but mention in PR which member's guide changed.
- `README.md`, `.env.example` — M-C (Backend API) owns keeping them updated, others can PR with `docs:` prefix.

**Branch examples:**

```
feat/m-a-combiner-scoring
feat/m-b-textdata-14-sector-parse
feat/m-c-pfz-cors-proxy
feat/m-d-mapview-cyan-circles
feat/m-e-chatpanel-bhashini
fix/m-b-jsessionid-refresh
docs/notion-core-overview
```

> **Rule:** One branch = one focused change. Don't mix agent + map in one branch.

---

## 4) Create a Branch (do this for every task)

```bash
# Always start from latest main
git checkout main
git pull origin main
# or if you're on a fork: git pull upstream main && git push origin main

# Create your feature branch
git checkout -b feat/m-a-orchestrator
# Now you are on feat/m-a-orchestrator — do your work here, never on main
```

---

## 5) Do Your Work (with checks)

### Before you code

1. Open your file's `Owner: M-X` header + TODOs — it tells you what to implement.
2. Read `docs/API.md` if you touch a URL — request/response shape is there.
3. If you change a table, update `backend/db/schema.sql` first, then `docker compose down -v && docker compose up -d` to re-apply.

### Code standards

**Backend (Python, `backend/`):**
- PEP 8 + type hints on all public functions (`def find_zones(lat: float) -> list[dict]:`)
- Docstring for every module/function
- `async/await` for all I/O (FastAPI is async)
- Use `psycopg` for PostGIS, `redis-py` for Redis — via `backend/db/postgis.py` / `redis.py` helpers, not raw connections

**Frontend (TypeScript, `frontend/`):**
- `strict: true` in `tsconfig.json` — no `any`
- Define `interface Props` for every component
- Import via barrels: `import { ChatPanel } from "@/chat"` and `import { MapView } from "@/map"` (not `../chat/ChatPanel`)
- Functional components + hooks

**GeoJSON:**
- WGS84 (EPSG:4326), `Point(lon, lat)` — lon first
- Always include `properties: {zone_id, place, sector, source, timestamp}`

### Test locally before you commit

```bash
# Backend — from repo root
docker compose -f infra/docker-compose.yml up -d
cd backend && python -m pytest -q   # when tests exist
cd ..
curl http://localhost:8000/health  # must be 200
curl http://localhost:8000/api/pfz/today | head

# Frontend — from repo root
cd frontend && npm run lint && npm run build
npm run dev  # http://localhost:3000  +  http://localhost:3000/map
# Verify: Malayalam "എവിടെ മത്സ്യം?" → map flies + badge green + citation appears
```

No PR should break `main`'s ability to `docker compose up` + `npm run dev` + `curl /health`.

---

## 6) Commit (small, clear commits)

```bash
git status --short
git add <only your files>        # don't git add -A blindly if you have unrelated local files
git commit -m "feat: implement combiner scoring 0.4/0.3/0.2/0.1 with citation"
```

**Commit message format:**

- Use prefix `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`
- Scope is optional but helpful: `feat(agents): ...`, `fix(data): ...`, `docs(notion): ...`
- For Member A/B/C/D/E, you can also use member prefix in body: `M-A: ...` but title stays conventional. Example:

```
feat: implement combiner scoring with evidence citation

M-A: closest*0.4 + sea*0.3 + wind*0.2 + not_forbidden*0.1
Implements INCOIS citation "INCOIS TextData SEC005 KERALA 02-Sep"
Test: fish_finder 12km/0.8m beats 8km/2.8m in unit test
```

**Rules:**
- Imperative mood: "Add feature" not "Added feature"
- Subject ≤ 72 chars
- One logical change per commit — keep `main` history clean for judges

**Do NOT include:**
- `Co-Authored-By` / agent footers
- Secrets (`.env`) — it is gitignored, never force-add

---

## 7) Push Your Branch

**If branch is on central repo (team member):**

```bash
git push -u origin feat/m-a-orchestrator
```

**If branch is on your fork (external contributor):**

```bash
git push -u origin feat/m-a-orchestrator
# origin = your fork (YOUR_USERNAME/orca-marine-intelligence)
# Keep fork in sync before pushing:
git fetch upstream
git rebase upstream/main   # or merge, but rebase keeps history linear
```

---

## 8) Create a Pull Request to Central `main`

### On GitHub (central workflow)

1. Push your branch (previous step).
2. GitHub shows a yellow banner: **"Compare & pull request"** → click it.
   - Or go to `https://github.com/parth5012/orca-marine-intelligence` → **Pull requests** → **New pull request** → choose base `main` ← compare your branch.
3. **Fill the PR form** (use the template below):

```markdown
## What changed
- Implement `backend/agents/combiner.py` scoring + citation

## Why
- Unblocks M-C's `POST /api/chat` which calls the combiner; needed for Fri 05 Sep Global Test #1

## How to test
- [ ] `docker compose -f infra/docker-compose.yml up -d`
- [ ] `curl -X POST http://localhost:8000/api/chat -d '{"message":"Where is fish near Kochi?","lat":9.93,"lon":76.26}' | jq .evidence`
- [ ] Chat in Malayalam "എവിടെ മത്സ്യം?" → map flies

## Screenshots (if UI)
- After vs before (for MapView / ChatPanel / SafetyBadge)

## Checklist
- [ ] No files outside my lane (M-A/B/C/D/E) without mention
- [ ] `npm run build` / `pytest` passes locally
- [ ] No secrets committed (`.env` not in diff)
```

4. **Request reviewer:** Add 1 team member (or `parth5012`) as reviewer. Don't merge yourself.
5. **CI must pass:** Vercel preview + lint/typecheck must be green.

### From a fork (external contributor)

Base: `parth5012/orca-marine-intelligence:main` ← Compare: `YOUR_USERNAME:feat/m-a-orchestrator`. Title stays same. The maintainer will merge your fork PR into central `main`.

---

## 9) Review & Merge (how `main` stays protected)

- `main` requires **1 approval** + **all CI green** + **no force pushes**.
- Address review comments by pushing **new commits** to the same branch (don't close the PR). GitHub updates the PR automatically.
- After approval, maintainer does **Squash merge** → keeps `main` history as one clean commit per PR (judges see a clean log).

**If CI fails:**
- Read the Vercel preview log / lint error, fix on your branch, push again — PR updates.

**If your branch is behind `main` (conflict):**

```bash
git checkout feat/m-a-orchestrator
git fetch origin
git rebase origin/main
# fix conflicts (open files, remove <<<<<< markers, git add each fixed file)
git rebase --continue
git push --force-with-lease   # rebase needs force-with-lease, never --force on main
```

---

## 10) After Merge

```bash
# Update your local main
git checkout main
git pull origin main   # or upstream/main if fork

# Delete your feature branch (optional, keeps repo tidy)
git branch -d feat/m-a-orchestrator
git push origin --delete feat/m-a-orchestrator   # deletes remote branch
```

---

## 11) Weekly Rhythm (so no one blocks)

- **Daily standup:** 10:00 IST, 15m — what you shipped, what you are blocked on
- **Global Test #1:** Fri 05 Sep 16:00 IST — everyone on live Vercel `https://cron-system.vercel.app/orca/` (Malayalam near Kochi → pin + badge + citation)
- **Global Test #2:** Fri 12 Sep 16:00 IST — 5 SIH scenarios, log P50 + geofence distance, then freeze `main` for SIH submission (due 20 Sep)

**Critical path:** M-B must deliver `data/pfz-today.geojson` 437 on Tue 02 Sep — A cannot rank, C cannot serve `/api/pfz/today`, D/E cannot draw dots or chat until then.

---

## 12) Questions?

- Open a GitHub Issue with label `question` or `help wanted`
- Ask in team channel / standup — mention your member (M-A/B/C/D/E) and lane
- For quick local check: `CONTRIBUTING.md` → this file; `README.md` → 4-step run; `docs/ORCA_Codebase_Guide.md` → which file does what

---

*This guide reflects the 5-member category split: M-A Agents, M-B Data, M-C Backend API, M-D Map, M-E Chat & Shell. One stack per person, no mixed files, no direct commits to `main` — every change goes via Pull Request to central `main`.*
