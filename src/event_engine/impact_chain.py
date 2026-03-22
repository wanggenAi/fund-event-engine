"""Build event -> variable -> asset -> fund impact chain."""

from __future__ import annotations

from typing import Dict, List


def build_impact_chain(fund_type: str, event_title: str) -> List[str]:
    """Return a simple explainable causal chain by fund type."""
    if fund_type == "thematic_equity":
        return [event_title, "产业供需/政策变量", "主题指数成分股预期", "基金净值方向"]
    if fund_type == "broad_equity":
        return [event_title, "流动性与风险偏好", "中盘风格表现", "基金净值方向"]
    if fund_type == "bond":
        return [event_title, "利率与信用利差", "债券价格表现", "基金净值方向"]
    if fund_type == "gold":
        return [event_title, "美元与实际利率", "黄金价格", "基金净值方向"]
    return [event_title, "变量", "资产", "基金"]
