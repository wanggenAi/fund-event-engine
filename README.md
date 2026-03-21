# fund-event-engine

最小可运行流程（MVP）已就位，当前按以下链路执行：

1. 去噪（`noise_filter_prompt.txt`）
2. 事件抽取（`event_extract_prompt.txt`）
3. 基金映射（`fund_map_prompt.txt` + `fund_profiles/<fund_code>.txt`）
4. 聚合判断（`aggregate_prompt.txt`）
5. 报告输出（`report_prompt.txt`）

## 运行方式

使用内置 mock 后端（无外部依赖）：

```bash
python3 scripts/run_mvp.py \
  --fund-code 002963 \
  --input sample_data/002963_docs.json \
  --backend mock
```

输出文件位于 `outputs/`：

- `<fund_code>_mapped_events.json`
- `<fund_code>_aggregate.json`
- `<fund_code>_report.txt`

## 最小网页抓取层（URL -> docs.json）

用于把 URL 列表转换为当前 `run_mvp.py` 可直接消费的输入文件。

种子配置文件：

- `configs/source_seeds.yaml`

按基金代码读取种子 URL 并构建 docs：

```bash
python3 scripts/build_docs_from_urls.py --fund-code 024194
```

按 URL 文件构建 docs：

```bash
python3 scripts/build_docs_from_urls.py --urls-file sample_data/024194_urls.txt --output sample_data/024194_docs.json
```

常用参数：

- `--max-urls 20`：限制抓取 URL 数量
- `--timeout 15`：单 URL 超时秒数

输出：

- docs：`sample_data/<fund_code>_docs.json`（或 `--output` 指定路径）
- 失败记录：`*.failures.json`（抓取失败不中断）

## 可替换 LLM 接口（未写死）

脚本支持两种模式：

- `--backend mock`：默认模式，建议本地开发/联调使用（确定性占位流程）。
- `--backend openai_compat`：备用模式，用于对接 OpenAI 兼容接口（可替换为免费方案网关）。

`openai_compat` 仅作为备用方案，生产上推荐把 LLM 分析放到 OpenClaw agent 会话中执行。

若使用 `openai_compat`，需要：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`（默认 `https://api.openai.com/v1`）
- `OPENAI_MODEL`（默认 `gpt-4o-mini`）

## OpenClaw 集成（最小运行方式）

建议固定部署路径（示例）：

- `/opt/fund-event-engine`

固定入口命令（推荐给 OpenClaw 执行）：

```bash
/opt/fund-event-engine/scripts/run_report.sh
```

指定基金代码：

```bash
/opt/fund-event-engine/scripts/run_report.sh 024194
```

指定基金代码 + 输入文件：

```bash
/opt/fund-event-engine/scripts/run_report.sh 024194 /opt/fund-event-engine/sample_data/024194_docs.json
```

默认报告执行行为：

- 不传参数时默认跑 `024194`
- 默认输入文件为 `sample_data/<fund_code>_docs.json`
- 默认 `BACKEND=mock`

可选环境变量：

- `UPDATE_REPO=1`：执行前先 `git pull --ff-only`
- `BACKEND=openai_compat`：切换到 OpenAI 兼容接口
- `FUND_CODE`、`INPUT_FILE`：可替代位置参数
- `RUN_TIMEOUT_SECONDS=180`：执行超时时间（秒），超时返回非 0

Telegram 触发 OpenClaw 执行示例（统一路径）：

- 默认报告：`/opt/fund-event-engine/scripts/run_report.sh`
- 指定基金：`/opt/fund-event-engine/scripts/run_report.sh 011035`
- 指定基金与输入：`/opt/fund-event-engine/scripts/run_report.sh 024194 /opt/fund-event-engine/sample_data/024194_docs.json`

## OpenClaw 原生运行模式（推荐）

目标：将 LLM 分析职责迁移到 OpenClaw 当前 agent 模型，Python 脚本保留为本地/兜底执行链路。

职责划分：

1. 脚本负责：
- 读取输入文件（`sample_data/<fund_code>_docs.json`）
- 串联流程骨架（去噪 -> 抽取 -> 映射 -> 聚合 -> 产物落盘）
- 产出中间结构化文件（`outputs/*_mapped_events.json`、`outputs/*_aggregate.json`）
- 输出最终报告文本（stdout）

2. OpenClaw agent 负责：
- 实际 LLM 推理与中文报告生成
- 按 prompt 契约执行各阶段分析
- Telegram 会话中的交互与结果回传

Telegram 触发时，OpenClaw 建议读取：

1. 全局与阶段 prompt：
- `prompts/system_prompt.txt`
- `prompts/noise_filter_prompt.txt`
- `prompts/event_extract_prompt.txt`
- `prompts/fund_map_prompt.txt`
- `prompts/aggregate_prompt.txt`
- `prompts/report_prompt.txt`

2. 基金画像与输入：
- `prompts/fund_profiles/<fund_code>.txt`
- `sample_data/<fund_code>_docs.json`（或你的实际抓取输入文件）

最小改造建议（不重构）：

1. 保留中间产物（建议继续落盘）：
- `outputs/<fund_code>_mapped_events.json`
- `outputs/<fund_code>_aggregate.json`
- `outputs/<fund_code>_report.txt`

2. OpenClaw 最适合消费的文件：
- 优先消费 `outputs/<fund_code>_aggregate.json`（结构稳定，便于二次生成报告）
- 需要追溯证据时再读 `outputs/<fund_code>_mapped_events.json`

3. 让最终报告由 OpenClaw 当前模型生成的方式：
- 在 OpenClaw 会话里，读取 `prompts/report_prompt.txt` + `outputs/<fund_code>_aggregate.json`
- 由 OpenClaw agent 直接生成并回传 Telegram
- 不必走 `run_mvp.py --backend openai_compat`（保留该模式仅作备用）

## OpenClaw 执行清单（可直接给运维/Agent）

1. 环境准备：
- 仓库部署在：`/opt/fund-event-engine`
- 确保可执行：`chmod +x /opt/fund-event-engine/scripts/run_report.sh`
- 机器具备：`python3`、`bash`

2. Telegram 前置：
- Telegram pairing 已完成
- `allowFrom` 已配置为允许当前对话/用户触发
- OpenClaw agent 允许使用 `exec` 工具

3. 推荐执行命令（OpenClaw exec）：
- 默认：`/opt/fund-event-engine/scripts/run_report.sh`
- 指定基金：`/opt/fund-event-engine/scripts/run_report.sh 011035`
- 指定基金+输入：`/opt/fund-event-engine/scripts/run_report.sh 024194 /opt/fund-event-engine/sample_data/024194_docs.json`

4. 输出约定：
- `stdout`：仅最终报告正文（适合直接回 Telegram）
- `stderr`：运行日志与错误信息
- 中间产物：`outputs/<fund_code>_mapped_events.json`、`outputs/<fund_code>_aggregate.json`、`outputs/<fund_code>_report.txt`
- 若执行失败，应优先将 `stderr` 的关键信息摘要回传 Telegram，避免静默失败

5. 常用运行参数：
- 更新代码：`UPDATE_REPO=1 /opt/fund-event-engine/scripts/run_report.sh 024194`
- 执行超时：`RUN_TIMEOUT_SECONDS=180 /opt/fund-event-engine/scripts/run_report.sh 024194`

6. OpenClaw 原生模型出报告（推荐）：
- 固定脚本先完成确定性执行，并产出聚合结果
- OpenClaw 会话再读取 `prompts/report_prompt.txt` + `outputs/<fund_code>_aggregate.json`
- 最终报告由当前 OpenClaw agent 模型生成并回传 Telegram
- 不要求 OpenClaw 在该模式下重新执行去噪、事件抽取、基金映射、聚合
- `run_mvp.py --backend openai_compat` 保留为备用方案，不作为当前推荐链路

7. Telegram 触发示例：
- “请执行 /opt/fund-event-engine/scripts/run_report.sh，并把最终报告回给我”
- “请执行 /opt/fund-event-engine/scripts/run_report.sh 011035，并把最终报告回给我”
