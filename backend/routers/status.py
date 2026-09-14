from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel
import logging

logger = logging.getLogger("orca.status")

router = APIRouter(tags=["system"])

async def check_database() -> str:
    """Verify database connection via backend.main or fallback."""
    try:
        from backend.main import check_database as _cd
        return await _cd()
    except Exception as e:
        logger.debug("Status db check error: %s", e)
        return "disconnected"

async def check_redis() -> str:
    """Verify Redis connection via backend.main or fallback."""
    try:
        from backend.main import check_redis as _cr
        return await _cr()
    except Exception as e:
        logger.debug("Status redis check error: %s", e)
        return "disconnected"

class ServiceStatus(BaseModel):
    weather: bool
    pfz: bool
    geofence: bool
    tiles: bool
    chat: bool

class StatusResponse(BaseModel):
    status: str
    services: ServiceStatus

async def check_service(service_name: str) -> bool:
    # Placeholder for actual service health checks
    # This will be expanded in future iterations
    return True  # Assume all services are OK for now

@router.get("/api/status")
async def get_status() -> StatusResponse:
    # Check core services
    db_status = await check_database()
    redis_status = await check_redis()

    # Check individual service dependencies
    services = ServiceStatus(
        weather=await check_service("weather"),
        pfz=await check_service("pfz"),
        geofence=await check_service("geofence"),
        tiles=await check_service("tiles"),
        chat=await check_service("chat")
    )

    # Determine overall status
    overall_status = "ok"
    if db_status != "connected" or redis_status != "connected":
        overall_status = "degraded"
    for service in [services.weather, services.pfz, services.geofence, services.tiles, services.chat]:
        if not service:
            overall_status = "degraded"

    return StatusResponse(
        status=overall_status,
        services=services
    )
