"""Zep SDK-compatible errors for the local memory backend.

The local backend raises the ``zep_cloud`` SDK's own exception classes so that
existing handling keeps working unchanged: ``except NotFoundError``,
``is_retryable_zep_error`` (status-code based), ``graph.py::_zep_status``
(which checks for the ``zep_cloud`` module prefix) and the sanitizers that
match the SDK's ``headers: ..., status_code: N, body: ...`` string form.

Messages passed to these helpers must never contain source text, prompts or
LLM output.
"""

from __future__ import annotations

import functools
import sqlite3
from typing import Any, Callable, TypeVar

from zep_cloud.core.api_error import ApiError
from zep_cloud.errors import BadRequestError, ConflictError, NotFoundError
from zep_cloud.types import ApiError as ApiErrorBody

__all__ = [
    "ApiError",
    "ApiErrorBody",
    "BadRequestError",
    "ConflictError",
    "NotFoundError",
    "STORE_BUSY_MESSAGE",
    "bad_request",
    "conflict",
    "is_busy_sqlite_error",
    "map_sqlite_error",
    "not_found",
    "store_busy",
    "translate_sqlite_errors",
    "unsupported",
]

F = TypeVar("F", bound=Callable[..., Any])

STORE_BUSY_MESSAGE = "local memory store is busy"
STORE_BUSY_RETRY_AFTER_SECONDS = "1"

# Substrings of sqlite3.OperationalError messages that mean "try again later".
_BUSY_MARKERS = ("locked", "busy", "disk i/o")


def not_found(message: str) -> NotFoundError:
    """404 for a missing graph, node, edge, episode or batch."""

    return NotFoundError(body=ApiErrorBody(message=message))


def bad_request(message: str) -> BadRequestError:
    """400 for an invalid argument or an unsupported feature (never retried)."""

    return BadRequestError(body=ApiErrorBody(message=message))


def conflict(message: str) -> ConflictError:
    """409 for a duplicate graph id or an operation in the wrong batch state."""

    return ConflictError(body=ApiErrorBody(message=message))


def unsupported(name: str) -> BadRequestError:
    """400 for SDK namespaces or features the local backend does not implement."""

    return bad_request(f"{name} is not supported by the local memory backend")


def store_busy(message: str = STORE_BUSY_MESSAGE) -> ApiError:
    """503 with ``Retry-After: 1``: retryable by ``call_zep_read_with_retry``."""

    return ApiError(
        status_code=503,
        headers={"Retry-After": STORE_BUSY_RETRY_AFTER_SECONDS},
        body={"message": message},
    )


def is_busy_sqlite_error(error: BaseException) -> bool:
    """True for SQLite lock contention or I/O errors worth retrying later."""

    if not isinstance(error, sqlite3.OperationalError):
        return False
    text = str(error).lower()
    return any(marker in text for marker in _BUSY_MARKERS)


def map_sqlite_error(error: BaseException) -> BaseException:
    """Return the 503 ``ApiError`` for busy/locked/I/O errors, else ``error`` itself."""

    if is_busy_sqlite_error(error):
        return store_busy()
    return error


def translate_sqlite_errors(func: F) -> F:
    """Decorator: re-raise busy/locked SQLite errors as the SDK's 503 ``ApiError``.

    Every other exception, including programming errors, propagates unchanged.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as error:
            mapped = map_sqlite_error(error)
            if mapped is error:
                raise
            raise mapped from error

    return wrapper  # type: ignore[return-value]
