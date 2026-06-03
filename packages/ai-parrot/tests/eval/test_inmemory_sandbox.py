"""Unit tests for InMemoryStateSandbox + InMemoryStateSandboxProvider (TASK-1419)."""
import pytest

from parrot.eval import (
    DatabaseToolkitBinder,
    DictStateBackend,
    InMemoryStateSandbox,
    InMemoryStateSandboxProvider,
)
from parrot.eval.sandbox.base import SandboxSpec


async def test_sandbox_delegates_to_backend():
    """reset/snapshot/health_check delegate to the backend correctly."""
    sb = InMemoryStateSandbox(DictStateBackend(), DatabaseToolkitBinder())
    await sb.reset({"t": {"1": {"v": 1}}})
    snap = await sb.snapshot()
    assert snap["t"]["1"]["v"] == 1
    assert await sb.health_check() is True


async def test_sandbox_exec_raises():
    """exec() always raises NotImplementedError."""
    sb = InMemoryStateSandbox(DictStateBackend(), DatabaseToolkitBinder())
    async with sb:
        with pytest.raises(NotImplementedError):
            await sb.exec(["ls"])


async def test_sandbox_context_manager():
    """InMemoryStateSandbox works as an async context manager."""
    sb = InMemoryStateSandbox(DictStateBackend(), DatabaseToolkitBinder())
    async with sb as s:
        await s.reset({"col": {"e1": {"x": 1}}})
        snap = await s.snapshot()
    assert snap["col"]["e1"]["x"] == 1


async def test_provider_fresh_backends():
    """Two acquires from the same provider give independent backends."""
    provider = InMemoryStateSandboxProvider(binder=DatabaseToolkitBinder())
    spec = SandboxSpec(kind="in_memory_state")

    sb1 = await provider.acquire(spec)
    sb2 = await provider.acquire(spec)

    await sb1.reset({"t": {"e1": {"v": 1}}})
    await sb2.reset({"t": {"e1": {"v": 99}}})

    snap1 = await sb1.snapshot()
    snap2 = await sb2.snapshot()
    assert snap1["t"]["e1"]["v"] == 1
    assert snap2["t"]["e1"]["v"] == 99

    await provider.release(sb1)
    await provider.release(sb2)


async def test_sandbox_reset_replaces_state():
    """Calling reset() replaces the previous state entirely."""
    sb = InMemoryStateSandbox(DictStateBackend(), DatabaseToolkitBinder())
    await sb.reset({"a": {"e1": {"x": 1}}})
    await sb.reset({"b": {"e2": {"y": 2}}})
    snap = await sb.snapshot()
    assert "a" not in snap
    assert snap["b"]["e2"]["y"] == 2
