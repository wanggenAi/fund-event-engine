"""Automated report-quality scoring and historical consistency checks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src.pipeline.contracts import FundReport
from src.utils.cache import save_json


ROOT = Path(__file__).resolve().parents[2]


def compute_source_stability_score(collect_stats: Dict[str, Any]) -> float:
    """Compute 0..1 source-collection stability score from run stats."""
    src_att = int(collect_stats.get("sources_attempted", 0))
    src_ok = int(collect_stats.get("sources_succeeded", 0))
    page_att = int(collect_stats.get("pages_attempted", 0))
    page_ok = int(collect_stats.get("pages_succeeded", 0))
    src_ratio = (src_ok / src_att) if src_att > 0 else 0.5
    page_ratio = (page_ok / page_att) if page_att > 0 else 0.5
    score = 0.6 * src_ratio + 0.4 * page_ratio
    return round(max(0.0, min(1.0, score)), 4)


def _direction_distance(a: str, b: str) -> float:
    if a == b:
        return 0.0
    dir_map = {"利空": -1, "中性": 0, "利好": 1}
    if a in dir_map and b in dir_map:
        return abs(dir_map[a] - dir_map[b]) / 2.0
    # long-term logic bucket fallback
    if a == "暂无足够证据判断" or b == "暂无足够证据判断":
        return 0.75
    if "不变" in {a, b}:
        return 0.5
    return 1.0


def _history_file(path: str | None = None) -> Path:
    if path:
        return Path(path)
    return ROOT / "outputs" / "history" / "fund_report_history.json"


def _load_history(path: str | None = None) -> List[Dict[str, Any]]:
    p = _history_file(path)
    if not p.exists():
        return []
    try:
        import json

        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _save_history(rows: List[Dict[str, Any]], path: str | None = None) -> None:
    save_json(_history_file(path), rows)


def _consistency_vs_recent(current: FundReport, history_rows: List[Dict[str, Any]], max_lookback: int = 3) -> float:
    candidates = [x for x in history_rows if x.get("fund_code") == current.fund_code]
    if not candidates:
        return 0.5
    recent = candidates[-max_lookback:]
    scores: List[float] = []
    for old in recent:
        d2w = _direction_distance(str(old.get("direction_2w", "中性")), current.direction_2w)
        d3m = _direction_distance(str(old.get("direction_3m", "中性")), current.direction_3m)
        dlt = _direction_distance(str(old.get("long_term_logic", "暂无足够证据判断")), current.long_term_logic)
        # Higher is better; distance 0 means fully consistent.
        score = 1.0 - (0.45 * d2w + 0.35 * d3m + 0.20 * dlt)
        scores.append(max(0.0, min(1.0, score)))
    return round(sum(scores) / max(1, len(scores)), 4)


def _reference_value_score(report: FundReport, source_stability_score: float) -> float:
    direct_share = round(1.0 - float(report.proxy_event_share_main), 4)
    source_diversity_score = min(1.0, float(report.source_diversity_main) / 3.0)
    decision_readiness_score = {"低": 0.35, "中": 0.7, "高": 1.0}.get(str(report.decision_readiness), 0.5)
    score = (
        0.30 * float(report.confidence)
        + 0.25 * direct_share
        + 0.15 * source_stability_score
        + 0.15 * source_diversity_score
        + 0.10 * decision_readiness_score
        + 0.05 * (1.0 if report.recent_event_count >= 2 else 0.5 if report.recent_event_count == 1 else 0.2)
    )
    return round(max(0.0, min(1.0, score)), 4)


def enrich_reports_with_quality(
    reports: List[FundReport],
    collect_stats: Dict[str, Any],
    history_path: str | None = None,
) -> Dict[str, Any]:
    """Update reports in-place with automated stability/consistency/reference scores."""
    history_rows = _load_history(history_path)
    source_stability = compute_source_stability_score(collect_stats)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_history_rows = list(history_rows)
    for report in reports:
        consistency = _consistency_vs_recent(report, history_rows)
        reference_score = _reference_value_score(report, source_stability)
        flags: List[str] = []
        if source_stability < 0.65:
            flags.append("source_stability_low")
        if consistency < 0.45:
            flags.append("historical_consistency_low")
        if report.source_diversity_main <= 1 and report.recent_event_count >= 1:
            flags.append("single_source_dominance")
        if report.proxy_event_share_main >= 0.8 and report.direct_event_count_main == 0:
            flags.append("proxy_dominant_without_direct_confirmation")
        if str(report.decision_readiness) == "低":
            flags.append("decision_readiness_low")
        if reference_score < 0.55:
            flags.append("reference_value_moderate_or_low")
        report.source_stability_score = source_stability
        report.historical_consistency_score = consistency
        report.reference_value_score = reference_score
        report.quality_flags = flags

        new_history_rows.append(
            {
                "timestamp": now,
                "fund_code": report.fund_code,
                "direction_2w": report.direction_2w,
                "direction_3m": report.direction_3m,
                "long_term_logic": report.long_term_logic,
                "conclusion_strength": report.conclusion_strength,
                "reference_value_score": report.reference_value_score,
            }
        )
    _save_history(new_history_rows, history_path)
    return {
        "source_stability_score": source_stability,
        "history_path": str(_history_file(history_path)),
    }
