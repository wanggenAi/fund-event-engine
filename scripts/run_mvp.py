#!/usr/bin/env python3
import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from urllib import request


ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "prompts"


@dataclass
class Backends:
    mode: str

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        if self.mode == "mock":
            raise RuntimeError("mock backend does not support generic chat()")
        if self.mode != "openai_compat":
            raise ValueError(f"Unsupported backend: {self.mode}")

        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for openai_compat backend")

        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_profile_keywords(fund_profile: str) -> List[str]:
    keywords: List[str] = []
    split_tokens = re.compile(r"[、，,；;：:\s/（）()]+")
    stop_tokens = {"相关", "变化", "风险", "环境", "需求", "进展", "部分", "影响", "核心", "重点关注"}
    for raw in fund_profile.splitlines():
        line = raw.strip()
        if line.startswith("-"):
            token = line.lstrip("-").strip()
            if token:
                keywords.append(token)
                parts = [p.strip() for p in split_tokens.split(token) if p.strip()]
                for p in parts:
                    if len(p) >= 2 and p not in stop_tokens:
                        keywords.append(p)
    dedup: List[str] = []
    for k in keywords:
        if k not in dedup:
            dedup.append(k)
    return dedup


def infer_asset_tags_and_scope(text: str) -> Dict[str, Any]:
    rules = [
        (["黄金", "购金", "美元", "实际利率", "避险"], "黄金", "黄金"),
        (["信用债", "信用利差", "违约", "债市", "转债"], "信用债", "债市"),
        (["中证500", "宽基", "风险偏好", "风格轮动", "流动性"], "中证500", "宽基"),
        (["稀土", "永磁", "配额", "开采", "冶炼"], "稀土", "行业"),
        (["卫星", "星座", "频轨", "发射", "商业航天"], "卫星通信", "行业"),
        (["电网", "特高压", "配网", "智能电网", "招标"], "电网设备", "行业"),
    ]
    for keys, tag, scope in rules:
        if any(k in text for k in keys):
            return {"asset_tags": [tag], "impact_scope": scope}
    return {"asset_tags": [], "impact_scope": "宏观"}


def infer_profile_theme(fund_profile: str) -> str:
    text = fund_profile
    if any(k in text for k in ["黄金", "购金", "实际利率", "美元"]):
        return "黄金"
    if any(k in text for k in ["信用利差", "信用债", "违约", "债市"]):
        return "信用债"
    if any(k in text for k in ["中证500", "宽基", "风格轮动"]):
        return "中证500"
    if any(k in text for k in ["稀土", "永磁", "冶炼"]):
        return "稀土"
    if any(k in text for k in ["卫星", "星座", "商业航天", "频轨"]):
        return "卫星通信"
    if any(k in text for k in ["电网", "特高压", "配网", "智能电网"]):
        return "电网设备"
    return ""


def try_parse_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"Cannot parse JSON from LLM output: {text[:200]}")
    return json.loads(m.group(0))


def build_stage_user_prompt(stage_prompt: str, payload: Dict[str, Any]) -> str:
    return (
        f"{stage_prompt}\n\n"
        "请基于以下输入完成任务，只输出 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def mock_noise_filter(doc: Dict[str, Any]) -> Dict[str, Any]:
    text = f"{doc.get('title', '')} {doc.get('content', '')}"
    noise_hits = ["观点", "看好", "情绪", "传闻", "听说", "网友", "股吧"]
    fact_hits = ["公告", "发布", "数据", "政策", "订单", "发射", "利率", "美元", "购金", "违约"]
    deny_fact_phrases = ["缺少新增事实", "缺少数据支撑", "仅为观点", "没有新增事实"]
    has_deny_phrase = any(k in text for k in deny_fact_phrases)
    is_noise = has_deny_phrase or (any(k in text for k in noise_hits) and not any(k in text for k in fact_hits))

    if is_noise:
        return {
            "info_quality": "噪音",
            "should_keep": False,
            "reason": "以观点或情绪表达为主，缺少新增可验证事实。",
            "novelty": 1,
            "credibility": 2,
            "signal_density": 1,
        }

    return {
        "info_quality": "中价值信息",
        "should_keep": True,
        "reason": "包含可用于基金判断的事实线索。",
        "novelty": 3,
        "credibility": 3,
        "signal_density": 3,
    }


def mock_event_extract(doc: Dict[str, Any]) -> Dict[str, Any]:
    content = f"{doc.get('title', '')} {doc.get('content', '')}"
    event_type = "其他"
    if "政策" in content or "监管" in content:
        event_type = "政策"
    elif "利率" in content or "降息" in content:
        event_type = "宏观流动性"
    elif "美元" in content or "美联储" in content:
        event_type = "宏观流动性"
    elif "购金" in content:
        event_type = "产业数据"
    elif "发射" in content:
        event_type = "发射或项目进展"

    bullish = "不明确"
    if any(k in content for k in ["降息", "利率回落", "美元走弱", "避险升温", "购金增加", "发射成功", "订单落地", "政策支持"]):
        bullish = "利好"
    if any(k in content for k in ["利率上行", "美元走强", "避险降温", "延期", "发射失败", "项目推迟", "违约"]):
        bullish = "利空"
    asset_and_scope = infer_asset_tags_and_scope(content)

    return {
        "doc_id": doc.get("doc_id", "未提供"),
        "source": doc.get("source", "未提供"),
        "publish_time": doc.get("publish_time", "未明确"),
        "events": [
            {
                "event_title": doc.get("title", "未命名事件"),
                "event_date": doc.get("publish_time", "未明确"),
                "event_type": event_type,
                "main_entities": [],
                "industry_tags": [],
                "asset_tags": asset_and_scope["asset_tags"],
                "fact_summary": doc.get("content", "")[:120],
                "bullish_bearish": bullish,
                "impact_scope": asset_and_scope["impact_scope"],
                "impact_horizon": "短期",
                "importance": 3,
                "confidence": 3,
                "is_noise": False,
                "noise_reason": "",
                "evidence": [doc.get("title", "")],
            }
        ],
    }


def mock_fund_map(fund_code: str, fund_name: str, fund_profile: str, event: Dict[str, Any]) -> Dict[str, Any]:
    direction_map = {
        "利好": "偏利好",
        "利空": "偏利空",
        "中性": "中性",
        "不明确": "不明确",
    }
    event_dir = event.get("bullish_bearish", "不明确")
    keywords = extract_profile_keywords(fund_profile)
    event_text = " ".join(
        [
            event.get("event_title", ""),
            event.get("fact_summary", ""),
            " ".join(event.get("asset_tags", [])),
            " ".join(event.get("industry_tags", [])),
        ]
    )
    overlap = sum(1 for k in keywords if k and k in event_text)
    profile_theme = infer_profile_theme(fund_profile)
    event_tags = set(event.get("asset_tags", []))
    thematic_hit = profile_theme and profile_theme in event_tags
    relevance_score = 1 if overlap == 0 else (2 if overlap == 1 else (3 if overlap <= 3 else (4 if overlap <= 6 else 5)))
    if thematic_hit and relevance_score < 3:
        relevance_score = 3
    related = relevance_score >= 2
    direction_for_fund = direction_map.get(event_dir, "不明确") if related else "不明确"
    logic_path = "事件与基金画像关键词匹配度较低，暂不构成清晰影响链条。"
    if related:
        logic_path = "事件触及基金核心暴露变量，可能通过估值与风险偏好路径传导至基金表现。"

    return {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "related": related,
        "relevance_score": relevance_score,
        "direction_for_fund": direction_for_fund,
        "impact_horizon": event.get("impact_horizon", "短期"),
        "is_direct_hit": overlap >= 2,
        "affects_core_logic": related and event.get("impact_horizon") in ["长期", "混合"],
        "logic_path": logic_path,
        "reasoning": "基于基金画像关键词与事件事实的重合度进行映射判断。",
        "confidence": 2 if overlap == 0 else (3 if overlap <= 2 else 4),
        "evidence_links": [event.get("doc_id", ""), event.get("event_title", "")],
    }


def mock_aggregate(fund_code: str, fund_name: str, mapped: List[Dict[str, Any]], noise_events: List[str]) -> Dict[str, Any]:
    score = 0
    for m in mapped:
        if m["direction_for_fund"] == "偏利好":
            score += m["relevance_score"]
        elif m["direction_for_fund"] == "偏利空":
            score -= m["relevance_score"]

    view = "中性"
    if score >= 3:
        view = "偏利好"
    elif score <= -3:
        view = "偏利空"

    long_logic = "暂不明确"
    if view == "偏利好":
        long_logic = "长期逻辑仍在"
    elif view == "偏利空":
        long_logic = "逻辑走弱"

    return {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "view_3d": {"direction": view, "reason": "基于最新事件加权后得出。", "confidence": 3},
        "view_2w": {"direction": view, "reason": "近两周叙事未出现明显反转。", "confidence": 3},
        "view_3m": {"direction": long_logic, "reason": "长期判断取决于核心变量是否持续验证。", "confidence": 2},
        "top_positive_drivers": [m["logic_path"] for m in mapped if m["direction_for_fund"] == "偏利好"][:3],
        "top_negative_drivers": [m["logic_path"] for m in mapped if m["direction_for_fund"] == "偏利空"][:3],
        "main_noise_events": noise_events[:3],
        "core_logic_status": long_logic,
        "key_risks": ["核心定价变量反向波动风险"],
        "conflicts_between_events": [],
        "final_summary": "当前结论为方向性判断，不构成收益率或交易建议。",
    }


def build_report(agg: Dict[str, Any]) -> str:
    return (
        f"【{agg['fund_name']}】\n\n"
        f"近3日判断：{agg['view_3d']['direction']}。{agg['view_3d']['reason']}\n\n"
        f"近2周判断：{agg['view_2w']['direction']}。{agg['view_2w']['reason']}\n\n"
        f"近3个月逻辑：{agg['view_3m']['direction']}。{agg['view_3m']['reason']}\n\n"
        "主要利好：\n"
        + "\n".join(f"- {x}" for x in agg["top_positive_drivers"][:3])
        + "\n\n主要利空：\n"
        + "\n".join(f"- {x}" for x in agg["top_negative_drivers"][:3])
        + "\n\n风险提醒：\n"
        + "\n".join(f"- {x}" for x in agg["key_risks"][:2])
        + "\n\n一句话结论：当前输出为事件驱动方向判断，证据不足时应保持谨慎。\n"
    )


def call_json_llm(backend: Backends, system_prompt: str, stage_prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = backend.chat(system_prompt, build_stage_user_prompt(stage_prompt, payload))
    return try_parse_json(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fund event engine MVP runner")
    parser.add_argument("--fund-code", required=True)
    parser.add_argument("--input", required=True, help="JSON file: list of docs")
    parser.add_argument("--backend", default="mock", choices=["mock", "openai_compat"])
    args = parser.parse_args()

    system_prompt = load_text(PROMPTS_DIR / "system_prompt.txt")
    noise_prompt = load_text(PROMPTS_DIR / "noise_filter_prompt.txt")
    event_prompt = load_text(PROMPTS_DIR / "event_extract_prompt.txt")
    map_prompt = load_text(PROMPTS_DIR / "fund_map_prompt.txt")
    aggregate_prompt = load_text(PROMPTS_DIR / "aggregate_prompt.txt")
    _report_prompt = load_text(PROMPTS_DIR / "report_prompt.txt")

    profile_path = PROMPTS_DIR / "fund_profiles" / f"{args.fund_code}.txt"
    if not profile_path.exists():
        raise FileNotFoundError(f"Missing fund profile: {profile_path}")
    fund_profile = load_text(profile_path)
    m = re.search(r"基金名称：(.+)", fund_profile)
    fund_name = m.group(1).strip() if m else args.fund_code

    docs = json.loads(Path(args.input).read_text(encoding="utf-8"))
    backend = Backends(args.backend)

    kept_docs: List[Dict[str, Any]] = []
    noise_events: List[str] = []

    for doc in docs:
        if args.backend == "mock":
            noise_out = mock_noise_filter(doc)
        else:
            noise_out = call_json_llm(backend, system_prompt, noise_prompt, doc)

        if noise_out.get("should_keep"):
            kept_docs.append(doc)
        else:
            noise_events.append(doc.get("doc_id", doc.get("title", "unknown")))

    extracted_events: List[Dict[str, Any]] = []
    for doc in kept_docs:
        if args.backend == "mock":
            out = mock_event_extract(doc)
        else:
            out = call_json_llm(backend, system_prompt, event_prompt, doc)

        for event in out.get("events", []):
            if event.get("is_noise"):
                noise_events.append(out.get("doc_id", event.get("event_title", "noise")))
                continue
            event["doc_id"] = out.get("doc_id", "未提供")
            extracted_events.append(event)

    mapped_results: List[Dict[str, Any]] = []
    for event in extracted_events:
        payload = {
            "fund_profile": fund_profile,
            "event": event,
            "fund_code": args.fund_code,
            "fund_name": fund_name,
        }
        if args.backend == "mock":
            mapped = mock_fund_map(args.fund_code, fund_name, fund_profile, event)
        else:
            mapped = call_json_llm(backend, system_prompt, map_prompt, payload)
        mapped_results.append(mapped)

    agg_payload = {
        "fund_code": args.fund_code,
        "fund_name": fund_name,
        "mapped_events": mapped_results,
        "noise_events": noise_events,
    }
    if args.backend == "mock":
        agg = mock_aggregate(args.fund_code, fund_name, mapped_results, noise_events)
    else:
        agg = call_json_llm(backend, system_prompt, aggregate_prompt, agg_payload)

    report_text = build_report(agg) if args.backend == "mock" else backend.chat(system_prompt, build_stage_user_prompt(_report_prompt, agg))

    out_dir = ROOT / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.fund_code}_mapped_events.json").write_text(
        json.dumps(mapped_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / f"{args.fund_code}_aggregate.json").write_text(
        json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / f"{args.fund_code}_report.txt").write_text(report_text, encoding="utf-8")

    print(f"MVP done for {args.fund_code}: {len(docs)} docs, {len(extracted_events)} extracted events")
    print(f"- mapped: outputs/{args.fund_code}_mapped_events.json")
    print(f"- aggregate: outputs/{args.fund_code}_aggregate.json")
    print(f"- report: outputs/{args.fund_code}_report.txt")


if __name__ == "__main__":
    main()
