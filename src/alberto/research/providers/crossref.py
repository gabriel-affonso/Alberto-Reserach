from __future__ import annotations

from alberto.enums import AccessLevel
from alberto.research.models import DiscoveryResult, PaperRecord
from alberto.research.providers.base import Provider


class CrossrefProvider(Provider):
    name = "crossref"
    endpoint = "https://api.crossref.org/works"

    def search(self, query: str, *, limit: int, dry_run: bool = False) -> DiscoveryResult:
        if dry_run:
            return DiscoveryResult(
                provider=self.name,
                query=query,
                records=(),
                dry_run=True,
                provenance={"endpoint": self.endpoint, "limit": limit},
            )
        payload = self._request_json(
            "GET",
            self.endpoint,
            params={"query": query, "rows": limit, "select": "DOI,title,author,issued,container-title,URL,abstract"},
        )
        items = payload.get("message", {}).get("items", [])
        return DiscoveryResult(
            provider=self.name,
            query=query,
            records=tuple(normalize_crossref_item(item) for item in items),
            provenance={"endpoint": self.endpoint, "count": len(items)},
        )


def normalize_crossref_item(item: dict) -> PaperRecord:
    title = (item.get("title") or ["Untitled"])[0]
    authors = tuple(
        " ".join(part for part in (author.get("given"), author.get("family")) if part)
        for author in item.get("author", [])
    )
    date_parts = item.get("issued", {}).get("date-parts", [[]])[0]
    year = int(date_parts[0]) if date_parts else None
    venue = (item.get("container-title") or [None])[0]
    access = AccessLevel.ABSTRACT_ONLY if item.get("abstract") else AccessLevel.METADATA_ONLY
    return PaperRecord(
        title=title,
        doi=item.get("DOI"),
        abstract=item.get("abstract"),
        authors=authors,
        venue=venue,
        publication_year=year,
        publication_date="-".join(str(part) for part in date_parts) if date_parts else None,
        url=item.get("URL"),
        external_ids={"crossref_doi": item["DOI"]} if item.get("DOI") else {},
        access_level=access,
        provenance={"provider": "crossref"},
    )
