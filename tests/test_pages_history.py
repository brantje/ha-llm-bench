"""Tests for merging history from GitHub Pages."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import ha_test.pages_history as pages_history
import ha_test.reporting as reporting


def test_merge_published_history_downloads_missing_runs(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    history_dir = reports_dir / "history"
    history_dir.mkdir(parents=True)
    monkeypatch.setattr(reporting, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(reporting, "HISTORY_DIR", history_dir)
    monkeypatch.setattr(reporting, "HISTORY_INDEX", history_dir / "index.json")

    remote_report = {
        "run_id": "2026-05-20T10:31:20.872740+00:00",
        "started_at": "2026-05-20T10:31:20.872740+00:00",
        "models": {"m": {"tests_total": 1}},
        "summary": {"overall_pass_rate": 1.0},
    }
    remote_index = [
        {
            "run_id": remote_report["run_id"],
            "path": "history/2026-05-20T10-31-20-872740_00-00/report.json",
        }
    ]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, timeout=30):
            response = MagicMock()
            response.status_code = 200
            if url.endswith("history/index.json"):
                response.json.return_value = remote_index
            else:
                response.json.return_value = remote_report
            return response

    monkeypatch.setattr(pages_history.httpx, "Client", FakeClient)

    added = pages_history.merge_published_history(
        reports_dir,
        pages_url="https://example.github.io/ha-llm-bench/",
    )
    assert added == 1
    archived = history_dir / "2026-05-20T10-31-20-872740_00-00" / "report.json"
    assert archived.exists()
    index = json.loads((history_dir / "index.json").read_text())
    assert index[0]["run_id"] == remote_report["run_id"]
