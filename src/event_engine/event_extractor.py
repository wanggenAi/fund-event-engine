"""Rule-first event extractor for MVP."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from src.event_engine.entity_linker import link_entities
from src.event_engine.taxonomy_mapper import map_taxonomy


SOURCE_LEVEL_HINTS = {
    "工信部": "official",
    "国家能源局": "official",
    "人民银行": "official",
    "上海黄金交易所": "exchange",
}


def _direction_hint(text: str) -> str:
    if any(k in text for k in ["上调", "增长", "落地", "成功", "走弱", "回落"]):
        return "利好"
    if any(k in text for k in ["下调", "下降", "延期", "失败", "走强", "违约"]):
        return "利空"
    return "中性"


def extract_events(raw_text: str, title: str = "") -> List[Dict[str, Any]]:
    """Extract one or more normalized events from raw text."""
    whole = f"{title} {raw_text}".strip()
    if not whole:
        return []

    date_match = re.search(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)", whole)
    event_type, event_subtype = map_taxonomy(whole)
    entities = link_entities(whole)
    source_level = "other"
    for k, v in SOURCE_LEVEL_HINTS.items():
        if k in whole:
            source_level = v
            break

    direction = _direction_hint(whole)
    is_confirmed = not any(x in whole for x in ["传闻", "据悉", "小作文"])
    if not is_confirmed:
        source_level = "other"

    event = {
        "title": title or (whole[:36] + ("..." if len(whole) > 36 else "")),
        "date": date_match.group(1) if date_match else "",
        "event_type": event_type,
        "event_subtype": event_subtype,
        "entities": entities,
        "industries": entities,
        "summary": raw_text[:180],
        "is_confirmed": is_confirmed,
        "source_level": source_level,
        "surprise_level": 3,
        "short_term_direction": direction,
        "medium_term_direction": direction,
    }
    return [event]
