"""Explicit process-wide monitoring setup and quiet application span helpers."""

import logging
import os
from contextlib import nullcontext
from threading import Lock
from typing import Any

import logfire

_configured = False
_capture_content = False
_configuration_lock = Lock()


def _parse_capture_content(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError("LOGFIRE_CAPTURE_CONTENT must be 'true' or 'false'.")
    return normalized == "true"


def capture_content_enabled() -> bool:
    """Return the central content policy, disabled until explicit configuration."""
    return _capture_content


def is_observability_configured() -> bool:
    return _configured


def configure_observability() -> None:
    """Configure once after environment loading, leaving SDK settings to Logfire."""
    global _configured, _capture_content
    with _configuration_lock:
        if _configured:
            return
        capture_content = _parse_capture_content(os.getenv("LOGFIRE_CAPTURE_CONTENT", "false"))
        logfire.configure(
            send_to_logfire=None if "LOGFIRE_SEND_TO_LOGFIRE" in os.environ else "if-token-present",
            service_name=os.getenv("LOGFIRE_SERVICE_NAME", "credit-monitoring"),
            console=False,
        )
        logfire.instrument_pydantic_ai(
            include_content=capture_content,
            include_binary_content=False,
        )
        # Imported here so configuration and logging helpers remain acyclic.
        from credit_monitoring.observability.logging import _update_logger_threshold

        logger = logging.getLogger("credit_monitoring")
        if not any(handler.name == "credit_monitoring_logfire" for handler in logger.handlers):
            handler = logfire.LogfireLoggingHandler(
                level=logging.DEBUG, fallback=logging.NullHandler()
            )
            handler.set_name("credit_monitoring_logfire")
            logger.addHandler(handler)
        _update_logger_threshold(logger)
        _capture_content = capture_content
        _configured = True


def span(name: str, **attributes: Any):
    """Avoid SDK warnings and tracing for uninitialized library consumers."""
    if not _configured:
        return nullcontext()
    return logfire.span(name, **attributes)
