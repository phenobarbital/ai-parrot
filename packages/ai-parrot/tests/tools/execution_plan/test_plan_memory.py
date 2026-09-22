"""Plan-memory activation and raw-read ceiling tests (FEAT-585 M2)."""

from __future__ import annotations

import pytest

from parrot.tools.execution_plan.memory import PlanMemoryBinding
from parrot.tools.working_memory.models import EnabledGetResultInput, GetResultInput
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig, TaskMemoryRuntime
from parrot.tools.working_memory.task_memory.models import TaskScope
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

pytestmark = pytest.mark.asyncio


async def test_activation_keeps_existing_entries_and_is_idempotent() -> None:
    """Activation migrates legacy entries and reuses its task-memory root."""
    toolkit = WorkingMemoryToolkit(session_id="plan-session")
    toolkit._catalog.put_generic("result", {"answer": 42})
    binding = PlanMemoryBinding(toolkit, runtime=None, scope=None, max_restore_bytes=64 * 1024 * 1024)

    task_memory = await binding.prepare()

    assert toolkit.get_result("result")["key"] == "result"
    assert task_memory.config.enabled is True
    assert await binding.prepare() is task_memory
    await binding.close()


async def test_activation_failure_preserves_legacy_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed versioned migration does not alter the legacy binding."""
    toolkit = WorkingMemoryToolkit()
    toolkit._catalog.put_generic("result", {"answer": 42})
    original_catalog = toolkit._catalog
    binding = PlanMemoryBinding(toolkit, runtime=None, scope=None, max_restore_bytes=64 * 1024 * 1024)

    async def fail_put(*args, **kwargs):
        """Refuse the one migration write."""
        raise RuntimeError("backend put failed")

    monkeypatch.setattr("parrot.tools.working_memory.task_memory.artifacts.InMemoryArtifactStore.put", fail_put)
    with pytest.raises(RuntimeError, match="backend put failed"):
        await binding.prepare()

    assert toolkit._catalog is original_catalog
    assert toolkit._task_memory is None
    await binding.close()


async def test_pre_registered_wrapper_gets_enabled_schema() -> None:
    """Activation changes an existing result wrapper schema in place."""
    toolkit = WorkingMemoryToolkit()
    wrapper = toolkit.get_tool("wm_get_result")
    assert wrapper is not None
    binding = PlanMemoryBinding(toolkit, runtime=None, scope=None, max_restore_bytes=64 * 1024 * 1024)

    await binding.prepare()

    assert wrapper.args_schema is EnabledGetResultInput
    await binding.close()


async def test_standalone_toolkit_unchanged() -> None:
    """A toolkit that was never prepared retains the legacy result schema."""
    toolkit = WorkingMemoryToolkit()

    assert toolkit.get_tool("wm_get_result").args_schema is GetResultInput


async def test_read_ceiling_clamps_and_zero_disables() -> None:
    """Enabled plan memory keeps the shipped hard rehydration ceiling."""
    toolkit = WorkingMemoryToolkit()
    binding = PlanMemoryBinding(toolkit, runtime=None, scope=None, max_restore_bytes=64 * 1024 * 1024)
    await binding.prepare()
    await toolkit.store_result("large", {"blob": "x" * 40_000_000})

    clamped = await toolkit.get_result("large", include_raw=True, max_rehydrate_bytes=40_000_000)
    disabled = await toolkit.get_result("large", include_raw=True, max_rehydrate_bytes=0)

    assert "raw_omitted" in clamped
    assert clamped["raw_policy"]["max_rehydrate_bytes"] == 2_000_000
    assert "raw_omitted" in disabled
    assert disabled["raw_policy"]["max_rehydrate_bytes"] == 0
    await binding.close()


async def test_host_runtime_requires_scope_and_is_borrowed() -> None:
    """Host runtime needs a trusted scope and remains open after binding close."""
    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=False))
    with pytest.raises(ValueError, match="trusted TaskScope"):
        PlanMemoryBinding(WorkingMemoryToolkit(), runtime=runtime, scope=None, max_restore_bytes=64 * 1024 * 1024)

    await runtime.start(start_scheduler=False)
    scope = TaskScope(chatbot_id="execution-plan", user_id="host-user", session_id="host-session")
    binding = PlanMemoryBinding(WorkingMemoryToolkit(), runtime=runtime, scope=scope, max_restore_bytes=64 * 1024 * 1024)
    await binding.prepare()
    await binding.close()

    assert runtime.is_running
    await runtime.stop()
