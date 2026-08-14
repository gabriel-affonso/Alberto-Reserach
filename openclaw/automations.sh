#!/usr/bin/env bash
set -euo pipefail

PROJECT_FILE="${ALBERTO_PROJECT_FILE:-projects/example-research.yaml}"
TZ_NAME="${ALBERTO_TIMEZONE:-Europe/Lisbon}"
AGENT="${ALBERTO_OPENCLAW_AGENT:-alberto-research}"

openclaw cron add \
  --name "Alberto daily research workflow" \
  --cron "0 2 * * *" \
  --tz "$TZ_NAME" \
  --session isolated \
  --agent "$AGENT" \
  --message "Run: alberto research run --project $PROJECT_FILE"

openclaw cron add \
  --name "Alberto research digest delivery" \
  --cron "0 8 * * *" \
  --tz "$TZ_NAME" \
  --session isolated \
  --agent "$AGENT" \
  --message "Run: alberto research digest --project $PROJECT_FILE, save locally, and deliver through the configured delivery interface."
