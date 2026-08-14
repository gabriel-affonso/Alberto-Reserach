#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/alberto-smoke.XXXXXX")"
DB_PATH="$TMP_DIR/alberto.sqlite3"
DIGEST_DIR="$TMP_DIR/digests"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON_BIN" -m alberto.cli db migrate --db "$DB_PATH" >/dev/null
"$PYTHON_BIN" -m alberto.cli config validate "$ROOT_DIR/projects/example-research.yaml" >/dev/null
"$PYTHON_BIN" -m alberto.cli research run --project "$ROOT_DIR/projects/example-research.yaml" --db "$DB_PATH" --dry-run >/dev/null
"$PYTHON_BIN" -m alberto.cli research digest --project "$ROOT_DIR/projects/example-research.yaml" --db "$DB_PATH" --output-dir "$DIGEST_DIR" >/dev/null
"$PYTHON_BIN" -m alberto.cli openclaw verify-templates >/dev/null

echo "Alberto smoke test succeeded"
