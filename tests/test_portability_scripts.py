from __future__ import annotations

import os
import subprocess
from pathlib import Path


FORBIDDEN_PATH_PATTERNS = (
    "/" + "Users" + "/",
    "/" + "Users" + "/" + "gabriel.affonso",
    "Documents" + "/" + "Alberto",
    "/" + "opt" + "/" + "homebrew",
    "Home" + "brew",
    "Library" + "/" + "Application Support",
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line]


def test_no_hardcoded_development_paths_in_tracked_files() -> None:
    offenders: list[str] = []
    for path in tracked_files():
        if not path.exists():
            continue
        if path.suffix in {".pyc", ".sqlite", ".db"}:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATH_PATTERNS:
            if pattern in text:
                offenders.append(f"{path}:{pattern}")
    assert offenders == []


def test_scripts_are_bash_syntax_clean() -> None:
    for script in sorted(Path("scripts").glob("*.sh")):
        subprocess.run(["bash", "-n", str(script)], cwd=Path.cwd(), check=True)


def test_preflight_is_read_only_with_fake_openclaw(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    openclaw = fake_bin / "openclaw"
    openclaw.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--version" ]]; then echo "openclaw 9.9.9"; exit 0; fi
if [[ "${1:-}" == "agents" && "${2:-}" == "list" ]]; then echo '{"agents":[{"id":"main","workspace":"/tmp/main","model":"ollama/qwen3.5:9b"}]}'; exit 0; fi
if [[ "${1:-}" == "config" && "${2:-}" == "get" ]]; then echo '{}'; exit 0; fi
if [[ "${1:-}" == "plugins" && "${2:-}" == "list" ]]; then echo '{"plugins":[{"id":"codex","enabled":true}]}'; exit 0; fi
if [[ "${1:-}" == "cron" && "${2:-}" == "list" ]]; then echo '[]'; exit 0; fi
if [[ "${1:-}" == "doctor" && "${2:-}" == "--help" ]]; then echo 'doctor help'; exit 0; fi
if [[ "${1:-}" == "doctor" ]]; then echo '{"ok":true,"findings":[]}'; exit 0; fi
echo "unexpected openclaw args: $*" >&2
exit 1
""",
        encoding="utf-8",
    )
    openclaw.chmod(0o755)
    state = tmp_path / "state"
    openclaw_home = tmp_path / "openclaw"
    state.mkdir()
    openclaw_home.mkdir()
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["XDG_STATE_HOME"] = str(state)
    env["OPENCLAW_HOME"] = str(openclaw_home)
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = subprocess.run(
        ["scripts/preflight.sh", "--skip-network-check"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    assert "Preflight completed without blocking failures" in result.stdout
    assert list(openclaw_home.iterdir()) == []


def run_writable_check(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["scripts/preflight.sh", "--check-writable-target", str(path)],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )


def test_preflight_writable_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "openclaw.json"
    target.write_text("{}", encoding="utf-8")
    result = run_writable_check(target)
    assert result.returncode == 0
    assert f"[ok] Writable file: {target}" in result.stdout


def test_preflight_non_writable_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "openclaw.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o400)
    try:
        result = run_writable_check(target)
    finally:
        target.chmod(0o600)
    assert result.returncode == 1
    assert f"[fail] Target file is not writable: {target}" in result.stderr


def test_preflight_nonexistent_file_with_writable_parent(tmp_path: Path) -> None:
    target = tmp_path / "openclaw.json"
    result = run_writable_check(target)
    assert result.returncode == 0
    assert f"[ok] Writable target parent: {tmp_path}" in result.stdout


def test_preflight_nonexistent_nested_path_uses_existing_parent(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "nested" / "openclaw.json"
    result = run_writable_check(target)
    assert result.returncode == 0
    assert f"[ok] Writable target parent: {tmp_path}" in result.stdout


def test_preflight_writable_existing_directory(tmp_path: Path) -> None:
    result = run_writable_check(tmp_path)
    assert result.returncode == 0
    assert f"[ok] Writable directory: {tmp_path}" in result.stdout


def test_install_dry_run_reports_phases() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = subprocess.run(
        ["scripts/install.sh", "--dry-run"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    for phase in (
        "preflight",
        "backup",
        "Python environment",
        "database",
        "OpenClaw configuration",
        "agents",
        "skills",
        "Codex harness",
        "automations",
        "integration checks",
        "smoke test",
    ):
        assert f"== {phase} ==" in result.stdout


def test_installer_preserves_main_and_does_not_create_alberto_main() -> None:
    install_script = Path("scripts/install.sh").read_text(encoding="utf-8")
    assert "ensure_openclaw_agent \"main\"" not in install_script
    assert "ensure_openclaw_agent \"alberto-main\"" not in install_script
    assert "agents add main" not in install_script
    assert "agents add alberto-main" not in install_script
    assert "Existing OpenClaw main agent is preserved" in install_script


def test_agent_creation_uses_supported_openclaw_agents_add() -> None:
    install_script = Path("scripts/install.sh").read_text(encoding="utf-8")
    assert "openclaw agents add \"$agent_id\"" in install_script
    assert "--workspace \"$workspace\"" in install_script
    assert "--non-interactive" in install_script
    assert "openclaw config set \"agents.entries.$agent_id\"" not in install_script
    assert "agents.entries.alberto-research" not in install_script


def test_existing_research_agent_is_not_duplicated() -> None:
    install_script = Path("scripts/install.sh").read_text(encoding="utf-8")
    assert "if agent_exists_in_list \"$agent_id\" \"$agents\"; then" in install_script
    assert "OpenClaw agent already exists: $agent_id" in install_script
    assert "return" in install_script


def test_install_dry_run_with_fake_openclaw_has_zero_mutations(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "openclaw.log"
    openclaw = fake_bin / "openclaw"
    openclaw.write_text(
        f"""#!/usr/bin/env bash
echo "$@" >> "{log_path}"
exit 0
""",
        encoding="utf-8",
    )
    openclaw.chmod(0o755)
    state = tmp_path / "state"
    openclaw_home = tmp_path / "openclaw"
    db_path = state / "alberto" / "alberto.sqlite3"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["XDG_STATE_HOME"] = str(state)
    env["OPENCLAW_HOME"] = str(openclaw_home)
    env["ALBERTO_DB"] = str(db_path)
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    result = subprocess.run(
        ["scripts/install.sh", "--dry-run"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    assert "openclaw agents add alberto-research" in result.stdout
    assert "openclaw agents add research-reader" in result.stdout
    assert "alberto-main" not in result.stdout
    assert not log_path.exists()
    assert not state.exists()
    assert not openclaw_home.exists()


def test_partially_initialized_venv_and_database_resume_safely(tmp_path: Path) -> None:
    db_path = tmp_path / "alberto.sqlite3"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    for _ in range(2):
        subprocess.run(
            [
                ".venv/bin/python",
                "-m",
                "alberto.cli",
                "db",
                "migrate",
                "--db",
                str(db_path),
            ],
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
            env=env,
            check=True,
        )
    assert db_path.exists()
