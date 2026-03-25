"""Openclaw-friendly CLI entry for full event->fund pipeline."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from src.pipeline.tasks import (
    aggregate_reports,
    extract_events_from_docs,
    load_example_documents,
    load_source_documents,
    map_events_to_funds,
    parse_documents,
    render_markdown,
    set_runtime_scoring_override,
)
from src.utils.cache import save_json
from src.utils.prediction_history import append_prediction_snapshots
from src.utils.report_quality import enrich_reports_with_quality


ROOT = Path(__file__).resolve().parents[2]


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def _topn(counter: Counter, n: int = 10) -> list[dict]:
    return [{"key": k, "count": v} for k, v in counter.most_common(n)]


def _build_source_mix_meta(signals: list) -> dict:
    """Build source contribution structure for observability and optimization."""
    total_by_tier: Counter = Counter()
    main_by_tier: Counter = Counter()
    total_by_category: Counter = Counter()
    main_by_category: Counter = Counter()
    main_by_source: Counter = Counter()
    for s in signals:
        total_by_tier[s.source_tier] += 1
        total_by_category[s.source_category] += 1
        if s.include_in_main:
            main_by_tier[s.source_tier] += 1
            main_by_category[s.source_category] += 1
            main_by_source[s.source] += 1
    return {
        "total_by_tier": dict(total_by_tier),
        "main_by_tier": dict(main_by_tier),
        "total_by_category": dict(total_by_category),
        "main_by_category": dict(main_by_category),
        "top_main_sources": _topn(main_by_source, n=12),
    }


def _load_source_feedback_override(path: str) -> dict:
    """Load source-performance multipliers as runtime scoring override."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    fb = payload.get("source_feedback", {}) if isinstance(payload, dict) else {}
    if not isinstance(fb, dict):
        return {}
    multipliers = fb.get("source_multipliers", {})
    multipliers_by_ft = fb.get("source_multipliers_by_fund_type", {})
    multipliers_by_hz = fb.get("source_multipliers_by_horizon", {})
    multipliers_by_ft_hz = fb.get("source_multipliers_by_fund_type_horizon", {})
    valid_global = isinstance(multipliers, dict) and bool(multipliers)
    valid_by_ft = isinstance(multipliers_by_ft, dict) and bool(multipliers_by_ft)
    valid_by_hz = isinstance(multipliers_by_hz, dict) and bool(multipliers_by_hz)
    valid_by_ft_hz = isinstance(multipliers_by_ft_hz, dict) and bool(multipliers_by_ft_hz)
    if not any([valid_global, valid_by_ft, valid_by_hz, valid_by_ft_hz]):
        return {}
    payload = {"source_feedback": {}}
    if valid_global:
        payload["source_feedback"]["source_multiplier_by_name"] = multipliers
    if valid_by_ft:
        payload["source_feedback"]["source_multiplier_by_fund_type"] = multipliers_by_ft
    if valid_by_hz:
        payload["source_feedback"]["source_multiplier_by_horizon"] = multipliers_by_hz
    if valid_by_ft_hz:
        payload["source_feedback"]["source_multiplier_by_fund_type_horizon"] = multipliers_by_ft_hz
    return payload


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for pipeline execution."""
    p = argparse.ArgumentParser(description="Run fund-event-engine pipeline")
    p.add_argument("--window-days", type=int, default=7, choices=[3, 7, 14, 30], help="Freshness gating window")
    p.add_argument("--fund", action="append", default=[], help="Target fund code, repeatable")
    p.add_argument("--examples-dir", default=str(ROOT / "examples"), help="Input examples directory")
    p.add_argument(
        "--collect-sources",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Collect from enabled free/public sources (default: true)",
    )
    p.add_argument(
        "--include-examples",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Include local example docs (default: false in formal runs)",
    )
    p.add_argument("--max-sources", type=int, default=20, help="Max enabled sources to collect when --collect-sources")
    p.add_argument("--max-items-per-source", type=int, default=3, help="Max docs per source when --collect-sources")
    p.add_argument("--max-list-links", type=int, default=15, help="Max candidate detail links per source list page")
    p.add_argument("--collect-timeout", type=float, default=10.0, help="HTTP timeout seconds for source collection")
    p.add_argument(
        "--strict-collect",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Fail fast on source collection errors (default: false)",
    )
    p.add_argument(
        "--verbose-collect",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Print source/page collection logs (default: false)",
    )
    p.add_argument("--events-out", default=str(ROOT / "data" / "events" / "pipeline_events.json"))
    p.add_argument("--signals-out", default=str(ROOT / "data" / "snapshots" / "pipeline_signals.json"))
    p.add_argument("--reports-out", default=str(ROOT / "data" / "snapshots" / "pipeline_reports.json"))
    p.add_argument("--markdown-out", default=str(ROOT / "reports" / "pipeline_report.md"))
    p.add_argument("--aggregate-out", default=str(ROOT / "outputs" / "pipeline_aggregate.json"))
    p.add_argument("--mapped-events-out", default=str(ROOT / "outputs" / "pipeline_mapped_events.json"))
    p.add_argument(
        "--scoring-override-json",
        default="",
        help="Inline JSON object to override scoring config for this run only",
    )
    p.add_argument(
        "--scoring-override-file",
        default="",
        help="Path to JSON file that overrides scoring config for this run only",
    )
    p.add_argument(
        "--history-path",
        default=str(ROOT / "outputs" / "history" / "fund_report_history.json"),
        help="History file path used for automated consistency scoring",
    )
    p.add_argument(
        "--prediction-history-path",
        default=str(ROOT / "outputs" / "history" / "fund_prediction_history.json"),
        help="Prediction history path used for realized-outcome evaluation",
    )
    p.add_argument(
        "--source-performance-file",
        default=str(ROOT / "outputs" / "history" / "source_performance.json"),
        help="Source performance feedback file from src.pipeline.evaluate",
    )
    p.add_argument(
        "--source-feedback",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable runtime source-feedback multiplier from evaluation history",
    )
    return p.parse_args()


def main() -> None:
    """Execute full pipeline and emit stable JSON + markdown artifacts."""
    args = parse_args()
    runtime_scoring_override = {}
    source_feedback_multiplier_count = 0
    source_feedback_fund_type_bucket_count = 0
    source_feedback_horizon_bucket_count = 0
    source_feedback_fund_type_horizon_bucket_count = 0
    if args.scoring_override_file:
        runtime_scoring_override = json.loads(Path(args.scoring_override_file).read_text(encoding="utf-8"))
    if args.scoring_override_json:
        inline_override = json.loads(args.scoring_override_json)
        if not isinstance(inline_override, dict):
            raise SystemExit("--scoring-override-json must be a JSON object")
        if not isinstance(runtime_scoring_override, dict):
            runtime_scoring_override = {}
        runtime_scoring_override = _deep_merge(runtime_scoring_override, inline_override)
    if runtime_scoring_override and not isinstance(runtime_scoring_override, dict):
        raise SystemExit("Runtime scoring override must be a JSON object")
    if args.source_feedback:
        fb_override = _load_source_feedback_override(args.source_performance_file)
        if fb_override:
            sf = fb_override.get("source_feedback", {})
            source_feedback_multiplier_count = len(sf.get("source_multiplier_by_name", {}))
            source_feedback_fund_type_bucket_count = len(sf.get("source_multiplier_by_fund_type", {}))
            source_feedback_horizon_bucket_count = len(sf.get("source_multiplier_by_horizon", {}))
            source_feedback_fund_type_horizon_bucket_count = len(sf.get("source_multiplier_by_fund_type_horizon", {}))
            runtime_scoring_override = _deep_merge(runtime_scoring_override, fb_override)
    set_runtime_scoring_override(runtime_scoring_override)

    raw_docs = []
    collect_stats = {}
    if args.include_examples:
        raw_docs.extend(load_example_documents(Path(args.examples_dir)))
    if args.collect_sources:
        source_docs, collect_stats = load_source_documents(
            max_sources=args.max_sources,
            max_items_per_source=args.max_items_per_source,
            max_list_links=args.max_list_links,
            timeout=args.collect_timeout,
            strict_collect=args.strict_collect,
            verbose_collect=args.verbose_collect,
            fund_codes=args.fund,
        )
        raw_docs.extend(source_docs)
    if not raw_docs:
        raise SystemExit("No input documents found. Enable --collect-sources or --include-examples.")
    parsed_docs = parse_documents(raw_docs)
    events = extract_events_from_docs(parsed_docs, window_days=args.window_days)
    signals = map_events_to_funds(events, fund_codes=args.fund, window_days=args.window_days)
    reports = aggregate_reports(signals, window_days=args.window_days, fund_codes=args.fund)
    quality_meta = enrich_reports_with_quality(reports, collect_stats=collect_stats, history_path=args.history_path)
    prediction_meta = append_prediction_snapshots(
        reports,
        analysis_window_days=args.window_days,
        prediction_history_path=args.prediction_history_path,
    )

    save_json(Path(args.events_out), [x.to_dict() for x in events])
    save_json(Path(args.signals_out), [x.to_dict() for x in signals])
    save_json(Path(args.reports_out), [x.to_dict() for x in reports])
    save_json(Path(args.mapped_events_out), [x.to_dict() for x in signals])

    md = render_markdown(reports)
    Path(args.markdown_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.markdown_out).write_text(md, encoding="utf-8")

    stale_count = sum(1 for x in events if x.is_stale)
    noise_count = sum(1 for x in events if x.is_noise or x.is_page_chrome)
    source_mix_meta = _build_source_mix_meta(signals)

    aggregate_payload = {
        "analysis_window": f"{args.window_days}d",
        "event_count": len(events),
        "signal_count": len(signals),
        "report_count": len(reports),
        "raw_doc_count": len(raw_docs),
        "stale_events_filtered": stale_count,
        "noise_events_filtered": noise_count,
        "collect_stats": collect_stats,
        "events_output": str(Path(args.events_out)),
        "signals_output": str(Path(args.signals_out)),
        "reports_output": str(Path(args.reports_out)),
        "markdown_output": str(Path(args.markdown_out)),
        "runtime_scoring_override_applied": bool(runtime_scoring_override),
        "runtime_scoring_override_keys": sorted(runtime_scoring_override.keys()) if runtime_scoring_override else [],
        "source_feedback_enabled": bool(args.source_feedback),
        "source_feedback_multiplier_count": int(source_feedback_multiplier_count),
        "source_feedback_fund_type_bucket_count": int(source_feedback_fund_type_bucket_count),
        "source_feedback_horizon_bucket_count": int(source_feedback_horizon_bucket_count),
        "source_feedback_fund_type_horizon_bucket_count": int(source_feedback_fund_type_horizon_bucket_count),
        "source_feedback_file": args.source_performance_file,
        "quality_meta": quality_meta,
        "prediction_meta": prediction_meta,
        "source_mix_meta": source_mix_meta,
    }
    save_json(Path(args.aggregate_out), aggregate_payload)
    print(json.dumps(aggregate_payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
