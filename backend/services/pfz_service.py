"""
PFZ Domain Service
Owner: M-B / M-C
Module: backend/services/pfz_service.py

High-level business operations for Potential Fishing Zones with 6-Hour Redis Caching.
"""

from datetime import date
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from backend.crud.pfz import CRUDPFZ, pfz_crud
from backend.db.models import PFZZone
from backend.schemas.pfz import (
    PFZZoneCreate,
    PFZZoneRead,
    PFZZoneUpdate,
)
from backend.services.base import BaseService
from backend.services.cache import CacheManager, cache_manager


class PFZService(BaseService[PFZZone, PFZZoneCreate, PFZZoneUpdate, PFZZoneRead]):
    """Business service for Potential Fishing Zones."""

    def __init__(
        self,
        crud: CRUDPFZ = pfz_crud,
        cache: CacheManager = cache_manager,
    ):
        super().__init__(
            crud=crud,
            read_schema=PFZZoneRead,
            namespace="pfz",
            cache=cache,
            default_ttl=21600,  # 6h matching INCOIS bulletin cycle
            list_ttl=3600,      # 1h for sector listings
        )
        self.pfz_crud = crud

    async def get_by_zone_id(
        self,
        db: AsyncSession,
        zone_id: str,
        use_cache: bool = True,
    ) -> Optional[PFZZoneRead]:
        """Fetch PFZ zone by unique zone_id with caching."""
        cache_key = self.cache.build_key(self.namespace, "by_zone_id", zone_id)

        if use_cache:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                return self.read_schema.model_validate(cached)

        zone = await self.pfz_crud.get_by_zone_id(db, zone_id=zone_id)
        if zone is None:
            return None

        read_obj = self.read_schema.model_validate(zone)
        if use_cache:
            await self.cache.set(cache_key, read_obj, ttl_seconds=self.default_ttl)

        return read_obj

    async def get_by_sector(
        self,
        db: AsyncSession,
        sector: str,
        valid_date: Optional[date] = None,
        skip: int = 0,
        limit: int = 100,
        use_cache: bool = True,
    ) -> List[PFZZoneRead]:
        """Fetch PFZ zones in a specific sector with query caching."""
        date_str = valid_date.isoformat() if valid_date else "latest"
        cache_key = self.cache.build_query_key(
            f"{self.namespace}:sector",
            {"sector": sector.upper(), "date": date_str, "skip": skip, "limit": limit}
        )

        if use_cache:
            cached = await self.cache.get(cache_key)
            if cached is not None and isinstance(cached, list):
                return [self.read_schema.model_validate(i) for i in cached]

        zones = await self.pfz_crud.get_by_sector(
            db, sector=sector, valid_date=valid_date, skip=skip, limit=limit
        )
        read_zones = [self.read_schema.model_validate(z) for z in zones]

        if use_cache:
            await self.cache.set(
                cache_key,
                [z.model_dump(mode="json") for z in read_zones],
                ttl_seconds=self.list_ttl,
            )

        return read_zones


pfz_service = PFZService()
