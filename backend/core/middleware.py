"""
Request Logging Middleware for ORCA Marine Intelligence (US-LOG-001)

Provides:
- ASGI RequestLoggingMiddleware
- X-Request-ID extraction / validation / generation
- Contextvars binding and cleanup
- Request entry/completion latency and status logging
- Response header injection
"""

from __future__ import annotations

import re
import time
import uuid
from typing import List, Optional, Tuple

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.core.logging import bind_contextvars, clear_contextvars, get_logger

logger = get_logger("orca.middleware.request")

# Valid request ID pattern: 1-128 chars of alphanumeric, hyphen, underscore, period
REQUEST_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")


def is_valid_request_id(req_id: Optional[str]) -> bool:
    """Validate incoming X-Request-ID to prevent header injection or malformed data."""
    if not req_id or not isinstance(req_id, str):
        return False
    return bool(REQUEST_ID_PATTERN.match(req_id))


class RequestLoggingMiddleware:
    """
    Pure ASGI middleware for HTTP request correlation, latency measurement,
    and structured access logging.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract incoming X-Request-ID or generate new uuid4 hex
        request_id: Optional[str] = None
        for raw_key, raw_val in scope.get("headers", []):
            if raw_key.lower() == b"x-request-id":
                try:
                    val = raw_val.decode("latin1").strip()
                    if is_valid_request_id(val):
                        request_id = val
                except Exception:
                    pass
                break

        if not request_id:
            request_id = uuid.uuid4().hex

        # Bind request_id to contextvars for all logs in this request lifecycle
        bind_contextvars(request_id=request_id)

        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "")
        start_time = time.perf_counter()

        logger.info(
            "Request started",
            http_method=method,
            method=method,
            path=path,
            client_ip=client_ip,
        )

        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                raw_headers: List[Tuple[bytes, bytes]] = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() != b"x-request-id"
                ]
                raw_headers.append((b"x-request-id", request_id.encode("latin1")))
                message["headers"] = raw_headers

            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info(
                "Request completed",
                http_method=method,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                client_ip=client_ip,
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                "Request failed",
                http_method=method,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                client_ip=client_ip,
                exc_info=exc,
            )
            raise exc
        finally:
            clear_contextvars()


__all__ = ["RequestLoggingMiddleware", "is_valid_request_id"]
