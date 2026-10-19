"""Tests for the governed SemanticLayerToolkit surface."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth import PermissionContext
from parrot.semantic import SemanticLayerToolkit, SemanticPolicyError
from parrot.semantic.models import CompiledQuery, GovernedQuery, SemanticQuery

from ._models import duckdb_warehouse, models_dir  # noqa: F401


def _tool_names(toolkit: SemanticLayerToolkit) -> set[str]:
    """Return generated names for a toolkit instance."""
    return {tool.name for tool in toolkit.get_tools()}


def test_toolkit_tool_exposure(models_dir: Path, allow_all_guard: MagicMock) -> None:
    """Expose prefixed governed tools and fail closed without a guard."""
    with pytest.raises(SemanticPolicyError, match="guard_required"):
        SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb")

    toolkit = SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", dataplane_guard=allow_all_guard)
    names = _tool_names(toolkit)

    assert "sl_query_metrics" in names
    assert "sl_compile_query" in names
    assert "sl_list_models" in names
    assert "sl_run_sql" not in names
    assert "sl_save_result_as_dataset" not in names
    assert "sl_reload" not in names


@pytest.mark.asyncio
async def test_audit_required_resolution(
    models_dir: Path,
    allow_all_guard: MagicMock,
    pctx_factory: Callable[..., PermissionContext],
) -> None:
    """Resolve audit durability defaults and withhold rows on required sink failure."""
    in_memory = SemanticLayerToolkit(
        models_dir=models_dir,
        dialect="duckdb",
        dataplane_guard=allow_all_guard,
    )
    durable = SemanticLayerToolkit(
        models_dir=models_dir,
        dialect="duckdb",
        dataplane_guard=allow_all_guard,
        audit_storage=AsyncMock(),
    )
    explicit = SemanticLayerToolkit(
        models_dir=models_dir,
        dialect="duckdb",
        dataplane_guard=allow_all_guard,
        audit_storage=AsyncMock(),
        audit_required=False,
    )

    assert in_memory._audit_required is False
    assert durable._audit_required is True
    assert explicit._audit_required is False

    failing = SemanticLayerToolkit(
        models_dir=models_dir,
        dialect="duckdb",
        dataplane_guard=allow_all_guard,
        audit_storage=AsyncMock(side_effect=OSError("sink unavailable")),
        audit_required=True,
    )
    failing._pbac.available = True
    failing._pipeline.govern = AsyncMock(
        return_value=GovernedQuery(
            sql="SELECT 1 AS revenue LIMIT 1",
            dialect="duckdb",
            driver="duckdb",
            tables=("sales.orders",),
            rls_applied=(),
            masked_columns=(),
            limit=1,
            subject_digest="subject",
        )
    )
    failing._executor.run = AsyncMock(return_value=([{"revenue": 1}], 1, False, 1))

    async def compiled(*args: Any, **kwargs: Any) -> CompiledQuery:
        return CompiledQuery(
            sql="SELECT 1 AS revenue",
            dialect="duckdb",
            engine="sidemantic",
            members=("revenue",),
            tables=("sales.orders",),
            cache_key="test",
        )

    import parrot.semantic.toolkit as toolkit_module

    original_compile = toolkit_module.compile_query_sql
    toolkit_module.compile_query_sql = compiled
    try:
        await failing._pre_execute("sl_query_metrics", _permission_context=pctx_factory(roles=("admin",)))
        result = await failing.query_metrics(SemanticQuery(model="orders", metrics=["revenue"], limit=1))
    finally:
        toolkit_module.compile_query_sql = original_compile

    assert result["error"] == "audit_unavailable"
    assert "rows" not in result


@pytest.mark.asyncio
async def test_toolkit_static_subject_logged(
    models_dir: Path,
    allow_all_guard: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Use, log, and audit a static local-MCP identity on every tool call."""
    toolkit = SemanticLayerToolkit(
        models_dir=models_dir,
        dialect="duckdb",
        dataplane_guard=allow_all_guard,
        static_subject={"user_id": "operator", "tenant_id": "local", "roles": ["admin"]},
    )
    toolkit._pbac.available = True
    tool = next(item for item in toolkit.get_tools() if item.name == "sl_list_models")

    with caplog.at_level(logging.WARNING):
        result = await tool._execute()

    assert result == [{"name": "orders", "governed": True, "engine": "sidemantic"}]
    assert "static_subject operator used for sl_list_models" in caplog.text
    entry = toolkit._ledger.entries[-1]
    assert entry.static_subject is True
    assert entry.user_id == "operator"
    assert entry.tenant_id == "local"
    assert entry.channel == "mcp-local"
