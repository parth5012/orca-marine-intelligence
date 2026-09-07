"""
Generic CRUD Base Repository for SQLAlchemy 2.0 Async
Owner: M-B (Data Extractors & Storage)
Module: backend/crud/base.py

Provides reusable, type-safe async CRUD database operations directly against PostgreSQL.
Decoupled from HTTP requests and caching layers.
"""

from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.models import Base

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    CRUD Base class with default methods to Create, Read, Update, Delete (CRUD).
    PostgreSQL is the single source of truth.
    """

    def __init__(self, model: Type[ModelType]):
        """
        CRUD object with default methods to Create, Read, Update, Delete (CRUD).

        **Parameters**
        * `model`: A SQLAlchemy model class
        """
        self.model = model

    async def get(self, db: AsyncSession, id: Any) -> Optional[ModelType]:
        """Fetch a single record by primary key."""
        return await db.get(self.model, id)

    async def get_multi(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[Any] = None,
    ) -> List[ModelType]:
        """Fetch a list of records with optional filtering and pagination."""
        stmt = select(self.model)

        if filters:
            for field, value in filters.items():
                if value is not None and hasattr(self.model, field):
                    stmt = stmt.where(getattr(self.model, field) == value)

        if order_by is not None:
            stmt = stmt.order_by(order_by)
        elif hasattr(self.model, "id"):
            stmt = stmt.order_by(self.model.id.desc())

        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        db: AsyncSession,
        *,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count total matching records in PostgreSQL."""
        stmt = select(func.count()).select_from(self.model)

        if filters:
            for field, value in filters.items():
                if value is not None and hasattr(self.model, field):
                    stmt = stmt.where(getattr(self.model, field) == value)

        result = await db.execute(stmt)
        return result.scalar_one() or 0

    async def exists(self, db: AsyncSession, id: Any) -> bool:
        """Check if a record exists by primary key."""
        obj = await self.get(db, id)
        return obj is not None

    async def create(
        self,
        db: AsyncSession,
        *,
        obj_in: Union[CreateSchemaType, Dict[str, Any]],
    ) -> ModelType:
        """
        Insert a new record into PostgreSQL and commit transaction.
        PostgreSQL is the source of truth.
        """
        if isinstance(obj_in, dict):
            create_data = obj_in
        else:
            create_data = obj_in.model_dump(exclude_unset=True)

        db_obj = self.model(**create_data)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def create_many(
        self,
        db: AsyncSession,
        *,
        objs_in: List[Union[CreateSchemaType, Dict[str, Any]]],
    ) -> List[ModelType]:
        """Batch insert multiple records."""
        if not objs_in:
            return []

        db_objs = []
        for item in objs_in:
            data = item if isinstance(item, dict) else item.model_dump(exclude_unset=True)
            db_objs.append(self.model(**data))

        db.add_all(db_objs)
        await db.commit()
        for obj in db_objs:
            await db.refresh(obj)
        return db_objs

    async def update(
        self,
        db: AsyncSession,
        *,
        db_obj: ModelType,
        obj_in: Union[UpdateSchemaType, Dict[str, Any]],
    ) -> ModelType:
        """
        Update an existing record in PostgreSQL and commit transaction.
        """
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, *, id: Any) -> Optional[ModelType]:
        """
        Delete a record by primary key from PostgreSQL and commit transaction.
        """
        obj = await db.get(self.model, id)
        if obj is not None:
            await db.delete(obj)
            await db.commit()
        return obj
