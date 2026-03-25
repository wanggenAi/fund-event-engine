"""Utilities for realized-outcome evaluation against fund NAV series."""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple


def classify_return_direction(ret: float, neutral_band: float) -> str:
    """Map realized return to directional label."""
    if ret > neutral_band:
        return "利好"
    if ret < -neutral_band:
        return "利空"
    return "中性"


def realized_direction_from_series(
    nav_rows: Sequence[Dict[str, float | str]],
    asof_date: str,
    horizon_days: int,
    neutral_band: float,
) -> Tuple[str, float] | None:
    """Compute realized direction and return over N trading rows ahead."""
    if not nav_rows:
        return None
    target_idx = -1
    for idx, row in enumerate(nav_rows):
        d = str(row.get("date", ""))
        if d >= asof_date:
            target_idx = idx
            break
    if target_idx < 0:
        return None
    end_idx = target_idx + horizon_days
    if end_idx >= len(nav_rows):
        return None
    start_nav = float(nav_rows[target_idx]["nav"])
    end_nav = float(nav_rows[end_idx]["nav"])
    if start_nav <= 0:
        return None
    ret = (end_nav / start_nav) - 1.0
    return classify_return_direction(ret, neutral_band), ret


def evaluate_prediction_rows(
    prediction_rows: Iterable[Dict[str, object]],
    nav_by_fund: Dict[str, Sequence[Dict[str, float | str]]],
    horizon_trading_days: Dict[str, int],
    neutral_band_by_horizon: Dict[str, float],
) -> Dict[str, object]:
    """Evaluate prediction rows against realized NAV direction."""
    details: List[Dict[str, object]] = []
    counters: Dict[str, Dict[str, int]] = {}
    for hz in horizon_trading_days.keys():
        counters[hz] = {"total": 0, "matched": 0, "neutral_pred": 0, "neutral_realized": 0}

    for row in prediction_rows:
        fund_code = str(row.get("fund_code", ""))
        asof = str(row.get("asof_date", ""))
        series = nav_by_fund.get(fund_code, [])
        for hz, trading_days in horizon_trading_days.items():
            pred_field = f"direction_{hz}"
            predicted = str(row.get(pred_field, ""))
            counters[hz]["total"] += 1
            if predicted == "中性":
                counters[hz]["neutral_pred"] += 1
            realized = realized_direction_from_series(
                series,
                asof_date=asof,
                horizon_days=trading_days,
                neutral_band=float(neutral_band_by_horizon.get(hz, 0.0)),
            )
            if not realized:
                details.append(
                    {
                        "fund_code": fund_code,
                        "asof_date": asof,
                        "horizon": hz,
                        "predicted_direction": predicted,
                        "status": "insufficient_future_nav",
                    }
                )
                continue
            realized_direction, realized_ret = realized
            if realized_direction == "中性":
                counters[hz]["neutral_realized"] += 1
            matched = predicted == realized_direction
            if matched:
                counters[hz]["matched"] += 1
            details.append(
                {
                    "fund_code": fund_code,
                    "asof_date": asof,
                    "horizon": hz,
                    "predicted_direction": predicted,
                    "realized_direction": realized_direction,
                    "realized_return": round(realized_ret, 6),
                    "matched": matched,
                    "status": "ok",
                }
            )

    summary: Dict[str, Dict[str, float | int]] = {}
    for hz, c in counters.items():
        ok_rows = [x for x in details if x["horizon"] == hz and x["status"] == "ok"]
        total_ok = len(ok_rows)
        matched = sum(1 for x in ok_rows if x.get("matched") is True)
        acc = (matched / total_ok) if total_ok > 0 else 0.0
        summary[hz] = {
            "total_rows": c["total"],
            "evaluable_rows": total_ok,
            "matched_rows": matched,
            "accuracy": round(acc, 4),
            "neutral_pred_rows": c["neutral_pred"],
            "neutral_realized_rows": c["neutral_realized"],
        }
    return {"summary": summary, "details": details}
