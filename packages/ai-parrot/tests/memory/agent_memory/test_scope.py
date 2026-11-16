"""Behavioral acceptance tests for request-local memory scope binding."""

import asyncio

import pytest

from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.agent_memory.runtime import (
    bind_memory_exposure,
    bind_memory_scope,
    current_memory_exposure,
    current_memory_scope,
    reset_memory_exposure,
    reset_memory_scope,
)


def _scope(suffix: str) -> MemoryRequestScope:
    """Build a distinct, trusted request identity for an isolated assertion."""
    return MemoryRequestScope(
        tenant_id=f"tenant-{suffix}",
        agent_id=f"agent-{suffix}",
        user_id=f"user-{suffix}",
        session_id=f"session-{suffix}",
        room_id=f"room-{suffix}",
        turn_id=f"turn-{suffix}",
        identity_provenance="runtime_derived",
    )


@pytest.mark.asyncio
async def test_parallel_principals_are_isolated() -> None:
    """Verify concurrent principals retain only their own scope and exposure."""
    first = _scope("first")
    second = _scope("second")

    async def resolve(scope: MemoryRequestScope, exposure_id: str) -> tuple[MemoryRequestScope | None, str | None]:
        """Bind one request after both tasks begin execution."""
        scope_token = bind_memory_scope(scope)
        exposure_token = bind_memory_exposure(exposure_id)
        try:
            await asyncio.sleep(0)
            return current_memory_scope(), current_memory_exposure()
        finally:
            reset_memory_exposure(exposure_token)
            reset_memory_scope(scope_token)

    first_result, second_result = await asyncio.gather(
        resolve(first, "exposure-first"),
        resolve(second, "exposure-second"),
    )

    assert first_result == (first, "exposure-first")
    assert second_result == (second, "exposure-second")
    assert current_memory_scope() is None
    assert current_memory_exposure() is None


def test_nested_token_restores_outer_scope() -> None:
    """Verify nested cleanup after an exception restores the outer bindings."""
    outer = _scope("outer")
    inner = _scope("inner")
    outer_scope_token = bind_memory_scope(outer)
    outer_exposure_token = bind_memory_exposure("outer-delivery")
    try:
        with pytest.raises(RuntimeError, match="nested failure"):
            inner_scope_token = bind_memory_scope(inner)
            inner_exposure_token = bind_memory_exposure(None)
            try:
                assert current_memory_scope() == inner
                assert current_memory_exposure() is None
                raise RuntimeError("nested failure")
            finally:
                reset_memory_exposure(inner_exposure_token)
                reset_memory_scope(inner_scope_token)

        assert current_memory_scope() == outer
        assert current_memory_exposure() == "outer-delivery"
    finally:
        reset_memory_exposure(outer_exposure_token)
        reset_memory_scope(outer_scope_token)

    assert current_memory_scope() is None
    assert current_memory_exposure() is None


@pytest.mark.asyncio
async def test_cancellation_and_clone_do_not_leak() -> None:
    """Verify cancellation restores a cloned task context without leaking child bindings."""
    parent = _scope("parent")
    child = _scope("child")
    parent_scope_token = bind_memory_scope(parent)
    parent_exposure_token = bind_memory_exposure("parent-delivery")
    entered = asyncio.Event()
    restored_contexts: list[tuple[MemoryRequestScope | None, str | None]] = []

    async def cloned_invocation() -> None:
        """Rebind the inherited task context and always restore it when cancelled."""
        child_scope_token = bind_memory_scope(child)
        child_exposure_token = bind_memory_exposure(None)
        try:
            assert current_memory_scope() == child
            assert current_memory_exposure() is None
            entered.set()
            await asyncio.Event().wait()
        finally:
            reset_memory_exposure(child_exposure_token)
            reset_memory_scope(child_scope_token)
            restored_contexts.append((current_memory_scope(), current_memory_exposure()))

    try:
        task = asyncio.create_task(cloned_invocation())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert restored_contexts == [(parent, "parent-delivery")]
        assert current_memory_scope() == parent
        assert current_memory_exposure() == "parent-delivery"
    finally:
        reset_memory_exposure(parent_exposure_token)
        reset_memory_scope(parent_scope_token)

    assert current_memory_scope() is None
    assert current_memory_exposure() is None


def test_memory_context_resets_tolerate_a_token_from_another_context() -> None:
    """Closing an async generator from another Context must not raise out of a finally that still has cleanup to run."""
    import contextvars

    from parrot.memory.agent_memory.runtime import (
        bind_memory_exposure,
        bind_memory_scope,
        current_memory_exposure,
        current_memory_scope,
        reset_memory_exposure,
        reset_memory_scope,
    )

    scope = MemoryRequestScope(
        tenant_id="tenant-a", agent_id="agent-a", turn_id="turn-1", identity_provenance="runtime_derived"
    )
    other = contextvars.copy_context()
    scope_token = other.run(bind_memory_scope, scope)
    exposure_token = other.run(bind_memory_exposure, "exposure-1")

    reset_memory_scope(scope_token)
    reset_memory_exposure(exposure_token)

    assert current_memory_scope() is None
    assert current_memory_exposure() is None
