# Technical Blueprint: Logging Infrastructure (US-LOG-001)

**Status:** Ready for Implementation  
**Category Member Owner:** M-C (Backend API & Platform) & M-E (Frontend Chat & Platform)  
**Tracking Ticket:** US-LOG-001  
**Target Branches:** `feat/m-c-logging-infra`, `feat/m-e-frontend-logger`  

---

## 1. Architectural Overview & Context

### 1.1 Objective
Establish an end-to-end, asynchronous, structured logging infrastructure across both backend (FastAPI + Structlog) and frontend (Next.js isomorphic logger). All requests across the API lifecycle are assigned a deterministic UUIDv4 `X-Request-ID`, propagating across context variables, HTTP headers, and access logs.

### 1.2 System Boundary & Component Topology
```
[ Browser / Next.js Client ]
      │
      │ fetchWithRequestId() [X-Request-ID: <uuidv4>]
      ▼
[ FastAPI Application (backend/main.py) ]
      │
      ├─► RequestLoggingMiddleware (backend/core/middleware.py)
      │     ├─ Extracts or generates X-Request-ID
      │     ├─ Binds request_id to contextvars
      │     ├─ Times request execution (duration_ms)
      │     └─ Emits structured access log on completion
      │
      ├─► Structured Logger (backend/core/logging.py)
      │     ├─ Processors: merge_contextvars, add_logger_name, add_log_level, TimeStamper, format_exc_info, JSONRenderer / ConsoleRenderer
      │     └─ Contextvar helpers: bind_contextvars, unbind_contextvars, clear_contextvars
      │
      └─► Routers (/api/chat, /api/pfz, /api/weather, /api/geofence, /api/tiles)
            └─ Contextual logs automatically inherit request_id without parameter passing
```

---

## 2. File Modification & Creation Inventory

| File Path | Action | Owner Lane | Description |
|-----------|--------|------------|-------------|
| `backend/core/__init__.py` | CREATE | M-C | Package marker for core platform utilities |
| `backend/core/logging.py` | CREATE | M-C | Structlog configuration, standard library integration, contextvar helpers |
| `backend/core/middleware.py` | CREATE | M-C | ASGI `RequestLoggingMiddleware` for tracing, timing, and access logging |
| `backend/main.py` | MODIFY | M-C | Mount `setup_logging()` in lifespan, mount `RequestLoggingMiddleware`, use structured logger |
| `backend/pyproject.toml` | MODIFY | M-C | Add `"structlog>=24.4.0"` dependency |
| `frontend/lib/logger.ts` | CREATE | M-E | Isomorphic structured logger (client/server), `x-request-id` injection helper |
| `tests/test_logging.py` | CREATE | M-C | Test suite validating structured formatting, middleware tracing, and contextvars |

---

## 3. Detailed Specifications & Contracts

### 3.1 `backend/core/logging.py`

#### Module Scope
Centralizes logging setup. Reconfigures standard library `logging` to delegate to `structlog`. Exposes typed helpers for context variable binding.

#### Exact Interfaces & Signatures
```python
import os
import sys
import logging
from typing import Any, Dict, List, Optional
import structlog
from structlog.typing import EventDict, Processor

def setup_logging(
    log_level: Optional[str] = None,
    log_format: Optional[str] = None
) -> None:
    """
    Configures structlog and standard library logging.
    
    Args:
        log_level: DEBUG, INFO, WARNING, ERROR, CRITICAL. Defaults to env LOG_LEVEL or 'INFO'.
        log_format: 'json' or 'console'. Defaults to env LOG_FORMAT or 'json'.
    """
    ...

def bind_contextvars(**kwargs: Any) -> None:
    """Bind key-value pairs to the current asyncio task/thread contextvars."""
    ...

def unbind_contextvars(*keys: str) -> None:
    """Remove keys from contextvars."""
    ...

def clear_contextvars() -> None:
    """Clear all contextvars bound to structlog."""
    ...

def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """Return a configured structlog BoundLogger instance."""
    ...
```

#### Processor Pipeline Execution Order
1. `structlog.contextvars.merge_contextvars` (extracts `request_id`, `user_id`, etc.)
2. `structlog.stdlib.filter_by_level`
3. `structlog.stdlib.add_logger_name`
4. `structlog.stdlib.add_log_level`
5. `structlog.processors.TimeStamper(fmt="iso", utc=True)`
6. `structlog.processors.StackInfoRenderer()`
7. `structlog.processors.format_exc_info`
8. `structlog.processors.UnicodeDecoder()`
9. Output Renderer:
   - If `log_format == "json"`: `structlog.processors.JSONRenderer()`
   - Else: `structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())`

---

### 3.2 `backend/core/middleware.py`

#### Module Scope
ASGI HTTP middleware for request tracing, execution duration calculation, context isolation, and uniform response header decoration.

#### Exact Interfaces & Signatures
```python
import time
import uuid
from typing import Callable, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from backend.core.logging import bind_contextvars, clear_contextvars, get_logger

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, logger_name: str = "orca.access") -> None:
        super().__init__(app)
        self.logger = get_logger(logger_name)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint
    ) -> Response:
        """
        Intercept request, assign/propagate X-Request-ID, profile duration, emit structured access log.
        """
        ...
```

#### Behavior & Contract
1. **Request ID Resolution:**
   - Check `request.headers.get("X-Request-ID")`.
   - If valid string present, reuse. Otherwise generate `str(uuid.uuid4())`.
2. **Context Binding:**
   - Call `bind_contextvars(request_id=request_id)`.
3. **Execution Profiling:**
   - `start_time = time.perf_counter()`
   - `response = await call_next(request)`
   - `duration_ms = round((time.perf_counter() - start_time) * 1000, 2)`
4. **Header Injection:**
   - `response.headers["X-Request-ID"] = request_id`
5. **Access Log Emission (`orca.access`):**
   - Payload:
     ```json
     {
       "event": "http_request",
       "request_id": "c62a937a-4ec6-4db6-bc7e-3ec1b73e5bf7",
       "method": "GET",
       "path": "/api/pfz/today",
       "status_code": 200,
       "duration_ms": 14.82,
       "client_host": "127.0.0.1",
       "user_agent": "Mozilla/5.0..."
     }
     ```
6. **Cleanup:**
   - In `finally:` block, invoke `clear_contextvars()`.

---

### 3.3 `backend/main.py` Modifications

#### Diff Strategy
1. **Imports:**
   ```python
   from backend.core.logging import setup_logging, get_logger
   from backend.core.middleware import RequestLoggingMiddleware
   ```
2. **Logger Initialization:**
   Replace:
   ```python
   logger = logging.getLogger("orca.api")
   ```
   With:
   ```python
   logger = get_logger("orca.api")
   ```
3. **Lifespan Startup:**
   ```python
   @asynccontextmanager
   async def lifespan(app: FastAPI):
       setup_logging()
       logger.info("Initializing ORCA Marine Intelligence API...")
       ...
   ```
4. **Middleware Stack:**
   Add immediately before or after CORS middleware:
   ```python
   app.add_middleware(RequestLoggingMiddleware)
   ```

---

### 3.4 `frontend/lib/logger.ts`

#### Module Scope
Isomorphic structured logger for Next.js (App Router / React Client & Server components). Wraps browser console and server output with timestamp, level, context, and request tracing helpers.

#### Exact Interfaces & Signatures
```typescript
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogContext {
  [key: string]: unknown;
}

export interface LogEntry {
  timestamp: string;
  level: LogLevel;
  message: string;
  context?: LogContext;
  requestId?: string;
  error?: {
    name: string;
    message: string;
    stack?: string;
  };
}

export class Logger {
  private context: LogContext = {};

  constructor(private namespace: string = 'orca.frontend') {}

  public setContext(context: LogContext): void;
  public debug(message: string, context?: LogContext): void;
  public info(message: string, context?: LogContext): void;
  public warn(message: string, context?: LogContext): void;
  public error(message: string, error?: Error | unknown, context?: LogContext): void;
}

export const logger: Logger;

/**
 * Injects or propagates x-request-id into standard Fetch RequestInit headers.
 */
export function injectRequestId(
  headers?: HeadersInit,
  customRequestId?: string
): Record<string, string>;

/**
 * Wrapper around standard fetch that automatically attaches x-request-id and logs failures.
 */
export function fetchWithRequestId(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response>;
```

---

### 3.5 `tests/test_logging.py`

#### Test Coverage Requirements
1. **`test_setup_logging_json_output`**: Configure json format; emit log; verify JSON parsable with `event`, `level`, `timestamp`, `logger`.
2. **`test_setup_logging_console_output`**: Configure console format; verify output formatting.
3. **`test_contextvars_propagation`**: Bind `request_id="test-123"`; verify bound fields appear in subsequent log outputs; verify `clear_contextvars` clears them.
4. **`test_middleware_generates_request_id`**: Issue `client.get("/health")`; verify response contains `X-Request-ID` conforming to UUIDv4.
5. **`test_middleware_preserves_incoming_request_id`**: Send `headers={"X-Request-ID": "custom-uuid"}`; verify response returns identical `custom-uuid`.
6. **`test_middleware_emits_structured_access_log`**: Intercept log stream during request; verify access log contains `method`, `path`, `status_code`, `duration_ms`, `request_id`.
7. **`test_log_level_filtering`**: Set `log_level="WARNING"`; verify `DEBUG` and `INFO` records are suppressed while `WARNING` and `ERROR` records pass.

---

## 4. Implementation Validation Gates & Checkpoints

### Stage 1: Architectural Alignment & Dependencies
- [ ] `backend/pyproject.toml` contains `structlog>=24.4.0`
- [ ] Dependencies lock clean via `uv sync` / `pip install -e .`

### Stage 2: TDD / Red Phase
- [ ] Create `tests/test_logging.py` with 7 test cases
- [ ] Execute `pytest tests/test_logging.py` -> All 7 tests fail (ImportError/AssertionError)

### Stage 3: Green Phase Implementation
- [ ] Create `backend/core/__init__.py`
- [ ] Implement `backend/core/logging.py`
- [ ] Implement `backend/core/middleware.py`
- [ ] Modify `backend/main.py`
- [ ] Create `frontend/lib/logger.ts`
- [ ] Re-run `pytest tests/test_logging.py` -> 7/7 tests GREEN

### Stage 4: Regression & System Integration
- [ ] Run full test suite: `pytest tests/` -> 100% green
- [ ] Verify `X-Request-ID` on all core endpoints (`/health`, `/api/chat`, `/api/pfz/today`, etc.)
- [ ] Typecheck verification: `mypy backend/` (or equivalent) passes cleanly
