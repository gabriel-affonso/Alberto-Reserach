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
ALBERTO_RESEARCH_MODEL="${ALBERTO_RESEARCH_MODEL:-openai/gpt-5.6-sol}"
ALBERTO_READER_MODEL="${ALBERTO_READER_MODEL:-openai/gpt-5.6-sol}"
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
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ install $label from $src to $dest if absent or explicitly approved"
    return
  fi
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

ensure_codex_harness() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ inspect OpenClaw plugin inventory for codex"
    note "Would preserve existing Codex plugin configuration"
    return
  fi
  if openclaw plugins list --json 2>/dev/null | grep -i '"codex"' >/dev/null 2>&1; then
    note "Codex plugin entry already exists; not replacing existing harness config"
    return
  fi
  note "Codex plugin was not confirmed by OpenClaw plugin inventory; leaving existing plugin configuration unchanged"
}

verify_agents_add_cli() {
  run openclaw agents add --help
}

agent_list_json() {
  openclaw agents list --json 2>/dev/null || openclaw agents list 2>/dev/null || true
}

agent_exists_in_list() {
  local agent_id="$1"
  local agents_json="$2"
  AGENTS_JSON="$agents_json" python3 - "$agent_id" <<'PY'
import json
import os
import re
import sys

agent_id = sys.argv[1]
text = os.environ.get("AGENTS_JSON", "")
try:
    payload = json.loads(text)
except json.JSONDecodeError:
    raise SystemExit(0 if re.search(rf"(^|[^A-Za-z0-9_-]){re.escape(agent_id)}([^A-Za-z0-9_-]|$)", text) else 1)

if isinstance(payload, dict):
    candidates = payload.get("agents") or payload.get("list") or payload.get("entries") or payload.get("data") or []
elif isinstance(payload, list):
    candidates = payload
else:
    candidates = []

for item in candidates:
    if isinstance(item, str) and item == agent_id:
        raise SystemExit(0)
    if isinstance(item, dict) and str(item.get("id") or item.get("name") or "") == agent_id:
        raise SystemExit(0)
raise SystemExit(1)
PY
}

agent_workspace_in_list() {
  local agent_id="$1"
  local workspace="$2"
  local agents_json="$3"
  AGENTS_JSON="$agents_json" python3 - "$agent_id" "$workspace" <<'PY'
import json
import os
import sys

agent_id = sys.argv[1]
workspace = sys.argv[2]
text = os.environ.get("AGENTS_JSON", "")
try:
    payload = json.loads(text)
except json.JSONDecodeError:
    raise SystemExit(2)

if isinstance(payload, dict):
    candidates = payload.get("agents") or payload.get("list") or payload.get("entries") or payload.get("data") or []
elif isinstance(payload, list):
    candidates = payload
else:
    candidates = []

for item in candidates:
    if isinstance(item, dict) and str(item.get("id") or item.get("name") or "") == agent_id:
        actual = str(item.get("workspace") or item.get("workspaceDir") or "")
        if actual == workspace:
            raise SystemExit(0)
        if actual:
            print(actual)
            raise SystemExit(1)
        raise SystemExit(2)
raise SystemExit(2)
PY
}

agent_model_in_list() {
  local agent_id="$1"
  local model="$2"
  local agents_json="$3"
  AGENTS_JSON="$agents_json" python3 - "$agent_id" "$model" <<'PY'
import json
import os
import sys

agent_id = sys.argv[1]
model = sys.argv[2]
text = os.environ.get("AGENTS_JSON", "")
try:
    payload = json.loads(text)
except json.JSONDecodeError:
    raise SystemExit(2)

if isinstance(payload, dict):
    candidates = payload.get("agents") or payload.get("list") or payload.get("entries") or payload.get("data") or []
elif isinstance(payload, list):
    candidates = payload
else:
    candidates = []

for item in candidates:
    if isinstance(item, dict) and str(item.get("id") or item.get("name") or "") == agent_id:
        actual = str(item.get("model") or item.get("runtimeModel") or "")
        if actual == model:
            raise SystemExit(0)
        if actual:
            print(actual)
            raise SystemExit(1)
        raise SystemExit(2)
raise SystemExit(2)
PY
}

ensure_openclaw_agent() {
  local agent_id="$1"
  local workspace="$2"
  local model="$3"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ openclaw agents list --json"
    echo "+ openclaw agents add $agent_id --workspace $workspace --model $model --non-interactive --json if missing"
    return
  fi
  local agents
  agents="$(agent_list_json)"
  if agent_exists_in_list "$agent_id" "$agents"; then
    note "OpenClaw agent already exists: $agent_id"
    local workspace_check
    set +e
    workspace_check="$(agent_workspace_in_list "$agent_id" "$workspace" "$agents")"
    local workspace_status=$?
    set -e
    case "$workspace_status" in
      0) note "Verified $agent_id workspace: $workspace" ;;
      1)
        echo "Existing OpenClaw agent '$agent_id' points at a different workspace: $workspace_check" >&2
        echo "No change made. Only Alberto Research-owned agents may be reviewed and corrected manually." >&2
        exit 1
        ;;
      *) note "Agent $agent_id exists; workspace was not present in agents list output, so no modification was made" ;;
    esac
    local model_check
    set +e
    model_check="$(agent_model_in_list "$agent_id" "$model" "$agents")"
    local model_status=$?
    set -e
    case "$model_status" in
      0) note "Verified $agent_id model: $model" ;;
      1)
        echo "Existing OpenClaw agent '$agent_id' uses a different model: $model_check" >&2
        echo "No change made. Review Alberto-owned agent runtime with supported OpenClaw operations." >&2
        exit 1
        ;;
      *) note "Agent $agent_id exists; model was not present in agents list output, so no modification was made" ;;
    esac
    return
  fi
  run openclaw agents add "$agent_id" \
    --workspace "$workspace" \
    --model "$model" \
    --non-interactive \
    --json
}

ensure_cron_job() {
  local name="$1"
  local cron_expr="$2"
  local message="$3"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ openclaw cron list"
    echo "+ openclaw cron add --name $name --cron $cron_expr --tz ${ALBERTO_TIMEZONE:-Europe/Lisbon} --session isolated --agent ${ALBERTO_OPENCLAW_AGENT:-alberto-research} --message $message if missing"
    return
  fi
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
  if [[ "$DRY_RUN" == "1" ]]; then
    note "Would detect OpenClaw version"
  else
    note "OpenClaw version: $(openclaw_version)"
  fi
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
  note "Existing OpenClaw main agent is preserved and remains Alberto's orchestrator."

  say_phase "agents"
  verify_agents_add_cli
  note "Not creating a separate orchestrator agent; existing main remains untouched."
  ensure_openclaw_agent "alberto-research" "$ROOT_DIR/openclaw/agents/alberto-research" "$ALBERTO_RESEARCH_MODEL"
  ensure_openclaw_agent "research-reader" "$ROOT_DIR/openclaw/agents/research-reader" "$ALBERTO_READER_MODEL"

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
