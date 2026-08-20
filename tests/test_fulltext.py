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
    COREResolver,
    DOAJResolver,
    EuropePMCResolver,
    FullTextResolver,
    MetadataFallbackResolver,
    OpenAlexResolver,
    ProviderUrlResolver,
    ResolutionError,
    ResolvedDocument,
    UnpaywallResolver,
    ZoteroFullTextResolver,
    download_pdf_url,
    extract_pdf_text,
    ordered_resolvers,
    resolver_name,
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


def libgen_integration_module():
    return pytest.importorskip(
        "alberto.research.libgen_integration",
        reason="optional LibGen compatibility dependencies are not installed",
        exc_type=ModuleNotFoundError,
    )


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


def test_openalex_oa_location_found(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class Response:
        def __init__(self, *, payload=None, content=b"", content_type="application/pdf", status_code=200):
            self._payload = payload
            self.content = content
            self.headers = {"Content-Type": content_type}
            self.status_code = status_code

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        calls.append(url)
        if "api.openalex.org" in url:
            return Response(
                payload={
                    "id": "https://openalex.org/W1",
                    "open_access": {"is_oa": True},
                    "best_oa_location": {"pdf_url": "https://example.test/openalex.pdf"},
                }
            )
        return Response(content=PDF_BYTES)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("alberto.research.fulltext.extract_pdf_text", lambda path: SimpleNamespace(text="--- PAGE 1 ---\nOpenAlex text with enough words", pages=1))
    resolved = OpenAlexResolver().resolve(
        PaperRecord(title="Paper", doi="10.1371/journal.pone.0234567"),
        config={"fulltext": {"user_agent": "AlbertoResearch/0.1 test"}},
        storage_dir=tmp_path,
    )
    assert resolved is not None
    assert resolved.access_level == AccessLevel.FULL_TEXT
    assert resolved.provenance["resolver"] == "openalex"
    assert calls == [
        "https://api.openalex.org/works/doi:10.1371/journal.pone.0234567",
        "https://example.test/openalex.pdf",
    ]


def test_openalex_404_returns_none(monkeypatch, tmp_path: Path) -> None:
    class Response:
        status_code = 404

        def raise_for_status(self):
            raise AssertionError("404 should be handled without raising")

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())
    assert OpenAlexResolver().resolve(PaperRecord(title="Missing", doi="10.9999/xyz123"), config={}, storage_dir=tmp_path) is None


def test_core_download_url_found(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class Response:
        status_code = 200

        def __init__(self, *, payload=None, content=b""):
            self._payload = payload
            self.content = content
            self.headers = {"Content-Type": "application/pdf"}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if "search/works" in url:
            return Response(payload={"results": [{"id": "core-1", "downloadUrl": "https://example.test/core.pdf"}]})
        return Response(content=PDF_BYTES)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("alberto.research.fulltext.extract_pdf_text", lambda path: SimpleNamespace(text="--- PAGE 1 ---\nCORE text with enough words", pages=1))
    resolved = COREResolver().resolve(
        PaperRecord(title="Paper", doi="10.1/core"),
        config={"fulltext": {"core_api_key": "secret-key"}},
        storage_dir=tmp_path,
    )
    assert resolved is not None
    assert resolved.provenance["resolver"] == "core"
    assert calls[0][1]["params"]["q"] == 'doi:"10.1/core"'
    assert calls[0][1]["headers"]["Authorization"] == "Bearer secret-key"
    assert calls[1][0] == "https://example.test/core.pdf"


def test_doaj_pdf_link_found(monkeypatch, tmp_path: Path) -> None:
    class Response:
        status_code = 200

        def __init__(self, *, payload=None, content=b""):
            self._payload = payload
            self.content = content
            self.headers = {"Content-Type": "application/pdf"}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "doaj.org" in url:
            return Response(payload={"results": [{"id": "article-1", "bibjson": {"link": [{"type": "fulltext", "url": "https://example.test/doaj.pdf"}]}}]})
        return Response(content=PDF_BYTES)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("alberto.research.fulltext.extract_pdf_text", lambda path: SimpleNamespace(text="--- PAGE 1 ---\nDOAJ text with enough words", pages=1))
    resolved = DOAJResolver().resolve(PaperRecord(title="Paper", doi="10.1/doaj"), config={}, storage_dir=tmp_path)
    assert resolved is not None
    assert resolved.uri == "https://example.test/doaj.pdf"
    assert resolved.provenance["resolver"] == "doaj"


def test_europepmc_pdf_link_found(monkeypatch, tmp_path: Path) -> None:
    class Response:
        status_code = 200

        def __init__(self, *, payload=None, content=b""):
            self._payload = payload
            self.content = content
            self.headers = {"Content-Type": "application/pdf"}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if "europepmc/webservices" in url:
            return Response(
                payload={
                    "resultList": {
                        "result": [
                            {
                                "pmcid": "PMC1",
                                "fullTextUrlList": {
                                    "fullTextUrl": [
                                        {"documentStyle": "html", "availability": "Free", "url": "https://example.test/article"},
                                        {"documentStyle": "pdf", "url": "https://example.test/europepmc.pdf"},
                                    ]
                                },
                            }
                        ]
                    }
                }
            )
        return Response(content=PDF_BYTES)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("alberto.research.fulltext.extract_pdf_text", lambda path: SimpleNamespace(text="--- PAGE 1 ---\nEurope PMC text with enough words", pages=1))
    resolved = EuropePMCResolver().resolve(PaperRecord(title="Paper", doi="10.1/europepmc"), config={}, storage_dir=tmp_path)
    assert resolved is not None
    assert resolved.uri == "https://example.test/europepmc.pdf"
    assert resolved.provenance["pmcid"] == "PMC1"


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
    assert Path(calls[0][0][0]).name == "openclaw"
    assert calls[0][0][1:] == ["agent", "--agent", "research-reader", "--timeout", "300"]
    assert "Set access_level exactly to FULL_TEXT" in calls[0][1]
    assert "--- PAGE 1 ---" in calls[0][1]


def test_metadata_only_reader_output_is_normalized(monkeypatch) -> None:
    calls = []

    def fake_invoke(command, prompt, *, timeout_seconds):
        calls.append((command, prompt, timeout_seconds))
        return {
            "access_level": "FULL_TEXT",
            "bibliographic_information": {"title": "Wrong"},
            "research_question": "Wrong?",
            "central_argument": None,
            "methodology": None,
            "sources": None,
            "major_findings": None,
            "concepts": None,
            "relevance_to_project": None,
            "connections": None,
            "disagreements": None,
            "references_to_follow": None,
            "human_reading_recommended": None,
            "confidence": None,
            "page_provenance": None,
        }

    monkeypatch.setattr("alberto.research.workflow.invoke_openclaw_json", fake_invoke)
    payload = default_research_reader(
        {"research_question": "Question?"},
        PaperRecord(title="Metadata Paper", doi="10.1/metadata", publication_year=2026),
        ResolvedDocument(
            access_level=AccessLevel.METADATA_ONLY,
            source_type="METADATA",
            text="Title: Metadata Paper",
            provenance={"resolver": "metadata_fallback"},
        ),
    )

    assert payload["access_level"] == "METADATA_ONLY"
    assert payload["bibliographic_information"]["title"] == "Metadata Paper"
    assert payload["research_question"] == "Question?"
    assert payload["central_argument"] == ""
    assert payload["major_findings"] == []
    assert payload["confidence"] == 0.0
    assert "Use this exact JSON structure" in calls[0][1]
    assert "Do not use null for any field" in calls[0][1]


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


class StaticPdfResolver:
    name = "static_pdf"

    def __init__(self, path: Path):
        self.path = path
        self.calls = 0

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path):
        self.calls += 1
        return ResolvedDocument(
            access_level=AccessLevel.FULL_TEXT,
            source_type="PDF",
            text="--- PAGE 1 ---\nStatic resolver text",
            uri="https://example.test/static.pdf",
            local_path=self.path,
            checksum_sha256="checksum",
            pages=1,
            provenance={"resolver": self.name},
        )


def test_resolver_order_can_be_configured_from_fulltext_block() -> None:
    resolvers = [ProviderUrlResolver(), OpenAlexResolver(), UnpaywallResolver()]
    ordered = [resolver.name for resolver in FullTextResolver(resolvers).resolvers]
    assert ordered == ["provider_url", "openalex", "unpaywall"]
    configured = [
        resolver.name
        for resolver in ordered_resolvers(
            resolvers,
            {"fulltext": {"resolver_order": ["openalex", "unpaywall"]}},
        )
    ]
    assert configured == ["openalex", "unpaywall", "provider_url"]


def test_default_fulltext_resolvers_use_supported_sources() -> None:
    ordered = [resolver_name(resolver) for resolver in FullTextResolver().resolvers]
    assert ordered[:9] == [
        "zotero",
        "unpaywall",
        "openalex",
        "core",
        "doaj",
        "europepmc",
        "provider_url",
        "scihub_mcp",
        "scihub",
    ]
    assert ordered[-2:] == [
        "abstract",
        "metadata",
    ]
    for optional_name in ("tesble", "libgen", "scihub_http"):
        if optional_name in ordered:
            assert ordered.index(optional_name) < ordered.index("abstract")


def test_legacy_libgen_wrapper_uses_supported_resolvers(tmp_path: Path) -> None:
    module = libgen_integration_module()
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(PDF_BYTES)
    static_resolver = StaticPdfResolver(pdf_path)

    resolver = module.LibgenResolver(storage_dir=tmp_path, resolvers=[static_resolver])

    assert resolver.fetch_text("10.1/legacy") == "--- PAGE 1 ---\nStatic resolver text"
    assert resolver.fetch_pdf_bytes("10.1/legacy") == PDF_BYTES
    assert static_resolver.calls == 2


def test_legacy_libgen_wrapper_reports_oa_miss(tmp_path: Path) -> None:
    module = libgen_integration_module()
    resolver = module.LibgenResolver(storage_dir=tmp_path, resolvers=[])

    with pytest.raises(module.LibgenResolverError, match="fontes OA suportadas"):
        resolver.fetch_text("10.1/missing")


def test_fulltext_cache_reuses_downloaded_pdf(monkeypatch, tmp_path: Path, repo: AlbertoRepository) -> None:
    pdf_path = tmp_path / "cached.pdf"
    pdf_path.write_bytes(PDF_BYTES)
    static_resolver = StaticPdfResolver(pdf_path)
    monkeypatch.setattr("alberto.research.fulltext.extract_pdf_text", lambda path: SimpleNamespace(text="--- PAGE 1 ---\nCached PDF text with enough words", pages=1))
    config = {"fulltext": {"cache_dir": "cache"}}
    record = PaperRecord(title="Paper", doi="10.1/cached")
    paper_id = repo.upsert_paper(record)

    first = FullTextResolver([static_resolver, MetadataFallbackResolver()]).resolve(
        repo, paper_id=paper_id, record=record, config=config, storage_dir=tmp_path
    )
    second = FullTextResolver([FailingResolver(), MetadataFallbackResolver()]).resolve(
        repo, paper_id=paper_id, record=record, config=config, storage_dir=tmp_path
    )

    assert first.resolved.provenance["resolver"] == "static_pdf"
    assert static_resolver.calls == 1
    assert second.resolved.provenance["resolver"] == "fulltext_cache"
    assert second.resolved.local_path == pdf_path


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
