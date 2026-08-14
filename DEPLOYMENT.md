# Deployment

## Supported Install Flow

```bash
git clone <repository>
cd alberto
./scripts/preflight.sh
./scripts/install.sh --dry-run
./scripts/install.sh
```

The installer is safe to run repeatedly. It performs preflight checks, backs up existing Alberto/OpenClaw state where present, creates `.venv`, installs Alberto, applies SQLite migrations, creates local runtime directories, merges Alberto-specific OpenClaw entries, registers cron jobs when safe, and runs smoke tests.

## Runtime Directories

By default Alberto uses XDG-compatible Linux paths:

- `${XDG_STATE_HOME:-$HOME/.local/state}/alberto/alberto.sqlite3`
- `${XDG_STATE_HOME:-$HOME/.local/state}/alberto/documents`
- `${XDG_STATE_HOME:-$HOME/.local/state}/alberto/digests`
- `${XDG_STATE_HOME:-$HOME/.local/state}/alberto/logs`
- `${XDG_STATE_HOME:-$HOME/.local/state}/alberto/backups`

Override with environment variables from `.env.example`.

## OpenClaw

The installer probes `openclaw --version`, `openclaw doctor --lint --severity-min error --json`, `openclaw agents list --json`, `openclaw plugins list --json` and `openclaw cron list` where available. It does not silently overwrite existing OpenClaw configuration. The existing `main` agent remains Alberto's orchestrator and is never modified. Alberto creates only `alberto-research` and `research-reader` through `openclaw agents add`; unrelated entries are preserved, and conflicting Alberto-owned entries stop the install for review.

If OpenClaw is not installed, Alberto still installs its Python package and database, and reports that OpenClaw registration was skipped.

## Operations

```bash
./scripts/update.sh
./scripts/backup.sh
./scripts/smoke-test.sh
```

Network-dependent provider checks are intentionally not part of normal smoke tests.

For a Mac-to-Linux NUC deployment with existing OpenClaw state, see `docs/PRODUCTION_DEPLOYMENT.md`.
