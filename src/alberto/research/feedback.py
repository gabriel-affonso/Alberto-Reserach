from __future__ import annotations

from alberto.db.repositories import AlbertoRepository
from alberto.enums import FeedbackType


def store_feedback(
    repo: AlbertoRepository,
    *,
    project_id: str,
    feedback_type: str,
    digest_item_id: str | None = None,
    paper_id: int | None = None,
    note: str | None = None,
) -> int:
    return repo.add_feedback(
        project_id,
        FeedbackType(feedback_type),
        digest_item_id=digest_item_id,
        paper_id=paper_id,
        note=note,
    )
