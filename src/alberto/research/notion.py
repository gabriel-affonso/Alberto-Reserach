from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from alberto.db.repositories import AlbertoRepository


LOG = logging.getLogger("alberto.research.notion")
NOTION_API_VERSION = "2026-03-11"
NOTION_BASE_URL = "https://api.notion.com/v1"
MAX_RICH_TEXT_LENGTH = 1_900


@dataclass(frozen=True)
class NotionDatabase:
    database_id: str
    data_source_id: str


@dataclass(frozen=True)
class NotionSyncReport:
    status: str
    created: int = 0
    updated: int = 0
    error: str | None = None


class NotionAdapter:
    """Official Notion API adapter for validated digest readings."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        data_source_id: str | None = None,
        database_id: str | None = None,
        base_url: str = NOTION_BASE_URL,
    ):
        self.api_key = api_key or os.environ.get("NOTION_API_KEY")
        self.data_source_id = data_source_id or os.environ.get("NOTION_DATA_SOURCE_ID")
        self.database_id = database_id or os.environ.get("NOTION_DATABASE_ID")
        self.base_url = base_url.rstrip("/")

    @classmethod
    def from_project_config(cls, config: dict[str, Any]) -> "NotionAdapter":
        settings = config.get("notion") or {}
        if not isinstance(settings, dict):
            settings = {}
        enabled_by_environment = os.environ.get("ALBERTO_NOTION_ENABLED") == "1"
        if settings.get("enabled") is not True and not enabled_by_environment:
            return cls(api_key="", data_source_id="", database_id="")
        return cls(
            data_source_id=settings.get("data_source_id"),
            database_id=settings.get("database_id"),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key and (self.data_source_id or self.database_id))

    def create_article_database(self, *, parent_page_id: str, title: str = "Alberto Research Library") -> NotionDatabase:
        if not self.api_key:
            raise RuntimeError("NOTION_API_KEY is not configured")
        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": text_blocks(title),
            "description": text_blocks("Artigos lidos pelo Alberto Research e incluídos em digests."),
            "initial_data_source": {"properties": article_database_properties()},
        }
        response = self._request("POST", "/databases", json=payload)
        database_id = str(response["id"])
        data_source_id = extract_data_source_id(response)
        if not data_source_id:
            data_source_id = extract_data_source_id(self._request("GET", f"/databases/{database_id}"))
        if not data_source_id:
            raise RuntimeError("Notion did not return the initial data source id")
        return NotionDatabase(database_id=database_id, data_source_id=data_source_id)

    def resolved_data_source_id(self) -> str:
        if self.data_source_id:
            return self.data_source_id
        if not self.database_id:
            raise RuntimeError("NOTION_DATA_SOURCE_ID or NOTION_DATABASE_ID is not configured")
        response = self._request("GET", f"/databases/{self.database_id}")
        data_source_id = extract_data_source_id(response)
        if not data_source_id:
            raise RuntimeError("Notion database has no accessible data source")
        return data_source_id

    def create_article_page(self, data_source_id: str, properties: dict[str, Any], children: list[dict[str, Any]]) -> str:
        response = self._request(
            "POST",
            "/pages",
            json={
                "parent": {"type": "data_source_id", "data_source_id": data_source_id},
                "properties": properties,
                "children": children,
            },
        )
        return str(response["id"])

    def update_article_page(self, page_id: str, properties: dict[str, Any]) -> None:
        self._request("PATCH", f"/pages/{page_id}", json={"properties": properties})

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("requests is required for Notion synchronization") from exc
        if not self.api_key:
            raise RuntimeError("NOTION_API_KEY is not configured")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        }
        try:
            response = requests.request(method, f"{self.base_url}{path}", headers=headers, timeout=30, **kwargs)
        except requests.RequestException as exc:
            raise RuntimeError("Notion API request could not be completed") from exc
        try:
            response.raise_for_status()
        except Exception as exc:
            detail = response.text[:500] if response.content else ""
            raise RuntimeError(f"Notion API request failed: {detail}") from exc
        return response.json() if response.content else {}


def sync_digest_readings_to_notion(
    repo: AlbertoRepository,
    *,
    config: dict[str, Any],
    digest_id: int,
    adapter: NotionAdapter | None = None,
) -> NotionSyncReport:
    adapter = adapter or NotionAdapter.from_project_config(config)
    if not adapter.configured:
        return NotionSyncReport(status="not_configured")
    rows = repo.digest_readings_for_notion(digest_id)
    if not rows:
        return NotionSyncReport(status="no_readings")
    try:
        data_source_id = adapter.resolved_data_source_id()
        created = updated = 0
        for row in rows:
            properties = notion_article_properties(row)
            existing_page_id = repo.notion_page_id(config["id"], int(row["paper_id"]))
            if existing_page_id:
                adapter.update_article_page(existing_page_id, properties)
                updated += 1
                page_id = existing_page_id
            else:
                page_id = adapter.create_article_page(data_source_id, properties, notion_article_children(row))
                created += 1
            repo.record_notion_article_sync(
                project_id=config["id"],
                paper_id=int(row["paper_id"]),
                notion_page_id=page_id,
                digest_item_id=str(row["digest_item_id"]),
            )
        return NotionSyncReport(status="synced", created=created, updated=updated)
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        LOG.warning("Notion synchronization failed for digest %s: %s", digest_id, exc)
        return NotionSyncReport(status="failed", error=str(exc))


def article_database_properties() -> dict[str, Any]:
    return {
        "Article": {"title": {}},
        "Project": {"rich_text": {}},
        "DOI": {"rich_text": {}},
        "Authors": {"rich_text": {}},
        "Venue": {"rich_text": {}},
        "Year": {"number": {"format": "number"}},
        "URL": {"url": {}},
        "Read access": {"select": {"options": []}},
        "Confidence": {"number": {"format": "number"}},
        "Digest date": {"date": {}},
        "Digest reference": {"rich_text": {}},
        "Central argument": {"rich_text": {}},
        "Relevance": {"rich_text": {}},
    }


def notion_article_properties(row: Any) -> dict[str, Any]:
    structured = structured_reading(row["structured_json"])
    return {
        "Article": {"title": text_blocks(row["title"])},
        "Project": {"rich_text": text_blocks(row["project_name"])},
        "DOI": {"rich_text": text_blocks(row["doi"])},
        "Authors": {"rich_text": text_blocks(row["authors"])},
        "Venue": {"rich_text": text_blocks(row["venue"])},
        "Year": {"number": row["publication_year"]},
        "URL": {"url": clean_text(row["url"]) or None},
        "Read access": {"select": {"name": clean_text(row["access_level"]) or "METADATA_ONLY"}},
        "Confidence": {"number": float(row["confidence"])},
        "Digest date": {"date": {"start": str(row["digest_date"])}},
        "Digest reference": {"rich_text": text_blocks(row["digest_item_id"])},
        "Central argument": {"rich_text": text_blocks(structured.get("central_argument"))},
        "Relevance": {"rich_text": text_blocks(structured.get("relevance_to_project") or structured.get("relevance"))},
    }


def notion_article_children(row: Any) -> list[dict[str, Any]]:
    structured = structured_reading(row["structured_json"])
    sections = [
        ("Major findings", list_value(structured.get("major_findings"))),
        ("Methodology", [structured.get("methodology")]),
        ("Connections", list_value(structured.get("connections"))),
        ("Disagreements", list_value(structured.get("disagreements"))),
        ("References to follow", list_value(structured.get("references_to_follow"))),
    ]
    blocks: list[dict[str, Any]] = []
    for heading, values in sections:
        values = [clean_text(value) for value in values if clean_text(value)]
        if not values:
            continue
        blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": text_blocks(heading)}})
        for value in values[:20]:
            blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": text_blocks(value)}})
    return blocks


def extract_data_source_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    data_sources = payload.get("data_sources")
    if isinstance(data_sources, list) and data_sources and isinstance(data_sources[0], dict) and data_sources[0].get("id"):
        return str(data_sources[0]["id"])
    initial = payload.get("initial_data_source")
    if isinstance(initial, dict) and initial.get("id"):
        return str(initial["id"])
    return None


def structured_reading(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", "").split()).strip()[:MAX_RICH_TEXT_LENGTH]


def text_blocks(value: Any) -> list[dict[str, Any]]:
    text = clean_text(value)
    return [] if not text else [{"type": "text", "text": {"content": text}}]
