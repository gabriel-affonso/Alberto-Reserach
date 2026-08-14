from __future__ import annotations

import os
import subprocess
from pathlib import Path

from alberto.db.connection import connect
from alberto.db.migrations import apply_migrations
from alberto.research.models import DiscoveryResult, PaperRecord
from alberto.research.providers.base import Provider
from alberto.research.workflow import (
    build_queries,
    run_digest_workflow,
    run_research_workflow,
    semantic_screen_candidate,
)


class FixtureProvider(Provider):
    name = "crossref"

    def search(self, query: str, *, limit: int, dry_run: bool = False):
        return DiscoveryResult(
            provider=self.name,
            query=query,
            records=(PaperRecord(title="Agent Sandbox", abstract="agent sandbox", doi="10.1/sandbox"),),
            dry_run=dry_run,
        )


class DeepReadProvider(Provider):
    name = "crossref"

    def search(self, query: str, *, limit: int, dry_run: bool = False):
        return DiscoveryResult(
            provider=self.name,
            query=query,
            records=(
                PaperRecord(title="Agent sandbox systems one", abstract="agent sandbox systems reading", doi="10.1/one"),
                PaperRecord(title="Agent sandbox systems two", abstract="agent sandbox systems reading", doi="10.1/two"),
                PaperRecord(title="Agent sandbox systems three", abstract="agent sandbox systems reading", doi="10.1/three"),
            ),
            dry_run=dry_run,
        )


class BrokenProvider(Provider):
    name = "semantic_scholar"

    def search(self, query: str, *, limit: int, dry_run: bool = False):
        raise RuntimeError("provider unavailable")


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


def write_project(tmp_path: Path) -> Path:
    path = tmp_path / "project.yaml"
    path.write_text(
        """
id: workflow-test
name: Workflow Test
research_question: agent sandbox systems
priority_topics:
  - agent sandbox
languages:
  - en
inclusion_terms:
  - agent
  - sandbox
exclusion_terms:
  - unrelated
discovery_limits:
  crossref: 2
  semantic_scholar: 2
screening_threshold: 0.4
deep_reading_threshold: 0.7
maximum_daily_deep_reads: 2
citation_chasing:
  enabled: false
digest:
  enabled: true
  max_items: 5
timezone: Europe/Lisbon
""",
        encoding="utf-8",
    )
    return path


def test_query_generation_uses_composed_queries() -> None:
    queries = build_queries(
        {
            "research_question": "agent orchestration for hostile papers",
            "priority_topics": ["sandboxed readers", "citation chasing", "digest synthesis", "zotero sync"],
            "inclusion_terms": ["prompt injection", "abstract screening", "metadata"],
        }
    )
    assert 1 <= len(queries) <= 4
    assert all("agent orchestration for hostile papers" in query for query in queries)
    assert "prompt injection" not in queries
    assert "sandboxed readers" not in queries


def test_semantic_screening_scores_and_rationale() -> None:
    config = {
        "research_question": "agent sandbox systems",
        "priority_topics": ["agent sandbox"],
        "inclusion_terms": ["agent", "sandbox"],
        "exclusion_terms": [],
        "screening_threshold": 0.4,
        "deep_reading_threshold": 0.7,
    }
    result = semantic_screen_candidate(
        config,
        PaperRecord(title="Agent sandbox systems", abstract="agent sandbox systems reading"),
    )
    assert 0 <= result.score <= 1
    assert result.decision == "DEEP_READ"
    assert "question_overlap" in result.rationale


def test_deep_reading_limit_and_reader_persistence(tmp_path: Path) -> None:
    project_path = write_project(tmp_path)
    db_path = tmp_path / "alberto.sqlite3"
    run_id = run_research_workflow(
        project_path=project_path,
        db_path=db_path,
        providers=[DeepReadProvider()],
    )
    conn = connect(db_path)
    apply_migrations(conn)
    run = conn.execute("SELECT read_count, screened_count FROM runs WHERE id=?", (run_id,)).fetchone()
    readings = conn.execute("SELECT structured_json FROM readings").fetchall()
    screening_rows = conn.execute("SELECT decision, rationale FROM screenings WHERE rationale LIKE 'Semantic screen%'").fetchall()
    assert run["read_count"] == 2
    assert run["screened_count"] == 3
    assert len(readings) == 2
    assert len(screening_rows) == 3
    assert "research-reader" in readings[0]["structured_json"]
    conn.close()


def test_digest_uses_persisted_readings(tmp_path: Path) -> None:
    project_path = write_project(tmp_path)
    db_path = tmp_path / "alberto.sqlite3"
    run_research_workflow(project_path=project_path, db_path=db_path, providers=[DeepReadProvider()])
    digest_id, digest_path = run_digest_workflow(project_path=project_path, db_path=db_path, output_dir=tmp_path / "digests")
    body = digest_path.read_text(encoding="utf-8")
    conn = connect(db_path)
    item = conn.execute("SELECT item_type FROM digest_items WHERE digest_id=?", (digest_id,)).fetchone()
    assert item["item_type"] == "reading"
    assert "agent sandbox systems reading" in body
    conn.close()


def test_provider_error_does_not_stop_valid_results(tmp_path: Path) -> None:
    project_path = write_project(tmp_path)
    db_path = tmp_path / "alberto.sqlite3"
    run_id = run_research_workflow(
        project_path=project_path,
        db_path=db_path,
        providers=[BrokenProvider(), DeepReadProvider()],
    )
    conn = connect(db_path)
    run = conn.execute("SELECT status, candidate_count, errors_json FROM runs WHERE id=?", (run_id,)).fetchone()
    assert run["status"] == "SUCCEEDED"
    assert run["candidate_count"] == 3
    assert "provider unavailable" in run["errors_json"]
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
