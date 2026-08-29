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
    portuguese_note = portuguese_executive_note(readings, papers)
    if portuguese_note:
        lines.extend(["", portuguese_note])
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
                "reading_id": int(reading["reading_id"]),
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


def portuguese_executive_note(readings: list[Any], papers: list[Any]) -> str:
    if readings:
        access_counts: dict[str, int] = {}
        titles: list[str] = []
        title_counts: dict[str, int] = {}
        priority_candidates: list[tuple[float, str]] = []
        references: list[str] = []
        evidence_texts: list[str] = []
        review_like_count = 0
        for reading in readings:
            structured = safe_structured_json(reading["structured_json"])
            title = clean_text(reading["title"])
            titles.append(title)
            title_counts[title] = title_counts.get(title, 0) + 1
            access = clean_text(structured.get("access_level") or reading["access_level"])
            access_counts[access] = access_counts.get(access, 0) + 1
            confidence = float(structured.get("confidence", reading["confidence"]) or 0)
            year = int(reading["publication_year"] or 0)
            repeated_penalty = 0.15 if title_counts[title] > 1 else 0
            priority_candidates.append((confidence + min(year, 2026) / 10000 - repeated_penalty, title))
            evidence_texts.extend(
                clean_text(value)
                for value in [
                    structured.get("central_argument"),
                    structured.get("relevance_to_project") or structured.get("relevance"),
                    *(structured.get("major_findings") or [])[:2],
                    *(structured.get("connections") or [])[:2],
                ]
                if clean_text(value)
            )
            references.extend(clean_text(ref) for ref in (structured.get("references_to_follow") or []) if clean_text(ref))
            review_signal = " ".join([title, *evidence_texts[-6:]]).lower()
            if "review" in review_signal or "resenha" in review_signal:
                review_like_count += 1

        access_phrase = portuguese_access_phrase(access_counts)
        themes = portuguese_theme_phrase(" ".join(evidence_texts).lower())
        priorities = unique_sorted_titles(priority_candidates, limit=3)
        priority_phrase = ", ".join(priorities) if priorities else "os itens de maior confiança"
        refs = unique_values(references, limit=3)
        reference_phrase = ", ".join(refs) if refs else "as referências indicadas pelos leitores"
        caveat = ""
        if review_like_count or any(count > 1 for count in title_counts.values()):
            caveat = (
                " Como vários achados vêm de resenhas ou de debates historiográficos repetidos, use-os como mapa de entrada "
                "e priorize consultar as obras de base que eles apontam."
            )
        return (
            f"Nota em português: li o conjunto deste digest como um todo: são {len(readings)} leituras analisadas, {access_phrase}. "
            f"O principal recado é que {themes}. Para aproveitar melhor o material, eu priorizaria primeiro {priority_phrase}; "
            f"depois, seguiria as pistas bibliográficas mais promissoras, especialmente {reference_phrase}.{caveat}"
        )
    if papers:
        titles = ", ".join(unique_values([clean_text(paper["title"]) for paper in papers], limit=3))
        return (
            f"Nota em português: este ciclo encontrou {len(papers)} candidato(s), mas ainda sem leitura sintetizada. "
            f"Vale começar por {titles or 'os candidatos com DOI e resumo mais completos'}, buscando texto completo antes de tirar conclusões fortes."
        )
    return ""


def safe_structured_json(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def portuguese_access_phrase(access_counts: dict[str, int]) -> str:
    labels = {
        "FULL_TEXT": "de texto completo",
        "PARTIAL_TEXT": "de texto parcial",
        "ABSTRACT_ONLY": "baseadas apenas em resumo",
        "METADATA_ONLY": "baseadas apenas em metadados",
    }
    parts = []
    for access, count in sorted(access_counts.items(), key=lambda item: item[0]):
        label = labels.get(access, access.lower())
        parts.append(f"{count} {label}")
    return "com " + ", ".join(parts) if parts else "com níveis de acesso variados"


def portuguese_theme_phrase(text: str) -> str:
    themes = []
    if any(term in text for term in ("architecture", "architectural", "stage", "cavea", "proskenion", "temple", "orchestra")):
        themes.append("a arquitetura e as condições materiais organizam a experiência teatral")
    if any(term in text for term in ("actor", "actors", "chorus", "mask", "performer", "performance", "dance", "music")):
        themes.append("atores, coro, música, corpo e visualidade precisam ser tratados como centrais, não acessórios")
    if any(term in text for term in ("festival", "religious", "ritual", "sanctuary", "divine", "god", "gods")):
        themes.append("o vínculo com festivais, ritual e religião continua sendo decisivo")
    if any(term in text for term in ("roman", "ovid", "pantomime", "mime", "pompey")):
        themes.append("a tradição romana amplia o projeto para sociabilidade, moralidade pública e espaços cívico-religiosos")
    if any(term in text for term in ("historiography", "scholarship", "evidence", "archaeological", "visual evidence", "inscriptions")):
        themes.append("as conclusões dependem de evidência fragmentária, visual, arqueológica e historiográfica")
    if not themes:
        return "o conjunto deve ser lido como um mapa inicial para separar achados fortes, lacunas e próximas leituras"
    if len(themes) == 1:
        return themes[0]
    return "; ".join(themes[:-1]) + "; e " + themes[-1]


def unique_sorted_titles(candidates: list[tuple[float, str]], limit: int) -> list[str]:
    seen = set()
    values = []
    for _, title in sorted(candidates, reverse=True):
        if title and title not in seen:
            seen.add(title)
            values.append(title)
        if len(values) >= limit:
            break
    return values


def unique_values(values: list[str], limit: int) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            unique.append(value)
        if len(unique) >= limit:
            break
    return unique


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
