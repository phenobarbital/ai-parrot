"""End-to-end raw-SQL and governed-result DatasetManager hand-off tests."""

from __future__ import annotations

from typing import Any, Callable

import duckdb
import pytest
import yaml

from parrot.auth import PermissionContext
from parrot.semantic import SemanticLayerToolkit
from parrot.semantic.errors import SemanticResultError
from parrot.tools.databasequery.base import QueryResult
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit
from parrot.tools.dataset_manager import DatasetManager

from ._models import duckdb_warehouse, models_dir  # noqa: F401

pytestmark = pytest.mark.asyncio

CONN_ENV = "PARROT_SEMANTIC_CONN_TEST_WAREHOUSE_DATABASE"


def _patch_duckdb_source(toolkit: DatabaseQueryToolkit) -> None:
    """Execute test warehouse queries through in-process DuckDB."""
    source = toolkit.get_source("duckdb")

    async def _query(credentials: dict, sql: str, params: Any = None) -> QueryResult:
        con = duckdb.connect(credentials["database"])
        try:
            cursor = con.execute(sql)
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        finally:
            con.close()
        return QueryResult(driver="duckdb", rows=rows, row_count=len(rows), columns=columns, execution_time_ms=0.0)

    source.query = _query  # type: ignore[method-assign]


def _build(
    models_dir: Any,
    warehouse: str,
    guard: Any,
    monkeypatch: pytest.MonkeyPatch,
    **kwargs: Any,
) -> SemanticLayerToolkit:
    """Build a raw-SQL-enabled semantic toolkit over the fixture warehouse."""
    policy_path = models_dir / "orders.policy.yaml"
    policy = yaml.safe_load(policy_path.read_text())
    for rule in policy["rls"]:
        rule["driver"] = "duckdb"
    policy["roles"]["analyst"]["usage"] = "*"
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False))
    monkeypatch.setenv(CONN_ENV, warehouse)
    monkeypatch.setattr("parrot.semantic.execution.get_default_credentials", lambda driver: {})
    database_toolkit = DatabaseQueryToolkit()
    _patch_duckdb_source(database_toolkit)
    toolkit = SemanticLayerToolkit(
        models_dir=models_dir,
        dialect="duckdb",
        dataplane_guard=guard,
        database_toolkit=database_toolkit,
        allow_raw_sql=True,
        **kwargs,
    )
    toolkit._pbac.available = True
    return toolkit


async def _call(tk: SemanticLayerToolkit, tool_name: str, pctx: PermissionContext, **params: Any) -> Any:
    """Execute a public semantic tool through its normal ContextVar hook."""
    tool = next(tool for tool in tk.get_tools() if tool.name == tool_name)
    result = await tool.execute(**params, _permission_context=pctx)
    assert getattr(result, "status", "success") == "success"
    return getattr(result, "result", result)


async def test_toolkit_shared_manager_rejected(
    models_dir: Any,
    duckdb_warehouse: str,
    allow_all_guard: Any,
    pctx_factory: Callable[..., PermissionContext],
    monkeypatch,
) -> None:
    """A host factory must not return one DatasetManager for different subjects."""
    shared = DatasetManager()
    toolkit = _build(
        models_dir, duckdb_warehouse, allow_all_guard, monkeypatch, dataset_manager_factory=lambda ctx: shared
    )
    first = pctx_factory(user_id="first", roles=("analyst",), programs=["EU"])
    second = pctx_factory(user_id="second", roles=("analyst",), programs=["EU"])
    assert await toolkit._dataset_manager_for(first) is shared
    with pytest.raises(SemanticResultError, match="shared_dataset_manager"):
        await toolkit._dataset_manager_for(second)


async def test_e2e_handoff_two_users_two_sessions(
    models_dir: Any,
    duckdb_warehouse: str,
    allow_all_guard: Any,
    pctx_factory: Callable[..., PermissionContext],
    monkeypatch,
) -> None:
    """Handles remain owner-bound and same-named hand-offs remain manager-isolated."""
    managers: dict[str, DatasetManager] = {}

    def factory(ctx: PermissionContext) -> DatasetManager:
        return managers.setdefault(ctx.user_id, DatasetManager())

    toolkit = _build(models_dir, duckdb_warehouse, allow_all_guard, monkeypatch, dataset_manager_factory=factory)
    owner = pctx_factory(user_id="owner", roles=("analyst",), programs=["EU"])
    other = pctx_factory(user_id="other", roles=("analyst",), programs=["EU"])
    result = await _call(toolkit, "sl_run_sql", owner, model="orders", sql="SELECT region, amount FROM sales.orders")
    saved = await _call(toolkit, "sl_save_result_as_dataset", owner, result_id=result["result_id"], name="orders")
    assert saved["name"] == "orders"
    assert managers["owner"].get_dataset_entry("orders") is not None
    denied = await _call(toolkit, "sl_save_result_as_dataset", other, result_id=result["result_id"], name="orders")
    assert denied["error"] == "result_unavailable"
    assert managers.get("other") is None


async def test_e2e_masked_inference_matrix(
    models_dir: Any,
    duckdb_warehouse: str,
    allow_all_guard: Any,
    pctx_factory: Callable[..., PermissionContext],
    monkeypatch,
) -> None:
    """Raw SQL rejects every non-projection use of a masked column without usage rights."""
    policy_path = models_dir / "orders.policy.yaml"
    policy = yaml.safe_load(policy_path.read_text())
    policy["masks"]["sales.orders.customer_id"] = {
        "strategy": "null",
        "projection_roles": ["admin"],
        "usage_roles": ["admin"],
    }
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False))
    toolkit = _build(models_dir, duckdb_warehouse, allow_all_guard, monkeypatch)
    analyst = pctx_factory(roles=("analyst",), programs=["EU"])
    queries = [
        "SELECT region FROM sales.orders WHERE customer_id > 0",
        "SELECT region, COUNT(*) FROM sales.orders GROUP BY region, customer_id HAVING customer_id > 0",
        "SELECT region FROM sales.orders ORDER BY customer_id",
        "WITH scoped AS (SELECT region, customer_id FROM sales.orders) SELECT region FROM scoped WHERE customer_id > 0",
        "SELECT region, ROW_NUMBER() OVER (ORDER BY customer_id) FROM sales.orders",
    ]
    for sql in queries:
        denied = await _call(toolkit, "sl_run_sql", analyst, model="orders", sql=sql)
        assert denied["error"] == "usage_denied"
        assert toolkit._ledger.entries[-1].raw_sql is True

    admin = pctx_factory(roles=("admin",), programs=["EU"])
    allowed = await _call(
        toolkit, "sl_run_sql", admin, model="orders", sql="SELECT region FROM sales.orders WHERE customer_id > 0"
    )
    assert allowed["rows"] == [{"region": "EU"}, {"region": "EU"}]


async def test_raw_sql_pbac_denial(
    models_dir: Any, duckdb_warehouse: str, deny_table_guard: Callable[[str], Any], pctx_factory, monkeypatch
) -> None:
    """Raw SQL follows the same PBAC denial path as structured queries."""
    toolkit = _build(models_dir, duckdb_warehouse, deny_table_guard("sales.orders"), monkeypatch)
    result = await _call(
        toolkit,
        "sl_run_sql",
        pctx_factory(roles=("analyst",), programs=["EU"]),
        model="orders",
        sql="SELECT region FROM sales.orders",
    )
    assert result["error"] == "pbac_denied"


async def test_request_scoped_handoff_never_mutates_shared_toolkit(
    models_dir: Any,
    duckdb_warehouse: str,
    allow_all_guard: Any,
    pctx_factory: Callable[..., PermissionContext],
    monkeypatch,
) -> None:
    """Review I1: concurrent host hand-offs keep their own managers; the shared toolkit is untouched."""
    import asyncio

    toolkit = _build(models_dir, duckdb_warehouse, allow_all_guard, monkeypatch)
    excluded_before = tuple(toolkit.exclude_tools)
    assert "save_result_as_dataset" in excluded_before
    alice = pctx_factory(user_id="alice", roles=("analyst",), programs=["EU"])
    bob = pctx_factory(user_id="bob", roles=("analyst",), programs=["US"])
    sql = "SELECT region, amount FROM sales.orders"
    res_a = await _call(toolkit, "sl_run_sql", alice, model="orders", sql=sql)
    res_b = await _call(toolkit, "sl_run_sql", bob, model="orders", sql=sql)
    manager_a, manager_b = DatasetManager(), DatasetManager()

    saved_a, saved_b = await asyncio.gather(
        toolkit._save_result_for_request(alice, manager_a, result_id=res_a["result_id"], name="mine"),
        toolkit._save_result_for_request(bob, manager_b, result_id=res_b["result_id"], name="mine"),
    )

    assert saved_a["name"] == saved_b["name"] == "mine"
    rows_a = manager_a.get_dataset_entry("mine")
    rows_b = manager_b.get_dataset_entry("mine")
    assert rows_a is not None and rows_b is not None and rows_a is not rows_b
    assert tuple(toolkit.exclude_tools) == excluded_before
    assert toolkit._dataset_manager_factory is None
    assert "sl_save_result_as_dataset" not in {tool.name for tool in toolkit.get_tools()}
