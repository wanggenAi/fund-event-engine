"""Build event -> variable -> asset -> fund impact chain."""

from __future__ import annotations

from typing import List


def build_impact_chain(fund_type: str, event_title: str) -> List[str]:
    """Return explainable causal chain by fund type."""
    if fund_type == "thematic_equity":
        return [event_title, "政策/供需/订单变量", "主题产业链盈利预期", "基金净值方向"]
    if fund_type == "broad_equity":
        return [event_title, "流动性/风险偏好/风格", "中证500估值与盈利预期", "基金净值方向"]
    if fund_type == "bond":
        return [event_title, "利率与信用利差", "债券价格与信用风险", "基金净值方向"]
    if fund_type == "gold":
        return [event_title, "金价/美元/实际利率/央行购金", "黄金资产定价", "基金净值方向"]
    return [event_title, "变量", "资产", "基金"]
