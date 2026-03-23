"""Contracts for source collection outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass
class CollectedDocument:
    """Normalized document payload from free/public source collection."""

    title: str
    url: str
    content: str
    source: str
    source_type: str
    source_tier: str
    category: str
    published_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

