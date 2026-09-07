"""
PFZ Zone Database Repository
Owner: M-B (Data Extractors & Storage)
Module: backend/crud/pfz.py

Handles PostgreSQL database operations for Potential Fishing Zones (PFZ).
"""

from datetime import date
from typing import Any, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.crud.base import CRUDBase
from backend.db.models import PFZZone
from backend.schemas.pfz import PFZZoneCreate, PFZZoneUpdate


class CRUDPFZ(CRUDBase[PFZZone, PFZZoneCreate, PFZZoneUpdate]):
    """Specialized CRUD repository for PFZZone entities."""

    async def get_by_zone_id(self, db: AsyncSession, *, zone_id: str) -> Optional[PFZZone]:
        """Lookup a PFZ zone by its unique INCOIS zone_id."""
        stmt = select(PFZZone).where(PFZZone.zone_id == zone_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_sector(
        self,
        db: AsyncSession,
        *,
        sector: str,
        valid_date: Optional[date] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[PFZZone]:
        """Fetch zones for a specific sector code or name."""
        sec = sector.strip().upper()
        stmt = select(PFZZone).where(
            (PFZZone.sector == sec) | (PFZZone.sector_name == sec)
        )
        if valid_date:
            stmt = stmt.where(PFZZone.valid_date == valid_date)

        stmt = stmt.order_by(PFZZone.valid_date.desc(), PFZZone.id.asc()).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_with_geom(
        self,
        db: AsyncSession,
        *,
        obj_in: PFZZoneCreate,
    ) -> PFZZone:
        """Create a PFZ zone with WGS84 Point geometry."""
        data = obj_in.model_dump()
        lat, lon = data["lat"], data["lon"]
        data["geom"] = f"SRID=4326;POINT({lon} {lat})"

        db_obj = PFZZone(**data)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj


pfz_crud = CRUDPFZ(PFZZone)
