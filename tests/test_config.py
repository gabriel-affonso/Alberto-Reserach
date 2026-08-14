from __future__ import annotations

from pathlib import Path

import pytest

from alberto.research.config import load_project_config, validate_project_config


def test_example_project_config_loads() -> None:
    config = load_project_config(Path("projects/example-research.yaml"))
    assert config["id"] == "alberto-research-example"
    assert config["timezone"] == "Europe/Lisbon"
    assert config["citation_chasing"]["enabled"] is True


def test_project_config_requires_threshold_range() -> None:
    config = load_project_config(Path("projects/example-research.yaml"))
    config["screening_threshold"] = 1.2
    with pytest.raises(ValueError):
        validate_project_config(config)
