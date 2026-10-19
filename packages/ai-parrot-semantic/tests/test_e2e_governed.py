"""FEAT-704 e2e security gate: governed queries on an in-process DuckDB (spec §4 Integration Tests).

DuckDB driver workaround (issue:58d44d14dd8a): the core asyncdb duckdb driver fails on ``fetch_all`` in some
environments, so the toolkit's duckdb source ``query`` is routed through the in-process ``duckdb`` module exactly
as ``test_execution.py`` does. Rows are always computed by DuckDB from the GOVERNED SQL — never stubbed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import duckdb
import pytest
import yaml

from parrot.auth import PermissionContext
from parrot.semantic import SemanticLayerToolkit
from parrot.tools.databasequery.base import QueryResult
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit

from ._models import duckdb_warehouse, models_dir  # noqa: F401

pytestmark = pytest.mark.asyncio

CONN_ENV = "PARROT_SEMANTIC_CONN_TEST_WAREHOUSE_DATABASE"
POLICY = "orders.policy.yaml"


def _patch_duckdb_source(toolkit: DatabaseQueryToolkit, executed: list[str]) -> None:
    """Record every SQL string the stock duckdb source executes (real driver, no stubbed rows)."""
    source = toolkit.get_source("duckdb")
    real_query = source.query

    async def _query(credentials: dict, sql: str, params: Any = None) -> QueryResult:
        executed.append(sql)
        return await real_query(credentials, sql, params)

    source.query = _query  # type: ignore[method-assign]


def _edit_policy(models_dir: Path, *, grant_amount_usage: bool = True, **updates: Any) -> None:
    """Rewrite the fixture policy: RLS bound to the duckdb driver, plus optional overrides.

    ``grant_amount_usage`` widens the analyst usage grant to ``"*"`` (``amount`` is not a member, so it cannot be listed): the lineage pass classifies the
    aggregate input of a granted metric (``SUM(amount)``) as a ``derived`` use, so without it a granted
    metric is unusable; masks still bind (see ``test_e2e_granted_metric_requires_no_usage_grant``).
    """
    path = models_dir / POLICY
    policy = yaml.safe_load(path.read_text())
    for rule in policy.get("rls", []):
        rule["driver"] = "duckdb"
    if grant_amount_usage:
        policy["roles"]["analyst"]["usage"] = "*"
    policy.update(updates)
    path.write_text(yaml.safe_dump(policy, sort_keys=False))


def _build(models_dir: Path, warehouse: str, guard: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[str]]:
    """Build a toolkit executing against the DuckDB warehouse."""
    monkeypatch.setenv(CONN_ENV, warehouse)
    monkeypatch.setattr("parrot.semantic.execution.get_default_credentials", lambda d: {})
    executed: list[str] = []
    dbtk = DatabaseQueryToolkit()
    _patch_duckdb_source(dbtk, executed)
    tk = SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", dataplane_guard=guard, database_toolkit=dbtk)
    tk._pbac.available = True  # navigator-auth evaluator presence is probed at import; the guard double decides
    return tk, executed


@pytest.fixture
def toolkit(models_dir, duckdb_warehouse, allow_all_guard, monkeypatch):  # noqa: F811
    """Toolkit over the fixture models with an allow-all guard."""
    _edit_policy(models_dir)
    tk, executed = _build(models_dir, duckdb_warehouse, allow_all_guard, monkeypatch)
    tk._executed = executed  # type: ignore[attr-defined]
    return tk


async def _call(tk: SemanticLayerToolkit, name: str, pctx: PermissionContext, **params: Any) -> Any:
    tool = next(t for t in tk.get_tools() if t.name == name)
    result = await tool.execute(**params, _permission_context=pctx)
    payload = getattr(result, "result", result)
    status = getattr(result, "status", "success")
    assert status == "success", result
    return payload


def _q(**kw: Any) -> dict:
    base = {"model": "orders", "metrics": ["revenue"], "dimensions": ["region"]}
    base.update(kw)
    return base


def _by_region(rows: list[dict]) -> dict[str, float]:
    return {r["region"]: float(r["revenue"]) for r in rows}


async def test_e2e_duckdb_governed_query(toolkit, pctx_factory: Callable[..., PermissionContext]) -> None:
    """Rows come from DuckDB via governed SQL; one ok ledger entry records compiled and governed SQL."""
    pctx = pctx_factory(roles=("analyst",), programs=["EU", "US"])
    result = await _call(toolkit, "sl_query_metrics", pctx, query=_q())
    assert _by_region(result["rows"]) == {"EU": 40.0, "US": 20.0}
    entries = [e for e in toolkit._ledger.entries if e.tool == "query_metrics"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.outcome == "ok" and entry.pbac == "allow"
    assert entry.governed_sql and entry.compiled_sql
    assert entry.governed_sql == result["compiled_sql"] == toolkit._executed[-1]
    assert entry.rls_applied and entry.row_count == 2


async def test_e2e_rls_two_subjects_same_roles(toolkit, pctx_factory: Callable[..., PermissionContext]) -> None:
    """Same roles/tenant, different programs -> different rows from one warm cache entry."""
    a = pctx_factory(user_id="user-a", roles=("analyst",), programs=["EU"])
    b = pctx_factory(user_id="user-b", roles=("analyst",), programs=["US"])
    ra = await _call(toolkit, "sl_query_metrics", a, query=_q())
    assert _by_region(ra["rows"]) == {"EU": 40.0}
    cached = list(toolkit._cache._data.values())
    assert len(cached) == 1
    sql_before = cached[0].sql
    rb = await _call(toolkit, "sl_query_metrics", b, query=_q())
    assert _by_region(rb["rows"]) == {"US": 20.0}
    after = list(toolkit._cache._data.values())
    assert len(after) == 1 and after[0].sql == sql_before
    assert "'EU'" not in sql_before and "'US'" not in sql_before
    assert ra["compiled_sql"] != rb["compiled_sql"]


async def test_e2e_pbac_denial_paths(
    models_dir, duckdb_warehouse, deny_table_guard, pctx_factory, monkeypatch  # noqa: F811
) -> None:
    """Denying sales.orders denies every structured path, leaks no SQL and never touches DuckDB."""
    saved = {
        "name": "revenue_by_region",
        "query": _q(),
        "verified_by": "reviewer",
        "verified_at": "2026-10-01",
    }
    _edit_policy(models_dir, saved_queries=[saved])
    guard = deny_table_guard("sales.orders")
    allow = guard.authorize_source.side_effect
    guard.authorize_source.side_effect = None  # allow while warming the compile cache
    tk, executed = _build(models_dir, duckdb_warehouse, guard, monkeypatch)
    pctx = pctx_factory(roles=("analyst",), programs=["EU"])
    warm = await _call(tk, "sl_compile_query", pctx, query=_q())
    assert "sql" in warm and tk._cache._data
    guard.authorize_source.side_effect = allow
    executed.clear()

    calls = [
        ("sl_compile_query", {"query": _q()}),  # cache hit path
        ("sl_query_metrics", {"query": _q()}),
        ("sl_query_metrics", {"query": {"model": "orders", "saved_query": "revenue_by_region"}}),
        ("sl_get_dimension_values", {"model": "orders", "dimension": "region"}),
    ]
    for name, params in calls:
        result = await _call(tk, name, pctx, **params)
        assert isinstance(result, dict) and result.get("error") == "pbac_denied", (name, result)
        text = repr(result).lower()
        assert "select" not in text and "sales.orders" not in text.replace("table:read", ""), (name, result)
        assert "rows" not in result and "sql" not in result and "compiled_sql" not in result
    assert executed == []
    denied = [e for e in tk._ledger.entries if e.outcome == "denied"]
    assert len(denied) == len(calls) and all(e.pbac == "deny" for e in denied)


async def test_e2e_native_engine_switch(
    models_dir, duckdb_warehouse, allow_all_guard, pctx_factory, monkeypatch, tmp_path  # noqa: F811
) -> None:
    """The native compiler returns the same governed rows as the sidemantic engine."""
    _edit_policy(models_dir)
    native_dir = tmp_path / "native_models"
    native_dir.mkdir()
    for item in models_dir.iterdir():
        (native_dir / item.name).write_bytes(item.read_bytes())
    _edit_policy(native_dir, engine="native")

    pctx = pctx_factory(roles=("analyst",), programs=["EU", "US"])
    side, _ = _build(models_dir, duckdb_warehouse, allow_all_guard, monkeypatch)
    native, _ = _build(native_dir, duckdb_warehouse, allow_all_guard, monkeypatch)
    assert native._models["orders"].policy.engine == "native"
    rs = await _call(side, "sl_query_metrics", pctx, query=_q())
    rn = await _call(native, "sl_query_metrics", pctx, query=_q())
    assert _by_region(rs["rows"]) == _by_region(rn["rows"]) == {"EU": 40.0, "US": 20.0}
    assert native._ledger.entries[-1].engine == "native"


async def test_e2e_granted_metric_requires_no_usage_grant(
    models_dir, duckdb_warehouse, allow_all_guard, pctx_factory, monkeypatch  # noqa: F811
) -> None:
    """A role granted metric ``revenue`` (usage: [region] only, as in spec §3) can query it."""
    _edit_policy(models_dir, grant_amount_usage=False)
    tk, _ = _build(models_dir, duckdb_warehouse, allow_all_guard, monkeypatch)
    pctx = pctx_factory(roles=("analyst",), programs=["EU"])
    result = await _call(tk, "sl_query_metrics", pctx, query=_q())
    assert _by_region(result["rows"]) == {"EU": 40.0}
