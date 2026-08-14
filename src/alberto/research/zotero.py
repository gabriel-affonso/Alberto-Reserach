from __future__ import annotations

import os
from typing import Any

from alberto.research.dedupe import normalize_doi


class ZoteroAdapter:
    """Official Zotero Web API adapter.

    SQLite remains operational state; Zotero is synchronized as the user's human
    research library when credentials are configured.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        library_type: str | None = None,
        library_id: str | None = None,
        base_url: str = "https://api.zotero.org",
    ):
        self.api_key = api_key or os.environ.get("ZOTERO_API_KEY")
        self.library_type = library_type or os.environ.get("ZOTERO_LIBRARY_TYPE", "user")
        self.library_id = library_id or os.environ.get("ZOTERO_LIBRARY_ID")
        self.base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.library_id)

    def _headers(self) -> dict[str, str]:
        if not self.configured:
            raise RuntimeError("Zotero credentials are not configured")
        return {"Zotero-API-Key": self.api_key or "", "Content-Type": "application/json"}

    def _library_url(self, suffix: str) -> str:
        return f"{self.base_url}/{self.library_type}s/{self.library_id}{suffix}"

    def search(self, query: str) -> list[dict[str, Any]]:
        return self._request("GET", "/items", params={"q": query, "format": "json"})

    def find_by_doi(self, doi: str) -> dict[str, Any] | None:
        normalized = normalize_doi(doi)
        for item in self.search(normalized or doi):
            data = item.get("data", {})
            if normalize_doi(data.get("DOI")) == normalized:
                return item
        return None

    def create_item(self, item: dict[str, Any]) -> Any:
        return self._request("POST", "/items", json=[item])

    def update_metadata(self, item_key: str, version: int, data: dict[str, Any]) -> Any:
        headers = self._headers() | {"If-Unmodified-Since-Version": str(version)}
        return self._request("PATCH", f"/items/{item_key}", json=data, headers=headers)

    def set_tags(self, item_key: str, version: int, tags: list[str]) -> Any:
        return self.update_metadata(item_key, version, {"tags": [{"tag": tag} for tag in tags]})

    def add_note(self, parent_key: str, note_html: str) -> Any:
        return self.create_item({"itemType": "note", "parentItem": parent_key, "note": note_html})

    def record_attachment_metadata(self, parent_key: str, title: str, url: str) -> Any:
        return self.create_item(
            {"itemType": "attachment", "parentItem": parent_key, "title": title, "url": url, "linkMode": "linked_url"}
        )

    def dedupe_key(self, item: dict[str, Any]) -> str:
        data = item.get("data", item)
        doi = normalize_doi(data.get("DOI"))
        if doi:
            return f"doi:{doi}"
        return f"title:{(data.get('title') or '').strip().lower()}"

    def _request(self, method: str, suffix: str, **kwargs):
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("requests is required for Zotero API calls") from exc
        headers = kwargs.pop("headers", self._headers())
        response = requests.request(method, self._library_url(suffix), headers=headers, timeout=30, **kwargs)
        response.raise_for_status()
        if response.content:
            return response.json()
        return None
