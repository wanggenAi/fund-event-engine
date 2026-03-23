# fund-event-engine

基金事件驱动判断引擎（研究辅助版，openclaw 友好）。

## 项目定位
- 目标是做“事件 -> 核心变量 -> 基金”的方向判断，不做净值/股价点位预测。
- 输出必须可追溯到事件与证据链。
- 证据不足时默认中性/待观察，不为结论而结论。

## 覆盖基金
- `025832` 天弘中证电网设备主题指数发起A
- `011035` 嘉实中证稀土产业ETF联接A
- `024194` 永赢国证商用卫星通信产业ETF发起联接A
- `007028` 易方达中证500ETF联接发起式A
- `217023` 招商信用增强债券A
- `007951` 招商信用增强债券C
- `002963` 易方达黄金ETF联接C

## 数据源原则
仅使用免费公开信息，不使用付费 API、付费爬虫、付费数据库。

- A层 `authoritative_data`：官方公告/监管/交易所/基金公司/上市公司
- B层 `top_tier_media`：主流财经与高质量行业媒体
- C层 `specialist_research`：博客/专题（仅辅助）
- D层 `sentiment_sources`：论坛/社区/社媒（仅情绪补充）

## Freshness Gating（硬门槛）
支持 `3d/7d/14d/30d` 窗口，默认近期优先。

事件层保留字段：
- `published_at`
- `event_date`
- `collected_at`
- `freshness_bucket`
- `is_stale`
- `date_uncertain`

策略要点：
- 过时/日期不确定事件默认降级或剔除主结论。
- 重复旧闻抑制，不重复计分。
- 近期缺少 A/B 新增证据时，默认中性/待观察。

## 工程结构
- `configs/`：基金画像、来源分层、评分参数、taxonomy
- `src/collectors/`：公开源抓取、结构化信号补充
- `src/parsers/`：正文清洗、噪音过滤
- `src/event_engine/`：事件抽取、影响链、打分
- `src/fund_mapper/`：事件到基金映射
- `src/pipeline/`：主流程与 openclaw 编排入口
- `src/reports/`：demo 和报告输出
- `src/utils/report_quality.py`：自动质量评分（稳定性/一致性/参考价值）
- `examples/`：样例输入

## 快速开始
```bash
python3 -m src.reports.run_demo
```

## 正式执行（推荐）
```bash
python3 -m src.pipeline.run \
  --window-days 7 \
  --collect-sources \
  --no-include-examples \
  --max-sources 20 \
  --max-items-per-source 3 \
  --collect-timeout 12 \
  --verbose-collect
```

仅跑指定基金：
```bash
python3 -m src.pipeline.run \
  --window-days 7 \
  --collect-sources \
  --no-include-examples \
  --fund 025832 --fund 011035 --fund 024194
```

## 避免旧文件混淆（时间戳输出）
```bash
TS=$(date +%Y%m%d_%H%M%S)
python3 -m src.pipeline.run \
  --window-days 7 \
  --collect-sources \
  --no-include-examples \
  --events-out data/events/pipeline_events_${TS}.json \
  --signals-out data/snapshots/pipeline_signals_${TS}.json \
  --reports-out data/snapshots/pipeline_reports_${TS}.json \
  --aggregate-out outputs/pipeline_aggregate_${TS}.json \
  --mapped-events-out outputs/pipeline_mapped_events_${TS}.json \
  --markdown-out reports/pipeline_report_${TS}.md
```

## openclaw 一键执行与 Telegram 推送
下面这段可以直接给 openclaw 执行。

前置环境变量：
- `TG_BOT_TOKEN`：Telegram Bot Token
- `TG_CHAT_ID`：你的 chat id（个人或群）

也可以直接用仓库脚本（推荐）：
```bash
TG_BOT_TOKEN=xxxx TG_CHAT_ID=xxxx \
bash scripts/run_and_push_telegram.sh
```

指定基金示例：
```bash
TG_BOT_TOKEN=xxxx TG_CHAT_ID=xxxx \
FUNDS="025832 011035 024194" \
bash scripts/run_and_push_telegram.sh
```

```bash
set -euo pipefail

TS=$(date +%Y%m%d_%H%M%S)
EVENTS="data/events/pipeline_events_${TS}.json"
SIGNALS="data/snapshots/pipeline_signals_${TS}.json"
REPORTS="data/snapshots/pipeline_reports_${TS}.json"
AGG="outputs/pipeline_aggregate_${TS}.json"
MAPPED="outputs/pipeline_mapped_events_${TS}.json"
MD="reports/pipeline_report_${TS}.md"

python3 -m src.pipeline.run \
  --window-days 7 \
  --collect-sources \
  --no-include-examples \
  --max-sources 20 \
  --max-items-per-source 3 \
  --collect-timeout 12 \
  --events-out "${EVENTS}" \
  --signals-out "${SIGNALS}" \
  --reports-out "${REPORTS}" \
  --aggregate-out "${AGG}" \
  --mapped-events-out "${MAPPED}" \
  --markdown-out "${MD}"

# 1) 发送 Markdown 报告
curl -sS -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendDocument" \
  -F chat_id="${TG_CHAT_ID}" \
  -F document=@"${MD}" \
  -F caption="fund-event-engine 报告 ${TS}"

# 2) 发送聚合 JSON（便于自动化读取）
curl -sS -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendDocument" \
  -F chat_id="${TG_CHAT_ID}" \
  -F document=@"${AGG}" \
  -F caption="pipeline_aggregate ${TS}"
```

## 运行时动态调参（不改仓库配置）
```bash
python3 -m src.pipeline.run \
  --fund 002963 \
  --window-days 7 \
  --collect-sources \
  --no-include-examples \
  --scoring-override-json '{"proxy_controls_by_fund_code":{"002963":{"max_proxy_share_in_main":0.9,"auto_downgrade_strength_when_proxy_dominant":false}}}'
```

也支持文件覆盖：
```bash
python3 -m src.pipeline.run \
  --window-days 7 \
  --scoring-override-file configs/scoring_override.json
```

## 输出文件与稳定契约
主输出：
- 事件层：`data/events/*.json`
- 信号层：`data/snapshots/*signals*.json`
- 报告层：`data/snapshots/*reports*.json`
- 聚合层：`outputs/*aggregate*.json`
- Markdown：`reports/*.md`

openclaw 重点字段：
- 事件层：`is_page_chrome`, `is_noise`, `content_quality_score`, `extractable_event_score`, `published_at`, `event_date`, `is_stale`
- 信号层：`source_tier`, `evidence_tier`, `include_in_main`, `evidence_class`, `gated_reason`, `score`, `variable_evidence_type`, `variable_evidence_note`
- 报告层：`direction_3d`, `direction_2w`, `direction_3m`, `long_term_logic`, `conclusion_strength`, `warnings`, `proxy_event_share_main`
- 报告层（自动质量）：`source_stability_score`, `historical_consistency_score`, `reference_value_score`, `quality_flags`
- 聚合层补充：`runtime_scoring_override_applied`, `runtime_scoring_override_keys`, `quality_meta`

## 评分与 proxy 控制（`configs/scoring.yaml`）
- `evidence_mode_weight`：`direct/proxy` 分数权重
- `proxy_controls`：全局 proxy 置信度与占比阈值
- `proxy_controls_by_fund_type`：按基金类型覆盖
- `proxy_controls_by_fund_code`：按基金代码覆盖（优先级最高）

## 自动质量评分
每次正式运行后自动计算并写入报告：
- 源稳定性分 `source_stability_score`
- 历史一致性分 `historical_consistency_score`
- 参考价值分 `reference_value_score`
- 质量标记 `quality_flags`

历史文件默认：
- `outputs/history/fund_report_history.json`

可通过参数覆盖：
- `--history-path outputs/history/your_history.json`

## 最小测试
```bash
python3 -m unittest discover -s tests -p "test_*unittest.py" -v
```

## 风险声明
本项目输出仅用于研究与信息整理，不构成投资建议。
