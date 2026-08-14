from __future__ import annotations

import os
import subprocess
from pathlib import Path

from alberto.db.connection import connect
from alberto.db.migrations import apply_migrations
from alberto.research.models import DiscoveryResult, PaperRecord
from alberto.research.providers.base import Provider
from alberto.research.workflow import run_research_workflow


class FixtureProvider(Provider):
    name = "crossref"

    def search(self, query: str, *, limit: int, dry_run: bool = False):
        return DiscoveryResult(
            provider=self.name,
            query=query,
            records=(PaperRecord(title="Agent Sandbox", abstract="agent sandbox", doi="10.1/sandbox"),),
            dry_run=dry_run,
        )


def test_workflow_persists_run_and_candidates(tmp_path: Path) -> None:
    db_path = tmp_path / "alberto.sqlite3"
    run_id = run_research_workflow(
        project_path="projects/example-research.yaml",
        db_path=db_path,
        providers=[FixtureProvider()],
    )
    conn = connect(db_path)
    apply_migrations(conn)
    row = conn.execute("SELECT status, candidate_count FROM runs WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "SUCCEEDED"
    assert row["candidate_count"] == 1
    conn.close()


def test_installer_dry_run() -> None:
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
    assert "Mode: dry-run" in result.stdout
    assert "Installation report" in result.stdout
