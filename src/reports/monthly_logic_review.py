"""Monthly logic review formatter."""

from __future__ import annotations

from typing import Any, Dict


def render_monthly_logic(fund: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Any]:
    """Return JSON-ready long logic payload."""
    return {
        "fund_code": fund.get("code"),
        "verdict": summary.get("long_term_logic", "不变"),
        "reasons": summary.get("top_positive_drivers", [])[:2],
        "risks": summary.get("top_negative_drivers", [])[:2],
        "need_more_data": summary.get("watch_points", []),
    }
