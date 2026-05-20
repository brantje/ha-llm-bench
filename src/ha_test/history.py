"""CLI and helpers for benchmark run history."""

from __future__ import annotations

import argparse
import json
import sys

from ha_test.reporting import (
    HISTORY_INDEX,
    REPORTS_DIR,
    format_history_summary,
    load_history_index,
    load_history_report,
    load_historical_reports,
)


def print_history_list(*, limit: int = 10) -> int:
    index = load_history_index()
    if not index:
        print(f"No archived runs in {HISTORY_INDEX}")
        return 0

    print(f"Archived benchmark runs ({len(index)} total, showing up to {limit}):")
    for entry in index[:limit]:
        print(f"  - {format_history_summary(entry)}")
    print("")
    print("Open the results viewer:")
    print("  python3 -m http.server 8080")
    print("  http://localhost:8080/docs/")
    return 0


def print_history_show(run_id: str) -> int:
    report = load_history_report(run_id)
    if not report:
        print(f"No archived report found for run_id: {run_id}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List or show archived benchmark runs")
    sub = parser.add_subparsers(dest="command")

    list_parser = sub.add_parser("list", help="List archived runs")
    list_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        help="Maximum entries to print (default: 10)",
    )

    show_parser = sub.add_parser("show", help="Print archived report JSON for a run")
    show_parser.add_argument("run_id", help="run_id from index.json")

    args = parser.parse_args(argv)
    if args.command == "show":
        return print_history_show(args.run_id)
    if args.command == "list" or args.command is None:
        return print_history_list(limit=getattr(args, "limit", 10))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
