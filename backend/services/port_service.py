"""
Coastal Port Domain Service
Owner: M-B / M-C
Module: backend/services/port_service.py

High-level business operations for Coastal Ports & Landing Centers with Redis Caching.
"""

from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from backend.crud.ports import CRUDCoastalPort, port_crud
from backend.db.models import CoastalPort
from backend.schemas.ports import (
    CoastalPortCreate,
    CoastalPortRead,
    CoastalPortUpdate,
)
from backend.services.base import BaseService
from backend.services.cache import CacheManager, cache_manager


class CoastalPortService(
    BaseService[CoastalPort, CoastalPortCreate, CoastalPortUpdate, CoastalPortRead]
):
    """Business service for coastal ports and landing centers."""

    def __init__(
        self,
        crud: CRUDCoastalPort = port_crud,
        cache: CacheManager = cache_manager,
    ):
        super().__init__(
            crud=crud,
            read_schema=CoastalPortRead,
            namespace="ports",
            cache=cache,
            default_ttl=86400,  # 24h for stable port registry
            list_ttl=1800,      # 30m for port search lists
        )
        self.port_crud = crud

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str,
        use_cache: bool = True,
    ) -> Optional[CoastalPortRead]:
        """Fetch port by name with caching."""
        cache_key = self.cache.build_key(self.namespace, "by_name", name.strip().lower())

        if use_cache:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                return self.read_schema.model_validate(cached)

        port = await self.port_crud.get_by_name(db, name=name)
        if port is None:
            return None

        read_obj = self.read_schema.model_validate(port)
        if use_cache:
            await self.cache.set(cache_key, read_obj, ttl_seconds=self.default_ttl)

        return read_obj

    async def search_ports(
        self,
        db: AsyncSession,
        query: str,
        skip: int = 0,
        limit: int = 50,
        use_cache: bool = True,
    ) -> List[CoastalPortRead]:
        """Search ports by name, state, or alias with query caching."""
        cache_key = self.cache.build_query_key(
            f"{self.namespace}:search",
            {"q": query.strip().lower(), "skip": skip, "limit": limit}
        )

        if use_cache:
            cached = await self.cache.get(cache_key)
            if cached is not None and isinstance(cached, list):
                return [self.read_schema.model_validate(i) for i in cached]

        ports = await self.port_crud.search_ports(db, query=query, skip=skip, limit=limit)
        read_ports = [self.read_schema.model_validate(p) for p in ports]

        if use_cache:
            await self.cache.set(
                cache_key,
                [p.model_dump(mode="json") for p in read_ports],
                ttl_seconds=self.list_ttl,
            )

        return read_ports


port_service = CoastalPortService()
