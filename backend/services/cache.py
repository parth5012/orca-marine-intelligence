"""
Enterprise Redis Cache Manager & Invalidation Engine
Owner: M-B / M-C
Module: backend/services/cache.py

Provides robust async caching with:
1. Automatic type-safe JSON serialization for Pydantic models, datetimes, dates, UUIDs, and geometries.
2. Structured namespace key generation (e.g. orca:ports:1, orca:pfz:list:<hash>).
3. Targeted cache eviction and pattern-based invalidation for consistency.
4. Transparent in-memory fallback with TTL if Redis is unavailable.
5. Fail-safe error handling to guarantee database operations never break due to cache issues.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
import fnmatch
import hashlib
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Set, Type, TypeVar
from urllib.parse import parse_qsl, urlencode, urlparse
from uuid import UUID

from pydantic import BaseModel

logger = logging.getLogger("orca.cache")

T = TypeVar("T")


class EnhancedJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder handling datetime, date, UUID, Decimal, and Pydantic models."""

    def default(self, o: Any) -> Any:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, BaseModel):
            return o.model_dump(mode="json")
        if hasattr(o, "__dict__"):
            return {k: v for k, v in o.__dict__.items() if not k.startswith("_")}
        return super().default(o)


def _redact_redis_url(url: str) -> str:
    """Safely redact credentials and password query parameters from Redis URL for logging."""
    try:
        parsed = urlparse(url)
        has_netloc_password = bool(parsed.password)

        has_query_password = False
        new_query = ""
        if parsed.query:
            q_pairs = parse_qsl(parsed.query, keep_blank_values=True)
            redacted_pairs = []
            for k, v in q_pairs:
                if k.lower() == "password":
                    has_query_password = True
                    redacted_pairs.append((k, "***"))
                else:
                    redacted_pairs.append((k, v))
            if has_query_password:
                new_query = urlencode(redacted_pairs, safe="*")
            else:
                new_query = parsed.query

        if not has_netloc_password and not has_query_password:
            return url

        netloc = parsed.netloc
        if has_netloc_password:
            auth, _, host_port = parsed.netloc.rpartition("@")
            user, _, _ = auth.partition(":")
            netloc = f"{user}:***@{host_port}"

        delimiter = "://" if "://" in url else ":"
        res = f"{parsed.scheme}{delimiter}{netloc}{parsed.path}"
        if parsed.params:
            res = f"{res};{parsed.params}"
        if new_query:
            res = f"{res}?{new_query}"
        if parsed.fragment:
            res = f"{res}#{parsed.fragment}"
        return res
    except Exception:
        return "[redacted-endpoint]"


class CacheManager:
    """
    Async Cache Manager supporting Redis with automatic in-memory fallback.
    Maintains cache consistency with PostgreSQL.
    """

    def __init__(self, prefix: str = "orca", redis_url: Optional[str] = None):
        self.prefix = prefix
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = None
        self._memory_store: Dict[str, Any] = {}
        self._memory_expiry: Dict[str, float] = {}
        self._connected: bool = False
        self._initialized: bool = False
        self._lock = asyncio.Lock()

    async def get_client(self):
        """Get or initialize the underlying Redis client."""
        if self._initialized:
            return self._redis

        async with self._lock:
            if self._initialized:
                return self._redis
            self._initialized = True
            try:
                import redis.asyncio as aioredis

                client = aioredis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=0.5,
                    socket_timeout=0.5,
                )
                # Test connection
                await client.ping()
                self._redis = client
                self._connected = True
                logger.info("CacheManager: Successfully connected to Redis at %s", _redact_redis_url(self.redis_url))
                return self._redis
            except Exception as exc:
                logger.warning("CacheManager: Redis unavailable (%s); using in-memory cache fallback", exc)
                self._redis = None
                self._connected = False
                return None

    def build_key(self, namespace: str, *parts: Any) -> str:
        """Construct a standardized namespaced cache key: {prefix}:{namespace}:{part1}:{part2}..."""
        str_parts = [str(p) for p in parts if p is not None]
        if str_parts:
            return f"{self.prefix}:{namespace}:{':'.join(str_parts)}"
        return f"{self.prefix}:{namespace}"

    def build_query_key(self, namespace: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Generate a deterministic hash key for filtered queries/collections."""
        if not params:
            return f"{self.prefix}:{namespace}:list:all"
        # Sort keys for deterministic hash
        serialized_params = json.dumps(params, sort_keys=True, cls=EnhancedJSONEncoder)
        query_hash = hashlib.md5(serialized_params.encode("utf-8")).hexdigest()[:12]
        return f"{self.prefix}:{namespace}:list:{query_hash}"

    def _clean_memory_key_if_expired(self, key: str) -> bool:
        """Check and clean expired keys in memory store."""
        expiry = self._memory_expiry.get(key)
        if expiry is not None and time.time() > expiry:
            self._memory_store.pop(key, None)
            self._memory_expiry.pop(key, None)
            return True
        return False

    async def get(self, key: str) -> Any | None:
        """Retrieve and deserialize a value from cache. Returns None on cache miss."""
        client = await self.get_client()

        if client is not None:
            try:
                raw = await asyncio.wait_for(client.get(key), timeout=1.0)
                if raw is None:
                    return None
                if isinstance(raw, (str, bytes)):
                    return json.loads(raw)
                return raw
            except Exception as exc:
                logger.warning("Cache get error for key '%s': %s (fallback to memory)", key, exc)

        # In-memory fallback
        if self._clean_memory_key_if_expired(key):
            return None
        val = self._memory_store.get(key)
        if val is None:
            return None
        # Return deep copy to prevent mutation
        try:
            return json.loads(json.dumps(val, cls=EnhancedJSONEncoder))
        except Exception:
            return val

    async def get_typed(self, key: str, schema: Type[T]) -> Optional[T]:
        """Retrieve and parse into a Pydantic model."""
        data = await self.get(key)
        if data is None:
            return None
        try:
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                return schema.model_validate(data)
            return data
        except Exception as exc:
            logger.warning("Failed to parse cached data into schema %s: %s", schema, exc)
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        """Store a value in cache with TTL. Handles serialization automatically."""
        try:
            serialized = json.dumps(value, cls=EnhancedJSONEncoder)
        except Exception as exc:
            logger.error("Failed to serialize cache value for key '%s': %s", key, exc)
            return False

        client = await self.get_client()
        if client is not None:
            try:
                await asyncio.wait_for(client.set(key, serialized, ex=ttl_seconds), timeout=1.0)
                return True
            except Exception as exc:
                logger.warning("Cache set error for key '%s': %s (storing in memory)", key, exc)

        # In-memory fallback
        try:
            self._memory_store[key] = json.loads(serialized)
            self._memory_expiry[key] = time.time() + ttl_seconds
            return True
        except Exception as exc:
            logger.error("Failed to set in-memory cache for key '%s': %s", key, exc)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a single key from cache."""
        deleted = False
        client = await self.get_client()

        if client is not None:
            try:
                res = await asyncio.wait_for(client.delete(key), timeout=1.0)
                deleted = bool(res)
            except Exception as exc:
                logger.warning("Cache delete error for key '%s': %s", key, exc)

        # Also purge from memory fallback
        if key in self._memory_store:
            self._memory_store.pop(key, None)
            self._memory_expiry.pop(key, None)
            deleted = True

        return deleted

    async def delete_many(self, *keys: str) -> int:
        """Delete multiple keys from cache."""
        if not keys:
            return 0

        count = 0
        client = await self.get_client()

        if client is not None:
            try:
                res = await asyncio.wait_for(client.delete(*keys), timeout=1.0)
                count = int(res)
            except Exception as exc:
                logger.warning("Cache delete_many error for keys %s: %s", keys, exc)

        # Also purge memory
        for k in keys:
            if k in self._memory_store:
                self._memory_store.pop(k, None)
                self._memory_expiry.pop(k, None)
                count += 1

        return count

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern (e.g. 'orca:ports:list:*').
        Uses non-blocking SCAN in Redis.
        """
        deleted_count = 0
        client = await self.get_client()

        if client is not None:
            try:
                cursor = 0
                keys_to_delete: List[str] = []
                while True:
                    cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
                    if keys:
                        keys_to_delete.extend(keys)
                    if cursor == 0:
                        break

                if keys_to_delete:
                    # Delete in batches of 200
                    for i in range(0, len(keys_to_delete), 200):
                        batch = keys_to_delete[i : i + 200]
                        res = await asyncio.wait_for(client.delete(*batch), timeout=1.5)
                        deleted_count += int(res)
            except Exception as exc:
                logger.warning("Cache delete_pattern error for pattern '%s': %s", pattern, exc)

        # Memory store pattern deletion
        matched_mem_keys = [k for k in list(self._memory_store.keys()) if fnmatch.fnmatch(k, pattern)]
        for k in matched_mem_keys:
            self._memory_store.pop(k, None)
            self._memory_expiry.pop(k, None)
            deleted_count += 1

        return deleted_count

    # High-level Cache Consistency & Invalidation Helpers
    async def invalidate_entity(self, namespace: str, entity_id: Any) -> None:
        """
        Invalidate cache for a specific entity and all related collection/list/search/by_* queries.
        Ensures consistency when an entity is updated or deleted.
        """
        entity_key = self.build_key(namespace, entity_id)
        patterns = [
            f"{self.prefix}:{namespace}:list:*",
            f"{self.prefix}:{namespace}:search:*",
            f"{self.prefix}:{namespace}:by_*",
            f"{self.prefix}:{namespace}:sector:*",
        ]

        await self.delete(entity_key)
        for pat in patterns:
            await self.delete_pattern(pat)
        logger.debug("Invalidated entity cache for %s:%s and patterns %s", namespace, entity_id, patterns)

    async def invalidate_collections(self, namespace: str) -> None:
        """Invalidate all collection/list/search caches for a namespace (e.g. after entity creation)."""
        patterns = [
            f"{self.prefix}:{namespace}:list:*",
            f"{self.prefix}:{namespace}:search:*",
            f"{self.prefix}:{namespace}:by_*",
            f"{self.prefix}:{namespace}:sector:*",
        ]
        for pat in patterns:
            await self.delete_pattern(pat)
        logger.debug("Invalidated collection caches for namespace %s (patterns %s)", namespace, patterns)

    async def invalidate_namespace(self, namespace: str) -> None:
        """Completely purge all cache keys under a namespace."""
        pattern = f"{self.prefix}:{namespace}:*"
        await self.delete_pattern(pattern)
        logger.debug("Purged entire namespace %s (pattern %s)", namespace, pattern)

    async def clear_all(self) -> None:
        """Clear all cache keys matching this prefix."""
        pattern = f"{self.prefix}:*"
        await self.delete_pattern(pattern)
        self._memory_store.clear()
        self._memory_expiry.clear()

    async def close(self) -> None:
        """Close connection cleanly."""
        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None
            self._connected = False


# Default Singleton Instance
cache_manager = CacheManager()
