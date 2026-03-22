#!/usr/bin/env bash
set -euo pipefail

err() {
  echo "[run_one_click] ERROR: $*" >&2
}

log() {
  echo "[run_one_click] $*" >&2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

FUND_CODE="${1:-${FUND_CODE:-024194}}"
INPUT_FILE="${2:-${INPUT_FILE:-${PROJECT_DIR}/sample_data/${FUND_CODE}_docs.json}}"
BACKEND="${BACKEND:-mock}"
AUTO_FETCH="${AUTO_FETCH:-1}"
MAX_URLS="${MAX_URLS:-20}"
FETCH_TIMEOUT_SECONDS="${FETCH_TIMEOUT_SECONDS:-180}"

cd "${PROJECT_DIR}" || { err "Cannot cd to ${PROJECT_DIR}"; exit 2; }

if [[ "${AUTO_FETCH}" == "1" ]]; then
  log "Rebuilding docs from URLs for fund=${FUND_CODE} (replace old files) ..."
  rm -f "${INPUT_FILE}" "${INPUT_FILE%.json}.failures.json" "${INPUT_FILE%.json}.skipped.json"
  FETCH_CMD=(
    python3 scripts/build_docs_from_urls.py
    --fund-code "${FUND_CODE}"
    --output "${INPUT_FILE}"
    --max-urls "${MAX_URLS}"
  )

  if command -v timeout >/dev/null 2>&1; then
    if ! timeout --foreground "${FETCH_TIMEOUT_SECONDS}s" "${FETCH_CMD[@]}" >/dev/null; then
      status=$?
      if [[ "${status}" -eq 124 ]]; then
        err "build_docs_from_urls.py timed out after ${FETCH_TIMEOUT_SECONDS}s"
        exit 124
      fi
      err "build_docs_from_urls.py failed"
      exit 3
    fi
  else
    "${FETCH_CMD[@]}" >/dev/null || { err "build_docs_from_urls.py failed"; exit 3; }
  fi
else
  log "AUTO_FETCH=0, skip fetching"
fi

if [[ ! -f "${INPUT_FILE}" ]]; then
  err "Input file not found: ${INPUT_FILE}"
  exit 4
fi

# Final report is printed to stdout by run_report.sh (Telegram/OpenClaw friendly).
BACKEND="${BACKEND}" scripts/run_report.sh "${FUND_CODE}" "${INPUT_FILE}"
