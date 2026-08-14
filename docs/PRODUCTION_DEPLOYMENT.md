# Production Deployment: Development Mac To Linux NUC

This guide prepares a Linux NUC that already has OpenClaw installed and running. It is written to preserve existing OpenClaw configuration, agents, plugins, cron jobs and state.

## Transfer

From the development Mac, push or copy the repository to the Linux NUC using your normal Git remote or an archive. Do not copy `.venv`, `.pytest_cache`, `data`, `logs`, `backups`, `.env`, SQLite databases or other local runtime artifacts.

On the NUC:

```bash
git clone <repository> ~/src/alberto
cd ~/src/alberto
```

## Read-Only Preflight

Run preflight before installation:

```bash
./scripts/preflight.sh
```

Preflight makes no configuration changes. It checks the OS, CPU architecture, Python, SQLite, Git, OpenClaw version, OpenClaw doctor lint status, existing agents, plugins, cron jobs, Codex harness visibility, writable target directories, environment variables and DNS prerequisites.

If DNS checks are intentionally blocked on the host:

```bash
./scripts/preflight.sh --skip-network-check
```

## Dry Run

Preview exactly what the installer would create, modify or register:

```bash
./scripts/install.sh --dry-run
```

Dry run does not create directories, install packages, migrate SQLite, edit OpenClaw config, copy skills or register cron jobs.

## Install

Run the installer only after reviewing preflight and dry-run output:

```bash
./scripts/install.sh
```

Installer phases:

- preflight
- backup
- Python environment
- database
- OpenClaw configuration
- agents
- skills
- Codex harness
- automations
- integration checks
- smoke test

The installer merges Alberto-specific OpenClaw entries by id. Existing unrelated OpenClaw agents, plugins, jobs and configuration are preserved. Existing Alberto agent entries with conflicting workspace paths stop the install unless `ALBERTO_ALLOW_OPENCLAW_AGENT_UPDATE=1` is set after review.

## Paths

Defaults are Linux/XDG-compatible:

- `ALBERTO_HOME=${XDG_STATE_HOME:-$HOME/.local/state}/alberto`
- `ALBERTO_DB=$ALBERTO_HOME/alberto.sqlite3`
- `OPENCLAW_HOME=$HOME/.openclaw`
- `OPENCLAW_CONFIG_PATH=$OPENCLAW_HOME/openclaw.json`

Override these with environment variables when the NUC uses a different layout.

## Optional Integrations

Zotero sync requires:

```bash
export ZOTERO_API_KEY=...
export ZOTERO_LIBRARY_TYPE=user
export ZOTERO_LIBRARY_ID=...
```

SMTP delivery requires:

```bash
export ALBERTO_EMAIL_PROVIDER=smtp
export SMTP_HOST=...
export SMTP_PORT=587
export SMTP_FROM=...
export SMTP_TO=...
```

Local digest saving works without Zotero or email credentials.

## Rollback

Before changes, the installer copies Alberto DB and OpenClaw config/state artifacts into `$ALBERTO_HOME/backups/<timestamp>/` when they exist.

To roll back:

1. Stop or pause OpenClaw using your existing production operating procedure.
2. Restore `openclaw.json` from the selected backup to `$OPENCLAW_CONFIG_PATH`.
3. Restore OpenClaw `state` or `cron` directories only if the failed install actually modified those areas.
4. Restore `alberto.sqlite3` to `$ALBERTO_DB` if database migrations need to be reverted.
5. Restart OpenClaw.
6. Run `./scripts/preflight.sh --skip-network-check` and `./scripts/smoke-test.sh`.

The installer does not delete non-Alberto OpenClaw configuration. Rollback should therefore be limited to Alberto-specific changes unless a production operator deliberately chooses a broader restore.

## Remaining Host-Dependent Assumptions

- OpenClaw CLI commands must match the installed version's current command surface.
- `openclaw doctor --lint --severity-min error --json` must be available for strict health checks.
- OpenClaw must permit `openclaw config set ... --merge` for agent and plugin entries.
- The NUC must have network/DNS access to Crossref, Semantic Scholar and Zotero when those workflows are enabled.
