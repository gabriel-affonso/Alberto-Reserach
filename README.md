# Alberto

Alberto is a modular personal AI system designed for OpenClaw. V1 implements Alberto Research: a SQLite-backed research workflow for discovery, screening, structured readings, synthesis, digest generation, feedback and optional Zotero synchronization.

## Quick Start

```bash
git clone <repository>
cd alberto
./scripts/preflight.sh
./scripts/install.sh --dry-run
./scripts/install.sh
```

The installer is idempotent and safe for an existing OpenClaw host. It creates a Python virtual environment, installs dependencies, initializes or migrates SQLite, prepares local runtime directories, merges Alberto-specific OpenClaw entries only after backup/preflight, registers supported automations when possible, and runs smoke tests.

## Local Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
pytest
```

Run a dry discovery/digest workflow against the example project:

```bash
alberto research run --project projects/example-research.yaml --dry-run
alberto research digest --project projects/example-research.yaml
```

## Repository Layout

- `src/alberto/` - Python package and CLI.
- `migrations/` - SQLite migrations.
- `projects/` - version-controlled research project YAML configs.
- `openclaw/` - agent workspaces, skills, policies and automation templates.
- `scripts/` - install, update, backup and smoke-test scripts.
- `tests/` - unit tests and fixtures.
- `docs/` - architecture, deployment, security and implementation plan.

## Integrations

Zotero, email delivery and the Notion archive are optional. Configure them using environment variables copied from `.env.example`; no credentials are required for local digest generation or tests.

## Notion Archive

Alberto can maintain a searchable Notion database containing every validated reading that was included in a digest. SQLite remains the operational source of truth; Notion is a consultation archive.

1. Create a Notion internal integration and share an empty parent page with it.
2. Set `NOTION_API_KEY` and run `alberto notion setup --parent-page-id <page-id>`.
3. Copy the returned `data_source_id` to `NOTION_DATA_SOURCE_ID`, and set `notion.enabled: true` in the project YAML. On the production NUC, `ALBERTO_NOTION_ENABLED=1` is an equivalent environment-only switch.

Future `alberto research digest` runs create a page for each new digest reading and update that same page when the article is read again. Candidate-only digest items are intentionally not sent to Notion.

To archive digest readings that existed before Notion was enabled, run `alberto notion backfill --db "$ALBERTO_DB"`. It is idempotent and only includes readings that were actually represented in a digest.
