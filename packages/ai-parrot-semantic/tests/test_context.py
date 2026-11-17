"""Regression contract: Scoped identity binding and exception-safe cleanup (M10 context)."""

import asyncio
from pathlib import Path

import pytest
from parrot.auth import PermissionContext
from parrot.auth.context import _pctx_var
from parrot.auth.permission import UserSession
from parrot.semantic.context import (
    SemanticRequestIdentity,
    bind_semantic_context,
    current_identity,
    current_pctx,
    require_identity,
)
from parrot.semantic.errors import SemanticAccessError, SemanticResultError


def _ctx(user: str, tenant: str = "t1", roles: frozenset[str] = frozenset({"r"}), **meta: str) -> PermissionContext:
    return PermissionContext(
        session=UserSession(user_id=user, tenant_id=tenant, roles=roles, metadata=dict(meta)),
        request_id=f"req-{user}",
    )


def _identity(ctx: PermissionContext) -> SemanticRequestIdentity:
    return SemanticRequestIdentity(ctx=ctx, channel="agent", agent_id="agent-1", session_id="sess-1")


def _unbound() -> bool:
    return current_pctx() is None and current_identity() is None and _pctx_var.get() is None


@pytest.mark.asyncio
async def test_trusted_scope_and_context_only_calls(tmp_path: Path) -> None:
    """Verify trusted scope and context only calls."""
    ctx = _ctx("alice", groups="g1")
    async with bind_semantic_context(ctx):
        assert current_pctx().user_id == "alice"
        assert _pctx_var.get() is current_pctx()
        assert current_identity() is None
        with pytest.raises(SemanticResultError):
            require_identity()
    assert _unbound()

    identity = _identity(ctx)
    async with bind_semantic_context(ctx, identity=identity):
        assert require_identity() is identity
        assert require_identity().session_id == "sess-1"
    assert _unbound()

    for other in (
        _ctx("bob", groups="g1"),
        _ctx("alice", tenant="t2", groups="g1"),
        _ctx("alice", roles=frozenset({"x"}), groups="g1"),
        _ctx("alice", groups="g2"),
    ):
        with pytest.raises(SemanticAccessError):
            async with bind_semantic_context(other, identity=identity):
                pass
        assert _unbound()

    # The bound context is a copy: later caller mutation cannot alter it.
    async with bind_semantic_context(ctx):
        ctx.extra["injected"] = "x"
        assert "injected" not in current_pctx().extra
    with pytest.raises(SemanticResultError):
        require_identity()


@pytest.mark.asyncio
async def test_concurrent_nested_isolation(tmp_path: Path) -> None:
    """Verify concurrent nested isolation."""
    seen: dict[str, tuple[str, str]] = {}

    async def call(user: str) -> None:
        ctx = _ctx(user)
        async with bind_semantic_context(ctx, identity=_identity(ctx)):
            await asyncio.sleep(0.01)
            seen[user] = (current_pctx().user_id, require_identity().ctx.user_id)

    await asyncio.gather(call("alice"), call("bob"))
    assert seen == {"alice": ("alice", "alice"), "bob": ("bob", "bob")}

    outer = _ctx("alice")
    async with bind_semantic_context(outer, identity=_identity(outer)):
        async with bind_semantic_context(_ctx("bob")):
            assert current_pctx().user_id == "bob"
            assert current_identity() is None
        assert current_pctx().user_id == "alice"
        assert require_identity().ctx.user_id == "alice"
    assert _unbound()


@pytest.mark.asyncio
async def test_error_cancellation_and_token_reset(tmp_path: Path) -> None:
    """Verify error cancellation and token reset."""
    ctx = _ctx("alice")
    with pytest.raises(RuntimeError):
        async with bind_semantic_context(ctx, identity=_identity(ctx)):
            raise RuntimeError("boom")
    assert _unbound()

    entered = asyncio.Event()
    observed: list[bool] = []

    async def worker() -> None:
        try:
            async with bind_semantic_context(ctx, identity=_identity(ctx)):
                entered.set()
                await asyncio.sleep(10)
        finally:
            observed.append(_unbound())

    task = asyncio.create_task(worker())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert observed == [True]
    assert _unbound()

    with pytest.raises(SemanticAccessError):
        async with bind_semantic_context(None):  # type: ignore[arg-type]
            pass
    assert _unbound()
