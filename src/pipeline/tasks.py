"""Pipeline task functions with freshness-first gating."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from src.event_engine.event_extractor import extract_events
from src.event_engine.impact_chain import build_impact_chain
from src.event_engine.signal_scorer import score_event, score_to_label
from src.fund_mapper.fund_profile_loader import load_fund_profiles
from src.fund_mapper.index_exposure_mapper import calc_relevance
from src.parsers.article_parser import parse_case_markdown
from src.pipeline.contracts import ExtractedEvent, FundReport, FundSignal, ParsedDocument, RawDocument
from src.utils.config_loader import load_yaml
from src.utils.dedup import title_key
from src.utils.time_utils import freshness_bucket, is_stale_for_window


ROOT = Path(__file__).resolve().parents[2]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _extract_date_from_text(text: str) -> str:
    m = re.search(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)", text)
    if not m:
        return ""
    return m.group(1).replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")


def load_example_documents(examples_dir: Path) -> List[RawDocument]:
    """Load markdown examples into raw document contracts."""
    rows: List[RawDocument] = []
    collected = _now_iso()
    for idx, path in enumerate(sorted(examples_dir.glob("*_case.md")), start=1):
        case = parse_case_markdown(path)
        raw_text = case.get("raw_text", "")
        published = _extract_date_from_text(raw_text)
        rows.append(
            RawDocument(
                doc_id=f"example-{idx:03d}",
                title=path.stem,
                source="examples",
                source_type="search_seed",
                published_at=published,
                collected_at=collected,
                content=raw_text,
                url=str(path),
            )
        )
    return rows


def parse_documents(raw_docs: Sequence[RawDocument]) -> List[ParsedDocument]:
    """Normalize raw docs into parsed docs."""
    out: List[ParsedDocument] = []
    for d in raw_docs:
        clean_text = re.sub(r"\s+", " ", d.content).strip()
        out.append(
            ParsedDocument(
                doc_id=d.doc_id,
                title=d.title,
                source=d.source,
                source_type=d.source_type,
                published_at=d.published_at,
                collected_at=d.collected_at,
                content=d.content,
                clean_text=clean_text,
                url=d.url,
            )
        )
    return out


def extract_events_from_docs(parsed_docs: Sequence[ParsedDocument], window_days: int) -> List[ExtractedEvent]:
    """Extract and enrich events with freshness-required fields."""
    events: List[ExtractedEvent] = []
    for doc in parsed_docs:
        extracted = extract_events(doc.clean_text, title=doc.title)
        for i, ev in enumerate(extracted, start=1):
            event_date = ev.get("date", "") or _extract_date_from_text(doc.clean_text)
            published_at = doc.published_at or ""
            reference_date = event_date or published_at
            date_uncertain = not bool(event_date)
            stale = is_stale_for_window(reference_date, window_days) if reference_date else True
            confidence = 0.75 if ev.get("is_confirmed") else 0.45
            if date_uncertain:
                confidence -= 0.25

            events.append(
                ExtractedEvent(
                    event_id=f"{doc.doc_id}-ev-{i}",
                    title=ev.get("title", doc.title),
                    source=doc.source,
                    source_type=doc.source_type,
                    published_at=published_at,
                    event_date=event_date,
                    collected_at=doc.collected_at,
                    freshness_bucket=freshness_bucket(reference_date),
                    is_stale=stale,
                    date_uncertain=date_uncertain,
                    event_type=ev.get("event_type", "sentiment"),
                    event_subtype=ev.get("event_subtype", "commentary"),
                    entities=ev.get("entities", []),
                    summary=ev.get("summary", ""),
                    relevance=0.0,
                    direction=ev.get("short_term_direction", "中性"),
                    confidence=max(0.1, round(confidence, 4)),
                )
            )

    # Lightweight dedupe for repeated old-news reposts.
    dedup_map: Dict[str, ExtractedEvent] = {}
    for e in events:
        key = f"{title_key(e.title)}::{e.event_date or e.published_at}"
        old = dedup_map.get(key)
        if not old or (e.collected_at > old.collected_at):
            dedup_map[key] = e
    return list(dedup_map.values())


def _stale_penalty_config() -> Dict[str, float]:
    cfg = load_yaml(ROOT / "configs" / "scoring.yaml")
    return cfg.get("stale_penalty", {"older_than_window": 0.6, "date_uncertain": 0.7})


def map_events_to_funds(events: Sequence[ExtractedEvent], fund_codes: Sequence[str] | None = None, window_days: int = 7) -> List[FundSignal]:
    """Map events into fund signals with freshness gating and background classification."""
    funds = load_fund_profiles()
    by_code = {f.get("code"): f for f in funds}
    target_funds = [by_code[c] for c in fund_codes if c in by_code] if fund_codes else funds
    penalties = _stale_penalty_config()

    out: List[FundSignal] = []
    for ev in events:
        ev_text = f"{ev.title} {ev.summary}"
        for fund in target_funds:
            relevance = calc_relevance(ev_text, fund)
            if relevance < 0.1:
                continue

            payload = {
                "source_level": _source_to_level(ev.source_type),
                "date": ev.event_date or ev.published_at,
                "is_confirmed": ev.confidence >= 0.6,
                "short_term_direction": ev.direction,
            }
            base_score = score_event(payload, relevance)

            include_in_main = True
            evidence_class = "event_evidence"
            adjusted_score = base_score

            # Community/self-media are high-frequency clue sources:
            # keep them for discovery, but do not let them directly drive
            # primary fund conclusions without secondary confirmation.
            if ev.source_type in {"community_forum", "self_media"}:
                include_in_main = False
                evidence_class = "clue_only"

            if ev.is_stale:
                include_in_main = False
                evidence_class = "background_evidence"
                adjusted_score *= penalties.get("older_than_window", 0.6)
            if ev.date_uncertain:
                adjusted_score *= penalties.get("date_uncertain", 0.7)
                if window_days <= 14:
                    include_in_main = False
                    evidence_class = "background_evidence"

            out.append(
                FundSignal(
                    fund_code=fund.get("code", ""),
                    fund_name=fund.get("name", ""),
                    event_id=ev.event_id,
                    event_title=ev.title,
                    source=ev.source,
                    source_type=ev.source_type,
                    published_at=ev.published_at,
                    event_date=ev.event_date,
                    collected_at=ev.collected_at,
                    freshness_bucket=ev.freshness_bucket,
                    is_stale=ev.is_stale,
                    date_uncertain=ev.date_uncertain,
                    relevance=round(relevance, 4),
                    direction=ev.direction,
                    confidence=ev.confidence,
                    score=round(adjusted_score, 6),
                    include_in_main=include_in_main,
                    evidence_class=evidence_class,
                    logic_chain=build_impact_chain(str(fund.get("type", "")), ev.title),
                )
            )
    return out


def _source_to_level(source_type: str) -> str:
    mapping = {
        "official_site": "official",
        "exchange_notice": "exchange",
        "fund_company": "fund_company",
        "media": "mainstream_media",
        "rss": "mainstream_media",
        "community_forum": "community_forum",
        "self_media": "self_media",
        "search_seed": "other",
    }
    return mapping.get(source_type, "other")


def _score_to_logic(score: float, low_event_count: bool) -> str:
    if low_event_count:
        return "不变"
    if score > 0.2:
        return "强化"
    if score < -0.2:
        return "弱化"
    return "不变"


def aggregate_reports(signals: Sequence[FundSignal], window_days: int) -> List[FundReport]:
    """Aggregate fund reports with stale-event hard filtering."""
    grouped: Dict[str, List[FundSignal]] = defaultdict(list)
    for s in signals:
        grouped[s.fund_code].append(s)

    funds = {f.get("code"): f for f in load_fund_profiles()}
    reports: List[FundReport] = []
    for code, fund in funds.items():
        items = grouped.get(code, [])
        fresh = [x for x in items if x.include_in_main]
        stale_filtered = [x for x in items if not x.include_in_main]
        clue_only = [x for x in items if x.evidence_class == "clue_only"]

        net = sum(x.score for x in fresh)
        direction_2w = score_to_label(net)
        direction_3d = score_to_label(net * 1.15)
        direction_3m = score_to_label(net * 0.85)

        warnings: List[str] = []
        if len(fresh) < 2:
            warnings.append("近期高质量新增事件不足，结论以中性/待观察为主")
            direction_3d = "中性"
            direction_2w = "中性"
        if any(x.date_uncertain for x in fresh):
            warnings.append("部分事件日期不确定，已下调权重")
        if len(clue_only) > 0 and len(fresh) == 0:
            warnings.append("当前仅有社区/自媒体线索，尚未形成可确认主证据")

        pos = [x for x in fresh if x.score > 0]
        neg = [x for x in fresh if x.score < 0]

        reports.append(
            FundReport(
                fund_code=code,
                analysis_window=f"{window_days}d",
                recent_event_count=len(fresh),
                stale_event_count_filtered=len(stale_filtered),
                signal_summary={
                    "net_score": round(net, 6),
                    "positive_count": len(pos),
                    "negative_count": len(neg),
                    "total_signals": len(items),
                },
                direction_3d=direction_3d,
                direction_2w=direction_2w,
                direction_3m=direction_3m,
                long_term_logic=_score_to_logic(net * 0.85, low_event_count=len(fresh) < 2),
                confidence=round(min(0.9, 0.35 + 0.08 * len(fresh) + abs(net) * 0.4), 4),
                warnings=warnings,
                top_positive_drivers=[x.event_title for x in sorted(pos, key=lambda i: i.score, reverse=True)[:3]],
                top_negative_drivers=[x.event_title for x in sorted(neg, key=lambda i: i.score)[:3]],
                background_events=[x.event_title for x in stale_filtered[:5]],
            )
        )

    return reports


def render_markdown(reports: Sequence[FundReport]) -> str:
    """Render report markdown with explicit freshness warnings."""
    lines = ["# fund-event-engine pipeline report", ""]
    for r in reports:
        lines.extend(
            [
                f"## {r.fund_code}",
                f"- 分析窗口：{r.analysis_window}",
                f"- 3日视角：{r.direction_3d}",
                f"- 2周视角：{r.direction_2w}",
                f"- 3个月视角：{r.direction_3m}",
                f"- 长期逻辑：{r.long_term_logic}",
                f"- 近期有效事件数：{r.recent_event_count}",
                f"- 已过滤陈旧/不确定事件数：{r.stale_event_count_filtered}",
                "",
                "### 核心驱动",
                *([f"- {x}" for x in r.top_positive_drivers] or ["- 近期未看到足以形成明确支撑的新增驱动"]),
                "",
                "### 反证与风险",
                *([f"- {x}" for x in r.top_negative_drivers] or ["- 当前未见集中新增利空证据"]),
                "",
                "### 背景信息（不纳入主结论）",
                *([f"- {x}" for x in r.background_events] or ["- 无"]),
                "",
                "### 警示",
                *([f"- {x}" for x in r.warnings] or ["- 无"]),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
