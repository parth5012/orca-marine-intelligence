"""
PROTOTYPE demo - awaiting human approval (wayfinder #25, map #22). ROUGH DRAFT.

Interactive demo of the dynamic planner: builds a sample PlannerOutput,
prints the tool-call plan + reasoning trace, runs mock-only tool stubs.

Usage:
    python scripts/demo_dynamic_planner.py [--query "..."] [--scenario normal]
    python scripts/demo_dynamic_planner.py --low-confidence   # show GPS clarification path

No external API calls. Offline-safe (mock_fetchers or hardcoded fallback).
Do NOT wire into graph.py / combiner until human approves direction.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python scripts/demo_...` from repo root without install.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.planner_schema import (  # noqa: E402
    CLARIFICATION_THRESHOLD,
    COASTAL_PORTS_REGISTRY,
    PLANNER_MODEL,
    PLANNER_TIMEOUT_MS,
    PlannerOutput,
    TargetLocation,
    check_geofence,
    check_ocean_state,
    check_weather,
    find_fishing_zones,
)


def build_sample_plan(query: str, low_confidence: bool = False) -> PlannerOutput:
    """Hardcoded sample PlannerOutput (what Gemini 2.5 Flash would return)."""
    q = (query or "").lower()
    # Naive port match for demo only (real planner = LLM + registry).
    port_hit: str | None = None
    for port in COASTAL_PORTS_REGISTRY:
        if port.lower() in q:
            port_hit = port
            break
    if port_hit is None:
        port_hit = "Munambam"  # demo default
    lat, lon = COASTAL_PORTS_REGISTRY[port_hit]

    if low_confidence:
        return PlannerOutput(
            detected_language="ml",
            target_location=TargetLocation(lat=None, lon=None, port_name=None, confidence=0.32),
            intents=["clarify_location"],
            confidence=0.32,
            reasoning_trace=[
                "SKIP find_fishing_zones: no GPS and port confidence 0.32 < 0.6 - must ask location first.",
                "SKIP check_ocean_state: no zones to check yet.",
                "SKIP check_weather: no zones to check yet.",
                "SKIP check_geofence: nothing to veto yet.",
            ],
            selected_tools=[],
        )

    wants_safety = any(k in q for k in ("safe", "sea", "weather", "wind", "wave", "sail", "cyclone"))
    if "safe" in q or "weather" in q or wants_safety:
        intents = ["find_fish", "check_safety"]
        tools = ["find_fishing_zones", "check_ocean_state", "check_weather", "check_geofence"]
        trace = [
            f"SELECT find_fishing_zones: fish intent + port '{port_hit}' ({lat},{lon}) conf 0.82 - need candidates.",
            "SELECT check_ocean_state: safety intent - waves/currents gate the badge.",
            "SELECT check_weather: safety intent - wind/cyclone 500km gates the badge.",
            "SELECT check_geofence: must recommend a sail-legal zone - Combiner hard-vetoes banned.",
        ]
        conf = 0.82
    else:
        intents = ["find_fish"]
        tools = ["find_fishing_zones", "check_geofence"]
        trace = [
            f"SELECT find_fishing_zones: fish-only query near '{port_hit}' ({lat},{lon}).",
            "SKIP check_ocean_state: no safety keywords - save latency (selective dispatch).",
            "SKIP check_weather: no safety keywords - save latency.",
            "SELECT check_geofence: still veto banned zones before showing map.",
        ]
        conf = 0.78

    return PlannerOutput(
        detected_language="ml" if any(c > "\u0900" for c in query) else "en",
        target_location=TargetLocation(lat=lat, lon=lon, port_name=port_hit, confidence=conf),
        intents=intents,
        confidence=conf,
        reasoning_trace=trace,
        selected_tools=tools,
    )


def run_plan(plan: PlannerOutput, scenario: str = "normal") -> dict:
    """Execute selected tools (mock-only) in planner order. Returns summary dict."""
    results: dict = {"dispatched": list(plan.selected_tools), "tool_results": {}}
    zones: list[dict] = []
    if "find_fishing_zones" in plan.selected_tools and plan.target_location.lat is not None:
        pfz = find_fishing_zones(
            lat=plan.target_location.lat, lon=plan.target_location.lon or 0.0, radius_km=80.0
        )
        zones = pfz.get("features", [])
        results["tool_results"]["find_fishing_zones"] = {
            "count": len(zones),
            "summary": pfz.get("summary", ""),
        }
    for tool in plan.selected_tools:
        if tool == "check_ocean_state":
            r = check_ocean_state(zones, scenario=scenario)
            results["tool_results"][tool] = {"count": len(r.get("results", [])), "summary": r.get("summary", "")}
        elif tool == "check_weather":
            r = check_weather(zones, scenario=scenario)
            results["tool_results"][tool] = {"count": len(r.get("results", [])), "summary": r.get("summary", "")}
        elif tool == "check_geofence":
            r = check_geofence(zones, scenario=scenario)
            results["tool_results"][tool] = {
                "count": len(r.get("results", [])),
                "restricted": r.get("restricted_count"),
                "summary": r.get("summary", ""),
            }
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="PROTOTYPE dynamic planner demo (mock-only).")
    ap.add_argument("--query", default="", help="Sample fisher query (default: interactive prompt)")
    ap.add_argument("--scenario", default="normal", help="mock scenario: normal|rough_seas|cyclone_warning|border_violation")
    ap.add_argument("--low-confidence", action="store_true", help="demo the <0.6 GPS clarification path")
    args = ap.parse_args()

    query = args.query.strip()
    if not query and not args.low_confidence:
        try:
            query = input("Fisher query [default: 'Where is fish near Munambam, is sea safe?']: ").strip()
        except EOFError:
            query = ""
    if not query:
        query = "Where is fish near Munambam, is sea safe?" if not args.low_confidence else "evide meen?"

    print("=" * 68)
    print(f"PROTOTYPE dynamic planner demo  |  model={PLANNER_MODEL} budget<{PLANNER_TIMEOUT_MS}ms")
    print(f"query: {query!r}   scenario: {args.scenario}")
    print("=" * 68)

    plan = build_sample_plan(query, low_confidence=args.low_confidence)
    print("\n--- PlannerOutput (JSON) ---")
    print(json.dumps(plan.model_dump(), indent=2, ensure_ascii=False))

    print("\n--- Tool-call plan ---")
    if not plan.selected_tools:
        print("(no tools selected)")
    for i, step in enumerate(plan.to_tool_plan(), 1):
        print(f"  {i}. {step['tool']}\n     why: {step['why']}")

    print("\n--- Reasoning trace ---")
    for line in plan.reasoning_trace:
        print(f"  - {line}")

    if plan.needs_clarification(CLARIFICATION_THRESHOLD):
        print(f"\n>>> confidence {plan.confidence:.2f} < {CLARIFICATION_THRESHOLD} "
              "-> CLARIFY: 'Please share your GPS location or nearest port.' (no tools run)")
        print("SSE would emit: status -> tokens(clarification) -> done  [map/safety skipped]")
        return 0

    print("\n--- Running mock tools (offline, no external calls) ---")
    out = run_plan(plan, scenario=args.scenario)
    for tool, res in out["tool_results"].items():
        print(f"  {tool}: {json.dumps(res, ensure_ascii=False)}")

    print("\nNext (post-approval, NOT in prototype): Combiner hard-veto + "
          "SSE status->map->safety->tokens->evidence->done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
