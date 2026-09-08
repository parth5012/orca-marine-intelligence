"""
Structured Logging Infrastructure for ORCA Marine Intelligence (US-LOG-001)

Provides:
- structlog setup with JSON and Console format support
- Contextvars binding (request_id, session_id, tenant, etc.)
- Standard library logging bridge (ProcessorFormatter)
- get_logger helper returning BoundLogger
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any, Dict, Optional, cast

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer
from structlog.typing import EventDict, Processor

_SENSITIVE_KEY_PATTERN = re.compile(r"(password|passwd|pwd|token|secret|authorization|api[_-]?key|cookie|set-cookie)", re.IGNORECASE)


def _redact_sensitive(_, __, event_dict: EventDict) -> EventDict:
    for key in list(event_dict.keys()):
        if _SENSITIVE_KEY_PATTERN.search(str(key)):
            event_dict[key] = "***REDACTED***"
    return event_dict


def _safe_json_serializer(obj: Any, **kwargs: Any) -> str:
    kwargs.pop("default", None)
    try:
        return json.dumps(obj, default=str, **kwargs)
    except (TypeError, ValueError, RecursionError):
        try:
            seen: set = set()

            def _fallback(o: Any) -> Any:
                if isinstance(o, dict):
                    oid = id(o)
                    if oid in seen:
                        return "[Circular]"
                    seen.add(oid)
                    return {str(k): _fallback(v) for k, v in o.items()}
                if isinstance(o, (list, tuple)):
                    return [_fallback(v) for v in o]
                try:
                    json.dumps(o)
                    return o
                except Exception:
                    return repr(o)

            if isinstance(obj, dict):
                return json.dumps(_fallback(obj))
            return json.dumps(repr(obj))
        except Exception:
            return '"<unserializable>"'

VALID_LOG_LEVELS: Dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def setup_logging(
    log_level: Optional[str] = None,
    log_format: Optional[str] = None,
) -> None:
    """
    Initialize and configure structured logging for the application.

    Args:
        log_level: Optional log level override (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                   Defaults to LOG_LEVEL env var or INFO.
        log_format: Optional log format override ('json' or 'console').
                    Defaults to LOG_FORMAT env var or 'console'.
    """
    level_str = (log_level or os.getenv("LOG_LEVEL", "INFO")).upper().strip()
    numeric_level = VALID_LOG_LEVELS.get(level_str, logging.INFO)

    format_str = (log_format or os.getenv("LOG_FORMAT", "console")).lower().strip()
    is_json = format_str == "json"

    # Shared processors between structlog and standard library logging
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        _redact_sensitive,
    ]

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    # Renderer for final string output (safe serializer guards circular / non-serializable objects)
    renderer: Processor = JSONRenderer(serializer=_safe_json_serializer) if is_json else ConsoleRenderer()

    # Bridge standard library logging via ProcessorFormatter
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Reconfigure root standard library logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    # Ensure third-party framework loggers propagate through structlog formatter
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        fw_logger = logging.getLogger(logger_name)
        fw_logger.handlers = []
        fw_logger.propagate = True


def bind_contextvars(**kwargs: Any) -> None:
    """Bind key-value pairs into the current contextvars."""
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_contextvars(*keys: str) -> None:
    """Remove keys from the current contextvars."""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_contextvars() -> None:
    """Clear all contextvars for the current context."""
    structlog.contextvars.clear_contextvars()


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog BoundLogger instance."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


__all__ = [
    "setup_logging",
    "get_logger",
    "bind_contextvars",
    "unbind_contextvars",
    "clear_contextvars",
    "JSONRenderer",
    "ConsoleRenderer",
]
