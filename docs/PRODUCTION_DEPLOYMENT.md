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

The installer preserves the existing OpenClaw `main` agent completely. `main` remains Alberto's orchestrator, including its existing workspace, sessions, credentials and model. For the current production host, this preserves the existing `ollama/qwen3.5:9b` model on `main`.

Alberto creates only `alberto-research` and `research-reader` using `openclaw agents add <agent-id> --workspace <workspace> --model <model> --non-interactive`. The default Alberto Research model is `openai/gpt-5.6-sol`; override with `ALBERTO_RESEARCH_MODEL` and `ALBERTO_READER_MODEL` if your installed OpenClaw model catalog requires a different OpenAI model id.

Existing unrelated OpenClaw agents, plugins, jobs and configuration are preserved. Existing Alberto Research-owned agent entries with conflicting workspace paths stop the install for manual review.

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
export SMTP_USERNAME=...
export SMTP_PASSWORD=...
export SMTP_FROM=...
export SMTP_TO=...
```

Notion archive requires an internal integration with access to a parent page. Set `NOTION_API_KEY`, run `alberto notion setup --parent-page-id <page-id>`, then store the returned `NOTION_DATA_SOURCE_ID`. For the production pipeline, set `ALBERTO_NOTION_ENABLED=1` in the service environment; this avoids changing a version-controlled project YAML.

After updating a NUC that already has prior digests, run `set -a; source ~/.alberto-env; set +a; alberto notion backfill --db "$ALBERTO_DB"` once to archive its historical digest readings. The command can be safely re-run after an interruption. It adds the required Alberto archive fields to an existing Notion database without removing its existing fields.

For Gmail or Google Workspace, use an app password rather than your account password. Local digest saving works without Zotero, email or Notion credentials.

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
- OpenClaw must support `openclaw agents add --workspace --model --non-interactive`.
- The NUC must have network/DNS access to Crossref, Semantic Scholar and Zotero when those workflows are enabled.
