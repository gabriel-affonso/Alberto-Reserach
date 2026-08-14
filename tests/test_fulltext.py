from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from alberto.db.connection import connect
from alberto.db.migrations import apply_migrations
from alberto.db.repositories import AlbertoRepository
from alberto.enums import AccessLevel
from alberto.research.fulltext import (
    AbstractFallbackResolver,
    FullTextResolver,
    MetadataFallbackResolver,
    ProviderUrlResolver,
    ResolutionError,
    ResolvedDocument,
    UnpaywallResolver,
    ZoteroFullTextResolver,
    download_pdf_url,
    extract_pdf_text,
    validate_pdf_response,
)
from alberto.research.models import DiscoveryResult, PaperRecord
from alberto.research.providers.base import Provider
from alberto.research.workflow import (
    ScreeningResult,
    default_research_reader,
    run_research_workflow,
)


PDF_BYTES = b"%PDF-1.4\nfake pdf bytes"


class FakeZoteroAdapter:
    configured = True

    def __init__(self, *, fulltext: str | None = "--- PAGE 1 ---\nZotero extracted text"):
        self.fulltext = fulltext

    def find_item_by_doi(self, doi: str):
        return {"key": "ITEM1", "data": {"DOI": doi}}

    def pdf_attachments(self, item_key: str):
        return [{"key": "ATTACH1", "data": {"contentType": "application/pdf", "filename": "paper.pdf"}}]

    def attachment_fulltext(self, attachment_key: str):
        return self.fulltext

    def download_attachment_file(self, attachment_key: str):
        return PDF_BYTES, "application/pdf"


class UnconfiguredZoteroAdapter(FakeZoteroAdapter):
    configured = False


class FakePage:
    def __init__(self, text: str):
        self.text = text

    def extract_text(self) -> str:
        return self.text


class FakePdfReader:
    def __init__(self, path: str):
        self.pages = [FakePage("First page text with enough words"), FakePage("Second page text with enough words")]


def test_zotero_pdf_attachment_found(tmp_path: Path) -> None:
    resolver = ZoteroFullTextResolver(FakeZoteroAdapter())
    resolved = resolver.resolve(
        PaperRecord(title="Paper", doi="10.1/paper"),
        config={},
        storage_dir=tmp_path,
    )
    assert resolved is not None
    assert resolved.access_level == AccessLevel.FULL_TEXT
    assert resolved.source_type == "PDF"
    assert resolved.uri == "zotero://attachment/ATTACH1"
    assert "Zotero extracted text" in resolved.text


def test_zotero_unavailable_falls_back_to_abstract(tmp_path: Path, repo: AlbertoRepository) -> None:
    resolver = FullTextResolver(
        [
            ZoteroFullTextResolver(UnconfiguredZoteroAdapter()),
            AbstractFallbackResolver(),
            MetadataFallbackResolver(),
        ]
    )
    paper_id = repo.upsert_paper(PaperRecord(title="Paper", abstract="Abstract only", doi="10.1/paper"))
    persisted = resolver.resolve(repo, paper_id=paper_id, record=PaperRecord(title="Paper", abstract="Abstract only", doi="10.1/paper"), config={}, storage_dir=tmp_path)
    assert persisted.resolved.access_level == AccessLevel.ABSTRACT_ONLY
    assert persisted.resolved.text == "Abstract only"


def test_unpaywall_oa_location_found(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class Response:
        def __init__(self, *, payload=None, content=b"", content_type="application/pdf"):
            self._payload = payload
            self.content = content
            self.headers = {"Content-Type": content_type}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        calls.append(url)
        if "unpaywall" in url:
            return Response(
                payload={
                    "is_oa": True,
                    "best_oa_location": {"url_for_pdf": "https://example.test/paper.pdf", "license": "cc-by"},
                }
            )
        return Response(content=PDF_BYTES)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("alberto.research.fulltext.extract_pdf_text", lambda path: SimpleNamespace(text="--- PAGE 1 ---\nOA text with enough words", pages=1))
    resolved = UnpaywallResolver().resolve(
        PaperRecord(title="Paper", doi="10.1/paper"),
        config={"unpaywall_email": "research@example.test"},
        storage_dir=tmp_path,
    )
    assert resolved is not None
    assert resolved.access_level == AccessLevel.FULL_TEXT
    assert resolved.local_path is not None
    assert calls == ["https://api.unpaywall.org/v2/10.1/paper", "https://example.test/paper.pdf"]


def test_unpaywall_no_oa_version_available(monkeypatch, tmp_path: Path) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"is_oa": False, "best_oa_location": None}

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())
    assert (
        UnpaywallResolver().resolve(
            PaperRecord(title="Paper", doi="10.1/paper"),
            config={"unpaywall_email": "research@example.test"},
            storage_dir=tmp_path,
        )
        is None
    )


def test_invalid_non_pdf_response_rejected() -> None:
    with pytest.raises(ResolutionError):
        validate_pdf_response(b"<html>paywall</html>", "text/html")


def test_provider_url_invalid_non_pdf_rejected(monkeypatch, tmp_path: Path) -> None:
    class Response:
        content = b"<html>not pdf</html>"
        headers = {"Content-Type": "text/html"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())
    with pytest.raises(ResolutionError):
        download_pdf_url("https://example.test/paper.pdf", storage_dir=tmp_path, provenance={})


def test_duplicate_document_checksum(repo: AlbertoRepository) -> None:
    paper_id = repo.upsert_paper(PaperRecord(title="Paper"))
    first = repo.add_document(
        paper_id=paper_id,
        access_level=AccessLevel.ABSTRACT_ONLY,
        source_type="ABSTRACT",
        checksum_sha256="abc123",
    )
    second = repo.add_document(
        paper_id=paper_id,
        access_level=AccessLevel.ABSTRACT_ONLY,
        source_type="ABSTRACT",
        checksum_sha256="abc123",
    )
    assert first == second
    assert repo.conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"] == 1


def test_document_persistence(tmp_path: Path, repo: AlbertoRepository) -> None:
    resolver = FullTextResolver([AbstractFallbackResolver(), MetadataFallbackResolver()])
    record = PaperRecord(title="Paper", abstract="Abstract text")
    paper_id = repo.upsert_paper(record)
    persisted = resolver.resolve(repo, paper_id=paper_id, record=record, config={}, storage_dir=tmp_path)
    row = repo.conn.execute("SELECT access_level, source_type, checksum_sha256 FROM documents WHERE id=?", (persisted.document_id,)).fetchone()
    assert row["access_level"] == "ABSTRACT_ONLY"
    assert row["source_type"] == "ABSTRACT"
    assert row["checksum_sha256"]


def test_pdf_text_extraction_preserves_page_markers(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(PDF_BYTES)
    extracted = extract_pdf_text(pdf_path, reader_factory=FakePdfReader)
    assert extracted.pages == 2
    assert "--- PAGE 1 ---" in extracted.text
    assert "--- PAGE 2 ---" in extracted.text
    assert "Second page text" in extracted.text


def test_full_text_reader_invocation(monkeypatch) -> None:
    calls = []

    def fake_invoke(command, prompt, *, timeout_seconds):
        calls.append((command, prompt, timeout_seconds))
        return {
            "access_level": "FULL_TEXT",
            "bibliographic_information": {"title": "Paper"},
            "research_question": "Question?",
            "central_argument": "Argument from full text",
            "methodology": "Method",
            "sources": ["--- PAGE 1 ---"],
            "major_findings": ["Finding"],
            "concepts": ["concept"],
            "relevance_to_project": "Relevant",
            "connections": [],
            "disagreements": [],
            "references_to_follow": [],
            "human_reading_recommended": True,
            "confidence": 0.8,
        }

    monkeypatch.setattr("alberto.research.workflow.invoke_openclaw_json", fake_invoke)
    payload = default_research_reader(
        {"research_question": "Question?"},
        PaperRecord(title="Paper"),
        ResolvedDocument(
            access_level=AccessLevel.FULL_TEXT,
            source_type="PDF",
            text="--- PAGE 1 ---\nFull text with evidence",
            provenance={"resolver": "test"},
        ),
    )
    assert payload["access_level"] == "FULL_TEXT"
    assert calls[0][0] == ["openclaw", "agent", "--agent", "research-reader", "--timeout", "300"]
    assert "Set access_level exactly to FULL_TEXT" in calls[0][1]
    assert "--- PAGE 1 ---" in calls[0][1]


def test_fallback_abstract_only(tmp_path: Path, repo: AlbertoRepository) -> None:
    record = PaperRecord(title="Paper", abstract="Only abstract")
    paper_id = repo.upsert_paper(record)
    persisted = FullTextResolver([AbstractFallbackResolver(), MetadataFallbackResolver()]).resolve(
        repo, paper_id=paper_id, record=record, config={}, storage_dir=tmp_path
    )
    assert persisted.resolved.access_level == AccessLevel.ABSTRACT_ONLY


def test_fallback_metadata_only(tmp_path: Path, repo: AlbertoRepository) -> None:
    record = PaperRecord(title="Paper")
    paper_id = repo.upsert_paper(record)
    persisted = FullTextResolver([AbstractFallbackResolver(), MetadataFallbackResolver()]).resolve(
        repo, paper_id=paper_id, record=record, config={}, storage_dir=tmp_path
    )
    assert persisted.resolved.access_level == AccessLevel.METADATA_ONLY


class DeepReadProvider(Provider):
    name = "crossref"

    def search(self, query: str, *, limit: int, dry_run: bool = False):
        return DiscoveryResult(
            provider=self.name,
            query=query,
            records=(PaperRecord(title="Paper", abstract="agent sandbox full text candidate", doi="10.1/paper"),),
            dry_run=dry_run,
        )


class FailingResolver:
    name = "failing"

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path):
        raise RuntimeError("resolver unavailable")


def test_acquisition_failure_does_not_abort_run(tmp_path: Path) -> None:
    project = tmp_path / "project.yaml"
    project.write_text(
        """
id: fulltext-test
name: FullText Test
research_question: agent sandbox
priority_topics:
  - agent sandbox
languages:
  - en
inclusion_terms:
  - agent
  - sandbox
discovery_limits:
  crossref: 1
screening_threshold: 0.4
deep_reading_threshold: 0.7
maximum_daily_deep_reads: 1
citation_chasing:
  enabled: false
digest:
  enabled: true
timezone: Europe/Lisbon
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "alberto.sqlite3"

    def semantic(config: dict, record: PaperRecord) -> ScreeningResult:
        return ScreeningResult(score=0.9, decision="DEEP_READ", rationale="relevant")

    def reader(config: dict, record: PaperRecord, document: ResolvedDocument) -> dict:
        return {
            "access_level": document.access_level.value,
            "bibliographic_information": {"title": record.title},
            "research_question": config["research_question"],
            "central_argument": document.text,
            "methodology": "",
            "sources": [document.source_type],
            "major_findings": [document.text],
            "concepts": [],
            "relevance_to_project": "Relevant",
            "connections": [],
            "disagreements": [],
            "references_to_follow": [],
            "human_reading_recommended": False,
            "confidence": 0.5,
        }

    resolver = FullTextResolver([FailingResolver(), AbstractFallbackResolver(), MetadataFallbackResolver()])
    run_id = run_research_workflow(
        project_path=project,
        db_path=db_path,
        providers=[DeepReadProvider()],
        semantic_screener=semantic,
        reader=reader,
        full_text_resolver=resolver,
    )
    conn = connect(db_path)
    apply_migrations(conn)
    run = conn.execute("SELECT status, read_count FROM runs WHERE id=?", (run_id,)).fetchone()
    doc = conn.execute("SELECT access_level, provenance_json FROM documents").fetchone()
    assert run["status"] == "SUCCEEDED"
    assert run["read_count"] == 1
    assert doc["access_level"] == "ABSTRACT_ONLY"
    assert "resolver unavailable" in doc["provenance_json"]
    conn.close()
