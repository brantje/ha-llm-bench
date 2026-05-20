"""Tests for report history archiving."""

from __future__ import annotations

import json

import ha_test.reporting as reporting


def test_archive_report_to_history_writes_index_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(reporting, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(reporting, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(reporting, "HISTORY_INDEX", tmp_path / "history" / "index.json")

    report = {
        "run_id": "2026-05-20T12:00:00+00:00",
        "started_at": "2026-05-20T12:00:00+00:00",
        "finished_at": "2026-05-20T12:30:00+00:00",
        "ha_version": "2026.5",
        "summary": {"overall_pass_rate": 1.0},
        "models": {},
    }
    reporting.archive_report_to_history(report)

    index = json.loads((tmp_path / "history" / "index.json").read_text())
    assert len(index) == 1
    assert index[0]["run_id"] == report["run_id"]
    assert index[0]["path"] == "history/2026-05-20T12-00-00_00-00/report.json"

    archived = tmp_path / "history" / "2026-05-20T12-00-00_00-00" / "report.json"
    assert archived.exists()
    assert json.loads(archived.read_text())["run_id"] == report["run_id"]
