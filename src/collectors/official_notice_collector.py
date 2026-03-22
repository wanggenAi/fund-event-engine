"""Official notice collector using public pages."""

from __future__ import annotations

from typing import Dict, List


def collect_official_notices(url: str) -> List[Dict[str, str]]:
    """Return placeholder official notice entries."""
    return [{"title": f"Official notice seed: {url}", "url": url, "content": ""}]
