"""Tests for parrot.bots.flows.core.checkpoint.checkpointer (TASK-2051).

Exercises FlowCheckpointer against an in-memory fake CheckpointStore —
no Redis, no AgentsFlow wiring (that's TASK-2053). Covers event-driven
snapshotting, write-through, failure isolation, results-vs-responses,
dump(), and the resume-lease lifecycle.
"""
import asyncio
from typing import Any

import pytest
from parrot.bots.flows.core.checkpoint import (
    CheckpointStore,
    FlowCheckpoint,
    FlowCheckpointer,
    FlowLockedError,
    MemoryRefs,
)
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.result import NodeExecutionInfo
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition


class FakeCheckpointStore(CheckpointStore):
    """In-memory CheckpointStore recording puts; lease as a plain dict."""

    def __init__(self, put_should_raise: bool = False) -> None:
        self.puts: list[FlowCheckpoint] = []
        self._by_flow: dict[str, list[FlowCheckpoint]] = {}
        self._leases: dict[str, str] = {}
        self.put_should_raise = put_should_raise

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        if self.put_should_raise:
            raise RuntimeError("simulated store failure")
        self.puts.append(checkpoint)
        self._by_flow.setdefault(checkpoint.flow_id, []).append(checkpoint)

    async def latest(self, flow_id: str) -> FlowCheckpoint | None:
        history = self._by_flow.get(flow_id, [])
        return history[-1] if history else None

    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None:
        for cp in self._by_flow.get(flow_id, []):
            if cp.checkpoint_id == checkpoint_id:
                return cp
        return None

    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]:
        return list(reversed(self._by_flow.get(flow_id, [])))[:limit]

    async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]:
        return []

    async def delete_flow(self, flow_id: str) -> None:
        self._by_flow.pop(flow_id, None)

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        if flow_id in self._leases:
            return False
        self._leases[flow_id] = holder
        return True

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return self._leases.get(flow_id) == holder

    async def release_lease(self, flow_id: str, holder: str) -> None:
        if self._leases.get(flow_id) == holder:
            del self._leases[flow_id]

    async def close(self) -> None:
        pass


@pytest.fixture
def flow_definition() -> FlowDefinition:
    return FlowDefinition(
        flow="checkpointer-test-flow",
        nodes=[NodeDefinition(id="start", type="start")],
    )


@pytest.fixture
def flow_context() -> FlowContext:
    ctx = FlowContext(initial_task="do the thing")
    ctx.mark_completed(
        "node-a",
        result={"answer": 42},
        response="raw-response",
        metadata=NodeExecutionInfo(
            node_id="node-a", node_name="node-a", status="completed"
        ),
    )
    return ctx


@pytest.fixture
def fake_store() -> FakeCheckpointStore:
    return FakeCheckpointStore()


@pytest.mark.asyncio
async def test_checkpointer_writes_on_node_completion(
    fake_store, flow_definition, flow_context
):
    cp = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store,
    )
    listener = cp.make_listener(flow_context)
    listener("node_completed", "node-a", {})
    listener("node_completed", "node-a", {})
    await cp.aclose()

    assert len(fake_store.puts) == 2
    assert fake_store.puts[0].checkpoint_id == 1
    assert fake_store.puts[0].parent_checkpoint_id is None
    assert fake_store.puts[1].checkpoint_id == 2
    assert fake_store.puts[1].parent_checkpoint_id == 1


@pytest.mark.asyncio
async def test_checkpointer_ignores_non_checkpoint_events(
    fake_store, flow_definition, flow_context
):
    cp = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store,
    )
    listener = cp.make_listener(flow_context)
    listener("node_started", "node-a", {})
    listener("flow_started", "", {})
    await cp.aclose()
    assert len(fake_store.puts) == 0


@pytest.mark.asyncio
async def test_checkpointer_write_failure_does_not_break_flow(
    flow_definition, flow_context, caplog
):
    failing_store = FakeCheckpointStore(put_should_raise=True)
    cp = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=failing_store,
    )
    listener = cp.make_listener(flow_context)
    with caplog.at_level("WARNING"):
        listener("node_completed", "node-a", {})  # must not raise
        await cp.aclose()

    assert any("failed" in record.message.lower() for record in caplog.records)


@pytest.mark.asyncio
async def test_checkpointer_results_only_vs_include_responses(
    fake_store, flow_definition, flow_context
):
    cp = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store,
    )
    listener = cp.make_listener(flow_context)
    listener("node_completed", "node-a", {})
    await cp.aclose()

    assert fake_store.puts[0].context.responses is None
    assert fake_store.puts[0].context.results.get("node-a") == {"answer": 42}

    fake_store2 = FakeCheckpointStore()
    cp2 = FlowCheckpointer(
        flow_id="f2", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store2,
        include_responses=True,
    )
    listener2 = cp2.make_listener(flow_context)
    listener2("node_completed", "node-a", {})
    await cp2.aclose()

    assert fake_store2.puts[0].context.responses is not None
    assert fake_store2.puts[0].context.responses.get("node-a") == "raw-response"


@pytest.mark.asyncio
async def test_checkpointer_write_through_both_stores(
    fake_store, flow_definition, flow_context
):
    durable_store = FakeCheckpointStore()
    cp = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store,
        durable_store=durable_store, durable=True,
    )
    listener = cp.make_listener(flow_context)
    listener("node_completed", "node-a", {})
    await cp.aclose()

    assert len(fake_store.puts) == 1
    assert len(durable_store.puts) == 1
    assert durable_store.puts[0].checkpoint_id == fake_store.puts[0].checkpoint_id


@pytest.mark.asyncio
async def test_dump_marks_suspended(fake_store, flow_definition, flow_context):
    durable_store = FakeCheckpointStore()
    cp = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store,
        durable_store=durable_store,
    )
    listener = cp.make_listener(flow_context)
    listener("node_completed", "node-a", {})
    await asyncio.gather(*cp._pending_tasks)  # let the write land before dump()

    final_checkpoint = await cp.dump(flow_context)

    assert final_checkpoint.status == "suspended"
    assert any(c.status == "suspended" for c in durable_store.puts)
    # history (1 running checkpoint) + final suspended checkpoint copied through
    assert len(durable_store.puts) >= 2
    await cp.aclose()


@pytest.mark.asyncio
async def test_dump_without_durable_store_raises(fake_store, flow_definition, flow_context):
    cp = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store,
    )
    with pytest.raises(ValueError, match="durable store"):
        await cp.dump(flow_context)
    await cp.aclose()


@pytest.mark.asyncio
async def test_lease_acquire_conflict_and_release(fake_store, flow_definition):
    cp1 = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store,
    )
    cp2 = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store,
    )

    await cp1.acquire_lease("holder-a", ttl=6)
    with pytest.raises(FlowLockedError):
        await cp2.acquire_lease("holder-b", ttl=6)

    await cp1.aclose()  # releases the lease + cancels heartbeat

    # now holder-b can acquire
    await cp2.acquire_lease("holder-b", ttl=6)
    await cp2.aclose()


@pytest.mark.asyncio
async def test_heartbeat_renews_lease(fake_store, flow_definition):
    cp = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store,
    )
    await cp.acquire_lease("holder-a", ttl=1)  # heartbeat every ~0.33s
    await asyncio.sleep(0.5)
    assert fake_store._leases.get("f1") == "holder-a"
    await cp.aclose()
    assert "f1" not in fake_store._leases


@pytest.mark.asyncio
async def test_memory_refs_stored_on_checkpoint(fake_store, flow_definition, flow_context):
    refs = MemoryRefs(session_id="sess-1", chatbot_id="bot-1", user_id="user-1")
    cp = FlowCheckpointer(
        flow_id="f1", flow_name="checkpointer-test-flow",
        definition=flow_definition, store=fake_store,
        memory_refs=refs,
    )
    listener = cp.make_listener(flow_context)
    listener("node_completed", "node-a", {})
    await cp.aclose()

    assert fake_store.puts[0].memory_refs == refs
