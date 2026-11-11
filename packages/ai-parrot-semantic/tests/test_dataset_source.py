"""Unit tests for SemanticDataSource (FEAT-880 M4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.auth import PermissionContext, UserSession
from parrot.auth.context import _pctx_var
from parrot.semantic import SemanticDataSource
from parrot.semantic.context import bind_semantic_context
from parrot.semantic.errors import SemanticAccessError, SemanticPolicyError, SemanticValidationError
from parrot.semantic.governance import pbac
from parrot.semantic.governance.pipeline import subject_digest

from ._models import duckdb_warehouse, models_dir  # noqa: F401


class _Guard:
    """Permissive PBAC evaluator."""

    def __init__(self) -> None:
        self._evaluator = object()

    async def authorize_source(self, ctx: PermissionContext, resources: object) -> None:
        """Allow everything."""


def _context(user_id: str, program: str) -> PermissionContext:
    return PermissionContext(
        session=UserSession(
            user_id=user_id, tenant_id="tenant-a", roles=frozenset({"analyst"}),
            metadata={"programs": [program]},
        )
    )


def _source(models_dir: Path, warehouse: Path, monkeypatch: pytest.MonkeyPatch, **kwargs) -> SemanticDataSource:
    monkeypatch.setattr(pbac.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setenv("PARROT_SEMANTIC_CONN_SEMANTIC_TEST_DATABASE", str(warehouse))
    policy_path = models_dir / "orders.policy.yaml"
    policy_path.write_text(
        policy_path.read_text(encoding="utf-8").replace("usage: [sales.orders.region]", 'usage: "*"'),
        encoding="utf-8",
    )
    return SemanticDataSource.from_models_dir(
        name="sales", model="orders", models_dir=models_dir, dialect="duckdb",
        dataplane_guard=_Guard(), **kwargs,
    )


_Q = {"metrics": ["revenue"], "dimensions": ["region"]}


def test_source_rejects_unknown_model(models_dir: Path, duckdb_warehouse: Path, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch)
    with pytest.raises(SemanticPolicyError) as exc:
        SemanticDataSource(name="x", toolkit=source.toolkit, model="nope")
    assert exc.value.code == "model_not_found"
    with pytest.raises(SemanticPolicyError) as bad:
        SemanticDataSource(name="x", toolkit=source.toolkit, model="orders", default_query={"sql": "x"})
    assert bad.value.code == "invalid_default_query"


@pytest.mark.asyncio
async def test_fetch_requires_some_context(models_dir, duckdb_warehouse, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch)
    with pytest.raises(SemanticAccessError) as exc:
        await source.fetch(**_Q)
    assert exc.value.code == "context_required"


@pytest.mark.asyncio
async def test_fetch_rejects_context_mismatch(models_dir, duckdb_warehouse, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch)
    token = _pctx_var.set(_context("other", "us"))
    try:
        async with bind_semantic_context(_context("first", "eu")):
            # bind_semantic_context sets both variables; force a divergence for the core one.
            inner = _pctx_var.set(_context("other", "us"))
            try:
                with pytest.raises(SemanticAccessError) as exc:
                    await source.fetch(**_Q)
                assert exc.value.code == "context_required"
                assert source.current_owner() is None
            finally:
                _pctx_var.reset(inner)
    finally:
        _pctx_var.reset(token)


@pytest.mark.asyncio
async def test_fetch_bridges_core_context(models_dir, duckdb_warehouse, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch)
    token = _pctx_var.set(_context("first", "eu"))
    try:
        frame = await source.fetch(**_Q)
    finally:
        _pctx_var.reset(token)
    assert frame.to_dict("records") == [{"region": "eu", "revenue": 12.5}]
    assert _pctx_var.get(None) is None


@pytest.mark.asyncio
async def test_fetch_rejects_non_context_object(models_dir, duckdb_warehouse, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch)
    token = _pctx_var.set({"user": "x"})
    try:
        with pytest.raises(SemanticAccessError) as exc:
            await source.fetch(**_Q)
        assert exc.value.code == "context_required"
        assert source.current_owner() is None
    finally:
        _pctx_var.reset(token)


@pytest.mark.asyncio
async def test_current_owner_resolution(models_dir, duckdb_warehouse, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch)
    assert source.current_owner() is None
    ctx = _context("first", "eu")
    token = _pctx_var.set(ctx)
    try:
        assert source.current_owner() == subject_digest(ctx)
    finally:
        _pctx_var.reset(token)
    async with bind_semantic_context(ctx):
        assert source.current_owner() == subject_digest(ctx)


@pytest.mark.asyncio
async def test_fetch_builds_query_from_params(models_dir, duckdb_warehouse, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch)
    async with bind_semantic_context(_context("first", "eu")):
        frame = await source.fetch(force_refresh=True, **_Q)
    assert list(frame.columns) == ["region", "revenue"] or set(frame.columns) == {"region", "revenue"}
    assert len(frame) == 1


@pytest.mark.asyncio
async def test_fetch_rejects_model_and_unknown_keys(models_dir, duckdb_warehouse, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch)
    async with bind_semantic_context(_context("first", "eu")):
        for bad in ({"model": "customers", **_Q}, {"sql": "select 1", **_Q}):
            with pytest.raises(SemanticValidationError) as exc:
                await source.fetch(**bad)
            assert exc.value.code == "invalid_params"
        with pytest.raises(SemanticValidationError) as invalid:
            await source.fetch(metrics="not-a-list-of-str", limit="x")
        assert invalid.value.code == "invalid_query"


@pytest.mark.asyncio
async def test_fetch_uses_default_query_and_requires_query(models_dir, duckdb_warehouse, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch, default_query=_Q)
    async with bind_semantic_context(_context("first", "eu")):
        assert len(await source.fetch()) == 1
    bare = SemanticDataSource(name="b", toolkit=source.toolkit, model="orders")
    async with bind_semantic_context(_context("first", "eu")):
        with pytest.raises(SemanticValidationError) as exc:
            await bare.fetch()
    assert exc.value.code == "query_required"


@pytest.mark.asyncio
async def test_fetch_dataframe_shape_and_attrs(models_dir, duckdb_warehouse, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch)
    async with bind_semantic_context(_context("first", "eu")):
        frame = await source.fetch(**_Q)
        empty = await source.fetch(
            metrics=["revenue"], dimensions=["region"], filters=[{"member": "region", "op": "equals", "values": ["zz"]}]
        )
    meta = frame.attrs["semantic"]
    assert set(meta) == {"model", "audit_id", "truncated", "row_count"}
    assert meta["model"] == "orders" and meta["row_count"] == 1
    assert "sql" not in str(meta).lower()
    assert len(empty) == 0 and set(empty.columns) == {"region", "revenue"}


def test_describe_lists_no_members(models_dir, duckdb_warehouse, monkeypatch) -> None:
    source = _source(models_dir, duckdb_warehouse, monkeypatch)
    text = source.describe()
    for member in ("revenue", "region", "order_count", "order_date", "customer_count", "email"):
        assert member not in text
    assert source.self_governed and source.has_builtin_cache
    assert source.cache_key == "semantic:duckdb:orders:sales"
