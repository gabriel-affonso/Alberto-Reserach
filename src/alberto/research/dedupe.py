from __future__ import annotations

import re
import unicodedata

from alberto.research.models import PaperRecord


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi or None


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9]+", " ", ascii_text.lower())).strip()


def bibliographic_key(record: PaperRecord) -> tuple[str, int | None, str]:
    first_author = normalize_text(record.authors[0]) if record.authors else ""
    return (normalize_text(record.title), record.publication_year, first_author)


def records_match(left: PaperRecord, right: PaperRecord) -> bool:
    left_doi = normalize_doi(left.doi)
    right_doi = normalize_doi(right.doi)
    if left_doi and right_doi:
        return left_doi == right_doi
    shared_ids = set(left.external_ids.items()) & set(right.external_ids.items())
    if shared_ids:
        return True
    return bibliographic_key(left) == bibliographic_key(right)


def dedupe_records(records: list[PaperRecord]) -> list[PaperRecord]:
    unique: list[PaperRecord] = []
    for record in records:
        if not any(records_match(record, existing) for existing in unique):
            unique.append(record)
    return unique
