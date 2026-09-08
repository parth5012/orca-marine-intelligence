"""
Tests for Structured Logging Infrastructure (US-LOG-001)

Validates:
- setup_logging for JSON and console formats
- Environment variable configuration (LOG_LEVEL, LOG_FORMAT)
- get_logger structured field binding
- Contextvars manipulation (bind_contextvars, unbind_contextvars, clear_contextvars)
- Standard library logging bridge (ProcessorFormatter)
- RequestLoggingMiddleware X-Request-ID propagation and metrics
"""

import io
import json
import logging
import uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.logging import (
    setup_logging,
    get_logger,
    bind_contextvars,
    unbind_contextvars,
    clear_contextvars,
)
from backend.core.middleware import RequestLoggingMiddleware
import structlog


@pytest.fixture(autouse=True)
def cleanup_logging():
    """Ensure contextvars and log handlers are cleanly reset after each test."""
    clear_contextvars()
    yield
    clear_contextvars()


def test_setup_logging_json_format(monkeypatch):
    """Verify setup_logging with JSON format emits valid structured JSON."""
    stream = io.StringIO()
    setup_logging(log_level="DEBUG", log_format="json")

    # Replace root handler stream to capture output
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = stream

    logger = get_logger("orca.test.json")
    logger.info("JSON log message", user_id="12345", action="login")

    output = stream.getvalue().strip()
    assert output, "Log output should not be empty"

    # Must parse as valid JSON
    data = json.loads(output)
    assert data["event"] == "JSON log message"
    assert data["logger"] == "orca.test.json"
    assert data["level"] == "info"
    assert data["user_id"] == "12345"
    assert data["action"] == "login"
    assert "timestamp" in data


def test_setup_logging_stdlib_bridge(monkeypatch):
    """Verify stdlib logging calls pass through structlog processors and output JSON."""
    stream = io.StringIO()
    setup_logging(log_level="INFO", log_format="json")

    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = stream

    std_logger = logging.getLogger("orca.stdlib.test")
    std_logger.info("Standard library log event")

    output = stream.getvalue().strip()
    assert output, "Log output should not be empty"

    data = json.loads(output)
    assert data["event"] == "Standard library log event"
    assert data["logger"] == "orca.stdlib.test"
    assert data["level"] == "info"
    assert "timestamp" in data


def test_setup_logging_console_format(monkeypatch):
    """Verify setup_logging with console format outputs human-readable text."""
    stream = io.StringIO()
    setup_logging(log_level="INFO", log_format="console")

    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = stream

    logger = get_logger("orca.test.console")
    logger.info("Console message", key="val")

    output = stream.getvalue().strip()
    assert "Console message" in output
    assert "orca.test.console" in output
    assert "val" in output


def test_setup_logging_env_vars(monkeypatch):
    """Verify setup_logging respects LOG_LEVEL and LOG_FORMAT environment variables."""
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("LOG_FORMAT", "json")

    stream = io.StringIO()
    setup_logging()

    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = stream

    logger = get_logger("orca.test.env")
    logger.info("This should be filtered out by WARNING level")
    assert stream.getvalue().strip() == ""

    logger.warning("This warning should be logged")
    output = stream.getvalue().strip()
    assert output != ""
    data = json.loads(output)
    assert data["level"] == "warning"
    assert data["event"] == "This warning should be logged"


def test_bind_and_clear_contextvars():
    """Verify bind_contextvars, unbind_contextvars, and clear_contextvars."""
    stream = io.StringIO()
    setup_logging(log_level="INFO", log_format="json")

    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = stream

    logger = get_logger("orca.test.contextvars")

    bind_contextvars(req_id="abc-123", tenant="navy")
    logger.info("Bound test")
    data = json.loads(stream.getvalue().splitlines()[-1])
    assert data["req_id"] == "abc-123"
    assert data["tenant"] == "navy"

    unbind_contextvars("tenant")
    logger.info("Unbound test")
    data2 = json.loads(stream.getvalue().splitlines()[-1])
    assert data2["req_id"] == "abc-123"
    assert "tenant" not in data2

    clear_contextvars()
    logger.info("Cleared test")
    data3 = json.loads(stream.getvalue().splitlines()[-1])
    assert "req_id" not in data3
    assert "tenant" not in data3


def test_request_logging_middleware_generated_request_id():
    """Verify middleware generates UUID request_id and injects X-Request-ID header."""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    captured_cv = {}

    @app.get("/test-endpoint")
    async def sample():
        captured_cv.update(structlog.contextvars.get_contextvars())
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/test-endpoint")
        assert response.status_code == 200
        assert "x-request-id" in response.headers
        req_id = response.headers["x-request-id"]
        # Ensure it is a valid hex uuid
        assert len(req_id) == 32
        int(req_id, 16)  # Validates hex

        # Contextvars inside endpoint must have received request_id
        assert captured_cv.get("request_id") == req_id

    # Contextvars must be cleared outside the request
    assert "request_id" not in structlog.contextvars.get_contextvars()


def test_request_logging_middleware_propagates_request_id():
    """Verify incoming X-Request-ID is preserved and propagated."""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    custom_id = "custom-req-id-789"
    captured_cv = {}

    @app.get("/test-endpoint")
    async def sample():
        captured_cv.update(structlog.contextvars.get_contextvars())
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/test-endpoint", headers={"X-Request-ID": custom_id})
        assert response.status_code == 200
        assert response.headers.get("x-request-id") == custom_id
        assert captured_cv.get("request_id") == custom_id


def test_request_logging_middleware_logs_entry_and_completion():
    """Verify request entry and completion are logged with method, path, status, duration_ms, client_ip."""
    stream = io.StringIO()
    setup_logging(log_level="INFO", log_format="json")

    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = stream

    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/metric-test")
    async def metric_route():
        return {"status": "ok"}

    with TestClient(app) as client:
        res = client.get("/metric-test")
        assert res.status_code == 200

    logs = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    assert len(logs) >= 2

    # Entry log
    start_log = next(log for log in logs if log.get("event") == "Request started")
    assert start_log["method"] == "GET"
    assert start_log["path"] == "/metric-test"
    assert "client_ip" in start_log
    assert "request_id" in start_log

    # Completion log
    end_log = next(log for log in logs if log.get("event") == "Request completed")
    assert end_log["method"] == "GET"
    assert end_log["path"] == "/metric-test"
    assert end_log["status_code"] == 200
    assert "duration_ms" in end_log
    assert isinstance(end_log["duration_ms"], (int, float))
    assert end_log["duration_ms"] >= 0
    assert "client_ip" in end_log
    assert "request_id" in end_log


def test_main_app_request_id_header():
    """Verify backend.main.app mounts RequestLoggingMiddleware and returns X-Request-ID on /health."""
    from backend.main import app as main_app

    with TestClient(main_app, raise_server_exceptions=False) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert "x-request-id" in response.headers
        req_id = response.headers["x-request-id"]
        assert len(req_id) == 32


def test_request_logging_middleware_rejects_malformed_id():
    """Verify malformed/injected X-Request-ID is rejected and replaced with a fresh id."""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/test-endpoint")
    async def sample():
        return {"ok": True}

    with TestClient(app) as client:
        bad_id = "bad\r\ninject<script>"
        response = client.get("/test-endpoint", headers={"X-Request-ID": bad_id})
        assert response.status_code == 200
        returned = response.headers.get("x-request-id")
        assert returned is not None
        assert returned != bad_id
        assert len(returned) == 32
        int(returned, 16)

        long_id = "x" * 200
        response2 = client.get("/test-endpoint", headers={"X-Request-ID": long_id})
        assert response2.headers.get("x-request-id") != long_id


def test_safe_serializer_and_redaction():
    """Verify circular/non-serializable context does not crash and sensitive keys are redacted."""
    stream = io.StringIO()
    setup_logging(log_level="INFO", log_format="json")

    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = stream

    logger = get_logger("orca.test.safety")
    circular: dict = {}
    circular["self"] = circular
    logger.info("safety check", extra_field=circular, password="supersecret", authorization="Bearer abc")
    output = stream.getvalue().strip().splitlines()[-1]
    data = json.loads(output)
    assert data["event"] == "safety check"
    assert data.get("password") == "***REDACTED***"
    assert data.get("authorization") == "***REDACTED***"

