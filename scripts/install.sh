#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALBERTO_HOME="${ALBERTO_HOME:-$HOME/.alberto}"
ALBERTO_DB="${ALBERTO_DB:-$ALBERTO_HOME/alberto.sqlite3}"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
PROJECT_FILE="${ALBERTO_PROJECT_FILE:-$ROOT_DIR/projects/example-research.yaml}"
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [[ "${ALBERTO_INSTALL_DRY_RUN:-0}" == "1" ]]; then
  DRY_RUN=1
fi

run() {
  echo "+ $*"
  if [[ "$DRY_RUN" != "1" ]]; then
    "$@"
  fi
}

copy_with_backup() {
  local src="$1"
  local dest="$2"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ copy $src -> $dest"
    return
  fi
  mkdir -p "$(dirname "$dest")"
  if [[ -e "$dest" ]]; then
    local backup="$ALBERTO_HOME/openclaw-backups/$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "$backup"
    cp -R "$dest" "$backup/"
    echo "Backed up existing $dest to $backup"
  fi
  cp -R "$src" "$dest"
}

echo "Alberto installer"
echo "Root: $ROOT_DIR"
echo "Home: $ALBERTO_HOME"
echo "Database: $ALBERTO_DB"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "Mode: dry-run"
fi

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

run mkdir -p "$ALBERTO_HOME" "$ALBERTO_HOME/documents" "$ALBERTO_HOME/digests" "$ALBERTO_HOME/logs" "$ALBERTO_HOME/openclaw-backups"

if [[ "$DRY_RUN" != "1" ]]; then
  if [[ ! -d "$ROOT_DIR/.venv" ]]; then
    run python3 -m venv "$ROOT_DIR/.venv"
  fi
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.venv/bin/activate"
  run python -m pip install --upgrade pip
  run python -m pip install -e "$ROOT_DIR[test]"
  run alberto db migrate --db "$ALBERTO_DB"
  run alberto config validate "$PROJECT_FILE"
else
  echo "+ python3 -m venv $ROOT_DIR/.venv"
  echo "+ python -m pip install -e $ROOT_DIR[test]"
  echo "+ alberto db migrate --db $ALBERTO_DB"
  echo "+ alberto config validate $PROJECT_FILE"
fi

if command -v openclaw >/dev/null 2>&1; then
  echo "OpenClaw detected: $(command -v openclaw)"
  if [[ "$DRY_RUN" != "1" ]]; then
    openclaw --help >/dev/null
  fi
  copy_with_backup "$ROOT_DIR/openclaw/agents/alberto-main" "$OPENCLAW_HOME/workspaces/alberto-main"
  copy_with_backup "$ROOT_DIR/openclaw/agents/alberto-research" "$OPENCLAW_HOME/workspaces/alberto-research"
  copy_with_backup "$ROOT_DIR/openclaw/agents/research-reader" "$OPENCLAW_HOME/workspaces/research-reader"
  copy_with_backup "$ROOT_DIR/openclaw/skills/research" "$OPENCLAW_HOME/skills/alberto-research"
  copy_with_backup "$ROOT_DIR/openclaw/policies" "$OPENCLAW_HOME/alberto-policies"
  if [[ "${ALBERTO_REGISTER_AUTOMATIONS:-1}" == "1" ]]; then
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "+ bash $ROOT_DIR/openclaw/automations.sh"
    else
      (cd "$ROOT_DIR" && bash "$ROOT_DIR/openclaw/automations.sh")
    fi
  fi
else
  echo "OpenClaw CLI not found; OpenClaw registration skipped."
  echo "Install OpenClaw, then rerun this installer to copy workspaces and register cron jobs."
fi

if [[ "$DRY_RUN" != "1" ]]; then
  run "$ROOT_DIR/scripts/smoke-test.sh"
fi

echo "Installation report:"
echo "- Python package: prepared"
echo "- SQLite migrations: configured"
echo "- Local digest directory: $ALBERTO_HOME/digests"
echo "- Zotero integration: optional; configured only when ZOTERO_API_KEY and ZOTERO_LIBRARY_ID are set"
echo "- Delivery integration: local always; email only when configured"
echo "- OpenClaw: $(command -v openclaw >/dev/null 2>&1 && echo detected || echo not-detected)"
