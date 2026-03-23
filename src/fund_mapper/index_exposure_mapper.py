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
    "设备",
    "产业",
    "开采",
    "冶炼",
    "通信",
    "卫星",
    "改造",
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
    strong_hit = 0
    for k in keys:
        if not k:
            continue
        expanded = _expand_key(str(k))
        matched = [token for token in expanded if token in event_text]
        if matched:
            hit += 1
            # Treat direct sector/factor token matches as stronger evidence.
            if any(token in event_text for token in expanded[:2]):
                strong_hit += 1

    base = hit / max(2, len(keys) // 3)
    boost = min(0.35, strong_hit * 0.08)
    score = max(0.0, min(1.0, base + boost))

    ftype = str(fund_profile.get("type", ""))
    fname = str(fund_profile.get("name", ""))
    txt = event_text.lower()
    if ftype == "gold" and any(k in txt for k in ["黄金", "comex", "现货金", "美元", "实际利率", "央行购金", "etf"]):
        score = max(score, 0.38)
    elif ftype == "bond" and any(k in txt for k in ["国债", "收益率", "信用利差", "违约", "流动性", "降息", "加息"]):
        score = max(score, 0.34)
    elif ftype == "broad_equity" and any(k in txt for k in ["中证500", "风格轮动", "风险偏好", "流动性"]):
        score = max(score, 0.34)
    elif ftype == "thematic_equity":
        sector_terms = [str(s) for s in fund_profile.get("sectors", [])]
        if any(s and s in event_text for s in sector_terms):
            score = max(score, 0.34)
        # Satellite thematic direct boost.
        if ("卫星" in fname or "卫星" in " ".join(sector_terms)) and any(k in event_text for k in ["卫星", "商业航天", "航天", "发射", "组网"]):
            score = max(score, 0.4)
        # Rare-earth thematic direct boost.
        if ("稀土" in fname or "稀土" in " ".join(sector_terms)) and any(k in event_text for k in ["稀土", "重稀土", "永磁", "配额", "冶炼", "开采"]):
            score = max(score, 0.4)
        # Power-grid thematic direct boost.
        if ("电网" in fname or "电网" in " ".join(sector_terms)) and any(k in event_text for k in ["电网", "特高压", "配网", "招标", "中标"]):
            score = max(score, 0.4)

    return score
