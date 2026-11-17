"""Regression contract: Governed catalog, compile and query toolkit (M10a)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.auth import PermissionContext, UserSession
from parrot.semantic import SemanticLayerToolkit
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context
from parrot.semantic.errors import SemanticAccessError, SemanticPolicyError
from parrot.semantic.models import GovernedQuery, SemanticQuery

from ._models import models_dir  # noqa: F401


def _context() -> PermissionContext:
    """Build a trusted context for toolkit tests."""
    return PermissionContext(session=UserSession("analyst", "tenant-a", frozenset({"analyst"}), {}))


@pytest.mark.asyncio
async def test_catalog_compile_query_govern_and_audit(models_dir: Path) -> None:
    """Compile an authorized fixture query and append its audit record first."""
    with pytest.raises(SemanticPolicyError) as error:
        SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb")
    assert error.value.code == "guard_required"
    (models_dir / "orders.policy.yaml").write_text(
        "governed: false\nroles: {analyst: {metrics: '*', dimensions: '*', usage: '*'}}\n", encoding="utf-8"
    )
    toolkit = SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb")
    async with bind_semantic_context(_context()):
        result = await toolkit.compile_query(SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]))
    assert "SELECT" in result["sql"]
    assert toolkit._ledger.entries[-1].entry_id == result["audit_id"]


@pytest.mark.asyncio
async def test_no_static_fallback_or_missing_guard(models_dir: Path) -> None:
    """Require an externally bound context and reject static subjects."""
    with pytest.raises(SemanticPolicyError) as error:
        SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", static_subject={"user_id": "operator"})
    assert error.value.code == "static_subject_forbidden"

    toolkit = object.__new__(SemanticLayerToolkit)
    with pytest.raises(SemanticAccessError) as error:
        await toolkit._pre_execute("query_metrics", _permission_context=_context())
    assert error.value.code == "context_required"


@pytest.mark.asyncio
async def test_trusted_retention_and_audit_before_return(models_dir: Path) -> None:
    """Retain a result only while a complete trusted identity is bound."""
    (models_dir / "orders.policy.yaml").write_text("governed: false\n", encoding="utf-8")
    toolkit = SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb")
    loaded = toolkit._models["orders"]
    governed = GovernedQuery(
        sql="SELECT orders.region FROM sales.orders AS orders",
        dialect="duckdb",
        driver="duckdb",
        tables=("sales.orders",),
        rls_applied=(),
        masked_columns=(),
        limit=50,
        subject_digest="digest",
        members=("region",),
        physical_columns=("sales.orders.region",),
    )
    async with bind_semantic_context(_context()):
        assert toolkit._retain(loaded, governed, ["region"], [{"region": "eu"}], "audit") is None
    identity = SemanticRequestIdentity(ctx=_context(), channel="agent", agent_id="agent", session_id="session")
    async with bind_semantic_context(_context(), identity=identity):
        assert toolkit._retain(loaded, governed, ["region"], [{"region": "eu"}], "audit") is not None
