"""Run demo pipeline with fixed demo output paths."""

from __future__ import annotations

from pathlib import Path

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


def run() -> None:
    """Execute demo scenario with default 7-day freshness gating."""
    window_days = 7
    raw_docs = load_example_documents(ROOT / "examples")
    parsed_docs = parse_documents(raw_docs)
    events = extract_events_from_docs(parsed_docs, window_days=window_days)
    signals = map_events_to_funds(events, window_days=window_days)
    reports = aggregate_reports(signals, window_days=window_days)

    save_json(ROOT / "data" / "events" / "demo_events.json", [x.to_dict() for x in events])
    save_json(ROOT / "data" / "snapshots" / "demo_signals.json", [x.to_dict() for x in signals])
    save_json(ROOT / "data" / "snapshots" / "demo_snapshot.json", [x.to_dict() for x in reports])
    (ROOT / "reports").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports" / "demo_output.md").write_text(render_markdown(reports), encoding="utf-8")


if __name__ == "__main__":
    run()
