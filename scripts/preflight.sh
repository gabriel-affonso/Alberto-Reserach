#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALBERTO_HOME="${ALBERTO_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/alberto}"
ALBERTO_DB="${ALBERTO_DB:-$ALBERTO_HOME/alberto.sqlite3}"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-$OPENCLAW_HOME/openclaw.json}"
PROJECT_FILE="${ALBERTO_PROJECT_FILE:-$ROOT_DIR/projects/example-research.yaml}"
ALLOW_MISSING_OPENCLAW=0
SKIP_NETWORK_CHECK=0
CHECK_WRITABLE_TARGET=""

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --allow-missing-openclaw) ALLOW_MISSING_OPENCLAW=1; shift ;;
    --skip-network-check) SKIP_NETWORK_CHECK=1; shift ;;
    --check-writable-target)
      CHECK_WRITABLE_TARGET="${2:-}"
      if [[ -z "$CHECK_WRITABLE_TARGET" ]]; then
        echo "--check-writable-target requires a path" >&2
        exit 2
      fi
      shift 2
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

STATUS=0

section() {
  printf '\n== %s ==\n' "$1"
}

ok() {
  echo "[ok] $*"
}

warn() {
  echo "[warn] $*"
}

fail() {
  echo "[fail] $*" >&2
  STATUS=1
}

have() {
  command -v "$1" >/dev/null 2>&1
}

show_command_output() {
  local label="$1"
  shift
  echo "--- $label ---"
  if "$@" 2>&1; then
    return 0
  fi
  warn "$label command failed"
  return 1
}

check_python() {
  if ! have python3; then
    fail "python3 not found"
    return
  fi
  python3 - <<'PY'
import sqlite3
import sys
version = sys.version_info
print(f"python={version.major}.{version.minor}.{version.micro}")
print(f"sqlite={sqlite3.sqlite_version}")
if version < (3, 11):
    raise SystemExit("Python 3.11 or newer is required")
PY
}

check_writable_target() {
  local path="$1"
  if [[ -f "$path" ]]; then
    if [[ -w "$path" ]]; then
      ok "Writable file: $path"
    else
      fail "Target file is not writable: $path"
    fi
    return
  fi
  if [[ -d "$path" ]]; then
    if [[ -w "$path" ]]; then
      ok "Writable directory: $path"
    else
      fail "Target directory is not writable: $path"
    fi
    return
  fi
  if [[ -e "$path" ]]; then
    if [[ -w "$path" ]]; then
      ok "Writable existing path: $path"
    else
      fail "Existing path is not writable: $path"
    fi
    return
  fi

  local parent
  parent="$(dirname "$path")"
  while [[ ! -e "$parent" && "$parent" != "/" ]]; do
    parent="$(dirname "$parent")"
  done
  if [[ -d "$parent" && -w "$parent" ]]; then
    ok "Writable target parent: $parent"
  else
    fail "Target parent is not writable for $path: $parent"
  fi
}

if [[ -n "$CHECK_WRITABLE_TARGET" ]]; then
  check_writable_target "$CHECK_WRITABLE_TARGET"
  exit "$STATUS"
fi

openclaw_version() {
  openclaw --version 2>/dev/null || openclaw version 2>/dev/null || echo "unknown"
}

section "OS and architecture"
uname -a
case "$(uname -s)" in
  Linux) ok "Linux host detected" ;;
  Darwin) warn "macOS host detected; production target is expected to be Linux" ;;
  *) warn "Unrecognized OS: $(uname -s)" ;;
esac

section "Required commands"
if have git; then
  git --version
else
  fail "git not found"
fi
check_python || fail "Python/SQLite check failed"

section "Repository"
echo "repo=$ROOT_DIR"
if [[ -f "$ROOT_DIR/pyproject.toml" && -d "$ROOT_DIR/src/alberto" ]]; then
  ok "Alberto repository layout detected"
else
  fail "Alberto repository layout incomplete"
fi

section "OpenClaw"
if have openclaw; then
  ok "openclaw found at $(command -v openclaw)"
  echo "version=$(openclaw_version)"
  show_command_output "openclaw agents list --json" openclaw agents list --json || true
  show_command_output "openclaw plugins list" openclaw plugins list --json || true
  show_command_output "openclaw cron list" openclaw cron list || true
  if openclaw doctor --help >/dev/null 2>&1; then
    show_command_output "openclaw doctor --lint --severity-min error --json" openclaw doctor --lint --severity-min error --json || fail "OpenClaw doctor reported error-level findings"
  else
    warn "openclaw doctor unavailable"
  fi
  if openclaw config get plugins.entries.codex --json >/dev/null 2>&1; then
    ok "Codex harness config path is readable"
  elif openclaw plugins list --json 2>/dev/null | grep -i '"codex"' >/dev/null 2>&1; then
    ok "Codex plugin appears in plugin inventory"
  else
    warn "Codex harness/plugin was not confirmed"
  fi
else
  if [[ "$ALLOW_MISSING_OPENCLAW" == "1" ]]; then
    warn "openclaw not found; allowed by flag"
  else
    fail "openclaw not found"
  fi
fi

section "Writable target directories"
check_writable_target "$ALBERTO_HOME"
check_writable_target "$ALBERTO_DB"
check_writable_target "$OPENCLAW_HOME"
check_writable_target "$OPENCLAW_CONFIG_PATH"

section "Environment"
echo "ALBERTO_HOME=$ALBERTO_HOME"
echo "ALBERTO_DB=$ALBERTO_DB"
echo "OPENCLAW_HOME=$OPENCLAW_HOME"
echo "OPENCLAW_CONFIG_PATH=$OPENCLAW_CONFIG_PATH"
echo "ALBERTO_PROJECT_FILE=$PROJECT_FILE"
if [[ -n "${ZOTERO_API_KEY:-}" && -n "${ZOTERO_LIBRARY_ID:-}" ]]; then
  ok "Zotero environment appears configured"
else
  warn "Zotero environment not configured; optional sync will be skipped"
fi
if [[ "${ALBERTO_EMAIL_PROVIDER:-}" == "smtp" ]]; then
  if [[ -n "${SMTP_HOST:-}" && -n "${SMTP_FROM:-}" && -n "${SMTP_TO:-}" ]]; then
    ok "SMTP delivery environment appears configured"
  else
    fail "ALBERTO_EMAIL_PROVIDER=smtp but SMTP_HOST/SMTP_FROM/SMTP_TO are incomplete"
  fi
else
  warn "Email delivery not configured; local digest saving is still available"
fi

section "Project config"
PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m alberto.cli config validate "$PROJECT_FILE" || fail "Project config validation failed"

section "Network/API prerequisites"
if [[ "$SKIP_NETWORK_CHECK" == "1" ]]; then
  warn "Network checks skipped"
else
  python3 - <<'PY' || fail "DNS prerequisite check failed"
import socket
hosts = ["api.crossref.org", "api.semanticscholar.org", "api.zotero.org"]
for host in hosts:
    try:
        print(f"{host}={socket.gethostbyname(host)}")
    except OSError as exc:
        raise SystemExit(f"{host}: {exc}")
PY
fi

section "Result"
if [[ "$STATUS" == "0" ]]; then
  ok "Preflight completed without blocking failures"
else
  fail "Preflight found blocking failures"
fi
exit "$STATUS"
