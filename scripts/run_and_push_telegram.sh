#!/usr/bin/env bash
set -euo pipefail

# fund-event-engine one-click formal run + Telegram push
#
# Required env:
#   TG_BOT_TOKEN=xxxx
#   TG_CHAT_ID=xxxx
#
# Optional env:
#   WINDOW_DAYS=7
#   MAX_SOURCES=20
#   MAX_ITEMS_PER_SOURCE=3
#   COLLECT_TIMEOUT=12
#   FUNDS="025832 011035 024194"   # space-separated
#   VERBOSE_COLLECT=1               # 1 or 0
#   SCORING_OVERRIDE_JSON='{"proxy_controls":{"max_proxy_share_in_main":0.7}}'
#   SCORING_OVERRIDE_FILE="configs/scoring_override.json"
#   RUN_EVAL=1                     # run realized-outcome evaluation after pipeline

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

: "${TG_BOT_TOKEN:?TG_BOT_TOKEN is required}"
: "${TG_CHAT_ID:?TG_CHAT_ID is required}"

WINDOW_DAYS="${WINDOW_DAYS:-7}"
MAX_SOURCES="${MAX_SOURCES:-20}"
MAX_ITEMS_PER_SOURCE="${MAX_ITEMS_PER_SOURCE:-3}"
COLLECT_TIMEOUT="${COLLECT_TIMEOUT:-12}"
VERBOSE_COLLECT="${VERBOSE_COLLECT:-1}"
FUNDS="${FUNDS:-}"
SCORING_OVERRIDE_JSON="${SCORING_OVERRIDE_JSON:-}"
SCORING_OVERRIDE_FILE="${SCORING_OVERRIDE_FILE:-}"
RUN_EVAL="${RUN_EVAL:-1}"

TS="$(date +%Y%m%d_%H%M%S)"
EVENTS_OUT="data/events/pipeline_events_${TS}.json"
SIGNALS_OUT="data/snapshots/pipeline_signals_${TS}.json"
REPORTS_OUT="data/snapshots/pipeline_reports_${TS}.json"
AGG_OUT="outputs/pipeline_aggregate_${TS}.json"
MAPPED_OUT="outputs/pipeline_mapped_events_${TS}.json"
MD_OUT="reports/pipeline_report_${TS}.md"
EVAL_JSON_OUT="outputs/prediction_evaluation_${TS}.json"
EVAL_MD_OUT="reports/prediction_evaluation_${TS}.md"

CMD=(
  python3 -m src.pipeline.run
  --window-days "${WINDOW_DAYS}"
  --collect-sources
  --no-include-examples
  --max-sources "${MAX_SOURCES}"
  --max-items-per-source "${MAX_ITEMS_PER_SOURCE}"
  --collect-timeout "${COLLECT_TIMEOUT}"
  --events-out "${EVENTS_OUT}"
  --signals-out "${SIGNALS_OUT}"
  --reports-out "${REPORTS_OUT}"
  --aggregate-out "${AGG_OUT}"
  --mapped-events-out "${MAPPED_OUT}"
  --markdown-out "${MD_OUT}"
)

if [[ "${VERBOSE_COLLECT}" == "1" ]]; then
  CMD+=(--verbose-collect)
fi

if [[ -n "${SCORING_OVERRIDE_JSON}" ]]; then
  CMD+=(--scoring-override-json "${SCORING_OVERRIDE_JSON}")
fi

if [[ -n "${SCORING_OVERRIDE_FILE}" ]]; then
  CMD+=(--scoring-override-file "${SCORING_OVERRIDE_FILE}")
fi

if [[ -n "${FUNDS}" ]]; then
  # shellcheck disable=SC2206
  FUND_ARR=(${FUNDS})
  for code in "${FUND_ARR[@]}"; do
    CMD+=(--fund "${code}")
  done
fi

echo "[run] start pipeline..."
"${CMD[@]}"
echo "[run] pipeline done."

if [[ "${RUN_EVAL}" == "1" ]]; then
  echo "[run] start evaluation..."
  python3 -m src.pipeline.evaluate \
    --prediction-history "outputs/history/fund_prediction_history.json" \
    --eval-out "${EVAL_JSON_OUT}" \
    --md-out "${EVAL_MD_OUT}" >/dev/null
  echo "[run] evaluation done."
fi

echo "[push] send markdown report to Telegram..."
curl -sS -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendDocument" \
  -F chat_id="${TG_CHAT_ID}" \
  -F document=@"${MD_OUT}" \
  -F caption="fund-event-engine report ${TS}" >/dev/null

echo "[push] send aggregate json to Telegram..."
curl -sS -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendDocument" \
  -F chat_id="${TG_CHAT_ID}" \
  -F document=@"${AGG_OUT}" \
  -F caption="pipeline_aggregate ${TS}" >/dev/null

if [[ "${RUN_EVAL}" == "1" ]]; then
  echo "[push] send evaluation markdown to Telegram..."
  curl -sS -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendDocument" \
    -F chat_id="${TG_CHAT_ID}" \
    -F document=@"${EVAL_MD_OUT}" \
    -F caption="prediction_evaluation ${TS}" >/dev/null
fi

echo "[done] sent:"
echo "  - ${MD_OUT}"
echo "  - ${AGG_OUT}"
echo "  - ${REPORTS_OUT}"
echo "  - ${SIGNALS_OUT}"
echo "  - ${EVENTS_OUT}"
if [[ "${RUN_EVAL}" == "1" ]]; then
  echo "  - ${EVAL_MD_OUT}"
  echo "  - ${EVAL_JSON_OUT}"
fi
