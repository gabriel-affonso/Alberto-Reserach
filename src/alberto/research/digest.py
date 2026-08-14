from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

from alberto.db.repositories import AlbertoRepository


def stable_digest_item_id(project_id: str, paper_id: int, item_type: str, digest_date: str) -> str:
    raw = f"{project_id}:{paper_id}:{item_type}:{digest_date}".encode("utf-8")
    return "di_" + hashlib.sha256(raw).hexdigest()[:16]


def generate_digest(
    repo: AlbertoRepository,
    *,
    project_id: str,
    project_name: str,
    run_id: str | None = None,
    digest_date: str | None = None,
    limit: int = 10,
) -> tuple[int, str]:
    digest_date = digest_date or date.today().isoformat()
    papers = repo.recent_reportable_papers(project_id, limit=limit)
    stats: dict[str, Any] = {"new_reported_papers": len(papers)}
    lines = [
        f"# {project_name} Research Digest - {digest_date}",
        "",
        "## Run Statistics",
        f"- New reportable papers: {len(papers)}",
        "",
        "## Top Findings",
    ]
    items: list[dict[str, Any]] = []
    if not papers:
        lines.append("- No new papers to report.")
    for paper in papers:
        item_id = stable_digest_item_id(project_id, int(paper["id"]), "paper", digest_date)
        title = paper["title"]
        body = paper["abstract"] or "Metadata-only discovery. Human review may be needed."
        stable_ref = item_id
        lines.append(f"- `{stable_ref}` {title}")
        items.append(
            {
                "id": item_id,
                "paper_id": int(paper["id"]),
                "item_type": "paper",
                "title": title,
                "body": body,
                "stable_ref": stable_ref,
            }
        )
    lines.extend(
        [
            "",
            "## What Changed In Our Understanding",
            "- Awaiting synthesized readings.",
            "",
            "## Important Connections",
            "- No persisted relationships were promoted into this digest yet.",
            "",
            "## Contradictions",
            "- No contradictions identified in deterministic digest generation.",
            "",
            "## Research Gaps",
            "- Review queued papers for gaps after reader analysis.",
            "",
            "## Rabbit Holes",
            "- Follow references from high-confidence readings.",
            "",
            "## Recommended Human Reading",
            "- Prioritize digest items marked by feedback as READ_PERSONALLY.",
            "",
            "## References Worth Pursuing",
            "- See reader `references_to_follow` fields as they accumulate.",
            "",
            "## Questions Requiring User Judgment",
            "- Which findings should become very important for future prioritization?",
        ]
    )
    body = "\n".join(lines)
    digest_id = repo.create_digest(
        project_id,
        run_id,
        digest_date,
        f"{project_name} Research Digest - {digest_date}",
        body,
        stats,
        items,
    )
    return digest_id, body


def save_digest(body: str, output_dir: str | Path, project_id: str, digest_id: int) -> Path:
    directory = Path(output_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{project_id}-digest-{digest_id}.md"
    path.write_text(body, encoding="utf-8")
    return path
