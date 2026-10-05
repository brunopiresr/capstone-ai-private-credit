"""Opt-in console logging and timed progress for application operations."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Any


def configure_logging(level: int | str = logging.INFO) -> None:
    """Show package logs, including in notebooks; repeated calls do not add handlers."""
    logger = logging.getLogger("credit_monitoring")
    handler = next((h for h in logger.handlers if h.name == "credit_monitoring_console"), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler.set_name("credit_monitoring_console")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
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
