#!/usr/bin/env python3
import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple
from urllib import parse, request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEEDS_FILE = ROOT / "configs" / "source_seeds.yaml"
GENERIC_TITLE_HINTS = {
    "首页",
    "home",
    "welcome",
    "index",
    "主页",
    "网站首页",
}
DETAIL_TEXT_HINTS = [
    "公告",
    "通知",
    "新闻",
    "政策",
    "解读",
    "快讯",
    "资讯",
    "公示",
]
DETAIL_URL_HINTS = [
    "content",
    "article",
    "detail",
    "news",
    "notice",
    "zhengce",
    "gonggao",
    "xinwen",
]
STATIC_BG_URL_HINTS = [
    "/fund/",
    "fundinfo",
    "funddetail",
    "fundrecord",
]
FUND_RELEVANCE_HINTS: Dict[str, Dict[str, List[str]]] = {
    "002963": {
        "positive": ["黄金", "金锭", "保证金", "涨跌停板", "au", "避险", "购金", "利率", "美元"],
        "negative": ["国际会员", "企业名称变更", "退会", "吸收"],
    },
    "024194": {
        "positive": ["卫星", "组网", "发射", "星座", "通信", "频轨", "牌照", "商用", "航天"],
        "negative": ["会员资格", "更名", "友情链接"],
    },
    "011035": {
        "positive": ["稀土", "永磁", "开采", "冶炼", "分离", "配额", "供给"],
        "negative": ["会员资格", "更名", "招聘"],
    },
    "025832": {
        "positive": ["电网", "特高压", "配网", "智能电网", "招标", "订单"],
        "negative": ["会员资格", "更名", "友情链接"],
    },
    "007028": {
        "positive": ["中证500", "流动性", "风险偏好", "风格轮动", "政策", "宏观"],
        "negative": ["会员资格", "更名", "友情链接"],
    },
    "217023": {
        "positive": ["信用", "利差", "债券", "流动性", "违约", "利率"],
        "negative": ["会员资格", "更名", "友情链接"],
    },
    "007951": {
        "positive": ["信用", "利差", "债券", "流动性", "违约", "利率"],
        "negative": ["会员资格", "更名", "友情链接"],
    },
}
NOISE_LINE_PATTERNS = [
    r"^首页$",
    r"^搜索$",
    r"^友情链接$",
    r"^会员专区$",
    r"^信息提示$",
    r"^提示文字$",
    r"^确认$",
    r"^取消$",
    r"^International Business$",
    r"^Copyright",
    r"沪ICP备",
    r"沪公网安备",
    r"电话[:：]",
    r"传真[:：]",
]
NOISE_TEXT_HINTS = [
    "关于上金所",
    "交易所介绍",
    "品牌中心",
    "新闻中心",
    "产品服务",
    "数据资讯",
    "会员专区",
    "投资者服务",
    "制度与规则",
    "国际交流与合作",
    "人才招聘",
    "联系我们",
    "聚焦二十大",
    "媒体报道",
    "交易所新闻",
    "友情链接",
    "会员单位专栏",
    "战略合作伙伴",
    "官方微信",
    "信息提示",
]


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def parse_seed_yaml(path: Path) -> Dict[str, List[str]]:
    """
    Minimal parser for configs/source_seeds.yaml expected shape:
    funds:
      "024194":
        urls:
          - "https://..."
    """
    if not path.exists():
        raise FileNotFoundError(f"Seeds file not found: {path}")

    # Preferred path: yaml.safe_load when PyYAML exists.
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out: Dict[str, List[str]] = {}
        fund_map = data.get("funds", {})
        if isinstance(fund_map, dict):
            for code, meta in fund_map.items():
                if not re.fullmatch(r"\d{6}", str(code)):
                    continue
                urls = []
                if isinstance(meta, dict) and isinstance(meta.get("urls"), list):
                    urls = [str(u).strip() for u in meta.get("urls", []) if str(u).strip()]
                out[str(code)] = urls
        return out
    except Exception:
        # Fallback parser to keep zero-extra-install behavior.
        pass

    funds: Dict[str, List[str]] = {}
    in_funds = False
    current_code = ""
    in_urls = False

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped == "funds:":
            in_funds = True
            current_code = ""
            in_urls = False
            continue

        if not in_funds:
            continue

        m_code = re.match(r'^\s{2}"?([0-9]{6})"?:\s*$', line)
        if m_code:
            current_code = m_code.group(1)
            funds.setdefault(current_code, [])
            in_urls = False
            continue

        if current_code and re.match(r"^\s{4}urls:\s*$", line):
            in_urls = True
            continue

        if current_code and in_urls:
            m_url = re.match(r"^\s{6}-\s*\"?([^\"]+)\"?\s*$", line)
            if m_url:
                funds[current_code].append(m_url.group(1).strip())
                continue

            # exited urls section when indentation changes
            if not line.startswith("      "):
                in_urls = False

    return funds


def read_urls_file(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"URLs file not found: {path}")
    urls: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def derive_source(url: str) -> str:
    host = parse.urlparse(url).netloc.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def decode_response(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    m = re.search(r"charset=([\w\-]+)", content_type or "", flags=re.IGNORECASE)
    if m:
        charset = m.group(1).strip()
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def strip_html(html_text: str) -> str:
    txt = re.sub(r"<!--.*?-->", " ", html_text, flags=re.DOTALL)
    txt = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", txt, flags=re.DOTALL | re.IGNORECASE)
    txt = re.sub(r"<(br|p|div|li|h1|h2|h3|h4|h5|h6|tr|section|article)[^>]*>", "\n", txt, flags=re.IGNORECASE)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    txt = re.sub(r"\r", "\n", txt)
    txt = re.sub(r"[ \t\f\v]+", " ", txt)
    txt = re.sub(r"\n{2,}", "\n\n", txt)
    return txt.strip()


def extract_main_content(html_text: str) -> str:
    candidates: List[str] = []
    block_patterns = [
        r"<article[^>]*>(.*?)</article>",
        r"<main[^>]*>(.*?)</main>",
        r"<div[^>]+(?:id|class)=[\"'][^\"']*(?:content|article|post|detail|text|news)[^\"']*[\"'][^>]*>(.*?)</div>",
    ]
    for p in block_patterns:
        for m in re.finditer(p, html_text, flags=re.IGNORECASE | re.DOTALL):
            chunk = strip_html(m.group(1))
            if chunk:
                candidates.append(chunk)

    whole = strip_html(html_text)
    if whole:
        candidates.append(whole)

    if not candidates:
        return ""
    candidates.sort(key=len, reverse=True)
    return candidates[0]


def extract_title(html_text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    title = html.unescape(m.group(1))
    title = re.sub(r"\s+", " ", title).strip()
    return title


def extract_publish_time(html_text: str) -> str:
    # Prefer explicit body-style timestamp markers often used in announcements.
    body_patterns = [
        r"(?:来源[:：]\s*)?时间[:：]\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)",
        r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)\s*(?:发布|公告|更新)",
    ]
    for p in body_patterns:
        m = re.search(p, html_text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()

    meta_patterns = [
        r'<meta[^>]+(?:property|name)=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+(?:property|name)=["\']publishdate["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+(?:property|name)=["\']pubdate["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+(?:property|name)=["\']date["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+(?:property|name)=["\']dc.date["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for p in meta_patterns:
        m = re.search(p, html_text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()

    m = re.search(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)", html_text)
    if m:
        return m.group(1).strip()
    return ""


def normalize_date_text(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    t = t.replace("年", "-").replace("月", "-").replace("日", "")
    t = t.replace("/", "-").replace(".", "-")
    t = re.sub(r"-{2,}", "-", t)
    m = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", t)
    if not m:
        return ""
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def extract_publish_time_from_content(content: str) -> str:
    txt = content or ""
    patterns = [
        r"(?:来源[:：]\s*)?时间[:：]\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)",
        r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)",
    ]
    for p in patterns:
        m = re.search(p, txt)
        if m:
            norm = normalize_date_text(m.group(1))
            if norm:
                return norm
    return ""


def fetch_url(url: str, timeout_sec: int, user_agent: str) -> Tuple[str, str]:
    req = request.Request(url, headers={"User-Agent": user_agent})
    with request.urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read()
        content_type = resp.headers.get("Content-Type", "")
        html_text = decode_response(body, content_type)
        final_url = resp.geturl()
        return final_url, html_text


def build_doc(url: str, final_url: str, html_text: str, fund_code: str, idx: int) -> Dict[str, str]:
    cleaned = extract_main_content(html_text)
    title = extract_title(html_text)
    publish_time = extract_publish_time(html_text)
    source = derive_source(final_url or url)

    base = final_url or url
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    code = fund_code if fund_code else "generic"
    doc_id = f"{code}-{idx:03d}-{digest}"

    # Keep content bounded for downstream prompt cost/stability.
    content = cleaned[:8000]

    return {
        "doc_id": doc_id,
        "url": final_url or url,
        "source": source,
        "title": title,
        "publish_time": publish_time,
        "content": content,
    }


def chinese_char_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def is_generic_title(title: str) -> bool:
    t = (title or "").strip().lower()
    if not t:
        return True
    if t in GENERIC_TITLE_HINTS:
        return True
    # e.g. "首页-xxx", "xxx-首页"
    if "首页" in t and len(t) <= 20:
        return True
    return False


def quality_check(doc: Dict[str, str]) -> Tuple[bool, str]:
    title = doc.get("title", "").strip()
    content = doc.get("content", "").strip()
    cjk = chinese_char_count(content)

    if len(content) < 180:
        return False, "content_too_short"
    if is_generic_title(title) and len(content) < 1200:
        return False, "generic_title_and_thin_content"
    if cjk < 60 and len(content) < 500:
        return False, "too_few_chinese_effective_text"
    return True, ""


def classify_page_type(url: str, title: str, publish_time: str, content: str) -> str:
    u = (url or "").lower()
    t = (title or "").lower()
    content_len = len(content or "")
    p = parse.urlparse(url)
    path = (p.path or "").strip("/").lower()

    if any(k in u for k in STATIC_BG_URL_HINTS):
        return "static_background"
    if "基金" in title and ("详情" in title or "档案" in title or "净值" in title):
        return "static_background"

    # Landing-like URLs should be identified before publish_time heuristics.
    if not path or path in {"index.html", "index.htm"}:
        return "landing"
    if any(k in path for k in ["ztzl", "channel", "columns", "index", "list"]):
        return "landing"
    if any(k in t for k in ["首页", "门户网站", "欢迎"]):
        return "landing"
    # Common list page paths (e.g., /jjsnotice, /xwzx/NewsCenter_sge).
    if any(k in path for k in ["newscenter", "jjsnotice", "list"]) and not re.search(r"\d{5,}", path):
        return "landing"

    if publish_time:
        return "article_detail"
    if any(k in u for k in DETAIL_URL_HINTS):
        return "article_detail"
    if any(k in t for k in [x.lower() for x in DETAIL_TEXT_HINTS]):
        return "article_detail"

    if content_len < 1200:
        return "landing"
    return "article_detail"


def extract_detail_links(html_text: str, base_url: str, limit: int = 8) -> List[str]:
    base = parse.urlparse(base_url)
    base_host = base.netloc.lower()
    candidates: List[Tuple[int, str]] = []

    for m in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html_text, flags=re.IGNORECASE | re.DOTALL):
        href = (m.group(1) or "").strip()
        anchor = strip_html(m.group(2) or "")
        if not href:
            continue
        if href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full = parse.urljoin(base_url, href)
        u = parse.urlparse(full)
        if u.scheme not in {"http", "https"}:
            continue
        if u.netloc.lower() != base_host:
            continue
        low_url = full.lower()
        if any(low_url.endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".png", ".zip"]):
            continue

        score = 0
        if any(k in low_url for k in DETAIL_URL_HINTS):
            score += 2
        if any(k in anchor for k in DETAIL_TEXT_HINTS):
            score += 3
        if re.search(r"20\d{2}[-_/]\d{1,2}[-_/]\d{1,2}", low_url):
            score += 2
        if len(anchor) >= 8:
            score += 1
        if score > 0:
            candidates.append((score, full))

    seen = set()
    out: List[str] = []
    for _, link in sorted(candidates, key=lambda x: x[0], reverse=True):
        if link in seen:
            continue
        seen.add(link)
        out.append(link)
        if len(out) >= limit:
            break
    return out


def extract_body_title(html_text: str, content: str, page_type: str) -> str:
    if page_type != "article_detail":
        return ""

    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if h1:
        t = strip_html(h1.group(1)).strip()
        if len(t) >= 6:
            return t

    for line in (content or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if len(s) < 6 or len(s) > 80:
            continue
        if re.search(r"(通知|公告|意见|办法|会议|发布会|答记者问|解读)$", s):
            return s
        if s.startswith("关于") and len(s) <= 60:
            return s
    return ""


def purify_article_content(url: str, title: str, content: str) -> str:
    lines = [ln.strip() for ln in (content or "").splitlines()]
    lines = [ln for ln in lines if ln]
    filtered: List[str] = []
    for ln in lines:
        if any(re.search(p, ln, flags=re.IGNORECASE) for p in NOISE_LINE_PATTERNS):
            continue
        if any(h in ln for h in NOISE_TEXT_HINTS):
            continue
        # drop pure symbol lines and extremely short UI crumbs
        if re.fullmatch(r"[\W_]+", ln):
            continue
        if len(ln) <= 2 and not re.search(r"\d", ln):
            continue
        if ln.startswith("") or ln.startswith("") or ln.startswith(""):
            continue
        filtered.append(ln)

    text = "\n".join(filtered)
    if not text:
        return ""

    # Try to cut from the real heading section.
    if title:
        pos = text.find(title)
        if pos >= 0:
            text = text[pos:]

    # If timestamp marker exists, align around it to remove long nav headers.
    time_idx = min([i for i in [text.find("来源: 时间:"), text.find("来源：时间："), text.find("时间: "), text.find("时间：")] if i >= 0], default=-1)
    if time_idx > 0:
        # Keep at most ~120 chars before time marker (usually title + source line).
        start = max(0, time_idx - 120)
        text = text[start:]

    # Trim common tail noise blocks.
    cut_marks = ["相关公告", "分享到", "友情链接", "Copyright", "会员单位专栏", "战略合作伙伴"]
    cut_pos = [text.find(m) for m in cut_marks if text.find(m) >= 0]
    if cut_pos:
        text = text[: min(cut_pos)].strip()

    # Keep title/time/body coherence.
    if title and title not in text[:120]:
        text = f"{title}\n{text}"
    return text[:5000]


def score_article_relevance(fund_code: str, title: str, content: str) -> int:
    cfg = FUND_RELEVANCE_HINTS.get(fund_code or "", {})
    pos = cfg.get("positive", [])
    neg = cfg.get("negative", [])
    title_l = (title or "").lower()
    body = (content or "")[:1200].lower()
    text = f"{title_l} {body}"
    score = 0
    for kw in pos:
        k = kw.lower()
        if k in title_l:
            score += 3
        elif k in text:
            score += 1
    for kw in neg:
        k = kw.lower()
        if k in title_l:
            score -= 3
        elif k in text:
            score -= 1
    return score


def summarize_static_background(title: str, content: str) -> str:
    text = (content or "").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)

    def grab(label: str, stop_labels: List[str], max_len: int = 300) -> str:
        stop = "|".join(re.escape(x) for x in stop_labels)
        pattern = rf"{re.escape(label)}\s*[:：]\s*(.*?)(?:\n(?:{stop})\s*[:：]|\Z)"
        m = re.search(pattern, text, flags=re.DOTALL)
        if not m:
            return ""
        v = m.group(1).strip()
        v = re.sub(r"\s+", " ", v)
        return v[:max_len]

    fund_short = grab("基金简称", ["基金代码", "基金类型", "成立日期"])
    fund_code = grab("基金代码", ["基金类型", "成立日期", "基金管理人"], max_len=40)
    index_name = grab("标的指数名称", ["投资比例", "投资目标", "业绩比较基准", "风险收益特征"], max_len=120)
    invest_scope = grab("投资范围", ["标的指数名称", "投资比例", "投资目标", "业绩比较基准"], max_len=360)
    bench = grab("业绩比较基准", ["风险收益特征", "基金经理", "费率结构"], max_len=220)
    risk = grab("风险收益特征", ["基金经理", "费率结构", "资产组合"], max_len=220)
    strategy = ""
    sm = re.search(
        r"报告期内基金投资策略和运作分析(.*?)(?:展开更多|历任基金经理|费率结构|资产组合|\Z)",
        text,
        flags=re.DOTALL,
    )
    if sm:
        strategy = re.sub(r"\s+", " ", sm.group(1)).strip()[:320]

    lines = [title.strip()]
    if fund_short or fund_code:
        lines.append(f"基金简称/代码：{fund_short} {fund_code}".strip())
    if index_name:
        lines.append(f"标的指数名称：{index_name}")
    if invest_scope:
        lines.append(f"投资范围：{invest_scope}")
    if bench:
        lines.append(f"业绩比较基准：{bench}")
    if risk:
        lines.append(f"风险收益特征：{risk}")
    if strategy:
        lines.append(f"季报关键策略：{strategy}")

    return "\n".join(x for x in lines if x).strip()[:1800]


def title_similarity_key(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[0-9０-９]", "", t)
    t = re.sub(r"[^\u4e00-\u9fffA-Za-z]", "", t)
    # remove frequent boilerplate words
    for w in ["通知", "公告", "关于"]:
        t = t.replace(w, "")
    return t[:40]


def dedupe_article_docs(article_docs: List[Dict[str, str]], skipped: List[Dict[str, str]]) -> List[Dict[str, str]]:
    chosen: Dict[str, Dict[str, str]] = {}
    for d in article_docs:
        key = title_similarity_key(d.get("title", ""))
        if not key:
            key = d.get("title", "")
        prev = chosen.get(key)
        if not prev:
            chosen[key] = d
            continue
        prev_date = normalize_date_text(prev.get("publish_time", ""))
        cur_date = normalize_date_text(d.get("publish_time", ""))
        prev_score = int(prev.get("_score", 0))
        cur_score = int(d.get("_score", 0))
        keep_cur = (cur_score > prev_score) or (cur_score == prev_score and cur_date > prev_date)
        if keep_cur:
            skipped.append(
                {
                    "url": prev.get("url", ""),
                    "reason": "duplicate_similar_title",
                    "title": prev.get("title", ""),
                    "kept_url": d.get("url", ""),
                }
            )
            chosen[key] = d
        else:
            skipped.append(
                {
                    "url": d.get("url", ""),
                    "reason": "duplicate_similar_title",
                    "title": d.get("title", ""),
                    "kept_url": prev.get("url", ""),
                }
            )
    return list(chosen.values())


def dedupe_urls(urls: List[str]) -> List[str]:
    seen = set()
    out = []
    for url in urls:
        u = url.strip()
        if not u:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def resolve_urls(args: argparse.Namespace) -> List[str]:
    urls: List[str] = []

    if args.urls_file:
        urls.extend(read_urls_file(Path(args.urls_file)))

    if args.fund_code:
        seeds = parse_seed_yaml(Path(args.seeds_file))
        urls.extend(seeds.get(args.fund_code, []))

    urls = dedupe_urls(urls)
    if args.max_urls > 0:
        urls = urls[: args.max_urls]
    return urls


def default_output_path(fund_code: str) -> Path:
    if fund_code:
        return ROOT / "sample_data" / f"{fund_code}_docs.json"
    return ROOT / "sample_data" / "urls_docs.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build docs.json from URL list (minimal fetch layer)")
    parser.add_argument("--fund-code", default="", help="Fund code for loading seeds and naming output")
    parser.add_argument("--urls-file", default="", help="Plain text URL file (one URL per line)")
    parser.add_argument("--seeds-file", default=str(DEFAULT_SEEDS_FILE), help="Seed YAML path")
    parser.add_argument("--output", default="", help="Output docs.json path")
    parser.add_argument("--max-urls", type=int, default=20, help="Maximum URLs to fetch")
    parser.add_argument("--max-detail-per-landing", type=int, default=8, help="Max detail links fetched from one landing page")
    parser.add_argument("--max-static-background", type=int, default=3, help="Max kept static background pages")
    parser.add_argument("--max-article-detail", type=int, default=20, help="Max kept article detail docs")
    parser.add_argument("--timeout", type=int, default=15, help="Per-request timeout seconds")
    parser.add_argument("--user-agent", default="fund-event-engine/0.1 (+minimal-fetch)")
    args = parser.parse_args()

    if not args.urls_file and not args.fund_code:
        raise SystemExit("Provide at least one source: --urls-file or --fund-code")

    urls = resolve_urls(args)
    if not urls:
        raise SystemExit("No URLs resolved from input")

    docs: List[Dict[str, str]] = []
    failures: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    seen_urls = set()
    static_bg_kept = 0
    doc_serial = 1

    eprint(f"[build_docs] fetching {len(urls)} urls...")
    for idx, url in enumerate(urls, start=1):
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            final_url, html_text = fetch_url(url, timeout_sec=args.timeout, user_agent=args.user_agent)
            doc = build_doc(url, final_url, html_text, args.fund_code, doc_serial)
            doc_serial += 1
            if not doc["content"] and not doc["title"]:
                raise ValueError("empty title/content after extraction")
            page_type = classify_page_type(doc["url"], doc["title"], doc["publish_time"], doc["content"])
            doc["page_type"] = page_type
            if page_type == "article_detail":
                better_title = extract_body_title(html_text, doc["content"], page_type)
                if better_title:
                    doc["title"] = better_title
                doc["content"] = purify_article_content(doc["url"], doc["title"], doc["content"])
                real_time = extract_publish_time_from_content(doc["content"])
                if real_time:
                    doc["publish_time"] = real_time

            if page_type == "landing":
                detail_links = extract_detail_links(html_text, doc["url"], limit=args.max_detail_per_landing)
                added_detail = 0
                for durl in detail_links:
                    if durl in seen_urls:
                        continue
                    seen_urls.add(durl)
                    try:
                        d_final, d_html = fetch_url(durl, timeout_sec=args.timeout, user_agent=args.user_agent)
                        d_doc = build_doc(durl, d_final, d_html, args.fund_code, doc_serial)
                        doc_serial += 1
                        d_doc["page_type"] = classify_page_type(d_doc["url"], d_doc["title"], d_doc["publish_time"], d_doc["content"])
                        if d_doc["page_type"] == "article_detail":
                            d_title = extract_body_title(d_html, d_doc["content"], d_doc["page_type"])
                            if d_title:
                                d_doc["title"] = d_title
                            d_doc["content"] = purify_article_content(d_doc["url"], d_doc["title"], d_doc["content"])
                            d_time = extract_publish_time_from_content(d_doc["content"])
                            if d_time:
                                d_doc["publish_time"] = d_time
                        if d_doc["page_type"] == "landing":
                            skipped.append({"url": durl, "reason": "landing_detail_not_used", "title": d_doc.get("title", "")})
                            continue
                        if d_doc["page_type"] == "static_background" and static_bg_kept >= args.max_static_background:
                            skipped.append({"url": durl, "reason": "static_background_limit", "title": d_doc.get("title", "")})
                            continue
                        ok, reason = quality_check(d_doc)
                        if not ok:
                            skipped.append({"url": durl, "reason": reason, "title": d_doc.get("title", "")})
                            continue
                        if d_doc["page_type"] == "static_background":
                            static_bg_kept += 1
                        docs.append(d_doc)
                        added_detail += 1
                    except Exception as dexc:  # noqa: BLE001
                        failures.append({"url": durl, "error": str(dexc)})
                        continue

                if added_detail > 0:
                    skipped.append({"url": doc["url"], "reason": "landing_has_details_use_details", "title": doc.get("title", "")})
                    eprint(f"[build_docs] ok {idx}/{len(urls)} {url} -> details:{added_detail}")
                    continue

            ok, reason = quality_check(doc)
            if not ok:
                skipped.append({"url": url, "reason": reason, "title": doc.get("title", "")})
                eprint(f"[build_docs] skip {idx}/{len(urls)} {url} :: {reason}")
                continue
            if doc["page_type"] == "static_background":
                if static_bg_kept >= args.max_static_background:
                    skipped.append({"url": url, "reason": "static_background_limit", "title": doc.get("title", "")})
                    continue
                doc["content"] = summarize_static_background(doc["title"], doc["content"])
                static_bg_kept += 1
            docs.append(doc)
            eprint(f"[build_docs] ok {idx}/{len(urls)} {url}")
        except Exception as exc:  # noqa: BLE001
            failures.append({"url": url, "error": str(exc)})
            eprint(f"[build_docs] fail {idx}/{len(urls)} {url} :: {exc}")
            continue

    # Final stage: strict landing filtering + article relevance ordering.
    article_docs = [d for d in docs if d.get("page_type") == "article_detail"]
    static_docs = [d for d in docs if d.get("page_type") == "static_background"]
    landing_docs = [d for d in docs if d.get("page_type") == "landing"]
    for d in article_docs:
        d["_score"] = score_article_relevance(args.fund_code, d.get("title", ""), d.get("content", ""))
    article_docs = dedupe_article_docs(article_docs, skipped)
    article_docs.sort(key=lambda x: (x.get("_score", 0), x.get("publish_time", ""), len(x.get("content", ""))), reverse=True)

    final_docs: List[Dict[str, str]] = []
    if article_docs:
        # Drop clearly low-relevance details when enough higher-signal details exist.
        hi = [d for d in article_docs if d.get("_score", 0) > 0]
        lo = [d for d in article_docs if d.get("_score", 0) <= 0]
        if len(hi) >= 3:
            for d in lo:
                skipped.append({"url": d.get("url", ""), "reason": "low_relevance_article_detail", "title": d.get("title", "")})
            article_docs = hi
        final_docs.extend(article_docs[: args.max_article_detail])
        final_docs.extend(static_docs[: args.max_static_background])
        for d in landing_docs:
            skipped.append({"url": d.get("url", ""), "reason": "landing_filtered_has_article_detail", "title": d.get("title", "")})
    else:
        final_docs.extend(static_docs[: args.max_static_background])
        final_docs.extend(landing_docs[:2])

    for d in final_docs:
        d.pop("_score", None)

    out_path = Path(args.output) if args.output else default_output_path(args.fund_code)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(final_docs, ensure_ascii=False, indent=2), encoding="utf-8")

    fail_path = out_path.with_suffix(".failures.json")
    fail_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    skipped_path = out_path.with_suffix(".skipped.json")
    skipped_path.write_text(json.dumps(skipped, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "output": str(out_path),
        "failures": str(fail_path),
        "skipped": str(skipped_path),
        "success_count": len(final_docs),
        "failure_count": len(failures),
        "skipped_count": len(skipped),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
