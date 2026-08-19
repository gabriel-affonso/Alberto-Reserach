from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from alberto.enums import AccessLevel


@dataclass(frozen=True)
class PaperRecord:
    title: str
    doi: str | None = None
    abstract: str | None = None
    authors: tuple[str, ...] = ()
    venue: str | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    document_type: str | None = None
    url: str | None = None
    external_ids: dict[str, str] = field(default_factory=dict)
    access_level: AccessLevel = AccessLevel.METADATA_ONLY
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryResult:
    provider: str
    query: str
    records: tuple[PaperRecord, ...]
    dry_run: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)
