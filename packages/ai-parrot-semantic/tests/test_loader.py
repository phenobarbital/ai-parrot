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
    model_path.write_text(model_path.read_text() + '\n    security:\n      access: "true"\n', encoding="utf-8")

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


def test_policy_model_schema_is_scoped(tmp_path) -> None:
    """Review I3 / issue:bd477252b8f3: unrelated layer tables are outside a policy model's schema and manifest."""
    import asyncio

    import sqlglot  # noqa: F401
    from unittest.mock import AsyncMock, MagicMock

    from parrot.auth import PermissionContext, RlsRegistry, UserSession
    from parrot.semantic.errors import SemanticValidationError
    from parrot.semantic.governance.pbac import PbacGate
    from parrot.semantic.governance.pipeline import GovernancePipeline
    from parrot.semantic.governance.rls import RlsPushdown
    from parrot.semantic.loader import SemanticModelLoader

    (tmp_path / "orders.yml").write_text("""version: 1
models:
  - name: orders
    table: sales.orders
    primary_key: id
    relationships:
      - {name: customers, type: many_to_one, foreign_key: customer_id}
    dimensions:
      - {name: region, type: categorical, metadata: {data_type: TEXT}}
      - {name: customer_id, type: numeric, metadata: {data_type: BIGINT}}
    metrics:
      - {name: revenue, agg: sum, sql: amount}
  - name: customers
    table: dim.customers
    primary_key: id
    dimensions:
      - {name: segment, type: categorical, metadata: {data_type: TEXT}}
  - name: payroll
    table: hr.payroll
    primary_key: id
    dimensions:
      - {name: salary, type: numeric, metadata: {data_type: DECIMAL}}
""")
    (tmp_path / "orders.policy.yaml").write_text(
        "governed: true\nconnection: c\nroles:\n  analyst: {metrics: [revenue], dimensions: [region], usage: '*'}\n"
    )
    model = SemanticModelLoader(tmp_path, driver="duckdb").load()["orders"]
    assert set(model.schema.tables) == {"sales.orders", "dim.customers"}

    guard = MagicMock()
    guard.authorize_source = AsyncMock()
    pbac = PbacGate(guard)
    pbac.available = True
    pipeline = GovernancePipeline(pbac=pbac, rls=RlsPushdown(RlsRegistry()), allowed_functions=frozenset())
    ctx = PermissionContext(session=UserSession(user_id="u", tenant_id="t", roles=frozenset({"analyst"})))

    manifest = asyncio.run(pbac.authorize_manifest(ctx, model))
    assert manifest.tables == {"duckdb:sales.orders", "duckdb:dim.customers"}
    with pytest.raises(SemanticValidationError) as denied:
        asyncio.run(
            pipeline.govern("SELECT salary FROM hr.payroll", model=model, ctx=ctx, roles=frozenset({"analyst"}))
        )
    assert denied.value.code in {"unknown_table", "unsafe_sql"}
    guard.authorize_source.assert_awaited_once()  # only the manifest call; the out-of-scope SQL never reached PBAC
