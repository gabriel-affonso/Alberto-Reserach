#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALBERTO_HOME="${ALBERTO_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/alberto}"
ALBERTO_DB="${ALBERTO_DB:-$ALBERTO_HOME/alberto.sqlite3}"
BACKUP_DIR="${ALBERTO_BACKUP_DIR:-$ROOT_DIR/backups/$(date -u +%Y%m%dT%H%M%SZ)}"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-$OPENCLAW_HOME/openclaw.json}"

mkdir -p "$BACKUP_DIR"
if [[ -f "$ALBERTO_DB" ]]; then
  cp "$ALBERTO_DB" "$BACKUP_DIR/alberto.sqlite3"
fi
if [[ -f "$OPENCLAW_CONFIG_PATH" ]]; then
  cp "$OPENCLAW_CONFIG_PATH" "$BACKUP_DIR/openclaw.json"
fi
if [[ -d "$OPENCLAW_HOME/state" ]]; then
  cp -R "$OPENCLAW_HOME/state" "$BACKUP_DIR/openclaw-state"
fi
if [[ -d "$OPENCLAW_HOME/cron" ]]; then
  cp -R "$OPENCLAW_HOME/cron" "$BACKUP_DIR/openclaw-cron"
fi
if [[ -d "$ALBERTO_HOME/digests" ]]; then
  cp -R "$ALBERTO_HOME/digests" "$BACKUP_DIR/digests"
fi
if [[ -d "$ALBERTO_HOME/documents" ]]; then
  cp -R "$ALBERTO_HOME/documents" "$BACKUP_DIR/documents"
fi
cp -R "$ROOT_DIR/projects" "$BACKUP_DIR/projects"
echo "Backup written to $BACKUP_DIR"
