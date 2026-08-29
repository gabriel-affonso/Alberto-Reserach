from __future__ import annotations

from alberto.db.repositories import AlbertoRepository
from alberto.research.digest import generate_digest
from alberto.research.models import PaperRecord
from alberto.research.notion import (
    NotionAdapter,
    article_database_properties,
    backfill_digest_readings_to_notion,
    notion_article_children,
    sync_digest_readings_to_notion,
)


def project_config() -> dict:
    return {
        "id": "notion-project",
        "name": "Notion Project",
        "research_question": "Question?",
        "priority_topics": [],
        "languages": ["en"],
        "discovery_limits": {},
        "screening_threshold": 0.5,
        "deep_reading_threshold": 0.8,
        "maximum_daily_deep_reads": 1,
        "citation_chasing": {},
        "digest": {},
        "timezone": "Europe/Lisbon",
        "notion": {"enabled": True},
    }


def reading_payload() -> dict:
    return {
        "access_level": "FULL_TEXT",
        "confidence": 0.85,
        "central_argument": "The central claim.",
        "methodology": "Close reading.",
        "major_findings": ["First finding"],
        "concepts": [],
        "relevance_to_project": "Directly relevant.",
        "connections": ["A useful connection"],
        "disagreements": [],
        "references_to_follow": ["A reference"],
    }


class FakeNotionAdapter:
    configured = True

    def __init__(self) -> None:
        self.created: list[tuple[str, dict, list[dict]]] = []
        self.updated: list[tuple[str, dict]] = []
        self.schema_sources: list[str] = []

    def resolved_data_source_id(self) -> str:
        return "source-1"

    def ensure_article_schema(self, data_source_id: str) -> None:
        self.schema_sources.append(data_source_id)

    def create_article_page(self, data_source_id: str, properties: dict, children: list[dict]) -> str:
        self.created.append((data_source_id, properties, children))
        return "page-1"

    def update_article_page(self, page_id: str, properties: dict) -> None:
        self.updated.append((page_id, properties))


def digest_with_reading(repo: AlbertoRepository) -> tuple[dict, int, int]:
    config = project_config()
    repo.upsert_project(config)
    paper_id = repo.upsert_paper(
        PaperRecord(
            title="A Notion-ready article",
            doi="10.1000/notion",
            authors=("Ada Lovelace", "Grace Hopper"),
            venue="Journal of Archives",
            publication_year=2026,
            url="https://example.test/article",
        )
    )
    repo.add_reading(config["id"], paper_id, reading_payload())
    digest_id, _ = generate_digest(repo, project_id=config["id"], project_name=config["name"], digest_date="2026-08-29")
    return config, paper_id, digest_id


def test_sync_creates_one_notion_page_per_digest_reading(repo: AlbertoRepository) -> None:
    config, paper_id, digest_id = digest_with_reading(repo)
    adapter = FakeNotionAdapter()

    report = sync_digest_readings_to_notion(repo, config=config, digest_id=digest_id, adapter=adapter)  # type: ignore[arg-type]

    assert report.status == "synced"
    assert report.created == 1
    assert adapter.created[0][0] == "source-1"
    assert adapter.schema_sources == ["source-1"]
    properties = adapter.created[0][1]
    assert properties["Article"]["title"][0]["text"]["content"] == "A Notion-ready article"
    assert properties["Authors"]["rich_text"][0]["text"]["content"] == "Ada Lovelace, Grace Hopper"
    assert repo.notion_page_id(config["id"], paper_id) == "page-1"


def test_sync_updates_an_existing_article_page(repo: AlbertoRepository) -> None:
    config, paper_id, digest_id = digest_with_reading(repo)
    digest_item_id = repo.digest_readings_for_notion(digest_id)[0]["digest_item_id"]
    repo.record_notion_article_sync(
        project_id=config["id"], paper_id=paper_id, notion_page_id="existing-page", digest_item_id=digest_item_id
    )
    adapter = FakeNotionAdapter()

    report = sync_digest_readings_to_notion(repo, config=config, digest_id=digest_id, adapter=adapter)  # type: ignore[arg-type]

    assert report.updated == 1
    assert not adapter.created
    assert adapter.updated[0][0] == "existing-page"


def test_notion_is_opt_in_and_schema_has_searchable_fields(monkeypatch) -> None:
    assert not NotionAdapter.from_project_config({}).configured
    monkeypatch.setenv("ALBERTO_NOTION_ENABLED", "1")
    monkeypatch.setenv("NOTION_DATABASE_ID", "database-1")
    monkeypatch.setenv("NOTION_API_KEY", "notion-secret")
    assert NotionAdapter.from_project_config({}).configured
    properties = article_database_properties()
    assert {"Article", "DOI", "Authors", "Digest date", "Central argument"}.issubset(properties)
    children = notion_article_children({"structured_json": '{"major_findings": ["Finding"]}'})
    assert children[0]["type"] == "heading_2"


def test_existing_notion_database_schema_is_completed_without_removing_fields(monkeypatch) -> None:
    adapter = NotionAdapter(api_key="notion-secret", data_source_id="source-1")
    requests: list[tuple[str, str, dict]] = []

    def fake_request(method: str, path: str, **kwargs):
        requests.append((method, path, kwargs))
        if method == "GET":
            return {
                "properties": {
                    "Name": {"id": "title-id", "type": "title", "title": {}},
                    "Personal note": {"id": "note-id", "type": "rich_text", "rich_text": {}},
                }
            }
        return {}

    monkeypatch.setattr(adapter, "_request", fake_request)
    adapter.ensure_article_schema("source-1")

    assert requests[1][0:2] == ("PATCH", "/data_sources/source-1")
    updates = requests[1][2]["json"]["properties"]
    assert updates["title-id"] == {"name": "Article"}
    assert "Personal note" not in updates
    assert {"DOI", "Confidence", "Digest date"}.issubset(updates)


def test_backfill_links_pre_notion_digest_items_and_syncs_them(repo: AlbertoRepository) -> None:
    config = project_config()
    repo.upsert_project(config)
    paper_id = repo.upsert_paper(PaperRecord(title="Historic reading", publication_year=2025))
    reading_id = repo.add_reading(config["id"], paper_id, reading_payload())
    digest_id = repo.create_digest(
        config["id"],
        None,
        "2026-08-01",
        "Historic digest",
        "Body",
        {},
        [
            {
                "id": "historic-item",
                "paper_id": paper_id,
                "item_type": "reading",
                "title": "Historic reading",
                "body": "Body",
                "stable_ref": "historic-item",
            }
        ],
    )
    repo.conn.execute("UPDATE digest_items SET reading_id=NULL WHERE digest_id=?", (digest_id,))
    adapter = FakeNotionAdapter()

    linked, report = backfill_digest_readings_to_notion(repo, adapter=adapter)  # type: ignore[arg-type]

    assert linked == 1
    assert report.created == 1
    assert repo.digest_readings_for_notion(digest_id)[0]["paper_id"] == paper_id
    assert repo.conn.execute("SELECT reading_id FROM digest_items WHERE id='historic-item'").fetchone()["reading_id"] == reading_id


def test_backfill_includes_readings_that_were_not_promoted_to_a_digest(repo: AlbertoRepository) -> None:
    config = project_config()
    repo.upsert_project(config)
    digest_paper_id = repo.upsert_paper(PaperRecord(title="Reported reading", publication_year=2025))
    unreported_paper_id = repo.upsert_paper(PaperRecord(title="Unreported reading", publication_year=2025))
    reported_reading_id = repo.add_reading(config["id"], digest_paper_id, reading_payload())
    repo.add_reading(config["id"], unreported_paper_id, reading_payload())
    repo.create_digest(
        config["id"],
        None,
        "2026-08-02",
        "Historic digest",
        "Body",
        {},
        [
            {
                "id": "reported-item",
                "paper_id": digest_paper_id,
                "reading_id": reported_reading_id,
                "item_type": "reading",
                "title": "Reported reading",
                "body": "Body",
                "stable_ref": "reported-item",
            }
        ],
    )
    adapter = FakeNotionAdapter()

    _, report = backfill_digest_readings_to_notion(repo, adapter=adapter)  # type: ignore[arg-type]

    assert report.created == 2
    properties = {page[1]["Article"]["title"][0]["text"]["content"]: page[1] for page in adapter.created}
    assert properties["Unreported reading"]["Digest date"]["date"] is None


def test_backfill_includes_historical_digest_candidates(repo: AlbertoRepository) -> None:
    config = project_config()
    repo.upsert_project(config)
    paper_id = repo.upsert_paper(
        PaperRecord(title="Historic candidate", abstract="Candidate abstract", publication_year=2025)
    )
    repo.create_digest(
        config["id"],
        None,
        "2026-08-03",
        "Historic digest",
        "Body",
        {},
        [
            {
                "id": "candidate-item",
                "paper_id": paper_id,
                "item_type": "paper",
                "title": "Historic candidate",
                "body": "Needs full-text acquisition.",
                "stable_ref": "candidate-item",
            }
        ],
    )
    adapter = FakeNotionAdapter()

    _, report = backfill_digest_readings_to_notion(repo, adapter=adapter)  # type: ignore[arg-type]

    assert report.created == 1
    properties = adapter.created[0][1]
    assert properties["Archive status"]["select"]["name"] == "Candidate / metadata only"
    assert properties["Abstract"]["rich_text"][0]["text"]["content"] == "Candidate abstract"
