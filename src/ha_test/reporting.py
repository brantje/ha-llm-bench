"""Benchmark report generation."""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ha_test.openrouter import (
    env_value,
    estimate_tokens_from_activity_history,
    get_activity_totals_for_models,
    get_model_pricing_lookup,
)

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"
HISTORY_DIR = REPORTS_DIR / "history"
HISTORY_INDEX = HISTORY_DIR / "index.json"
HISTORY_MAX_ENTRIES = 20


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
    cost_usd: float | None = None
    prompt_tokens: float | None = None
    completion_tokens: float | None = None
    total_tokens: float | None = None


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
    cost_usd: float | None = None,
    prompt_tokens: float | None = None,
    completion_tokens: float | None = None,
    total_tokens: float | None = None,
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
            cost_usd=cost_usd,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )
    write_results_json()


def remove_test_records(*, nodeid: str, model: str) -> None:
    """Drop all recorded results for a test/model pair (e.g. before a retry)."""
    before = len(RUN_METRICS.records)
    RUN_METRICS.records = [
        record
        for record in RUN_METRICS.records
        if not (record.nodeid == nodeid and record.model == model)
    ]
    if len(RUN_METRICS.records) != before:
        write_results_json()


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[index]


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    if remaining_seconds < 0.05:
        return f"{minutes}m"
    return f"{minutes}m {remaining_seconds:.0f}s"


def tokens_per_second(completion_tokens: float | None, latency_ms: float) -> float | None:
    if completion_tokens is None or latency_ms <= 0:
        return None
    return round(completion_tokens / (latency_ms / 1000), 4)


def test_record_to_dict(record: TestRecord) -> dict[str, Any]:
    data = asdict(record)
    data.pop("model", None)
    data["tokens_per_second"] = tokens_per_second(record.completion_tokens, record.latency_ms)
    return data


def records_with_usage_allocated(
    records: list[TestRecord],
    usage: dict[str, float | None],
) -> list[TestRecord]:
    total_tokens = usage.get("total_tokens")
    if not total_tokens:
        return records
    if all(record.total_tokens is not None for record in records):
        return records

    missing = [record for record in records if record.total_tokens is None]
    if not missing:
        return records

    prompt_total = float(usage.get("prompt_tokens") or 0.0)
    completion_total = float(usage.get("completion_tokens") or 0.0)
    latency_total = sum(record.latency_ms for record in missing) or float(len(missing))

    allocated: list[TestRecord] = []
    for record in records:
        if record.total_tokens is not None:
            allocated.append(record)
            continue
        share = record.latency_ms / latency_total if latency_total else 1 / len(missing)
        allocated.append(
            replace(
                record,
                prompt_tokens=prompt_total * share,
                completion_tokens=completion_total * share,
                total_tokens=float(total_tokens) * share,
            )
        )
    return allocated


def resolve_model_usage(
    model: str,
    records: list[TestRecord],
    activity_totals: dict[str, dict[str, float]],
) -> dict[str, float | None]:
    session_cost = sum(record.cost_usd or 0.0 for record in records)
    session_prompt = sum(record.prompt_tokens or 0.0 for record in records)
    session_completion = sum(record.completion_tokens or 0.0 for record in records)
    session_total = sum(record.total_tokens or 0.0 for record in records)
    has_session_cost = any(record.cost_usd is not None for record in records)
    has_session_tokens = any(record.total_tokens is not None for record in records)

    activity = activity_totals.get(model, {})
    if has_session_cost and session_cost > 0:
        cost_usd = session_cost
    elif activity:
        cost_usd = activity.get("cost_usd", 0.0)
    elif has_session_cost:
        cost_usd = session_cost
    else:
        cost_usd = None

    if has_session_tokens and session_total > 0:
        prompt_tokens = session_prompt
        completion_tokens = session_completion
        total_tokens = session_total
    elif activity and (activity.get("total_tokens") or 0) > 0:
        prompt_tokens = activity.get("prompt_tokens", 0.0)
        completion_tokens = activity.get("completion_tokens", 0.0)
        total_tokens = activity.get("total_tokens", 0.0)
    elif activity:
        estimated = estimate_tokens_from_activity_history(activity, len(records))
        prompt_tokens = estimated["prompt_tokens"]
        completion_tokens = estimated["completion_tokens"]
        total_tokens = estimated["total_tokens"]
    else:
        prompt_tokens = None
        completion_tokens = None
        total_tokens = None

    return {
        "cost_usd": cost_usd,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def build_model_report(
    model: str,
    records: list[TestRecord],
    activity_totals: dict[str, dict[str, float]],
    pricing_lookup: dict[str, dict[str, str]],
) -> dict[str, Any]:
    latencies = [record.latency_ms for record in records]
    passed = sum(1 for record in records if record.outcome == "passed")
    failed = len(records) - passed
    usage = resolve_model_usage(model, records, activity_totals)
    display_records = records_with_usage_allocated(records, usage)
    total_test_time_ms = sum(latencies)
    total_test_time_seconds = total_test_time_ms / 1000 if total_test_time_ms else 0.0
    completion_tokens = float(usage["completion_tokens"] or 0.0)
    avg_tokens_per_second = (
        completion_tokens / total_test_time_seconds if total_test_time_seconds > 0 else 0.0
    )
    return {
        "pricing": pricing_lookup.get(model, {}),
        "tests_total": len(records),
        "tests_passed": passed,
        "tests_failed": failed,
        "total_test_time_ms": total_test_time_ms,
        "total_test_time_seconds": round(total_test_time_seconds, 3),
        "latency_ms": {
            "avg": statistics.mean(latencies) if latencies else 0.0,
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
        },
        "cost_usd": usage["cost_usd"],
        "total_tokens": usage["total_tokens"],
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "avg_tokens_per_second": round(avg_tokens_per_second, 4),
        "hallucination_count": sum(1 for record in records if record.hallucination),
        "clarification_count": sum(1 for record in records if record.clarification),
        "incorrect_entity_targeting": sum(
            1 for record in records if record.incorrect_entity_targeting
        ),
        "tests": [test_record_to_dict(record) for record in display_records],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Home Assistant Conversational Benchmark",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- HA Version: `{report['ha_version']}`",
        f"- Models tested: {summary['models_tested']}",
        f"- Overall pass rate: {summary['overall_pass_rate']:.2%}",
        f"- Total test time: {format_duration(summary['total_test_time_seconds'])}",
        f"- Total run time: {format_duration(summary['total_run_time_seconds'])}",
        f"- Avg tokens/sec: {summary.get('avg_tokens_per_second')}",
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
                f"- Total test time: {format_duration(stats['total_test_time_seconds'])}",
                f"- Avg latency: {stats['latency_ms']['avg']:.0f} ms",
                f"- Cost (USD): {stats['cost_usd']}",
                f"- Avg tokens/sec: {stats['avg_tokens_per_second']}",
                f"- Hallucinations: {stats['hallucination_count']}",
                f"- Clarifications: {stats['clarification_count']}",
                "",
            ]
        )

    failures = [
        (model, test)
        for model, stats in report["models"].items()
        for test in stats.get("tests", [])
        if test.get("outcome") == "failed"
    ]
    if failures:
        lines.extend(["## Failures", ""])
        for model, test in failures:
            lines.extend(
                [
                    f"### `{test['nodeid']}` ({model})",
                    "",
                    f"- Command: `{test.get('command')}`",
                    f"- Reason: {test.get('failure_reason')}",
                ]
            )
            if test.get("entity_id"):
                lines.append(f"- Entity: `{test['entity_id']}`")
            if test.get("response_type"):
                lines.append(f"- Response type: `{test['response_type']}`")
            if test.get("response_speech"):
                lines.append(f"- Assistant said: {test['response_speech']}")
            if test.get("actual_state"):
                lines.append(f"- Actual state: `{test['actual_state']}`")
            if test.get("changed_entities"):
                lines.append(f"- Changed entities: `{test['changed_entities']}`")
            lines.append("")

    if report["summary"].get("activity_warning"):
        lines.extend(["## Notes", "", report["summary"]["activity_warning"], ""])
    return "\n".join(lines)


def build_report(
    run_metrics: RunMetrics,
    *,
    activity_totals: dict[str, dict[str, float]] | None = None,
    activity_warning: str | None = None,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    models = sorted({record.model for record in run_metrics.records})
    pricing_lookup = get_model_pricing_lookup()
    model_reports = {
        model: build_model_report(
            model,
            [record for record in run_metrics.records if record.model == model],
            activity_totals or {},
            pricing_lookup,
        )
        for model in models
    }
    total_tests = len(run_metrics.records)
    passed_tests = sum(1 for record in run_metrics.records if record.outcome == "passed")
    total_test_time_ms = sum(record.latency_ms for record in run_metrics.records)
    total_test_time_seconds = total_test_time_ms / 1000 if total_test_time_ms else 0.0
    started_at = datetime.fromisoformat(run_metrics.started_at)
    finished_at = end_time or (
        datetime.fromisoformat(run_metrics.finished_at) if run_metrics.finished_at else None
    )
    total_run_time_seconds = (
        (finished_at - started_at).total_seconds() if finished_at else 0.0
    )
    total_cost = sum(
        (stats["cost_usd"] or 0.0)
        for stats in model_reports.values()
        if stats["cost_usd"] is not None
    )
    total_completion_tokens = sum(
        float(stats["completion_tokens"] or 0.0)
        for stats in model_reports.values()
        if stats["completion_tokens"] is not None
    )
    avg_tokens_per_second = (
        total_completion_tokens / total_test_time_seconds if total_test_time_seconds > 0 else 0.0
    )
    return {
        "run_id": run_metrics.run_id,
        "started_at": run_metrics.started_at,
        "finished_at": finished_at.isoformat() if finished_at else None,
        "ha_version": run_metrics.ha_version,
        "models": model_reports,
        "summary": {
            "models_tested": len(models),
            "overall_pass_rate": (passed_tests / total_tests) if total_tests else 0.0,
            "total_test_time_ms": total_test_time_ms,
            "total_test_time_seconds": round(total_test_time_seconds, 3),
            "total_run_time_seconds": round(total_run_time_seconds, 3),
            "total_cost_usd": total_cost,
            "avg_tokens_per_second": round(avg_tokens_per_second, 4),
            "activity_warning": activity_warning,
        },
    }


def fetch_activity_totals(run_metrics: RunMetrics) -> tuple[dict[str, dict[str, float]], str | None]:
    models = sorted({record.model for record in run_metrics.records})
    if env_value("OPENROUTER_MANAGEMENT_KEY"):
        return get_activity_totals_for_models(set(models)), None
    return {}, (
        "OPENROUTER_MANAGEMENT_KEY not set; cost and token totals use session estimates only."
    )


def write_results_json(run_metrics: RunMetrics | None = None) -> None:
    metrics = run_metrics or RUN_METRICS
    if not metrics.records:
        return
    activity_totals, activity_warning = fetch_activity_totals(metrics)
    report = build_report(
        metrics,
        activity_totals=activity_totals,
        activity_warning=activity_warning,
        end_time=datetime.now(UTC),
    )
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "results.json").write_text(json.dumps(report, indent=2))


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "-").replace(".", "-").replace("+", "_")


def prune_history_index(index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop index entries whose report.json is missing on disk."""
    pruned: list[dict[str, Any]] = []
    for entry in index:
        if load_report_json(history_report_path(entry)):
            pruned.append(entry)
    return pruned


def load_history_index(*, prune: bool = True) -> list[dict[str, Any]]:
    """Return archived run manifest entries (newest first)."""
    if not HISTORY_INDEX.exists():
        return []
    try:
        index = json.loads(HISTORY_INDEX.read_text())
    except json.JSONDecodeError:
        return []
    if not isinstance(index, list):
        return []
    if prune:
        pruned = prune_history_index(index)
        if len(pruned) != len(index):
            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            HISTORY_INDEX.write_text(json.dumps(pruned, indent=2))
        return pruned
    return index


def history_report_path(entry: dict[str, Any]) -> Path:
    """Resolve on-disk path for a history index entry."""
    rel = entry.get("path")
    if isinstance(rel, str) and rel:
        return REPORTS_DIR / rel
    run_id = entry.get("run_id")
    if not run_id:
        return HISTORY_DIR / "unknown" / "report.json"
    return HISTORY_DIR / _sanitize_run_id(run_id) / "report.json"


def load_report_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def load_historical_reports(*, max_runs: int | None = None) -> list[dict[str, Any]]:
    """Load archived reports (newest first), then current report/results if not duplicates."""
    limit = max_runs if max_runs is not None else HISTORY_MAX_ENTRIES
    reports: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()

    for entry in load_history_index():
        run_id = entry.get("run_id")
        if not run_id or run_id in seen_run_ids:
            continue
        report = load_report_json(history_report_path(entry))
        if not report:
            continue
        reports.append(report)
        seen_run_ids.add(run_id)
        if len(reports) >= limit:
            return reports

    for path in (REPORTS_DIR / "results.json", REPORTS_DIR / "report.json"):
        report = load_report_json(path)
        if not report:
            continue
        run_id = report.get("run_id")
        if run_id and run_id in seen_run_ids:
            continue
        reports.append(report)
        if run_id:
            seen_run_ids.add(run_id)

    return reports


def load_history_report(run_id: str) -> dict[str, Any] | None:
    """Load a single archived report by run_id."""
    for entry in load_history_index():
        if entry.get("run_id") == run_id:
            return load_report_json(history_report_path(entry))
    folder = HISTORY_DIR / _sanitize_run_id(run_id) / "report.json"
    return load_report_json(folder)


def format_history_summary(entry: dict[str, Any]) -> str:
    """One-line summary for CLI / bootstrap output."""
    summary = entry.get("summary") or {}
    rate = summary.get("overall_pass_rate")
    rate_label = f"{rate:.1%}" if rate is not None else "n/a"
    started = (entry.get("started_at") or entry.get("run_id") or "")[:19]
    cost = summary.get("total_cost_usd")
    cost_label = f"${cost:.4f}" if cost is not None else "n/a"
    return f"{started}  pass {rate_label}  cost {cost_label}  ({entry.get('run_id', '')})"


def archive_report_to_history(report: dict[str, Any]) -> None:
    """Copy finalized report into reports/history and update index.json."""
    run_id = report.get("run_id")
    if not run_id:
        return

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    folder_name = _sanitize_run_id(run_id)
    run_dir = HISTORY_DIR / folder_name
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2))

    relative_path = f"history/{folder_name}/report.json"
    entry = {
        "run_id": run_id,
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "ha_version": report.get("ha_version"),
        "summary": report.get("summary", {}),
        "path": relative_path,
    }

    index: list[dict[str, Any]] = []
    if HISTORY_INDEX.exists():
        try:
            index = json.loads(HISTORY_INDEX.read_text())
        except json.JSONDecodeError:
            index = []
    if not isinstance(index, list):
        index = []

    index = [item for item in index if item.get("run_id") != run_id]
    index.insert(0, entry)
    index = index[:HISTORY_MAX_ENTRIES]
    HISTORY_INDEX.write_text(json.dumps(index, indent=2))


def finalize_report(run_metrics: RunMetrics) -> dict[str, Any]:
    run_metrics.finished_at = datetime.now(UTC).isoformat()
    activity_totals, activity_warning = fetch_activity_totals(run_metrics)

    report = build_report(
        run_metrics,
        activity_totals=activity_totals,
        activity_warning=activity_warning,
        end_time=datetime.fromisoformat(run_metrics.finished_at),
    )
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "report.json").write_text(json.dumps(report, indent=2))
    (REPORTS_DIR / "report.md").write_text(render_markdown(report))
    archive_report_to_history(report)
    write_results_json(run_metrics)
    return report
