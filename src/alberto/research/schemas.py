from __future__ import annotations

from typing import Any

from alberto.enums import AccessLevel


READER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "access_level",
        "bibliographic_information",
        "research_question",
        "central_argument",
        "methodology",
        "sources",
        "major_findings",
        "concepts",
        "relevance_to_project",
        "connections",
        "disagreements",
        "references_to_follow",
        "human_reading_recommended",
        "confidence",
    ],
    "properties": {
        "access_level": {"enum": [level.value for level in AccessLevel]},
        "bibliographic_information": {"type": "object"},
        "research_question": {"type": "string"},
        "central_argument": {"type": "string"},
        "methodology": {"type": "string"},
        "sources": {"type": "array"},
        "major_findings": {"type": "array"},
        "concepts": {"type": "array"},
        "relevance_to_project": {"type": "string"},
        "connections": {"type": "array"},
        "disagreements": {"type": "array"},
        "references_to_follow": {"type": "array"},
        "human_reading_recommended": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "page_provenance": {"type": "array"},
    },
    "additionalProperties": True,
}


FORBIDDEN_OUTPUT_KEYS = {
    "tool_calls",
    "commands",
    "shell",
    "email",
    "secrets",
    "credentials",
    "delete_files",
}


class SchemaValidationError(ValueError):
    pass


def validate_reader_output(payload: dict[str, Any]) -> None:
    try:
        from jsonschema import validate
        from jsonschema.exceptions import ValidationError
    except ModuleNotFoundError:
        _fallback_validate_reader_output(payload)
        return
    try:
        validate(instance=payload, schema=READER_OUTPUT_SCHEMA)
    except ValidationError as exc:
        raise SchemaValidationError(exc.message) from exc
    forbidden = FORBIDDEN_OUTPUT_KEYS & set(payload)
    if forbidden:
        raise SchemaValidationError(f"Reader output contains forbidden keys: {', '.join(sorted(forbidden))}")
    if payload["access_level"] == AccessLevel.ABSTRACT_ONLY.value and payload.get("page_provenance"):
        raise SchemaValidationError("ABSTRACT_ONLY readings must not claim page provenance")


def _fallback_validate_reader_output(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise SchemaValidationError("Reader output must be an object")
    missing = [key for key in READER_OUTPUT_SCHEMA["required"] if key not in payload]
    if missing:
        raise SchemaValidationError(f"Reader output missing required fields: {', '.join(missing)}")
    if payload["access_level"] not in {level.value for level in AccessLevel}:
        raise SchemaValidationError("Invalid access_level")
    if not isinstance(payload["human_reading_recommended"], bool):
        raise SchemaValidationError("human_reading_recommended must be boolean")
    confidence = payload["confidence"]
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise SchemaValidationError("confidence must be between 0 and 1")
    for key in ("sources", "major_findings", "concepts", "connections", "disagreements", "references_to_follow"):
        if not isinstance(payload[key], list):
            raise SchemaValidationError(f"{key} must be a list")
    forbidden = FORBIDDEN_OUTPUT_KEYS & set(payload)
    if forbidden:
        raise SchemaValidationError(f"Reader output contains forbidden keys: {', '.join(sorted(forbidden))}")
    if payload["access_level"] == AccessLevel.ABSTRACT_ONLY.value and payload.get("page_provenance"):
        raise SchemaValidationError("ABSTRACT_ONLY readings must not claim page provenance")
