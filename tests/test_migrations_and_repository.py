from __future__ import annotations

from alberto.db.migrations import apply_migrations
from alberto.db.repositories import AlbertoRepository
from alberto.enums import FeedbackType, LifecycleState, RelationshipType
from alberto.research.models import PaperRecord


def test_migrations_are_idempotent(migrated_conn) -> None:
    assert apply_migrations(migrated_conn) == []
    tables = {
        row["name"]
        for row in migrated_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"projects", "papers", "runs", "digests", "feedback"}.issubset(tables)


def test_repository_dedupes_and_tracks_state(repo: AlbertoRepository) -> None:
    config = {
        "id": "p1",
        "name": "Project",
        "research_question": "Question?",
        "priority_topics": [],
        "languages": ["en"],
        "discovery_limits": {},
        "screening_threshold": 0.5,
        "deep_reading_threshold": 0.8,
        "maximum_daily_deep_reads": 1,
        "citation_chasing": {},
        "digest": {},
        "timezone": "Europe/Lisbon",
    }
    repo.upsert_project(config, "project.yaml")
    left = repo.upsert_paper(PaperRecord(title="An Example", doi="https://doi.org/10.1/ABC", authors=("Ada Lovelace",), publication_year=2025))
    right = repo.upsert_paper(PaperRecord(title="An Example", doi="10.1/abc", authors=("Ada Lovelace",), publication_year=2025))
    assert left == right
    repo.set_paper_state(left, LifecycleState.QUEUED)
    repo.add_relationship("p1", left, RelationshipType.RESEARCH_GAP, "Needs stronger evidence")
    feedback_id = repo.add_feedback("p1", FeedbackType.USEFUL, paper_id=left)
    assert feedback_id > 0
