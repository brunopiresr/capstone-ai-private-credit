"""Opt-in console logging and timed progress for application operations."""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from time import perf_counter
from typing import Any

_context: ContextVar[dict[str, Any]] = ContextVar("credit_monitoring_log_context", default={})
_CONTEXT_FIELDS = (
    "assessment_run_id",
    "borrower_id",
    "period_end",
    "information_cutoff",
    "covenant_id",
    "agreement_id",
    "document_id",
    "source_file",
    "source_row",
    "metric",
    "comparison_period_end",
    "trend",
)


def _snapshot(value: Any) -> Any:
    """Copy explicitly projected fields; never implicitly serialize domain objects."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _snapshot(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_snapshot(item) for item in value]
    return value


class StructuredConsoleFormatter(logging.Formatter):
    """Render record attributes without changing records consumed by other handlers."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if not hasattr(record, "operation"):
            return message
        fields = {
            name: getattr(record, name)
            for name in (*_CONTEXT_FIELDS, "inputs", "outputs", "error_type", "elapsed_s")
            if hasattr(record, name)
        }
        return f"{message} {json.dumps(fields, ensure_ascii=False)}"


@contextmanager
def logging_context(**fields: Any) -> Iterator[None]:
    """Inherit identifiers within a call, restoring them on success or failure.

    Context variables isolate threads and asyncio tasks. Worker threads created
    manually must receive context explicitly (asyncio.to_thread copies it).
    """
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def log_event(
    logger: logging.Logger,
    operation: str,
    *,
    inputs: dict | None = None,
    outputs: dict | None = None,
    status: str = "complete",
    **fields: Any,
) -> None:
    """Emit local INFO records reusable by any standard logging handler."""
    if not logger.isEnabledFor(logging.INFO):
        return
    logger.info(
        "%s %s",
        operation,
        status,
        extra=_snapshot(
            {
                **_context.get(),
                **fields,
                "operation": operation,
                "status": status,
                "inputs": inputs or {},
                "outputs": outputs or {},
            }
        ),
    )


def configure_logging(level: int | str = logging.INFO) -> None:
    """Show package logs, including in notebooks; repeated calls do not add handlers."""
    logger = logging.getLogger("credit_monitoring")
    handler = next((h for h in logger.handlers if h.name == "credit_monitoring_console"), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler.set_name("credit_monitoring_console")
        handler.setFormatter(
            StructuredConsoleFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    handler.setLevel(level)
    logger.setLevel(level)
    logger.propagate = False


@contextmanager
def log_step(logger: logging.Logger, action: str, **context: Any) -> Iterator[None]:
    """Emit before blocking work and report its duration or failure without source text."""
    details = " ".join(f"{key}={value}" for key, value in context.items())
    started = perf_counter()
    logger.info("%s started %s", action, details)
    try:
        yield
    except Exception as exc:
        logger.error(
            "%s failed %s elapsed_s=%.2f error_type=%s",
            action,
            details,
            perf_counter() - started,
            type(exc).__name__,
        )
        raise
    else:
        logger.info("%s complete %s elapsed_s=%.2f", action, details, perf_counter() - started)
