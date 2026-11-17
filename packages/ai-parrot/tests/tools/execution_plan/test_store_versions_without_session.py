"""FEAT-789 — plan-node writes keep their exact version without a turn session."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from parrot.bots.flows.plan.models import PlanNode
from parrot.bots.flows.plan.node import PlanToolNode, _current_session
from parrot.tools.execution_plan.memory import PlanMemoryBinding, RestoreError
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig, TaskMemoryRuntime
from parrot.tools.working_memory.task_memory.models import TaskScope
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

pytestmark = pytest.mark.asyncio


class _ToolManager:
    """Return a fixed payload for every dispatch."""

    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional[Any] = None
    ) -> Any:
        """Return the canned payload."""
        return {"tool": tool_name, "v": 1}


class _Ctx:
    """Minimal flow context."""

    def __init__(self) -> None:
        """No upstream results."""
        self.results: Dict[str, Any] = {}
        self.initial_task = ""


def _node(memory: WorkingMemoryToolkit) -> PlanToolNode:
    """Build a single-call plan node writing to ``memory``."""
    return PlanToolNode(
        node_id="b",
        plan_node=PlanNode(id="b", tool="b", store_as="b_out"),
        tool_manager=_ToolManager(),
        working_memory=memory,
    )


async def test_enabled_catalog_without_session_records_version() -> None:
    """A background plan write still yields an exact, restorable version."""
    memory = WorkingMemoryToolkit()
    binding = PlanMemoryBinding(memory, runtime=None, scope=None, max_restore_bytes=1_000_000)
    await binding.prepare()
    try:
        assert memory._catalog.is_enabled
        assert _current_session() is None

        ref = await _node(memory).execute(_Ctx())

        assert ref.status == "ok"
        assert len(ref.versions) == 1
        entry = await memory._catalog.aget("b_out")
        meta = entry.version_metadata
        assert ref.versions[0] == f"{meta.artifact_id}@{meta.version}"
        assert entry.data == {"tool": "b", "v": 1}
    finally:
        await binding.close()


async def test_disabled_catalog_keeps_legacy_unversioned_write() -> None:
    """Without task memory the write path and empty versions are unchanged."""
    memory = WorkingMemoryToolkit()
    assert not memory._catalog.is_enabled

    ref = await _node(memory).execute(_Ctx())

    assert ref.status == "ok"
    assert ref.versions == []
    assert memory._catalog.get("b_out").data == {"tool": "b", "v": 1}


async def _versioned_ref() -> Any:
    """Return a ref whose version lives only in another binding's private store."""
    memory = WorkingMemoryToolkit()
    binding = PlanMemoryBinding(memory, runtime=None, scope=None, max_restore_bytes=1_000_000)
    await binding.prepare()
    try:
        return await _node(memory).execute(_Ctx())
    finally:
        await binding.close()


async def test_process_private_restore_skips_unreadable_version() -> None:
    """A private store skips another binding's version and leaves no pin behind."""
    ref = await _versioned_ref()
    memory = WorkingMemoryToolkit()
    binding = PlanMemoryBinding(memory, runtime=None, scope=None, max_restore_bytes=1_000_000)
    await binding.prepare()
    try:
        await binding.restore([ref])
        assert "b_out" not in memory._catalog._pinned
    finally:
        await binding.close()


async def test_host_runtime_restore_refuses_unreadable_version() -> None:
    """A host-supplied runtime keeps refusing a version it cannot read."""
    ref = await _versioned_ref()
    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=False))
    await runtime.start(start_scheduler=False)
    try:
        binding = PlanMemoryBinding(
            WorkingMemoryToolkit(),
            runtime=runtime,
            scope=TaskScope(chatbot_id="execution-plan", user_id="host", session_id="s"),
            max_restore_bytes=1_000_000,
        )
        await binding.prepare()
        with pytest.raises(RestoreError) as caught:
            await binding.restore([ref])
        assert caught.value.code == "missing_or_expired"
    finally:
        await runtime.stop()
