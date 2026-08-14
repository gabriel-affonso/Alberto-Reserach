from __future__ import annotations

import hashlib
import json
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
    readings = repo.recent_reportable_readings(project_id, limit=limit)
    papers = [] if readings else repo.recent_reportable_papers(project_id, limit=limit)
    stats: dict[str, Any] = {"new_reported_papers": len(readings) if readings else len(papers)}
    lines = [
        f"# {project_name} Research Digest - {digest_date}",
        "",
        "## Run Statistics",
        f"- New reportable papers: {stats['new_reported_papers']}",
        "",
        "## Top Findings",
    ]
    items: list[dict[str, Any]] = []
    changed: list[str] = []
    connections: list[str] = []
    contradictions: list[str] = []
    gaps: list[str] = []
    human_reading: list[str] = []
    references: list[str] = []
    if not readings and not papers:
        lines.append("- No new papers to report.")
    for reading in readings:
        paper_id = int(reading["paper_id"])
        item_id = stable_digest_item_id(project_id, paper_id, "reading", digest_date)
        structured = json.loads(reading["structured_json"])
        title = reading["title"]
        findings = structured.get("major_findings") or []
        body = "\n".join(str(finding) for finding in findings[:3]) or structured.get("relevance_to_project") or "Structured reading persisted."
        changed.extend(str(finding) for finding in findings[:2])
        connections.extend(str(item) for item in structured.get("connections", [])[:2])
        contradictions.extend(str(item) for item in structured.get("disagreements", [])[:2])
        references.extend(str(item) for item in structured.get("references_to_follow", [])[:3])
        if structured.get("human_reading_recommended"):
            human_reading.append(title)
        relevance = structured.get("relevance_to_project")
        if relevance and not findings:
            changed.append(str(relevance))
        if structured.get("confidence", 1) < 0.5:
            gaps.append(f"Low-confidence reading needs review: {title}")
        stable_ref = item_id
        lines.append(f"- `{stable_ref}` {title}")
        if body:
            lines.append(f"  {body}")
        items.append(
            {
                "id": item_id,
                "paper_id": paper_id,
                "item_type": "reading",
                "title": title,
                "body": body,
                "stable_ref": stable_ref,
            }
        )
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
            *_section_items(changed, "Awaiting synthesized readings."),
            "",
            "## Important Connections",
            *_section_items(connections, "No persisted relationships were promoted into this digest yet."),
            "",
            "## Contradictions",
            *_section_items(contradictions, "No contradictions identified in persisted readings."),
            "",
            "## Research Gaps",
            *_section_items(gaps, "Review queued papers for gaps after reader analysis."),
            "",
            "## Rabbit Holes",
            "- Follow references from high-confidence readings.",
            "",
            "## Recommended Human Reading",
            *_section_items(human_reading, "Prioritize digest items marked by feedback as READ_PERSONALLY."),
            "",
            "## References Worth Pursuing",
            *_section_items(references, "See reader `references_to_follow` fields as they accumulate."),
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


def _section_items(values: list[str], fallback: str) -> list[str]:
    if not values:
        return [f"- {fallback}"]
    return [f"- {value}" for value in values]
