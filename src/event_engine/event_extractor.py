"""Rule-first event extractor with strict fact and quality gates."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from src.event_engine.entity_linker import link_entities
from src.event_engine.taxonomy_mapper import map_taxonomy


POSITIVE_HINTS = [
    "上调",
    "增长",
    "落地",
    "中标",
    "签约",
    "成功",
    "走弱",
    "回落",
    "改善",
    "收窄",
    "购金增加",
    "上行",
    "反弹",
    "创新高",
    "新高",
    "加速",
    "高增",
    "可期",
    "流入",
    "上涨",
    "涨价",
    "走高",
]
NEGATIVE_HINTS = [
    "下调",
    "下降",
    "延期",
    "失败",
    "走强",
    "违约",
    "走扩",
    "取消",
    "回落不及预期",
    "购金减少",
    "失守",
    "下跌",
    "新低",
    "承压",
    "下行",
]
ACTION_HINTS = [
    "发布",
    "公告",
    "披露",
    "中标",
    "签约",
    "发射",
    "召开",
    "下调",
    "上调",
    "新增",
    "暂停",
    "降息",
    "加息",
    "回落",
    "上行",
    "走弱",
    "走强",
    "走阔",
    "收窄",
    "失守",
    "下跌",
    "反弹",
    "创下",
    "维持",
    "预计",
    "上行",
    "下行",
    "走高",
    "走低",
    "走阔",
    "收窄",
    "波动",
    "通知",
    "印发",
    "批复",
    "通告",
    "公示",
    "实施",
    "出台",
    "征求意见",
    "总量控制",
    "指标",
    "跟踪",
    "趋势",
    "信号",
    "走向",
]
SUBJECT_HINT = r"(国家|中国|央行|工信部|能源局|发改委|交易所|公司|集团|基金|统计局|美联储|财政部|协会)"

_NEGATIONS = ["不会", "无法", "难以", "并非", "没有", "未能", "不"]


def _negate_check(text: str, keyword: str) -> bool:
    """Return True if keyword is immediately preceded (within 5 chars) by a negation."""
    idx = text.find(keyword)
    while idx != -1:
        prefix = text[max(0, idx - 5):idx]
        if any(neg in prefix for neg in _NEGATIONS):
            return True
        idx = text.find(keyword, idx + 1)
    return False


def _direction_hint(text: str) -> str:
    for k in POSITIVE_HINTS:
        if k in text:
            return "利空" if _negate_check(text, k) else "利好"
    for k in NEGATIVE_HINTS:
        if k in text:
            return "利好" if _negate_check(text, k) else "利空"
    return "中性"


def _event_strength(text: str, is_confirmed: bool) -> float:
    if not is_confirmed:
        return 0.3
    if any(k in text for k in ["正向信号", "负向信号", "趋势偏强", "趋势偏弱", "跟踪"]):
        return 0.8
    if any(k in text for k in ["官方", "公告", "数据", "统计", "招标", "中标", "会议纪要", "决议"]):
        return 1.0
    if any(k in text for k in ["报道", "采访", "消息"]):
        return 0.75
    return 0.55


def _evidence_tier(source_tier: str, is_confirmed: bool) -> str:
    if source_tier in {"A", "B"} and is_confirmed:
        return source_tier
    return "C"


def _is_fact_like(sentence: str) -> bool:
    has_subject = bool(re.search(SUBJECT_HINT, sentence))
    has_action = any(k in sentence for k in ACTION_HINTS)
    has_date = bool(re.search(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?", sentence))
    has_number = bool(re.search(r"\d+(?:\.\d+)?[%万吨亿元个家项]", sentence))
    policy_headline = bool(re.search(r"关于.+(通知|公告|通告|方案|意见|规定)", sentence))
    return (
        (has_subject and has_action)
        or (has_date and has_action)
        or (has_action and has_number and len(sentence) >= 10)
        or (policy_headline and len(sentence) >= 12)
        or (has_action and len(sentence) >= 14)
    )


def _extract_date(text: str) -> str:
    match = re.search(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)", text)
    if not match:
        return ""
    return match.group(1).replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")


def extract_events(raw_text: str, title: str = "", source_tier: str = "C") -> List[Dict[str, Any]]:
    """Extract one or more normalized events from raw text."""
    if not raw_text.strip():
        return []

    sentences = [s.strip() for s in re.split(r"[。！？!?\n\r]+", raw_text) if s.strip()]
    events: List[Dict[str, Any]] = []

    for sentence in sentences:
        if len(sentence) < 18:
            continue
        if not _is_fact_like(sentence):
            continue

        event_type, event_subtype = map_taxonomy(sentence)
        entities = link_entities(sentence)
        event_date = _extract_date(sentence)

        is_confirmed = not any(x in sentence for x in ["传闻", "据悉", "小作文", "猜测", "市场传"])
        evidence_tier = _evidence_tier(source_tier, is_confirmed)
        direction = _direction_hint(sentence)
        event_strength = _event_strength(sentence, is_confirmed)

        event_title = title.strip()
        # Keep snapshot-style titles to preserve key variable tags (e.g.,申赎/ETF流向).
        if "快照" in event_title:
            pass
        # Avoid misleading document-level headlines when body sentence is the real event.
        elif not event_title or (len(sentence) >= 22 and sentence not in event_title):
            event_title = sentence[:48] + ("..." if len(sentence) > 48 else "")

        events.append(
            {
                "title": event_title,
                "date": event_date,
                "event_type": event_type,
                "event_subtype": event_subtype,
                "entities": entities,
                "industries": entities,
                "summary": sentence[:220],
                "is_confirmed": is_confirmed,
                "source_level": "official" if source_tier == "A" else "mainstream_media",
                "source_tier": source_tier,
                "evidence_tier": evidence_tier,
                "surprise_level": 3,
                "short_term_direction": direction,
                "medium_term_direction": direction,
                "event_strength": event_strength,
            }
        )

    if events:
        return events

    # Fallback: use title as event sentence for news-style feeds.
    if title and (_is_fact_like(title) or bool(re.search(r"(公告|通知|通告|印发|批复|征求意见|总量控制)", title))):
        event_type, event_subtype = map_taxonomy(title)
        entities = link_entities(title)
        is_confirmed = not any(x in title for x in ["传闻", "据悉", "小作文", "猜测", "市场传"])
        return [
            {
                "title": title,
                "date": _extract_date(title),
                "event_type": event_type,
                "event_subtype": event_subtype,
                "entities": entities,
                "industries": entities,
                "summary": title[:220],
                "is_confirmed": is_confirmed,
                "source_level": "official" if source_tier == "A" else "mainstream_media",
                "source_tier": source_tier,
                "evidence_tier": _evidence_tier(source_tier, is_confirmed),
                "surprise_level": 2,
                "short_term_direction": _direction_hint(title),
                "medium_term_direction": _direction_hint(title),
                "event_strength": _event_strength(title, is_confirmed),
            }
        ]

    return []
