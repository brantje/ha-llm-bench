"""Benchmark report generation."""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ha_test.openrouter import aggregate_activity_for_models, get_activity

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


@dataclass
class TestRecord:
    nodeid: str
    model: str
    outcome: str
    latency_ms: float
    command: str | None = None
    entity_id: str | None = None
    failure_reason: str | None = None
    response_speech: str | None = None
    response_type: str | None = None
    actual_state: str | None = None
    changed_entities: list[str] | None = None
    clarification: bool = False
    hallucination: bool = False
    incorrect_entity_targeting: bool = False


@dataclass
class RunMetrics:
    run_id: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    ha_version: str = os.environ.get("HA_VERSION", "2026.5")
    records: list[TestRecord] = field(default_factory=list)

    def add_record(self, record: TestRecord) -> None:
        self.records.append(record)


RUN_METRICS = RunMetrics()


def record_test_result(
    *,
    nodeid: str,
    model: str,
    outcome: str,
    latency_ms: float,
    command: str | None = None,
    entity_id: str | None = None,
    failure_reason: str | None = None,
    response_speech: str | None = None,
    response_type: str | None = None,
    actual_state: str | None = None,
    changed_entities: list[str] | None = None,
    clarification: bool = False,
    hallucination: bool = False,
    incorrect_entity_targeting: bool = False,
) -> None:
    RUN_METRICS.add_record(
        TestRecord(
            nodeid=nodeid,
            model=model,
            outcome=outcome,
            latency_ms=latency_ms,
            command=command,
            entity_id=entity_id,
            failure_reason=failure_reason,
            response_speech=response_speech,
            response_type=response_type,
            actual_state=actual_state,
            changed_entities=changed_entities,
            clarification=clarification,
            hallucination=hallucination,
            incorrect_entity_targeting=incorrect_entity_targeting,
        )
    )


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[index]


def build_model_report(
    model: str,
    records: list[TestRecord],
    activity_totals: dict[str, dict[str, float]],
) -> dict[str, Any]:
    latencies = [record.latency_ms for record in records]
    passed = sum(1 for record in records if record.outcome == "passed")
    failed = len(records) - passed
    activity = activity_totals.get(model, {})
    total_latency_seconds = sum(latencies) / 1000 if latencies else 0.0
    completion_tokens = activity.get("completion_tokens", 0.0)
    avg_tokens_per_second = (
        completion_tokens / total_latency_seconds if total_latency_seconds > 0 else 0.0
    )
    return {
        "tests_total": len(records),
        "tests_passed": passed,
        "tests_failed": failed,
        "latency_ms": {
            "avg": statistics.mean(latencies) if latencies else 0.0,
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
        },
        "cost_usd": activity.get("cost_usd") if activity else None,
        "total_tokens": activity.get("total_tokens") if activity else None,
        "prompt_tokens": activity.get("prompt_tokens") if activity else None,
        "completion_tokens": activity.get("completion_tokens") if activity else None,
        "avg_tokens_per_second": round(avg_tokens_per_second, 4),
        "hallucination_count": sum(1 for record in records if record.hallucination),
        "clarification_count": sum(1 for record in records if record.clarification),
        "incorrect_entity_targeting": sum(
            1 for record in records if record.incorrect_entity_targeting
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Home Assistant Conversational Benchmark",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- HA Version: `{report['ha_version']}`",
        f"- Models tested: {report['summary']['models_tested']}",
        f"- Overall pass rate: {report['summary']['overall_pass_rate']:.2%}",
        "",
        "## Model Results",
        "",
    ]
    for model, stats in report["models"].items():
        lines.extend(
            [
                f"### `{model}`",
                "",
                f"- Passed: {stats['tests_passed']}/{stats['tests_total']}",
                f"- Avg latency: {stats['latency_ms']['avg']:.0f} ms",
                f"- Cost (USD): {stats['cost_usd']}",
                f"- Avg tokens/sec: {stats['avg_tokens_per_second']}",
                f"- Hallucinations: {stats['hallucination_count']}",
                f"- Clarifications: {stats['clarification_count']}",
                "",
            ]
        )

    failures = [record for record in report["records"] if record.get("outcome") == "failed"]
    if failures:
        lines.extend(["## Failures", ""])
        for record in failures:
            lines.extend(
                [
                    f"### `{record['nodeid']}` ({record['model']})",
                    "",
                    f"- Command: `{record.get('command')}`",
                    f"- Reason: {record.get('failure_reason')}",
                ]
            )
            if record.get("entity_id"):
                lines.append(f"- Entity: `{record['entity_id']}`")
            if record.get("response_type"):
                lines.append(f"- Response type: `{record['response_type']}`")
            if record.get("response_speech"):
                lines.append(f"- Assistant said: {record['response_speech']}")
            if record.get("actual_state"):
                lines.append(f"- Actual state: `{record['actual_state']}`")
            if record.get("changed_entities"):
                lines.append(f"- Changed entities: `{record['changed_entities']}`")
            lines.append("")

    if report["summary"].get("activity_warning"):
        lines.extend(["## Notes", "", report["summary"]["activity_warning"], ""])
    return "\n".join(lines)


def finalize_report(run_metrics: RunMetrics) -> dict[str, Any]:
    run_metrics.finished_at = datetime.now(UTC).isoformat()
    models = sorted({record.model for record in run_metrics.records})
    activity_warning = None
    activity_totals: dict[str, dict[str, float]] = {}
    if os.environ.get("OPENROUTER_MANAGEMENT_KEY"):
        date = run_metrics.started_at[:10]
        activity = get_activity(date)
        activity_totals = aggregate_activity_for_models(activity, set(models))
    else:
        activity_warning = (
            "OPENROUTER_MANAGEMENT_KEY not set; cost and token totals are unavailable."
        )

    model_reports = {
        model: build_model_report(
            model,
            [record for record in run_metrics.records if record.model == model],
            activity_totals,
        )
        for model in models
    }
    total_tests = len(run_metrics.records)
    passed_tests = sum(1 for record in run_metrics.records if record.outcome == "passed")
    total_cost = sum(
        (stats["cost_usd"] or 0.0)
        for stats in model_reports.values()
        if stats["cost_usd"] is not None
    )
    report = {
        "run_id": run_metrics.run_id,
        "started_at": run_metrics.started_at,
        "finished_at": run_metrics.finished_at,
        "ha_version": run_metrics.ha_version,
        "models": model_reports,
        "summary": {
            "models_tested": len(models),
            "overall_pass_rate": (passed_tests / total_tests) if total_tests else 0.0,
            "total_cost_usd": total_cost,
            "activity_warning": activity_warning,
        },
        "records": [asdict(record) for record in run_metrics.records],
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "report.json").write_text(json.dumps(report, indent=2))
    (REPORTS_DIR / "report.md").write_text(render_markdown(report))
    return report
