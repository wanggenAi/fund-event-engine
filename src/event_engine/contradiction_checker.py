"""Check conclusion quality and return corrective flags."""

from __future__ import annotations

from typing import Any, Dict, List


def check_contradictions(mapped_events: List[Dict[str, Any]], final_view: str) -> Dict[str, Any]:
    """Return contradiction report for auditing."""
    problems: List[str] = []
    if not mapped_events:
        problems.append("无可用事件却输出强结论")
    pos = sum(1 for x in mapped_events if x.get("direction") == "利好")
    neg = sum(1 for x in mapped_events if x.get("direction") == "利空")
    if pos and neg and final_view in {"利好", "利空"}:
        problems.append("正负证据并存但净结论过强")

    has_problem = len(problems) > 0
    return {
        "has_problem": has_problem,
        "problems": problems,
        "fixed_conclusion": "中性" if has_problem else final_view,
        "confidence_adjustment": -0.2 if has_problem else 0.0,
    }
