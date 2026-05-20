"""Bootstrap test plan preview and cost estimation."""

from __future__ import annotations

import json
import os
import statistics
from pathlib import Path
from typing import Any

import pytest

from ha_test.openrouter import (
    _is_free,
    env_value,
    get_api_key_credit_balance,
    get_models,
    get_target_model_ids,
    usage_settle_seconds,
)
from ha_test.reporting import format_duration

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_PROMPT_TOKENS_PER_TEST = 5000.0
DEFAULT_COMPLETION_TOKENS_PER_TEST = 500.0
COLLECT_PLACEHOLDER_MODEL = "_collect_"


def resolve_target_models(api_key: str | None = None) -> list[dict[str, Any]]:
    model_ids = get_target_model_ids(api_key)
    if not model_ids or model_ids == ["unconfigured"]:
        return []

    lookup: dict[str, dict[str, Any]] = {}
    if api_key or env_value("OPENROUTER_API_KEY"):
        try:
            lookup = {model["id"]: model for model in get_models(api_key=api_key)}
        except RuntimeError:
            lookup = {}

    resolved: list[dict[str, Any]] = []
    for model_id in model_ids:
        catalog = lookup.get(model_id)
        pricing = (catalog or {}).get("pricing") or {}
        resolved.append(
            {
                "id": model_id,
                "name": (catalog or {}).get("name") or model_id,
                "pricing": pricing,
                "is_free": _is_free(catalog) if catalog else False,
                "known": catalog is not None,
            }
        )
    return resolved


class _CollectPlugin:
    def __init__(self) -> None:
        self.items: list[Any] = []

    def pytest_collection_modifyitems(self, items: list[Any]) -> None:
        self.items = items


def count_tests_per_model() -> int:
    tests_dir = PROJECT_ROOT / "tests"
    previous_model = os.environ.get("OPENROUTER_MODEL")
    os.environ["OPENROUTER_MODEL"] = COLLECT_PLACEHOLDER_MODEL
    plugin = _CollectPlugin()
    try:
        pytest.main(
            ["--collect-only", "-q", str(tests_dir)],
            plugins=[plugin],
        )
        return len(plugin.items)
    finally:
        if previous_model is None:
            os.environ.pop("OPENROUTER_MODEL", None)
        else:
            os.environ["OPENROUTER_MODEL"] = previous_model


def _tokens_per_test_from_report(report: dict[str, Any]) -> list[float]:
    per_test: list[float] = []
    for stats in report.get("models", {}).values():
        tests_total = stats.get("tests_total") or 0
        total_tokens = stats.get("total_tokens")
        if tests_total <= 0 or not total_tokens:
            continue
        per_test.append(float(total_tokens) / float(tests_total))
    return per_test


def load_historical_tokens_per_test() -> dict[str, float] | None:
    for path in (REPORTS_DIR / "results.json", REPORTS_DIR / "report.json"):
        if not path.exists():
            continue
        try:
            report = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        per_test = _tokens_per_test_from_report(report)
        if not per_test:
            continue
        total_tokens = statistics.median(per_test)
        return {
            "prompt_tokens": total_tokens * 0.9,
            "completion_tokens": total_tokens * 0.1,
            "total_tokens": total_tokens,
            "source": str(path.relative_to(PROJECT_ROOT)),
        }
    return None


def default_tokens_per_test() -> dict[str, float]:
    total = DEFAULT_PROMPT_TOKENS_PER_TEST + DEFAULT_COMPLETION_TOKENS_PER_TEST
    return {
        "prompt_tokens": DEFAULT_PROMPT_TOKENS_PER_TEST,
        "completion_tokens": DEFAULT_COMPLETION_TOKENS_PER_TEST,
        "total_tokens": total,
        "source": "default",
    }


def resolve_tokens_per_test() -> dict[str, float | str]:
    historical = load_historical_tokens_per_test()
    if historical:
        return historical
    return default_tokens_per_test()


def estimate_model_cost(
    pricing: dict[str, str],
    tokens_per_test: dict[str, float],
    test_count: int,
) -> float | None:
    prompt_rate = float(pricing.get("prompt") or 0)
    completion_rate = float(pricing.get("completion") or 0)
    if prompt_rate <= 0 and completion_rate <= 0:
        return 0.0
    if not pricing:
        return None
    per_test = (
        tokens_per_test["prompt_tokens"] * prompt_rate
        + tokens_per_test["completion_tokens"] * completion_rate
    )
    return per_test * test_count


def build_test_plan(api_key: str | None = None) -> dict[str, Any]:
    models = resolve_target_models(api_key)
    if not models:
        raise RuntimeError("No OpenRouter models matched the configured filters")

    tests_per_model = count_tests_per_model()
    tokens_per_test = resolve_tokens_per_test()
    settle_seconds = usage_settle_seconds()
    credit_balance = get_api_key_credit_balance(api_key)

    model_rows: list[dict[str, Any]] = []
    total_estimated_cost = 0.0
    has_unknown_cost = False
    unknown_models: list[str] = []

    for model in models:
        estimated_cost = None
        if not model["known"]:
            unknown_models.append(model["id"])
            has_unknown_cost = True
        elif model["is_free"]:
            estimated_cost = 0.0
        else:
            estimated_cost = estimate_model_cost(
                model["pricing"],
                tokens_per_test,
                tests_per_model,
            )
            if estimated_cost is None:
                has_unknown_cost = True
            else:
                total_estimated_cost += estimated_cost

        model_rows.append(
            {
                **model,
                "tests_per_model": tests_per_model,
                "estimated_cost_usd": estimated_cost,
            }
        )

    total_invocations = tests_per_model * len(models)
    avg_latency_seconds = 25.0
    if tokens_per_test.get("source") != "default":
        historical_latency = _historical_avg_latency_seconds()
        if historical_latency is not None:
            avg_latency_seconds = historical_latency

    estimated_wall_seconds = total_invocations * (avg_latency_seconds + settle_seconds)

    return {
        "models": model_rows,
        "tests_per_model": tests_per_model,
        "model_count": len(models),
        "total_invocations": total_invocations,
        "tokens_per_test": tokens_per_test,
        "estimated_total_cost_usd": None if has_unknown_cost else total_estimated_cost,
        "estimated_wall_seconds": estimated_wall_seconds,
        "settle_seconds": settle_seconds,
        "unknown_models": unknown_models,
        "credit_balance": credit_balance,
    }


def _historical_avg_latency_seconds() -> float | None:
    for path in (REPORTS_DIR / "results.json", REPORTS_DIR / "report.json"):
        if not path.exists():
            continue
        try:
            report = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        latencies: list[float] = []
        for stats in report.get("models", {}).values():
            avg_ms = (stats.get("latency_ms") or {}).get("avg")
            if avg_ms:
                latencies.append(float(avg_ms) / 1000.0)
        if latencies:
            return statistics.mean(latencies)
    return None


def render_test_plan(plan: dict[str, Any]) -> str:
    lines = [f"Models to test ({plan['model_count']}):"]
    for model in plan["models"]:
        if model["estimated_cost_usd"] is None:
            cost_label = "pricing unknown"
        elif model["is_free"]:
            cost_label = "free"
        else:
            cost_label = f"paid, ~${model['estimated_cost_usd']:.4f} / {plan['tests_per_model']} tests"
        lines.append(f"  - {model['id']}  ({cost_label})")

    lines.extend(
        [
            "",
            (
                f"Test matrix: {plan['tests_per_model']} tests x {plan['model_count']} models "
                f"= {plan['total_invocations']} LLM calls"
            ),
        ]
    )

    tokens = plan["tokens_per_test"]
    if plan["estimated_total_cost_usd"] is not None:
        lines.append(
            f"Estimated cost: ~${plan['estimated_total_cost_usd']:.4f} USD "
            f"(based on median {tokens['total_tokens']:.0f} tokens/test "
            f"from {tokens['source']})"
        )
    else:
        lines.append(
            f"Estimated cost: unavailable for some models "
            f"(token basis: {tokens['total_tokens']:.0f} tokens/test from {tokens['source']})"
        )

    lines.append(
        "Estimated wall time: "
        f"{format_duration(plan['estimated_wall_seconds'])} "
        f"(includes OPENROUTER_USAGE_SETTLE_SECONDS={plan['settle_seconds']:.0f})"
    )

    remaining = plan["credit_balance"].get("remaining")
    if remaining is not None:
        lines.append(f"OpenRouter credit remaining: ${remaining:.4f} USD")

    if plan["unknown_models"]:
        lines.append(
            "Warning: unknown model IDs (not in OpenRouter catalog): "
            + ", ".join(plan["unknown_models"])
        )

    return "\n".join(lines)


def print_test_plan(api_key: str | None = None) -> dict[str, Any]:
    plan = build_test_plan(api_key)
    print(render_test_plan(plan))
    return plan
