"""Tests for governed semantic-model loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.semantic.errors import SemanticPolicyError
from parrot.semantic.loader import SemanticModelLoader

from ._models import models_dir


def test_loader_loads_native_and_ossie_sources(models_dir: Path) -> None:
    """The shared directory loads after validating its Apache Ossie document."""
    loaded = SemanticModelLoader(models_dir, driver="duckdb").load()

    assert set(loaded) == {"orders"}
    assert "orders" in loaded["orders"].layer.graph.models
    assert loaded["orders"].schema.tables["sales.orders"]["amount"] == "DECIMAL"
    assert {member.name for member in loaded["orders"].members} >= {"revenue", "region", "email"}


def test_loader_rejects_security_block(models_dir: Path) -> None:
    """Sidemantic model security is rejected in favor of ai-parrot governance."""
    model_path = models_dir / "orders.yml"
    model_path.write_text(model_path.read_text() + "\n    security:\n      access: \"true\"\n", encoding="utf-8")

    with pytest.raises(SemanticPolicyError) as raised:
        SemanticModelLoader(models_dir, driver="duckdb").load()

    assert raised.value.code == "security_block"


def test_reload_if_changed_uses_content_digest(models_dir: Path) -> None:
    """Reload detection ignores stable content and notices policy changes."""
    loader = SemanticModelLoader(models_dir, driver="duckdb")
    loader.load()
    assert loader.reload_if_changed() is False
    policy = models_dir / "orders.policy.yaml"
    policy.write_text(policy.read_text() + "\nallowed_functions: [ROUND]\n", encoding="utf-8")
    assert loader.reload_if_changed() is True
