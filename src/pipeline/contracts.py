"""Stable data contracts for openclaw-friendly pipeline integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class RawDocument:
    """Raw document collected from public/free sources."""

    doc_id: str
    title: str
    source: str
    source_type: str
    published_at: str
    collected_at: str
    content: str
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedDocument:
    """Normalized document after basic cleaning/parsing."""

    doc_id: str
    title: str
    source: str
    source_type: str
    published_at: str
    collected_at: str
    content: str
    clean_text: str
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedEvent:
    """Event contract with mandatory freshness fields."""

    event_id: str
    title: str
    source: str
    source_type: str
    published_at: str
    event_date: str
    collected_at: str
    freshness_bucket: str
    is_stale: bool
    date_uncertain: bool
    event_type: str
    event_subtype: str
    entities: List[str]
    summary: str
    relevance: float
    direction: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FundSignal:
    """Per-event signal mapped to one fund."""

    fund_code: str
    fund_name: str
    event_id: str
    event_title: str
    source: str
    source_type: str
    published_at: str
    event_date: str
    collected_at: str
    freshness_bucket: str
    is_stale: bool
    date_uncertain: bool
    relevance: float
    direction: str
    confidence: float
    score: float
    include_in_main: bool
    evidence_class: str
    logic_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FundReport:
    """Final fund-level stable report payload."""

    fund_code: str
    analysis_window: str
    recent_event_count: int
    stale_event_count_filtered: int
    signal_summary: Dict[str, Any]
    direction_3d: str
    direction_2w: str
    direction_3m: str
    long_term_logic: str
    confidence: float
    warnings: List[str]
    top_positive_drivers: List[str] = field(default_factory=list)
    top_negative_drivers: List[str] = field(default_factory=list)
    background_events: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
