# Contributing to ORCA — Agentic Marine Intelligence

Thank you for contributing to ORCA! This guide covers branch naming, commit conventions, pull request workflow, and code review standards.

---

## Branch Naming

Use the format `feat/M{milestone}-{short-description}` for feature branches:

```
feat/M1-orchestrator
feat/M2-textdata-ingest
feat/M3-map-view
feat/M4-bhashini-integration
feat/M5-geofencing
feat/M6-fastapi-proxy
```

For bug fixes: `fix/M{milestone}-{short-description}`
For docs: `docs/{short-description}`

**Never commit directly to `main`.** The `main` branch is protected.

---

## Commit Messages

Follow this format with milestone prefix:

```
M{milestone}: {concise description of change}
```

Examples:

```
M2: Add INCOIS TextData HTML parser for PFZ extraction
M3: Implement MapView component with React Leaflet
M5: Add EEZ/MPA geofence check with PostGIS ST_Contains
M6: Configure CORS middleware with ALLOWED_ORIGINS
M1: Implement Smart Combiner ranking algorithm
```

**Rules:**
- Use imperative mood ("Add feature" not "Added feature")
- Keep subject line under 72 characters
- Reference issue number if applicable: `M2: Add parser (#12)`
- Separate subject from body with a blank line for complex changes

---

## Pull Request Workflow

1. **Create your branch** from `main`:
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feat/M1-orchestrator
   ```

2. **Make your changes** with clear, focused commits.

3. **Push your branch**:
   ```bash
   git push origin feat/M1-orchestrator
   ```

4. **Open a Pull Request** against `main` with:
   - Title matching your branch name or commit message
   - Description of what changed and why
   - Screenshots for UI changes
   - Testing steps

5. **Code Review**: PRs require **1 approval** before merge.

6. **Merge**: Use squash merge to keep `main` history clean.

---

## Code Standards

### Python (Backend)
- Follow PEP 8 with type hints on all public functions
- Use docstrings for all modules, classes, and public functions
- Keep functions focused — one responsibility per function
- Use `async/await` for all I/O operations (FastAPI is async)

### TypeScript (Frontend)
- Use TypeScript strict mode
- Define interfaces for all component props
- Use JSDoc for public functions
- Prefer functional components with hooks

### GeoJSON
- Use WGS84 coordinate reference system (EPSG:4326)
- Always include `properties` with `zone_id`, `source`, and `timestamp`
- Use `MultiPolygon` for zone boundaries, `Point` for PFZ locations

---

## Testing

- **Backend**: Run `pytest` before pushing
- **Frontend**: Run `npm run lint` and `npm run build`
- **Integration**: Test the full flow locally before PR:
  1. `docker compose up -d` (PostGIS + Redis)
  2. `uvicorn backend.main:app --reload` (backend)
  3. `cd frontend && npm run dev` (frontend)
  4. Verify chat → map → safety flow works

---

## Protected Branch Rules

- `main` requires 1 review approval
- All CI checks must pass (lint, typecheck, tests)
- No force pushes to `main`
- No direct commits to `main`

---

## Weekly Schedule

- **Daily standup**: 10:00 IST, 15 minutes
- **Global Test #1**: Friday 05 Sep 16:00 IST (all 6 members)
- **Global Test #2**: Friday 12 Sep 16:00 IST (SIH dress rehearsal)

---

## Questions?

Open a GitHub issue or ask in the team channel.
