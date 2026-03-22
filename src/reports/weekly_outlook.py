"""Weekly outlook wrapper."""

from __future__ import annotations

from typing import Any, Dict

from src.reports.daily_digest import render_fund_markdown


def render_weekly(fund: Dict[str, Any], summary: Dict[str, Any]) -> str:
    """Render weekly outlook as markdown."""
    return render_fund_markdown(fund, summary)
