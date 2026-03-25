"""Free/public fund NAV collector for realized-outcome evaluation."""

from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from typing import Dict, List
from urllib.parse import urlencode
from urllib.request import urlopen


NAV_API = "https://fundf10.eastmoney.com/F10DataApi.aspx"


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", text)
    return unescape(cleaned).strip()


def _parse_table_rows(html: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, flags=re.S | re.I):
        cols = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)
        if len(cols) < 2:
            continue
        date_text = _strip_html(cols[0])
        nav_text = _strip_html(cols[1])
        if not date_text or not nav_text:
            continue
        if not re.match(r"\d{4}-\d{2}-\d{2}", date_text):
            continue
        try:
            nav = float(nav_text)
        except ValueError:
            continue
        rows.append({"date": date_text, "nav": nav})
    return rows


def fetch_fund_nav_series(
    fund_code: str,
    start_date: str,
    end_date: str,
    timeout: float = 10.0,
    per_page: int = 49,
    max_pages: int = 60,
) -> List[Dict[str, float | str]]:
    """Fetch fund NAV rows from Eastmoney public API."""
    rows: List[Dict[str, float | str]] = []
    for page in range(1, max_pages + 1):
        query = urlencode(
            {
                "type": "lsjz",
                "code": fund_code,
                "page": page,
                "per": per_page,
                "sdate": start_date,
                "edate": end_date,
            }
        )
        url = f"{NAV_API}?{query}"
        req_rows: List[Dict[str, float | str]] = []
        with urlopen(url, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            req_rows = _parse_table_rows(html)
        if not req_rows:
            break
        rows.extend(req_rows)
        if len(req_rows) < per_page:
            break
    # API returns latest first; convert to ascending date order.
    unique_by_date: Dict[str, float] = {}
    for r in rows:
        unique_by_date[str(r["date"])] = float(r["nav"])
    ordered = [{"date": d, "nav": v} for d, v in sorted(unique_by_date.items(), key=lambda x: x[0])]
    return ordered


def date_minus_days(date_str: str, days: int) -> str:
    """Return YYYY-MM-DD minus N calendar days."""
    dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
    from datetime import timedelta

    return (dt - timedelta(days=days)).strftime("%Y-%m-%d")
