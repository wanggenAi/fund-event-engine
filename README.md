# fund-event-engine

基金事件驱动判断引擎（研究辅助版，openclaw 友好）。

## 项目定位
- 目标：做“事件 -> 核心变量 -> 基金”的方向判断，不做净值/股价点位预测。
- 输出：必须可追溯到事件、证据链、反证与观察点。
- 策略：证据不足时默认中性/待观察，不为结论而结论。

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

`configs/sources.yaml` 支持 `parser_hint: google_news_query` + `search_query`，可把博客/论坛/KOL 以“可控查询”接入，且保留 C/D 不进入主结论的硬约束。

## Freshness Gating（硬门槛）
支持 `3d/7d/14d/30d` 窗口，默认近期优先。

事件层关键字段：
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

说明：
- 每次运行会写入预测快照到 `outputs/history/fund_prediction_history.json`。
- 默认会读取 `outputs/history/source_performance.json` 做来源后验微调，可用 `--no-source-feedback` 关闭。

仅跑指定基金：
```bash
python3 -m src.pipeline.run \
  --window-days 7 \
  --collect-sources \
  --no-include-examples \
  --fund 011035
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

## 真实后验评估（关键）
当累计了多次正式运行后，可评估“预测方向 vs 后续净值方向”。

```bash
python3 -m src.pipeline.evaluate \
  --prediction-history outputs/history/fund_prediction_history.json \
  --eval-out outputs/prediction_evaluation.json \
  --md-out reports/prediction_evaluation.md \
  --source-performance-out outputs/history/source_performance.json \
  --source-feedback-half-life-days 45 \
  --source-feedback-dynamic-min-samples \
  --source-feedback-uncertainty-shrinkage \
  --source-feedback-shrinkage-strength 6.0
```

输出：
- `outputs/prediction_evaluation.json`：结构化命中结果（3d/2w/3m）
- `reports/prediction_evaluation.md`：可读评估摘要
- `outputs/history/source_performance.json`：来源后验表现与推荐 multiplier

`source_performance.json` 已包含：
- 全局、按基金类型、按窗口（3d/2w/3m）、按基金类型+窗口 的反馈
- 时间衰减、动态样本门槛、不确定性收缩
- 来源先验基准 + 后验 multiplier 融合（默认后验权重 0.65）

## How To Use With openclaw
推荐让 openclaw 走两步流水线：

1. 跑主流程（抓取 + 判断 + 报告）  
2. 跑后验评估（更新来源反馈）  

示例（给 openclaw 直接执行）：
```bash
set -euo pipefail

TS=$(date +%Y%m%d_%H%M%S)

python3 -m src.pipeline.run \
  --window-days 7 \
  --collect-sources \
  --no-include-examples \
  --max-sources 20 \
  --max-items-per-source 3 \
  --collect-timeout 12 \
  --events-out data/events/pipeline_events_${TS}.json \
  --signals-out data/snapshots/pipeline_signals_${TS}.json \
  --reports-out data/snapshots/pipeline_reports_${TS}.json \
  --aggregate-out outputs/pipeline_aggregate_${TS}.json \
  --mapped-events-out outputs/pipeline_mapped_events_${TS}.json \
  --markdown-out reports/pipeline_report_${TS}.md

python3 -m src.pipeline.evaluate \
  --prediction-history outputs/history/fund_prediction_history.json \
  --eval-out outputs/prediction_evaluation_${TS}.json \
  --md-out reports/prediction_evaluation_${TS}.md \
  --source-performance-out outputs/history/source_performance.json
```

openclaw 消费建议：
- 报告主读：`reports/pipeline_report_${TS}.md`
- 结构化主读：`outputs/pipeline_aggregate_${TS}.json` 与 `outputs/pipeline_mapped_events_${TS}.json`
- 反馈学习：`outputs/history/source_performance.json`

## Telegram 一键推送
前置环境变量：
- `TG_BOT_TOKEN`
- `TG_CHAT_ID`

```bash
TG_BOT_TOKEN=xxxx TG_CHAT_ID=xxxx bash scripts/run_and_push_telegram.sh
```

指定基金示例：
```bash
TG_BOT_TOKEN=xxxx TG_CHAT_ID=xxxx FUNDS="011035 002963" bash scripts/run_and_push_telegram.sh
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

或：
```bash
python3 -m src.pipeline.run --window-days 7 --scoring-override-file configs/scoring_override.json
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
- 聚合层来源结构：`source_mix_meta.total_by_tier`, `source_mix_meta.main_by_category`, `source_mix_meta.top_main_sources`
- 来源后验字段：`source_feedback_enabled`, `source_feedback_multiplier_count`, `source_feedback_fund_type_bucket_count`, `source_feedback_horizon_bucket_count`, `source_feedback_fund_type_horizon_bucket_count`, `source_feedback_file`

## 最小测试
```bash
python3 -m unittest discover -s tests -p "test_*unittest.py" -v
```

## 风险声明
本项目输出仅用于研究与信息整理，不构成投资建议。
