from __future__ import annotations

import json
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Iterable

from alberto.db.connection import connect
from alberto.db.migrations import apply_migrations
from alberto.db.repositories import AlbertoRepository
from alberto.enums import AccessLevel, LifecycleState
from alberto.research.config import load_project_config
from alberto.research.dedupe import dedupe_records
from alberto.research.digest import generate_digest, save_digest
from alberto.research.fulltext import FullTextResolver, PersistedDocument, ResolvedDocument
from alberto.research.models import PaperRecord
from alberto.research.openclaw import invoke_openclaw_json
from alberto.research.providers import CrossrefProvider, Provider, SemanticScholarProvider
from alberto.research.reader import READER_CONTRACT_PROMPT, build_reader_output_template, normalize_reader_output
from alberto.research.schemas import validate_reader_output

LOG = logging.getLogger("alberto.research.workflow")
SEMANTIC_SCREENING_MODEL = "openai/gpt-5.6-sol"


def default_providers() -> list[Provider]:
    return [CrossrefProvider(), SemanticScholarProvider()]


def build_queries(config: dict) -> list[str]:
    question = _clean_query_part(config["research_question"])
    priority_topics = [_clean_query_part(term) for term in config.get("priority_topics", [])]
    inclusion_terms = [_clean_query_part(term) for term in config.get("inclusion_terms", [])]
    priority_topics = [term for term in priority_topics if term]
    inclusion_terms = [term for term in inclusion_terms if term]

    queries = [
        _compose_query(question, priority_topics[:2], inclusion_terms[:2]),
    ]
    for topic in priority_topics[:3]:
        queries.append(_compose_query(question, [topic], inclusion_terms[:2]))
    if len(queries) < 4 and inclusion_terms:
        queries.append(_compose_query(question, priority_topics[:1], inclusion_terms[:3]))

    unique: list[str] = []
    for query in queries:
        if query and query not in unique:
            unique.append(query)
    return unique[:4]


def _clean_query_part(value: object) -> str:
    return " ".join(str(value).split())


def _compose_query(question: str, priority_topics: list[str], inclusion_terms: list[str]) -> str:
    parts = [question, *priority_topics, *inclusion_terms]
    return " ".join(part for part in parts if part)


@dataclass(frozen=True)
class ScreeningResult:
    score: float
    decision: str
    rationale: str


@dataclass(frozen=True)
class ScreenedCandidate:
    paper_id: int
    record: PaperRecord
    semantic: ScreeningResult


def run_research_workflow(
    *,
    project_path: str | Path,
    db_path: str | Path | None = None,
    dry_run: bool = False,
    providers: Iterable[Provider] | None = None,
    semantic_screener: Callable[[dict, PaperRecord], ScreeningResult] | None = None,
    reader: Callable[..., dict] | None = None,
    full_text_resolver: FullTextResolver | None = None,
) -> str:
    config = load_project_config(project_path)
    conn = connect(db_path)
    apply_migrations(conn)
    repo = AlbertoRepository(conn)
    repo.upsert_project(config, str(project_path))
    run_id = repo.create_run(config["id"], "daily_research")
    providers = list(providers or default_providers())
    provider_names: list[str] = []
    candidate_count = 0
    screened_count = 0
    read_count = 0
    errors: list[str] = []
    semantic_screener = semantic_screener or semantic_screen_candidate
    reader = reader or default_research_reader
    full_text_resolver = full_text_resolver or FullTextResolver()
    document_storage_dir = Path(db_path).expanduser().parent / "documents" if db_path else None
    try:
        records = []
        processed_paper_ids: set[int] = set()
        screened_candidates: list[ScreenedCandidate] = []
        deep_read_limit = int(config.get("maximum_daily_deep_reads", 0))
        for provider in providers:
            limit = int(config.get("discovery_limits", {}).get(provider.name, 10))
            if limit <= 0:
                continue
            provider_names.append(provider.name)
            for query in build_queries(config):
                search_id = repo.create_search(config["id"], provider.name, query, {"limit": limit}, dry_run)
                try:
                    result = provider.search(query, limit=limit, dry_run=dry_run)
                    repo.finish_search(search_id, "SUCCEEDED")
                except Exception as exc:
                    repo.finish_search(search_id, "FAILED", str(exc))
                    errors.append(f"{provider.name}:{exc}")
                    continue
                for rank, record in enumerate(result.records, start=1):
                    records.append(record)
                    paper_id = repo.upsert_paper(record)
                    repo.add_discovery(
                        search_id,
                        paper_id,
                        provider.name,
                        record.doi or record.external_ids.get("paperId"),
                        rank,
                        record.provenance | result.provenance,
                    )
                    if paper_id in processed_paper_ids:
                        continue
                    processed_paper_ids.add(paper_id)

                    pre_score = deterministic_screening_score(config, record.title, record.abstract)
                    pre_decision = "MAYBE" if pre_score >= 0.25 else "REJECT"
                    repo.add_screening(
                        config["id"],
                        paper_id,
                        pre_score,
                        pre_decision,
                        "Deterministic keyword pre-screen",
                        provenance={"stage": "cheap_pre_screen", "provider": provider.name},
                    )

                    if pre_decision == "REJECT":
                        repo.set_paper_state(paper_id, LifecycleState.REJECTED)
                        screened_count += 1
                        continue

                    try:
                        semantic = semantic_screener(config, record)
                    except Exception as exc:
                        errors.append(f"semantic_screen:{record.title}:{exc}")
                        repo.set_paper_state(paper_id, LifecycleState.SCREENED)
                        screened_count += 1
                        continue
                    repo.add_screening(
                        config["id"],
                        paper_id,
                        semantic.score,
                        semantic.decision,
                        semantic.rationale,
                        model=SEMANTIC_SCREENING_MODEL,
                        provenance={"stage": "semantic_screen", "model": SEMANTIC_SCREENING_MODEL},
                    )
                    screened_count += 1
                    screened_candidates.append(ScreenedCandidate(paper_id, record, semantic))
                    if semantic.decision == "REJECT":
                        repo.set_paper_state(paper_id, LifecycleState.REJECTED)
                    elif semantic.decision == "MAYBE":
                        repo.set_paper_state(paper_id, LifecycleState.SCREENED)
                    else:
                        repo.set_paper_state(paper_id, LifecycleState.QUEUED)

        eligible = [
            candidate
            for candidate in screened_candidates
            if candidate.semantic.decision == "DEEP_READ"
            and candidate.semantic.score >= float(config["deep_reading_threshold"])
        ]
        eligible.sort(key=lambda candidate: candidate.semantic.score, reverse=True)
        for candidate in eligible[:deep_read_limit]:
            try:
                persisted_document = full_text_resolver.resolve(
                    repo,
                    paper_id=candidate.paper_id,
                    record=candidate.record,
                    config=config,
                    storage_dir=document_storage_dir,
                )
                structured = invoke_reader(reader, config, candidate.record, persisted_document.resolved)
                repo.add_reading(
                    config["id"],
                    candidate.paper_id,
                    structured,
                    document_id=persisted_document.document_id,
                )
                read_count += 1
            except Exception as exc:
                errors.append(f"reader:{candidate.record.title}:{exc}")
                repo.set_paper_state(candidate.paper_id, LifecycleState.QUEUED)
                continue
        candidate_count = len(dedupe_records(records))
        repo.finish_run(
            run_id,
            "SUCCEEDED" if candidate_count > 0 or not errors else "FAILED",
            providers=provider_names,
            candidate_count=candidate_count,
            screened_count=screened_count,
            read_count=read_count,
            errors=errors,
        )
        LOG.info("research workflow complete", extra={"run_id": run_id})
        return run_id
    except Exception as exc:
        repo.finish_run(
            run_id,
            "FAILED",
            providers=provider_names,
            candidate_count=candidate_count,
            screened_count=screened_count,
            read_count=read_count,
            errors=errors + [str(exc)],
        )
        raise
    finally:
        conn.close()


def deterministic_screening_score(config: dict, title: str, abstract: str | None) -> float:
    haystack = f"{title} {abstract or ''}".lower()
    include = [str(term).lower() for term in config.get("inclusion_terms", [])]
    exclude = [str(term).lower() for term in config.get("exclusion_terms", [])]
    score = 0.25
    if include:
        score += sum(1 for term in include if term in haystack) / max(len(include), 1) * 0.6
    if any(term in haystack for term in exclude):
        score -= 0.5
    return max(0.0, min(1.0, score))


def semantic_screen_candidate(config: dict, record: PaperRecord) -> ScreeningResult:
    payload = invoke_openclaw_json(
        ["openclaw", "agent", "--agent", "alberto-research"],
        build_semantic_screening_prompt(config, record),
        timeout_seconds=120,
    )
    return validate_semantic_screening_output(payload)


def _tokenize(value: object) -> set[str]:
    tokens = []
    for raw in str(value).lower().replace("-", " ").split():
        token = "".join(char for char in raw if char.isalnum())
        if len(token) >= 3:
            tokens.append(token)
    return set(tokens)


def _overlap_ratio(haystack: set[str], needles: set[str]) -> float:
    if not needles:
        return 0.0
    return len(haystack & needles) / len(needles)


def invoke_reader(
    reader: Callable[..., dict],
    config: dict,
    record: PaperRecord,
    document: ResolvedDocument,
) -> dict:
    try:
        return reader(config, record, document)
    except TypeError:
        return reader(config, record)


def default_research_reader(config: dict, record: PaperRecord, document: ResolvedDocument | None = None) -> dict:
    bibliography = {
        "title": record.title,
        "doi": record.doi,
        "authors": list(record.authors),
        "venue": record.venue,
        "publication_year": record.publication_year,
        "publication_date": record.publication_date,
        "url": record.url,
        "external_ids": record.external_ids,
        "reader_agent": "research-reader",
    }
    document = document or ResolvedDocument(
        access_level=AccessLevel.ABSTRACT_ONLY if record.abstract else AccessLevel.METADATA_ONLY,
        source_type="ABSTRACT" if record.abstract else "METADATA",
        text=record.abstract or f"Title: {record.title}",
        provenance={"resolver": "legacy_reader_fallback"},
    )
    payload = invoke_openclaw_json(
        ["openclaw", "agent", "--agent", "research-reader", "--timeout", "300"],
        build_reader_prompt(config, record, bibliography, document),
        timeout_seconds=300,
    )
    payload = normalize_reader_output(
        payload,
        access_level=document.access_level,
        bibliographic_information=bibliography,
        research_question=config["research_question"],
    )
    validate_reader_output(payload)
    return payload


def validate_semantic_screening_output(payload: dict) -> ScreeningResult:
    try:
        score = float(payload["score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Semantic screening output must include numeric score") from exc
    decision = payload.get("decision")
    rationale = payload.get("rationale")
    if not 0 <= score <= 1:
        raise ValueError("Semantic screening score must be between 0 and 1")
    if decision not in {"REJECT", "MAYBE", "QUEUE", "DEEP_READ"}:
        raise ValueError("Semantic screening decision is invalid")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("Semantic screening rationale must be non-empty")
    return ScreeningResult(score=score, decision=decision, rationale=rationale.strip())


def build_semantic_screening_prompt(config: dict, record: PaperRecord) -> str:
    return "\n".join(
        [
            "Evaluate this academic paper for the Alberto Research project.",
            "Return ONLY JSON exactly like:",
            '{"score":0.0,"decision":"REJECT|MAYBE|QUEUE|DEEP_READ","rationale":"..."}',
            "",
            f"Research question: {config['research_question']}",
            f"Priority topics: {config.get('priority_topics', [])}",
            f"Priority authors: {config.get('priority_authors', [])}",
            "",
            f"Paper title: {record.title}",
            f"Abstract: {record.abstract or ''}",
            f"Authors: {list(record.authors)}",
            f"Venue: {record.venue or ''}",
            f"Year: {record.publication_year or ''}",
            "",
            "Score must be semantic relevance from 0 to 1, independent of lexical overlap.",
            "Use decision REJECT, MAYBE, QUEUE, or DEEP_READ.",
        ]
    )


def build_reader_prompt(config: dict, record: PaperRecord, bibliography: dict, document: ResolvedDocument) -> str:
    if document.access_level.value == "FULL_TEXT":
        document_instruction = (
            "The document text below is FULL_TEXT extracted from an accessible source. "
            "Distinguish claims supported by full text from inference. Never fabricate quotations or page numbers."
        )
    elif document.access_level.value == "ABSTRACT_ONLY":
        document_instruction = "Only abstract text is available. Do not represent this as full-paper reading."
    else:
        document_instruction = "Only metadata is available. Do not infer full-paper claims."
    template = build_reader_output_template(
        access_level=document.access_level,
        bibliographic_information=bibliography,
        research_question=config["research_question"],
    )
    return "\n".join(
        [
            READER_CONTRACT_PROMPT,
            "",
            "Return ONLY valid JSON matching Alberto's existing reader schema.",
            "Use this exact JSON structure and keep every field present:",
            json.dumps(template, indent=2, sort_keys=True),
            "",
            "Do not use null for any field. Use empty strings, empty arrays, false, or 0.0 when evidence is absent.",
            "Copy access_level, bibliographic_information, and research_question exactly from the template.",
            f"Set access_level exactly to {document.access_level.value}.",
            document_instruction,
            "For METADATA_ONLY, keep central_argument, methodology, sources, major_findings, concepts, "
            "connections, disagreements, and references_to_follow empty unless directly supported by metadata.",
            "For ABSTRACT_ONLY, use only the abstract and bibliographic metadata.",
            "For FULL_TEXT, use only the extracted document text and bibliographic metadata.",
            "",
            f"Research question: {config['research_question']}",
            f"Title: {record.title}",
            f"DOI: {record.doi or 'Not available'}",
            f"Authors: {list(record.authors)}",
            f"Venue: {record.venue or 'Not available'}",
            f"Publication year: {record.publication_year or 'Not available'}",
            f"Publication date: {record.publication_date or 'Not available'}",
            f"URL: {record.url or 'Not available'}",
            f"Bibliographic metadata: {json.dumps(bibliography, sort_keys=True)}",
            f"Document provenance: {json.dumps(document.provenance, sort_keys=True, default=str)}",
            "",
            "Document text:",
            document.text,
            "",
            "Return only the JSON object, with no markdown fence and no explanatory text.",
        ]
    )


def run_digest_workflow(
    *,
    project_path: str | Path,
    db_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    run_id: str | None = None,
) -> tuple[int, Path]:
    config = load_project_config(project_path)
    conn = connect(db_path)
    apply_migrations(conn)
    repo = AlbertoRepository(conn)
    repo.upsert_project(config, str(project_path))
    digest_id, body = generate_digest(
        repo,
        project_id=config["id"],
        project_name=config["name"],
        run_id=run_id,
        limit=int(config.get("digest", {}).get("max_items", 10)),
    )
    path = save_digest(body, output_dir or Path("data/digests"), config["id"], digest_id)
    conn.close()
    return digest_id, path
