"""Parsers for example markdown cases and raw article text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict


def parse_case_markdown(path: Path) -> Dict[str, str]:
    """Extract case sections from example markdown file."""
    text = path.read_text(encoding="utf-8")

    def section(title: str) -> str:
        pat = rf"## {re.escape(title)}\n([\s\S]*?)(?:\n## |$)"
        m = re.search(pat, text)
        return m.group(1).strip() if m else ""

    return {
        "case_file": path.name,
        "raw_text": section("模拟新闻/公告正文"),
        "target_funds": section("对应目标基金"),
        "expected": section("预期判断方向"),
        "logic_chain": section("关键逻辑链"),
        "counter": section("可能反证"),
    }
