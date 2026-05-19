"""OpenRouter rate limit detection and header-based retry delays."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

import httpx

T = TypeVar("T")

DEFAULT_MAX_RETRIES = int(os.environ.get("OPENROUTER_RATE_LIMIT_MAX_RETRIES", "8"))
DEFAULT_BUFFER_SECONDS = float(os.environ.get("OPENROUTER_RATE_LIMIT_BUFFER_SECONDS", "1.0"))
DEFAULT_FALLBACK_DELAY = float(os.environ.get("OPENROUTER_RATE_LIMIT_FALLBACK_SECONDS", "30"))


def _header_value(headers: Mapping[str, str], *names: str) -> str | None:
    normalized = {key.lower(): value for key, value in headers.items()}
    for name in names:
        value = normalized.get(name.lower())
        if value is not None:
            return value
    return None


def retry_delay_from_headers(
    headers: Mapping[str, str],
    *,
    now: float | None = None,
) -> float | None:
    """Return seconds to wait before retrying, based on OpenRouter/HTTP headers."""
    now = now or time.time()

    retry_after = _header_value(headers, "Retry-After", "retry-after")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass

    reset_raw = _header_value(headers, "X-RateLimit-Reset", "x-ratelimit-reset")
    if reset_raw:
        try:
            reset_value = float(reset_raw)
            if reset_value > 1_000_000_000_000:
                reset_epoch = reset_value / 1000.0
            elif reset_value > 1_000_000_000:
                reset_epoch = reset_value
            else:
                reset_epoch = now + reset_value
            return max(0.0, reset_epoch - now)
        except ValueError:
            return None

    return None


def is_rate_limit_status(status_code: int | None) -> bool:
    return status_code == 429


def is_rate_limit_message(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    return "rate limit" in lowered or "too many requests" in lowered


def is_rate_limit_error(
    *,
    status_code: int | None = None,
    message: str | None = None,
) -> bool:
    return is_rate_limit_status(status_code) or is_rate_limit_message(message)


def wait_for_rate_limit_reset(
    headers: Mapping[str, str],
    *,
    buffer_seconds: float | None = None,
    fallback_seconds: float | None = None,
) -> float:
    """Sleep until the rate limit window resets. Returns total seconds slept."""
    buffer = DEFAULT_BUFFER_SECONDS if buffer_seconds is None else buffer_seconds
    fallback = DEFAULT_FALLBACK_DELAY if fallback_seconds is None else fallback_seconds
    delay = retry_delay_from_headers(headers)
    if delay is None:
        delay = fallback
    sleep_for = max(0.0, delay + buffer)
    if sleep_for > 0:
        time.sleep(sleep_for)
    return sleep_for


def request_with_rate_limit_retry(
    request_fn: Callable[[], httpx.Response],
    *,
    max_retries: int | None = None,
) -> httpx.Response:
    """Retry an httpx request when OpenRouter returns 429, honoring response headers."""
    retries = DEFAULT_MAX_RETRIES if max_retries is None else max_retries
    last_response: httpx.Response | None = None

    for attempt in range(retries):
        response = request_fn()
        last_response = response
        if not is_rate_limit_status(response.status_code):
            return response
        if attempt + 1 >= retries:
            break
        wait_for_rate_limit_reset(response.headers)

    assert last_response is not None
    return last_response


def probe_retry_delay(api_key: str) -> float:
    """Probe OpenRouter and return recommended wait time from rate limit headers."""
    response = httpx.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    if is_rate_limit_status(response.status_code):
        return retry_delay_from_headers(response.headers) or DEFAULT_FALLBACK_DELAY

    remaining = _header_value(response.headers, "X-RateLimit-Remaining", "x-ratelimit-remaining")
    if remaining == "0":
        return retry_delay_from_headers(response.headers) or DEFAULT_FALLBACK_DELAY

    return 0.0


def wait_for_openrouter_rate_limit(api_key: str | None) -> float:
    """Wait for OpenRouter rate limit reset using a live header probe."""
    if not api_key:
        time.sleep(DEFAULT_FALLBACK_DELAY)
        return DEFAULT_FALLBACK_DELAY

    delay = probe_retry_delay(api_key)
    if delay <= 0:
        return 0.0

    sleep_for = max(0.0, delay + DEFAULT_BUFFER_SECONDS)
    time.sleep(sleep_for)
    return sleep_for


def conversation_error_is_rate_limited(
    *,
    response_type: str | None,
    speech: str | None,
    response_body: dict[str, Any] | None = None,
) -> bool:
    if is_rate_limit_message(speech):
        return True

    if response_body:
        serialized = str(response_body).lower()
        if "rate limit" in serialized or "'code': 429" in serialized or '"code": 429' in serialized:
            return True

    return False


def should_retry_after_conversation_error(
    *,
    response_type: str | None,
    speech: str | None,
    response_body: dict[str, Any] | None = None,
    api_key: str | None = None,
) -> bool:
    if conversation_error_is_rate_limited(
        response_type=response_type,
        speech=speech,
        response_body=response_body,
    ):
        return True

    if response_type != "error":
        return False

    if speech and "error talking to api" in speech.lower():
        return probe_retry_delay(api_key or "") > 0 if api_key else False

    return False
