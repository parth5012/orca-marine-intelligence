"""PROTOTYPE test client for wayfinder #27 (map #22) — ROUGH DRAFT, not final.

Runs ``orchestrate_stream_via_graph`` with a Kochi query fully mock-backed
(offline, no API keys), collects SSE event types, and asserts the strict
docs/API.md order::

    status* -> map -> safety -> token+ -> evidence -> done

Also prints elapsed ms at the ``map`` event vs ``done`` to demonstrate the
early-flyTo benefit (map must arrive before full completion).

A no-location smoke path is included (map center None, amber safety).

Usage (from repo root):
    D:\\Python\\python.exe scripts/test_sse_ordering.py

Exit 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Field-name contract per docs/API.md SSE Event Schema section.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "status": ["type", "agent", "state"],
    "token": ["type", "text"],
    "map": ["type", "center", "pfz_features", "route"],
    "safety": ["type", "waves_m", "wind_kts", "danger", "badge"],
    "evidence": ["type", "items"],
    "done": ["type", "language", "confidence", "session_id"],
    "error": ["type", "agent", "message", "fallback"],
}

# Node names must match docs/API.md SSE agent names (issue #27 follow-up).
OLD_NODE_NAMES = {"fish_discovery_agent", "ocean_analytics_agent", "weather_intel_agent", "geospatial_risk_agent"}
DOC_AGENTS = {"fish_finder", "sea_checker", "weather_agent", "danger_agent"}
ALLOWED_STATUS_AGENTS = DOC_AGENTS | {"planner", "parallel_analysis", "decision_agent"}

SHARED_FISH = [
    {
        "zone_id": "z1",
        "place": "Pallithottam",
        "lat": 10.0,
        "lon": 76.0,
        "distance_from_user_km": 5.0,
        "bearing": 90,
        "direction": "E",
        "depth_range": "20-30",
        "sector": "KERALA",
    }
]
SEA_OK = [
    {
        "zone_id": "z1", "place": "Pallithottam", "lat": 10.0, "lon": 76.0,
        "wave_height_m": 0.8, "current_kt": 1.0, "wave_status": "safe",
        "current_status": "safe", "status": "safe", "reason": "ok",
        "source": "mock_heuristic",
    }
]
WEATHER_OK = [
    {
        "zone_id": "z1", "place": "Pallithottam", "lat": 10.0, "lon": 76.0,
        "wind_kt": 10.0, "wind_speed_kt": 10.0, "wind_dir": "N",
        "wind_direction": "N", "wind_deg": 0, "wind_status": "safe",
        "cyclone_alert": False, "nearest_cyclone_km": None,
        "cyclone_name": None, "status": "safe", "reason": "ok",
        "source": "mock_heuristic",
    }
]
DANGER_OK = [
    {
        "zone_id": "z1", "place": "Pallithottam", "lat": 10.0, "lon": 76.0,
        "is_safe": True, "status": "safe", "warnings": [],
        "inside_eez": True, "inside_mpa": False, "mpa_name": None,
    }
]


def check_fields(events: list[dict]) -> list[str]:
    """Return list of field-contract violations (empty = ok)."""
    problems: list[str] = []
    for i, e in enumerate(events):
        t = e.get("type")
        if t not in REQUIRED_FIELDS:
            problems.append(f"event[{i}]: unknown type {t!r}")
            continue
        for f in REQUIRED_FIELDS[t]:
            if f not in e:
                problems.append(f"event[{i}] type={t!r}: missing field {f!r}")
    return problems


def check_strict_order(types: list[str]) -> list[str]:
    """Assert status* -> map -> safety -> token+ -> evidence -> done.

    ``error`` events are ignored for ordering (timeout/fallback channel per
    docs/API.md). Returns list of violations (empty = ok).
    """
    problems: list[str] = []
    main = [t for t in types if t != "error"]
    if not main:
        return ["no events collected"]
    # All statuses must precede map (strict reading used by this prototype).
    try:
        map_i = main.index("map")
    except ValueError:
        return ["missing map event"]
    try:
        safety_i = main.index("safety")
    except ValueError:
        return ["missing safety event"]
    try:
        ev_i = main.index("evidence")
    except ValueError:
        return ["missing evidence event"]
    try:
        done_i = main.index("done")
    except ValueError:
        return ["missing done event"]
    token_is = [i for i, t in enumerate(main) if t == "token"]
    if not token_is:
        problems.append("missing token events (expected token+)")
    # Order constraints
    if not all(t == "status" for t in main[:map_i]):
        problems.append(f"pre-map events must all be status, got {main[:map_i]}")
    if not (map_i < safety_i):
        problems.append("map must precede safety")
    if token_is and not (safety_i < token_is[0]):
        problems.append("safety must precede first token")
    if token_is and not (token_is[-1] < ev_i):
        problems.append("tokens must precede evidence")
    if not (ev_i < done_i):
        problems.append("evidence must precede done")
    if done_i != len(main) - 1:
        problems.append(f"done must be last, got trailing {main[done_i + 1:]}")
    if main.count("map") != 1:
        problems.append(f"expected exactly 1 map, got {main.count('map')}")
    if main.count("safety") != 1:
        problems.append(f"expected exactly 1 safety, got {main.count('safety')}")
    if main.count("evidence") != 1:
        problems.append(f"expected exactly 1 evidence, got {main.count('evidence')}")
    if main.count("done") != 1:
        problems.append(f"expected exactly 1 done, got {main.count('done')}")
    # No status after map under the strict reading.
    post_map_status = [i for i in range(map_i + 1, len(main)) if main[i] == "status"]
    if post_map_status:
        problems.append(f"status events after map at positions {post_map_status} (strict order violated)")
    return problems


async def collect(query: str, language: str, location: dict | None, session_id: str,
                  fish_delay: float = 0.05, sub_delay: float = 0.25):
    """Run the stream mock-backed and return (events, elapsed_ms_per_event)."""
    from backend.agents import graph as gmod

    async def mock_fish(lat, lon, radius_km=80.0, **kw):
        await asyncio.sleep(fish_delay)
        return list(SHARED_FISH)

    async def mock_sea(points):
        await asyncio.sleep(sub_delay)
        return [dict(r) for r in SEA_OK]

    async def mock_weather(points):
        await asyncio.sleep(sub_delay)
        return [dict(r) for r in WEATHER_OK]

    async def mock_danger(points, **kw):
        await asyncio.sleep(sub_delay)
        return [dict(r) for r in DANGER_OK]

    events: list[dict] = []
    stamps_ms: list[int] = []
    t0 = time.perf_counter()
    with patch("backend.agents.fish_finder.find_fishing_zones", side_effect=mock_fish), \
        patch("backend.agents.sea_checker.check_sea_conditions", side_effect=mock_sea), \
        patch("backend.agents.weather_agent.check_weather", side_effect=mock_weather), \
        patch("backend.agents.danger_agent.check_safety_batch", side_effect=mock_danger), \
        patch("backend.db.redis.get_session", new=AsyncMock(return_value=None)), \
        patch("backend.db.redis.save_session", new=AsyncMock(return_value=None)):
        async for evt in gmod.orchestrate_stream_via_graph(query, language, location, session_id):
            events.append(evt)
            stamps_ms.append(int((time.perf_counter() - t0) * 1000))
    return events, stamps_ms


async def main() -> int:
    failures: list[str] = []

    print("=== PROTOTYPE #27: Kochi ordering run (mock-backed, offline) ===")
    events, stamps = await collect("fish near Kochi", "en", None, "test-sse-kochi")
    types = [str(e.get("type")) for e in events]
    for e, ms in zip(events, stamps):
        t = e.get("type")
        extra = ""
        if t == "status":
            extra = f"agent={e.get('agent')} state={e.get('state')}"
        elif t in ("map", "safety", "done", "evidence", "error"):
            extra = str({k: v for k, v in e.items() if k != "type"})[:160]
        elif t == "token":
            extra = f"text={str(e.get('text'))[:40]!r}"
        print(f"  +{ms:5d}ms  {t:8s} {extra}")

    map_ms = next((ms for e, ms in zip(events, stamps) if e.get("type") == "map"), None)
    done_ms = next((ms for e, ms in zip(events, stamps) if e.get("type") == "done"), None)
    print(f"\nmap arrived at +{map_ms}ms; done at +{done_ms}ms; "
          f"early-flyTo delta = {(done_ms - map_ms) if map_ms is not None and done_ms is not None else 'n/a'}ms")

    for p in check_fields(events):
        failures.append(f"[fields] {p}")
    for p in check_strict_order(types):
        failures.append(f"[order] {p}")
    if map_ms is None or done_ms is None:
        failures.append("[timing] missing map or done timestamp")
    elif not (map_ms < done_ms):
        failures.append(f"[timing] map (+{map_ms}ms) must arrive before done (+{done_ms}ms)")

    # Spot-check payload sanity for the Kochi run.
    by_type = {}
    for e in events:
        by_type.setdefault(e.get("type"), []).append(e)
    safety = (by_type.get("safety") or [{}])[0]
    if safety.get("badge") != "green":
        failures.append(f"[safety] expected badge 'green' for calm mocks, got {safety.get('badge')!r}")
    sentev = (by_type.get("map") or [{}])[0]
    if not sentev.get("pfz_features"):
        failures.append("[map] expected non-empty pfz_features for Kochi query")
    # Issue #27 follow-ups: doc agent names + provisional early map/safety.
    status_agents = [str(e.get("agent")) for e in events if e.get("type") == "status"]
    for a in status_agents:
        if a in OLD_NODE_NAMES:
            failures.append(f"[nodes] stale node name {a!r} — expected docs/API.md names (fish_finder etc.)")
        elif a not in ALLOWED_STATUS_AGENTS:
            failures.append(f"[nodes] unexpected status agent {a!r}")
    if "fish_finder" not in status_agents:
        failures.append(f"[nodes] expected status from 'fish_finder', got {status_agents}")
    if sentev.get("provisional") is not True:
        failures.append(f"[provisional] early map must include provisional:true, got {sentev.get('provisional')!r}")
    if safety.get("provisional") is not True:
        failures.append(f"[provisional] early safety must include provisional:true, got {safety.get('provisional')!r}")

    print("\n=== PROTOTYPE #27: no-location smoke run ===")
    events2, _ = await collect("fish", "en", None, "test-sse-noloc",
                               fish_delay=0.0, sub_delay=0.0)
    # Force no-location by using a query with no port and no GPS: planner
    # cannot resolve "fish" alone... note _parse_intent defaults both true but
    # location resolve needs explicit/GPS/port — "fish" has none, and the
    # mocked empty redis session means user_location stays None.
    types2 = [str(e.get("type")) for e in events2]
    print(f"  types: {types2}")
    for p in check_strict_order(types2):
        failures.append(f"[noloc order] {p}")
    m2 = next((e for e in events2 if e.get("type") == "map"), {})
    s2 = next((e for e in events2 if e.get("type") == "safety"), {})
    d2 = next((e for e in events2 if e.get("type") == "done"), {})
    for e in events2:
        if e.get("type") == "status" and str(e.get("agent")) in OLD_NODE_NAMES:
            failures.append(f"[noloc nodes] stale node name {e.get('agent')!r}")
    if m2.get("center") is not None:
        failures.append(f"[noloc map] expected center None, got {m2.get('center')!r}")
    if s2.get("badge") != "amber":
        failures.append(f"[noloc safety] expected badge 'amber', got {s2.get('badge')!r}")
    if abs(float(d2.get("confidence", -1)) - 0.62) > 0.01:
        failures.append(f"[noloc done] expected confidence ~0.62, got {d2.get('confidence')!r}")

    print()
    if failures:
        print(f"FAIL ({len(failures)} problem(s)):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: status* -> map -> safety -> token+ -> evidence -> done; map arrived before done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
