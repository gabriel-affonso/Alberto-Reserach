# Alberto OpenClaw Templates

These files are templates for an OpenClaw installation. `scripts/install.sh` copies them only after probing the local `openclaw` CLI and backing up existing files.

Current docs referenced by this package:

- Cron scheduled jobs use `openclaw cron add` / `openclaw cron create` with `--cron`, `--tz`, `--session isolated`, `--message` and `--agent`.
- Codex harness configuration lives under `plugins.entries.codex.config`.
- OpenClaw workspaces use bootstrap files including `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `HEARTBEAT.md`, `BOOTSTRAP.md` and `MEMORY.md`.

Run:

```bash
./scripts/install.sh
```
