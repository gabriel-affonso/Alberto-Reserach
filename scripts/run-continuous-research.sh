#!/usr/bin/env bash
set -euo pipefail

PROJECT_FILE="${1:-projects/greek-tragedy-function.yaml}"
INTERVAL_SECONDS="${ALBERTO_RESEARCH_INTERVAL_SECONDS:-3600}"
ENV_FILE="${ALBERTO_ENV_FILE:-$HOME/.alberto-env}"
ALBERTO_BIN="${ALBERTO_BIN:-./.venv/bin/alberto}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

while true; do
  printf '[%s] starting research cycle for %s\n' "$(date -Is)" "$PROJECT_FILE"
  if ! "$ALBERTO_BIN" research run --project "$PROJECT_FILE"; then
    printf '[%s] research run failed; continuing after sleep\n' "$(date -Is)" >&2
  fi

  if ! "$ALBERTO_BIN" research digest --project "$PROJECT_FILE"; then
    printf '[%s] digest generation failed; continuing after sleep\n' "$(date -Is)" >&2
  fi

  printf '[%s] sleeping for %s seconds\n' "$(date -Is)" "$INTERVAL_SECONDS"
  sleep "$INTERVAL_SECONDS"
done
