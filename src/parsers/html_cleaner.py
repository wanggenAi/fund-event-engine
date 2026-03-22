"""Minimal HTML cleaner for public pages."""

from __future__ import annotations

import html
import re


def clean_html(raw_html: str) -> str:
    """Strip script/style/nav-like blocks and return plain text."""
    txt = re.sub(r"<(script|style|noscript)[^>]*>.*?</\\1>", " ", raw_html, flags=re.I | re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()
