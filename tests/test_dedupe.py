from __future__ import annotations

from alberto.research.dedupe import dedupe_records, normalize_doi, normalize_text, records_match
from alberto.research.models import PaperRecord


def test_doi_normalization() -> None:
    assert normalize_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert normalize_doi("doi: 10.1000/ABC") == "10.1000/abc"


def test_bibliographic_fallback_match() -> None:
    left = PaperRecord(title="The Same Paper!", authors=("Jane Doe",), publication_year=2024)
    right = PaperRecord(title="The Same Paper", authors=("Jane Doe",), publication_year=2024)
    assert normalize_text(left.title) == normalize_text(right.title)
    assert records_match(left, right)
    assert len(dedupe_records([left, right])) == 1
