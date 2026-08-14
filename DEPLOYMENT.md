# Deployment

## Supported Install Flow

```bash
git clone <repository>
cd alberto
./scripts/install.sh
```

The installer is safe to run repeatedly. It performs preflight checks, creates `.venv`, installs Alberto, applies SQLite migrations, creates local runtime directories, copies OpenClaw templates when OpenClaw is available, and runs smoke tests.

## Runtime Directories

By default Alberto uses:

- `~/.alberto/alberto.sqlite3`
- `~/.alberto/documents`
- `~/.alberto/digests`
- `~/.alberto/logs`
- `~/.alberto/openclaw-backups`

Override with environment variables from `.env.example`.

## OpenClaw

The installer probes `openclaw --help` and then tries version-aware supported commands. It does not silently overwrite existing OpenClaw configuration. Existing files are backed up before replacement.

If OpenClaw is not installed, Alberto still installs its Python package and database, and reports that OpenClaw registration was skipped.

## Operations

```bash
./scripts/update.sh
./scripts/backup.sh
./scripts/smoke-test.sh
```

Network-dependent provider checks are intentionally not part of normal smoke tests.
