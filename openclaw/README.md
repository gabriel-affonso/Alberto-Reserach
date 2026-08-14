# Alberto OpenClaw Templates

These files are templates for an OpenClaw installation. `scripts/install.sh` installs Alberto Research by using supported OpenClaw CLI operations and backing up existing files first.

Current docs referenced by this package:

- Agents are created with `openclaw agents add <agent-id> --workspace <workspace> --model <model> --non-interactive`.
- The existing OpenClaw `main` agent remains Alberto's orchestrator; Alberto does not create `alberto-main`.
- Cron scheduled jobs use `openclaw cron add` / `openclaw cron create` with `--cron`, `--tz`, `--session isolated`, `--message` and `--agent`.
- Codex harness configuration lives under `plugins.entries.codex.config`.
- OpenClaw workspaces use bootstrap files including `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `HEARTBEAT.md`, `BOOTSTRAP.md` and `MEMORY.md`.

Run:

```bash
./scripts/install.sh
```
