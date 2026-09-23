#!/usr/bin/env python3
"""
Seed PostGIS Database with Initial PFZ GeoJSON Features (CLI wrapper)

Usage:
    python scripts/seed_pfz.py [--force]
"""

import asyncio
from backend.db.seed_pfz import main

if __name__ == "__main__":
    asyncio.run(main())
