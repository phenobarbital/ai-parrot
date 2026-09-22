"""FEAT-585 M7 — recovery across simulated process boundaries."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

import pytest

from parrot.bots.flows.plan import ExecutionPlan, ForEach, PlanNode
from parrot.tools.execution_plan import ExecutionPlanToolkit, PlanRecoveryConfig
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig, TaskMemoryRuntime
from parrot.tools.working_memory.task_memory.models import TaskScope
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

from ._recovery_fakes import CountingToolManager, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio

SCOPE = TaskScope(chatbot_id="execution-plan", user_id="host-user", session_id="host-session")
FAST = PlanRecoveryConfig(checkpoint_probe_timeout=0.2)
DSN_ENV = "TASK_MEMORY_TEST_DSN"
_PG_SKIP = f"{DSN_ENV} is not set. Durable recovery requires a real PostgreSQL; this case is SKIPPED, not passed."


def _chain_plan() -> ExecutionPlan:
    """Return the deterministic A-to-B-to-C recovery plan."""
    return ExecutionPlan(
        name="chain",
        objective="A→B→C",
        nodes=[
            PlanNode(id="a", tool="a", store_as="a_out"),
            PlanNode(id="b", tool="b", store_as="b_out", depends_on=["a"], args={"prev": "{nodes.a.output}"}),
            PlanNode(id="c", tool="c", store_as="c_out", depends_on=["b"], args={"prev": "{artifacts.b}"}),
        ],
    )


class Process:
    """Objects which die at a process boundary; only checkpoint bytes survive."""

    def __init__(
        self,
        store_bytes: Optional[Dict[str, Dict[int, bytes]]] = None,
        *,
        runtime: Optional[TaskMemoryRuntime] = None,
        scope: Optional[TaskScope] = None,
        durable: bool = False,
        gates: Optional[Dict[str, asyncio.Event]] = None,
    ) -> None:
        """Build a fresh execution process around optionally recovered bytes."""
        self.store = SerializingFakeCheckpointStore(durable=durable)
        if store_bytes is not None:
            self.store._bytes = {key: dict(value) for key, value in store_bytes.items()}
        self.manager = CountingToolManager({"a": {"v": 1}, "b": {"v": 2}, "c": {"v": 3}}, gates=gates)
        self.memory = WorkingMemoryToolkit()
        self.toolkit = ExecutionPlanToolkit(
            tool_manager=self.manager,
            working_memory=self.memory,
            soft_timeout=0.05,
            recovery=FAST,
            checkpoint_store=self.store,
            durable_store=self.store if durable else None,
            task_memory_runtime=runtime,
            scope=scope,
        )


async def _run_until_b_checkpointed(proc: Process) -> str:
    """Interrupt a chain only after B is recorded in a checkpoint."""
    result = await proc.toolkit._run_plan(_chain_plan(), source="plan_name")
    run_id = result.result["run_id"]
    for _ in range(200):
        checkpoint = await proc.store.latest(run_id)
        if checkpoint is not None and "b" in checkpoint.context.completion_order:
            task = proc.toolkit._run_tasks[run_id]
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return run_id
        await asyncio.sleep(0)
    raise AssertionError("B was not checkpointed before the bounded interruption")


async def _wait_for_terminal(toolkit: ExecutionPlanToolkit, run_id: str) -> Dict[str, Any]:
    """Await the background task and return its terminal status payload."""
    task = toolkit._run_tasks[run_id]
    await task
    status = await toolkit.plan_status(run_id)
    return status.result


async def test_fresh_process_recovery_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rebuilt host runtime resumes only C, while cross-process memory refuses."""
    gate_c = asyncio.Event()
    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=False))
    await runtime.start(start_scheduler=False)
    try:
        original = Process(runtime=runtime, scope=SCOPE, durable=True, gates={"c": gate_c})
        run_id = await _run_until_b_checkpointed(original)
        bytes_before = {key: dict(value) for key, value in original.store._bytes.items()}
        original_identity = original.toolkit._plan_runs[run_id].metadata.process_id
        resumed = Process(bytes_before, runtime=runtime, scope=SCOPE, durable=True)
        monkeypatch.setattr("parrot.tools.execution_plan.runs.process_identity", lambda: "different-process")
        unavailable = await resumed.toolkit.plan_resume(run_id)
        assert unavailable.status == "error"
        assert unavailable.result["code"] == "artifacts_unavailable"

        monkeypatch.setattr("parrot.tools.execution_plan.runs.process_identity", lambda: original_identity)
        continuation = await resumed.toolkit.plan_resume(run_id)
        assert continuation.status == "success"
        terminal = await _wait_for_terminal(resumed.toolkit, run_id)
        assert terminal["status"] == "completed"
        assert resumed.manager.dispatch_counts == {"c": 1}
    finally:
        await runtime.stop()


async def test_large_fanout_restart_preserves_skip_existing() -> None:
    """A 300-item fan-out retains existing aliases when restarted in-process."""
    manager = CountingToolManager({"list": {"items": list(range(300))}, "item": {"ok": True}})
    memory = WorkingMemoryToolkit()
    for index in range(150):
        memory._catalog.put_generic(f"item_{index}", {"ok": True})
    plan = ExecutionPlan(
        name="fanout",
        objective="fanout",
        nodes=[
            PlanNode(id="list", tool="list", store_as="list_out"),
            PlanNode(
                id="fetch",
                tool="item",
                store_as="item_{index}",
                depends_on=["list"],
                args={"item": "{item}"},
                for_each=ForEach(source="{artifacts.list_out}", select="items[]", skip_existing=True),
            ),
        ],
    )
    toolkit = ExecutionPlanToolkit(tool_manager=manager, working_memory=memory, soft_timeout=10.0)
    result = await toolkit._run_plan(plan, source="plan_name")
    assert result.status == "success"
    assert manager.dispatch_counts["item"] == 150
    assert manager.dispatch_counts["list"] == 1
    assert len([key for key in memory._catalog._store if key.startswith("item_")]) == 300


async def test_actual_durable_artifacts_reconnect(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real PostgreSQL artifact version remains usable after reconstruction."""
    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        pytest.skip(_PG_SKIP)
    from navigator.utils.file import LocalFileManager
    from parrot.tools.working_memory.task_memory.store.postgres import PostgresTaskMemoryStore

    migrator = PostgresTaskMemoryStore(dsn)
    await migrator.apply_migrations()
    await migrator.close()
    runtime = TaskMemoryRuntime(
        TaskMemoryConfig(enabled=True, durable=True, dsn=dsn),
        file_manager=LocalFileManager(base_path=str(tmp_path), create_base=True),
    )
    await runtime.start(start_scheduler=False)
    try:
        gate_c = asyncio.Event()
        original = Process(runtime=runtime, scope=SCOPE, durable=True, gates={"c": gate_c})
        run_id = await _run_until_b_checkpointed(original)
        checkpoint = await original.store.latest(run_id)
        assert checkpoint is not None
        original_b = checkpoint.context.results["b"]
        restored = Process(
            {key: dict(value) for key, value in original.store._bytes.items()},
            runtime=runtime,
            scope=SCOPE,
            durable=True,
        )
        monkeypatch.setattr("parrot.tools.execution_plan.runs.process_identity", lambda: "different-process")
        continuation = await restored.toolkit.plan_resume(run_id)
        assert continuation.status == "success"
        terminal = await _wait_for_terminal(restored.toolkit, run_id)
        assert terminal["status"] == "completed"
        restored_b = next(item for item in terminal["artifacts"] if item["node_id"] == "b")
        assert restored_b["versions"] == original_b.versions
        assert restored.manager.dispatch_counts == {"c": 1}
    finally:
        await runtime.stop()


async def test_serialized_fake_store_recovery_always_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Metadata-only reads survive object loss without materializing payload bytes."""
    gate_c = asyncio.Event()
    original = Process(durable=True, gates={"c": gate_c})
    run_id = await _run_until_b_checkpointed(original)
    restored = Process({key: dict(value) for key, value in original.store._bytes.items()}, durable=True)
    monkeypatch.setattr("parrot.tools.execution_plan.runs.process_identity", lambda: "same-process")
    status = await restored.toolkit.plan_status(run_id)
    artifacts = await restored.toolkit.plan_artifacts(run_id)
    assert status.status == artifacts.status == "success"
    assert status.result["run_id"] == artifacts.result["run_id"] == run_id
    assert [item["node_id"] for item in artifacts.result["artifacts"]] == ["a", "b"]


async def test_in_memory_downgrade_status_works_resume_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checkpoint bytes remain inspectable while process-local artifacts block resume."""
    gate_c = asyncio.Event()
    original = Process(gates={"c": gate_c})
    run_id = await _run_until_b_checkpointed(original)
    restored = Process({key: dict(value) for key, value in original.store._bytes.items()})
    monkeypatch.setattr("parrot.tools.execution_plan.runs.process_identity", lambda: "different-process")
    status = await restored.toolkit.plan_status(run_id)
    assert status.result["resume_level"] == "process"
    assert status.result["resumable"] is False
    assert status.result["recovery_reason"] == "artifacts_unavailable"
    resume = await restored.toolkit.plan_resume(run_id)
    assert resume.status == "error"
    assert resume.result["code"] == "artifacts_unavailable"


def test_standalone_disabled_surface_unchanged() -> None:
    """A standalone working-memory toolkit preserves its disabled result schema."""
    toolkit = WorkingMemoryToolkit()
    schema = toolkit.get_tool("wm_get_result").args_schema
    assert toolkit.task_memory_enabled is False
    assert toolkit._task_memory is None
    assert set(schema.model_fields) == {"include_raw", "key", "max_length"}


async def test_expiration_identity_by_tier() -> None:
    """Durable misses are unknown while ephemeral TTL misses are expired."""
    durable = Process(durable=True)
    unknown = await durable.toolkit.plan_status("unrecorded")
    assert unknown.status == "error"
    assert unknown.result["code"] == "unknown_run"

    ephemeral = Process()
    ephemeral.store._bytes["expired"] = {}
    ephemeral.store.ttl_expired.add("expired")
    expired = await ephemeral.toolkit.plan_status("expired")
    assert expired.status == "error"
    assert expired.result["code"] == "missing_or_expired"
    assert set(ephemeral.store._bytes) == {"expired"}
