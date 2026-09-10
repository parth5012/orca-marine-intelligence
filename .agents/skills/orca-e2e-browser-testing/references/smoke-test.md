# ORCA E2E Browser Testing — Quick-Run Checklist

Use this checklist for a **fast smoke test** (15 minutes) when you don't need
the full 100+ test case sweep. Run the full suite for releases.

---

## Smoke Test Checklist (15 min)

### ✅ Services Up
- [ ] Backend: `curl http://localhost:8000/health` → `"status": "ok"`
- [ ] Frontend: `curl http://localhost:3000` → HTML response
- [ ] Redis: `docker exec orca-redis redis-cli ping` → PONG

### ✅ Home Page (`/`)
- [ ] Page loads with ORCA branding and dolphin emoji
- [ ] Chat panel visible on left (desktop) or via tab (mobile)
- [ ] Map panel visible on right (desktop) or via tab (mobile)
- [ ] GPS badge shows coordinates (locked or default)
- [ ] Safety badge shows GREEN/SAFE
- [ ] Language switcher dropdown works (EN → ML → EN)

### ✅ Chat Flow
- [ ] Type a message → send button enables
- [ ] Send "Where is fish near Kochi?" → SSE stream starts
- [ ] Response appears with reasoning accordion
- [ ] Zone cards render with "Show on Map" button
- [ ] Quick action chip click fills input

### ✅ Map Page (`/map`)
- [ ] Navigate via "Ocean Map" link
- [ ] Sector dropdown changes map center (try Kerala → Gujarat)
- [ ] Layer toggles flip (try EEZ off/on)
- [ ] Coordinate search: type "Veraval" → map flies there
- [ ] Invalid search: type "xyz" → error banner → dismiss ✕

### ✅ Navigation
- [ ] `/` → `/map` via header link
- [ ] `/map` → `/` via "Back to Chat" button
- [ ] `/map` → `/` via logo icon

### ✅ No Console Errors
- [ ] Open DevTools → Console → No red errors on any page

---

## Full Regression Checklist Reference

For the complete test matrix, refer to the main [SKILL.md](../SKILL.md) which
contains 14 test suites and 100+ individual test cases covering:

1. Navigation & Routing (8 tests)
2. Chat Advisory Panel (15 tests)
3. Voice Input (4 tests)
4. Language Switcher (9 tests)
5. Map Visualization (8 tests)
6. Map Layers & Controls (9 tests)
7. Sector Selection (7 tests)
8. Coordinate Search (10 tests)
9. Safety Badge & Telemetry (6 tests)
10. Responsive & Mobile Layout (8 tests)
11. API Integration (13 tests)
12. Error & Edge Cases (12 tests)
13. Accessibility (8 tests)
14. Performance Smoke (5 tests)

**Total: 122 test cases**

Plus the domain-specific [Edge Cases Catalog](./edge-cases.md) with 40+
maritime-specific scenarios across 10 categories.
