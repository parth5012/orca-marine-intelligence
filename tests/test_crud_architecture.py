"""
Comprehensive Tests for CRUD Architecture, PostgreSQL Source of Truth, and Redis Consistency
Owner: M-C / M-B
Module: tests/test_crud_architecture.py

Validates:
1. CacheManager serialization, key generation, TTL, pattern deletion, and fallbacks.
2. Repository (CRUD) layer operations against PostgreSQL.
3. Service Layer Cache-Aside pattern (Cache Hit on repeat reads).
4. Service Layer Invalidation on Create, Update, and Delete.
5. Resilience & Graceful degradation during Redis outages.
6. RESTful CRUD API endpoints for Coastal Ports.
"""

import asyncio
from datetime import date, datetime
import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.crud.base import CRUDBase
from backend.crud.ports import CRUDCoastalPort
from backend.db.models import CoastalPort, PFZZone
from backend.main import app
from backend.schemas.ports import (
    CoastalPortCreate,
    CoastalPortRead,
    CoastalPortUpdate,
)
from backend.services.base import BaseService
from backend.services.cache import CacheManager
from backend.services.port_service import CoastalPortService, port_service


# ==============================================================================
# 1. CacheManager Serialization & Eviction Tests
# ==============================================================================

class SampleModel(BaseModel):
    id: int
    name: str
    created_at: datetime
    valid_on: date


@pytest.mark.asyncio
async def test_cache_manager_serialization_and_retrieval():
    """Verify CacheManager handles datetime, date, and Pydantic serialization."""
    cache = CacheManager(prefix="test_orca")
    now = datetime(2026, 9, 7, 12, 0, 0)
    today = date(2026, 9, 7)

    item = SampleModel(id=1, name="Kochi Port", created_at=now, valid_on=today)
    key = cache.build_key("sample", item.id)

    # 1. Set in cache
    success = await cache.set(key, item, ttl_seconds=60)
    assert success is True

    # 2. Get untyped dict
    raw = await cache.get(key)
    assert raw is not None
    assert raw["id"] == 1
    assert raw["name"] == "Kochi Port"
    assert "2026-09-07" in raw["created_at"]

    # 3. Get typed Pydantic
    typed = await cache.get_typed(key, SampleModel)
    assert typed is not None
    assert typed.id == 1
    assert typed.name == "Kochi Port"
    assert typed.valid_on == today


@pytest.mark.asyncio
async def test_cache_manager_pattern_deletion_and_invalidation():
    """Verify targeted and pattern-based cache deletion."""
    cache = CacheManager(prefix="test_orca")

    # Populate multiple keys
    await cache.set(cache.build_key("ports", 1), {"id": 1, "name": "Kochi"})
    await cache.set(cache.build_key("ports", 2), {"id": 2, "name": "Vizhinjam"})
    await cache.set(cache.build_query_key("ports", {"state": "Kerala"}), {"items": [{"id": 1}]})
    await cache.set(cache.build_query_key("ports", {"state": "Goa"}), {"items": [{"id": 3}]})

    # Verify keys exist
    assert await cache.get(cache.build_key("ports", 1)) is not None
    assert await cache.get(cache.build_key("ports", 2)) is not None

    # Invalidate port 1 and related collections
    await cache.invalidate_entity("ports", 1)

    # Port 1 and list queries should be gone
    assert await cache.get(cache.build_key("ports", 1)) is None
    assert await cache.get(cache.build_query_key("ports", {"state": "Kerala"})) is None

    # Port 2 should still exist
    assert await cache.get(cache.build_key("ports", 2)) is not None


# ==============================================================================
# 2. Service Layer Cache-Aside & Consistency Tests (PostgreSQL Source of Truth)
# ==============================================================================

@pytest.mark.asyncio
async def test_service_cache_aside_read():
    """
    Test Cache-Aside flow:
    - 1st read: Cache Miss -> calls DB -> populates Cache.
    - 2nd read: Cache Hit -> returns from Cache directly (no DB call).
    """
    cache = CacheManager(prefix="test_orca_aside")
    mock_crud = MagicMock(spec=CRUDCoastalPort)
    mock_db = MagicMock()

    # Fake database record
    fake_port = CoastalPort(
        id=10,
        name="Munambam",
        state="Kerala",
        aliases={"roman": ["munambam"]},
        lat=10.18,
        lon=76.17,
    )
    mock_crud.get = AsyncMock(return_value=fake_port)

    service = CoastalPortService(crud=mock_crud, cache=cache)

    # 1. First read (Cache Miss)
    result1 = await service.get_by_id(mock_db, id=10)
    assert result1 is not None
    assert result1.id == 10
    assert result1.name == "Munambam"
    assert mock_crud.get.call_count == 1  # DB was queried

    # 2. Second read (Cache Hit)
    result2 = await service.get_by_id(mock_db, id=10)
    assert result2 is not None
    assert result2.id == 10
    assert result2.name == "Munambam"
    assert mock_crud.get.call_count == 1  # DB was NOT queried again! Cache Hit!


@pytest.mark.asyncio
async def test_service_create_invalidates_list_caches():
    """
    Test Create consistency:
    - New record committed to PostgreSQL.
    - Stale list caches are invalidated so subsequent queries see fresh data.
    """
    cache = CacheManager(prefix="test_orca_create")
    mock_crud = MagicMock(spec=CRUDCoastalPort)
    mock_db = MagicMock()

    # Pre-populate a cached list
    list_key = cache.build_query_key("ports", {"state": "Kerala"})
    await cache.set(list_key, {"items": [{"id": 1, "name": "Old Port"}], "total": 1})
    assert await cache.get(list_key) is not None

    created_port = CoastalPort(
        id=20,
        name="Beypore",
        state="Kerala",
        aliases={},
        lat=11.16,
        lon=75.80,
    )
    mock_crud.create = AsyncMock(return_value=created_port)

    service = CoastalPortService(crud=mock_crud, cache=cache)

    # Create new port
    port_in = CoastalPortCreate(
        name="Beypore",
        state="Kerala",
        aliases={},
        lat=11.16,
        lon=75.80,
    )
    res = await service.create(mock_db, obj_in=port_in)
    assert res.id == 20
    assert mock_crud.create.call_count == 1

    # List cache should be invalidated
    assert await cache.get(list_key) is None
    # Entity cache should be primed
    entity_key = cache.build_key("ports", 20)
    assert await cache.get(entity_key) is not None


@pytest.mark.asyncio
async def test_service_update_invalidates_stale_cache():
    """
    Test Update consistency:
    - Existing record updated in PostgreSQL.
    - Stale entity cache and list caches are evicted/updated with new data.
    """
    cache = CacheManager(prefix="test_orca_update")
    mock_crud = MagicMock(spec=CRUDCoastalPort)
    mock_db = MagicMock()

    initial_port = CoastalPort(id=30, name="Old Name", state="Goa", aliases={}, lat=15.0, lon=73.0)
    updated_port = CoastalPort(id=30, name="Panaji Port", state="Goa", aliases={}, lat=15.0, lon=73.0)

    mock_crud.get = AsyncMock(return_value=initial_port)
    mock_crud.update = AsyncMock(return_value=updated_port)

    service = CoastalPortService(crud=mock_crud, cache=cache)

    # Prime initial cache
    entity_key = cache.build_key("ports", 30)
    await cache.set(entity_key, {"id": 30, "name": "Old Name", "state": "Goa", "aliases": {}, "lat": 15.0, "lon": 73.0})

    # Update port
    update_in = CoastalPortUpdate(name="Panaji Port")
    res = await service.update(mock_db, id=30, obj_in=update_in)
    assert res is not None
    assert res.name == "Panaji Port"

    # Cache should now contain updated value
    cached = await cache.get(entity_key)
    assert cached is not None
    assert cached["name"] == "Panaji Port"


@pytest.mark.asyncio
async def test_service_delete_evicts_cache():
    """
    Test Delete consistency:
    - Record deleted from PostgreSQL.
    - Entity cache and list caches evicted.
    """
    cache = CacheManager(prefix="test_orca_delete")
    mock_crud = MagicMock(spec=CRUDCoastalPort)
    mock_db = MagicMock()

    port_to_delete = CoastalPort(id=40, name="Karwar", state="Karnataka", aliases={}, lat=14.8, lon=74.1)
    mock_crud.get = AsyncMock(return_value=port_to_delete)
    mock_crud.delete = AsyncMock(return_value=port_to_delete)

    service = CoastalPortService(crud=mock_crud, cache=cache)

    # Prime cache
    entity_key = cache.build_key("ports", 40)
    await cache.set(entity_key, {"id": 40, "name": "Karwar", "state": "Karnataka", "aliases": {}, "lat": 14.8, "lon": 74.1})
    assert await cache.get(entity_key) is not None

    # Delete
    deleted = await service.delete(mock_db, id=40)
    assert deleted is not None
    assert deleted.id == 40
    assert mock_crud.delete.call_count == 1

    # Entity key must be evicted
    assert await cache.get(entity_key) is None


# ==============================================================================
# 3. Resilience & Degradation Tests (Redis Outage)
# ==============================================================================

@pytest.mark.asyncio
async def test_service_resilience_on_cache_failure():
    """
    Verify that when Redis throws errors/timeouts, the Service Layer
    transparently degrades and serves directly from PostgreSQL without crashing.
    """
    failing_cache = CacheManager(prefix="failing")
    failing_cache.get = AsyncMock(side_effect=Exception("Redis connection refused"))
    failing_cache.set = AsyncMock(side_effect=Exception("Redis timeout"))

    mock_crud = MagicMock(spec=CRUDCoastalPort)
    mock_db = MagicMock()

    fake_port = CoastalPort(id=50, name="Ratnagiri", state="Maharashtra", aliases={}, lat=16.9, lon=73.3)
    mock_crud.get = AsyncMock(return_value=fake_port)

    service = CoastalPortService(crud=mock_crud, cache=failing_cache)

    # Should not throw exception; should return DB result safely
    res = await service.get_by_id(mock_db, id=50)
    assert res is not None
    assert res.id == 50
    assert res.name == "Ratnagiri"


# ==============================================================================
# 4. RESTful API Endpoint Integration Tests
# ==============================================================================

@pytest.fixture
def api_client():
    """Test client with mocked lifespan health checks for fast testing."""
    with patch("backend.main.check_database", new_callable=AsyncMock) as m_db, \
         patch("backend.main.check_redis", new_callable=AsyncMock) as m_rd:
        m_db.return_value = "connected"
        m_rd.return_value = "connected"
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


def test_api_list_ports_endpoint(api_client):
    """Verify GET /api/ports returns paginated schema."""
    fake_port = CoastalPortRead(id=1, name="Kochi", state="Kerala", aliases={}, lat=9.93, lon=76.26)
    mock_paginated = {"items": [fake_port.model_dump()], "total": 1, "skip": 0, "limit": 50, "cached": False}

    with patch.object(port_service, "get_multi", new_callable=AsyncMock) as mock_get_multi:
        mock_get_multi.return_value = mock_paginated

        resp = api_client.get("/api/ports?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "Kochi"


def test_api_create_port_endpoint(api_client):
    """Verify POST /api/ports creates port and returns 201."""
    created_port = CoastalPortRead(id=99, name="Tuticorin", state="Tamil Nadu", aliases={}, lat=8.76, lon=78.13)

    with patch.object(port_service, "get_by_name", new_callable=AsyncMock) as mock_name, \
         patch.object(port_service, "create", new_callable=AsyncMock) as mock_create:
        mock_name.return_value = None
        mock_create.return_value = created_port

        payload = {
            "name": "Tuticorin",
            "state": "Tamil Nadu",
            "aliases": {"ta": ["தூத்துக்குடி"]},
            "lat": 8.76,
            "lon": 78.13,
        }
        resp = api_client.post("/api/ports", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == 99
        assert data["name"] == "Tuticorin"


def test_api_get_port_not_found(api_client):
    """Verify GET /api/ports/{id} returns 404 on missing entity."""
    with patch.object(port_service, "get_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        resp = api_client.get("/api/ports/99999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


def test_api_delete_port_endpoint(api_client):
    """Verify DELETE /api/ports/{id} returns 204."""
    deleted_port = CoastalPortRead(id=88, name="Mangalore", state="Karnataka", aliases={}, lat=12.91, lon=74.85)

    with patch.object(port_service, "delete", new_callable=AsyncMock) as mock_delete:
        mock_delete.return_value = deleted_port

        resp = api_client.delete("/api/ports/88")
        assert resp.status_code == 204


# ==============================================================================
# 5. Regression Tests for Edge Cases & Fixes
# ==============================================================================

@pytest.mark.asyncio
async def test_port_update_syncs_geom():
    """Verify that updating coordinates updates geom geometry column."""
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    initial_port = CoastalPort(id=1, name="Kochi", state="Kerala", aliases={}, lat=9.93, lon=76.26)
    initial_port.geom = "SRID=4326;POINT(76.26 9.93)"

    crud = CRUDCoastalPort(CoastalPort)
    update_in = CoastalPortUpdate(lat=10.05, lon=76.35)

    updated = await crud.update(mock_db, db_obj=initial_port, obj_in=update_in)
    assert updated.lat == 10.05
    assert updated.lon == 76.35
    assert updated.geom == "SRID=4326;POINT(76.35 10.05)"


@pytest.mark.asyncio
async def test_cache_invalidation_covers_derived_key_types():
    """Verify invalidation evicts by_name, search, and sector derived cache keys."""
    cache = CacheManager(prefix="test_derived")

    # Populate entity and derived keys
    entity_key = cache.build_key("ports", 1)
    by_name_key = cache.build_key("ports", "by_name", "kochi")
    search_key = cache.build_query_key("ports:search", {"q": "kochi", "skip": 0, "limit": 20})
    list_key = cache.build_query_key("ports", {"state": "Kerala"})
    pfz_sector_key = cache.build_query_key("pfz:sector", {"sector": "KERALA"})

    await cache.set(entity_key, {"id": 1, "name": "Kochi"})
    await cache.set(by_name_key, {"id": 1, "name": "Kochi"})
    await cache.set(search_key, [{"id": 1}])
    await cache.set(list_key, {"items": [{"id": 1}], "total": 1})
    await cache.set(pfz_sector_key, [{"id": 101}])

    # Invalidate ports
    await cache.invalidate_entity("ports", 1)

    assert await cache.get(entity_key) is None
    assert await cache.get(by_name_key) is None
    assert await cache.get(search_key) is None
    assert await cache.get(list_key) is None

    # PFZ sector key should still be intact until pfz invalidation
    assert await cache.get(pfz_sector_key) is not None
    await cache.invalidate_collections("pfz")
    assert await cache.get(pfz_sector_key) is None


@pytest.mark.asyncio
async def test_chat_session_service_logger_on_cache_error():
    """Verify that chat_session_service logs warning on cache sync failure without NameError."""
    from backend.services.chat_session_service import ChatSessionService
    from backend.db.models import ChatMessage, ChatSession

    failing_cache = CacheManager(prefix="failing_chat")
    failing_cache.get = AsyncMock(side_effect=Exception("Redis cache failure"))
    failing_cache.set = AsyncMock(side_effect=Exception("Redis set failure"))
    failing_cache.invalidate_entity = AsyncMock(side_effect=Exception("Redis invalidation failure"))

    mock_session_crud = MagicMock()
    mock_msg_crud = MagicMock()
    mock_db = MagicMock()

    mock_session_crud.get = AsyncMock(return_value=ChatSession(session_id="sess_123", preferred_language="en"))
    mock_msg_crud.append_message = AsyncMock(
        return_value=ChatMessage(id=1, session_id="sess_123", sender="user", message="hello")
    )

    service = ChatSessionService(session_crud=mock_session_crud, message_crud=mock_msg_crud, cache=failing_cache)

    # Should succeed cleanly without NameError: name 'logger' is not defined
    res = await service.append_message(mock_db, session_id="sess_123", sender="user", message="hello")
    assert res.message == "hello"
    assert res.sender == "user"

