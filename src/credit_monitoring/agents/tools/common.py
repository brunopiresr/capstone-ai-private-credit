"""Strict argument types and expected service-error conversion for function tools."""

import asyncio
import json
import sqlite3
from collections.abc import Awaitable, Callable, Iterable
from functools import wraps
from typing import Annotated, Any

import requests
from pydantic import Field, StrictStr

from credit_monitoring.covenants.extraction import ExtractionError

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
ISODate = Annotated[StrictStr, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class InvalidToolArguments(ValueError):
    pass


def tool_result(data: Any, *, sources: Iterable[dict[str, str]] = ()) -> str:
    return json.dumps({"ok": True, "data": data, "sources": list(sources)}, ensure_ascii=False)


def service_errors[**P](function: Callable[P, str]) -> Callable[P, Awaitable[str]]:
    """Keep recoverable service errors as tool data; unexpected exceptions propagate."""

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        except (
            OSError,
            ValueError,
            sqlite3.Error,
            requests.RequestException,
            ExtractionError,
        ) as exc:
            code = "invalid_arguments" if isinstance(exc, InvalidToolArguments) else "service_error"
            return json.dumps({"ok": False, "error": code, "message": str(exc)})

    return wrapped
