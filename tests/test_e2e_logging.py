"""
End-to-End Integration Test Suite for Unified Logging Infrastructure (US-LOG-001)

Verifies:
1. End-to-end client-to-server request lifecycle across core endpoints:
   - Root ('/'), Health ('/health'), Geofence ('/api/geofence/status'),
     Weather ('/api/weather/current'), Tiles ('/api/tiles/config'), Chat ('/api/chat')
2. Structured access log emission with all required fields:
   - timestamp, level, event/message, http_method, path, status_code, duration_ms, request_id
3. Edge case: Custom valid X-Request-ID preservation and propagation
4. Edge case: Missing X-Request-ID generation of valid UUIDv4
5. Edge case: Malformed X-Request-ID detection and replacement with valid UUIDv4
6. Edge case: 404 Not Found and 422 Unprocessable Entity error logging
7. Edge case: Concurrency isolation of contextvars across simultaneous requests
8. Frontend logger correlation: Client-generated X-Request-ID matched on server
"""

import asyncio
import io
import json
import logging
import uuid
from typing import Any, Dict, List

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.core.logging import clear_contextvars, setup_logging
from backend.main import app


@pytest.fixture(autouse=True)
def clean_context_and_logging():
    """Ensure contextvars and log streams are pristine before and after every test."""
    clear_contextvars()
    yield
    clear_contextvars()


def setup_log_capture(log_level: str = "INFO") -> io.StringIO:
    """Configure structured JSON logging and attach an in-memory buffer."""
    stream = io.StringIO()
    setup_logging(log_level=log_level, log_format="json")
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = stream
    return stream


def parse_captured_logs(stream: io.StringIO) -> List[Dict[str, Any]]:
    """Parse captured JSON log lines into dictionaries."""
    logs = []
    for line in stream.getvalue().splitlines():
        line = line.strip()
        if line:
            try:
                logs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return logs


# ============================================================================
# 1. Full Request Lifecycle Across Core Endpoints
# ============================================================================

@pytest.mark.parametrize(
    "method,endpoint,payload,expected_status",
    [
        ("GET", "/", None, 200),
        ("GET", "/health", None, 200),
        ("GET", "/api/geofence/status", None, 200),
        ("GET", "/api/weather/current?lat=18.9&lon=72.8", None, 200),
        ("GET", "/api/tiles/config", None, 200),
        ("POST", "/api/chat", {"message": "Is it safe to sail today?"}, 200),
    ],
)
def test_e2e_request_lifecycle_core_endpoints(
    method: str, endpoint: str, payload: Any, expected_status: int
):
    """
    Verify client-to-server request lifecycle across all core endpoints:
    middleware intercepts, binds contextvars, returns matching X-Request-ID,
    and logs access entries.
    """
    stream = setup_log_capture()
    client = TestClient(app)
    custom_id = f"client-req-{uuid.uuid4().hex[:12]}"

    headers = {"X-Request-ID": custom_id}
    if method == "GET":
        response = client.get(endpoint, headers=headers)
    else:
        response = client.post(endpoint, json=payload, headers=headers)

    assert response.status_code == expected_status
    assert response.headers.get("x-request-id") == custom_id

    logs = parse_captured_logs(stream)
    completed_logs = [
        log for log in logs
        if (log.get("event") == "Request completed" or log.get("message") == "Request completed")
        and log.get("request_id") == custom_id
    ]
    assert len(completed_logs) >= 1, f"Missing completed log for {endpoint}"
    access_log = completed_logs[0]
    assert access_log["request_id"] == custom_id
    assert access_log["http_method"] == method
    assert access_log["status_code"] == expected_status
    assert "duration_ms" in access_log
    assert access_log["duration_ms"] >= 0


# ============================================================================
# 2. Structured Access Log Field Verification
# ============================================================================

def test_e2e_structured_access_log_fields():
    """
    Verify structured access logs contain all mandatory fields:
    timestamp, level, event/message, http_method, path, status_code, duration_ms, request_id.
    """
    stream = setup_log_capture()
    client = TestClient(app)
    req_id = "test-field-verification-id"

    response = client.get("/health", headers={"X-Request-ID": req_id})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == req_id

    logs = parse_captured_logs(stream)
    access_logs = [
        log for log in logs
        if log.get("event") == "Request completed" and log.get("request_id") == req_id
    ]
    assert len(access_logs) == 1
    log = access_logs[0]

    # Required fields verification
    assert "timestamp" in log, "Missing 'timestamp' field"
    assert "level" in log, "Missing 'level' field"
    assert log["level"] == "info"
    assert log.get("event") == "Request completed"
    assert "http_method" in log, "Missing 'http_method' field"
    assert log["http_method"] == "GET"
    assert "path" in log, "Missing 'path' field"
    assert log["path"] == "/health"
    assert "status_code" in log, "Missing 'status_code' field"
    assert log["status_code"] == 200
    assert "duration_ms" in log, "Missing 'duration_ms' field"
    assert isinstance(log["duration_ms"], (int, float))
    assert log["duration_ms"] >= 0
    assert "request_id" in log, "Missing 'request_id' field"
    assert log["request_id"] == req_id


# ============================================================================
# 3. Edge Case: Custom Valid X-Request-ID Client Propagated
# ============================================================================

@pytest.mark.parametrize(
    "valid_custom_id",
    [
        "c9bf9e57-1685-4c89-bafb-ff5af830be8a",  # Standard UUID format
        "orca-client-uuid-001",                   # Alphanumeric with hyphens
        "trace_999.node_1",                      # Underscore and period
        "83dc17a3f8c6465a95b7e4223d917e72",      # 32-character hex
    ],
)
def test_e2e_custom_valid_request_id_propagated(valid_custom_id: str):
    """
    Verify client-supplied valid X-Request-ID is preserved across middleware,
    injected in response header, and bound into all structured logs.
    """
    stream = setup_log_capture()
    client = TestClient(app)

    response = client.get("/api/tiles/config", headers={"X-Request-ID": valid_custom_id})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == valid_custom_id

    logs = parse_captured_logs(stream)
    matched_logs = [log for log in logs if log.get("request_id") == valid_custom_id]
    assert len(matched_logs) >= 1
    # Check start and completed logs have the same request_id
    events = [log.get("event") for log in matched_logs]
    assert "Request started" in events
    assert "Request completed" in events


# ============================================================================
# 4. Edge Case: Missing X-Request-ID Replaced by Valid UUIDv4
# ============================================================================

def test_e2e_missing_request_id_generates_valid_uuidv4():
    """
    Verify requests omitting X-Request-ID receive a generated UUIDv4 hex,
    returned in response headers and bound in logs.
    """
    stream = setup_log_capture()
    client = TestClient(app)

    response = client.get("/api/geofence/status")
    assert response.status_code == 200
    assigned_id = response.headers.get("x-request-id")
    assert assigned_id is not None
    assert len(assigned_id) == 32
    # Validate it is valid hexadecimal and valid UUIDv4
    parsed_uuid = uuid.UUID(assigned_id, version=4)
    assert parsed_uuid.hex == assigned_id

    logs = parse_captured_logs(stream)
    matched_logs = [log for log in logs if log.get("request_id") == assigned_id]
    assert len(matched_logs) >= 1
    assert matched_logs[0]["request_id"] == assigned_id


# ============================================================================
# 5. Edge Case: Malformed X-Request-ID Replaced by Valid UUIDv4
# ============================================================================

@pytest.mark.parametrize(
    "malformed_id",
    [
        "invalid request id with spaces",        # Contains spaces
        "header\r\ninjection: bad",              # CRLF injection attempt
        "<script>alert('xss')</script>",         # XSS / HTML tags
        "???$$$###@@@!",                         # Disallowed special characters
        "   ",                                   # Whitespace only
        "a" * 200,                               # Exceeds maximum 128 chars
    ],
)
def test_e2e_malformed_request_id_replaced_by_uuidv4(malformed_id: str):
    """
    Verify malformed X-Request-ID is rejected and replaced by a valid UUIDv4.
    The malformed value must NOT be echoed in headers or logs.
    """
    stream = setup_log_capture()
    client = TestClient(app)

    response = client.get("/health", headers={"X-Request-ID": malformed_id})
    assert response.status_code == 200

    assigned_id = response.headers.get("x-request-id")
    assert assigned_id is not None
    assert assigned_id != malformed_id
    assert len(assigned_id) == 32

    # Validate that the replacement is a valid UUIDv4
    parsed_uuid = uuid.UUID(assigned_id, version=4)
    assert parsed_uuid.hex == assigned_id

    # Verify logs do NOT contain the malformed input and DO contain the clean UUID
    raw_logs = stream.getvalue()
    assert malformed_id not in raw_logs

    logs = parse_captured_logs(stream)
    matched_logs = [log for log in logs if log.get("request_id") == assigned_id]
    assert len(matched_logs) >= 1


# ============================================================================
# 6. Edge Case: 404 Not Found & 422 Validation Error Logging
# ============================================================================

def test_e2e_404_not_found_logged_with_status_and_duration():
    """
    Verify 404 Not Found responses are captured by middleware,
    logging appropriate status_code (404), duration_ms, and request_id.
    """
    stream = setup_log_capture()
    client = TestClient(app)
    req_id = f"client-404-{uuid.uuid4().hex[:8]}"

    response = client.get("/api/nonexistent-route-for-testing", headers={"X-Request-ID": req_id})
    assert response.status_code == 404
    assert response.headers.get("x-request-id") == req_id

    logs = parse_captured_logs(stream)
    completed_logs = [
        log for log in logs
        if log.get("event") == "Request completed" and log.get("request_id") == req_id
    ]
    assert len(completed_logs) == 1
    log = completed_logs[0]
    assert log["status_code"] == 404
    assert log["http_method"] == "GET"
    assert log["path"] == "/api/nonexistent-route-for-testing"
    assert "duration_ms" in log
    assert log["duration_ms"] >= 0


def test_e2e_422_validation_error_logged_with_status_and_duration():
    """
    Verify 422 Unprocessable Entity validation errors are logged with
    appropriate status_code (422), duration_ms, and request_id.
    """
    stream = setup_log_capture()
    client = TestClient(app)
    req_id = f"client-422-{uuid.uuid4().hex[:8]}"

    # Sending invalid empty payload to POST /api/chat which requires 'message'
    response = client.post("/api/chat", json={}, headers={"X-Request-ID": req_id})
    assert response.status_code == 422
    assert response.headers.get("x-request-id") == req_id

    logs = parse_captured_logs(stream)
    completed_logs = [
        log for log in logs
        if log.get("event") == "Request completed" and log.get("request_id") == req_id
    ]
    assert len(completed_logs) == 1
    log = completed_logs[0]
    assert log["status_code"] == 422
    assert log["http_method"] == "POST"
    assert log["path"] == "/api/chat"
    assert "duration_ms" in log
    assert log["duration_ms"] >= 0


# ============================================================================
# 7. Edge Case: Concurrent Requests Isolation
# ============================================================================

@pytest.mark.asyncio
async def test_e2e_concurrent_requests_maintain_isolated_contextvars():
    """
    Verify concurrent requests maintain isolated contextvars and distinct
    request IDs without cross-contamination.
    """
    stream = setup_log_capture()
    num_requests = 16

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as async_client:

        async def send_request(idx: int):
            req_id = f"concurrent-req-{idx}-{uuid.uuid4().hex[:6]}"
            res = await async_client.get(
                "/api/tiles/config",
                headers={"X-Request-ID": req_id}
            )
            return req_id, res

        tasks = [send_request(i) for i in range(num_requests)]
        results = await asyncio.gather(*tasks)

    # Verify each response header matched its own unique request ID
    assigned_ids = set()
    for req_id, response in results:
        assert response.status_code == 200
        header_id = response.headers.get("x-request-id")
        assert header_id == req_id
        assigned_ids.add(header_id)

    # Ensure all 16 request IDs are completely distinct
    assert len(assigned_ids) == num_requests

    # Verify logs for all requests are isolated and mapped correctly
    logs = parse_captured_logs(stream)
    for req_id in assigned_ids:
        matched = [
            log for log in logs
            if log.get("event") == "Request completed" and log.get("request_id") == req_id
        ]
        assert len(matched) == 1, f"Expected exactly 1 completion log for {req_id}"
        assert matched[0]["status_code"] == 200
        assert matched[0]["path"] == "/api/tiles/config"


# ============================================================================
# 8. Frontend Logger Emulation & End-to-End Correlation
# ============================================================================

def test_e2e_frontend_logger_request_correlation():
    """
    Emulate the frontend lib/logger.ts behavior:
    - Frontend injects standard X-Request-ID (UUID format)
    - Sends request to backend
    - Backend preserves and logs request_id
    - Backend returns matching X-Request-ID in response
    - Frontend receives and correlates the response
    """
    stream = setup_log_capture()
    client = TestClient(app)

    # Emulate frontend generateRequestId()
    frontend_request_id = str(uuid.uuid4())

    # Emulate frontend injectRequestId / fetchWithRequestId
    frontend_headers = {
        "Content-Type": "application/json",
        "X-Request-ID": frontend_request_id,
    }

    response = client.get("/health", headers=frontend_headers)
    assert response.status_code == 200

    # Frontend asserts response matches correlated request ID
    response_request_id = response.headers.get("x-request-id")
    assert response_request_id == frontend_request_id

    # Backend access log verification
    logs = parse_captured_logs(stream)
    correlated_logs = [
        log for log in logs
        if log.get("request_id") == frontend_request_id
    ]
    assert len(correlated_logs) >= 1
    completion_log = next(
        log for log in correlated_logs if log.get("event") == "Request completed"
    )
    assert completion_log["status_code"] == 200
    assert completion_log["http_method"] == "GET"
    assert completion_log["path"] == "/health"
    assert completion_log["request_id"] == frontend_request_id
