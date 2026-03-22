"""Exposure mapping between event keywords and fund profile factors."""

from __future__ import annotations

import re
from typing import Any, Dict


GENERIC_TAILS = [
    "进展",
    "环境",
    "预期",
    "需求",
    "变量",
    "主题",
    "指数",
    "基金",
    "压力",
    "节奏",
    "管理",
]


def _expand_key(key: str) -> list[str]:
    candidates = {key.strip()}
    cleaned = key.strip()
    for tail in GENERIC_TAILS:
        if cleaned.endswith(tail) and len(cleaned) > len(tail) + 1:
            candidates.add(cleaned[: -len(tail)])
    for p in re.split(r"[、，,；;：:\s/（）()\-]+", key):
        p = p.strip()
        if len(p) >= 2:
            candidates.add(p)
    return [c for c in candidates if len(c) >= 2]


def calc_relevance(event_text: str, fund_profile: Dict[str, Any]) -> float:
    """Compute rough relevance by keyword overlap."""
    keys = []
    keys.extend(fund_profile.get("sectors", []))
    keys.extend(fund_profile.get("factors", []))
    keys.extend(fund_profile.get("bullish_triggers", []))
    keys.extend(fund_profile.get("bearish_triggers", []))
    if not keys:
        return 0.0
    hit = 0
    for k in keys:
        if not k:
            continue
        if any(token in event_text for token in _expand_key(str(k))):
            hit += 1
    return min(1.0, hit / max(3, len(keys) // 2))
