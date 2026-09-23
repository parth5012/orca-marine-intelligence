"""
Seed PostGIS Database with Initial PFZ GeoJSON Features

Usage:
    python -m backend.db.seed_pfz [--force]

This script:
1. Connects to PostGIS database via DATABASE_URL.
2. Initializes schema (enables PostGIS extension, creates tables if needed).
3. Reads data/pfz-today.geojson and upserts all features into pfz_zones table.
4. Reports total rows in pfz_zones table.
"""

import asyncio
import logging
import sys
from datetime import date

from backend.db.session import init_db, seed_initial_pfz_if_empty, AsyncSessionLocal
from backend.db.models import PFZZone
from sqlalchemy import func, select

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_pfz")


async def main() -> None:
    force = "--force" in sys.argv
    logger.info("Initializing PostGIS schema...")
    await init_db()
    logger.info("Seeding PFZ features (force=%s)...", force)
    upserted = await seed_initial_pfz_if_empty(force=force)

    async with AsyncSessionLocal() as session:
        today = date.today()
        count_today_q = select(func.count(PFZZone.id)).where(PFZZone.valid_date == today)
        res_today = await session.execute(count_today_q)
        today_count = res_today.scalar() or 0

        count_total_q = select(func.count(PFZZone.id))
        res_total = await session.execute(count_total_q)
        total_count = res_total.scalar() or 0

    logger.info(
        "PostGIS PFZ status: seeded_now=%d, today_count=%d (valid_date=%s), total_count=%d",
        upserted,
        today_count,
        today,
        total_count,
    )
    if today_count == 0 and total_count == 0:
        logger.error("Failed to seed any PFZ features into PostGIS. Check data/pfz-today.geojson.")
        sys.exit(1)
    logger.info("PostGIS database is ready for PFZ queries.")


if __name__ == "__main__":
    asyncio.run(main())
