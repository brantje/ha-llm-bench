"""Tests for benchmark history loading."""

from __future__ import annotations

import json

import ha_test.reporting as reporting
from ha_test.history import print_history_list
from ha_test.test_plan import load_historical_tokens_per_test


def test_load_history_index_and_reports(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    history_dir = reports_dir / "history"
    history_dir.mkdir(parents=True)
    monkeypatch.setattr(reporting, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(reporting, "HISTORY_DIR", history_dir)
    monkeypatch.setattr(reporting, "HISTORY_INDEX", history_dir / "index.json")

    older = {
        "run_id": "run-older",
        "started_at": "2026-05-19T10:00:00+00:00",
        "models": {"m": {"tests_total": 2, "total_tokens": 800.0}},
    }
    newer = {
        "run_id": "run-newer",
        "started_at": "2026-05-20T10:00:00+00:00",
        "models": {"m": {"tests_total": 2, "total_tokens": 1200.0}},
    }
    (history_dir / "run-older").mkdir()
    (history_dir / "run-newer").mkdir()
    (history_dir / "run-older" / "report.json").write_text(json.dumps(older))
    (history_dir / "run-newer" / "report.json").write_text(json.dumps(newer))
    (history_dir / "index.json").write_text(
        json.dumps(
            [
                {
                    "run_id": "run-newer",
                    "path": "history/run-newer/report.json",
                    "summary": {},
                },
                {
                    "run_id": "run-older",
                    "path": "history/run-older/report.json",
                    "summary": {},
                },
            ]
        )
    )

    index = reporting.load_history_index()
    assert len(index) == 2
    reports = reporting.load_historical_reports()
    assert [r["run_id"] for r in reports] == ["run-newer", "run-older"]
    assert reporting.load_history_report("run-older")["run_id"] == "run-older"


def test_load_historical_tokens_uses_history(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    history_dir = reports_dir / "history"
    history_dir.mkdir(parents=True)
    monkeypatch.setattr(reporting, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(reporting, "HISTORY_DIR", history_dir)
    monkeypatch.setattr(reporting, "HISTORY_INDEX", history_dir / "index.json")
    monkeypatch.setattr("ha_test.test_plan.REPORTS_DIR", reports_dir)
    monkeypatch.setattr("ha_test.test_plan.PROJECT_ROOT", tmp_path)

    report = {
        "run_id": "run-a",
        "models": {"model-a": {"tests_total": 2, "total_tokens": 1000.0}},
    }
    (history_dir / "run-a").mkdir()
    (history_dir / "run-a" / "report.json").write_text(json.dumps(report))
    (history_dir / "index.json").write_text(
        json.dumps([{"run_id": "run-a", "path": "history/run-a/report.json"}])
    )

    tokens = load_historical_tokens_per_test()
    assert tokens is not None
    assert tokens["total_tokens"] == 500.0
    assert tokens["source"] == "reports/history (1 runs)"


def test_print_history_list_empty(tmp_path, monkeypatch, capsys):
    reports_dir = tmp_path / "reports"
    history_dir = reports_dir / "history"
    history_dir.mkdir(parents=True)
    monkeypatch.setattr(reporting, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(reporting, "HISTORY_DIR", history_dir)
    monkeypatch.setattr(reporting, "HISTORY_INDEX", history_dir / "index.json")

    assert print_history_list() == 0
    assert "No archived runs" in capsys.readouterr().out
