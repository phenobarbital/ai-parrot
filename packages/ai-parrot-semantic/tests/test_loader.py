"""Regression contract: Clean-room model loader, graph scoping and fixtures (M4b)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from parrot.semantic.errors import SemanticPolicyError
from parrot.semantic.loader import SemanticModelLoader

_FIXTURES = Path(__file__).parent / "fixtures"


def _copy_own_models(tmp_path: Path) -> Path:
    """Create an isolated complete own-format model directory."""
    models_dir = tmp_path / "models"
    shutil.copytree(_FIXTURES / "models", models_dir)
    (models_dir / "customers.policy.yaml").write_text("governed: false\n", encoding="utf-8")
    return models_dir


def _write_ossie_policy(models_dir: Path) -> None:
    """Add the required side-file for the public Ossie orders fixture."""
    (models_dir / "orders.policy.yaml").write_text(
        "governed: false\nroles: {admin: {metrics: '*', dimensions: '*', usage: '*'}}\n",
        encoding="utf-8",
    )


def test_own_and_ossie_lowering(tmp_path: Path) -> None:
    """Verify own and Ossie lowering into the same typed public graph."""
    own_dir = _copy_own_models(tmp_path)
    own = SemanticModelLoader(own_dir, driver="duckdb").load()
    assert set(own) == {"customers", "orders"}
    assert own["orders"].model.metrics[0].name == "revenue"
    assert own["orders"].schema.tables["sales.orders"]["amount"] == "DECIMAL"

    ossie_dir = tmp_path / "ossie"
    ossie_dir.mkdir()
    shutil.copy(_FIXTURES / "ossie" / "orders.ossie.json", ossie_dir / "orders.ossie.json")
    _write_ossie_policy(ossie_dir)
    ossie = SemanticModelLoader(ossie_dir, driver="duckdb").load()
    assert ossie["orders"].model.metrics[0].agg == "sum"
    assert ossie["orders"].model.dimensions[1].kind == "time"

    document = json.loads((_FIXTURES / "ossie" / "orders.ossie.json").read_text(encoding="utf-8"))
    document["semantic_model"][0]["metrics"][0]["expression"]["dialects"][0]["expression"] = "SUM(amount + 1)"
    (ossie_dir / "orders.ossie.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SemanticPolicyError, match="simple aggregate"):
        SemanticModelLoader(ossie_dir, driver="duckdb").load()


def test_related_model_digest_and_manifest(tmp_path: Path) -> None:
    """Verify reachable graph schema and dependent-model digest provenance."""
    models_dir = _copy_own_models(tmp_path)
    first = SemanticModelLoader(models_dir, driver="duckdb").load()["orders"]
    assert set(first.related_models) == {"customers"}
    assert set(first.schema.tables) == {"dim.customers", "sales.orders"}
    assert first.schema.sqlglot_schema()["sales"]["orders"]["amount"] == "DECIMAL"

    content = (models_dir / "orders.yml").read_text(encoding="utf-8")
    changed = content.replace("email: VARCHAR", "email: TEXT")
    (models_dir / "orders.yml").write_text(changed, encoding="utf-8")
    second = SemanticModelLoader(models_dir, driver="duckdb").load()["orders"]
    assert second.model_digest != first.model_digest
    assert second.policy_digest == first.policy_digest


def test_reload_atomicity_and_bad_policy(tmp_path: Path) -> None:
    """Verify failed reload leaves the last complete snapshot published."""
    models_dir = _copy_own_models(tmp_path)
    loader = SemanticModelLoader(models_dir, driver="duckdb")
    initial = loader.load()
    assert loader.reload_if_changed() is False

    policy_path = models_dir / "orders.policy.yaml"
    policy_path.write_text("governed: true\nconnection: semantic_test\nroles: {analyst: {metrics: [missing]}}\n", encoding="utf-8")
    with pytest.raises(SemanticPolicyError, match="unknown"):
        loader.reload_if_changed()
    assert loader._snapshot is initial
    assert loader._snapshot["orders"].policy_digest == initial["orders"].policy_digest

    policy_path.write_text(
        (_FIXTURES / "models" / "orders.policy.yaml")
        .read_text(encoding="utf-8")
        .replace("default: 1000", "default: 999"),
        encoding="utf-8",
    )
    assert loader.reload_if_changed() is True
