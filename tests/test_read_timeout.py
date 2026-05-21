"""Tests for ReadTimeout detection and reporting cleanup."""

from __future__ import annotations

import httpx
import pytest

from ha_test.read_timeout import (
    failed_with_read_timeout,
    failed_with_timeout,
    is_read_timeout,
    is_state_wait_timeout,
    is_test_timeout,
    is_timeout_message,
)
from ha_test.reporting import RUN_METRICS, record_test_result, remove_test_records


def test_is_read_timeout_detects_direct_exception():
    assert is_read_timeout(httpx.ReadTimeout("timed out"))


def test_is_read_timeout_detects_wrapped_exception():
    try:
        raise httpx.ReadTimeout("timed out")
    except httpx.ReadTimeout as exc:
        wrapper = AssertionError("conversation failed")
        wrapper.__cause__ = exc
    assert is_read_timeout(wrapper)


def test_is_read_timeout_false_for_other_errors():
    assert not is_read_timeout(TimeoutError("state wait"))
    assert not is_read_timeout(None)


def test_is_state_wait_timeout_detects_entity_wait():
    exc = TimeoutError("Timed out waiting for climate.living_room. Last state: {}")
    assert is_state_wait_timeout(exc)


def test_is_state_wait_timeout_detects_wrapped_exception():
    try:
        raise TimeoutError("Timed out waiting for light.lamp_x. Last state: {}")
    except TimeoutError as exc:
        wrapper = AssertionError("entity check failed")
        wrapper.__cause__ = exc
    assert is_state_wait_timeout(wrapper)


def test_is_state_wait_timeout_false_for_other_timeouts():
    assert not is_state_wait_timeout(TimeoutError("Config entry did not load"))
    assert not is_state_wait_timeout(None)


def test_is_test_timeout_covers_read_and_state_wait():
    assert is_test_timeout(httpx.ReadTimeout("timed out"))
    assert is_test_timeout(
        TimeoutError("Timed out waiting for climate.living_room. Last state: {}")
    )


def test_is_timeout_message():
    assert is_timeout_message("climate.living_room: Timed out waiting for climate.living_room")
    assert is_timeout_message("httpx.ReadTimeout: timed out")
    assert not is_timeout_message("Expected light on, got off")


def test_failed_with_timeout_from_excinfo():
    class FakeExcInfo:
        value = TimeoutError("Timed out waiting for climate.living_room. Last state: {}")

    class FakeReport:
        failed = True
        excinfo = FakeExcInfo()
        longrepr = ""

    assert failed_with_timeout(FakeReport())


def test_failed_with_read_timeout_from_excinfo():
    class FakeExcInfo:
        value = httpx.ReadTimeout("timed out")

    class FakeReport:
        failed = True
        excinfo = FakeExcInfo()
        longrepr = ""

    assert failed_with_read_timeout(FakeReport())


@pytest.fixture
def isolated_run_metrics(monkeypatch):
    """Keep unit tests from mutating session-wide benchmark metrics."""
    saved = list(RUN_METRICS.records)
    RUN_METRICS.records.clear()
    monkeypatch.setattr("ha_test.reporting.write_results_json", lambda *args, **kwargs: None)
    yield
    RUN_METRICS.records[:] = saved


def test_remove_test_records_clears_matching_entries(isolated_run_metrics):
    record_test_result(
        nodeid="tests/test_lights.py::test_lights[a-turn_on]",
        model="model-a",
        outcome="failed",
        latency_ms=1.0,
    )
    record_test_result(
        nodeid="tests/test_lights.py::test_lights[a-turn_on]",
        model="model-b",
        outcome="passed",
        latency_ms=2.0,
    )

    remove_test_records(
        nodeid="tests/test_lights.py::test_lights[a-turn_on]",
        model="model-a",
    )

    assert len(RUN_METRICS.records) == 1
    assert RUN_METRICS.records[0].model == "model-b"
