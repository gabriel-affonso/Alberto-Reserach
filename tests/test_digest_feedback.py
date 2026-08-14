from __future__ import annotations

from alberto.db.repositories import AlbertoRepository
from alberto.enums import FeedbackType
from alberto.research.digest import generate_digest, stable_digest_item_id
from alberto.research.models import PaperRecord


def test_digest_items_are_stable(repo: AlbertoRepository) -> None:
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
    repo.upsert_project(config)
    paper_id = repo.upsert_paper(PaperRecord(title="Digest Paper", abstract="Important abstract", publication_year=2026))
    digest_id, body = generate_digest(repo, project_id="p1", project_name="Project", digest_date="2026-08-14")
    item_id = stable_digest_item_id("p1", paper_id, "paper", "2026-08-14")
    assert item_id in body
    feedback_id = repo.add_feedback("p1", FeedbackType.VERY_IMPORTANT, digest_item_id=item_id)
    assert digest_id > 0
    assert feedback_id > 0
