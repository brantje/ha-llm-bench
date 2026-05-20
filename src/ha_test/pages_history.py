"""Merge benchmark history from a live GitHub Pages deployment into local reports."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from ha_test.reporting import (
    HISTORY_MAX_ENTRIES,
    REPORTS_DIR,
    _sanitize_run_id,
    prune_history_index,
)


def pages_base_url() -> str | None:
    explicit = os.environ.get("GITHUB_PAGES_URL", "").strip()
    if explicit:
        return explicit if explicit.endswith("/") else f"{explicit}/"
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repository or "/" not in repository:
        return None
    owner, name = repository.split("/", 1)
    return f"https://{owner}.github.io/{name}/"


def fetch_json(client: httpx.Client, url: str) -> Any | None:
    try:
        response = client.get(url, timeout=30)
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        return None


def merge_published_history(
    reports_dir: Path | None = None,
    *,
    pages_url: str | None = None,
) -> int:
    """
    Download prior reports/history from GitHub Pages and merge into reports_dir.

    Returns the number of archived runs added.
    """
    base = pages_url or pages_base_url()
    if not base:
        return 0

    reports_dir = reports_dir or REPORTS_DIR
    history_dir = reports_dir / "history"
    history_index = history_dir / "index.json"
    history_dir.mkdir(parents=True, exist_ok=True)

    added = 0
    with httpx.Client(follow_redirects=True) as client:
        remote_index = fetch_json(client, urljoin(base, "reports/history/index.json"))
        if not isinstance(remote_index, list):
            return 0

        local_index = []
        if history_index.exists():
            try:
                local_index = json.loads(history_index.read_text())
            except json.JSONDecodeError:
                local_index = []
        if not isinstance(local_index, list):
            local_index = []

        local_run_ids = {
            entry.get("run_id")
            for entry in local_index
            if isinstance(entry, dict) and entry.get("run_id")
        }

        for entry in remote_index:
            if not isinstance(entry, dict):
                continue
            run_id = entry.get("run_id")
            if not run_id or run_id in local_run_ids:
                continue

            rel_path = entry.get("path") or f"history/{_sanitize_run_id(run_id)}/report.json"
            report_url = urljoin(base, f"reports/{rel_path.lstrip('/')}")
            report = fetch_json(client, report_url)
            if not isinstance(report, dict):
                continue

            folder_name = _sanitize_run_id(run_id)
            run_dir = history_dir / folder_name
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "report.json").write_text(json.dumps(report, indent=2))

            local_entry = {
                "run_id": run_id,
                "started_at": report.get("started_at") or entry.get("started_at"),
                "finished_at": report.get("finished_at") or entry.get("finished_at"),
                "ha_version": report.get("ha_version") or entry.get("ha_version"),
                "summary": report.get("summary") or entry.get("summary") or {},
                "path": f"history/{folder_name}/report.json",
            }
            local_index = [item for item in local_index if item.get("run_id") != run_id]
            local_index.insert(0, local_entry)
            local_run_ids.add(run_id)
            added += 1

    if added:
        local_index = prune_history_index(local_index)
        local_index = local_index[:HISTORY_MAX_ENTRIES]
        history_index.write_text(json.dumps(local_index, indent=2))

    return added
