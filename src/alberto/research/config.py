from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised when PyYAML is absent
    yaml = None


REQUIRED_FIELDS = {
    "id",
    "name",
    "research_question",
    "priority_topics",
    "languages",
    "discovery_limits",
    "screening_threshold",
    "deep_reading_threshold",
    "maximum_daily_deep_reads",
    "citation_chasing",
    "digest",
    "timezone",
}


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith("[") or value.startswith("{"):
        return json.loads(value)
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip('"').strip("'")


def _minimal_yaml_load(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    pending_key: tuple[int, dict[str, Any], str] | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if pending_key and indent > pending_key[0]:
            container: Any = [] if line.startswith("- ") else {}
            pending_key[1][pending_key[2]] = container
            stack.append((indent - 1, container))
            pending_key = None
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        if line.startswith("- "):
            if not isinstance(current, list):
                raise ValueError("Unsupported YAML list placement")
            current.append(_parse_scalar(line[2:]))
            continue
        if ":" not in line or not isinstance(current, dict):
            raise ValueError(f"Unsupported YAML line: {raw}")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if raw_value.strip() == "":
            current[key] = {}
            pending_key = (indent, current, key)
        else:
            current[key] = _parse_scalar(raw_value)
    return root


def load_project_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text)
    else:
        data = _minimal_yaml_load(text)
    if not isinstance(data, dict):
        raise ValueError("Project config must be a mapping")
    validate_project_config(data)
    return data


def validate_project_config(config: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_FIELDS - set(config))
    if missing:
        raise ValueError(f"Project config missing required fields: {', '.join(missing)}")
    if not isinstance(config["id"], str) or not config["id"]:
        raise ValueError("Project id must be a non-empty string")
    if not isinstance(config["research_question"], str) or not config["research_question"]:
        raise ValueError("research_question must be a non-empty string")
    for field in ("priority_topics", "languages"):
        if not isinstance(config[field], list):
            raise ValueError(f"{field} must be a list")
    for field in ("screening_threshold", "deep_reading_threshold"):
        if not isinstance(config[field], (int, float)):
            raise ValueError(f"{field} must be numeric")
        if not 0 <= float(config[field]) <= 1:
            raise ValueError(f"{field} must be between 0 and 1")
    if int(config["maximum_daily_deep_reads"]) < 0:
        raise ValueError("maximum_daily_deep_reads must be non-negative")
    if not isinstance(config["discovery_limits"], dict):
        raise ValueError("discovery_limits must be a mapping")
    if not isinstance(config["citation_chasing"], dict):
        raise ValueError("citation_chasing must be a mapping")
    if not isinstance(config["digest"], dict):
        raise ValueError("digest must be a mapping")
