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
    """Normalized document after strict cleaning and noise screening."""

    doc_id: str
    title: str
    source: str
    source_type: str
    published_at: str
    collected_at: str
    content: str
    clean_text: str
    url: str = ""
    noise_lines_filtered: int = 0
    chrome_lines_filtered: int = 0
    content_quality_score: float = 0.0
    extractable_event_score: float = 0.0
    extractable_event_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedEvent:
    """Event contract with mandatory freshness and quality fields."""

    event_id: str
    title: str
    source: str
    source_type: str
    source_category: str
    source_tier: str
    published_at: str
    event_date: str
    collected_at: str
    freshness_bucket: str
    is_stale: bool
    date_uncertain: bool
    is_page_chrome: bool
    is_noise: bool
    content_quality_score: float
    extractable_event_score: float
    evidence_tier: str
    event_type: str
    event_subtype: str
    entities: List[str]
    summary: str
    relevance: float
    direction: str
    confidence: float
    event_strength: float
    duplicate_group: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FundSignal:
    """Per-event signal mapped to one fund."""

    fund_code: str
    fund_name: str
    fund_type: str
    event_id: str
    event_title: str
    source: str
    source_type: str
    source_category: str
    source_tier: str
    evidence_tier: str
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
    gated_reason: str
    variable_evidence_type: str = "direct"
    variable_evidence_note: str = ""
    logic_chain: List[str] = field(default_factory=list)
    counter_evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FundReport:
    """Final fund-level stable report payload."""

    fund_code: str
    fund_name: str
    fund_type: str
    analysis_window: str
    recent_event_count: int
    stale_event_count_filtered: int
    noise_event_count_filtered: int
    low_tier_event_count_filtered: int
    proxy_event_count_main: int
    proxy_event_share_main: float
    direct_event_count_main: int
    source_diversity_main: int
    decision_readiness: str
    decision_constraints: List[str]
    signal_summary: Dict[str, Any]
    direction_3d: str
    direction_2w: str
    direction_3m: str
    long_term_logic: str
    confidence: float
    conclusion_strength: str
    warnings: List[str]
    key_events: List[Dict[str, Any]] = field(default_factory=list)
    downgraded_events: List[Dict[str, Any]] = field(default_factory=list)
    core_driver_check: Dict[str, str] = field(default_factory=dict)
    driver_coverage_summary: Dict[str, Any] = field(default_factory=dict)
    counter_evidence: List[str] = field(default_factory=list)
    watch_points: List[str] = field(default_factory=list)
    one_liner: str = ""
    source_stability_score: float = 0.0
    historical_consistency_score: float = 0.0
    reference_value_score: float = 0.0
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
