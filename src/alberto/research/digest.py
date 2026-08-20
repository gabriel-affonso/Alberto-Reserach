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
        "## Executive Summary",
        digest_summary_line(readings_count=len(readings), papers_count=len(papers)),
    ]
    items: list[dict[str, Any]] = []
    changed: list[str] = []
    connections: list[str] = []
    contradictions: list[str] = []
    gaps: list[str] = []
    human_reading: list[str] = []
    references: list[str] = []
    if not readings and not papers:
        lines.append("")
        lines.append("## Status")
        lines.append("- No new papers to report.")
    if readings:
        lines.extend(["", "## Synthesized Readings"])
    for reading in readings:
        paper_id = int(reading["paper_id"])
        item_id = stable_digest_item_id(project_id, paper_id, "reading", digest_date)
        structured = json.loads(reading["structured_json"])
        title = reading["title"]
        findings = structured.get("major_findings") or []
        body = reading_body(structured)
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
        lines.extend(format_reading_item(reading, structured, stable_ref))
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
    if papers:
        lines.extend(["", "## Newly Discovered Candidates"])
    for paper in papers:
        item_id = stable_digest_item_id(project_id, int(paper["id"]), "paper", digest_date)
        title = paper["title"]
        body = paper_candidate_body(paper)
        stable_ref = item_id
        lines.extend(format_paper_item(paper, stable_ref))
        gaps.append(f"Needs full-text acquisition or abstract-level reading: {title}")
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


def digest_summary_line(*, readings_count: int, papers_count: int) -> str:
    if readings_count:
        return f"- {readings_count} new synthesized reading(s) with extracted findings, relevance, and follow-up leads."
    if papers_count:
        return f"- {papers_count} newly discovered candidate paper(s) need reading; details below include DOI, venue and abstract when available."
    return "- No new reportable papers or readings were found in this cycle."


def format_reading_item(reading: Any, structured: dict[str, Any], stable_ref: str) -> list[str]:
    lines = [
        f"### {reading['title']}",
        f"- Ref: `{stable_ref}`",
        f"- Access: {structured.get('access_level') or reading['access_level']} | Confidence: {structured.get('confidence', reading['confidence'])}",
    ]
    metadata = compact_metadata(
        doi=reading["doi"],
        venue=reading["venue"],
        year=reading["publication_year"],
    )
    if metadata:
        lines.append(f"- Metadata: {metadata}")
    central = clean_text(structured.get("central_argument"))
    if central:
        lines.append(f"- Central argument: {central}")
    relevance = clean_text(structured.get("relevance_to_project") or structured.get("relevance"))
    if relevance:
        lines.append(f"- Relevance: {relevance}")
    findings = [clean_text(item) for item in structured.get("major_findings", []) if clean_text(item)]
    if findings:
        lines.append("- Key findings:")
        lines.extend(f"  - {finding}" for finding in findings[:3])
    refs = [clean_text(item) for item in structured.get("references_to_follow", []) if clean_text(item)]
    if refs:
        lines.append("- Follow up:")
        lines.extend(f"  - {ref}" for ref in refs[:3])
    return lines


def format_paper_item(paper: Any, stable_ref: str) -> list[str]:
    title = paper["title"]
    lines = [
        f"### {title}",
        f"- Ref: `{stable_ref}`",
    ]
    metadata = compact_metadata(
        doi=paper["doi"],
        venue=paper["venue"],
        year=paper["publication_year"],
    )
    if metadata:
        lines.append(f"- Metadata: {metadata}")
    abstract = clean_text(paper["abstract"])
    if abstract:
        lines.append(f"- Abstract signal: {truncate_words(abstract, 80)}")
    else:
        lines.append("- Abstract signal: No abstract available yet; this is a metadata-only candidate.")
    lines.append("- Next action: acquire full text or perform abstract-level reading in a future cycle.")
    return lines


def reading_body(structured: dict[str, Any]) -> str:
    findings = [clean_text(finding) for finding in structured.get("major_findings", []) if clean_text(finding)]
    if findings:
        return "\n".join(findings[:3])
    for key in ("central_argument", "relevance_to_project", "relevance"):
        value = clean_text(structured.get(key))
        if value:
            return value
    return "Structured reading persisted."


def paper_candidate_body(paper: Any) -> str:
    abstract = clean_text(paper["abstract"])
    if abstract:
        return truncate_words(abstract, 120)
    return "Metadata-only discovery. Human review may be needed."


def compact_metadata(*, doi: str | None, venue: str | None, year: int | None) -> str:
    parts = []
    if doi:
        parts.append(f"DOI {doi}")
    if year:
        parts.append(str(year))
    if venue:
        parts.append(str(venue))
    return " | ".join(parts)


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def truncate_words(value: str, limit: int) -> str:
    words = clean_text(value).split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(".,;:") + "..."


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
