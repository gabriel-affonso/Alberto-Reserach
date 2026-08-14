from __future__ import annotations

import json
from pathlib import Path

import pytest

from alberto.research.providers.base import Provider, ProviderError, RetryPolicy
from alberto.research.providers.crossref import normalize_crossref_item
from alberto.research.providers.semantic_scholar import normalize_semantic_scholar_item


def load_records() -> dict:
    return json.loads(Path("tests/fixtures/provider_records.json").read_text(encoding="utf-8"))


def test_provider_normalization() -> None:
    fixtures = load_records()
    crossref = normalize_crossref_item(fixtures["crossref"])
    scholar = normalize_semantic_scholar_item(fixtures["semantic_scholar"])
    assert crossref.doi == "10.1234/Example.DOI"
    assert scholar.doi == "10.1234/example.doi"
    assert crossref.authors == ("Ada Lovelace",)
    assert scholar.external_ids["CorpusId"] == "987"


def test_crossref_missing_and_partial_dates_do_not_fail() -> None:
    no_issued = normalize_crossref_item({"title": ["No Date"]})
    none_issued = normalize_crossref_item({"title": ["None Date"], "issued": None})
    partial = normalize_crossref_item({"title": ["Partial"], "issued": {"date-parts": [[2025, None, 4]]}})
    none_first = normalize_crossref_item({"title": ["None First"], "issued": {"date-parts": [[None]]}})
    assert no_issued.publication_year is None
    assert none_issued.publication_year is None
    assert partial.publication_year == 2025
    assert partial.publication_date == "2025"
    assert none_first.publication_year is None


class FailingProvider(Provider):
    name = "failing"

    def search(self, query: str, *, limit: int, dry_run: bool = False):
        raise NotImplementedError


def test_retry_failure_behavior(monkeypatch) -> None:
    calls = {"count": 0}

    class Response:
        status_code = 429

        def raise_for_status(self):
            raise RuntimeError("rate limited")

    def request(*args, **kwargs):
        calls["count"] += 1
        return Response()

    import sys
    import types

    fake_requests = types.SimpleNamespace(request=request)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    provider = FailingProvider(retry_policy=RetryPolicy(attempts=2, base_delay_seconds=0), sleep=lambda _: None)
    with pytest.raises(ProviderError):
        provider._request_json("GET", "https://example.test")
    assert calls["count"] == 2


def test_retry_after_header_controls_429_backoff(monkeypatch) -> None:
    calls = {"count": 0}
    sleeps: list[float] = []

    class Response:
        def __init__(self, status_code: int, headers: dict[str, str] | None = None):
            self.status_code = status_code
            self.headers = headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")

        def json(self):
            return {"ok": True}

    def request(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return Response(429, {"Retry-After": "2"})
        return Response(200)

    import sys
    import types

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(request=request))
    provider = FailingProvider(
        retry_policy=RetryPolicy(attempts=3, base_delay_seconds=0.25),
        sleep=sleeps.append,
    )
    assert provider._request_json("GET", "https://example.test") == {"ok": True}
    assert calls["count"] == 2
    assert sleeps == [2.0]
