"""
Redis Connection & Cache Utilities

Owner: M-B (Data Extractors & Storage) — Redis cache (6h + sessions)
Module: backend/db/redis.py

Provides Redis connection management and caching helpers for ORCA.
Used for PFZ data caching (6h TTL), tile caching (1h TTL),
and multi-turn conversation memory.

Cache keys:
    - pfz:today           — Today's PFZ GeoJSON (TTL: 6h)
    - pfz:history:{date}  — Historical PFZ data (TTL: 7d)
    - tile:{z}:{x}:{y}   — Vector tiles (TTL: 1h)
    - session:{id}        — Conversation memory (TTL: 24h)

Dependencies:
    - redis.asyncio for async Redis client
"""

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_redis_client = None
_redis_binary_client = None
_memory_store: dict[str, Any] = {}
_memory_expiry: dict[str, float] = {}


def _is_expired(key: str) -> bool:
    exp = _memory_expiry.get(key)
    if exp is None:
        return False
    if time.time() > exp:
        _memory_store.pop(key, None)
        _memory_expiry.pop(key, None)
        return True
    return False


async def init_redis(redis_url: str | None = None):
    """Initialize Redis connection."""
    global _redis_client, _redis_binary_client
    if _redis_client is not None:
        return _redis_client
    url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis.asyncio as aioredis  # type: ignore

        _redis_client = aioredis.from_url(url, decode_responses=True)
        _redis_binary_client = aioredis.from_url(url, decode_responses=False)
        # Quick ping with short timeout to verify connectivity
        try:
            import asyncio

            await asyncio.wait_for(_redis_client.ping(), timeout=1.0)
            logger.info("Redis connected at %s", url)
        except Exception as e:
            logger.warning("Redis ping failed, falling back to memory: %s", e)
            _redis_client = None
            _redis_binary_client = None
    except Exception as e:
        logger.warning("Redis not available, using in-memory fallback: %s", e)
        _redis_client = None
        _redis_binary_client = None
    return _redis_client


async def get_redis_client():
    """Return the global Redis client, or None if Redis is not configured or unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    return await init_redis()


async def get_json(key: str) -> dict | None:
    """Get a JSON value from Redis cache."""
    # Try real Redis first if connected
    if _redis_client is not None:
        try:
            import asyncio

            raw = await asyncio.wait_for(_redis_client.get(key), timeout=1.0)
            if raw is None:
                return None
            if isinstance(raw, (bytes, str)):
                return json.loads(raw)
            return raw
        except Exception as e:
            logger.warning("Redis get_json failed for %s: %s, falling back to memory", key, e)
    # In-memory fallback
    if _is_expired(key):
        return None
    val = _memory_store.get(key)
    if val is None:
        return None
    # Return deep copy to avoid mutation
    try:
        return json.loads(json.dumps(val))
    except Exception:
        return val


async def set_json(key: str, value: dict, ttl_seconds: int = 3600):
    """Set a JSON value in Redis with TTL."""
    if _redis_client is not None:
        try:
            import asyncio

            data = json.dumps(value, ensure_ascii=False)
            await asyncio.wait_for(_redis_client.set(key, data, ex=ttl_seconds), timeout=1.0)
            return
        except Exception as e:
            logger.warning("Redis set_json failed for %s: %s, falling back to memory", key, e)
    # In-memory fallback
    _memory_store[key] = json.loads(json.dumps(value, ensure_ascii=False))
    _memory_expiry[key] = time.time() + ttl_seconds


async def save_session(session_id: str, data: dict, ttl_seconds: int = 86400):
    """Persist user session data with 24-hour expiration (T10 #126).

    Key: session:{session_id}
    Stores last_lat, last_lon, last_zone_id, last_zone_name, detected_language,
    boat_type, risk_preference, turn_history, etc.
    """
    key = f"session:{session_id}"
    if isinstance(data, dict):
        if "lat" in data and "last_lat" not in data:
            data["last_lat"] = data["lat"]
        if "lon" in data and "last_lon" not in data:
            data["last_lon"] = data["lon"]
        if "place" in data and "last_zone_name" not in data:
            data["last_zone_name"] = data["place"]
        if "zone_id" in data and "last_zone_id" not in data:
            data["last_zone_id"] = data["zone_id"]
    # Ensure TTL is 24h per spec
    await set_json(key, data, ttl_seconds=ttl_seconds)


async def get_session(session_id: str) -> dict | None:
    """Retrieve cached session data for multi-turn continuation."""
    key = f"session:{session_id}"
    return await get_json(key)


async def append_message(session_id: str, role: str, content: str):
    """Append a message to conversation history."""
    try:
        sess = await get_session(session_id)
        if sess is None:
            sess = {}
        history = sess.get("turn_history") or sess.get("history") or []
        if not isinstance(history, list):
            history = []
        history.append({"role": role, "content": content, "ts": time.time()})
        # Keep last 20 turns
        history = history[-20:]
        sess["turn_history"] = history
        # Update timestamp
        import datetime

        sess["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        await save_session(session_id, sess)
    except Exception as e:
        logger.warning("append_message failed for %s: %s", session_id, e)
        raise


async def get_history(session_id: str, limit: int = 10) -> list:
    """Get recent conversation history for a session."""
    try:
        sess = await get_session(session_id)
        if not sess:
            return []
        history = sess.get("turn_history") or sess.get("history") or []
        if not isinstance(history, list):
            return []
        return history[-limit:]
    except Exception as e:
        logger.warning("get_history failed for %s: %s", session_id, e)
        return []


async def get_tile_cache(key: str) -> bytes | None:
    """Get binary tile bytes from Redis cache or in-memory fallback."""
    if _redis_binary_client is not None:
        try:
            import asyncio

            raw = await asyncio.wait_for(_redis_binary_client.get(key), timeout=1.0)
            if raw is not None:
                if isinstance(raw, bytes):
                    return raw
                if isinstance(raw, str):
                    return raw.encode("latin1")
                return bytes(raw)
        except Exception as e:
            logger.warning("Redis get_tile_cache failed for %s: %s, falling back to memory", key, e)
    elif _redis_client is not None:
        try:
            import asyncio

            raw = await asyncio.wait_for(_redis_client.get(key), timeout=1.0)
            if raw is not None:
                if isinstance(raw, bytes):
                    return raw
                if isinstance(raw, str):
                    return raw.encode("latin1")
        except Exception as e:
            logger.warning("Redis get_tile_cache failed for %s: %s, falling back to memory", key, e)

    # In-memory fallback
    if _is_expired(key):
        return None
    val = _memory_store.get(key)
    if val is None:
        return None
    if isinstance(val, bytes):
        return val
    if isinstance(val, str):
        return val.encode("latin1")
    if isinstance(val, (bytearray, memoryview)):
        return bytes(val)
    return None


async def set_tile_cache(key: str, value: bytes, ttl_seconds: int = 3600) -> None:
    """Set binary tile bytes in Redis cache or in-memory fallback."""
    data = bytes(value) if not isinstance(value, bytes) else value
    if _redis_binary_client is not None:
        try:
            import asyncio

            await asyncio.wait_for(_redis_binary_client.set(key, data, ex=ttl_seconds), timeout=1.0)
            return
        except Exception as e:
            logger.warning("Redis set_tile_cache failed for %s: %s, falling back to memory", key, e)
    elif _redis_client is not None:
        try:
            import asyncio

            await asyncio.wait_for(_redis_client.set(key, data.decode("latin1"), ex=ttl_seconds), timeout=1.0)
            return
        except Exception as e:
            logger.warning("Redis set_tile_cache failed for %s: %s, falling back to memory", key, e)

    _memory_store[key] = data
    _memory_expiry[key] = time.time() + ttl_seconds

