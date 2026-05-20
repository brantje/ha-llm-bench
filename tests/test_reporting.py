"""Unit tests for reporting token allocation."""

from __future__ import annotations

import ha_test.reporting as reporting


def test_records_with_usage_allocated_distributes_by_latency():
    records = [
        reporting.TestRecord(
            nodeid="a",
            model="m",
            outcome="passed",
            latency_ms=1000.0,
        ),
        reporting.TestRecord(
            nodeid="b",
            model="m",
            outcome="passed",
            latency_ms=3000.0,
        ),
    ]
    usage = {
        "prompt_tokens": 900.0,
        "completion_tokens": 100.0,
        "total_tokens": 1000.0,
    }

    allocated = reporting.records_with_usage_allocated(records, usage)
    assert allocated[0].total_tokens == 250.0
    assert allocated[1].total_tokens == 750.0
    assert allocated[0].prompt_tokens == 225.0
    assert allocated[1].completion_tokens == 75.0


def test_records_with_usage_allocated_keeps_existing_tokens():
    records = [
        reporting.TestRecord(
            nodeid="a",
            model="m",
            outcome="passed",
            latency_ms=1000.0,
            total_tokens=42.0,
            prompt_tokens=38.0,
            completion_tokens=4.0,
        )
    ]
    allocated = reporting.records_with_usage_allocated(
        records,
        {"prompt_tokens": 900.0, "completion_tokens": 100.0, "total_tokens": 1000.0},
    )
    assert allocated[0].total_tokens == 42.0
