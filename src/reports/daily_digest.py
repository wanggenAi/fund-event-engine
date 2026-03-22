"""Daily digest markdown renderer."""

from __future__ import annotations

from typing import Any, Dict


def render_fund_markdown(fund: Dict[str, Any], summary: Dict[str, Any]) -> str:
    """Render one-fund markdown block."""
    pos = summary.get("top_positive_drivers", [])
    neg = summary.get("top_negative_drivers", [])
    watch = summary.get("watch_points", [])
    return (
        f"## {fund.get('code')} {fund.get('name')}\n"
        f"- 3日视角：{summary.get('view_3d', '中性')}\n"
        f"- 2周视角：{summary.get('view_2w', '中性')}\n"
        f"- 3个月视角：{summary.get('view_3m', '中性')}\n"
        f"- 长期逻辑：{summary.get('long_term_logic', '不变')}\n\n"
        "### 核心驱动\n"
        + "\n".join(f"{i+1}. {x}" for i, x in enumerate(pos[:3]))
        + ("\n" if pos else "1. 暂无明确利好驱动\n")
        + "\n### 影响链条\n"
        + "- 事件 -> 行业变量 -> 指数/资产 -> 基金\n"
        + "\n### 反证与风险\n"
        + "\n".join(f"- {x}" for x in (neg[:2] or ["暂无集中反证，仍需观察"]))
        + "\n\n### 需要继续跟踪\n"
        + "\n".join(f"- {x}" for x in watch)
        + "\n"
    )
