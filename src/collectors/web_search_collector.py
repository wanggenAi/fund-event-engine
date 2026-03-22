"""Web search seed collector placeholder for free sources."""

from __future__ import annotations

from typing import Dict, List


def build_recent_query(base_query: str, window_days: int = 7) -> str:
    """Build time-constrained search query text."""
    if window_days <= 3:
        return f"{base_query} 最近3天 最新"
    if window_days <= 7:
        return f"{base_query} 最近7天 本周 最新"
    if window_days <= 14:
        return f"{base_query} 最近两周 最新"
    return f"{base_query} 近一月 最新"


def collect_from_search_seed(seed_url: str) -> List[Dict[str, str]]:
    """Return placeholder links from a public seed page."""
    return [{"title": f"Search seed: {seed_url}", "url": seed_url, "content": ""}]
