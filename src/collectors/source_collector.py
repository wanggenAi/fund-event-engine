"""Source collection orchestrator for free/public sources."""

from __future__ import annotations

import re
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib import parse, request
from xml.etree import ElementTree as ET

from src.collectors.contracts import CollectedDocument
from src.parsers.html_cleaner import clean_html
from src.utils.config_loader import load_yaml


ROOT = Path(__file__).resolve().parents[2]


@dataclass
class CollectStats:
    sources_total: int = 0
    sources_attempted: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    pages_attempted: int = 0
    pages_succeeded: int = 0
    pages_failed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _extract_date(text: str) -> str:
    match = re.search(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)", text)
    if not match:
        try:
            dt = parsedate_to_datetime(text.strip())
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return ""
    return match.group(1).replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")


def _extract_date_from_url(url: str) -> str:
    # Common URL date patterns: /2026/03/22/ or 2026-03-22
    m = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", url)
    if not m:
        return ""
    y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    return f"{y}-{mo}-{d}"


def _extract_title(html_text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.I | re.S)
    if not m:
        return ""
    return clean_html(m.group(1)).strip()


def _fetch_url(url: str, timeout: float = 10.0) -> str:
    req = request.Request(url, headers={"User-Agent": "fund-event-engine/0.3"})
    with request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _extract_links(seed_html: str, base_url: str) -> List[str]:
    links = re.findall(r"href=[\"']([^\"']+)[\"']", seed_html, flags=re.I)
    out: List[str] = []
    seen = set()
    for link in links:
        link = link.strip()
        if not link or link.startswith("javascript:") or link.startswith("mailto:"):
            continue
        abs_link = parse.urljoin(base_url, link)
        if abs_link in seen:
            continue
        seen.add(abs_link)
        out.append(abs_link)
    return out


def _same_host(url_a: str, url_b: str) -> bool:
    try:
        return parse.urlparse(url_a).netloc == parse.urlparse(url_b).netloc
    except Exception:
        return False


def _rank_link(url: str) -> int:
    score = 0
    patterns = [r"notice", r"announcement", r"article", r"news", r"disclosure", r"detail", r"gg", r"tzgg", r"/20\d{2}/"]
    for p in patterns:
        if re.search(p, url, flags=re.I):
            score += 1
    return score


def _source_tier_from_category(category: str) -> str:
    if category == "authoritative_data":
        return "A"
    if category == "top_tier_media":
        return "B"
    if category == "specialist_research":
        return "C"
    return "D"


def _is_query_source(source: Dict[str, Any]) -> bool:
    hint = str(source.get("parser_hint", "")).lower()
    return bool(source.get("search_query")) or hint in {"google_news_query", "query_seed"}


def _source_priority(source: Dict[str, Any]) -> int:
    """Prioritize sources by category/reliability/freshness when capped by max_sources."""
    cat = str(source.get("category", "specialist_research"))
    fresh = str(source.get("freshness_priority", "low"))
    rel = str(source.get("reliability", "community"))
    cat_score = {
        "authoritative_data": 50,
        "top_tier_media": 40,
        "specialist_research": 25,
        "sentiment_sources": 15,
    }
    fresh_score = {"high": 12, "medium": 8, "low": 4}
    rel_score = {
        "official": 10,
        "exchange": 10,
        "mainstream_media": 8,
        "industry_media": 7,
        "specialist": 5,
        "community": 2,
    }
    score = cat_score.get(cat, 10) + fresh_score.get(fresh, 3) + rel_score.get(rel, 1)
    if _is_query_source(source):
        score += 4
    return score


def _source_tags(source: Dict[str, Any]) -> List[str]:
    tags = source.get("tags", [])
    if not isinstance(tags, list):
        return []
    return [str(x).strip().lower() for x in tags if str(x).strip()]


def _select_sources(
    sources: List[Dict[str, Any]],
    max_sources: int,
    category_quotas: Dict[str, int] | None = None,
    required_tags: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Select enabled sources with quality priority + optional mix constraints."""
    if max_sources <= 0:
        return []
    ranked = sorted(sources, key=_source_priority, reverse=True)
    if not category_quotas and not required_tags:
        return ranked[:max_sources]

    picked: List[Dict[str, Any]] = []
    used = set()
    need_tags = [t.strip().lower() for t in (required_tags or []) if t and str(t).strip()]

    # 1) Ensure thematic coverage by required tags.
    for tag in need_tags:
        for idx, src in enumerate(ranked):
            if idx in used:
                continue
            if tag in _source_tags(src):
                picked.append(src)
                used.add(idx)
                break
        if len(picked) >= max_sources:
            return picked[:max_sources]

    # 2) Fill category minimum quotas.
    quotas = {str(k): int(v) for k, v in (category_quotas or {}).items() if int(v) > 0}
    if quotas:
        cat_count: Dict[str, int] = {}
        for p in picked:
            cat = str(p.get("category", "specialist_research"))
            cat_count[cat] = cat_count.get(cat, 0) + 1
        for cat, q in quotas.items():
            while cat_count.get(cat, 0) < q and len(picked) < max_sources:
                added = False
                for idx, src in enumerate(ranked):
                    if idx in used:
                        continue
                    if str(src.get("category", "")) != cat:
                        continue
                    picked.append(src)
                    used.add(idx)
                    cat_count[cat] = cat_count.get(cat, 0) + 1
                    added = True
                    break
                if not added:
                    break

    # 3) Fill remaining slots by overall priority.
    if len(picked) < max_sources:
        for idx, src in enumerate(ranked):
            if idx in used:
                continue
            picked.append(src)
            used.add(idx)
            if len(picked) >= max_sources:
                break
    return picked[:max_sources]


def _collect_rss(
    source: Dict[str, Any],
    max_items: int,
    timeout: float,
    strict: bool,
    verbose: bool,
    stats: CollectStats,
) -> List[CollectedDocument]:
    docs: List[CollectedDocument] = []
    xml_text = _fetch_url(source.get("url", ""), timeout=timeout)
    root = ET.fromstring(xml_text)
    source_tier = _source_tier_from_category(source.get("category", "top_tier_media"))

    for item in root.findall(".//item")[:max_items]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or source.get("url", "")).strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()
        published_at = _extract_date(pub_date) or _extract_date(desc) or _extract_date_from_url(link)

        content = clean_html(desc)
        if link:
            stats.pages_attempted += 1
            try:
                detail_html = _fetch_url(link, timeout=timeout)
                detail_text = clean_html(detail_html)
                if len(detail_text) >= 120:
                    content = detail_text[:8000]
                stats.pages_succeeded += 1
            except Exception as exc:
                stats.pages_failed += 1
                if verbose:
                    print(f"[collect] rss detail fail: {link} ({exc})")
                if strict:
                    raise

        docs.append(
            CollectedDocument(
                title=title or source.get("name", "rss_item"),
                url=link,
                content=content,
                source=source.get("name", ""),
                source_type=source.get("source_type", "rss"),
                source_tier=source_tier,
                category=source.get("category", "top_tier_media"),
                published_at=published_at,
            )
        )
    return docs


def _collect_html_source(
    source: Dict[str, Any],
    max_items: int,
    max_list_links: int,
    timeout: float,
    strict: bool,
    verbose: bool,
    stats: CollectStats,
) -> List[CollectedDocument]:
    seed_url = source.get("url", "")
    seed_html = _fetch_url(seed_url, timeout=timeout)
    links = _extract_links(seed_html, seed_url)
    source_tier = _source_tier_from_category(source.get("category", "authoritative_data"))

    # Focus on same-host links and rank by notice/article-like structure.
    link_candidates = [u for u in links if _same_host(seed_url, u)]
    link_candidates = sorted(link_candidates, key=_rank_link, reverse=True)[:max_list_links]

    docs: List[CollectedDocument] = []
    for link in link_candidates[:max_items]:
        stats.pages_attempted += 1
        try:
            detail_html = _fetch_url(link, timeout=timeout)
            title = _extract_title(detail_html) or source.get("name", "page_source")
            detail_text = clean_html(detail_html)
            if len(detail_text) < 120:
                continue
            published_at = _extract_date(detail_text[:1000]) or _extract_date_from_url(link)
            docs.append(
                CollectedDocument(
                    title=title,
                    url=link,
                    content=detail_text[:8000],
                    source=source.get("name", ""),
                    source_type=source.get("source_type", "official_site"),
                    source_tier=source_tier,
                    category=source.get("category", "authoritative_data"),
                    published_at=published_at,
                )
            )
            stats.pages_succeeded += 1
        except Exception as exc:
            stats.pages_failed += 1
            if verbose:
                print(f"[collect] detail fail: {link} ({exc})")
            if strict:
                raise

    # Fallback to seed page if no detail page passed quality bar.
    if not docs:
        seed_text = clean_html(seed_html)
        docs.append(
            CollectedDocument(
                title=source.get("name", "page_source"),
                url=seed_url,
                content=seed_text[:8000],
                source=source.get("name", ""),
                source_type=source.get("source_type", "official_site"),
                source_tier=source_tier,
                category=source.get("category", "authoritative_data"),
                published_at=_extract_date(seed_text[:1000]) or _extract_date_from_url(seed_url),
            )
        )

    return docs[:max_items]


def collect_documents_from_sources(
    max_sources: int = 20,
    max_items_per_source: int = 3,
    max_list_links: int = 15,
    timeout: float = 10.0,
    strict: bool = False,
    verbose: bool = False,
    category_quotas: Dict[str, int] | None = None,
    required_tags: List[str] | None = None,
) -> Tuple[List[CollectedDocument], CollectStats]:
    """Collect docs from enabled free/public sources with graceful fallback."""
    cfg = load_yaml(ROOT / "configs" / "sources.yaml")
    sources = [s for s in cfg.get("sources", []) if s.get("enabled", False)]
    stats = CollectStats(sources_total=len(sources))
    out: List[CollectedDocument] = []
    selected_sources = _select_sources(
        sources,
        max_sources=max_sources,
        category_quotas=category_quotas,
        required_tags=required_tags,
    )

    for source in selected_sources:
        stats.sources_attempted += 1
        source_name = source.get("name", "source")
        if verbose:
            print(f"[collect] source start: {source_name}")
        try:
            if _is_query_source(source):
                docs = _collect_query_source(
                    source,
                    max_items=max_items_per_source,
                    timeout=timeout,
                    strict=strict,
                    verbose=verbose,
                    stats=stats,
                )
            elif source.get("source_type") == "rss":
                docs = _collect_rss(source, max_items=max_items_per_source, timeout=timeout, strict=strict, verbose=verbose, stats=stats)
            else:
                docs = _collect_html_source(
                    source,
                    max_items=max_items_per_source,
                    max_list_links=max_list_links,
                    timeout=timeout,
                    strict=strict,
                    verbose=verbose,
                    stats=stats,
                )
            out.extend(docs)
            stats.sources_succeeded += 1
            if verbose:
                print(f"[collect] source done: {source_name} docs={len(docs)}")
        except Exception as exc:
            stats.sources_failed += 1
            if strict:
                raise
            if verbose:
                print(f"[collect] source fail: {source_name} ({exc})")
            out.append(
                CollectedDocument(
                    title=f"{source_name} (collect_failed)",
                    url=source.get("url", ""),
                    content="",
                    source=source_name,
                    source_type=source.get("source_type", "other"),
                    source_tier=_source_tier_from_category(str(source.get("category", "specialist_research"))),
                    category=source.get("category", "specialist_research"),
                    published_at=_now_iso(),
                )
            )

    return out, stats


def collect_google_news_documents(
    queries: List[str],
    max_items_per_query: int = 3,
    timeout: float = 10.0,
    hl: str = "zh-CN",
    gl: str = "CN",
    ceid: str = "CN:zh-Hans",
    verbose: bool = False,
    source_name: str = "Google News RSS",
    source_type: str = "media",
    source_tier: str = "B",
    category: str = "top_tier_media",
    strict: bool = False,
) -> List[CollectedDocument]:
    """Collect recent public news via Google News RSS queries (free source)."""
    docs: List[CollectedDocument] = []
    for query in queries:
        rss_url = (
            "https://news.google.com/rss/search?"
            + parse.urlencode({"q": query, "hl": hl, "gl": gl, "ceid": ceid})
        )
        try:
            xml_text = _fetch_url(rss_url, timeout=timeout)
            root = ET.fromstring(xml_text)
            items = root.findall(".//item")[:max_items_per_query]
            for item in items:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                desc = clean_html((item.findtext("description") or "").strip())
                published_at = _extract_date(pub_date) or _extract_date(desc) or _extract_date_from_url(link)
                docs.append(
                    CollectedDocument(
                        title=title or f"news:{query}",
                        url=link or rss_url,
                        content=desc[:3000],
                        source=source_name,
                        source_type=source_type,
                        source_tier=source_tier,
                        category=category,
                        published_at=published_at,
                    )
                )
        except Exception as exc:
            if verbose:
                print(f"[collect] google news fail: {query} ({exc})")
            if strict:
                raise
    return docs


def _build_source_queries(source: Dict[str, Any]) -> List[str]:
    """Build bounded query list from source metadata."""
    out: List[str] = []
    q = source.get("search_query")
    if isinstance(q, str) and q.strip():
        out.append(q.strip())
    elif isinstance(q, list):
        out.extend([str(x).strip() for x in q if str(x).strip()])
    if not out:
        tags = source.get("tags", [])
        if isinstance(tags, list) and tags:
            out.append(" ".join([str(x) for x in tags[:4] if str(x).strip()]))
    if not out:
        return []
    domain = parse.urlparse(str(source.get("url", ""))).netloc.replace("www.", "")
    max_age = int(source.get("max_age_days", 7) or 7)
    max_age = min(30, max(3, max_age))
    enriched: List[str] = []
    for qx in out:
        query = qx
        if domain and "site:" not in query:
            query = f"{query} site:{domain}".strip()
        if "when:" not in query:
            query = f"{query} when:{max_age}d".strip()
        enriched.append(query)
    return list(dict.fromkeys(enriched))


def _collect_query_source(
    source: Dict[str, Any],
    max_items: int,
    timeout: float,
    strict: bool,
    verbose: bool,
    stats: CollectStats,
) -> List[CollectedDocument]:
    """Collect query-based source via Google News RSS while preserving source metadata."""
    queries = _build_source_queries(source)[:3]
    if not queries:
        return []
    stats.pages_attempted += len(queries)
    docs = collect_google_news_documents(
        queries=queries,
        max_items_per_query=max(1, max_items),
        timeout=timeout,
        hl=str(source.get("hl", "zh-CN")),
        gl=str(source.get("gl", "CN")),
        ceid=str(source.get("ceid", "CN:zh-Hans")),
        verbose=verbose,
        source_name=str(source.get("name", "query_source")),
        source_type=str(source.get("source_type", "search_seed")),
        source_tier=_source_tier_from_category(str(source.get("category", "specialist_research"))),
        category=str(source.get("category", "specialist_research")),
        strict=strict,
    )
    if docs:
        stats.pages_succeeded += len(queries)
    else:
        stats.pages_failed += len(queries)
    return docs


def collect_central_bank_gold_signal_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Build structured central-bank-gold signal from free Google News RSS headlines."""
    queries = [
        "央行 购金 黄金储备 增持 when:30d",
        "central bank gold buying reserves when:30d",
    ]
    rows = collect_google_news_documents(
        queries=queries,
        max_items_per_query=5,
        timeout=timeout,
        hl="en-US",
        gl="US",
        ceid="US:en",
        verbose=verbose,
    )
    if not rows:
        return []

    pos_words = ["购金", "增持", "increase", "buying", "added", "rise", "rose", "record"]
    neg_words = ["减持", "减少", "sell", "sold", "decline", "cut", "drop"]
    pos = 0
    neg = 0
    latest = ""
    for r in rows:
        title = (r.title or "").lower()
        if any(w in title for w in pos_words):
            pos += 1
        if any(w in title for w in neg_words):
            neg += 1
        d = (r.published_at or "").strip()
        if d and d > latest:
            latest = d

    if not latest:
        latest = _now_iso()

    if pos > neg:
        trend = "偏强"
    elif neg > pos:
        trend = "偏弱"
    else:
        trend = "中性"
    sentence = (
        f"{latest}，央行购金跟踪披露：近30天相关报道中增持信号{pos}条、减持信号{neg}条，"
        f"央行购金趋势{trend}。"
    )
    return [
        CollectedDocument(
            title="央行购金趋势信号",
            url="https://news.google.com/",
            content=sentence,
            source="Central Bank Gold Signal",
            source_type="media",
            source_tier="B",
            category="top_tier_media",
            published_at=latest,
        )
    ]










def collect_rare_earth_direct_signal_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Build direct-style rare-earth signals from policy, price and order-demand public reports."""
    docs: List[CollectedDocument] = []

    policy_queries = [
        "稀土 配额 总量控制 出口管制 工信部 when:30d",
        "稀土 政策 指标 配额 出口 when:30d",
        "中国稀土行业协会 稀土 政策 供给 when:30d",
    ]
    rows = collect_google_news_documents(
        queries=policy_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        pos_words = ["收紧", "总量控制", "配额", "出口管制", "偏紧", "强化"]
        neg_words = ["放松", "放开", "宽松", "下调", "供给释放"]
        pos = neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        latest = latest or _now_iso()
        trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
        docs.append(CollectedDocument(
            title="稀土政策与供给约束趋势信号",
            url="https://news.google.com/",
            content=f"{latest}，稀土政策与供给约束跟踪：近30天收紧/约束信号{pos}条、放松/释放信号{neg}条，供给约束趋势{trend}。",
            source="Rare Earth Policy Direct Signal",
            source_type="media",
            source_tier="B",
            category="top_tier_media",
            published_at=latest,
        ))

    price_queries = [
        "氧化镨钕 价格 重稀土 价格 稀土 永磁 when:14d",
        "稀土 价格 新高 回落 镨钕 when:14d",
        "上海有色网 稀土 镨钕 价格 when:14d",
    ]
    rows = collect_google_news_documents(
        queries=price_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        pos_words = ["新高", "上涨", "上行", "走强", "提价", "偏紧"]
        neg_words = ["回落", "下跌", "下行", "走弱", "承压"]
        pos = neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        latest = latest or _now_iso()
        trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
        docs.append(CollectedDocument(
            title="稀土价格趋势信号",
            url="https://news.google.com/",
            content=f"{latest}，稀土价格跟踪：近14天价格走强信号{pos}条、走弱信号{neg}条，价格趋势{trend}。",
            source="Rare Earth Price Direct Signal",
            source_type="media",
            source_tier="B",
            category="top_tier_media",
            published_at=latest,
        ))

    order_queries = [
        "稀土 永磁 订单 排产 开工率 出货 when:30d",
        "磁材 订单 稀土 永磁 新能源 风电 机器人 when:30d",
        "稀土 永磁 下游需求 开工 出货 when:30d",
    ]
    rows = collect_google_news_documents(
        queries=order_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        pos_words = ["订单增长", "订单改善", "排产提升", "开工率提升", "出货增长", "需求回暖"]
        neg_words = ["订单下滑", "排产下滑", "开工率回落", "出货承压", "需求走弱"]
        pos = neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        latest = latest or _now_iso()
        trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
        docs.append(CollectedDocument(
            title="稀土永磁订单与开工趋势信号",
            url="https://news.google.com/",
            content=f"{latest}，稀土永磁订单与开工跟踪：近30天订单/开工改善信号{pos}条、走弱信号{neg}条，订单与开工趋势{trend}。",
            source="Rare Earth Order Direct Signal",
            source_type="media",
            source_tier="B",
            category="top_tier_media",
            published_at=latest,
        ))
    return docs


def collect_power_grid_direct_signal_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Build direct-style power-grid signals from public bidding/order/policy news."""
    docs: List[CollectedDocument] = []

    order_queries = [
        "国家电网 南方电网 招标 中标 设备 特高压 when:14d",
        "电网设备 中标 订单 配网 特高压 when:14d",
        "变压器 开关 电缆 电网 中标 订单 when:14d",
    ]
    rows = collect_google_news_documents(
        queries=order_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        pos_words = ["中标", "开标", "订单", "中选", "落地", "签约", "交付"]
        neg_words = ["延期", "取消", "流标", "推迟"]
        pos = 0
        neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="电网招投标与订单趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，电网招投标与订单跟踪：近14天订单落地/中标信号{pos}条、延期/取消信号{neg}条，订单趋势{trend}。",
                source="Power Grid Tender Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )

    policy_queries = [
        "特高压 核准 电网投资 配网改造 政策 when:14d",
        "国家能源局 电网投资 特高压 配网 when:30d",
    ]
    rows = collect_google_news_documents(
        queries=policy_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        pos_words = ["核准", "投资", "提速", "开工", "改造", "推进", "落地"]
        neg_words = ["放缓", "推迟", "下调", "不及预期"]
        pos = 0
        neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="电网投资与核准推进趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，电网投资与核准推进跟踪：近14天推进/核准信号{pos}条、放缓/推迟信号{neg}条，政策推进趋势{trend}。",
                source="Power Grid Policy Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )
    return docs


def collect_satellite_direct_signal_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Build direct-style satellite signals from public launch/order/policy rollout news."""
    docs: List[CollectedDocument] = []

    launch_queries = [
        "商业航天 卫星 发射 成功 延期 组网 when:14d",
        "卫星互联网 发射 低轨 组网 when:14d",
        "国家航天局 卫星 发射 商业航天 when:30d",
    ]
    rows = collect_google_news_documents(
        queries=launch_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        pos_words = ["发射成功", "组网推进", "入轨", "部署", "发射"]
        neg_words = ["延期", "推迟", "失败", "失利", "受阻"]
        pos = 0
        neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="商用卫星发射与组网趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，商用卫星发射与组网跟踪：近14天发射成功/组网推进信号{pos}条、延期/失败信号{neg}条，发射与组网趋势{trend}。",
                source="Satellite Launch Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )

    policy_queries = [
        "卫星互联网 标准委 牌照 频轨 政策 推进 when:30d",
        "商业航天 标准 政策 牌照 卫星互联网 when:30d",
    ]
    rows = collect_google_news_documents(
        queries=policy_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        pos_words = ["成立", "推进", "批复", "标准", "牌照", "核准", "落地"]
        neg_words = ["搁置", "推迟", "暂停", "受阻"]
        pos = 0
        neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="商用卫星政策与标准推进趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，商用卫星政策与标准推进跟踪：近14天推进/落地信号{pos}条、受阻/推迟信号{neg}条，政策推进趋势{trend}。",
                source="Satellite Rollout Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )
    return docs


def collect_bond_china_direct_signal_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Build China-local bond direct signals from public news around issuance/funding/credit events."""
    docs: List[CollectedDocument] = []

    issue_queries = [
        "信用债 取消发行 净融资 票面利率 城投债 when:14d",
        "公司债 中票 短融 取消发行 净融资 when:14d",
        "城投债 净融资 发行 利率 认购 倍数 when:14d",
    ]
    rows = collect_google_news_documents(
        queries=issue_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        pos_words = ["净融资改善", "发行回暖", "认购积极", "利率下行", "超额认购", "发行成功"]
        neg_words = ["取消发行", "发行失败", "净融资走弱", "利率抬升", "认购不足", "取消"]
        pos = 0
        neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "改善" if pos > neg else "承压" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="信用债发行与净融资趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，信用债发行与净融资跟踪：近14天改善信号{pos}条、承压信号{neg}条，净融资与发行环境{trend}。",
                source="Bond Financing Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )

    credit_queries = [
        "城投债 债务 展期 兑付 风险 缓释 when:14d",
        "信用债 兑付 展期 违约 增信 when:14d",
        "地产债 债务 风险 化解 兑付 when:14d",
    ]
    rows = collect_google_news_documents(
        queries=credit_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        pos_words = ["化解", "纾困", "增信", "兑付完成", "风险缓释", "支持工具"]
        neg_words = ["违约", "展期", "逾期", "兑付承压", "风险暴露", "下调"]
        pos = 0
        neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "改善" if pos > neg else "承压" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="中国信用债风险事件趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，中国信用债风险事件跟踪：近14天风险缓释信号{pos}条、风险暴露信号{neg}条，信用环境{trend}。",
                source="China Bond Credit Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )
    return docs




def collect_gold_holdings_direct_signal_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Build gold holdings/positioning direct-style signals from public ETF/holdings news."""
    docs: List[CollectedDocument] = []
    queries = [
        "gold ETF holdings rise fall SPDR holdings when:14d",
        "黄金 ETF 持仓 增持 减持 when:14d",
        "SPDR Gold Shares holdings inflow outflow when:14d",
    ]
    rows = collect_google_news_documents(
        queries=queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="en-US",
        gl="US",
        ceid="US:en",
        verbose=verbose,
    )
    if not rows:
        return docs
    pos_words = ["holdings rise", "inflow", "added", "增持", "净流入", "持仓增加"]
    neg_words = ["holdings fall", "outflow", "sold", "减持", "净流出", "持仓下降"]
    pos = neg = 0
    latest = ""
    for r in rows:
        t = (r.title or "").lower()
        if any(w in t for w in pos_words):
            pos += 1
        if any(w in t for w in neg_words):
            neg += 1
        d = (r.published_at or "").strip()
        if d and d > latest:
            latest = d
    latest = latest or _now_iso()
    trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
    docs.append(
        CollectedDocument(
            title="黄金ETF持仓变化趋势信号",
            url="https://news.google.com/",
            content=f"{latest}，黄金ETF持仓变化跟踪：近14天持仓增加/净流入信号{pos}条、持仓下降/净流出信号{neg}条，持仓趋势{trend}。",
            source="Gold Holdings Signal",
            source_type="media",
            source_tier="B",
            category="top_tier_media",
            published_at=latest,
        )
    )
    return docs


def collect_gold_direct_signal_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Build direct-style gold signals from public news on ETF flows and gold-specific catalysts."""
    docs: List[CollectedDocument] = []

    etf_queries = [
        "黄金 ETF 资金流 净流入 净流出 when:14d",
        "gold ETF inflow outflow holdings when:14d",
    ]
    rows = collect_google_news_documents(
        queries=etf_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="en-US",
        gl="US",
        ceid="US:en",
        verbose=verbose,
    )
    if rows:
        pos_words = ["净流入", "增持", "流入", "inflow", "added", "holdings rise"]
        neg_words = ["净流出", "减持", "流出", "outflow", "sold", "holdings fall"]
        pos = 0
        neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="黄金ETF资金流趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，黄金ETF资金流跟踪：近14天净流入/增持信号{pos}条、净流出/减持信号{neg}条，ETF资金流趋势{trend}。",
                source="Gold ETF Flow Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )

    safe_haven_queries = [
        "黄金 避险 升温 降温 when:14d",
        "gold safe haven demand geopolitical when:14d",
    ]
    rows = collect_google_news_documents(
        queries=safe_haven_queries,
        max_items_per_query=5,
        timeout=timeout,
        hl="en-US",
        gl="US",
        ceid="US:en",
        verbose=verbose,
    )
    if rows:
        pos_words = ["避险", "升温", "safe haven", "geopolitical risk", "tension"]
        neg_words = ["降温", "缓和", "ceasefire", "truce", "de-escalation"]
        pos = 0
        neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="黄金避险需求趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，黄金避险需求跟踪：近14天避险升温信号{pos}条、缓和信号{neg}条，避险需求趋势{trend}。",
                source="Gold Safe Haven Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )
    return docs


def collect_bond_direct_signal_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Build bond direct-style signals from public news on credit events, liquidity and issuance/funding."""
    docs: List[CollectedDocument] = []

    credit_queries = [
        "信用债 违约 展期 风险缓释 when:14d",
        "城投债 信用 风险 违约 展期 when:14d",
    ]
    rows = collect_google_news_documents(
        queries=credit_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        neg_words = ["违约", "展期", "爆雷", "风险暴露", "下调", "兑付承压"]
        pos_words = ["风险缓释", "兑付完成", "增信", "纾困", "支持工具", "化解"]
        pos = 0
        neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "改善" if pos > neg else "承压" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="信用债信用事件趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，信用债信用事件跟踪：近14天风险缓释信号{pos}条、风险暴露信号{neg}条，信用环境{trend}。",
                source="Bond Credit Event Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )

    liquidity_queries = [
        "回购利率 资金面 流动性 债市 when:14d",
        "同业存单 利率 资金面 债券 when:14d",
    ]
    rows = collect_google_news_documents(
        queries=liquidity_queries,
        max_items_per_query=6,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if rows:
        pos_words = ["宽松", "回落", "改善", "呵护", "投放", "降准", "降息"]
        neg_words = ["收紧", "抬升", "紧张", "扰动", "上行"]
        pos = 0
        neg = 0
        latest = ""
        for r in rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "改善" if pos > neg else "趋紧" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="债市流动性趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，债市流动性跟踪：近14天流动性改善信号{pos}条、收紧信号{neg}条，资金面趋势{trend}。",
                source="Bond Liquidity Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )
    return docs


def collect_structured_theme_signal_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Create structured macro/geopolitical signal docs from free news headlines."""
    docs: List[CollectedDocument] = []

    # Broad-equity macro/risk-appetite signal.
    macro_queries = [
        "中证500 风险偏好 回升 宏观 修复 when:14d",
        "PMI 社融 流动性 风险偏好 when:14d",
    ]
    macro_rows = collect_google_news_documents(
        queries=macro_queries,
        max_items_per_query=5,
        timeout=timeout,
        hl="zh-CN",
        gl="CN",
        ceid="CN:zh-Hans",
        verbose=verbose,
    )
    if macro_rows:
        pos_words = ["修复", "回升", "改善", "宽松", "回暖", "超预期", "企稳"]
        neg_words = ["回落", "收紧", "走弱", "承压", "下行", "不及预期"]
        pos = 0
        neg = 0
        latest = ""
        for r in macro_rows:
            t = (r.title or "").lower()
            if any(w in t for w in pos_words):
                pos += 1
            if any(w in t for w in neg_words):
                neg += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "偏强" if pos > neg else "偏弱" if neg > pos else "中性"
        docs.append(
            CollectedDocument(
                title="宽基风险偏好趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，宽基风险偏好跟踪：近14天正向信号{pos}条、负向信号{neg}条，风险偏好趋势{trend}。",
                source="Broad Equity Risk Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )

    # Gold geopolitical safe-haven signal.
    geo_queries = [
        "地缘 冲突 避险 黄金 when:14d",
        "geopolitical risk safe haven gold when:14d",
    ]
    geo_rows = collect_google_news_documents(
        queries=geo_queries,
        max_items_per_query=5,
        timeout=timeout,
        hl="en-US",
        gl="US",
        ceid="US:en",
        verbose=verbose,
    )
    if geo_rows:
        risk_up_words = ["冲突", "升级", "attack", "missile", "tension", "war", "escalat"]
        risk_down_words = ["缓和", "停火", "ceasefire", "de-escalat", "talks", "truce"]
        up = 0
        down = 0
        latest = ""
        for r in geo_rows:
            t = (r.title or "").lower()
            if any(w in t for w in risk_up_words):
                up += 1
            if any(w in t for w in risk_down_words):
                down += 1
            d = (r.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        trend = "上行" if up > down else "回落" if down > up else "中性"
        docs.append(
            CollectedDocument(
                title="地缘避险趋势信号",
                url="https://news.google.com/",
                content=f"{latest}，地缘避险跟踪：近14天风险升温信号{up}条、缓和信号{down}条，避险需求趋势{trend}。",
                source="Geopolitical Risk Signal",
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )

    return docs


def collect_thematic_industry_signal_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Build structured 14-day thematic signals for rare-earth/power-grid/satellite."""
    docs: List[CollectedDocument] = []

    theme_defs: List[Dict[str, Any]] = [
        {
            "title": "稀土政策供给约束趋势信号",
            "source": "Rare Earth Policy Signal",
            "queries": [
                "稀土 配额 指标 工信部 出口 管制 when:14d",
                "工信部 稀土 总量控制 指标 配额 when:30d",
                "稀土 出口 管制 政策 供给 收紧 site:gov.cn when:30d",
            ],
            "pos_words": ["收紧", "上调", "总量控制", "管制", "偏紧", "强化"],
            "neg_words": ["放松", "下调", "放开", "偏弱", "宽松"],
            "summary_prefix": "稀土政策与供给约束跟踪（配额/出口管制/总量控制）",
        },
        {
            "title": "稀土价格与下游需求趋势信号",
            "source": "Rare Earth Price-Demand Signal",
            "queries": [
                "重稀土 轻稀土 价格 新高 回落 永磁 需求 when:14d",
                "氧化镨钕 价格 稀土 永磁 需求 when:30d",
                "稀土 永磁 订单 需求 回暖 新能源 风电 机器人 when:30d",
            ],
            "pos_words": ["新高", "上行", "走强", "提价", "需求回暖", "高增", "订单改善"],
            "neg_words": ["回落", "下行", "走弱", "需求下滑", "订单走弱", "承压"],
            "summary_prefix": "稀土价格与永磁下游需求跟踪（氧化镨钕/重稀土/永磁需求）",
        },
        {
            "title": "稀土永磁订单与交付趋势信号",
            "source": "Rare Earth Order Signal",
            "queries": [
                "稀土 永磁 订单 交付 开工 排产 when:14d",
                "磁材 企业 订单 产能 利用率 出货 稀土 when:30d",
                "稀土永磁 下游 订单 新能源 风电 机器人 when:30d",
            ],
            "pos_words": ["订单增长", "订单改善", "排产提升", "交付提速", "开工率提升", "出货增长"],
            "neg_words": ["订单下滑", "交付放缓", "排产下滑", "开工率回落", "需求不足", "不及预期"],
            "summary_prefix": "稀土永磁订单与交付跟踪（订单/排产/开工/交付）",
        },
        {
            "title": "电网设备订单投资趋势信号",
            "source": "Power Grid Structured Signal",
            "queries": [
                "电网 特高压 配网 招标 中标 投资 when:14d",
                "国家电网 南方电网 设备 订单 项目 when:14d",
                "特高压 项目 核准 开工 政策 投资 when:30d",
            ],
            "pos_words": ["中标", "开工", "提速", "投资增加", "超预期", "扩容", "落地"],
            "neg_words": ["延期", "取消", "放缓", "下调", "低于预期", "推迟"],
            "summary_prefix": "电网设备政策与订单投资节奏跟踪（特高压/配网/中标订单/项目核准）",
        },
        {
            "title": "电网设备景气与供需趋势信号",
            "source": "Power Grid Demand-Supply Signal",
            "queries": [
                "电网设备 景气 需求 出货 交付 供需 when:30d",
                "变压器 开关 电力设备 产能 利用率 订单 when:30d",
                "电网设备 原材料 成本 利润 交付 节奏 when:30d",
            ],
            "pos_words": ["景气回升", "需求改善", "出货增长", "交付提速", "供需改善", "高增", "超预期"],
            "neg_words": ["景气回落", "需求走弱", "出货下滑", "交付放缓", "供需失衡", "不及预期", "承压"],
            "summary_prefix": "电网设备景气与供需跟踪（需求/出货/交付/供需）",
        },
        {
            "title": "电网设备成本价格趋势信号",
            "source": "Power Grid Price Signal",
            "queries": [
                "电网设备 原材料 价格 铜 铝 硅钢 成本 利润 when:30d",
                "变压器 线缆 成本 价格 传导 毛利 when:30d",
                "电力设备 价格 成本 压力 回落 提价 when:30d",
            ],
            "pos_words": ["成本回落", "价格传导", "毛利改善", "提价落地", "利润修复", "超预期"],
            "neg_words": ["成本上行", "毛利承压", "价格倒挂", "利润下滑", "不及预期"],
            "summary_prefix": "电网设备成本与价格传导跟踪（铜铝硅钢/提价/毛利）",
        },
        {
            "title": "商用卫星发射组网趋势信号",
            "source": "Satellite Structured Signal",
            "queries": [
                "商用卫星 发射 组网 订单 牌照 when:14d",
                "卫星互联网 低轨 频轨 招标 标准 when:14d",
                "商业航天 发射 组网 订单 卫星互联网 进展 when:30d",
            ],
            "pos_words": ["发射成功", "组网推进", "订单落地", "政策推进", "牌照进展", "标准成立", "提速"],
            "neg_words": ["发射失败", "延期", "推迟", "订单取消", "进展不及预期", "受阻"],
            "summary_prefix": "商用卫星发射与组网进展跟踪（发射/组网/牌照/订单）",
        },
        {
            "title": "商用卫星订单与商业化供需趋势信号",
            "source": "Satellite Order-Demand Signal",
            "queries": [
                "卫星通信 订单 招标 终端 商业化 需求 when:30d",
                "卫星互联网 终端 订单 交付 应用落地 when:30d",
                "低轨卫星 通信应用 商业化 供需 进展 when:30d",
            ],
            "pos_words": ["订单增长", "订单落地", "商业化推进", "需求回暖", "应用落地", "交付提速", "扩容"],
            "neg_words": ["订单取消", "订单下滑", "商业化受阻", "需求不足", "交付延后", "放缓"],
            "summary_prefix": "商用卫星订单与商业化供需跟踪（终端订单/应用落地/商业化）",
        },
        {
            "title": "商用卫星产业链成本价格趋势信号",
            "source": "Satellite Price Signal",
            "queries": [
                "商用卫星 成本 价格 毛利 商业化 when:14d",
                "卫星互联网 终端 成本 价格 交付 when:14d",
                "商用卫星 制造成本 发射成本 价格 产业链 毛利 when:30d",
                "卫星通信 终端成本 芯片器件 价格 交付 when:30d",
                "商业航天 成本 价格 订单 盈利能力 when:30d",
                "satellite launch cost pricing margins commercial space when:14d",
                "satellite communication terminal cost price demand when:14d",
            ],
            "pos_words": ["成本下降", "成本优化", "毛利改善", "价格提升", "盈利改善", "降本增效"],
            "neg_words": ["成本上升", "毛利下滑", "价格承压", "盈利承压", "降价竞争"],
            "summary_prefix": "商用卫星产业链成本与价格跟踪（制造/发射/终端/毛利）",
            "use_global_feed": True,
        },
        {
            "title": "商用卫星政策与标准推进趋势信号",
            "source": "Satellite Policy Signal",
            "queries": [
                "卫星互联网 标准委 政策 指引 牌照 频轨 when:30d",
                "商业航天 政策 推进 低轨 卫星互联网 when:30d",
                "国家航天局 商业航天 政策 进展 卫星互联网 when:30d",
            ],
            "pos_words": ["成立", "推进", "发布", "落地", "提速", "批复", "核准"],
            "neg_words": ["推迟", "搁置", "暂停", "受阻", "不及预期"],
            "summary_prefix": "商用卫星政策与标准推进跟踪（标准委/牌照/频轨）",
        },
    ]

    for definition in theme_defs:
        rows = collect_google_news_documents(
            queries=definition["queries"],
            max_items_per_query=8,
            timeout=timeout,
            hl="zh-CN",
            gl="CN",
            ceid="CN:zh-Hans",
            verbose=verbose,
        )
        if definition.get("use_global_feed", False):
            rows_en = collect_google_news_documents(
                queries=definition["queries"],
                max_items_per_query=6,
                timeout=timeout,
                hl="en-US",
                gl="US",
                ceid="US:en",
                verbose=verbose,
            )
            dedup: Dict[str, CollectedDocument] = {}
            for row in rows + rows_en:
                dedup[row.title] = row
            rows = list(dedup.values())
        if not rows:
            continue

        pos = 0
        neg = 0
        latest = ""
        for row in rows:
            t = (row.title or "").lower()
            if any(w in t for w in definition["pos_words"]):
                pos += 1
            if any(w in t for w in definition["neg_words"]):
                neg += 1
            d = (row.published_at or "").strip()
            if d and d > latest:
                latest = d
        if not latest:
            latest = _now_iso()
        # Freshness hard gate for structured thematic docs: skip stale synthetic docs.
        age_ok = True
        try:
            dt_latest = datetime.strptime(latest, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            age_ok = (datetime.now(timezone.utc) - dt_latest).days <= 21
        except Exception:
            age_ok = False
        if not age_ok:
            continue

        if pos > neg:
            trend = "偏强"
        elif neg > pos:
            trend = "偏弱"
        else:
            trend = "中性"
        sentence = (
            f"{latest}，{definition['summary_prefix']}：近14天正向信号{pos}条、负向信号{neg}条，"
            f"趋势{trend}。"
        )
        docs.append(
            CollectedDocument(
                title=definition["title"],
                url="https://news.google.com/",
                content=sentence,
                source=definition["source"],
                source_type="media",
                source_tier="B",
                category="top_tier_media",
                published_at=latest,
            )
        )

    return docs


def _yahoo_chart(symbol: str, timeout: float) -> Dict[str, Any]:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + parse.quote(symbol)
        + "?range=1mo&interval=1d"
    )
    raw = _fetch_url(url, timeout=timeout)
    return json.loads(raw)


def _series_from_yahoo(payload: Dict[str, Any]) -> Tuple[List[int], List[float], List[float]]:
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    timestamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [None])[0] or {})
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    triples: List[Tuple[int, float, float]] = []
    for ts, c, v in zip(timestamps, closes, volumes):
        if c is None:
            continue
        vv = float(v) if v is not None else 0.0
        triples.append((int(ts), float(c), vv))
    if not triples:
        return [], [], []
    ts_out = [x[0] for x in triples]
    close_out = [x[1] for x in triples]
    vol_out = [x[2] for x in triples]
    return ts_out, close_out, vol_out


def _weekly_return_and_volume(closes: List[float], volumes: List[float]) -> Tuple[float, float] | None:
    if len(closes) < 3:
        return None
    latest = closes[-1]
    prev = closes[-6] if len(closes) >= 6 else closes[0]
    if prev in (0, None):
        return None
    ret = latest / prev - 1.0

    if len(volumes) >= 10:
        v_curr = sum(volumes[-5:]) / 5.0
        v_prev = sum(volumes[-10:-5]) / 5.0
    elif len(volumes) >= 6:
        v_curr = sum(volumes[-3:]) / 3.0
        v_prev = sum(volumes[-6:-3]) / 3.0
    else:
        v_curr = volumes[-1] if volumes else 0.0
        v_prev = volumes[0] if volumes else 0.0
    vol_chg = 0.0 if v_prev in (0, None) else (v_curr / v_prev - 1.0)
    return ret, vol_chg


def collect_satellite_price_proxy_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Collect weekly satellite-industry equity proxy basket move from free Yahoo endpoints."""
    proxy_symbols = {
        "RKLB": "Rocket Lab",
        "ASTS": "AST SpaceMobile",
        "IRDM": "Iridium",
    }
    changes: List[float] = []
    latest_dt = ""
    covered = 0
    for symbol in proxy_symbols:
        try:
            payload = _yahoo_chart(symbol, timeout=timeout)
            timestamps, closes, volumes = _series_from_yahoo(payload)
            if len(closes) < 3:
                continue
            rv = _weekly_return_and_volume(closes, volumes)
            if not rv:
                continue
            ret = rv[0] * 100.0
            changes.append(ret)
            covered += 1
            dt = datetime.fromtimestamp(int(timestamps[-1]), tz=timezone.utc).strftime("%Y-%m-%d")
            if dt > latest_dt:
                latest_dt = dt
        except Exception as exc:
            if verbose:
                print(f"[collect] satellite proxy fail: {symbol} ({exc})")
            continue

    if not changes or not latest_dt:
        return []
    avg = sum(changes) / len(changes)
    move = "上行" if avg > 0.25 else "下行" if avg < -0.25 else "震荡"
    sentence = (
        f"{latest_dt}，商用卫星产业链价格代理篮子（{covered}只美股卫星相关公司）近一周{move}{abs(avg):.2f}% ，"
        "可作为卫星主题价格与估值情绪的辅助变量。"
    )
    return [
        CollectedDocument(
            title="商用卫星产业链价格代理周度变化快照",
            url="https://finance.yahoo.com/",
            content=sentence,
            source="Yahoo Finance API",
            source_type="media",
            source_tier="B",
            category="top_tier_media",
            published_at=latest_dt,
        )
    ]


def collect_market_variable_documents(timeout: float = 10.0, verbose: bool = False) -> List[CollectedDocument]:
    """Collect free market variable snapshots (gold/dollar/yield) as synthetic event docs."""
    symbols = {
        "GC=F": "COMEX黄金",
        "DX-Y.NYB": "美元指数",
        "^TNX": "美国10Y国债收益率",
        "^VIX": "VIX波动率指数",
    }
    docs: List[CollectedDocument] = []
    for symbol, name in symbols.items():
        try:
            payload = _yahoo_chart(symbol, timeout=timeout)
            timestamps, closes, volumes = _series_from_yahoo(payload)
            if len(closes) < 3:
                continue
            ret_vol = _weekly_return_and_volume(closes, volumes)
            if not ret_vol:
                continue
            ts_latest = timestamps[-1]
            change = ret_vol[0] * 100.0
            dt = datetime.fromtimestamp(int(ts_latest), tz=timezone.utc).strftime("%Y-%m-%d")
            move = "上行" if change > 0.05 else "下行" if change < -0.05 else "波动"
            if name == "美元指数":
                sentence = f"{dt}，{name}近一周{move}{abs(change):.2f}% ，对黄金定价有直接影响，属于可验证市场变量变化。"
            elif name == "美国10Y国债收益率":
                sentence = f"{dt}，{name}近一周{move}{abs(change):.2f}% ，属于利率核心变量，对债券与黄金估值有影响。"
            elif name == "VIX波动率指数":
                risk = "回落" if move == "下行" else "抬升" if move == "上行" else "震荡"
                sentence = f"{dt}，{name}近一周{move}{abs(change):.2f}% ，风险偏好{risk}，可作为宽基风格变量。"
            else:
                sentence = f"{dt}，{name}近一周{move}{abs(change):.2f}% ，属于可验证市场变量变化。"
            docs.append(
                CollectedDocument(
                    title=f"{name}周度变化快照",
                    url=f"https://finance.yahoo.com/quote/{parse.quote(symbol)}",
                    content=sentence,
                    source="Yahoo Finance API",
                    source_type="media",
                    source_tier="B",
                    category="top_tier_media",
                    published_at=dt,
                )
            )
        except Exception as exc:
            if verbose:
                print(f"[collect] market snapshot fail: {symbol} ({exc})")
            continue
    # Broad-equity index snapshot (as macro style/risk appetite proxy).
    index_symbols = {
        "000905.SS": "中证500指数",
        "000001.SS": "上证综指",
    }
    for symbol, name in index_symbols.items():
        try:
            payload = _yahoo_chart(symbol, timeout=timeout)
            timestamps, closes, volumes = _series_from_yahoo(payload)
            if len(closes) < 3:
                continue
            ret_vol = _weekly_return_and_volume(closes, volumes)
            if not ret_vol:
                continue
            ts_latest = timestamps[-1]
            change = ret_vol[0] * 100.0
            dt = datetime.fromtimestamp(int(ts_latest), tz=timezone.utc).strftime("%Y-%m-%d")
            move = "上行" if change > 0.2 else "下行" if change < -0.2 else "震荡"
            risk = "回升" if move == "上行" else "回落" if move == "下行" else "震荡"
            sentence = f"{dt}，{name}近一周{move}{abs(change):.2f}% ，风险偏好{risk}，可作为宽基风格变量。"
            docs.append(
                CollectedDocument(
                    title=f"{name}周度变化快照",
                    url=f"https://finance.yahoo.com/quote/{parse.quote(symbol)}",
                    content=sentence,
                    source="Yahoo Finance API",
                    source_type="media",
                    source_tier="B",
                    category="top_tier_media",
                    published_at=dt,
                )
            )
            break
        except Exception as exc:
            if verbose:
                print(f"[collect] equity index snapshot fail: {symbol} ({exc})")
            continue
    # Yahoo proxy variables to avoid unstable external endpoints:
    # TIP as real-yield inverse proxy, GLD as gold-ETF activity proxy.
    proxy_symbols = {
        "TIP": "美国实际利率代理(TIP)",
        "GLD": "黄金ETF代理(GLD)",
    }
    proxy_points: Dict[str, Tuple[str, float, float]] = {}
    for symbol, name in proxy_symbols.items():
        try:
            payload = _yahoo_chart(symbol, timeout=timeout)
            timestamps, closes, volumes = _series_from_yahoo(payload)
            if len(closes) < 3:
                continue
            ret_vol = _weekly_return_and_volume(closes, volumes)
            if not ret_vol:
                continue
            ts_latest = timestamps[-1]
            change = ret_vol[0] * 100.0
            dt = datetime.fromtimestamp(int(ts_latest), tz=timezone.utc).strftime("%Y-%m-%d")
            proxy_points[symbol] = (dt, change, float(closes[-1]))
            if symbol == "TIP":
                move = "上行" if change > 0.15 else "下行" if change < -0.15 else "震荡"
                real_yield_dir = "下行" if move == "上行" else "上行" if move == "下行" else "震荡"
                sentence = (
                    f"{dt}，{name}近一周{move}{abs(change):.2f}% ，对应美国实际利率{real_yield_dir}，"
                    "属于黄金定价核心变量。"
                )
            else:
                move = "上行" if change > 0.2 else "下行" if change < -0.2 else "震荡"
                vol_change = ret_vol[1] * 100.0
                vol_move = "放大" if vol_change > 5 else "收缩" if vol_change < -5 else "平稳"
                flow_hint = "净流出压力上升" if move == "下行" and vol_move == "放大" else "资金活跃度改善" if move == "上行" and vol_move == "放大" else "资金流向信号中性"
                sentence = (
                    f"{dt}，{name}近一周{move}{abs(change):.2f}% ，成交量{vol_move}{abs(vol_change):.2f}% ，"
                    f"{flow_hint}。"
                )
            docs.append(
                CollectedDocument(
                    title=f"{name}周度变化快照",
                    url=f"https://finance.yahoo.com/quote/{parse.quote(symbol)}",
                    content=sentence,
                    source="Yahoo Finance API",
                    source_type="media",
                    source_tier="B",
                    category="top_tier_media",
                    published_at=dt,
                )
            )
        except Exception as exc:
            if verbose:
                print(f"[collect] proxy snapshot fail: {symbol} ({exc})")
            continue

    # Credit spread proxy: HYG vs IEF weekly relative performance.
    try:
        p_hyg = _yahoo_chart("HYG", timeout=timeout)
        p_ief = _yahoo_chart("IEF", timeout=timeout)
        def _latest_and_prev(payload: Dict[str, Any]) -> Tuple[str, float, float] | None:
            result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
            timestamps = result.get("timestamp") or []
            quote = (((result.get("indicators") or {}).get("quote") or [None])[0] or {})
            closes = quote.get("close") or []
            points = [(ts, c) for ts, c in zip(timestamps, closes) if c is not None]
            if len(points) < 3:
                return None
            ts_latest, close_latest = points[-1]
            _, close_prev = points[-6] if len(points) >= 6 else points[0]
            if close_prev in (None, 0):
                return None
            dt = datetime.fromtimestamp(int(ts_latest), tz=timezone.utc).strftime("%Y-%m-%d")
            return dt, float(close_latest), float(close_prev)
        s_hyg = _latest_and_prev(p_hyg)
        s_ief = _latest_and_prev(p_ief)
        if s_hyg and s_ief:
            dt = s_hyg[0]
            hyg_ret = s_hyg[1] / s_hyg[2] - 1.0
            ief_ret = s_ief[1] / s_ief[2] - 1.0
            spread_proxy = (hyg_ret - ief_ret) * 100.0
            move = "走阔" if spread_proxy < -0.25 else "收窄" if spread_proxy > 0.25 else "震荡"
            sentence = f"{dt}，信用利差代理(HYG-IEF)近一周{move}{abs(spread_proxy):.2f}个百分点，属于信用风险变量。"
            docs.append(
                CollectedDocument(
                    title="信用利差代理周度变化快照",
                    url="https://finance.yahoo.com/quote/HYG",
                    content=sentence,
                    source="Yahoo Finance API",
                    source_type="media",
                    source_tier="B",
                    category="top_tier_media",
                    published_at=dt,
                )
            )
    except Exception as exc:
        if verbose:
            print(f"[collect] credit spread proxy fail: {exc}")

    # Redemption-pressure proxy for credit bonds.
    try:
        p_hyg = _yahoo_chart("HYG", timeout=timeout)
        ts_hyg, c_hyg, v_hyg = _series_from_yahoo(p_hyg)
        rv = _weekly_return_and_volume(c_hyg, v_hyg)
        if ts_hyg and rv:
            dt = datetime.fromtimestamp(int(ts_hyg[-1]), tz=timezone.utc).strftime("%Y-%m-%d")
            ret = rv[0] * 100.0
            vol = rv[1] * 100.0
            pressure = "申赎压力上升" if ret < -0.2 and vol > 5 else "申赎压力缓解" if ret > 0.2 and vol > 5 else "申赎压力中性"
            sentence = f"{dt}，信用债ETF(HYG)近一周{'下行' if ret < 0 else '上行'}{abs(ret):.2f}% ，成交量{'放大' if vol > 0 else '收缩'}{abs(vol):.2f}% ，{pressure}。"
            docs.append(
                CollectedDocument(
                    title="信用债申赎压力代理周度变化快照",
                    url="https://finance.yahoo.com/quote/HYG",
                    content=sentence,
                    source="Yahoo Finance API",
                    source_type="media",
                    source_tier="B",
                    category="top_tier_media",
                    published_at=dt,
                )
            )
    except Exception as exc:
        if verbose:
            print(f"[collect] redemption proxy fail: {exc}")
    return docs
