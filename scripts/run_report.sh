#!/usr/bin/env bash
set -euo pipefail

err() {
  echo "[run_report] ERROR: $*" >&2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

FUND_CODE="${1:-${FUND_CODE:-024194}}"
INPUT_FILE="${2:-${INPUT_FILE:-${PROJECT_DIR}/sample_data/${FUND_CODE}_docs.json}}"
BACKEND="${BACKEND:-mock}"
RUN_TIMEOUT_SECONDS="${RUN_TIMEOUT_SECONDS:-180}"

cd "${PROJECT_DIR}" || { err "Cannot cd to ${PROJECT_DIR}"; exit 2; }

if [[ "${UPDATE_REPO:-0}" == "1" ]]; then
  echo "[run_report] Updating repo..." >&2
  git pull --ff-only || { err "git pull failed"; exit 3; }
fi

if [[ ! -f "${INPUT_FILE}" ]]; then
  err "Input file not found: ${INPUT_FILE}"
  exit 4
fi

if ! [[ "${RUN_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] || [[ "${RUN_TIMEOUT_SECONDS}" -le 0 ]]; then
  err "RUN_TIMEOUT_SECONDS must be a positive integer (got: ${RUN_TIMEOUT_SECONDS})"
  exit 6
fi

CMD=(python3 scripts/run_mvp.py --fund-code "${FUND_CODE}" --input "${INPUT_FILE}" --backend "${BACKEND}")

if command -v timeout >/dev/null 2>&1; then
  if ! timeout --foreground "${RUN_TIMEOUT_SECONDS}s" "${CMD[@]}"; then
    status=$?
    if [[ "${status}" -eq 124 ]]; then
      err "run_mvp.py timed out after ${RUN_TIMEOUT_SECONDS}s (fund_code=${FUND_CODE})"
      exit 124
    fi
    err "run_mvp.py failed (fund_code=${FUND_CODE}, input=${INPUT_FILE}, backend=${BACKEND})"
    exit 5
  fi
else
  "${CMD[@]}" &
  pid=$!
  elapsed=0
  while kill -0 "${pid}" 2>/dev/null; do
    if (( elapsed >= RUN_TIMEOUT_SECONDS )); then
      kill "${pid}" 2>/dev/null || true
      sleep 1
      kill -9 "${pid}" 2>/dev/null || true
      err "run_mvp.py timed out after ${RUN_TIMEOUT_SECONDS}s (fund_code=${FUND_CODE})"
      exit 124
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  if ! wait "${pid}"; then
    err "run_mvp.py failed (fund_code=${FUND_CODE}, input=${INPUT_FILE}, backend=${BACKEND})"
    exit 5
  fi
fi
