from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def openclaw_template_dir() -> Path:
    return repo_root() / "openclaw"


def required_openclaw_paths() -> list[Path]:
    root = openclaw_template_dir()
    return [
        root / "agents" / "alberto-research" / "AGENTS.md",
        root / "agents" / "research-reader" / "AGENTS.md",
        root / "policies" / "research-reader-sandbox.json",
        root / "automations.sh",
    ]
