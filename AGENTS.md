# AGENTS.md — ORCA Marine Intelligence

> General-purpose harness guide. **Not prescriptive** — use this to set up *your own* harness system. Each member (M-A..M-E) copies the pattern and modifies for their lane. Personal work logs are gitignored so you never conflict on `main`.

---

## 1. What this repo expects from any agent/member

You are one of **5 category members**. Work only in your `Owner:` files (see `docs/notion/00-core.md`).

| Member | Lane | Owner dirs |
|--------|------|------------|
| M-A | Agents | `backend/agents/` |
| M-B | Data | `backend/ingest/`, `backend/db/`, `scripts/`, `data/` |
| M-C | Backend API | `backend/routers/`, `backend/main.py`, `infra/` |
| M-D | Map | `frontend/map/`, `frontend/app/map/`, `frontend/app/api/pfz/` |
| M-E | Chat & Shell | `frontend/chat/`, `frontend/app/page.tsx` |

All 5 lanes are independent (no overlapping files). See `CONTRIBUTING.md` for branch/PR flow: `feat/m-a-` .. `feat/m-e-` → PR to `parth5012:main`.

---

## 2. Set up your personal harness (3 minutes, once)

Your harness is **local-only** — it never hits git (see `.gitignore` § Harness). Do this on clone:

```bash
# pick your lane, e.g. M-A
cp LOG.md LOG_M-A.md 2>/dev/null || echo "# LOG — M-A" > LOG_M-A.md
cp BLOCKED.md BLOCKED_M-A.md 2>/dev/null || echo "# BLOCKED — M-A" > BLOCKED_M-A.md
touch LEARNINGS.md TECH_DEBT.md   # optional, also gitignored
```

From now on, **log in your `LOG_M-X.md`, not in `AGENTS.md` and not in docs**. One line per task:

```
2026-09-03 | orchestrator gather | done | artifacts: backend/agents/orchestrator.py | next: combiner weights
```

If you're blocked, add one line to `BLOCKED_M-X.md`:

```
2026-09-03 | ingest SEC005 | JSESSIONID expired | tried: re-fetch TextDataHome 1× | need: retry backoff
```

These files are gitignored (`LOG.md`, `LOG_*.md`, `BLOCKED.md`, `BLOCKED_*.md`, `LEARNINGS.md`, `TECH_DEBT.md`) precisely so 5 members never merge-conflict on progress logs.

---

## 3. Harness construction — principles (from `agent-harness-construction` skill)

Use these **4 lenses** to design *your* tools. Keep them as references, not rules.

### 3.1 Action space — stable, narrow, typed
- Name tools explicitly (`find_nearest_pfz` not `search`). Keep inputs schema-first.
- Prefer **micro-tools** for risky ops (deploy, migration, PostGIS `ST_DWithin`), **medium** for common read/edit/search loops, **macro** only when round-trip cost dominates.
- Avoid overlapping semantics (don't have `search_pfz`, `find_pfz`, `lookup_pfz`).

> ORCA example (adapt for your lane): M-A could expose `find_nearest_pfz{lat,lon,radius_m}` → `Feature[]`; M-B `ingest_pfz{sectors}` → `count`; M-C `serve_pfz{sector?}` → `FeatureCollection`. Your lane may need different params — keep shape deterministic.

### 3.2 Observation — always `status + summary + next_actions + artifacts`
Every tool/script you write should return:

```json
{"status": "success|warning|error", "summary": "one line", "next_actions": ["retry with 120km", "call combiner"], "artifacts": ["data/pfz-today.geojson"]}
```

This is what lets the next agent/human decide without re-reading code.

### 3.3 Recovery — root cause → retry → stop
For each failure mode in *your* lane, define:

- **hint** (why): `JSESSIONID expired` / `psycopg refused` / `Bhashini 429`
- **retry** (safe, bounded): `re-fetch TextDataHome → backoff 1s/2s/4s, max 3×`
- **stop** (degrade gracefully): `serve yesterday's data/pfz-today.geojson + warn "up to 24h old"` / `mark zone unknown, confidence 0.87→0.62`

Don't crash the pipeline because one agent timed out (>10s) — return partial with `warning`.

### 3.4 Context budget — keep prompts small
- System prompt = minimal + invariant (who you are: M-A/B/...).
- Load large guidance **on demand** (reference `backend/db/schema.sql` path, don't inline 400 lines).
- Compact at **phase boundaries** (W1 done / W2 done), not arbitrary token counts.

---

## 4. Architecture pattern — pick for your task

- **ReAct**: exploratory, uncertain path (good for debugging INCOIS scraping)
- **Function-calling**: structured, deterministic (good for `POST /api/chat` → orchestrator → 4 agents)
- **Hybrid (recommended for ORCA)**: ReAct planning (decide *which* tools) + typed execution (call them)

---

## 5. Benchmark yourself (Fri 16:00 before Global Test)

Add to your `LOG_M-X.md` / PR description:

- **completion rate** — % of your tools that return `success`
- **retries per task** — avg retries for your riskiest tool (target ≤1)
- **pass@1 / pass@3** — same query 3× → same result?
- **cost per success** — e.g. Bhashini calls + PostGIS queries per chat

---

## 6. Anti-patterns (avoid)

- Many tools with overlapping meaning
- Tool output with no `next_actions` (opaque error only)
- Inlining huge docs/GeoJSON in prompt — reference the file instead
- Editing `main` directly — every change via branch + PR

---

## 7. Where to look next

- **Your build steps**: `docs/notion/00-core.md` + your `docs/notion/0x-m*.md` (step-by-step, file list, local run cmds)
- **API shapes**: `docs/API.md`
- **Architecture**: `docs/ORCA_GeoJSON_Architecture.md`
- **Branch/PR rules**: `CONTRIBUTING.md`

> This `AGENTS.md` is general — **modify your personal `LOG_M-X.md` / `BLOCKED_M-X.md` workflow as your lane needs**. If you improve a pattern (e.g., better retry for Bhashini), share the learning in your PR description so others can adopt it.
