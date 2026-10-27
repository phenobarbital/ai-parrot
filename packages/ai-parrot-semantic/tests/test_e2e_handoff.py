"""Regression contract: Security-gated raw SQL and guarded hand-off tools (M10b)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from parrot.auth import PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired
from parrot.semantic import SemanticLayerToolkit
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context
from parrot.semantic.errors import SemanticAccessError, SemanticResultError
from parrot.semantic.governance import pbac
from parrot.semantic.governance.pipeline import subject_digest
from parrot.semantic.models import SemanticQuery
from parrot.semantic.results import ResultHandle

from ._models import duckdb_warehouse, models_dir  # noqa: F401
from .sink_conformance import PrivateManagerAdapter

_POLICY = """governed: true
connection: semantic_test
limits: {default: 1000, max: 10000}
roles:
  analyst: {metrics: [revenue, order_count], dimensions: [region], usage: "*"}
  admin: {metrics: "*", dimensions: "*", usage: "*"}
rls:
  - {driver: duckdb, table: sales.orders, predicate_template: "region IN (:subject.programs)", subject_attribute: programs}
"""


class _Guard:
    """Deterministic PBAC evaluator with a switchable denial."""

    def __init__(self) -> None:
        """Create an allowing guard that records authorized resources."""
        self._evaluator = object()
        self.deny = False
        self.calls: list[Any] = []

    async def authorize_source(self, ctx: PermissionContext, resources: Any) -> None:
        """Authorize or deny the supplied resources."""
        self.calls.append(resources)
        if self.deny:
            raise AuthorizationRequired("semantic_query", "denied")


def _ctx(user: str = "analyst-1", program: str = "eu") -> PermissionContext:
    return PermissionContext(
        session=UserSession(
            user_id=user, tenant_id="tenant-a", roles=frozenset({"analyst"}), metadata={"programs": [program]}
        )
    )


def _identity(ctx: PermissionContext, session: str = "session-1") -> SemanticRequestIdentity:
    return SemanticRequestIdentity(ctx=ctx, channel="agent", agent_id="agent-1", session_id=session)


def _owner(identity: SemanticRequestIdentity) -> tuple[str, str, str, str]:
    return (identity.agent_id, identity.ctx.user_id, identity.ctx.tenant_id, identity.session_id)


class _Factory:
    """Host factory building one private guarded sink per trusted owner."""

    def __init__(self) -> None:
        self.sinks: dict[tuple[str, str, str, str], PrivateManagerAdapter] = {}

    async def __call__(self, identity: SemanticRequestIdentity) -> PrivateManagerAdapter:
        owner = _owner(identity)
        if owner not in self.sinks:
            self.sinks[owner] = PrivateManagerAdapter(f"scope-{len(self.sinks)}", owner)
        return self.sinks[owner]


def _toolkit(
    models_dir: Path,
    warehouse: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    guard: _Guard,
    factory: Any = None,
    allow_raw_sql: bool = False,
) -> SemanticLayerToolkit:
    monkeypatch.setattr(pbac.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setenv("PARROT_SEMANTIC_CONN_SEMANTIC_TEST_DATABASE", str(warehouse))
    (models_dir / "orders.policy.yaml").write_text(_POLICY, encoding="utf-8")
    return SemanticLayerToolkit(
        models_dir=models_dir,
        dialect="duckdb",
        dataplane_guard=guard,
        dataset_manager_factory=factory,
        allow_raw_sql=allow_raw_sql,
    )


def _tool_names(toolkit: SemanticLayerToolkit) -> set[str]:
    return set(toolkit.list_tool_names())


async def _query(toolkit: SemanticLayerToolkit) -> str:
    result = await toolkit.query_metrics(SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]))
    assert result.result_id
    return result.result_id


@pytest.mark.asyncio
async def test_raw_sql_opt_in_and_same_governance(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_sql is absent by default and, when enabled, governed, audited and provenance-exact."""
    guard = _Guard()
    default = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=guard)
    assert "sl_run_sql" not in _tool_names(default)
    async with bind_semantic_context(_ctx()):
        with pytest.raises(SemanticAccessError) as disabled:
            await default.run_sql("orders", "SELECT region FROM sales.orders")
    assert disabled.value.code == "raw_sql_disabled"

    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=guard, allow_raw_sql=True)
    assert "sl_run_sql" in _tool_names(toolkit)
    with pytest.raises(SemanticAccessError):
        await toolkit.run_sql("orders", "SELECT region FROM sales.orders")

    ctx = _ctx()
    async with bind_semantic_context(ctx, identity=_identity(ctx)):
        result = await toolkit.run_sql(
            "orders", "SELECT region, SUM(amount) AS total FROM sales.orders GROUP BY region"
        )
        # RLS is pushed down exactly as for structured queries.
        assert result.rows == [{"region": "eu", "total": 12.5}]
        # issue:22fbd14d96a9 — the caller sees its own SQL; governed SQL only in the audit.
        assert "'eu'" not in result.compiled_sql
        audited = {entry.entry_id: entry for entry in toolkit._ledger.entries}[result.audit_id]
        assert "'eu'" in audited.governed_sql
        # Hidden member order_date is not granted to analyst.
        with pytest.raises(SemanticAccessError) as hidden:
            await toolkit.run_sql("orders", "SELECT order_date FROM sales.orders")
        assert hidden.value.code == "member_not_granted"
        guard.deny = True
        with pytest.raises(SemanticAccessError) as denied:
            await toolkit.run_sql("orders", "SELECT region FROM sales.orders")
        assert denied.value.code == "pbac_denied"
        guard.deny = False

    entries = [entry for entry in toolkit._ledger.entries if entry.tool == "run_sql"]
    assert [entry.outcome for entry in entries] == ["ok", "denied", "denied"]
    assert all(entry.raw_sql for entry in entries)
    stored = toolkit._handles._data[result.result_id]
    assert stored.physical_tables == ("sales.orders",)
    assert stored.physical_columns == ("sales.orders.amount", "sales.orders.region")
    assert stored.members == ("region", "revenue")
    assert stored.audit_id == result.audit_id


@pytest.mark.asyncio
async def test_handoff_publishes_through_guarded_sink(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A claimed owned result is published with a read authorizer; missing factory hides the tool."""
    guard = _Guard()
    absent = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=guard)
    assert "sl_save_result_as_dataset" not in _tool_names(absent)
    ctx = _ctx()
    identity = _identity(ctx)
    async with bind_semantic_context(ctx, identity=identity):
        with pytest.raises(SemanticResultError) as unavailable:
            await absent.save_result_as_dataset(await _query(absent), "orders_eu")
    assert unavailable.value.code == "handoff_unavailable"

    factory = _Factory()
    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=guard, factory=factory)
    assert "sl_save_result_as_dataset" in _tool_names(toolkit)
    async with bind_semantic_context(ctx, identity=identity):
        result_id = await _query(toolkit)
        published = await toolkit.save_result_as_dataset(result_id, "orders_eu", "EU revenue")
    assert published["name"] == "orders_eu" and published["rows"] == 1
    assert published["audit_id"]
    sink = factory.sinks[_owner(identity)]
    assert (await sink.route("sample", "orders_eu", identity))["rows"] == [{"region": "eu", "revenue": 12.5}]
    with pytest.raises(SemanticResultError):
        await sink.route("query", "orders_eu", _identity(_ctx(user="intruder")))
    with pytest.raises(SemanticResultError):
        await sink.route("query", "orders_eu", _identity(ctx, session="session-2"))
    assert toolkit._ledger.entries[-1].tool == "save_result_as_dataset"
    assert toolkit._ledger.entries[-1].outcome == "ok"

    # A foreign session or a different subject cannot claim the handle.
    other_session = _identity(ctx, session="session-2")
    async with bind_semantic_context(ctx, identity=other_session):
        with pytest.raises(SemanticResultError):
            await toolkit.save_result_as_dataset(result_id, "stolen")
    other_ctx = _ctx(program="us")
    async with bind_semantic_context(other_ctx, identity=_identity(other_ctx)):
        with pytest.raises(SemanticResultError):
            await toolkit.save_result_as_dataset(result_id, "stolen")
    # Without a bound identity, hand-off is refused.
    async with bind_semantic_context(ctx):
        with pytest.raises(SemanticResultError) as no_identity:
            await toolkit.save_result_as_dataset(result_id, "anon")
    assert no_identity.value.code == "identity_required"


@pytest.mark.asyncio
async def test_unrelated_visible_member_does_not_authorize_handle(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A handle carrying one hidden member is refused although its other members are visible."""
    factory = _Factory()
    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=_Guard(), factory=factory)
    ctx = _ctx()
    identity = _identity(ctx)
    loaded = toolkit._models["orders"]
    handle = ResultHandle(
        result_id="seed",
        agent_id=identity.agent_id,
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        session_id=identity.session_id,
        subject_digest=subject_digest(ctx),
        model="orders",
        model_digest=loaded.model_digest,
        policy_digest=loaded.policy_digest,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        members=("order_date", "region", "revenue"),
        physical_columns=("sales.orders.amount", "sales.orders.order_date", "sales.orders.region"),
        physical_tables=("sales.orders",),
        columns=["region", "order_date", "revenue"],
        rows=[{"region": "eu", "order_date": "2026-01-01", "revenue": 12.5}],
        audit_id="audit-seed",
        governed_sql="SELECT region, order_date, SUM(amount) FROM sales.orders GROUP BY 1, 2",
    )
    result_id = toolkit._handles.put(handle)
    async with bind_semantic_context(ctx, identity=identity):
        with pytest.raises(SemanticAccessError) as hidden:
            await toolkit.save_result_as_dataset(result_id, "leak")
    assert hidden.value.code == "member_not_granted"
    assert factory.sinks == {}
    assert toolkit._ledger.entries[-1].outcome == "denied"


@pytest.mark.asyncio
async def test_shared_scope_and_raw_manager_rejected(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A factory sharing one sink across owners, or returning a raw manager, never receives data."""
    first_ctx, second_ctx = _ctx(user="first"), _ctx(user="second")
    first, second = _identity(first_ctx), _identity(second_ctx)
    shared = PrivateManagerAdapter("shared", _owner(first))

    async def shared_factory(identity: SemanticRequestIdentity) -> PrivateManagerAdapter:
        return shared

    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=_Guard(), factory=shared_factory)
    async with bind_semantic_context(first_ctx, identity=first):
        await toolkit.save_result_as_dataset(await _query(toolkit), "mine")
    async with bind_semantic_context(second_ctx, identity=second):
        with pytest.raises(SemanticResultError) as rejected:
            await toolkit.save_result_as_dataset(await _query(toolkit), "theirs")
    assert rejected.value.code == "sink_rejected"
    assert set(shared._items) == {"mine"}

    class DatasetManager:
        guarded_reads = True
        scope_id = "raw"

        def __init__(self, owner: tuple[str, str, str, str]) -> None:
            self.owner = owner
            self.items: list[Any] = []

        async def publish(self, name: str, handle: ResultHandle, authorize_read: Any) -> dict[str, Any]:
            self.items.append(handle)
            return {"name": name}

    raw = DatasetManager(_owner(first))

    async def raw_factory(identity: SemanticRequestIdentity) -> DatasetManager:
        return raw

    raw_toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=_Guard(), factory=raw_factory)
    async with bind_semantic_context(first_ctx, identity=first):
        with pytest.raises(SemanticResultError) as raw_rejected:
            await raw_toolkit.save_result_as_dataset(await _query(raw_toolkit), "raw")
    assert raw_rejected.value.code == "sink_rejected"
    assert raw.items == []


@pytest.mark.asyncio
async def test_guarded_sink_read_after_revocation(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changed PBAC, policy, metadata and expiry block publish and every later read."""
    guard = _Guard()
    factory = _Factory()
    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=guard, factory=factory)
    ctx = _ctx()
    identity = _identity(ctx)
    async with bind_semantic_context(ctx, identity=identity):
        published_id = await _query(toolkit)
        await toolkit.save_result_as_dataset(published_id, "orders_eu")
        pbac_id = await _query(toolkit)
        expiry_id = await _query(toolkit)
        policy_id = await _query(toolkit)
    sink = factory.sinks[_owner(identity)]
    await sink.route("query", "orders_eu", identity)

    # PBAC revocation: publish refused, and the already-published dataset is no longer readable.
    guard.deny = True
    async with bind_semantic_context(ctx, identity=identity):
        with pytest.raises(SemanticAccessError) as pbac_denied:
            await toolkit.save_result_as_dataset(pbac_id, "after_revocation")
    assert pbac_denied.value.code == "pbac_denied"
    for exposure in ("list", "describe", "cache", "derive"):
        with pytest.raises(SemanticResultError):
            await sink.route(exposure, "orders_eu", identity)
    guard.deny = False
    await sink.route("query", "orders_eu", identity)

    # Changed subject metadata: the handle no longer matches the subject digest.
    changed_ctx = _ctx(program="us")
    async with bind_semantic_context(changed_ctx, identity=_identity(changed_ctx)):
        with pytest.raises(SemanticResultError):
            await toolkit.save_result_as_dataset(pbac_id, "changed_subject")
    with pytest.raises(SemanticResultError):
        await sink.route("query", "orders_eu", _identity(changed_ctx))

    # Expiry: an expired handle cannot be claimed.
    toolkit._handles._clock = lambda: datetime.now(timezone.utc) + timedelta(days=1)
    async with bind_semantic_context(ctx, identity=identity):
        with pytest.raises(SemanticResultError) as expired:
            await toolkit.save_result_as_dataset(expiry_id, "expired")
    assert expired.value.code == "result_unavailable"
    toolkit._handles._clock = lambda: datetime.now(timezone.utc)

    # Policy change + reload: the handle is stale and the published dataset is denied.
    (models_dir / "orders.policy.yaml").write_text(_POLICY.replace('usage: "*"}\n  admin', "usage: []}\n  admin"))
    toolkit.reload()
    async with bind_semantic_context(ctx, identity=identity):
        with pytest.raises(SemanticResultError):
            await toolkit.save_result_as_dataset(policy_id, "stale_policy")
    with pytest.raises(SemanticResultError):
        await sink.route("query", "orders_eu", identity)
    assert [entry.outcome for entry in toolkit._ledger.entries if entry.tool == "save_result_as_dataset"] == [
        "ok",
        "denied",
        # Claim failures (changed subject, expiry, stale policy) are audited too.
        "denied",
        "denied",
        "denied",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT tenant_id, id, customer_id FROM sales.orders",
        "SELECT region, tenant_id FROM sales.orders",
    ],
)
async def test_raw_sql_rejects_non_member_projection(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch, sql: str
) -> None:
    """Projected physical columns backing no granted member are denied even with usage '*'."""
    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=_Guard(), allow_raw_sql=True)
    ctx = _ctx()
    async with bind_semantic_context(ctx, identity=_identity(ctx)):
        with pytest.raises(SemanticAccessError) as denied:
            await toolkit.run_sql("orders", sql)
    assert denied.value.code == "member_not_granted"
    assert toolkit._ledger.entries[-1].outcome == "denied"
    assert toolkit._handles._data == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT salary, email FROM dim.customers",
        "SELECT o.region, c.email FROM sales.orders o JOIN dim.customers c ON o.customer_id = c.id",
    ],
)
async def test_raw_sql_rejects_cross_model_tables(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch, sql: str
) -> None:
    """Tables of other models are never reachable through the root model's raw SQL."""
    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=_Guard(), allow_raw_sql=True)
    ctx = _ctx()
    async with bind_semantic_context(ctx, identity=_identity(ctx)):
        with pytest.raises(SemanticAccessError):
            await toolkit.run_sql("orders", sql)
    assert toolkit._ledger.entries[-1].outcome == "denied"


@pytest.mark.asyncio
async def test_fresh_sink_per_call_same_owner(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host factory re-creating an equivalent sink per call keeps working for the same owner."""
    created: list[PrivateManagerAdapter] = []

    async def fresh_factory(identity: SemanticRequestIdentity) -> PrivateManagerAdapter:
        sink = PrivateManagerAdapter("scope-fresh", _owner(identity))
        created.append(sink)
        return sink

    toolkit = _toolkit(models_dir, duckdb_warehouse, monkeypatch, guard=_Guard(), factory=fresh_factory)
    ctx = _ctx()
    async with bind_semantic_context(ctx, identity=_identity(ctx)):
        first = await toolkit.save_result_as_dataset(await _query(toolkit), "one")
        second = await toolkit.save_result_as_dataset(await _query(toolkit), "two")
    assert first["name"] == "one" and second["name"] == "two"
    assert len(created) == 2 and created[0] is not created[1]
    assert toolkit._sinks.is_registered(created[1])
    assert not toolkit._sinks.is_registered(created[0])

    # The same scope re-created for a DIFFERENT owner is still rejected.
    other_ctx = _ctx(user="other")
    other = _identity(other_ctx)
    with pytest.raises(SemanticResultError) as rejected:
        toolkit._sinks.register(PrivateManagerAdapter("scope-fresh", _owner(other)))
    assert rejected.value.code == "sink_rejected"


def test_sink_registry_is_bounded() -> None:
    """The registry evicts the oldest scope beyond its bound."""
    from parrot.semantic.handoff import GovernedSinkRegistry

    registry = GovernedSinkRegistry(max_entries=2)
    sinks = [PrivateManagerAdapter(f"s{i}", ("a", f"u{i}", "t", "s")) for i in range(3)]
    for sink in sinks:
        registry.register(sink)
    assert not registry.is_registered(sinks[0])
    assert registry.is_registered(sinks[1]) and registry.is_registered(sinks[2])


@pytest.mark.asyncio
async def test_unexpected_failures_are_audited_and_wrapped(
    models_dir: Path, duckdb_warehouse: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-semantic failures write an execution_error audit and surface as an opaque SemanticError."""
    from parrot.semantic.errors import SemanticError

    toolkit = _toolkit(
        models_dir, duckdb_warehouse, monkeypatch, guard=_Guard(), allow_raw_sql=True, factory=_Factory()
    )
    ctx = _ctx()

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("driver exploded: secret detail")

    async with bind_semantic_context(ctx, identity=_identity(ctx)):
        result_id = await _query(toolkit)
        monkeypatch.setattr(toolkit._executor, "run_with_columns", boom)
        with pytest.raises(SemanticError) as structured:
            await toolkit.query_metrics(SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]))
        assert structured.value.code == "internal_error"
        assert "secret" not in str(structured.value)
        assert toolkit._ledger.entries[-1].outcome == "execution_error"

        with pytest.raises(SemanticError) as raw:
            await toolkit.run_sql("orders", "SELECT region FROM sales.orders")
        assert raw.value.code == "internal_error"
        last = toolkit._ledger.entries[-1]
        assert (last.tool, last.outcome) == ("run_sql", "execution_error")

        async def broken_sink(identity: SemanticRequestIdentity) -> Any:
            raise RuntimeError("factory down")

        monkeypatch.setattr(toolkit, "_sink_factory", broken_sink)
        with pytest.raises(SemanticError) as handoff:
            await toolkit.save_result_as_dataset(result_id, "x")
        assert handoff.value.code == "internal_error"
        last = toolkit._ledger.entries[-1]
        assert (last.tool, last.outcome) == ("save_result_as_dataset", "execution_error")

        with pytest.raises(SemanticResultError):
            await toolkit.save_result_as_dataset("no-such-handle", "y")
        last = toolkit._ledger.entries[-1]
        assert (last.tool, last.outcome, last.error_code) == ("save_result_as_dataset", "denied", "result_unavailable")
