"""Fail-closed tests for the semantic layer's two-phase PBAC gate."""

from __future__ import annotations

import importlib.util
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest
import sqlglot

from parrot.auth import PermissionContext
from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.governance.pbac import PbacGate, resources_from_ast
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources


async def test_pbac_gate_fail_closed(
    allow_all_guard: MagicMock,
    pctx_factory: Callable[..., PermissionContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Governed access denies before the fail-open core guard can see a missing subject."""
    resources = PhysicalResources(driver="duckdb", tables={"duckdb:sales.orders"})

    with pytest.raises(SemanticAccessError, match="no_subject"):
        await PbacGate(allow_all_guard).authorize(None, resources, governed=True)
    allow_all_guard.authorize_source.assert_not_called()

    with pytest.raises(SemanticAccessError, match="pbac_unavailable"):
        await PbacGate(None).authorize(pctx_factory(), resources, governed=True)
    await PbacGate(None).authorize(None, resources, governed=False)

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(SemanticAccessError, match="pbac_unavailable"):
        await PbacGate(allow_all_guard).authorize(pctx_factory(), resources, governed=True)


async def test_pbac_denied_table_blocks_sql(
    deny_table_guard: Callable[[str], MagicMock],
    pctx_factory: Callable[..., PermissionContext],
) -> None:
    """Map a physical table denial to the stable semantic access error."""
    guard = deny_table_guard("dim.customers")
    resources = PhysicalResources(driver="duckdb", tables={"duckdb:dim.customers"})

    with pytest.raises(SemanticAccessError, match="pbac_denied") as caught:
        await PbacGate(guard).authorize(pctx_factory(), resources, governed=True)

    assert caught.value.code == "pbac_denied"
    guard.authorize_source.assert_awaited_once()


async def test_pbac_rejects_tables_outside_manifest(
    allow_all_guard: MagicMock,
    pctx_factory: Callable[..., PermissionContext],
) -> None:
    """Reject compiled tables that were absent from the pre-authorized manifest."""
    resources = PhysicalResources(driver="duckdb", tables={"duckdb:sales.orders", "duckdb:dim.customers"})
    manifest = PhysicalResources(driver="duckdb", tables={"duckdb:sales.orders"})

    with pytest.raises(SemanticAccessError, match="outside_manifest"):
        await PbacGate(allow_all_guard).authorize(pctx_factory(), resources, governed=True, manifest=manifest)
    allow_all_guard.authorize_source.assert_not_called()


def test_resources_from_ast_excludes_cte_names() -> None:
    """Only physical tables become PBAC resources."""
    tree = sqlglot.parse_one("WITH recent AS (SELECT order_id FROM sales.orders) SELECT order_id FROM recent")

    resources = resources_from_ast(tree, "duckdb")

    assert resources.tables == {"duckdb:sales.orders"}
