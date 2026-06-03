"""Unit tests for parrot.eval.sandbox.base (TASK-1417)."""
import pytest

from parrot.eval import EvalTask, NoopSandbox, SandboxSpec
from parrot.eval.sandbox.base import NoopSandboxProvider


async def test_noop_sandbox_lifecycle():
    """NoopSandbox works as async context manager with all lifecycle methods."""
    prov = NoopSandboxProvider()
    sb = await prov.acquire(SandboxSpec(kind="noop"))
    async with sb:
        await sb.reset(None)
        assert await sb.health_check() is True
        assert await sb.snapshot() == {}
        with pytest.raises(NotImplementedError):
            await sb.exec(["echo", "hi"])
    await prov.release(sb)


async def test_sandbox_spec_defaults():
    """SandboxSpec defaults to kind='noop' with no image or seed state."""
    spec = SandboxSpec()
    assert spec.kind == "noop"
    assert spec.image is None
    assert spec.seed_state is None
    assert spec.setup == []


async def test_eval_task_with_sandbox_spec():
    """EvalTask.sandbox_spec accepts a SandboxSpec after model_rebuild()."""
    t = EvalTask(
        task_id="t1",
        inputs={"q": "hi"},
        sandbox_spec=SandboxSpec(kind="in_memory_state", seed_state={"k": "v"}),
    )
    assert t.sandbox_spec is not None
    assert t.sandbox_spec.kind == "in_memory_state"


async def test_noop_sandbox_reset_idempotent():
    """NoopSandbox.reset() is a no-op regardless of seed_state."""
    sb = NoopSandbox()
    async with sb:
        await sb.reset({"x": 1})
        assert await sb.snapshot() == {}
        await sb.reset(None)
        assert await sb.snapshot() == {}


async def test_noop_sandbox_health_always_true():
    """NoopSandbox.health_check() always returns True."""
    sb = NoopSandbox()
    async with sb:
        assert await sb.health_check() is True
