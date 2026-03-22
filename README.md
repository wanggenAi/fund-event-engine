# fund-event-engine

基金事件驱动判断引擎（MVP）。

项目定位：
- 这是“事件 -> 资产/行业 -> 基金”的方向判断系统。
- 不是价格点位预测器，不输出买卖建议。

## 当前覆盖基金
- 025832 天弘中证电网设备主题指数发起A
- 011035 嘉实中证稀土产业ETF联接A
- 024194 永赢国证商用卫星通信产业ETF发起联接A
- 007028 易方达中证500ETF联接发起式A
- 217023 招商信用增强债券A
- 007951 招商信用增强债券C
- 002963 易方达黄金ETF联接C

## 项目结构
- `configs/`: 基金画像、事件分类、评分与数据源配置。
- `src/collectors/`: 免费公开源采集模块骨架。
- `src/parsers/`: 文本清洗与样例解析。
- `src/event_engine/`: 事件抽取、分类、影响链、评分、反证检查。
- `src/fund_mapper/`: 基金画像加载、事件映射、基金级聚合判断。
- `src/reports/`: 日/周/月报告渲染与 demo 执行脚本。
- `prompts/`: 可复用提示词（结构化、可程序加载）。
- `examples/`: 回归样例。
- `data/events`, `data/snapshots`: 结构化输出。
- `reports/`: Markdown 报告输出。

## 数据源原则
仅使用免费公开信息：
- 官方网站、监管与交易所公告
- 基金公司公开页面
- 主流财经媒体
- RSS 与站点搜索入口

不使用付费 API、付费爬虫服务、付费数据库。

## 判断框架
对每只基金输出：
- 3d：利好 / 利空 / 中性
- 2w：利好 / 利空 / 中性
- 3m：利好 / 利空 / 中性
- 长期逻辑：强化 / 不变 / 弱化

并附带：
- 核心驱动
- 影响链条
- 反证与风险
- 观察点
- 置信度

## 快速开始
### 1) 运行新 demo 链路（推荐）
```bash
python3 -m src.reports.run_demo
```

运行后将生成：
- `data/events/demo_events.json`
- `data/snapshots/demo_signals.json`
- `data/snapshots/demo_snapshot.json`
- `reports/demo_output.md`

### 2) 运行 openclaw 友好 pipeline
```bash
python3 -m src.pipeline.run --window-days 7
```

可选参数：
- `--window-days 3|7|14|30`：严格新鲜度窗口（默认 7）。
- `--fund 011035 --fund 002963`：仅输出指定基金。
- `--events-out/--signals-out/--reports-out/--markdown-out`：自定义产物路径。

### 3) 兼容旧 MVP 主链路
项目保留 `scripts/run_mvp.py` 与 `scripts/run_report.sh`，用于你现有 sample_data 流程。

### 4) 一键执行（抓取 + 分析 + 报告）
```bash
scripts/run_one_click.sh 002963
```

说明：
- 默认每次都会先抓取网页并覆盖旧的 `sample_data/<fund_code>_docs.json`，再运行报告分析。
- 最终报告正文输出到 stdout，便于 Telegram/OpenClaw 直接回传。
- 常用环境变量：
  - `AUTO_FETCH=0`：跳过抓取，直接用现有 input
  - `MAX_URLS=20`：抓取 URL 上限
  - `BACKEND=mock|openai_compat`

## 关键配置文件
- `configs/funds.yaml`: 7只基金结构化画像与驱动因子。
- `configs/taxonomy.yaml`: 事件分类体系、同义词、适用基金类型。
- `configs/scoring.yaml`: 来源/新鲜度/强度权重与阈值。
- `configs/sources.yaml`: 免费公开来源清单。

## Prompts
- `prompts/extract_event.md`
- `prompts/map_event_to_fund.md`
- `prompts/short_term_judgement.md`
- `prompts/long_term_logic_review.md`
- `prompts/contradiction_check.md`

## How To Use With Openclaw
推荐将 pipeline 拆分为可编排步骤，并消费稳定 JSON 契约：
1. `python3 -m src.pipeline.run --window-days 7`
2. 读取 `data/events/pipeline_events.json`
3. 读取 `data/snapshots/pipeline_signals.json`
4. 读取 `data/snapshots/pipeline_reports.json`
5. 可选回传 `reports/pipeline_report.md` 给 Telegram

字段稳定性说明：
- 事件层保留 `published_at/event_date/collected_at/freshness_bucket/is_stale`
- 基金层保留 `analysis_window/recent_event_count/stale_event_count_filtered/direction_3d/direction_2w/direction_3m/long_term_logic/confidence/warnings`
- `evidence_class` 说明：`event_evidence`（主证据）、`background_evidence`（背景）、`clue_only`（社区/自媒体线索，不直接驱动结论）

新鲜度硬约束：
- 超过分析窗口的事件默认不纳入主结论
- 日期不确定事件在 14 天及以下窗口默认降级为背景证据
- 若近期新增高质量事件不足，默认输出中性/待观察

## 路线图
- v0.1：最小可运行链路（样例输入 -> 基金判断 -> JSON/Markdown）
- v0.2：历史样例验证与评分回看
- v0.3：自动日报/周报与更稳定的数据采集

## 风险声明
本项目输出仅用于研究与信息整理，不构成任何投资建议。
