"""
Generic Service Layer with Redis Cache-Aside & Strong Consistency
Owner: M-C / M-B
Module: backend/services/base.py

Coordinates business logic between PostgreSQL (Single Source of Truth) and Redis (Caching Layer).
Enforces:
- Cache-Aside on Reads
- Immediate Cache-Eviction / Invalidation on Writes (Create, Update, Delete)
- Clean fallback if Redis is unavailable
"""

from typing import Any, Dict, Generic, List, Optional, Type, TypeVar
import logging
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.crud.base import CRUDBase
from backend.db.models import Base
from backend.schemas.base import PaginatedResponse
from backend.services.cache import CacheManager, cache_manager

logger = logging.getLogger("orca.service")

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)
ReadSchemaType = TypeVar("ReadSchemaType", bound=BaseModel)


class BaseService(Generic[ModelType, CreateSchemaType, UpdateSchemaType, ReadSchemaType]):
    """
    High-level service managing business logic, PostgreSQL transactions,
    and Redis cache synchronization.
    """

    def __init__(
        self,
        crud: CRUDBase[ModelType, CreateSchemaType, UpdateSchemaType],
        read_schema: Type[ReadSchemaType],
        namespace: str,
        cache: CacheManager = cache_manager,
        default_ttl: int = 3600,
        list_ttl: int = 300,
    ):
        self.crud = crud
        self.read_schema = read_schema
        self.namespace = namespace
        self.cache = cache
        self.default_ttl = default_ttl
        self.list_ttl = list_ttl

    def _get_entity_id(self, obj: Any) -> Any:
        """Extract primary key identifier from entity or schema."""
        if hasattr(obj, "id"):
            return getattr(obj, "id")
        if hasattr(obj, "session_id"):
            return getattr(obj, "session_id")
        if hasattr(obj, "zone_id"):
            return getattr(obj, "zone_id")
        return getattr(obj, "name", None)

    async def get_by_id(
        self,
        db: AsyncSession,
        id: Any,
        use_cache: bool = True,
    ) -> Optional[ReadSchemaType]:
        """
        Cache-Aside Read:
        1. Check Redis for cached entity.
        2. On cache hit: return deserialized entity immediately.
        3. On cache miss: query PostgreSQL (source of truth).
        4. Populate Redis with entity data and TTL.
        """
        cache_key = self.cache.build_key(self.namespace, id)

        # 1. Try Redis cache
        if use_cache:
            try:
                cached_data = await self.cache.get(cache_key)
                if cached_data is not None:
                    logger.debug("Cache HIT for %s", cache_key)
                    return self.read_schema.model_validate(cached_data)
            except Exception as exc:
                logger.warning("Cache read exception for %s: %s", cache_key, exc)

        logger.debug("Cache MISS for %s — querying PostgreSQL", cache_key)

        # 2. Query PostgreSQL
        db_obj = await self.crud.get(db, id)
        if db_obj is None:
            return None

        # 3. Serialize to Read schema
        read_obj = self.read_schema.model_validate(db_obj)

        # 4. Populate Redis cache
        if use_cache:
            try:
                await self.cache.set(cache_key, read_obj, ttl_seconds=self.default_ttl)
            except Exception as exc:
                logger.warning("Cache write exception for %s: %s", cache_key, exc)

        return read_obj

    async def get_multi(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 50,
        filters: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> PaginatedResponse[ReadSchemaType]:
        """
        Fetch paginated collection with query cache.
        On miss, executes count and select queries on PostgreSQL, then populates Redis.
        """
        clean_filters = {k: v for k, v in (filters or {}).items() if v is not None}
        cache_params = {"skip": skip, "limit": limit, **clean_filters}
        query_key = self.cache.build_query_key(self.namespace, cache_params)

        # 1. Try Query Cache
        if use_cache:
            try:
                cached_payload = await self.cache.get(query_key)
                if cached_payload is not None and isinstance(cached_payload, dict):
                    items = [self.read_schema.model_validate(i) for i in cached_payload.get("items", [])]
                    return PaginatedResponse[ReadSchemaType](
                        items=items,
                        total=cached_payload.get("total", len(items)),
                        skip=skip,
                        limit=limit,
                        cached=True,
                    )
            except Exception as exc:
                logger.warning("Query cache read error: %s", exc)

        # 2. Query PostgreSQL
        db_items = await self.crud.get_multi(db, skip=skip, limit=limit, filters=clean_filters)
        total = await self.crud.count(db, filters=clean_filters)

        items = [self.read_schema.model_validate(item) for item in db_items]
        response = PaginatedResponse[ReadSchemaType](
            items=items,
            total=total,
            skip=skip,
            limit=limit,
            cached=False,
        )

        # 3. Store in Redis Query Cache
        if use_cache:
            try:
                payload = {
                    "items": [item.model_dump(mode="json") for item in items],
                    "total": total,
                    "skip": skip,
                    "limit": limit,
                }
                await self.cache.set(query_key, payload, ttl_seconds=self.list_ttl)
            except Exception as exc:
                logger.warning("Query cache write error: %s", exc)

        return response

    async def create(
        self,
        db: AsyncSession,
        *,
        obj_in: CreateSchemaType,
    ) -> ReadSchemaType:
        """
        Write to PostgreSQL first (Source of Truth), then update cache:
        1. Persist to PostgreSQL and commit transaction.
        2. Prime entity cache in Redis.
        3. Invalidate collection/list caches to guarantee consistency.
        """
        # 1. PostgreSQL commit
        db_obj = await self.crud.create(db, obj_in=obj_in)
        read_obj = self.read_schema.model_validate(db_obj)
        entity_id = self._get_entity_id(db_obj)

        # 2. Redis Consistency: Prime entity cache & evict list caches
        try:
            if entity_id is not None:
                entity_key = self.cache.build_key(self.namespace, entity_id)
                await self.cache.set(entity_key, read_obj, ttl_seconds=self.default_ttl)
            await self.cache.invalidate_collections(self.namespace)
        except Exception as exc:
            logger.warning("Cache sync error after create: %s", exc)

        return read_obj

    async def update(
        self,
        db: AsyncSession,
        *,
        id: Any,
        obj_in: UpdateSchemaType,
    ) -> Optional[ReadSchemaType]:
        """
        Write to PostgreSQL first, then evict stale cache:
        1. Query and update PostgreSQL record.
        2. Evict/Update entity cache in Redis.
        3. Invalidate related collection caches.
        """
        db_obj = await self.crud.get(db, id)
        if db_obj is None:
            return None

        # 1. Commit update to PostgreSQL
        updated_db_obj = await self.crud.update(db, db_obj=db_obj, obj_in=obj_in)
        read_obj = self.read_schema.model_validate(updated_db_obj)

        # 2. Redis Consistency: Invalidate entity key and list caches
        try:
            await self.cache.invalidate_entity(self.namespace, id)
            # Re-prime cache with updated value
            entity_key = self.cache.build_key(self.namespace, id)
            await self.cache.set(entity_key, read_obj, ttl_seconds=self.default_ttl)
        except Exception as exc:
            logger.warning("Cache invalidation error after update for %s:%s: %s", self.namespace, id, exc)

        return read_obj

    async def delete(
        self,
        db: AsyncSession,
        *,
        id: Any,
    ) -> Optional[ReadSchemaType]:
        """
        Delete from PostgreSQL first, then evict from cache:
        1. Remove record from PostgreSQL.
        2. Evict entity cache and collection caches from Redis.
        """
        db_obj = await self.crud.get(db, id)
        if db_obj is None:
            return None

        read_obj = self.read_schema.model_validate(db_obj)

        # 1. Commit deletion to PostgreSQL
        await self.crud.delete(db, id=id)

        # 2. Redis Consistency: Invalidate entity and list caches
        try:
            await self.cache.invalidate_entity(self.namespace, id)
        except Exception as exc:
            logger.warning("Cache eviction error after delete for %s:%s: %s", self.namespace, id, exc)

        return read_obj

    async def invalidate_cache(self, id: Optional[Any] = None) -> None:
        """Manual cache invalidation hook."""
        if id is not None:
            await self.cache.invalidate_entity(self.namespace, id)
        else:
            await self.cache.invalidate_namespace(self.namespace)
