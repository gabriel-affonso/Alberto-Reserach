from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from alberto.db.repositories import AlbertoRepository
from alberto.enums import AccessLevel
from alberto.research.dedupe import normalize_doi
from alberto.research.models import PaperRecord
from alberto.research.zotero import ZoteroAdapter


MAX_DOWNLOAD_BYTES = int(os.environ.get("ALBERTO_MAX_FULLTEXT_BYTES", str(50 * 1024 * 1024)))


class ResolutionError(RuntimeError):
    pass


class Resolver(Protocol):
    name: str

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> "ResolvedDocument | None":
        ...


@dataclass(frozen=True)
class ResolvedDocument:
    access_level: AccessLevel
    source_type: str
    text: str
    uri: str | None = None
    local_path: Path | None = None
    checksum_sha256: str | None = None
    pages: int | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersistedDocument:
    document_id: int
    resolved: ResolvedDocument


class FullTextResolver:
    def __init__(self, resolvers: list[Resolver] | None = None):
        self.resolvers = resolvers or [
            ZoteroFullTextResolver(),
            UnpaywallResolver(),
            ProviderUrlResolver(),
            AbstractFallbackResolver(),
            MetadataFallbackResolver(),
        ]

    def resolve(
        self,
        repo: AlbertoRepository,
        *,
        paper_id: int,
        record: PaperRecord,
        config: dict,
        storage_dir: str | Path | None = None,
    ) -> PersistedDocument:
        directory = Path(storage_dir).expanduser() if storage_dir else default_document_storage_dir()
        directory.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        resolved: ResolvedDocument | None = None
        for resolver in self.resolvers:
            try:
                resolved = resolver.resolve(record, config=config, storage_dir=directory)
            except Exception as exc:
                errors.append(f"{resolver.name}:{exc}")
                continue
            if resolved is not None:
                provenance = dict(resolved.provenance)
                if errors:
                    provenance["resolver_errors"] = errors
                resolved = ResolvedDocument(
                    access_level=resolved.access_level,
                    source_type=resolved.source_type,
                    text=resolved.text,
                    uri=resolved.uri,
                    local_path=resolved.local_path,
                    checksum_sha256=resolved.checksum_sha256,
                    pages=resolved.pages,
                    provenance=provenance,
                )
                break
        if resolved is None:
            resolved = MetadataFallbackResolver().resolve(record, config=config, storage_dir=directory)
        assert resolved is not None
        document_id = repo.add_document(
            paper_id=paper_id,
            access_level=resolved.access_level,
            source_type=resolved.source_type,
            uri=resolved.uri,
            local_path=str(resolved.local_path) if resolved.local_path else None,
            checksum_sha256=resolved.checksum_sha256,
            pages=resolved.pages,
            provenance=resolved.provenance,
        )
        return PersistedDocument(document_id=document_id, resolved=resolved)


class ZoteroFullTextResolver:
    name = "zotero"

    def __init__(self, adapter: ZoteroAdapter | None = None):
        self.adapter = adapter or ZoteroAdapter()

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        if not self.adapter.configured or not record.doi:
            return None
        item = self.adapter.find_item_by_doi(record.doi)
        if not item:
            return None
        item_key = item.get("key") or item.get("data", {}).get("key")
        if not item_key:
            return None
        for attachment in self.adapter.pdf_attachments(item_key):
            attachment_key = attachment.get("key") or attachment.get("data", {}).get("key")
            if not attachment_key:
                continue
            text = self.adapter.attachment_fulltext(attachment_key)
            if text:
                checksum = sha256_bytes(text.encode("utf-8"))
                return ResolvedDocument(
                    access_level=AccessLevel.FULL_TEXT,
                    source_type="PDF",
                    text=text,
                    uri=f"zotero://attachment/{attachment_key}",
                    checksum_sha256=checksum,
                    provenance={"resolver": self.name, "source": "zotero_fulltext", "attachment_key": attachment_key},
                )
            content, content_type = self.adapter.download_attachment_file(attachment_key)
            validate_pdf_response(content, content_type)
            path = store_pdf(content, storage_dir, source_id=f"zotero-{attachment_key}")
            extracted = extract_pdf_text(path)
            return ResolvedDocument(
                access_level=AccessLevel.FULL_TEXT,
                source_type="PDF",
                text=extracted.text,
                uri=f"zotero://attachment/{attachment_key}",
                local_path=path,
                checksum_sha256=sha256_bytes(content),
                pages=extracted.pages,
                provenance={"resolver": self.name, "source": "zotero_file", "attachment_key": attachment_key},
            )
        return None


class UnpaywallResolver:
    name = "unpaywall"

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        doi = normalize_doi(record.doi)
        email = config.get("unpaywall_email") or os.environ.get("UNPAYWALL_EMAIL")
        if not doi or not email:
            return None
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ResolutionError("requests is required for Unpaywall resolution") from exc
        response = requests.get(f"https://api.unpaywall.org/v2/{doi}", params={"email": email}, timeout=30)
        response.raise_for_status()
        payload = response.json()
        location = payload.get("best_oa_location") or {}
        url = location.get("url_for_pdf") or location.get("url")
        if not url or not payload.get("is_oa"):
            return None
        return download_pdf_url(
            url,
            storage_dir=storage_dir,
            provenance={"resolver": self.name, "license": location.get("license"), "host_type": location.get("host_type")},
        )


class ProviderUrlResolver:
    name = "provider_url"

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        url = record.url
        if not url or ".pdf" not in url.lower():
            return None
        return download_pdf_url(url, storage_dir=storage_dir, provenance={"resolver": self.name})


class AbstractFallbackResolver:
    name = "abstract"

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        if not record.abstract:
            return None
        text = record.abstract.strip()
        return ResolvedDocument(
            access_level=AccessLevel.ABSTRACT_ONLY,
            source_type="ABSTRACT",
            text=text,
            checksum_sha256=sha256_bytes(text.encode("utf-8")),
            provenance={"resolver": self.name},
        )


class MetadataFallbackResolver:
    name = "metadata"

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument:
        text = f"Title: {record.title}"
        return ResolvedDocument(
            access_level=AccessLevel.METADATA_ONLY,
            source_type="METADATA",
            text=text,
            checksum_sha256=sha256_bytes(text.encode("utf-8")),
            provenance={"resolver": self.name},
        )


@dataclass(frozen=True)
class ExtractedPdfText:
    text: str
    pages: int


def default_document_storage_dir() -> Path:
    home = Path(os.environ.get("ALBERTO_HOME", os.path.join(os.environ.get("XDG_STATE_HOME", "~/.local/state"), "alberto"))).expanduser()
    return home / "documents"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_pdf_response(content: bytes, content_type: str | None) -> None:
    if len(content) > MAX_DOWNLOAD_BYTES:
        raise ResolutionError("Downloaded PDF exceeds configured maximum size")
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized and normalized != "application/pdf":
        raise ResolutionError(f"Downloaded content is not a PDF: {content_type}")
    if not content.startswith(b"%PDF"):
        raise ResolutionError("Downloaded content does not look like a PDF")


def store_pdf(content: bytes, storage_dir: Path, *, source_id: str) -> Path:
    digest = sha256_bytes(content)
    directory = storage_dir / digest[:2]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{source_id}-{digest[:16]}.pdf"
    if not path.exists():
        path.write_bytes(content)
    return path


def download_pdf_url(url: str, *, storage_dir: Path, provenance: dict[str, Any]) -> ResolvedDocument:
    try:
        import requests
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ResolutionError("requests is required for PDF download") from exc
    response = requests.get(url, timeout=60, allow_redirects=True)
    response.raise_for_status()
    content = response.content
    validate_pdf_response(content, response.headers.get("Content-Type"))
    path = store_pdf(content, storage_dir, source_id="oa")
    extracted = extract_pdf_text(path)
    return ResolvedDocument(
        access_level=AccessLevel.FULL_TEXT,
        source_type="PDF",
        text=extracted.text,
        uri=url,
        local_path=path,
        checksum_sha256=sha256_bytes(content),
        pages=extracted.pages,
        provenance=provenance,
    )


def extract_pdf_text(path: str | Path, reader_factory=None) -> ExtractedPdfText:
    if reader_factory is None:
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError as exc:
            raise ResolutionError("pypdf is required for PDF text extraction") from exc
        reader_factory = PdfReader
    reader = reader_factory(str(path))
    page_texts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        page_texts.append(f"--- PAGE {index} ---\n{text.strip()}")
    combined = "\n\n".join(page_texts).strip()
    if len("".join(combined.split())) < 20:
        raise ResolutionError("PDF text extraction produced no usable text; OCR is not enabled")
    return ExtractedPdfText(text=combined, pages=len(page_texts))
