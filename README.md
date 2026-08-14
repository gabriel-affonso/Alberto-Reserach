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

Zotero and email delivery are optional. Configure them using environment variables copied from `.env.example`; no credentials are required for local digest generation or tests.
