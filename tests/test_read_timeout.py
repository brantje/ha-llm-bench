"""Tests for ReadTimeout detection and reporting cleanup."""

from __future__ import annotations

import httpx
import pytest

from ha_test.read_timeout import failed_with_read_timeout, is_read_timeout
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


def test_failed_with_read_timeout_from_excinfo():
    class FakeExcInfo:
        value = httpx.ReadTimeout("timed out")

    class FakeReport:
        failed = True
        excinfo = FakeExcInfo()
        longrepr = ""

    assert failed_with_read_timeout(FakeReport())


def test_remove_test_records_clears_matching_entries():
    RUN_METRICS.records.clear()
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
