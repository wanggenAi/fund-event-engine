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

## 可替换 LLM 接口（未写死）

脚本支持 `--backend openai_compat`，用于对接 OpenAI 兼容接口（可替换为免费方案网关）：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`（默认 `https://api.openai.com/v1`）
- `OPENAI_MODEL`（默认 `gpt-4o-mini`）
