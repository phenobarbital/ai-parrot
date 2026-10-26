"""Regression contract: Guarded dataset sink and read-time authorization (M9H)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.auth import PermissionContext, UserSession
from parrot.semantic.context import SemanticRequestIdentity
from parrot.semantic.errors import SemanticResultError
from parrot.semantic.governance.pipeline import subject_digest
from parrot.semantic.handoff import GovernedSinkRegistry, build_read_authorizer
from parrot.semantic.loader import PhysicalSchema
from parrot.semantic.results import ResultHandle

from .sink_conformance import PrivateManagerAdapter, assert_sink_conformance


def _identity(user: str = "user-1", session: str = "session-1", roles: frozenset[str] = frozenset({"analyst"})):
    ctx = PermissionContext(session=UserSession(user, "tenant-1", roles, {"region": "EU"}))
    return SemanticRequestIdentity(ctx=ctx, channel="agent", agent_id="agent-1", session_id=session)


def _handle(identity: SemanticRequestIdentity, *, ttl: timedelta = timedelta(hours=1)) -> ResultHandle:
    return ResultHandle(
        result_id="r1",
        agent_id=identity.agent_id,
        user_id=identity.ctx.user_id,
        tenant_id=identity.ctx.tenant_id,
        session_id=identity.session_id,
        subject_digest=subject_digest(identity.ctx),
        model="sales",
        model_digest="model-v1",
        policy_digest="policy-v1",
        expires_at=datetime.now(timezone.utc) + ttl,
        members=("revenue", "region"),
        physical_columns=("public.sales.amount",),
        physical_tables=("public.sales",),
        columns=["Revenue"],
        rows=[{"Revenue": 1}],
        audit_id="a1",
        governed_sql="SELECT amount FROM public.sales",
    )


def _loaded(model_digest: str = "model-v1", policy_digest: str = "policy-v1") -> Any:
    return SimpleNamespace(
        model_digest=model_digest,
        policy_digest=policy_digest,
        policy=SimpleNamespace(governed=True),
        schema=PhysicalSchema(driver="pg", tables={"public.sales": {"amount": "INT"}}),
    )


class _Catalog:
    def __init__(self, names: tuple[str, ...] = ("revenue", "region")) -> None:
        self.names = names

    def visible_members(self, model: str, roles: frozenset[str], *, authorized: bool) -> list[Any]:
        return [SimpleNamespace(name=name) for name in self.names]


class _Pbac:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.calls: list[Any] = []

    async def authorize(self, ctx: Any, resources: Any, *, governed: bool, manifest: Any = None) -> None:
        self.calls.append((ctx, resources))
        if self.fail:
            raise self.fail


def _build(handle: ResultHandle, state: dict[str, Any]) -> Any:
    return build_read_authorizer(
        handle,
        models=lambda: state["models"],
        catalog=lambda: state["catalog"],
        pbac=state["pbac"],
    )


def _state() -> dict[str, Any]:
    return {"models": {"sales": _loaded()}, "catalog": _Catalog(), "pbac": _Pbac()}


@pytest.mark.asyncio
async def test_exact_provenance_and_scope_rejection(tmp_path: Path) -> None:
    """Verify exact provenance and scope rejection."""
    assert tmp_path.is_dir()
    owner = _identity()
    state = _state()
    authorize = _build(_handle(owner), state)
    await authorize(owner)
    assert state["pbac"].calls[0][1].tables == {"pg:public.sales"}
    for foreign in (_identity(user="user-2"), _identity(session="session-2"), _identity(roles=frozenset({"x"}))):
        with pytest.raises(SemanticResultError):
            await authorize(foreign)

    # Sink registration: raw managers, flag-only objects, scope/owner reuse are all refused.
    registry = GovernedSinkRegistry()
    owner_tuple = ("agent-1", "user-1", "tenant-1", "session-1")
    sink = PrivateManagerAdapter("scope-1", owner_tuple)
    registry.register(sink)
    with pytest.raises(SemanticResultError):
        registry.register(PrivateManagerAdapter("scope-1", ("a", "b", "c", "d")))
    with pytest.raises(SemanticResultError):
        registry.register(PrivateManagerAdapter("scope-2", owner_tuple))

    class DatasetManager:
        guarded_reads = True
        scope_id = "scope-3"
        owner = ("a", "b", "c", "d")

        async def publish(self, *args: Any) -> dict[str, Any]:
            return {}

    with pytest.raises(SemanticResultError):
        registry.register(DatasetManager())  # type: ignore[arg-type]
    unregistered = PrivateManagerAdapter("scope-9", ("a", "b", "c", "d"))
    with pytest.raises(SemanticResultError):
        await registry.publish(unregistered, "n", _handle(owner), authorize, identity=owner)
    assert unregistered._items == {}
    # Owner mismatch is rejected before the sink is touched.
    other = _identity(user="user-2")
    with pytest.raises(SemanticResultError):
        await registry.publish(sink, "n", _handle(other), authorize, identity=other)
    assert sink._items == {}
    result = await registry.publish(sink, "n", _handle(owner), authorize, identity=owner)
    assert result["name"] == "n"


@pytest.mark.asyncio
async def test_every_exposure_revocation_and_expiry(tmp_path: Path) -> None:
    """Verify every exposure revocation and expiry."""
    assert tmp_path.is_dir()
    other = _identity(user="user-2")
    owner = _identity()

    async def factory() -> PrivateManagerAdapter:
        return PrivateManagerAdapter("scope-1", ("agent-1", "user-1", "tenant-1", "session-1"))

    await assert_sink_conformance(factory, (owner, other))

    state = _state()
    authorize = _build(_handle(owner), state)
    await authorize(owner)
    state["catalog"] = _Catalog(("revenue",))  # member revoked
    with pytest.raises(SemanticResultError):
        await authorize(owner)
    state["catalog"] = _Catalog()
    await authorize(owner)
    state["pbac"] = _Pbac(fail=RuntimeError("evaluator down"))
    with pytest.raises(SemanticResultError) as error:
        await _build(_handle(owner), state)(owner)
    assert error.value.code == "result_unavailable"
    expired = _build(_handle(owner, ttl=timedelta(seconds=-1)), _state())
    with pytest.raises(SemanticResultError):
        await expired(owner)


@pytest.mark.asyncio
async def test_cached_derived_inheritance_and_reload_race(tmp_path: Path) -> None:
    """Verify cached derived inheritance and reload race."""
    assert tmp_path.is_dir()
    owner = _identity()
    state = _state()
    authorize = _build(_handle(owner), state)
    await authorize(owner)
    state["models"] = {"sales": _loaded(model_digest="model-v2")}
    with pytest.raises(SemanticResultError):
        await authorize(owner)
    state["models"] = {"sales": _loaded(policy_digest="policy-v2")}
    with pytest.raises(SemanticResultError):
        await authorize(owner)
    state["models"] = {}
    with pytest.raises(SemanticResultError):
        await authorize(owner)

    # Reload race: the model changes while PBAC awaits.
    racing = _state()

    class _RacingPbac(_Pbac):
        async def authorize(self, ctx: Any, resources: Any, *, governed: bool, manifest: Any = None) -> None:
            racing["models"] = {"sales": _loaded(policy_digest="policy-v2")}

    racing["pbac"] = _RacingPbac()
    with pytest.raises(SemanticResultError):
        await _build(_handle(owner), racing)(owner)

    # Derived outputs inherit provenance and the earliest expiry (adapter-level).
    sink = PrivateManagerAdapter("s", ("agent-1", "user-1", "tenant-1", "session-1"))
    handle = _handle(owner)
    ok = _build(handle, _state())
    await sink.publish("d", handle, ok)
    derived = await sink.route("derive", "d", owner)
    assert derived["expires_at"] == handle.expires_at
    assert derived["provenance"] == (handle.model, handle.model_digest, handle.policy_digest)
