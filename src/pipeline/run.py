"""Openclaw-friendly CLI entry for full event->fund pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from src.pipeline.tasks import (
    aggregate_reports,
    extract_events_from_docs,
    load_example_documents,
    map_events_to_funds,
    parse_documents,
    render_markdown,
)
from src.utils.cache import save_json


ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for pipeline execution."""
    p = argparse.ArgumentParser(description="Run fund-event-engine pipeline")
    p.add_argument("--window-days", type=int, default=7, choices=[3, 7, 14, 30], help="Freshness gating window")
    p.add_argument("--fund", action="append", default=[], help="Target fund code, repeatable")
    p.add_argument("--examples-dir", default=str(ROOT / "examples"), help="Input examples directory")
    p.add_argument("--events-out", default=str(ROOT / "data" / "events" / "pipeline_events.json"))
    p.add_argument("--signals-out", default=str(ROOT / "data" / "snapshots" / "pipeline_signals.json"))
    p.add_argument("--reports-out", default=str(ROOT / "data" / "snapshots" / "pipeline_reports.json"))
    p.add_argument("--markdown-out", default=str(ROOT / "reports" / "pipeline_report.md"))
    return p.parse_args()


def main() -> None:
    """Execute full pipeline and emit stable JSON + markdown artifacts."""
    args = parse_args()

    raw_docs = load_example_documents(Path(args.examples_dir))
    parsed_docs = parse_documents(raw_docs)
    events = extract_events_from_docs(parsed_docs, window_days=args.window_days)
    signals = map_events_to_funds(events, fund_codes=args.fund, window_days=args.window_days)
    reports = aggregate_reports(signals, window_days=args.window_days)

    save_json(Path(args.events_out), [x.to_dict() for x in events])
    save_json(Path(args.signals_out), [x.to_dict() for x in signals])
    save_json(Path(args.reports_out), [x.to_dict() for x in reports])

    md = render_markdown(reports)
    Path(args.markdown_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.markdown_out).write_text(md, encoding="utf-8")

    payload = {
        "analysis_window": f"{args.window_days}d",
        "events_output": str(Path(args.events_out)),
        "signals_output": str(Path(args.signals_out)),
        "reports_output": str(Path(args.reports_out)),
        "markdown_output": str(Path(args.markdown_out)),
        "event_count": len(events),
        "signal_count": len(signals),
        "report_count": len(reports),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
