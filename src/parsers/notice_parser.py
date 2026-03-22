"""Notice parser helpers."""

from __future__ import annotations

import re
from typing import Dict


def parse_notice(text: str) -> Dict[str, str]:
    """Extract title/date style fragments from notice-like text."""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    title = lines[0] if lines else ""
    m = re.search(r"(20\\d{2}[-/.年]\\d{1,2}[-/.月]\\d{1,2}(?:日)?)", text)
    date = m.group(1) if m else ""
    return {"title": title, "date": date, "content": text.strip()}
