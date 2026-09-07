"""
Coastal Ports Database Repository
Owner: M-B (Data Extractors & Storage)
Module: backend/crud/ports.py

Handles PostgreSQL database operations for coastal fishing harbors and ports.
"""

from typing import Any, Dict, List, Optional
from sqlalchemy import cast, func, select, Text
from sqlalchemy.ext.asyncio import AsyncSession
from backend.crud.base import CRUDBase
from backend.db.models import CoastalPort
from backend.schemas.ports import CoastalPortCreate, CoastalPortUpdate


class CRUDCoastalPort(CRUDBase[CoastalPort, CoastalPortCreate, CoastalPortUpdate]):
    """Specialized CRUD repository for CoastalPort entities."""

    async def get_by_name(self, db: AsyncSession, *, name: str) -> Optional[CoastalPort]:
        """Fetch port by exact or case-insensitive name."""
        stmt = select(CoastalPort).where(func.lower(CoastalPort.name) == name.strip().lower())
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_state(
        self,
        db: AsyncSession,
        *,
        state: str,
        skip: int = 0,
        limit: int = 100,
    ) -> List[CoastalPort]:
        """Fetch ports belonging to a maritime state."""
        stmt = (
            select(CoastalPort)
            .where(func.lower(CoastalPort.state) == state.strip().lower())
            .order_by(CoastalPort.name.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def search_ports(
        self,
        db: AsyncSession,
        *,
        query: str,
        skip: int = 0,
        limit: int = 50,
    ) -> List[CoastalPort]:
        """Search ports by name, state, or regional alias."""
        term = f"%{query.strip().lower()}%"
        stmt = (
            select(CoastalPort)
            .where(
                (func.lower(CoastalPort.name).like(term))
                | (func.lower(CoastalPort.state).like(term))
                | (func.lower(cast(CoastalPort.aliases, Text)).like(term))
            )
            .order_by(CoastalPort.name.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        *,
        obj_in: CoastalPortCreate | Dict[str, Any],
    ) -> CoastalPort:
        """Create port with spatial Point geometry."""
        data = obj_in if isinstance(obj_in, dict) else obj_in.model_dump()
        lat, lon = data["lat"], data["lon"]
        data["geom"] = f"SRID=4326;POINT({lon} {lat})"

        db_obj = CoastalPort(**data)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        *,
        db_obj: CoastalPort,
        obj_in: CoastalPortUpdate | Dict[str, Any],
    ) -> CoastalPort:
        """Update port and synchronize spatial Point geometry when coordinates change."""
        data = obj_in if isinstance(obj_in, dict) else obj_in.model_dump(exclude_unset=True)
        effective_lat = data.get("lat", db_obj.lat)
        effective_lon = data.get("lon", db_obj.lon)
        if "lat" in data or "lon" in data:
            data["geom"] = f"SRID=4326;POINT({effective_lon} {effective_lat})"
        return await super().update(db, db_obj=db_obj, obj_in=data)


port_crud = CRUDCoastalPort(CoastalPort)
