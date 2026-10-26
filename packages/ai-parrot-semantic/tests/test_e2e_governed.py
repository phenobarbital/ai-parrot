"""Regression contract: Real-DuckDB governed-query security gate (M10 gate)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from parrot.auth import PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired
from parrot.semantic import SemanticLayerToolkit
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context, current_identity, current_pctx
from parrot.semantic.errors import SemanticAccessError, SemanticExecutionError, SemanticResultError
from parrot.semantic.governance import pbac
from parrot.semantic.governance.pipeline import subject_digest
from parrot.semantic.models import SemanticQuery

from ._models import duckdb_warehouse, models_dir  # noqa: F401


class _EvaluatorGuard:
    """Deterministic PBAC evaluator used while exercising the real DuckDB source."""

    def __init__(self, *, deny: bool = False) -> None:
        """Create a guard that records manifest and post-compile authorization."""
        self._evaluator = object()
        self.deny = deny
        self.calls: list[object] = []

    async def authorize_source(self, ctx: PermissionContext, resources: object) -> None:
        """Authorize the supplied resources or deterministically deny them."""
        self.calls.append(resources)
        if self.deny:
            raise AuthorizationRequired("semantic_query", "denied")


def _context(user_id: str, program: str) -> PermissionContext:
    """Build subjects with identical role and tenant claims but distinct programs."""
    return PermissionContext(
        session=UserSession(
            user_id=user_id,
            tenant_id="tenant-a",
            roles=frozenset({"analyst"}),
            metadata={"programs": [program]},
        )
    )


def _toolkit(
    models_dir: Path,
    warehouse: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    guard: _EvaluatorGuard | None = None,
    audit_storage: object | None = None,
    audit_required: bool = False,
) -> SemanticLayerToolkit:
    """Configure a toolkit whose executor resolves to the real fixture database."""
    monkeypatch.setattr(pbac.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setenv("PARROT_SEMANTIC_CONN_SEMANTIC_TEST_DATABASE", str(warehouse))
    policy_path = models_dir / "orders.policy.yaml"
    policy_path.write_text(
        policy_path.read_text(encoding="utf-8").replace("usage: [sales.orders.region]", 'usage: "*"'),
        encoding="utf-8",
    )
    return SemanticLayerToolkit(
        models_dir=models_dir,
        dialect="duckdb",
        dataplane_guard=guard or _EvaluatorGuard(),
        audit_storage=audit_storage,
        audit_required=audit_required,
    )


@pytest.mark.asyncio
async def test_real_source_two_subjects_warm_cache(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply RLS below aggregation for distinct subjects without cache contamination."""
    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch)
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])

    async with bind_semantic_context(_context("first", "eu")):
        first = await toolkit.query_metrics(query)
    cached_before = tuple(toolkit._cache._data.values())
    async with bind_semantic_context(_context("second", "us")):
        second = await toolkit.query_metrics(query)
    cached_after = tuple(toolkit._cache._data.values())

    assert first.rows == [{"region": "eu", "revenue": 12.5}]
    assert second.rows == [{"region": "us", "revenue": 25.0}]
    assert len(cached_before) == len(cached_after) == 1
    assert cached_before == cached_after
    # issue:22fbd14d96a9 — callers get pre-RLS SQL; RLS literals live only in the audit.
    assert first.compiled_sql == second.compiled_sql
    assert "'eu'" not in first.compiled_sql and "'us'" not in second.compiled_sql
    audited = tuple(toolkit._ledger.entries)[-2:]
    assert all(entry.governed_sql is not None for entry in audited)
    assert "'eu'" in audited[0].governed_sql and "'us'" in audited[1].governed_sql
    assert all("'eu'" not in rule and "'us'" not in rule for entry in audited for rule in entry.rls_applied)


@pytest.mark.asyncio
async def test_all_denial_paths_and_no_sql_leak(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deny unavailable PBAC, policy denial, missing context, and audit failures safely."""
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=_EvaluatorGuard(deny=True))
    async with bind_semantic_context(_context("denied", "eu")):
        with pytest.raises(SemanticAccessError) as denied:
            await toolkit.compile_query(query)
    assert denied.value.code == "pbac_denied"
    assert "SELECT" not in str(denied.value).upper()

    unavailable = _toolkit(models_dir, duckdb_warehouse, monkeypatch)
    unavailable._pbac.available = False
    async with bind_semantic_context(_context("unavailable", "eu")):
        with pytest.raises(SemanticAccessError) as missing_evaluator:
            await unavailable.compile_query(query)
    assert missing_evaluator.value.code == "pbac_unavailable"
    with pytest.raises(SemanticAccessError) as missing_context:
        await unavailable.compile_query(query)
    assert missing_context.value.code == "context_required"

    async def unavailable_audit(_: str) -> None:
        """Simulate a required durable audit sink failure."""
        raise RuntimeError("audit unavailable")

    audited = _toolkit(
        models_dir,
        duckdb_warehouse,
        monkeypatch,
        audit_storage=unavailable_audit,
        audit_required=True,
    )
    async with bind_semantic_context(_context("audit", "eu")):
        with pytest.raises(SemanticExecutionError) as audit_failure:
            await audited.query_metrics(query)
    assert audit_failure.value.code == "audit_unavailable"
    assert "SELECT" not in str(audit_failure.value).upper()

    permitted = _toolkit(models_dir, duckdb_warehouse, monkeypatch)
    async with bind_semantic_context(_context("catalog", "eu")):
        assert await permitted.list_models() == [{"name": "customers", "members": 2}, {"name": "orders", "members": 4}]
        assert {item["name"] for item in await permitted.list_metrics("orders")} == {"revenue", "order_count"}
        assert {item["name"] for item in await permitted.get_dimensions("orders")} == {"region", "order_date"}
        assert await permitted.get_dimension_values("orders", "region")
        assert await permitted.search_data_model("revenue", "orders")
        assert await permitted.list_saved_queries("orders") == []


@pytest.mark.asyncio
async def test_concurrent_context_and_required_audit_failure(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep concurrent identity scopes isolated and reject stale retained provenance."""
    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch)
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    first_context = _context("first", "eu")
    second_context = _context("second", "us")

    async def compile_for(context: PermissionContext) -> dict:
        """Compile under a context-only binding, which must not create a result handle."""
        async with bind_semantic_context(context):
            return await toolkit.compile_query(query)

    first, second = await asyncio.gather(compile_for(first_context), compile_for(second_context))
    assert first["sql"] == second["sql"] and "'eu'" not in first["sql"] and "'us'" not in second["sql"]
    governed = {entry.entry_id: entry.governed_sql for entry in toolkit._ledger.entries}
    assert "'eu'" in governed[first["audit_id"]] and "'us'" in governed[second["audit_id"]]
    assert current_pctx() is None and current_identity() is None

    identity = SemanticRequestIdentity(ctx=first_context, channel="agent", agent_id="agent", session_id="session")
    async with bind_semantic_context(first_context, identity=identity):
        result = await toolkit.query_metrics(query)
    assert result.result_id is not None
    loaded = toolkit._models["orders"]
    with pytest.raises(SemanticResultError) as stale:
        toolkit._handles.claim(
            result.result_id,
            identity=identity,
            subject_digest=subject_digest(first_context),
            model_digest=loaded.model_digest,
            policy_digest="stale-policy-version",
        )
    assert stale.value.code == "result_unavailable"

    entered = asyncio.Event()

    async def cancelled_binding() -> None:
        """Hold a request binding until cancellation exercises context cleanup."""
        async with bind_semantic_context(second_context):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(cancelled_binding())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert current_pctx() is None and current_identity() is None
