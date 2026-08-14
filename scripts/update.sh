#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALBERTO_DB="${ALBERTO_DB:-${ALBERTO_HOME:-$HOME/.alberto}/alberto.sqlite3}"

echo "Updating Alberto from $ROOT_DIR"
if [[ -d "$ROOT_DIR/.git" ]]; then
  git -C "$ROOT_DIR" pull --ff-only
else
  echo "No git repository found; skipping git pull."
fi

if [[ ! -d "$ROOT_DIR/.venv" ]]; then
  python3 -m venv "$ROOT_DIR/.venv"
fi

# shellcheck disable=SC1091
source "$ROOT_DIR/.venv/bin/activate"
python -m pip install -e "$ROOT_DIR[test]"
alberto db migrate --db "$ALBERTO_DB"
"$ROOT_DIR/scripts/smoke-test.sh"
