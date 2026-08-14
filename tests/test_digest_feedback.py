from __future__ import annotations

from alberto.db.repositories import AlbertoRepository
from alberto.enums import FeedbackType
from alberto.research.digest import generate_digest, stable_digest_item_id
from alberto.research.models import PaperRecord


def _project_config(project_id: str) -> dict:
    return {
        "id": project_id,
        "name": f"Project {project_id}",
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


def _reading_payload(access_level: str) -> dict:
    return {
        "access_level": access_level,
        "confidence": 0.85,
        "central_argument": "Argument",
        "methodology": "Method",
        "major_findings": [],
        "concepts": [],
        "relevance": "Relevant",
        "connections": [],
        "disagreements": [],
        "references_to_follow": [],
    }


def _paper(repo: AlbertoRepository, title: str = "Digest Paper") -> int:
    return repo.upsert_paper(PaperRecord(title=title, abstract="Important abstract", publication_year=2026))


def _set_reading_created_at(repo: AlbertoRepository, reading_id: int, timestamp: str) -> None:
    with repo.conn:
        repo.conn.execute("UPDATE readings SET created_at=? WHERE id=?", (timestamp, reading_id))


def _digest_paper(repo: AlbertoRepository, project_id: str, paper_id: int, timestamp: str, suffix: str) -> None:
    item_id = f"{project_id}-{paper_id}-{suffix}"
    repo.create_digest(
        project_id,
        None,
        "2026-08-14",
        "Digest",
        "Digest body",
        {},
        [
            {
                "id": item_id,
                "paper_id": paper_id,
                "item_type": "reading",
                "title": "Paper",
                "body": "Digest item",
                "stable_ref": item_id,
            }
        ],
    )
    with repo.conn:
        repo.conn.execute("UPDATE digest_items SET created_at=? WHERE id=?", (timestamp, item_id))


def test_digest_items_are_stable(repo: AlbertoRepository) -> None:
    config = _project_config("p1")
    repo.upsert_project(config)
    paper_id = _paper(repo)
    digest_id, body = generate_digest(repo, project_id="p1", project_name="Project", digest_date="2026-08-14")
    item_id = stable_digest_item_id("p1", paper_id, "paper", "2026-08-14")
    assert item_id in body
    feedback_id = repo.add_feedback("p1", FeedbackType.VERY_IMPORTANT, digest_item_id=item_id)
    assert digest_id > 0
    assert feedback_id > 0


def test_newer_full_text_reading_after_metadata_digest_is_reportable(repo: AlbertoRepository) -> None:
    repo.upsert_project(_project_config("p1"))
    paper_id = _paper(repo)
    metadata_id = repo.add_reading("p1", paper_id, _reading_payload("METADATA_ONLY"))
    _set_reading_created_at(repo, metadata_id, "2026-08-14 08:00:00")
    _digest_paper(repo, "p1", paper_id, "2026-08-14 09:00:00", "metadata")

    full_text_id = repo.add_reading("p1", paper_id, _reading_payload("FULL_TEXT"))
    _set_reading_created_at(repo, full_text_id, "2026-08-14 10:00:00")

    rows = repo.recent_reportable_readings("p1")

    assert [row["paper_id"] for row in rows] == [paper_id]
    assert '"access_level": "FULL_TEXT"' in rows[0]["structured_json"]


def test_reading_represented_by_newer_digest_is_not_reportable(repo: AlbertoRepository) -> None:
    repo.upsert_project(_project_config("p1"))
    paper_id = _paper(repo)
    reading_id = repo.add_reading("p1", paper_id, _reading_payload("FULL_TEXT"))
    _set_reading_created_at(repo, reading_id, "2026-08-14 10:00:00")
    _digest_paper(repo, "p1", paper_id, "2026-08-14 11:00:00", "full-text")

    assert repo.recent_reportable_readings("p1") == []


def test_digest_in_another_project_does_not_suppress_reading(repo: AlbertoRepository) -> None:
    repo.upsert_project(_project_config("p1"))
    repo.upsert_project(_project_config("p2"))
    paper_id = _paper(repo)
    reading_id = repo.add_reading("p1", paper_id, _reading_payload("FULL_TEXT"))
    _set_reading_created_at(repo, reading_id, "2026-08-14 10:00:00")
    _digest_paper(repo, "p2", paper_id, "2026-08-14 11:00:00", "other-project")

    reading_rows = repo.recent_reportable_readings("p1")
    paper_rows = repo.recent_reportable_papers("p1")

    assert [row["paper_id"] for row in reading_rows] == [paper_id]
    assert [row["id"] for row in paper_rows] == [paper_id]


def test_digest_at_same_time_as_reading_prevents_duplicate_report(repo: AlbertoRepository) -> None:
    repo.upsert_project(_project_config("p1"))
    paper_id = _paper(repo)
    reading_id = repo.add_reading("p1", paper_id, _reading_payload("FULL_TEXT"))
    _set_reading_created_at(repo, reading_id, "2026-08-14 10:00:00")
    _digest_paper(repo, "p1", paper_id, "2026-08-14 10:00:00", "same-time")

    assert repo.recent_reportable_readings("p1") == []
