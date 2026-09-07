"""
Coastal Ports CRUD Router
Owner: M-C (Backend API & Platform)
Module: backend/routers/ports.py

Provides production-ready RESTful CRUD endpoints for Coastal Ports & Landing Centers.
Backed by PostgreSQL (Source of Truth) and Redis (Cache-Aside & Invalidation).
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db
from backend.schemas.base import BaseResponse, PaginatedResponse
from backend.schemas.ports import (
    CoastalPortCreate,
    CoastalPortRead,
    CoastalPortUpdate,
)
from backend.services.port_service import CoastalPortService, port_service

router = APIRouter(prefix="/ports", tags=["ports"])


@router.get("", response_model=PaginatedResponse[CoastalPortRead])
async def list_ports(
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(50, ge=1, le=500, description="Page limit"),
    state: Optional[str] = Query(None, description="Filter by coastal state"),
    db: AsyncSession = Depends(get_db),
    service: CoastalPortService = Depends(lambda: port_service),
) -> PaginatedResponse[CoastalPortRead]:
    """
    List coastal ports with pagination and optional state filtering.
    Utilizes Redis query caching with automatic TTL and invalidation.
    """
    filters = {}
    if state:
        filters["state"] = state

    return await service.get_multi(db, skip=skip, limit=limit, filters=filters)


@router.get("/search", response_model=List[CoastalPortRead])
async def search_ports(
    q: str = Query(..., min_length=1, description="Search query for port name or state"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    service: CoastalPortService = Depends(lambda: port_service),
) -> List[CoastalPortRead]:
    """
    Search coastal ports by name, state, or regional aliases.
    Cached in Redis for rapid auto-complete.
    """
    return await service.search_ports(db, query=q, skip=skip, limit=limit)


@router.get("/{port_id}", response_model=CoastalPortRead)
async def get_port(
    port_id: int,
    db: AsyncSession = Depends(get_db),
    service: CoastalPortService = Depends(lambda: port_service),
) -> CoastalPortRead:
    """
    Retrieve single coastal port by ID.
    Enforces Cache-Aside pattern: reads from Redis first; falls back to PostgreSQL on miss.
    """
    port = await service.get_by_id(db, id=port_id)
    if port is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CoastalPort with ID {port_id} not found",
        )
    return port


@router.post("", response_model=CoastalPortRead, status_code=status.HTTP_201_CREATED)
async def create_port(
    port_in: CoastalPortCreate,
    db: AsyncSession = Depends(get_db),
    service: CoastalPortService = Depends(lambda: port_service),
) -> CoastalPortRead:
    """
    Register a new coastal harbor or landing center.
    Persists to PostgreSQL (Source of Truth) and invalidates Redis list caches.
    """
    # Check if port name already exists
    existing = await service.get_by_name(db, name=port_in.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Port with name '{port_in.name}' already exists",
        )
    return await service.create(db, obj_in=port_in)


@router.put("/{port_id}", response_model=CoastalPortRead)
async def update_port(
    port_id: int,
    port_in: CoastalPortUpdate,
    db: AsyncSession = Depends(get_db),
    service: CoastalPortService = Depends(lambda: port_service),
) -> CoastalPortRead:
    """
    Update details of an existing coastal port.
    Commits update to PostgreSQL and immediately invalidates/updates Redis cache for consistency.
    """
    updated = await service.update(db, id=port_id, obj_in=port_in)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CoastalPort with ID {port_id} not found",
        )
    return updated


@router.delete("/{port_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_port(
    port_id: int,
    db: AsyncSession = Depends(get_db),
    service: CoastalPortService = Depends(lambda: port_service),
) -> None:
    """
    Delete a coastal port.
    Removes from PostgreSQL and evicts entity and collection cache keys from Redis.
    """
    deleted = await service.delete(db, id=port_id)
    if deleted is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CoastalPort with ID {port_id} not found",
        )


@router.post("/{port_id}/invalidate-cache", response_model=BaseResponse[str])
async def invalidate_port_cache(
    port_id: int,
    service: CoastalPortService = Depends(lambda: port_service),
) -> BaseResponse[str]:
    """Manually evict cache for a specific port."""
    await service.invalidate_cache(id=port_id)
    return BaseResponse[str](
        status="success",
        data=f"Cache invalidated for port {port_id}",
        message="Port cache evicted successfully",
    )
