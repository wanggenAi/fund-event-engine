"""Lightweight dedup helpers for similar event titles."""

from __future__ import annotations

import re
from typing import Dict, List


def title_key(title: str) -> str:
    """Build normalized key from title for near-duplicate detection."""
    t = re.sub(r"\s+", "", title.lower())
    t = re.sub(r"[^\w\u4e00-\u9fff]", "", t)
    return t[:32]


def dedupe_events(events: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Deduplicate events by normalized title key."""
    seen = set()
    out: List[Dict[str, str]] = []
    for e in events:
        key = title_key(e.get("title", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out
