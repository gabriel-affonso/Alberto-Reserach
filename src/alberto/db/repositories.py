from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from alberto.enums import AccessLevel, FeedbackType, LifecycleState, RelationshipType
from alberto.research.dedupe import normalize_doi, normalize_text
from alberto.research.models import PaperRecord


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AlbertoRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_project(self, config: dict[str, Any], config_path: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO projects(id, name, research_question, config_path, config_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  research_question=excluded.research_question,
                  config_path=excluded.config_path,
                  config_json=excluded.config_json,
                  updated_at=excluded.updated_at
                """,
                (
                    config["id"],
                    config["name"],
                    config["research_question"],
                    config_path,
                    dumps(config),
                    utc_now(),
                ),
            )

    def create_run(self, project_id: str | None, workflow: str) -> str:
        run_id = f"run_{uuid4().hex}"
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs(id, project_id, workflow, status) VALUES (?, ?, ?, 'RUNNING')",
                (run_id, project_id, workflow),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        providers: list[str] | None = None,
        candidate_count: int = 0,
        screened_count: int = 0,
        read_count: int = 0,
        digest_id: int | None = None,
        errors: list[str] | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE runs
                SET status=?, providers_queried_json=?, candidate_count=?, screened_count=?,
                    read_count=?, digest_id=?, errors_json=?, finished_at=?
                WHERE id=?
                """,
                (
                    status,
                    dumps(providers or []),
                    candidate_count,
                    screened_count,
                    read_count,
                    digest_id,
                    dumps(errors or []),
                    utc_now(),
                    run_id,
                ),
            )

    def create_search(self, project_id: str, provider: str, query: str, params: dict[str, Any], dry_run: bool) -> int:
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO searches(project_id, provider, query, parameters_json, dry_run)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, provider, query, dumps(params), int(dry_run)),
            )
            return int(cur.lastrowid)

    def finish_search(self, search_id: int, status: str, error: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE searches SET status=?, error=?, finished_at=? WHERE id=?",
                (status, error, utc_now(), search_id),
            )

    def upsert_paper(self, record: PaperRecord) -> int:
        normalized_doi = normalize_doi(record.doi)
        normalized_title = normalize_text(record.title)
        row = None
        if normalized_doi:
            row = self.conn.execute(
                "SELECT id FROM papers WHERE normalized_doi=?", (normalized_doi,)
            ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT id FROM papers WHERE normalized_title=? AND publication_year IS ?",
                (normalized_title, record.publication_year),
            ).fetchone()
        if row:
            paper_id = int(row["id"])
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE papers SET doi=COALESCE(?, doi), abstract=COALESCE(?, abstract),
                      venue=COALESCE(?, venue), publication_date=COALESCE(?, publication_date),
                      url=COALESCE(?, url), external_ids_json=?, access_level=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        record.doi,
                        record.abstract,
                        record.venue,
                        record.publication_date,
                        record.url,
                        dumps(record.external_ids),
                        record.access_level.value,
                        utc_now(),
                        paper_id,
                    ),
                )
        else:
            with self.conn:
                cur = self.conn.execute(
                    """
                    INSERT INTO papers(doi, normalized_doi, title, normalized_title, abstract, venue,
                      publication_year, publication_date, url, external_ids_json, access_level)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.doi,
                        normalized_doi,
                        record.title,
                        normalized_title,
                        record.abstract,
                        record.venue,
                        record.publication_year,
                        record.publication_date,
                        record.url,
                        dumps(record.external_ids),
                        record.access_level.value,
                    ),
                )
                paper_id = int(cur.lastrowid)
        self._replace_authors(paper_id, record.authors)
        return paper_id

    def _replace_authors(self, paper_id: int, authors: tuple[str, ...]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM paper_authors WHERE paper_id=?", (paper_id,))
            for index, name in enumerate(authors):
                normalized = normalize_text(name)
                cur = self.conn.execute(
                    """
                    INSERT INTO authors(name, normalized_name) VALUES (?, ?)
                    ON CONFLICT(normalized_name) DO UPDATE SET name=excluded.name
                    RETURNING id
                    """,
                    (name, normalized),
                )
                author_id = int(cur.fetchone()["id"])
                self.conn.execute(
                    "INSERT OR REPLACE INTO paper_authors(paper_id, author_id, author_order) VALUES (?, ?, ?)",
                    (paper_id, author_id, index),
                )

    def add_discovery(
        self,
        search_id: int,
        paper_id: int,
        provider: str,
        provider_record_id: str | None,
        rank: int | None,
        provenance: dict[str, Any],
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO discoveries(search_id, paper_id, provider, provider_record_id, rank, provenance_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (search_id, paper_id, provider, provider_record_id, rank, dumps(provenance)),
            )

    def set_paper_state(self, paper_id: int, state: LifecycleState) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE papers SET lifecycle_state=?, updated_at=? WHERE id=?",
                (state.value, utc_now(), paper_id),
            )

    def has_reading(self, project_id: str, paper_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM readings WHERE project_id=? AND paper_id=? LIMIT 1",
            (project_id, paper_id),
        ).fetchone()
        return row is not None

    def add_screening(
        self,
        project_id: str,
        paper_id: int,
        score: float,
        decision: str,
        rationale: str,
        model: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO screenings(project_id, paper_id, score, decision, rationale, model, provenance_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, paper_id, score, decision, rationale, model, dumps(provenance or {})),
            )
            return int(cur.lastrowid)

    def add_reading(
        self,
        project_id: str,
        paper_id: int,
        structured: dict[str, Any],
        *,
        document_id: int | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO readings(project_id, paper_id, document_id, access_level, structured_json, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    paper_id,
                    document_id,
                    structured["access_level"],
                    dumps(structured),
                    float(structured["confidence"]),
                ),
            )
            self.conn.execute(
                "UPDATE papers SET lifecycle_state='READ', updated_at=? WHERE id=?",
                (utc_now(), paper_id),
            )
            return int(cur.lastrowid)

    def add_document(
        self,
        *,
        paper_id: int,
        access_level: AccessLevel,
        source_type: str,
        uri: str | None = None,
        local_path: str | None = None,
        checksum_sha256: str | None = None,
        pages: int | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> int:
        if checksum_sha256:
            existing = self.conn.execute(
                "SELECT id FROM documents WHERE checksum_sha256=?",
                (checksum_sha256,),
            ).fetchone()
            if existing:
                return int(existing["id"])
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO documents(
                  paper_id, access_level, source_type, uri, local_path,
                  checksum_sha256, pages, provenance_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    access_level.value,
                    source_type,
                    uri,
                    local_path,
                    checksum_sha256,
                    pages,
                    dumps(provenance or {}),
                ),
            )
            return int(cur.lastrowid)

    def add_relationship(
        self,
        project_id: str,
        source_paper_id: int,
        relationship_type: RelationshipType,
        description: str,
        target_paper_id: int | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO relationships(project_id, source_paper_id, target_paper_id, relationship_type, description, provenance_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, source_paper_id, target_paper_id, relationship_type.value, description, dumps(provenance or {})),
            )
            return int(cur.lastrowid)

    def create_digest(
        self,
        project_id: str,
        run_id: str | None,
        digest_date: str,
        title: str,
        body: str,
        stats: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO digests(project_id, run_id, digest_date, title, body_markdown, stats_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, run_id, digest_date, title, body, dumps(stats)),
            )
            digest_id = int(cur.lastrowid)
            for item in items:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO digest_items(id, digest_id, paper_id, item_type, title, body, stable_ref)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["id"],
                        digest_id,
                        item.get("paper_id"),
                        item["item_type"],
                        item["title"],
                        item["body"],
                        item["stable_ref"],
                    ),
                )
            return digest_id

    def add_feedback(
        self,
        project_id: str,
        feedback_type: FeedbackType,
        *,
        digest_item_id: str | None = None,
        paper_id: int | None = None,
        note: str | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO feedback(project_id, digest_item_id, paper_id, feedback_type, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, digest_item_id, paper_id, feedback_type.value, note),
            )
            return int(cur.lastrowid)

    def paper_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS count FROM papers").fetchone()["count"])

    def recent_reportable_papers(self, project_id: str, limit: int = 10) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT p.*
            FROM papers p
            WHERE p.lifecycle_state IN ('DISCOVERED','SCREENED','QUEUED','READ')
              AND NOT EXISTS (
                SELECT 1
                FROM digest_items di
                JOIN digests d ON d.id = di.digest_id
                WHERE di.paper_id = p.id
                  AND d.project_id = ?
              )
            ORDER BY COALESCE(p.publication_year, 0) DESC, p.created_at DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()

    def recent_reportable_readings(self, project_id: str, limit: int = 10) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT
              p.id AS paper_id,
              p.title,
              p.abstract,
              p.publication_year,
              r.structured_json,
              r.confidence,
              r.created_at AS reading_created_at
            FROM readings r
            JOIN papers p ON p.id = r.paper_id
            WHERE r.project_id = ?
              AND NOT EXISTS (
                SELECT 1
                FROM digest_items di
                JOIN digests d ON d.id = di.digest_id
                WHERE di.paper_id = p.id
                  AND d.project_id = r.project_id
                  AND di.created_at >= r.created_at
              )
              AND r.id = (
                SELECT MAX(r2.id)
                FROM readings r2
                WHERE r2.project_id = r.project_id AND r2.paper_id = r.paper_id
              )
            ORDER BY r.confidence DESC, COALESCE(p.publication_year, 0) DESC, r.created_at DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
