"""Text cleaning and page-chrome/noise filtering helpers."""

from __future__ import annotations

import html
import re
from typing import Dict, List


CHROME_PATTERNS = [
    r"导航",
    r"网站地图",
    r"帮助中心",
    r"联系我们",
    r"关于我们",
    r"免责声明",
    r"版权",
    r"友情链接",
    r"用户反馈",
    r"客服",
    r"隐私",
    r"页脚",
    r"返回顶部",
]
NOISE_PATTERNS = [
    r"推荐阅读",
    r"猜你喜欢",
    r"广告",
    r"扫码",
    r"点击下载",
    r"专题合集",
    r"责任编辑",
    r"转发",
    r"点赞",
    r"评论区",
    r"未经授权",
    r"净值下跌",
    r"净值上涨",
    r"涨跌幅",
    r"单位净值",
]
EVENT_HINT_PATTERNS = [
    r"发布",
    r"公告",
    r"披露",
    r"上调",
    r"下调",
    r"中标",
    r"签约",
    r"发射",
    r"落地",
    r"会议",
    r"数据",
    r"同比",
    r"环比",
    r"购金",
    r"降息",
    r"加息",
]
CODE_LIKE_PATTERNS = [
    r"\bvar\b",
    r"\bfunction\b",
    r"channelCode",
    r"channelId",
    r"\{.*\}",
    r";\s*$",
]


def clean_html(raw_html: str) -> str:
    """Strip tags and normalize whitespace."""
    txt = re.sub(r"<(script|style|noscript)[^>]*>.*?</\\1>", " ", raw_html, flags=re.I | re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def split_text_lines(text: str) -> List[str]:
    """Split text into short candidate lines for filtering."""
    chunks = re.split(r"[\n\r]+|。|；|;", text)
    return [c.strip() for c in chunks if c and c.strip()]


def classify_line(line: str) -> Dict[str, bool]:
    """Classify a line as chrome/noise/event-like."""
    is_chrome = any(re.search(p, line, flags=re.I) for p in CHROME_PATTERNS)
    noise_hit = any(re.search(p, line, flags=re.I) for p in NOISE_PATTERNS)
    has_date = bool(re.search(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?", line))
    has_event_hint = any(re.search(p, line, flags=re.I) for p in EVENT_HINT_PATTERNS)
    has_subject = bool(re.search(r"(国家|中国|央行|工信部|发改委|统计局|公司|集团|交易所|基金|银行|美联储)", line))
    is_code_like = any(re.search(p, line, flags=re.I) for p in CODE_LIKE_PATTERNS)
    is_noise = (noise_hit or is_code_like) and not is_chrome
    is_extractable = (has_date or has_subject) and has_event_hint and len(line) >= 18 and not is_noise

    return {
        "is_page_chrome": is_chrome,
        "is_noise": is_noise,
        "is_extractable": is_extractable and not is_chrome,
    }


def clean_and_score_text(text: str) -> Dict[str, object]:
    """Apply strict pre-extraction filtering and return quality metrics."""
    lines = split_text_lines(text)
    kept_lines: List[str] = []
    chrome_count = 0
    noise_count = 0
    extractable_count = 0

    for line in lines:
        flags = classify_line(line)
        if flags["is_page_chrome"]:
            chrome_count += 1
            continue
        if flags["is_noise"]:
            noise_count += 1
            continue
        kept_lines.append(line)
        if flags["is_extractable"]:
            extractable_count += 1

    total = max(1, len(lines))
    content_quality = max(0.0, min(1.0, (len(kept_lines) - noise_count * 0.3) / total))
    extractable_score = max(0.0, min(1.0, extractable_count / max(1, len(kept_lines))))

    return {
        "clean_text": "。".join(kept_lines).strip(),
        "noise_lines_filtered": noise_count,
        "chrome_lines_filtered": chrome_count,
        "content_quality_score": round(content_quality, 4),
        "extractable_event_score": round(extractable_score, 4),
        "extractable_event_count": extractable_count,
    }
