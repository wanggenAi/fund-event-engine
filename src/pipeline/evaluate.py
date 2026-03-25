"""Evaluate historical prediction accuracy using realized fund NAV moves."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from src.collectors.fund_nav_collector import date_minus_days, fetch_fund_nav_series
from src.utils.cache import save_json
from src.utils.outcome_eval import evaluate_prediction_rows
from src.utils.prediction_history import default_prediction_history_path
from src.utils.source_feedback import build_source_feedback


ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate prediction history with realized NAV direction")
    p.add_argument(
        "--prediction-history",
        default=str(default_prediction_history_path()),
        help="Prediction snapshots produced by src.pipeline.run",
    )
    p.add_argument("--fund", action="append", default=[], help="Optional fund code filter")
    p.add_argument("--max-rows", type=int, default=2000, help="Max prediction rows to evaluate from tail")
    p.add_argument("--timeout", type=float, default=12.0, help="HTTP timeout for NAV fetching")
    p.add_argument("--eval-out", default=str(ROOT / "outputs" / "prediction_evaluation.json"))
    p.add_argument("--md-out", default=str(ROOT / "reports" / "prediction_evaluation.md"))
    p.add_argument("--lookback-days", type=int, default=220, help="NAV lookback days before first prediction date")
    p.add_argument("--horizon-3d-days", type=int, default=3, help="Trading-day step for 3d horizon")
    p.add_argument("--horizon-2w-days", type=int, default=10, help="Trading-day step for 2w horizon")
    p.add_argument("--horizon-3m-days", type=int, default=60, help="Trading-day step for 3m horizon")
    p.add_argument("--neutral-band-3d", type=float, default=0.002)
    p.add_argument("--neutral-band-2w", type=float, default=0.005)
    p.add_argument("--neutral-band-3m", type=float, default=0.015)
    p.add_argument(
        "--source-performance-out",
        default=str(ROOT / "outputs" / "history" / "source_performance.json"),
        help="Output source-performance feedback JSON for runtime scoring",
    )
    p.add_argument("--source-feedback-min-samples", type=int, default=6)
    p.add_argument("--source-feedback-min-samples-floor", type=int, default=2)
    p.add_argument(
        "--source-feedback-dynamic-min-samples",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable dynamic effective-sample threshold in source feedback",
    )
    p.add_argument("--source-feedback-sensitivity", type=float, default=0.5)
    p.add_argument("--source-feedback-half-life-days", type=int, default=45)
    p.add_argument("--source-feedback-decay-floor", type=float, default=0.35)
    p.add_argument(
        "--source-feedback-uncertainty-shrinkage",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Shrink source accuracy toward neutral when effective samples are low",
    )
    p.add_argument("--source-feedback-shrinkage-strength", type=float, default=6.0)
    p.add_argument("--source-feedback-min-multiplier", type=float, default=0.85)
    p.add_argument("--source-feedback-max-multiplier", type=float, default=1.15)
    return p.parse_args()


def _load_prediction_rows(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        raise SystemExit(f"Prediction history not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid prediction history JSON: {exc}") from exc
    if not isinstance(data, list):
        raise SystemExit("Prediction history JSON must be an array")
    return data


def _render_md(payload: Dict[str, object]) -> str:
    lines = ["# Prediction Evaluation", ""]
    lines.append(f"- generated_at: {payload.get('generated_at', '')}")
    lines.append(f"- prediction_history: {payload.get('prediction_history', '')}")
    lines.append("")
    lines.append("## Horizon Summary")
    summary = payload.get("summary", {})
    if isinstance(summary, dict):
        for hz in ("3d", "2w", "3m"):
            s = summary.get(hz, {})
            if not isinstance(s, dict):
                continue
            lines.append(f"- {hz}: accuracy={s.get('accuracy', 0):.2%}, evaluable={s.get('evaluable_rows', 0)}, matched={s.get('matched_rows', 0)}")
    lines.append("")
    lines.append("## Notes")
    lines.append("- 该评估使用基金净值后验方向，不是盘中交易收益回测。")
    lines.append("- 中性区间由 neutral-band 参数控制。")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    args = parse_args()
    history_path = Path(args.prediction_history)
    rows = _load_prediction_rows(history_path)
    if args.fund:
        wanted = set(args.fund)
        rows = [r for r in rows if str(r.get("fund_code", "")) in wanted]
    if args.max_rows > 0:
        rows = rows[-args.max_rows :]
    if not rows:
        raise SystemExit("No prediction rows to evaluate after filtering.")

    fund_codes = sorted({str(r.get("fund_code", "")) for r in rows if str(r.get("fund_code", ""))})
    dates = sorted({str(r.get("asof_date", ""))[:10] for r in rows if str(r.get("asof_date", ""))})
    if not dates:
        raise SystemExit("Prediction rows missing asof_date.")
    start_date = date_minus_days(dates[0], int(args.lookback_days))
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    nav_by_fund: Dict[str, List[Dict[str, float | str]]] = {}
    nav_errors: Dict[str, str] = {}
    for code in fund_codes:
        try:
            nav_by_fund[code] = fetch_fund_nav_series(
                code,
                start_date=start_date,
                end_date=end_date,
                timeout=args.timeout,
            )
        except Exception as exc:
            nav_by_fund[code] = []
            nav_errors[code] = str(exc)

    eval_result = evaluate_prediction_rows(
        prediction_rows=rows,
        nav_by_fund=nav_by_fund,
        horizon_trading_days={
            "3d": int(args.horizon_3d_days),
            "2w": int(args.horizon_2w_days),
            "3m": int(args.horizon_3m_days),
        },
        neutral_band_by_horizon={
            "3d": float(args.neutral_band_3d),
            "2w": float(args.neutral_band_2w),
            "3m": float(args.neutral_band_3m),
        },
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prediction_history": str(history_path),
        "prediction_rows_input": len(rows),
        "fund_count": len(fund_codes),
        "nav_fetch_start_date": start_date,
        "nav_fetch_end_date": end_date,
        "nav_errors": nav_errors,
        "summary": eval_result["summary"],
        "details": eval_result["details"],
    }
    source_feedback = build_source_feedback(
        prediction_rows=rows,
        eval_details=eval_result["details"],
        min_samples=int(args.source_feedback_min_samples),
        min_samples_floor=int(args.source_feedback_min_samples_floor),
        enable_dynamic_min_samples=bool(args.source_feedback_dynamic_min_samples),
        sensitivity=float(args.source_feedback_sensitivity),
        half_life_days=int(args.source_feedback_half_life_days),
        decay_floor=float(args.source_feedback_decay_floor),
        enable_uncertainty_shrinkage=bool(args.source_feedback_uncertainty_shrinkage),
        shrinkage_strength=float(args.source_feedback_shrinkage_strength),
        min_multiplier=float(args.source_feedback_min_multiplier),
        max_multiplier=float(args.source_feedback_max_multiplier),
    )
    source_payload = {
        "generated_at": payload["generated_at"],
        "prediction_history": str(history_path),
        "source_feedback": source_feedback,
    }

    save_json(Path(args.eval_out), payload)
    save_json(Path(args.source_performance_out), source_payload)
    md = _render_md(payload)
    Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.md_out).write_text(md, encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
