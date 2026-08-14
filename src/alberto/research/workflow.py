from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Iterable

from alberto.db.connection import connect
from alberto.db.migrations import apply_migrations
from alberto.db.repositories import AlbertoRepository
from alberto.enums import LifecycleState
from alberto.research.config import load_project_config
from alberto.research.dedupe import dedupe_records
from alberto.research.digest import generate_digest, save_digest
from alberto.research.models import PaperRecord
from alberto.research.providers import CrossrefProvider, Provider, SemanticScholarProvider
from alberto.research.reader import build_abstract_only_reading

LOG = logging.getLogger("alberto.research.workflow")


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


def run_research_workflow(
    *,
    project_path: str | Path,
    db_path: str | Path | None = None,
    dry_run: bool = False,
    providers: Iterable[Provider] | None = None,
    reader: Callable[[dict, PaperRecord], dict] | None = None,
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
    reader = reader or default_research_reader
    try:
        records = []
        processed_paper_ids: set[int] = set()
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
                        {"stage": "cheap_pre_screen", "provider": provider.name},
                    )

                    if pre_decision == "REJECT":
                        repo.set_paper_state(paper_id, LifecycleState.REJECTED)
                        screened_count += 1
                        continue

                    semantic = semantic_screen_candidate(config, record)
                    repo.add_screening(
                        config["id"],
                        paper_id,
                        semantic.score,
                        semantic.decision,
                        semantic.rationale,
                        {"stage": "semantic_screen", "agent": "alberto-research"},
                    )
                    screened_count += 1

                    if semantic.decision == "DEEP_READ" and read_count < deep_read_limit:
                        structured = reader(config, record)
                        repo.add_reading(config["id"], paper_id, structured)
                        read_count += 1
                        continue
                    if semantic.decision in {"DEEP_READ", "QUEUE"}:
                        repo.set_paper_state(paper_id, LifecycleState.QUEUED)
                    elif semantic.decision == "REJECT":
                        repo.set_paper_state(paper_id, LifecycleState.REJECTED)
                    else:
                        repo.set_paper_state(paper_id, LifecycleState.SCREENED)
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
    question_terms = _tokenize(config["research_question"])
    priority_terms = set().union(*(_tokenize(term) for term in config.get("priority_topics", []))) if config.get("priority_topics") else set()
    inclusion_terms = set().union(*(_tokenize(term) for term in config.get("inclusion_terms", []))) if config.get("inclusion_terms") else set()
    exclusion_terms = set().union(*(_tokenize(term) for term in config.get("exclusion_terms", []))) if config.get("exclusion_terms") else set()
    haystack_terms = _tokenize(f"{record.title} {record.abstract or ''}")

    question_overlap = _overlap_ratio(haystack_terms, question_terms)
    priority_overlap = _overlap_ratio(haystack_terms, priority_terms)
    inclusion_overlap = _overlap_ratio(haystack_terms, inclusion_terms)
    score = 0.15 + (question_overlap * 0.35) + (priority_overlap * 0.25) + (inclusion_overlap * 0.25)
    if record.abstract:
        score += 0.05
    if haystack_terms & exclusion_terms:
        score -= 0.4
    score = max(0.0, min(1.0, score))

    deep_threshold = float(config["deep_reading_threshold"])
    screen_threshold = float(config["screening_threshold"])
    if score >= deep_threshold:
        decision = "DEEP_READ"
    elif score >= screen_threshold:
        decision = "QUEUE"
    elif score >= 0.3:
        decision = "MAYBE"
    else:
        decision = "REJECT"
    rationale = (
        "Semantic screen from title/abstract metadata: "
        f"question_overlap={question_overlap:.2f}, priority_overlap={priority_overlap:.2f}, "
        f"inclusion_overlap={inclusion_overlap:.2f}."
    )
    return ScreeningResult(score=score, decision=decision, rationale=rationale)


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


def default_research_reader(config: dict, record: PaperRecord) -> dict:
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
    return build_abstract_only_reading(
        title=record.title,
        abstract=record.abstract,
        research_question=config["research_question"],
        bibliographic_information=bibliography,
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
