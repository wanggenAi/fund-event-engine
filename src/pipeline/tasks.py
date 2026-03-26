"""Pipeline task functions with freshness-first and evidence-tier gating."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from src.collectors.source_collector import (
    collect_central_bank_gold_signal_documents,
    collect_documents_from_sources,
    collect_google_news_documents,
    collect_market_variable_documents,
    collect_satellite_price_proxy_documents,
    collect_structured_theme_signal_documents,
    collect_thematic_industry_signal_documents,
)
from src.event_engine.event_extractor import extract_events
from src.event_engine.impact_chain import build_impact_chain
from src.event_engine.signal_scorer import score_event, score_to_label
from src.fund_mapper.fund_profile_loader import load_fund_profiles
from src.fund_mapper.index_exposure_mapper import calc_relevance
from src.parsers.article_parser import parse_case_markdown
from src.parsers.html_cleaner import clean_and_score_text
from src.pipeline.contracts import ExtractedEvent, FundReport, FundSignal, ParsedDocument, RawDocument
from src.utils.config_loader import load_yaml
from src.utils.dedup import title_key
from src.utils.time_utils import age_days, freshness_bucket, is_stale_for_window


ROOT = Path(__file__).resolve().parents[2]
_SCORING_OVERRIDE: Dict[str, Any] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _extract_date_from_text(text: str) -> str:
    m = re.search(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)", text)
    if not m:
        return ""
    return m.group(1).replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")


def _sources_config() -> Dict[str, Any]:
    return load_yaml(ROOT / "configs" / "sources.yaml")


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def set_runtime_scoring_override(override: Dict[str, Any] | None = None) -> None:
    """Set runtime scoring override for current process (openclaw-friendly dynamic tuning)."""
    global _SCORING_OVERRIDE
    _SCORING_OVERRIDE = dict(override or {})


def _scoring_config() -> Dict[str, Any]:
    cfg = load_yaml(ROOT / "configs" / "scoring.yaml")
    if not _SCORING_OVERRIDE:
        return cfg
    return _deep_merge(cfg, _SCORING_OVERRIDE)


def _source_tier(source_type: str) -> str:
    cfg = _sources_config()
    tier_map = cfg.get("source_type_tier", {})
    return str(tier_map.get(source_type, "C"))


def _source_category(source_type: str) -> str:
    cfg = _sources_config()
    cat_map = cfg.get("source_type_category", {})
    return str(cat_map.get(source_type, "specialist_research"))


def _news_title_relevant(title: str) -> bool:
    keys = [
        "黄金",
        "现货金",
        "comex",
        "美元",
        "实际利率",
        "美联储",
        "稀土",
        "电网",
        "特高压",
        "卫星",
        "商用卫星",
        "发射",
        "特高压",
        "招标",
        "中标",
        "信用债",
        "信用利差",
        "中证500",
        "央行购金",
        "黄金储备",
        "gold reserve",
        "central bank gold",
        "永磁",
        "氧化镨钕",
        "镨钕",
        "镝",
        "铽",
        "出口管制",
        "配额",
    ]
    t = title.lower()
    return any(k in title for k in keys) or ("comex" in t)


def _google_news_publisher(title: str) -> str:
    if " - " not in title:
        return ""
    return title.rsplit(" - ", 1)[-1].strip()


def _google_news_tier(title: str) -> str:
    publisher = _google_news_publisher(title)
    if not publisher:
        return "C"
    high = {
        "Reuters",
        "财联社",
        "中国证券报",
        "中证网",
        "证券时报",
        "上海证券报",
        "上证报",
        "第一财经",
        "新华网",
        "人民网",
        "经济日报",
        "World Gold Council",
        "Bloomberg",
        "CNBC",
        "Financial Times",
        "WSJ",
        "华尔街日报",
        "FT中文网",
        "Kitco",
        "Fastmarkets",
        "SMM",
        "上海有色网",
        "Mysteel",
        "金十数据",
    }
    mid = {"新浪财经", "每日经济新闻", "21财经", "界面新闻", "华尔街见闻"}
    low = {"中金在线", "手机新浪网", "财富号", "搜狐", "网易号", "百家号", "同花顺", "股吧"}

    if any(x in publisher for x in high):
        return "B"
    if any(x in publisher for x in mid):
        return "B"
    if any(x in publisher for x in low):
        return "C"
    return "C"


def _title_direction_by_theme(title: str) -> str:
    """Infer directional hint from headline-level thematic cues."""
    # Generic negative first.
    if any(k in title for k in ["下跌", "失守", "违约", "下行", "延期", "失败", "走弱不及预期"]):
        return "利空"

    # Power-grid thematic cues.
    if any(k in title for k in ["电网", "特高压", "配网"]) and any(k in title for k in ["招标", "中标", "开工", "提速", "投资"]):
        return "利好"

    # Rare-earth thematic cues.
    if "稀土" in title and any(k in title for k in ["价格", "新高", "配额收紧", "出口管制", "供给偏紧"]):
        return "利好"

    # Commercial satellite thematic cues.
    if any(k in title for k in ["卫星", "商用卫星", "航天"]) and any(k in title for k in ["发射成功", "订单", "牌照", "组网推进"]):
        return "利好"
    if any(k in title for k in ["卫星", "商用卫星", "航天"]) and any(k in title for k in ["标准委成立", "标准委", "产业发展", "商业化推进", "组网进展"]):
        return "利好"
    if any(k in title for k in ["卫星", "商用卫星", "航天"]) and any(k in title for k in ["推迟", "延期", "发射失败"]):
        return "利空"

    # Macro/gold cues.
    if any(k in title for k in ["中证500", "流动性", "风险偏好", "估值"]) and any(k in title for k in ["修复", "改善", "回升", "走强"]):
        return "利好"
    if any(k in title for k in ["中证500", "流动性", "风险偏好", "估值"]) and any(k in title for k in ["收紧", "回落", "承压", "下行"]):
        return "利空"
    if any(k in title for k in ["新高", "加速", "高增", "流入", "中标", "走弱", "回落"]):
        return "利好"
    return "中性"


def _is_low_quality_news_title(title: str) -> bool:
    """Detect low-information or clickbait-style titles and downgrade them."""
    bad_markers = [
        "财富号",
        "Sohu",
        "手机新浪网",
        "涨停",
        "暴涨",
        "卖铲人",
        "大战",
        "终于等到",
        "无硝烟",
        "怎么分析",
        "为啥不灵",
    ]
    return any(k in title for k in bad_markers)


def load_example_documents(examples_dir: Path) -> List[RawDocument]:
    """Load markdown examples into raw document contracts."""
    rows: List[RawDocument] = []
    collected = _now_iso()
    for idx, path in enumerate(sorted(examples_dir.glob("*_case.md")), start=1):
        case = parse_case_markdown(path)
        raw_text = case.get("raw_text", "")
        published = case.get("published_at", "").strip() or _extract_date_from_text(raw_text)
        source = case.get("source_name", "").strip() or "examples"
        source_type = case.get("source_type", "").strip() or "search_seed"
        rows.append(
            RawDocument(
                doc_id=f"example-{idx:03d}",
                title=path.stem,
                source=source,
                source_type=source_type,
                published_at=published,
                collected_at=collected,
                content=raw_text,
                url=str(path),
            )
        )
    return rows


def load_source_documents(
    max_sources: int = 20,
    max_items_per_source: int = 3,
    max_list_links: int = 15,
    timeout: float = 10.0,
    strict_collect: bool = False,
    verbose_collect: bool = False,
    fund_codes: Sequence[str] | None = None,
) -> tuple[List[RawDocument], Dict[str, Any]]:
    """Collect docs from enabled source config and convert to raw contracts."""
    funds = load_fund_profiles()
    by_code = {str(f.get("code", "")): f for f in funds}
    target_funds = [by_code[c] for c in (fund_codes or []) if c in by_code] if fund_codes else funds

    categories = [str(f.get("type", "")) for f in target_funds]
    has_gold = "gold" in categories
    has_bond = "bond" in categories
    has_broad = "broad_equity" in categories
    has_thematic = "thematic_equity" in categories
    names = " ".join([str(f.get("name", "")) for f in target_funds])

    required_tags: List[str] = []
    if has_gold or "黄金" in names:
        required_tags.extend(["黄金", "gold"])
    if has_bond:
        required_tags.extend(["利率", "信用"])
    if has_broad:
        required_tags.extend(["宏观", "流动性"])
    if "稀土" in names:
        required_tags.extend(["稀土", "镨钕"])
    if "电网" in names:
        required_tags.extend(["电网", "特高压"])
    if "卫星" in names:
        required_tags.extend(["卫星", "商业航天"])
    required_tags = list(dict.fromkeys(required_tags))

    category_quotas: Dict[str, int] = {"authoritative_data": 2, "top_tier_media": 2}
    if has_thematic:
        category_quotas["top_tier_media"] = 3
    if has_gold or has_bond:
        category_quotas["authoritative_data"] = 3
    if has_gold and has_thematic:
        category_quotas["specialist_research"] = 1

    collected, stats = collect_documents_from_sources(
        max_sources=max_sources,
        max_items_per_source=max_items_per_source,
        max_list_links=max_list_links,
        timeout=timeout,
        strict=strict_collect,
        verbose=verbose_collect,
        category_quotas=category_quotas,
        required_tags=required_tags,
    )

    # Targeted free news feed to avoid homepage-only noise.
    fund_profiles = target_funds
    query_terms: List[str] = []
    rare_earth_queries: List[str] = []
    for f in fund_profiles:
        ftype = str(f.get("type", ""))
        fname = str(f.get("name", ""))
        if ftype == "gold":
            query_terms.extend(
                [
                    "黄金 美元指数 实际利率 when:7d",
                    "黄金 ETF 资金流 央行购金 when:7d",
                    "美联储 降息 预期 黄金 when:7d",
                    "COMEX 黄金 现货金 涨跌 when:14d",
                    "美国 实际利率 TIPS 黄金 定价 when:14d",
                    "央行 购金 黄金储备 变化 when:30d",
                    "central bank gold buying world gold council when:30d",
                ]
            )
        elif ftype == "bond":
            query_terms.extend(
                [
                    "国债收益率 公开市场操作 when:7d",
                    "信用利差 违约 债券 when:7d",
                    "同业存单 回购利率 资金面 when:14d",
                    "债券基金 申赎 久期 when:14d",
                ]
            )
        elif ftype == "broad_equity":
            query_terms.extend(
                [
                    "中证500 流动性 风格轮动 when:7d",
                    "风险偏好 宏观 修复 when:7d",
                    "社融 PMI 中证500 估值 when:14d",
                    "中证500 估值 修复 风险偏好 回升 when:14d",
                    "国家统计局 PMI 社融 宏观 数据 when:14d",
                ]
            )
        else:
            lead_sector = " ".join([str(x) for x in f.get("sectors", [])[:1]])
            if "电网" in lead_sector:
                query_terms.extend(
                    [
                        "电网 特高压 招标 中标 投资 when:7d",
                        "国家电网 配网 改造 项目 when:7d",
                        "南方电网 招标 中标 设备 when:14d",
                    ]
                )
            elif "稀土" in lead_sector:
                query_terms.extend(
                    [
                        "稀土 配额 价格 出口 管制 when:7d",
                        "工信部 稀土 指标 供给 when:7d",
                        "重稀土 价格 新高 产能 供给",
                    ]
                )
                rare_earth_queries.extend(
                    [
                        "稀土 永磁 价格 供给 需求 site:cs.com.cn when:30d",
                        "稀土 配额 总量控制 工信部 site:gov.cn when:30d",
                        "北方稀土 公告 订单 业绩 when:30d",
                        "中国稀土 公告 出口 供给 when:30d",
                        "重稀土 轻稀土 价差 产业链 when:30d",
                    ]
                )
            elif "卫星" in lead_sector:
                query_terms.extend(
                    [
                        "商用卫星 发射 订单 组网 when:7d",
                        "卫星通信 牌照 频轨 招标 when:7d",
                        "商业航天 卫星 发射 产业链",
                        "低轨卫星 星座 组网 进展 when:14d",
                        "卫星互联网 终端 订单 招标 when:14d",
                        "卫星互联网 标准委 成立 政策 推进 when:14d",
                        "国家航天局 商业航天 卫星 发射 when:14d",
                    ]
                )
            else:
                query_terms.extend([f"{lead_sector} 政策 招标 订单 when:7d", f"{lead_sector} 价格 供需 when:7d"])
    query_terms = [q for q in query_terms if q and len(q) >= 2]
    query_terms = list(dict.fromkeys(query_terms))[:20]
    news_docs = collect_google_news_documents(
        queries=query_terms,
        max_items_per_query=max(1, min(2, max_items_per_source)),
        timeout=timeout,
        verbose=verbose_collect,
    )
    collected.extend(news_docs)
    # Global macro supplement for bond/gold core variables (free RSS endpoint).
    global_queries = [
        "gold price real yields fed rate cut expectations",
        "US 10-year yield credit spread bond market",
        "dollar index gold ETF flows central bank gold buying",
    ]
    global_news_docs = collect_google_news_documents(
        queries=global_queries,
        max_items_per_query=max(1, min(2, max_items_per_source)),
        timeout=timeout,
        hl="en-US",
        gl="US",
        ceid="US:en",
        verbose=verbose_collect,
    )
    collected.extend(global_news_docs)
    market_docs = collect_market_variable_documents(timeout=timeout, verbose=verbose_collect)
    collected.extend(market_docs)
    satellite_proxy_docs = collect_satellite_price_proxy_documents(timeout=timeout, verbose=verbose_collect)
    collected.extend(satellite_proxy_docs)
    central_bank_gold_docs = collect_central_bank_gold_signal_documents(timeout=timeout, verbose=verbose_collect)
    collected.extend(central_bank_gold_docs)
    structured_theme_docs = collect_structured_theme_signal_documents(timeout=timeout, verbose=verbose_collect)
    collected.extend(structured_theme_docs)
    thematic_signal_docs = collect_thematic_industry_signal_documents(timeout=timeout, verbose=verbose_collect)
    collected.extend(thematic_signal_docs)
    if rare_earth_queries:
        rare_docs = collect_google_news_documents(
            queries=list(dict.fromkeys(rare_earth_queries))[:6],
            max_items_per_query=max(2, min(4, max_items_per_source + 1)),
            timeout=timeout,
            verbose=verbose_collect,
        )
        collected.extend(rare_docs)
    rows: List[RawDocument] = []
    collected_at = _now_iso()
    for idx, doc in enumerate(collected, start=1):
        rows.append(
            RawDocument(
                doc_id=f"source-{idx:03d}",
                title=doc.title,
                source=doc.source,
                source_type=doc.source_type,
                published_at=doc.published_at,
                collected_at=collected_at,
                content=doc.content,
                url=doc.url,
            )
        )
    stats_dict = stats.to_dict()
    stats_dict["source_required_tags"] = required_tags
    stats_dict["source_category_quotas"] = category_quotas
    stats_dict["google_news_docs"] = len(news_docs) + len(global_news_docs)
    stats_dict["market_variable_docs"] = len(market_docs)
    stats_dict["satellite_proxy_docs"] = len(satellite_proxy_docs)
    stats_dict["central_bank_gold_docs"] = len(central_bank_gold_docs)
    stats_dict["structured_theme_docs"] = len(structured_theme_docs)
    stats_dict["thematic_signal_docs"] = len(thematic_signal_docs)
    return rows, stats_dict


def parse_documents(raw_docs: Sequence[RawDocument]) -> List[ParsedDocument]:
    """Normalize raw docs into parsed docs with strict noise/chrome filtering."""
    out: List[ParsedDocument] = []
    for d in raw_docs:
        merged_text = f"{d.title}。{d.content}".strip()
        cleaned = clean_and_score_text(merged_text)
        out.append(
            ParsedDocument(
                doc_id=d.doc_id,
                title=d.title,
                source=d.source,
                source_type=d.source_type,
                published_at=d.published_at,
                collected_at=d.collected_at,
                content=merged_text,
                clean_text=str(cleaned.get("clean_text", "")),
                url=d.url,
                noise_lines_filtered=int(cleaned.get("noise_lines_filtered", 0)),
                chrome_lines_filtered=int(cleaned.get("chrome_lines_filtered", 0)),
                content_quality_score=float(cleaned.get("content_quality_score", 0.0)),
                extractable_event_score=float(cleaned.get("extractable_event_score", 0.0)),
                extractable_event_count=int(cleaned.get("extractable_event_count", 0)),
            )
        )
    return out


def _raw_event_priority(ev: Dict[str, Any]) -> float:
    score = 0.0
    if ev.get("date"):
        score += 0.6
    if ev.get("is_confirmed"):
        score += 0.5
    score += float(ev.get("event_strength", 0.0))
    if ev.get("short_term_direction") in {"利好", "利空"}:
        score += 0.2
    return score


def extract_events_from_docs(parsed_docs: Sequence[ParsedDocument], window_days: int) -> List[ExtractedEvent]:
    """Extract and enrich events with freshness and quality-required fields."""
    events: List[ExtractedEvent] = []

    for doc in parsed_docs:
        source_tier = _source_tier(doc.source_type)
        if doc.source == "Google News RSS":
            source_tier = _google_news_tier(doc.title)
        source_category = _source_category(doc.source_type)
        extracted = extract_events(doc.clean_text, title=doc.title, source_tier=source_tier)
        if len(extracted) > 3:
            extracted = sorted(extracted, key=_raw_event_priority, reverse=True)[:3]
        if not extracted and doc.source == "Google News RSS" and _news_title_relevant(doc.title):
            title = doc.title
            if any(k in title for k in ["中东", "地缘", "冲突", "避险"]) and "黄金" in title:
                title_direction = "利好"
            else:
                title_direction = _title_direction_by_theme(title)
            extracted = [
                {
                    "title": title,
                    "date": doc.published_at,
                    "event_type": "market_macro",
                    "event_subtype": "commentary",
                    "entities": [],
                    "summary": title,
                    "is_confirmed": True,
                    "evidence_tier": "B" if source_tier in {"A", "B"} else "C",
                    "short_term_direction": title_direction,
                    "event_strength": 0.85 if title_direction in {"利好", "利空"} else 0.65,
                }
            ]

        for i, ev in enumerate(extracted, start=1):
            event_date = ev.get("date", "") or _extract_date_from_text(doc.clean_text)
            published_at = doc.published_at or ""
            reference_date = event_date or published_at
            date_uncertain = not bool(event_date) and not bool(published_at)
            stale = is_stale_for_window(reference_date, window_days) if reference_date else True

            confidence = 0.75 if ev.get("is_confirmed") else 0.45
            title_low_quality = doc.source == "Google News RSS" and (
                _is_low_quality_news_title(doc.title) or _google_news_tier(doc.title) == "C"
            )
            if date_uncertain:
                confidence -= 0.25
            if doc.content_quality_score < 0.4:
                confidence -= 0.2
            if title_low_quality:
                confidence -= 0.2

            is_noise = (
                doc.extractable_event_count == 0
                and doc.extractable_event_score < 0.05
                and doc.content_quality_score < 0.6
            )
            if title_low_quality and doc.extractable_event_count == 0:
                is_noise = True
            is_page_chrome = doc.chrome_lines_filtered > 0 and doc.extractable_event_score == 0

            evidence_tier = str(ev.get("evidence_tier", "C"))
            if doc.source == "Google News RSS":
                evidence_tier = "B" if source_tier == "B" else "C"

            event = ExtractedEvent(
                event_id=f"{doc.doc_id}-ev-{i}",
                title=ev.get("title", doc.title),
                source=doc.source,
                source_type=doc.source_type,
                source_category=source_category,
                source_tier=source_tier,
                published_at=published_at,
                event_date=event_date,
                collected_at=doc.collected_at,
                freshness_bucket=freshness_bucket(reference_date),
                is_stale=stale,
                date_uncertain=date_uncertain,
                is_page_chrome=is_page_chrome,
                is_noise=is_noise,
                content_quality_score=doc.content_quality_score,
                extractable_event_score=doc.extractable_event_score,
                evidence_tier="C" if title_low_quality else evidence_tier,
                event_type=ev.get("event_type", "sentiment"),
                event_subtype=ev.get("event_subtype", "commentary"),
                entities=ev.get("entities", []),
                summary=ev.get("summary", ""),
                relevance=0.0,
                direction=ev.get("short_term_direction", "中性"),
                confidence=max(0.1, round(confidence, 4)),
                event_strength=float(ev.get("event_strength", 0.55)),
            )
            events.append(event)

    # Duplicate-event suppression: if same headline/date repeated, keep freshest and highest quality one only.
    dedup_map: Dict[str, ExtractedEvent] = {}
    for e in events:
        key = f"{title_key(e.title)}::{e.event_date or e.published_at}::{e.event_subtype}"
        e.duplicate_group = key
        old = dedup_map.get(key)
        if not old:
            dedup_map[key] = e
            continue
        better = e if (e.content_quality_score, e.collected_at) > (old.content_quality_score, old.collected_at) else old
        dedup_map[key] = better

    return list(dedup_map.values())


def _stale_penalty_config() -> Dict[str, float]:
    cfg = _scoring_config()
    return cfg.get("stale_penalty", {"older_than_window": 0.6, "date_uncertain": 0.7, "community_unconfirmed": 0.75})


def _evidence_mode_weight_config() -> Dict[str, float]:
    cfg = _scoring_config()
    return cfg.get("evidence_mode_weight", {"direct": 1.0, "proxy": 0.78})


def _feedback_horizon_from_bucket(freshness_bucket_name: str) -> str:
    fb = (freshness_bucket_name or "").strip()
    if fb == "within_3d":
        return "3d"
    if fb in {"within_7d", "within_14d"}:
        return "2w"
    return "3m"


def _source_feedback_prior_multiplier(source_tier: str = "", source_category: str = "", source_name: str = "") -> float:
    cfg = _scoring_config().get("source_feedback", {})
    by_name = cfg.get("prior_multiplier_by_source_name", {})
    if isinstance(by_name, dict) and source_name in by_name:
        return float(by_name.get(source_name, 1.0))
    by_tier = cfg.get("prior_multiplier_by_source_tier", {})
    if isinstance(by_tier, dict) and source_tier in by_tier:
        return float(by_tier.get(source_tier, 1.0))
    by_cat = cfg.get("prior_multiplier_by_source_category", {})
    if isinstance(by_cat, dict) and source_category in by_cat:
        return float(by_cat.get(source_category, 1.0))
    return float(cfg.get("prior_multiplier_default", 1.0))


def _blend_prior_posterior(prior: float, posterior: float) -> float:
    cfg = _scoring_config().get("source_feedback", {})
    w = float(cfg.get("posterior_blend_weight", 0.65))
    w = max(0.0, min(1.0, w))
    return prior * (1.0 - w) + posterior * w


def _source_feedback_multiplier(
    source_name: str,
    fund_type: str = "",
    feedback_horizon: str = "",
    source_tier: str = "",
    source_category: str = "",
) -> float:
    """Runtime multiplier from realized source-performance feedback."""
    cfg = _scoring_config().get("source_feedback", {})
    if not bool(cfg.get("enabled", False)):
        return 1.0
    prior = _source_feedback_prior_multiplier(source_tier=source_tier, source_category=source_category, source_name=source_name)
    prior_only = bool(cfg.get("use_prior_only", False))
    if prior_only:
        lo = float(cfg.get("min_multiplier", 0.85))
        hi = float(cfg.get("max_multiplier", 1.15))
        return max(lo, min(hi, prior))
    by_ft_hz = cfg.get("source_multiplier_by_fund_type_horizon", {})
    if isinstance(by_ft_hz, dict):
        ft_map = by_ft_hz.get(str(fund_type), {})
        if isinstance(ft_map, dict):
            hz_map = ft_map.get(str(feedback_horizon), {})
            if isinstance(hz_map, dict) and source_name in hz_map:
                raw = _blend_prior_posterior(prior, float(hz_map.get(source_name, 1.0)))
                lo = float(cfg.get("min_multiplier", 0.85))
                hi = float(cfg.get("max_multiplier", 1.15))
                return max(lo, min(hi, raw))
    by_ft = cfg.get("source_multiplier_by_fund_type", {})
    mapping = {}
    if isinstance(by_ft, dict):
        ft_map = by_ft.get(str(fund_type), {})
        if isinstance(ft_map, dict):
            mapping = ft_map
    if not mapping:
        by_hz = cfg.get("source_multiplier_by_horizon", {})
        if isinstance(by_hz, dict):
            hz_map = by_hz.get(str(feedback_horizon), {})
            if isinstance(hz_map, dict):
                mapping = hz_map
    if not mapping:
        fallback = cfg.get("source_multiplier_by_name", {})
        if isinstance(fallback, dict):
            mapping = fallback
    posterior = float(mapping.get(source_name, 1.0)) if isinstance(mapping, dict) else 1.0
    raw = _blend_prior_posterior(prior, posterior)
    lo = float(cfg.get("min_multiplier", 0.85))
    hi = float(cfg.get("max_multiplier", 1.15))
    return max(lo, min(hi, raw))


def _proxy_controls_for_fund(fund_type: str, fund_code: str = "") -> Dict[str, float]:
    cfg = _scoring_config()
    base = cfg.get(
        "proxy_controls",
        {
            "confidence_multiplier": 0.9,
            "max_proxy_share_in_main": 0.6,
            "auto_downgrade_strength_when_proxy_dominant": True,
            "downgrade_steps": 1,
        },
    )
    by_type = cfg.get("proxy_controls_by_fund_type", {})
    override = by_type.get(fund_type, {})
    by_code = cfg.get("proxy_controls_by_fund_code", {})
    code_override = by_code.get(str(fund_code), {})
    merged = dict(base)
    merged.update(override)
    merged.update(code_override)
    return merged


def _source_to_level(source_type: str) -> str:
    mapping = {
        "official_site": "official",
        "exchange_notice": "exchange",
        "fund_company": "fund_company",
        "listed_company": "listed_company",
        "media": "mainstream_media",
        "industry_media": "industry_media",
        "rss": "mainstream_media",
        "community_forum": "community_forum",
        "self_media": "self_media",
        "search_seed": "other",
    }
    return mapping.get(source_type, "other")


def _theme_tokens(fund: Dict[str, Any]) -> List[str]:
    name = str(fund.get("name", ""))
    sectors = " ".join(str(x) for x in fund.get("sectors", []))
    if "稀土" in name or "稀土" in sectors:
        return ["稀土", "重稀土", "轻稀土", "永磁", "配额", "出口管制", "氧化镨钕", "冶炼", "开采"]
    if "电网" in name or "电网" in sectors:
        return ["电网", "特高压", "配网", "招标", "中标", "电网投资", "国网", "南网", "变压器"]
    if "卫星" in name or "卫星" in sectors:
        return [
            "卫星",
            "商业航天",
            "商用卫星",
            "发射",
            "星座",
            "组网",
            "频轨",
            "卫星通信",
            "遥感",
            "卫星互联网",
            "标准委",
            "低轨",
            "终端",
            "商业化",
            "应用落地",
            "订单",
        ]
    return [str(x) for x in fund.get("sectors", []) if str(x)]


def _pass_fund_type_gate(event_text: str, fund: Dict[str, Any]) -> bool:
    """Hard gate to prevent cross-type mis-mapping from noisy headlines."""
    text = event_text.lower()
    ftype = str(fund.get("type", ""))

    if ftype == "gold":
        gold_primary = ["黄金", "现货金", "comex", "gold"]
        macro_secondary = ["美元", "美元指数", "实际利率", "美联储", "央行购金", "黄金etf", "gold etf"]
        # Gold fund mapping must be anchored by explicit gold context.
        if "央行购金" in text or "黄金储备" in text or "地缘避险趋势" in text:
            return True
        return any(k in text for k in gold_primary) and (
            any(k in text for k in macro_secondary) or any(k in text for k in ["上涨", "下跌", "新高", "回落", "上行", "下行"])
        )

    if ftype == "bond":
        must = ["国债", "债市", "信用利差", "收益率", "票息", "回购利率", "同业存单", "信用债", "城投债", "违约"]
        return any(k in text for k in must)

    if ftype == "broad_equity":
        if "宽基风险偏好趋势" in text:
            return True
        must = ["中证500", "a股", "风格", "风险偏好", "流动性", "估值", "pmi", "社融", "宏观"]
        return any(k in text for k in must)

    if ftype == "thematic_equity":
        return any(t.lower() in text for t in _theme_tokens(fund))

    return True


def _fund_specific_direction(fund_type: str, text_input: str, default_direction: str) -> str:
    text = text_input.lower()
    if fund_type == "bond":
        if (
            ("收益率" in text and any(k in text for k in ["上行", "走高", "抬升"]))
            or any(k in text for k in ["信用利差走阔", "违约", "流动性收紧", "加息", "申赎压力上升", "净流出"])
        ):
            return "利空"
        if (
            ("收益率" in text and any(k in text for k in ["下行", "走低", "回落"]))
            or any(k in text for k in ["信用利差收窄", "降息", "流动性改善", "回购利率下行", "申赎压力缓解", "净流入"])
        ):
            return "利好"
        return default_direction

    if fund_type == "gold":
        if (
            any(k in text for k in ["金价上涨", "黄金上涨", "comex上涨", "美元走弱", "实际利率下行", "央行购金增加", "避险升温"])
            or ("央行购金趋势" in text and "偏强" in text)
            or ("地缘避险趋势" in text and "上行" in text)
            or ("美元指数" in text and any(k in text for k in ["下行", "走弱", "回落"]))
            or ("黄金etf" in text and any(k in text for k in ["上行", "净流入", "增持"]))
            or ("资金活跃度改善" in text)
            or ("收益率" in text and any(k in text for k in ["下行", "走低", "回落"]))
        ):
            return "利好"
        if (
            any(k in text for k in ["金价下跌", "黄金回落", "美元走强", "实际利率上行", "购金减少", "避险降温"])
            or ("央行购金趋势" in text and "偏弱" in text)
            or ("地缘避险趋势" in text and "回落" in text)
            or ("美元指数" in text and any(k in text for k in ["上行", "走强", "抬升"]))
            or ("黄金etf" in text and any(k in text for k in ["下行", "净流出", "减持"]))
            or ("净流出压力上升" in text)
            or ("收益率" in text and any(k in text for k in ["上行", "走高", "抬升"]))
        ):
            return "利空"
        return default_direction

    if fund_type == "broad_equity":
        if any(
            k in text
            for k in [
                "风险偏好回升",
                "流动性改善",
                "估值修复",
                "风格回归中小盘",
                "双轮驱动",
                "宏观修复",
                "社融回升",
                "pmi回升",
                "宽基风险偏好趋势",
                "趋势偏强",
            ]
        ):
            return "利好"
        if any(k in text for k in ["风险偏好回落", "流动性收紧", "估值承压", "社融回落", "pmi回落", "趋势偏弱"]):
            return "利空"
        return default_direction

    if fund_type == "thematic_equity":
        if any(
            k in text
            for k in [
                "趋势偏强",
                "价格新高",
                "供给偏紧",
                "中标",
                "开工提速",
                "组网推进",
                "订单落地",
                "配额",
                "总量控制",
                "需求回暖",
                "商业化推进",
                "交付提速",
                "出货增长",
                "供需改善",
            ]
        ):
            return "利好"
        if any(
            k in text
            for k in [
                "趋势偏弱",
                "价格回落",
                "供给过剩",
                "延期",
                "发射失败",
                "订单取消",
                "需求下滑",
                "走弱",
                "商业化受阻",
                "交付延后",
                "供需失衡",
            ]
        ):
            return "利空"
        return default_direction

    return default_direction


def _variable_evidence_meta(event_title: str, source: str, source_type: str) -> tuple[str, str]:
    """Classify whether a signal is direct variable evidence or proxy evidence."""
    t = (event_title or "").lower()
    s = (source or "").lower()
    st = (source_type or "").lower()
    proxy_markers = ["代理", "proxy", "篮子", "hyg-ief", "tip", "gld", "vix"]
    if any(k in t for k in proxy_markers) or any(k in s for k in ["yahoo finance api"]) or (st == "media" and "周度变化快照" in event_title and any(k in event_title for k in ["代理", "篮子"])):
        return ("proxy", "代理变量证据：用于跟踪核心变量方向，非产业一手现货/公告数据")
    return ("direct", "直接变量证据：来自可验证事件或核心变量原始披露")


def map_events_to_funds(events: Sequence[ExtractedEvent], fund_codes: Sequence[str] | None = None, window_days: int = 7) -> List[FundSignal]:
    """Map events into fund signals with strict source-tier and freshness gating."""
    funds = load_fund_profiles()
    by_code = {f.get("code"): f for f in funds}
    target_funds = [by_code[c] for c in fund_codes if c in by_code] if fund_codes else funds
    penalties = _stale_penalty_config()
    evidence_mode_weight = _evidence_mode_weight_config()
    relevance_cfg = _scoring_config().get("relevance_thresholds", {})
    min_relevance = float(relevance_cfg.get("ignore_below", 0.25))

    out: List[FundSignal] = []
    for ev in events:
        ev_text = f"{ev.title} {ev.summary}"

        for fund in target_funds:
            if not _pass_fund_type_gate(ev_text, fund):
                continue
            relevance = calc_relevance(ev_text, fund)
            if relevance < min_relevance:
                continue
            fund_type = str(fund.get("type", ""))
            fund_code = str(fund.get("code", ""))
            proxy_controls = _proxy_controls_for_fund(fund_type, fund_code)
            directional_view = _fund_specific_direction(fund_type, f"{ev.title} {ev.summary}", ev.direction)

            payload = {
                "source_level": _source_to_level(ev.source_type),
                "date": ev.event_date or ev.published_at,
                "is_confirmed": ev.confidence >= 0.6,
                "short_term_direction": directional_view,
                "confidence": ev.confidence,
                "event_strength": ev.event_strength,
            }
            base_score = score_event(payload, relevance, horizon="2w")

            include_in_main = True
            evidence_class = "event_evidence"
            gated_reason = ""
            adjusted_score = base_score
            min_main_score = 0.04

            if ev.is_page_chrome:
                include_in_main = False
                evidence_class = "discarded"
                gated_reason = "is_page_chrome=true"
                adjusted_score = 0.0
            elif ev.is_noise:
                include_in_main = False
                evidence_class = "discarded"
                gated_reason = "is_noise=true"
                adjusted_score = 0.0
            elif ev.source_tier in {"C", "D"}:
                include_in_main = False
                evidence_class = "auxiliary_evidence" if ev.source_tier == "C" else "sentiment_only"
                gated_reason = f"source_tier={ev.source_tier}"
            elif ev.evidence_tier == "C":
                include_in_main = False
                evidence_class = "auxiliary_evidence"
                gated_reason = "evidence_tier=C"

            if ev.is_stale:
                include_in_main = False
                evidence_class = "background_evidence"
                gated_reason = "stale_event"
                adjusted_score *= penalties.get("older_than_window", 0.6)
            if ev.date_uncertain:
                adjusted_score *= penalties.get("date_uncertain", 0.7)
                if window_days <= 14 and not (ev.published_at and not ev.is_stale):
                    include_in_main = False
                    evidence_class = "background_evidence"
                    gated_reason = "date_uncertain"

            if ev.source_tier == "D" and ev.confidence < 0.6:
                adjusted_score *= penalties.get("community_unconfirmed", 0.75)
            evidence_type, evidence_note = _variable_evidence_meta(ev.title, ev.source, ev.source_type)
            if evidence_type == "proxy":
                adjusted_score *= float(evidence_mode_weight.get("proxy", 0.78))
            if ev.source_tier in {"A", "B"}:
                feedback_horizon = _feedback_horizon_from_bucket(ev.freshness_bucket)
                adjusted_score *= _source_feedback_multiplier(
                    ev.source,
                    fund_type=fund_type,
                    feedback_horizon=feedback_horizon,
                    source_tier=ev.source_tier,
                    source_category=ev.source_category,
                )
            if include_in_main and abs(adjusted_score) < min_main_score:
                include_in_main = False
                evidence_class = "auxiliary_evidence"
                gated_reason = "weak_score"
            signal_confidence = ev.confidence
            if evidence_type == "proxy":
                signal_confidence = round(ev.confidence * float(proxy_controls.get("confidence_multiplier", 0.9)), 4)

            out.append(
                FundSignal(
                    fund_code=fund.get("code", ""),
                    fund_name=fund.get("name", ""),
                    fund_type=fund.get("type", ""),
                    event_id=ev.event_id,
                    event_title=ev.title,
                    source=ev.source,
                    source_type=ev.source_type,
                    source_category=ev.source_category,
                    source_tier=ev.source_tier,
                    evidence_tier=ev.evidence_tier,
                    published_at=ev.published_at,
                    event_date=ev.event_date,
                    collected_at=ev.collected_at,
                    freshness_bucket=ev.freshness_bucket,
                    is_stale=ev.is_stale,
                    date_uncertain=ev.date_uncertain,
                    relevance=round(relevance, 4),
                    direction=directional_view,
                    confidence=signal_confidence,
                    score=round(adjusted_score, 6),
                    include_in_main=include_in_main,
                    evidence_class=evidence_class,
                    gated_reason=gated_reason,
                    variable_evidence_type=evidence_type,
                    variable_evidence_note=evidence_note,
                    logic_chain=build_impact_chain(str(fund.get("type", "")), ev.title),
                    counter_evidence=["该事件可能只影响行业情绪，未必传导到基金核心驱动"],
                )
            )
    return out


def _conclusion_strength(confidence: float, recent_event_count: int) -> str:
    if confidence >= 0.72 and recent_event_count >= 3:
        return "高"
    if confidence >= 0.55 and recent_event_count >= 1:
        return "中"
    return "低"


def _downgrade_conclusion_strength(strength: str, steps: int = 1) -> str:
    order = ["高", "中", "低"]
    if strength not in order:
        return strength
    idx = order.index(strength)
    idx = min(len(order) - 1, idx + max(0, steps))
    return order[idx]


def _decision_controls() -> Dict[str, Any]:
    cfg = _scoring_config()
    return cfg.get(
        "decision_controls",
        {
            "min_direct_main_by_fund_type": {"thematic_equity": 1, "broad_equity": 0, "bond": 1, "gold": 1},
            "enforce_neutral_when_below_direct_min": True,
            "enforce_on_horizons": ["3d", "2w"],
            "single_source_requires_direct_for_actionable": True,
        },
    )


def _decision_readiness(strength: str, constraints: Sequence[str]) -> str:
    severe = {
        "single_source_main_evidence",
        "no_direct_confirmation",
        "proxy_dominant",
        "insufficient_recent_ab_evidence",
        "below_direct_evidence_min",
    }
    moderate = {
        "low_source_diversity",
        "limited_recent_signal_count",
        "conflicted_fresh_signals",
        "date_uncertain_present",
    }
    hits = set(constraints)
    if strength == "低" or hits & severe:
        return "低"
    if strength == "中" or hits & moderate:
        return "中"
    return "高"


def _driver_template(fund_type: str) -> Dict[str, str]:
    if fund_type == "thematic_equity":
        return {"政策": "证据不足", "景气": "证据不足", "价格": "证据不足", "订单": "证据不足", "供需": "证据不足"}
    if fund_type == "broad_equity":
        return {"流动性": "证据不足", "风格": "证据不足", "风险偏好": "证据不足", "宏观": "证据不足"}
    if fund_type == "bond":
        return {"利率": "证据不足", "信用利差": "证据不足", "供需": "证据不足", "申赎": "证据不足"}
    if fund_type == "gold":
        return {
            "金价": "证据不足",
            "美元": "证据不足",
            "实际利率": "证据不足",
            "避险": "证据不足",
            "央行购金": "证据不足",
            "ETF流向": "证据不足",
        }
    return {"核心变量": "证据不足"}


def _mark_driver_checks(fund_type: str, events: Sequence[FundSignal]) -> Dict[str, str]:
    checks = _driver_template(fund_type)
    # Use observed event text only; avoid auto-generated chain text inflating coverage.
    text = " ".join(e.event_title for e in events)

    keyword_map = {
        "政策": ["政策", "部委", "核准", "配额", "总量控制", "标准委", "牌照", "指引", "规划", "出口管制"],
        "景气": ["景气", "同比", "需求", "出货", "高增", "增长", "修复", "永磁需求", "下游需求", "商业化推进", "应用落地", "开工率", "排产"],
        "价格": ["价格", "涨价", "跌价", "新高", "回落", "上行", "下行", "氧化镨钕", "重稀土", "成本", "毛利", "提价", "降本增效"],
        "订单": ["订单", "招标", "中标", "签约", "开工", "终端订单", "交付", "应用订单", "排产", "交付提速"],
        "供需": ["供给", "供需", "库存", "产能", "供给收紧", "交付节奏", "供需改善", "供需失衡"],
        "流动性": ["流动性", "降息", "加息", "回购", "社融", "资金面"],
        "风格": ["风格", "估值", "中小盘", "成长", "价值"],
        "风险偏好": ["风险偏好", "避险", "波动", "风险评价", "宽基风险偏好趋势", "趋势偏强", "趋势偏弱"],
        "宏观": ["宏观", "GDP", "PMI", "通胀", "经济修复", "财政"],
        "利率": ["利率", "收益率", "国债", "同业存单", "回购利率"],
        "信用利差": ["信用利差", "违约", "信用", "信用债", "城投债"],
        "申赎": ["赎回", "申购", "久期", "净申购", "净赎回", "申赎压力", "净流出", "净流入"],
        "金价": ["黄金", "COMEX", "现货金", "金价"],
        "美元": ["美元", "美元指数"],
        "实际利率": ["实际利率", "名义利率"],
        "避险": ["地缘", "避险", "地缘避险趋势", "风险升温", "缓和信号"],
        "央行购金": ["央行购金", "购金"],
        "ETF流向": ["ETF", "资金流", "持仓变化", "净流入", "净流出", "成交量放大", "活跃度", "增持", "减持"],
    }

    for k in checks:
        if any(word in text for word in keyword_map.get(k, [])):
            checks[k] = "有覆盖"
    return checks


def _score_to_logic(score: float, low_event_count: bool) -> str:
    if low_event_count:
        return "暂无足够证据判断"
    if score > 0.12:
        return "强化"
    if score < -0.12:
        return "弱化"
    return "不变"


def _watch_points_by_type(fund_type: str) -> List[str]:
    if fund_type == "thematic_equity":
        return ["关注未来7天政策/招标/订单是否新增A/B级事件", "若仅有转载与评论，维持中性/待观察"]
    if fund_type == "broad_equity":
        return ["关注流动性与风险偏好变量是否同向改善", "关注PMI/社融等宏观确认信号"]
    if fund_type == "bond":
        return ["关注收益率方向与信用利差是否同向收敛", "关注资金面与申赎压力是否恶化"]
    if fund_type == "gold":
        return ["关注金价-美元-实际利率三变量是否形成同向链条", "关注央行购金与黄金ETF资金流是否持续"]
    return ["关注未来7天是否出现A/B级新增证据", "若仅有C/D级来源，维持中性/待观察"]


def aggregate_reports(signals: Sequence[FundSignal], window_days: int, fund_codes: Sequence[str] | None = None) -> List[FundReport]:
    """Aggregate fund reports with strict gating and cautious conclusion policy."""
    grouped: Dict[str, List[FundSignal]] = defaultdict(list)
    for s in signals:
        grouped[s.fund_code].append(s)

    funds = {f.get("code"): f for f in load_fund_profiles()}
    if fund_codes:
        wanted = set(fund_codes)
        funds = {k: v for k, v in funds.items() if k in wanted}
    reports: List[FundReport] = []
    for code, fund in funds.items():
        items = grouped.get(code, [])
        fresh_main = [x for x in items if x.include_in_main]
        fresh_3d = [x for x in fresh_main if (age_days(x.event_date or x.published_at) is not None and age_days(x.event_date or x.published_at) <= 3)]
        fresh_2w = [x for x in fresh_main if (age_days(x.event_date or x.published_at) is not None and age_days(x.event_date or x.published_at) <= 14)]
        fresh_3m = [x for x in fresh_main if (age_days(x.event_date or x.published_at) is not None and age_days(x.event_date or x.published_at) <= 90)]
        background_ab = [
            x
            for x in items
            if (not x.include_in_main)
            and x.evidence_class == "background_evidence"
            and x.source_tier in {"A", "B"}
            and not x.date_uncertain
        ]
        stale_filtered = [x for x in items if x.gated_reason in {"stale_event", "date_uncertain"}]
        noise_filtered = [x for x in items if x.gated_reason in {"is_noise=true", "is_page_chrome=true"}]
        low_tier_filtered = [x for x in items if x.gated_reason.startswith("source_tier=") or x.gated_reason == "evidence_tier=C"]
        auxiliary_ab = [
            x
            for x in items
            if (not x.include_in_main)
            and x.evidence_class == "auxiliary_evidence"
            and x.source_tier in {"A", "B"}
            and not x.is_stale
            and not x.date_uncertain
        ]

        # Clamp individual signals to [-0.25, 0.25] to prevent single-event domination
        def _clamp(s: float) -> float:
            return max(-0.25, min(0.25, s))

        net_2w = sum(_clamp(x.score) for x in fresh_2w)
        net_3d = sum(_clamp(x.score) for x in fresh_3d) * float(
            _scoring_config().get("horizon_adjustments", {}).get("3d", {}).get("freshness_multiplier", 1.2)
        )
        net_3m = (
            sum(_clamp(x.score) for x in fresh_3m)
            * float(_scoring_config().get("horizon_adjustments", {}).get("3m", {}).get("freshness_multiplier", 0.8))
            + 0.35 * sum(_clamp(x.score) for x in background_ab)
        )

        # Momentum bonus: consistent direction in last 7 days amplifies net_2w by 15%
        fresh_7d = [x for x in fresh_main if (age_days(x.event_date or x.published_at) is not None and age_days(x.event_date or x.published_at) <= 7)]
        if len(fresh_7d) >= 2:
            pos_7d = sum(1 for x in fresh_7d if x.score > 0)
            neg_7d = sum(1 for x in fresh_7d if x.score < 0)
            if pos_7d >= 2 and neg_7d == 0 and net_2w > 0:
                net_2w *= 1.15
            elif neg_7d >= 2 and pos_7d == 0 and net_2w < 0:
                net_2w *= 1.15

        direction_2w = score_to_label(net_2w)
        direction_3d = score_to_label(net_3d)
        # 3m uses slightly lower trigger to reflect medium-term accumulation.
        if net_3m >= 0.06:
            direction_3m = "利好"
        elif net_3m <= -0.06:
            direction_3m = "利空"
        else:
            direction_3m = "中性"
        # Rare-earth thematic override: multiple consistent A/B background signals
        # can support medium-term bias, but fresh bearish A/B signal suppresses forced bullish override.
        if "稀土" in str(fund.get("name", "")):
            bg_pos = [x for x in background_ab if x.score > 0 and x.evidence_tier in {"A", "B"}]
            bg_neg = [x for x in background_ab if x.score < 0 and x.evidence_tier in {"A", "B"}]
            fresh_neg = [x for x in fresh_2w if x.score < 0 and x.evidence_tier in {"A", "B"}]
            if len(bg_pos) >= 2 and len(bg_neg) == 0 and not fresh_neg:
                direction_3m = "利好"
            elif len(bg_pos) >= 1 and len(bg_neg) == 0 and not fresh_neg and any((age_days(x.event_date or x.published_at) or 999) <= 30 for x in bg_pos):
                direction_3m = "利好"

        warnings: List[str] = []
        decision_constraints: List[str] = []
        proxy_controls = _proxy_controls_for_fund(str(fund.get("type", "")), str(code))
        proxy_count = 0
        proxy_share = 0.0
        direct_count = 0
        source_diversity_main = 0
        # Avoid over-conservative "always neutral" when there is one strong fresh A/B signal.
        single_signal_min = 0.08
        pos_count = sum(1 for x in fresh_2w if x.score > 0)
        neg_count = sum(1 for x in fresh_2w if x.score < 0)
        conflict_in_fresh = pos_count > 0 and neg_count > 0
        if len(fresh_2w) == 0:
            decision_constraints.append("insufficient_recent_ab_evidence")
            direction_3d = "中性"
            direction_2w = "中性"
            if len(background_ab) > 0 and abs(net_3m) >= 0.06:
                if net_3m > 0:
                    warnings.append("短期新增A/B级催化不足，但中期背景证据链偏利好")
                else:
                    warnings.append("短期新增A/B级催化不足，但中期背景证据链偏利空")
            else:
                warnings.append("近期高质量新增事件不足，结论以中性/待观察为主")
                warnings.append("近期未识别到高质量新增催化")
                if len(background_ab) > 0:
                    warnings.append("存在A/B级背景证据，已用于3个月逻辑复核")
        elif len(fresh_2w) == 1 and abs(net_2w) < single_signal_min:
            decision_constraints.append("limited_recent_signal_count")
            warnings.append("有效证据仅1条且强度有限，结论以中性/待观察为主")
            direction_3d = "中性"
            direction_2w = "中性"
        elif conflict_in_fresh and direction_2w == "中性":
            decision_constraints.append("conflicted_fresh_signals")
            warnings.append("近期高质量证据多空并存，方向性不足")
        if fresh_2w:
            proxy_count = sum(1 for x in fresh_2w if x.variable_evidence_type == "proxy")
            direct_count = sum(1 for x in fresh_2w if x.variable_evidence_type != "proxy")
            proxy_share = proxy_count / max(1, len(fresh_2w))
            source_diversity_main = len({x.source for x in fresh_2w})
            if proxy_share > float(proxy_controls.get("max_proxy_share_in_main", 0.6)):
                decision_constraints.append("proxy_dominant")
                warnings.append("短期主结论中代理变量占比较高，建议结合直接证据复核")
            if direct_count == 0:
                decision_constraints.append("no_direct_confirmation")
                warnings.append("主结论缺少直接证据确认，更适合做风向参考，不宜直接拍板")
            if source_diversity_main <= 1 and len(fresh_2w) >= 1:
                decision_constraints.append("single_source_main_evidence")
                warnings.append("主结论主要来自单一来源，需防止单源偏差")
            elif source_diversity_main == 2:
                decision_constraints.append("low_source_diversity")
                warnings.append("主结论来源多样性一般，建议结合更多来源复核")
        if any(x.date_uncertain for x in fresh_2w):
            decision_constraints.append("date_uncertain_present")
            warnings.append("部分事件日期不确定，已降级处理")

        # Confidence: A/B source share is the primary driver, then fresh signal count and net score magnitude
        ab_share = sum(1 for x in fresh_2w if x.evidence_tier in {"A", "B"}) / max(1, len(fresh_2w))
        direct_share = (direct_count / max(1, len(fresh_2w))) if fresh_2w else 0.0
        diversity_score = min(1.0, source_diversity_main / 3.0) if fresh_2w else 0.0
        confidence = round(
            min(
                0.9,
                0.18
                + 0.28 * ab_share
                + 0.18 * min(1.0, len(fresh_2w) / 4.0)
                + 0.12 * min(1.0, abs(net_2w) / 0.2)
                + 0.14 * direct_share
                + 0.10 * diversity_score,
            ),
            4,
        )
        conclusion_strength = _conclusion_strength(confidence, len(fresh_2w))
        proxy_downgraded = False
        if (
            proxy_share > float(proxy_controls.get("max_proxy_share_in_main", 0.6))
            and bool(proxy_controls.get("auto_downgrade_strength_when_proxy_dominant", True))
        ):
            steps = int(proxy_controls.get("downgrade_steps", 1))
            downgraded_strength = _downgrade_conclusion_strength(conclusion_strength, steps=steps)
            if downgraded_strength != conclusion_strength:
                conclusion_strength = downgraded_strength
                proxy_downgraded = True
                warnings.append("代理变量占比较高，结论强度已自动下调")

        decision_controls = _decision_controls()
        min_direct_required = int(decision_controls.get("min_direct_main_by_fund_type", {}).get(str(fund.get("type", "")), 0))
        enforce_neutral = bool(decision_controls.get("enforce_neutral_when_below_direct_min", True))
        enforce_horizons = set(decision_controls.get("enforce_on_horizons", ["3d", "2w"]))
        if direct_count < min_direct_required and len(fresh_2w) > 0:
            decision_constraints.append("below_direct_evidence_min")
            warnings.append("主结论直接证据数量不足，短中期判断按保守口径处理")
            if enforce_neutral:
                if "3d" in enforce_horizons:
                    direction_3d = "中性"
                if "2w" in enforce_horizons:
                    direction_2w = "中性"
        if direct_count == 0 and conclusion_strength != "低":
            conclusion_strength = _downgrade_conclusion_strength(conclusion_strength, steps=1)
        if source_diversity_main <= 1 and conclusion_strength == "高":
            conclusion_strength = _downgrade_conclusion_strength(conclusion_strength, steps=1)
        if source_diversity_main <= 1 and direct_count < max(1, min_direct_required):
            conclusion_strength = _downgrade_conclusion_strength(conclusion_strength, steps=1)
        decision_readiness = _decision_readiness(conclusion_strength, decision_constraints)

        top_events = sorted(fresh_2w, key=lambda i: abs(i.score), reverse=True)[:3]
        key_events = [
            {
                "title": x.event_title,
                "date": x.event_date or x.published_at,
                "source": x.source,
                "why_important": "事件直接作用于基金核心驱动变量",
                "evidence_mode": x.variable_evidence_type,
                "evidence_mode_note": x.variable_evidence_note,
                "impact_chain": x.logic_chain,
                "evidence_tier": x.evidence_tier,
            }
            for x in top_events
        ]
        if not key_events and background_ab:
            key_events = [
                {
                    "title": x.event_title,
                    "date": x.event_date or x.published_at,
                    "source": x.source,
                    "why_important": "中期背景证据（不计入短期主结论）",
                    "evidence_mode": x.variable_evidence_type,
                    "evidence_mode_note": x.variable_evidence_note,
                    "impact_chain": x.logic_chain,
                    "evidence_tier": x.evidence_tier,
                }
                for x in sorted([b for b in background_ab if b.evidence_tier in {"A", "B"}], key=lambda i: abs(i.score), reverse=True)[:3]
            ]

        downgraded_events = [
            {
                "title": x.event_title,
                "reason": x.gated_reason or x.evidence_class,
                "source_tier": x.source_tier,
            }
            for x in items
            if not x.include_in_main
        ][:8]

        driver_basis = (fresh_2w + auxiliary_ab) if (fresh_2w or auxiliary_ab) else background_ab
        core_driver_check = _mark_driver_checks(str(fund.get("type", "")), driver_basis)

        if conflict_in_fresh and direction_2w == "中性":
            counter_evidence = ["当前窗口内多空证据并存，净方向性不足"]
        elif net_2w >= 0:
            counter_evidence = [x.event_title for x in sorted(fresh_2w, key=lambda i: i.score)[:2] if x.score < 0]
        else:
            counter_evidence = [x.event_title for x in sorted(fresh_2w, key=lambda i: i.score, reverse=True)[:2] if x.score > 0]
        if not counter_evidence:
            counter_evidence = ["当前窗口内缺少可验证反向高质量事件"]

        long_term_logic = _score_to_logic(net_3m, low_event_count=(len(fresh_3m) < 2 and len(background_ab) < 2))
        if "稀土" in str(fund.get("name", "")):
            bg_pos = [x for x in background_ab if x.score > 0 and x.evidence_tier in {"A", "B"}]
            bg_neg = [x for x in background_ab if x.score < 0 and x.evidence_tier in {"A", "B"}]
            fresh_neg = [x for x in fresh_2w if x.score < 0 and x.evidence_tier in {"A", "B"}]
            if len(bg_pos) >= 2 and len(bg_neg) == 0 and not fresh_neg:
                long_term_logic = "强化"
            elif len(bg_pos) >= 1 and len(bg_neg) == 0 and not fresh_neg and long_term_logic == "暂无足够证据判断":
                long_term_logic = "不变"
            elif fresh_neg and long_term_logic == "强化":
                long_term_logic = "不变"
        has_actionable_chain = len(fresh_2w) >= 2 or (len(fresh_2w) == 1 and abs(net_2w) >= single_signal_min)
        if "below_direct_evidence_min" in decision_constraints and direction_3m in {"利好", "利空"}:
            one_liner_prefix = "短中期直接证据不足，当前更适合把方向判断视为观察结论"
        else:
            one_liner_prefix = ""

        if direction_2w == "中性" and direction_3m in {"利好", "利空"}:
            short_desc = f"近3日偏{direction_3d}" if direction_3d in {"利好", "利空"} else "短期维持中性观察"
            one_liner = (
                f"近7天新增催化有限，{fund.get('name', code)}{short_desc}，"
                f"但3个月维度偏{direction_3m}，长期逻辑{long_term_logic}。"
            )
        else:
            one_liner = (
                f"近7天高质量事件{'已形成可参考链条' if has_actionable_chain else '仍偏不足'}，"
                f"{fund.get('name', code)}短期以{direction_2w}观察为主，长期逻辑{long_term_logic}。"
            )
        if one_liner_prefix:
            one_liner = f"{one_liner_prefix}。" + one_liner
        if proxy_share > float(proxy_controls.get("max_proxy_share_in_main", 0.6)):
            one_liner += "（提示：短期结论中代理变量占比较高）"
        if direct_count == 0:
            one_liner += "（缺少直接证据确认）"
        if source_diversity_main <= 1 and len(fresh_2w) >= 1:
            one_liner += "（主结论来源单一）"
        if proxy_downgraded:
            one_liner += "（已自动下调结论强度）"

        reports.append(
            FundReport(
                fund_code=code,
                fund_name=fund.get("name", ""),
                fund_type=fund.get("type", ""),
                analysis_window=f"{window_days}d",
                recent_event_count=len(fresh_2w),
                stale_event_count_filtered=len(stale_filtered),
                noise_event_count_filtered=len(noise_filtered),
                low_tier_event_count_filtered=len(low_tier_filtered),
                proxy_event_count_main=proxy_count,
                proxy_event_share_main=round(proxy_share, 4),
                direct_event_count_main=direct_count,
                source_diversity_main=source_diversity_main,
                decision_readiness=decision_readiness,
                decision_constraints=decision_constraints,
                signal_summary={
                    "net_score_3d": round(net_3d, 6),
                    "net_score_2w": round(net_2w, 6),
                    "net_score_3m": round(net_3m, 6),
                    "positive_count": sum(1 for x in fresh_2w if x.score > 0),
                    "negative_count": sum(1 for x in fresh_2w if x.score < 0),
                    "total_signals": len(items),
                    "proxy_main_count": proxy_count,
                    "proxy_main_share": round(proxy_share, 4),
                    "direct_main_count": direct_count,
                    "source_diversity_main": source_diversity_main,
                    "decision_readiness": decision_readiness,
                },
                direction_3d=direction_3d,
                direction_2w=direction_2w,
                direction_3m=direction_3m,
                long_term_logic=long_term_logic,
                confidence=confidence,
                conclusion_strength=conclusion_strength,
                warnings=warnings,
                key_events=key_events,
                downgraded_events=downgraded_events,
                core_driver_check=core_driver_check,
                counter_evidence=counter_evidence,
                watch_points=_watch_points_by_type(str(fund.get("type", ""))),
                one_liner=one_liner,
                source_stability_score=0.0,
                historical_consistency_score=0.0,
                reference_value_score=0.0,
                quality_flags=[],
            )
        )

    return reports


def render_markdown(reports: Sequence[FundReport]) -> str:
    """Render research-style markdown report with stable structure."""
    lines = ["# fund-event-engine pipeline report", ""]
    for r in reports:
        lines.extend(
            [
                f"## 【{r.fund_name}】",
                "",
                "一、最终判断",
                f"- 近3日：{r.direction_3d}",
                f"- 近2周：{r.direction_2w}",
                f"- 近3个月逻辑：{r.direction_3m}",
                f"- 长期逻辑：{r.long_term_logic}",
                f"- 结论强度：{r.conclusion_strength}",
                f"- 决策可用性：{r.decision_readiness}",
                "",
                "二、本次真正有效的关键事件",
            ]
        )

        if r.key_events:
            for idx, e in enumerate(r.key_events, start=1):
                lines.extend(
                    [
                        f"- 事件{idx}：{e.get('title', '')}",
                        f"  - 日期：{e.get('date', '')}",
                        f"  - 来源：{e.get('source', '')}",
                        f"  - 为什么重要：{e.get('why_important', '')}",
                        f"  - 变量证据类型：{e.get('evidence_mode', 'direct')}",
                        f"  - 变量证据说明：{e.get('evidence_mode_note', '')}",
                        f"  - 对基金的传导链条：{' -> '.join(e.get('impact_chain', []))}",
                        f"  - 证据等级：{e.get('evidence_tier', 'C')}",
                    ]
                )
        else:
            lines.append("- 近期未识别到可进入主结论的A/B级新增事件")

        lines.extend(["", "三、被过滤或降级的信息"])
        lines.append(f"- 网页噪音过滤数量：{r.noise_event_count_filtered}")
        lines.append(f"- 过时或日期不确定过滤数量：{r.stale_event_count_filtered}")
        lines.append(f"- 低层级证据降级数量：{r.low_tier_event_count_filtered}")
        lines.append(f"- 主结论中代理变量数量：{r.proxy_event_count_main}")
        lines.append(f"- 主结论中代理变量占比：{r.proxy_event_share_main:.2%}")
        lines.append(f"- 主结论中直接证据数量：{r.direct_event_count_main}")
        lines.append(f"- 主结论来源数：{r.source_diversity_main}")

        lines.extend(["", "四、核心驱动变量检查"])
        for k, v in r.core_driver_check.items():
            lines.append(f"- {k}：{v}")

        lines.extend(["", "五、反证"])
        for c in r.counter_evidence:
            lines.append(f"- {c}")

        lines.extend(["", "六、一句话结论"])
        lines.append(f"- {r.one_liner}")

        lines.extend(["", "附：系统警示"])
        if r.warnings:
            for w in r.warnings:
                lines.append(f"- {w}")
        else:
            lines.append("- 无")

        lines.extend(["", "附：自动质量评分"])
        lines.append(f"- 源稳定性分：{r.source_stability_score:.2f}")
        lines.append(f"- 历史一致性分：{r.historical_consistency_score:.2f}")
        lines.append(f"- 参考价值分：{r.reference_value_score:.2f}")
        if r.quality_flags:
            for flag in r.quality_flags:
                lines.append(f"- 质量标记：{flag}")
        else:
            lines.append("- 质量标记：无")

        lines.append("")

    return "\n".join(lines).strip() + "\n"
