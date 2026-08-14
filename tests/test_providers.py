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
