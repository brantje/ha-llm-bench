"""Detect httpx/httpcore read timeouts for test retries."""

from __future__ import annotations

import os
from typing import Any

import httpx

try:
    import httpcore
except ImportError:  # pragma: no cover
    httpcore = None  # type: ignore[assignment]

READ_TIMEOUT_MAX_RETRIES = int(os.environ.get("HA_READ_TIMEOUT_MAX_RETRIES", "1"))
STATE_WAIT_TIMEOUT_PREFIX = "Timed out waiting for"


def is_read_timeout(exc: BaseException | None) -> bool:
    """Return True if exc or its cause/context chain is a read timeout."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, httpx.ReadTimeout):
            return True
        if httpcore is not None and isinstance(exc, httpcore.ReadTimeout):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def is_state_wait_timeout(exc: BaseException | None) -> bool:
    """Return True if exc or its cause/context chain is a state wait timeout."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, TimeoutError) and STATE_WAIT_TIMEOUT_PREFIX in str(exc):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def is_timeout_message(message: str) -> bool:
    return STATE_WAIT_TIMEOUT_PREFIX in message or "ReadTimeout" in message


def is_test_timeout(exc: BaseException | None) -> bool:
    """Return True for HA/API read timeouts and entity state wait timeouts."""
    return is_read_timeout(exc) or is_state_wait_timeout(exc)


def failed_with_read_timeout(report: Any) -> bool:
    if not getattr(report, "failed", False):
        return False
    if getattr(report, "excinfo", None) is not None:
        return is_read_timeout(report.excinfo.value)
    return is_timeout_message(str(getattr(report, "longrepr", "")))


def failed_with_timeout(report: Any) -> bool:
    if not getattr(report, "failed", False):
        return False
    if getattr(report, "excinfo", None) is not None:
        return is_test_timeout(report.excinfo.value)
    return is_timeout_message(str(getattr(report, "longrepr", "")))
