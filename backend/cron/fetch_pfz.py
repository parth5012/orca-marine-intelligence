"""
ORCA PFZ Daily Cron Fetcher

Owner: M-C (Backend API & Platform) / M-B (Data)
Module: backend/cron/fetch_pfz.py

Daily cron entrypoint for refreshing PFZ data:
  python -m backend.cron.fetch_pfz [--sectors SEC005,SEC002] [--timeout 60]

What it does:
  1. Calls backend.ingest.incois_textdata.ingest_textdata()
     - live INCOIS scrape (all 14 sectors by default)
     - writes data/pfz-today.geojson when features non-empty
     - upserts PostGIS pfz_zones (skipped gracefully when offline)
     - caches Redis pfz:today with 6h TTL
  2. Prints AGENTS.md §3.2 observable envelope JSON to stdout:
     {"status","summary","next_actions","artifacts","count","source"}

Cron scheduling (INCOIS publishes ~11:30 IST daily):
  - OS cron / Render Cron Job (UTC): 30 6 * * *  (= 12:00 IST)
  - Vercel Cron: frontend/app/api/cron/pfz -> POST /api/pfz/refresh
  - See infra/cron/pfz-cron.example + infra/vercel.json

Exit codes: 0 success (even on fallback), 1 only on unexpected crash.
Never raises on INCOIS offline — fallback chain handles it.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orca.cron.pfz")


def _parse_sectors(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    sectors = [s.strip().upper() for s in raw.split(",") if s.strip()]
    return sectors or None


async def run_fetch(sectors: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run one PFZ refresh cycle. Returns observable envelope dict."""
    from backend.ingest.incois_textdata import ingest_textdata

    t0 = time.time()
    try:
        doc = await ingest_textdata()
        features = doc.get("features", [])
        # Optional sector narrowing for targeted re-fetch (filters in-memory, no re-scrape)
        if sectors:
            sec_set = {s.upper() for s in sectors}
            features = [
                f
                for f in features
                if f.get("properties", {}).get("sector", "").upper() in sec_set
                or f.get("properties", {}).get("sector_name", "").upper() in sec_set
            ]
            doc = {**doc, "features": features, "count": len(features)}

        count = len(features)
        source = doc.get("source", "incois_textdata")
        elapsed = round(time.time() - t0, 2)
        status = "success" if count > 0 else "warning"
        # sector_count must reflect the post-filter feature set, not the
        # unfiltered document (they diverge when --sectors narrows features).
        sector_count = len(
            {
                f.get("properties", {}).get("sector")
                for f in features
                if f.get("properties", {}).get("sector")
            }
        )

        # Distinguish live vs fallback for operators
        if source == "copernicus_fallback":
            summary = f"PFZ cron fallback: {count} features via Copernicus (INCOIS offline) in {elapsed}s"
            next_actions = ["check INCOIS portal", "verify JSESSIONID", "serve cached GeoJSON"]
        elif count == 0:
            summary = f"PFZ cron warning: 0 features in {elapsed}s; yesterday file retained"
            next_actions = ["check INCOIS portal", "inspect data/pfz-today.geojson", "retry in 30m"]
        else:
            summary = f"PFZ cron success: {count} features via {source} in {elapsed}s"
            next_actions = ["serve /api/pfz/today", "verify map renders"]

        return {
            "status": status,
            "summary": summary,
            "next_actions": next_actions,
            # Only sinks ingest_textdata actually persisted (file/PostGIS/Redis).
            "artifacts": doc.get("artifacts", []),
            "count": count,
            "source": source,
            "sector_count": sector_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": elapsed,
        }
    except Exception as exc:  # last-resort guard: cron must never crash silently
        logger.exception("PFZ cron crashed: %s", exc)
        return {
            "status": "error",
            "summary": f"PFZ cron error: {exc}",
            "next_actions": ["check logs", "verify DATABASE_URL/REDIS_URL", "retry manually"],
            "artifacts": [],
            "count": 0,
            "source": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": round(time.time() - t0, 2),
        }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ORCA PFZ daily cron fetcher")
    parser.add_argument(
        "--sectors",
        default=None,
        help="Optional comma-separated sector filter e.g. SEC005,SEC002 (default: all 14)",
    )
    parser.add_argument("--timeout", type=int, default=120, help="Hard timeout seconds (default 120)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    sectors = _parse_sectors(args.sectors)

    async def _bounded() -> Dict[str, Any]:
        return await asyncio.wait_for(run_fetch(sectors=sectors), timeout=args.timeout)

    try:
        result = asyncio.run(_bounded())
    except asyncio.TimeoutError:
        result = {
            "status": "error",
            "summary": f"PFZ cron timed out after {args.timeout}s",
            "next_actions": ["retry with --timeout 180", "check INCOIS latency"],
            "artifacts": [],
            "count": 0,
            "source": "timeout",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    print(json.dumps(result, indent=2))
    # Exit 0 on success/warning (fallback served), 1 only on hard error/timeout
    return 0 if result.get("status") in ("success", "warning") else 1


if __name__ == "__main__":
    sys.exit(main())
