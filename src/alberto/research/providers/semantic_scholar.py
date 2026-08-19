from __future__ import annotations

import os

from alberto.enums import AccessLevel
from alberto.research.models import DiscoveryResult, PaperRecord
from alberto.research.providers.base import Provider


class SemanticScholarProvider(Provider):
    name = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def search(self, query: str, *, limit: int, dry_run: bool = False) -> DiscoveryResult:
        if dry_run:
            return DiscoveryResult(
                provider=self.name,
                query=query,
                records=(),
                dry_run=True,
                provenance={"endpoint": self.endpoint, "limit": limit},
            )
        headers = {}
        if os.environ.get("SEMANTIC_SCHOLAR_API_KEY"):
            headers["x-api-key"] = os.environ["SEMANTIC_SCHOLAR_API_KEY"]
        payload = self._request_json(
            "GET",
            self.endpoint,
            params={
                "query": query,
                "limit": limit,
                "fields": "title,abstract,authors,venue,year,publicationDate,url,externalIds,publicationTypes",
            },
            headers=headers,
        )
        items = payload.get("data", [])
        return DiscoveryResult(
            provider=self.name,
            query=query,
            records=tuple(normalize_semantic_scholar_item(item) for item in items),
            provenance={"endpoint": self.endpoint, "count": len(items)},
        )


def normalize_semantic_scholar_item(item: dict) -> PaperRecord:
    external_ids = {str(k): str(v) for k, v in (item.get("externalIds") or {}).items() if v}
    doi = external_ids.get("DOI")
    publication_types = [str(value) for value in item.get("publicationTypes") or [] if value]
    access = AccessLevel.ABSTRACT_ONLY if item.get("abstract") else AccessLevel.METADATA_ONLY
    return PaperRecord(
        title=item.get("title") or "Untitled",
        doi=doi,
        abstract=item.get("abstract"),
        authors=tuple(author.get("name", "") for author in item.get("authors", []) if author.get("name")),
        venue=item.get("venue"),
        publication_year=item.get("year"),
        publication_date=item.get("publicationDate"),
        document_type=publication_types[0] if publication_types else None,
        url=item.get("url"),
        external_ids=external_ids,
        access_level=access,
        provenance={"provider": "semantic_scholar", "paperId": item.get("paperId"), "publication_types": publication_types},
    )
