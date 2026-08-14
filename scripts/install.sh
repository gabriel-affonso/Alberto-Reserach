#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALBERTO_HOME="${ALBERTO_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/alberto}"
ALBERTO_DB="${ALBERTO_DB:-$ALBERTO_HOME/alberto.sqlite3}"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-$OPENCLAW_HOME/openclaw.json}"
OPENCLAW_SKILLS_DIR="${OPENCLAW_SKILLS_DIR:-$OPENCLAW_HOME/skills}"
PROJECT_FILE="${ALBERTO_PROJECT_FILE:-$ROOT_DIR/projects/example-research.yaml}"
BACKUP_ROOT="${ALBERTO_BACKUP_ROOT:-$ALBERTO_HOME/backups}"
BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DRY_RUN=0
SKIP_OPENCLAW=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --skip-openclaw) SKIP_OPENCLAW=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [[ "${ALBERTO_INSTALL_DRY_RUN:-0}" == "1" ]]; then
  DRY_RUN=1
fi

say_phase() {
  printf '\n== %s ==\n' "$1"
}

run() {
  echo "+ $*"
  if [[ "$DRY_RUN" != "1" ]]; then
    "$@"
  fi
}

note() {
  echo "- $*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || { echo "$1 is required" >&2; exit 1; }
}

openclaw_available() {
  command -v openclaw >/dev/null 2>&1
}

openclaw_version() {
  openclaw --version 2>/dev/null || openclaw version 2>/dev/null || echo "unknown"
}

timestamp() {
  date -u +%Y%m%dT%H%M%SZ
}

backup_path() {
  local src="$1"
  local label="$2"
  if [[ ! -e "$src" ]]; then
    note "No existing $label found at $src"
    return
  fi
  local dest="$BACKUP_ROOT/$BACKUP_STAMP/$label"
  run mkdir -p "$(dirname "$dest")"
  run cp -R "$src" "$dest"
}

safe_install_dir() {
  local src="$1"
  local dest="$2"
  local label="$3"
  if [[ -e "$dest" ]]; then
    if diff -qr "$src" "$dest" >/dev/null 2>&1; then
      note "$label already installed and identical: $dest"
      return
    fi
    if [[ "${ALBERTO_ALLOW_OVERWRITE_OPENCLAW_FILES:-0}" != "1" ]]; then
      echo "Refusing to overwrite existing $label at $dest." >&2
      echo "Set ALBERTO_ALLOW_OVERWRITE_OPENCLAW_FILES=1 after reviewing the backup plan." >&2
      exit 1
    fi
    backup_path "$dest" "$label"
  fi
  run mkdir -p "$(dirname "$dest")"
  run cp -R "$src" "$dest"
}

config_get() {
  local path="$1"
  openclaw config get "$path" --json 2>/dev/null || true
}

ensure_agent_entry() {
  local agent_id="$1"
  local workspace="$2"
  local current
  current="$(config_get "agents.entries.$agent_id")"
  if [[ -n "$current" && "$current" != "null" ]]; then
    if printf '%s' "$current" | grep -F "$workspace" >/dev/null 2>&1; then
      note "OpenClaw agent $agent_id already points at $workspace"
      return
    fi
    if [[ "${ALBERTO_ALLOW_OPENCLAW_AGENT_UPDATE:-0}" != "1" ]]; then
      echo "Existing OpenClaw agent '$agent_id' differs from Alberto's desired workspace." >&2
      echo "No change made. Review with: openclaw config get agents.entries.$agent_id --json" >&2
      echo "Set ALBERTO_ALLOW_OPENCLAW_AGENT_UPDATE=1 only after confirming this is safe." >&2
      exit 1
    fi
  fi
  local payload
  payload="$(printf '{"workspace":"%s"}' "$workspace")"
  run openclaw config set "agents.entries.$agent_id" "$payload" --strict-json --merge
}

ensure_codex_harness() {
  local current
  current="$(config_get "plugins.entries.codex")"
  if [[ -n "$current" && "$current" != "null" ]]; then
    note "Codex plugin entry already exists; not replacing existing harness config"
    return
  fi
  local payload='{"enabled":true,"config":{"discovery":{"enabled":true,"timeoutMs":2500},"appServer":{"mode":"guardian","homeScope":"agent"},"codexDynamicToolsLoading":"searchable"}}'
  run openclaw config set "plugins.entries.codex" "$payload" --strict-json --merge
}

ensure_cron_job() {
  local name="$1"
  local cron_expr="$2"
  local message="$3"
  local jobs
  jobs="$(openclaw cron list 2>/dev/null || true)"
  if printf '%s' "$jobs" | grep -F "$name" >/dev/null 2>&1; then
    note "Cron job already exists: $name"
    return
  fi
  run openclaw cron add \
    --name "$name" \
    --cron "$cron_expr" \
    --tz "${ALBERTO_TIMEZONE:-Europe/Lisbon}" \
    --session isolated \
    --agent "${ALBERTO_OPENCLAW_AGENT:-alberto-research}" \
    --message "$message"
}

echo "Alberto installer"
echo "Root: $ROOT_DIR"
echo "Home: $ALBERTO_HOME"
echo "Database: $ALBERTO_DB"
echo "OpenClaw config: $OPENCLAW_CONFIG_PATH"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "Mode: dry-run"
fi

say_phase "preflight"
require_command python3
require_command git
preflight_args=()
if [[ "$SKIP_OPENCLAW" == "1" ]]; then
  preflight_args+=(--allow-missing-openclaw)
fi
if [[ "${#preflight_args[@]}" -gt 0 ]]; then
  run "$ROOT_DIR/scripts/preflight.sh" "${preflight_args[@]}"
else
  run "$ROOT_DIR/scripts/preflight.sh"
fi

say_phase "backup"
run mkdir -p "$BACKUP_ROOT"
backup_path "$ALBERTO_DB" "alberto.sqlite3"
if openclaw_available && [[ "$SKIP_OPENCLAW" != "1" ]]; then
  note "OpenClaw detected: $(command -v openclaw)"
  note "OpenClaw version: $(openclaw_version)"
  backup_path "$OPENCLAW_CONFIG_PATH" "openclaw.json"
  backup_path "$OPENCLAW_HOME/state" "openclaw-state"
  backup_path "$OPENCLAW_HOME/cron" "openclaw-cron"
else
  note "OpenClaw unavailable or skipped; OpenClaw backup skipped"
fi

say_phase "Python environment"
run mkdir -p "$ALBERTO_HOME" "$ALBERTO_HOME/documents" "$ALBERTO_HOME/digests" "$ALBERTO_HOME/logs"
if [[ ! -d "$ROOT_DIR/.venv" ]]; then
  run python3 -m venv "$ROOT_DIR/.venv"
fi
if [[ "$DRY_RUN" != "1" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.venv/bin/activate"
fi
run "$ROOT_DIR/.venv/bin/python" -m pip install --upgrade pip
run "$ROOT_DIR/.venv/bin/python" -m pip install -e "${ROOT_DIR}[test]"

say_phase "database"
run "$ROOT_DIR/.venv/bin/alberto" db migrate --db "$ALBERTO_DB"
run "$ROOT_DIR/.venv/bin/alberto" config validate "$PROJECT_FILE"

if openclaw_available && [[ "$SKIP_OPENCLAW" != "1" ]]; then
  say_phase "OpenClaw configuration"
  if [[ "$DRY_RUN" != "1" ]]; then
    openclaw --help >/dev/null
  fi
  note "Existing OpenClaw agents are preserved; Alberto entries are merged only by id."

  say_phase "agents"
  ensure_agent_entry "alberto-main" "$ROOT_DIR/openclaw/agents/alberto-main"
  ensure_agent_entry "alberto-research" "$ROOT_DIR/openclaw/agents/alberto-research"
  ensure_agent_entry "research-reader" "$ROOT_DIR/openclaw/agents/research-reader"

  say_phase "skills"
  safe_install_dir "$ROOT_DIR/openclaw/skills/research" "$OPENCLAW_SKILLS_DIR/alberto-research" "alberto-research-skill"

  say_phase "Codex harness"
  ensure_codex_harness

  say_phase "automations"
  if [[ "${ALBERTO_REGISTER_AUTOMATIONS:-1}" == "1" ]]; then
    ensure_cron_job "Alberto daily research workflow" "0 2 * * *" "Run: $ROOT_DIR/.venv/bin/alberto research run --project $PROJECT_FILE --db $ALBERTO_DB"
    ensure_cron_job "Alberto research digest delivery" "0 8 * * *" "Run: $ROOT_DIR/.venv/bin/alberto research digest --project $PROJECT_FILE --db $ALBERTO_DB --output-dir $ALBERTO_HOME/digests, then deliver through the configured delivery interface."
  else
    note "Automation registration disabled by ALBERTO_REGISTER_AUTOMATIONS=0"
  fi
else
  say_phase "OpenClaw configuration"
  note "OpenClaw unavailable or skipped; no OpenClaw config, agent, skill, harness or automation changes made"
  say_phase "agents"
  note "Skipped because OpenClaw is unavailable or --skip-openclaw was set"
  say_phase "skills"
  note "Skipped because OpenClaw is unavailable or --skip-openclaw was set"
  say_phase "Codex harness"
  note "Skipped because OpenClaw is unavailable or --skip-openclaw was set"
  say_phase "automations"
  note "Skipped because OpenClaw is unavailable or --skip-openclaw was set"
fi

say_phase "integration checks"
if [[ -n "${ZOTERO_API_KEY:-}" && -n "${ZOTERO_LIBRARY_ID:-}" ]]; then
  note "Zotero env appears configured"
else
  note "Zotero env not configured; optional integration skipped"
fi
if [[ "${ALBERTO_EMAIL_PROVIDER:-}" == "smtp" ]]; then
  note "SMTP delivery requested; installer does not send a test email"
else
  note "Email delivery not configured; local digest delivery remains enabled"
fi

say_phase "smoke test"
run "$ROOT_DIR/scripts/smoke-test.sh"

echo
echo "Installation report:"
echo "- Python package: prepared"
echo "- SQLite migrations: configured at $ALBERTO_DB"
echo "- OpenClaw: $(openclaw_available && echo detected || echo not-detected)"
echo "- Existing unrelated OpenClaw agents, jobs, plugins and config were not replaced"
