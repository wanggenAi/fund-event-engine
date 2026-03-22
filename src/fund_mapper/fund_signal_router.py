"""Route events to fund-specific judgement paths."""

from __future__ import annotations

from typing import Any, Dict, List

from src.event_engine.impact_chain import build_impact_chain
from src.event_engine.signal_scorer import score_event, score_to_label
from src.fund_mapper.index_exposure_mapper import calc_relevance


def _long_logic_from_scores(score_3m: float) -> str:
    if score_3m > 0.2:
        return "强化"
    if score_3m < -0.2:
        return "弱化"
    return "不变"


def map_event_to_fund(event: Dict[str, Any], fund: Dict[str, Any]) -> Dict[str, Any]:
    """Map single event to one fund with explainable fields."""
    text = f"{event.get('title', '')} {event.get('summary', '')}"
    relevance = calc_relevance(text, fund)
    score = score_event(event, relevance)

    return {
        "fund_code": fund.get("code"),
        "fund_name": fund.get("name"),
        "fund_type": fund.get("type"),
        "event_title": event.get("title"),
        "relevance": round(relevance, 4),
        "direction_3d": score_to_label(score * 1.2),
        "direction_2w": score_to_label(score),
        "direction_3m": score_to_label(score * 0.8),
        "logic_chain": build_impact_chain(str(fund.get("type", "")), str(event.get("title", ""))),
        "counter_arguments": ["存在风格轮动或情绪反向扰动风险"],
        "confidence": round(min(0.95, 0.35 + relevance * 0.5), 4),
        "score": round(score, 6),
    }


def aggregate_for_fund(mapped_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate mapped events into final 3d/2w/3m views and report blocks."""
    if not mapped_items:
        return {
            "view_3d": "中性",
            "view_2w": "中性",
            "view_3m": "中性",
            "long_term_logic": "不变",
            "top_positive_drivers": [],
            "top_negative_drivers": [],
            "watch_points": ["当前缺少高相关事件，建议继续观察"],
            "confidence": 0.3,
        }

    score = sum(x.get("score", 0.0) for x in mapped_items)
    pos = [x for x in mapped_items if x.get("score", 0.0) > 0]
    neg = [x for x in mapped_items if x.get("score", 0.0) < 0]

    return {
        "view_3d": score_to_label(score * 1.2),
        "view_2w": score_to_label(score),
        "view_3m": score_to_label(score * 0.8),
        "long_term_logic": _long_logic_from_scores(score * 0.8),
        "top_positive_drivers": [x.get("event_title", "") for x in sorted(pos, key=lambda i: i.get("score", 0), reverse=True)[:3]],
        "top_negative_drivers": [x.get("event_title", "") for x in sorted(neg, key=lambda i: i.get("score", 0))[:3]],
        "watch_points": ["关注新增高可信度公告", "若出现反向证据需下调置信度"],
        "confidence": round(min(0.95, 0.4 + abs(score)), 4),
    }
