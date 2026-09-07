"""
Base Pydantic Schemas & DTO Utilities
Owner: M-C / M-B (Platform & Data)
Module: backend/schemas/base.py

Provides common pagination, metadata, and API response wrappers.
"""

from typing import Generic, List, Optional, TypeVar
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Standard query parameters for paginated queries."""
    skip: int = Field(0, ge=0, description="Number of items to skip")
    limit: int = Field(50, ge=1, le=1000, description="Max number of items to return")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard envelope for paginated collections."""
    model_config = ConfigDict(from_attributes=True)

    items: List[T]
    total: int = Field(..., description="Total count matching filter")
    skip: int = Field(0, description="Offset used")
    limit: int = Field(50, description="Limit used")
    cached: bool = Field(False, description="Whether response was served from cache")


class BaseResponse(BaseModel, Generic[T]):
    """Standard generic API single-item response envelope."""
    status: str = "success"
    data: Optional[T] = None
    message: Optional[str] = None
    cached: bool = False
