from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from alberto.db.connection import connect
from alberto.db.migrations import apply_migrations
from alberto.db.repositories import AlbertoRepository
from alberto.enums import LifecycleState
from alberto.research.config import load_project_config
from alberto.research.dedupe import dedupe_records
from alberto.research.digest import generate_digest, save_digest
from alberto.research.providers import CrossrefProvider, Provider, SemanticScholarProvider

LOG = logging.getLogger("alberto.research.workflow")


def default_providers() -> list[Provider]:
    return [CrossrefProvider(), SemanticScholarProvider()]


def build_queries(config: dict) -> list[str]:
    terms = list(config.get("inclusion_terms") or config.get("priority_topics") or [])
    if not terms:
        terms = [config["research_question"]]
    return [str(term) for term in terms]


def run_research_workflow(
    *,
    project_path: str | Path,
    db_path: str | Path | None = None,
    dry_run: bool = False,
    providers: Iterable[Provider] | None = None,
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
    errors: list[str] = []
    try:
        records = []
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
                    score = deterministic_screening_score(config, record.title, record.abstract)
                    decision = "QUEUE" if score >= float(config["screening_threshold"]) else "MAYBE"
                    repo.add_screening(config["id"], paper_id, score, decision, "Deterministic keyword pre-screen")
                    repo.set_paper_state(paper_id, LifecycleState.QUEUED if decision == "QUEUE" else LifecycleState.SCREENED)
        candidate_count = len(dedupe_records(records))
        repo.finish_run(
            run_id,
            "SUCCEEDED" if not errors else "FAILED",
            providers=provider_names,
            candidate_count=candidate_count,
            screened_count=candidate_count,
            errors=errors,
        )
        LOG.info("research workflow complete", extra={"run_id": run_id})
        return run_id
    except Exception as exc:
        repo.finish_run(run_id, "FAILED", providers=provider_names, candidate_count=candidate_count, errors=errors + [str(exc)])
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
