"""Entity linker for basic institution/asset recognition."""

from __future__ import annotations

from typing import List


KNOWN_ENTITIES = [
    "工信部",
    "国家能源局",
    "中国人民银行",
    "上海黄金交易所",
    "中证500",
    "稀土",
    "卫星",
    "特高压",
    "信用债",
]


def link_entities(text: str) -> List[str]:
    """Extract known entities by dictionary match."""
    return [x for x in KNOWN_ENTITIES if x in text]
