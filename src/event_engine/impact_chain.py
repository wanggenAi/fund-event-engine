"""Build event -> variable -> asset -> fund impact chain."""

from __future__ import annotations

from typing import List


def build_impact_chain(fund_type: str, event_title: str) -> List[str]:
    """Return explainable causal chain by fund type, with event-specific variable inference."""
    title = event_title or ""

    if fund_type == "thematic_equity":
        # Infer dominant variable from title keywords
        if any(k in title for k in ["招标", "中标", "订单", "合同"]):
            mid_var = "订单/招标落地→产业链收入确认预期"
        elif any(k in title for k in ["政策", "规划", "标准", "核准", "补贴"]):
            mid_var = "政策信号→产业景气度预期修正"
        elif any(k in title for k in ["价格", "涨价", "降价", "原材料", "成本"]):
            mid_var = "价格/成本变量→毛利率预期"
        elif any(k in title for k in ["出口", "管制", "禁令", "配额"]):
            mid_var = "供给侧约束→供需格局变化"
        else:
            mid_var = "政策/供需/订单变量"
        return [event_title, mid_var, "主题产业链盈利预期", "基金净值方向"]

    if fund_type == "broad_equity":
        if any(k in title for k in ["降息", "降准", "流动性", "货币政策"]):
            mid_var = "货币宽松→流动性与估值扩张"
        elif any(k in title for k in ["PMI", "GDP", "工业增加值", "经济数据"]):
            mid_var = "宏观数据→盈利预期修正"
        else:
            mid_var = "流动性/风险偏好/风格"
        return [event_title, mid_var, "中证500估值与盈利预期", "基金净值方向"]

    if fund_type == "bond":
        if any(k in title for k in ["违约", "信用", "评级", "展期"]):
            mid_var = "信用事件→信用利差走扩/收窄"
        elif any(k in title for k in ["央行", "利率", "国债", "收益率"]):
            mid_var = "利率变动→债券估值调整"
        else:
            mid_var = "利率与信用利差"
        return [event_title, mid_var, "债券价格与信用风险", "基金净值方向"]

    if fund_type == "gold":
        if any(k in title for k in ["美元", "美联储", "加息", "降息"]):
            mid_var = "美元/美联储预期→黄金定价压力/支撑"
        elif any(k in title for k in ["实际利率", "通胀", "CPI", "TIPS"]):
            mid_var = "实际利率变动→黄金持有成本"
        elif any(k in title for k in ["央行", "购金", "储备"]):
            mid_var = "央行购金→结构性需求支撑"
        elif any(k in title for k in ["避险", "地缘", "冲突", "战争"]):
            mid_var = "地缘/避险需求→黄金溢价"
        else:
            mid_var = "金价/美元/实际利率/央行购金"
        return [event_title, mid_var, "黄金资产定价", "基金净值方向"]

    return [event_title, "变量", "资产", "基金"]
