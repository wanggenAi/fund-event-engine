"""RSS collector placeholder (free/public sources only)."""

from __future__ import annotations

from typing import Dict, List


def collect_from_rss(url: str) -> List[Dict[str, str]]:
    """Return a minimal RSS item list placeholder.

    This MVP does not depend on paid APIs. Extend this function with real RSS
    parsing when needed.
    """
    return [{"title": f"RSS seed: {url}", "url": url, "content": ""}]
