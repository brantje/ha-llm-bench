"""Unit tests for test plan preview and model parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ha_test.reporting as reporting
from ha_test.openrouter import get_target_model_ids, parse_csv_ids
from ha_test.test_plan import (
    _tokens_per_test_from_report,
    build_test_plan,
    default_tokens_per_test,
    estimate_model_cost,
    load_historical_tokens_per_test,
    render_test_plan,
    resolve_target_models,
)


def test_parse_csv_ids_splits_and_strips():
    assert parse_csv_ids(
        "deepseek/deepseek-v4-flash, anthropic/claude-sonnet-4.6,,stepfun/step-3.5-flash"
    ) == [
        "deepseek/deepseek-v4-flash",
        "anthropic/claude-sonnet-4.6",
        "stepfun/step-3.5-flash",
    ]


def test_get_target_model_ids_uses_csv(monkeypatch):
    monkeypatch.setenv(
        "OPENROUTER_MODEL",
        "model-a,model-b",
    )
    assert get_target_model_ids() == ["model-a", "model-b"]


def test_estimate_model_cost_for_paid_model():
    pricing = {"prompt": "0.000001", "completion": "0.000002"}
    tokens = default_tokens_per_test()
    cost = estimate_model_cost(pricing, tokens, test_count=13)
    assert cost == pytest.approx(0.078)


def test_estimate_model_cost_for_free_model():
    pricing = {"prompt": "0", "completion": "0"}
    tokens = default_tokens_per_test()
    assert estimate_model_cost(pricing, tokens, test_count=13) == 0.0


def test_tokens_per_test_from_report():
    report = {
        "models": {
            "a": {"tests_total": 2, "total_tokens": 1000.0},
            "b": {"tests_total": 4, "total_tokens": 2000.0},
        }
    }
    assert _tokens_per_test_from_report(report) == [500.0, 500.0]


def test_load_historical_tokens_per_test(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report = {
        "models": {
            "model-a": {"tests_total": 2, "total_tokens": 1100.0},
            "model-b": {"tests_total": 2, "total_tokens": 900.0},
        }
    }
    (reports_dir / "results.json").write_text(json.dumps(report))
    monkeypatch.setattr(reporting, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(reporting, "HISTORY_DIR", reports_dir / "history")
    monkeypatch.setattr(reporting, "HISTORY_INDEX", reports_dir / "history" / "index.json")
    monkeypatch.setattr("ha_test.test_plan.REPORTS_DIR", reports_dir)
    monkeypatch.setattr("ha_test.test_plan.PROJECT_ROOT", tmp_path)

    tokens = load_historical_tokens_per_test()
    assert tokens is not None
    assert tokens["total_tokens"] == 500.0
    assert tokens["prompt_tokens"] == 450.0
    assert tokens["completion_tokens"] == 50.0
    assert tokens["source"] == "reports/results.json"


def test_resolve_target_models_marks_unknown(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "known/model,unknown/model")
    monkeypatch.setattr(
        "ha_test.test_plan.get_models",
        lambda api_key=None: [{"id": "known/model", "name": "Known", "pricing": {"prompt": "0", "completion": "0"}}],
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    models = resolve_target_models("test-key")
    assert len(models) == 2
    assert models[0]["known"] is True
    assert models[0]["is_free"] is True
    assert models[1]["known"] is False


def test_build_test_plan_summary(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "paid/model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        "ha_test.test_plan.resolve_target_models",
        lambda api_key=None: [
            {
                "id": "paid/model",
                "name": "Paid",
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                "is_free": False,
                "known": True,
            }
        ],
    )
    monkeypatch.setattr("ha_test.test_plan.count_tests_per_model", lambda: 13)
    monkeypatch.setattr("ha_test.test_plan.resolve_tokens_per_test", default_tokens_per_test)
    monkeypatch.setattr(
        "ha_test.test_plan.get_api_key_credit_balance",
        lambda api_key=None: {"total_credits": 10.0, "total_usage": 1.0, "remaining": 9.0},
    )

    plan = build_test_plan("test-key")
    assert plan["tests_per_model"] == 13
    assert plan["total_invocations"] == 13
    assert plan["estimated_total_cost_usd"] == pytest.approx(0.078)

    rendered = render_test_plan(plan)
    assert "Models to test (1):" in rendered
    assert "paid/model" in rendered
    assert "Estimated cost:" in rendered
    assert "OpenRouter credit remaining: $9.0000 USD" in rendered
