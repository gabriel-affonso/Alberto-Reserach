from __future__ import annotations

import hashlib
import json
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
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = "AlbertoResearch/0.1"


class ResolutionError(RuntimeError):
    pass


class Resolver(Protocol):
    name: str

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> "ResolvedDocument | None":
        ...


class BaseResolver:
    name = "base"
    priority = 100

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> "ResolvedDocument | None":
        raise NotImplementedError


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
            OpenAlexResolver(),
            COREResolver(),
            DOAJResolver(),
            EuropePMCResolver(),
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
        cached = read_fulltext_cache(record, config=config, storage_dir=directory)
        if cached is not None:
            document_id = repo.add_document(
                paper_id=paper_id,
                access_level=cached.access_level,
                source_type=cached.source_type,
                uri=cached.uri,
                local_path=str(cached.local_path) if cached.local_path else None,
                checksum_sha256=cached.checksum_sha256,
                pages=cached.pages,
                provenance=cached.provenance,
            )
            return PersistedDocument(document_id=document_id, resolved=cached)
        errors: list[str] = []
        resolved: ResolvedDocument | None = None
        for resolver in ordered_resolvers(self.resolvers, config):
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
                write_fulltext_cache(record, resolved, config=config, storage_dir=directory)
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


class ZoteroFullTextResolver(BaseResolver):
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


class UnpaywallResolver(BaseResolver):
    name = "unpaywall"

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        config = fulltext_config(config)
        doi = normalize_doi(record.doi)
        email = config.get("unpaywall_email") or os.environ.get("UNPAYWALL_EMAIL")
        if not doi or not email:
            return None
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ResolutionError("requests is required for Unpaywall resolution") from exc
        response = requests.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": email},
            headers=request_headers(config),
            timeout=request_timeout(config),
        )
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
            config=config,
        )


class OpenAlexResolver(BaseResolver):
    name = "openalex"
    priority = 10

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        config = fulltext_config(config)
        doi = normalize_doi(record.doi)
        if not doi:
            return None
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ResolutionError("requests is required for OpenAlex resolution") from exc
        response = requests.get(
            f"https://api.openalex.org/works/doi:{doi}",
            headers=request_headers(config),
            timeout=request_timeout(config),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not (payload.get("open_access") or {}).get("is_oa"):
            return None
        pdf_url = pdf_url_from_openalex(payload)
        if not pdf_url:
            return None
        return download_pdf_url(
            pdf_url,
            storage_dir=storage_dir,
            provenance={"resolver": self.name, "source": "openalex", "openalex_id": payload.get("id")},
            config=config,
        )


class COREResolver(BaseResolver):
    name = "core"
    priority = 30

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        config = fulltext_config(config)
        api_key = config.get("core_api_key") or os.environ.get("CORE_API_KEY")
        doi = normalize_doi(record.doi)
        if not api_key or not (doi or record.title):
            return None
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ResolutionError("requests is required for CORE resolution") from exc
        query = f'doi:"{doi}"' if doi else f'title:"{record.title}"'
        response = requests.get(
            "https://api.core.ac.uk/v3/search/works",
            params={"q": query, "limit": 1},
            headers={**request_headers(config), "Authorization": f"Bearer {api_key}"},
            timeout=request_timeout(config),
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        for result in results:
            for url in candidate_pdf_urls(result):
                return download_pdf_url(
                    url,
                    storage_dir=storage_dir,
                    provenance={"resolver": self.name, "source": "core", "core_id": result.get("id")},
                    config=config,
                )
            core_id = result.get("id")
            if core_id:
                return download_pdf_url(
                    f"https://api.core.ac.uk/v3/outputs/{core_id}/download",
                    storage_dir=storage_dir,
                    provenance={"resolver": self.name, "source": "core_download", "core_id": core_id},
                    config=config,
                )
        return None


class DOAJResolver(BaseResolver):
    name = "doaj"
    priority = 40

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        config = fulltext_config(config)
        doi = normalize_doi(record.doi)
        if not doi:
            return None
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ResolutionError("requests is required for DOAJ resolution") from exc
        response = requests.get(
            f"https://doaj.org/api/search/articles/doi:{doi}",
            headers=request_headers(config),
            timeout=request_timeout(config),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        results = response.json().get("results") or []
        for result in results:
            bibjson = result.get("bibjson") or {}
            for url in candidate_pdf_urls(bibjson):
                return download_pdf_url(
                    url,
                    storage_dir=storage_dir,
                    provenance={"resolver": self.name, "source": "doaj", "doaj_id": result.get("id")},
                    config=config,
                )
        return None


class EuropePMCResolver(BaseResolver):
    name = "europepmc"
    priority = 50

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        config = fulltext_config(config)
        doi = normalize_doi(record.doi)
        if not doi:
            return None
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ResolutionError("requests is required for Europe PMC resolution") from exc
        response = requests.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": f'DOI:"{doi}"', "format": "json", "pageSize": 1},
            headers=request_headers(config),
            timeout=request_timeout(config),
        )
        response.raise_for_status()
        results = (response.json().get("resultList") or {}).get("result") or []
        for result in results:
            urls = ((result.get("fullTextUrlList") or {}).get("fullTextUrl")) or []
            for url in europepmc_pdf_urls(urls):
                return download_pdf_url(
                    url,
                    storage_dir=storage_dir,
                    provenance={"resolver": self.name, "source": "europepmc", "pmcid": result.get("pmcid")},
                    config=config,
                )
        return None


class ProviderUrlResolver(BaseResolver):
    name = "provider_url"

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        url = record.url
        if not url or ".pdf" not in url.lower():
            return None
        return download_pdf_url(url, storage_dir=storage_dir, provenance={"resolver": self.name}, config=config)


class AbstractFallbackResolver(BaseResolver):
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


class MetadataFallbackResolver(BaseResolver):
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


def fulltext_config(config: dict) -> dict:
    nested = config.get("fulltext")
    if isinstance(nested, dict):
        return {**config, **nested}
    return config


def ordered_resolvers(resolvers: list[Resolver], config: dict) -> list[Resolver]:
    settings = fulltext_config(config)
    configured_order = settings.get("resolver_order") or []
    if not isinstance(configured_order, list):
        return resolvers
    by_name = {resolver.name: resolver for resolver in resolvers}
    ordered = [by_name[name] for name in configured_order if isinstance(name, str) and name in by_name]
    ordered_names = {resolver.name for resolver in ordered}
    ordered.extend(resolver for resolver in resolvers if resolver.name not in ordered_names)
    return ordered


def request_timeout(config: dict) -> int | float:
    settings = fulltext_config(config)
    value = settings.get("download_timeout", DEFAULT_DOWNLOAD_TIMEOUT_SECONDS)
    try:
        return float(value)
    except (TypeError, ValueError):
        return DEFAULT_DOWNLOAD_TIMEOUT_SECONDS


def request_headers(config: dict) -> dict[str, str]:
    settings = fulltext_config(config)
    user_agent = settings.get("user_agent") or os.environ.get("ALBERTO_USER_AGENT")
    if not user_agent:
        email = settings.get("unpaywall_email") or os.environ.get("UNPAYWALL_EMAIL")
        user_agent = f"{DEFAULT_USER_AGENT} (mailto:{email})" if email else DEFAULT_USER_AGENT
    return {"User-Agent": str(user_agent)}


def pdf_url_from_openalex(payload: dict[str, Any]) -> str | None:
    best = payload.get("best_oa_location") or {}
    if best.get("pdf_url"):
        return best["pdf_url"]
    primary = payload.get("primary_location") or {}
    if primary.get("pdf_url"):
        return primary["pdf_url"]
    for location in payload.get("locations") or []:
        if location.get("pdf_url"):
            return location["pdf_url"]
    return None


def candidate_pdf_urls(payload: Any) -> list[str]:
    urls: list[str] = []
    if not isinstance(payload, dict):
        return urls
    for key in ("downloadUrl", "download_url", "url_for_pdf", "pdf_url"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            urls.append(value)
    for link in payload.get("link") or payload.get("links") or []:
        if not isinstance(link, dict):
            continue
        url = link.get("url") or link.get("href")
        if not isinstance(url, str) or not url:
            continue
        link_type = " ".join(
            str(link.get(field, "")).lower()
            for field in ("type", "content_type", "contentType", "mime_type", "mimeType")
        )
        if "pdf" in link_type or url.lower().split("?")[0].endswith(".pdf"):
            urls.append(url)
    return dedupe_preserve_order(urls)


def europepmc_pdf_urls(entries: list[dict[str, Any]]) -> list[str]:
    pdf_urls: list[str] = []
    fallback_urls: list[str] = []
    for entry in entries:
        url = entry.get("url") if isinstance(entry, dict) else None
        if not isinstance(url, str) or not url:
            continue
        style = str(entry.get("documentStyle", "")).lower()
        availability = str(entry.get("availability", "")).lower()
        if style == "pdf" or url.lower().split("?")[0].endswith(".pdf"):
            pdf_urls.append(url)
        elif "free" in availability:
            fallback_urls.append(url)
    return dedupe_preserve_order(pdf_urls + fallback_urls)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def fulltext_cache_dir(config: dict, storage_dir: Path) -> Path | None:
    settings = fulltext_config(config)
    if settings.get("cache_enabled") is False:
        return None
    raw = settings.get("cache_dir", ".cache/fulltext")
    directory = Path(str(raw)).expanduser()
    if not directory.is_absolute():
        directory = storage_dir / directory
    return directory


def fulltext_cache_path(record: PaperRecord, *, config: dict, storage_dir: Path) -> Path | None:
    doi = normalize_doi(record.doi)
    directory = fulltext_cache_dir(config, storage_dir)
    if not doi or directory is None:
        return None
    digest = sha256_bytes(doi.encode("utf-8"))
    return directory / f"{digest}.json"


def read_fulltext_cache(record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
    cache_path = fulltext_cache_path(record, config=config, storage_dir=storage_dir)
    if cache_path is None or not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        local_path = Path(payload["local_path"]).expanduser()
        if not local_path.exists():
            return None
        extracted = extract_pdf_text(local_path)
    except (OSError, KeyError, TypeError, ValueError, ResolutionError, json.JSONDecodeError):
        return None
    return ResolvedDocument(
        access_level=AccessLevel.FULL_TEXT,
        source_type="PDF",
        text=extracted.text,
        uri=payload.get("uri"),
        local_path=local_path,
        checksum_sha256=payload.get("checksum_sha256"),
        pages=extracted.pages,
        provenance={
            "resolver": "fulltext_cache",
            "cached_resolver": payload.get("resolver"),
            "cache_path": str(cache_path),
        },
    )


def write_fulltext_cache(record: PaperRecord, resolved: ResolvedDocument, *, config: dict, storage_dir: Path) -> None:
    if resolved.local_path is None or resolved.access_level != AccessLevel.FULL_TEXT:
        return
    cache_path = fulltext_cache_path(record, config=config, storage_dir=storage_dir)
    if cache_path is None:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "doi": normalize_doi(record.doi),
        "resolver": resolved.provenance.get("resolver"),
        "uri": resolved.uri,
        "local_path": str(resolved.local_path),
        "checksum_sha256": resolved.checksum_sha256,
    }
    cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def validate_pdf_response(content: bytes, content_type: str | None) -> None:
    if len(content) > MAX_DOWNLOAD_BYTES:
        raise ResolutionError("Downloaded PDF exceeds configured maximum size")
    normalized = (content_type or "").split(";")[0].strip().lower()
    allowed_content_types = {"application/pdf", "application/octet-stream", "binary/octet-stream"}
    if normalized and normalized not in allowed_content_types:
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


def download_pdf_url(url: str, *, storage_dir: Path, provenance: dict[str, Any], config: dict | None = None) -> ResolvedDocument:
    try:
        import requests
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ResolutionError("requests is required for PDF download") from exc
    settings = fulltext_config(config or {})
    response = requests.get(
        url,
        headers=request_headers(settings),
        timeout=request_timeout(settings),
        allow_redirects=True,
    )
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
