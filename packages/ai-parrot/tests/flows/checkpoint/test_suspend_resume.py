"""Tests for AgentsFlow checkpoint wiring — suspend()/resume() (TASK-2053).

Unit-level: an in-memory FakeCheckpointStore stands in for both the
ephemeral and (where needed) durable tier — no Redis required. Covers
the resume-skips-completed-nodes contract via node-execution counters,
lease-conflict/expired-checkpoint error paths, and suspend().
"""
from typing import Any

import pytest
from parrot.bots.flows.core.checkpoint import (
    CheckpointNotFoundError,
    CheckpointStore,
    FlowCheckpoint,
    FlowLockedError,
)
from parrot.bots.flows.flow.flow import AgentsFlow


class FakeCheckpointStore(CheckpointStore):
    """In-memory CheckpointStore — full contract, no external service."""

    def __init__(self) -> None:
        self._by_flow: dict[str, list[FlowCheckpoint]] = {}
        self._leases: dict[str, str] = {}

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        history = self._by_flow.setdefault(checkpoint.flow_id, [])
        # Upsert by checkpoint_id (dump() may write the same final id twice).
        history[:] = [c for c in history if c.checkpoint_id != checkpoint.checkpoint_id]
        history.append(checkpoint)
        history.sort(key=lambda c: c.checkpoint_id)

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
        flows = []
        for flow_id, history in self._by_flow.items():
            if not history:
                continue
            latest = history[-1]
            if status is not None and latest.status != status:
                continue
            flows.append({"flow_id": flow_id, "status": latest.status})
        return flows

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


class CountingAgent:
    """Minimal AgentLike stub that counts every `.ask()` invocation.

    Note: no `start`/`end` typed nodes are used anywhere in this file —
    ``AgentNode``/``StartNode``/``EndNode`` (`core/node.py`) are frozen
    Pydantic models, and only ``AgentNode`` declares an `fsm` field
    (auto-created in `model_post_init`); `StartNode`/`EndNode` have none.
    `AgentsFlow._run_node()` unconditionally calls `node.fsm.schedule()`
    for every dispatched node — a latent, pre-existing gap for
    definition-driven `start`/`end` nodes that no test in the existing
    suite exercises (`_start_node_def()` in `test_agents_flow.py` is
    defined but never called; every passing `from_definition()` +
    `run_flow()` test chains plain `"agent"`-typed nodes only). Out of
    scope for FEAT-399 to fix `core/node.py` — this test suite instead
    follows the same working pattern as the rest of the codebase.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def invoke(self, prompt: str, **kwargs: object) -> object:
        self.calls += 1
        return "ok"

    async def ask(self, question: str = "", **kwargs: object) -> object:
        self.calls += 1
        return type("R", (), {"content": f"{self._name}-done"})()


class StubRegistry:
    """Minimal AgentRegistry stub using get_bot_instance (sync)."""

    def __init__(self, agents: dict) -> None:
        self._agents = agents

    def get_bot_instance(self, name: str) -> object:
        return self._agents.get(name)


def _make_linear_definition():
    from parrot.bots.flows.flow.definition import (
        EdgeDefinition,
        FlowDefinition,
        NodeDefinition,
    )

    return FlowDefinition(
        flow="suspend-resume-test-flow",
        nodes=[
            NodeDefinition(id="n1", type="agent", agent_ref="agent1"),
            NodeDefinition(id="n2", type="agent", agent_ref="agent2"),
            NodeDefinition(id="n3", type="agent", agent_ref="agent3"),
        ],
        edges=[
            EdgeDefinition(**{"from": "n1", "to": "n2", "condition": "on_success"}),
            EdgeDefinition(**{"from": "n2", "to": "n3", "condition": "on_success"}),
        ],
    )


@pytest.fixture
def agents():
    return {
        "agent1": CountingAgent("agent1"),
        "agent2": CountingAgent("agent2"),
        "agent3": CountingAgent("agent3"),
    }


@pytest.fixture
def registry(agents):
    return StubRegistry(agents)


@pytest.fixture
def fake_store():
    return FakeCheckpointStore()


@pytest.mark.asyncio
async def test_checkpoint_disabled_is_byte_identical(registry):
    """checkpoint=False (default) must not touch any store or attach a checkpointer."""
    definition = _make_linear_definition()
    flow = AgentsFlow.from_definition(definition, agent_registry=registry)
    result = await flow.run_flow("go")
    assert result.status.value == "completed"
    assert flow._checkpointer is None


@pytest.mark.asyncio
async def test_resume_skips_completed_nodes(agents, registry, fake_store):
    flow_id = "resume-test-flow"
    definition = _make_linear_definition()
    flow = AgentsFlow.from_definition(
        definition,
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=fake_store,
        flow_id=flow_id,
    )
    await flow.run_flow("go")

    assert agents["agent1"].calls == 1
    assert agents["agent2"].calls == 1
    assert agents["agent3"].calls == 1

    # Re-fork from the checkpoint written right after n1 completed
    # (checkpoint_id=1) — n1 must NOT re-execute; n2/n3 (the frontier) must.
    history = await fake_store.history(flow_id, limit=20)
    checkpoint_after_n1 = next(
        cp for cp in history if "n1" in cp.context.completed_tasks
        and "n2" not in cp.context.completed_tasks
    )

    resumed = await AgentsFlow.resume(
        flow_id,
        checkpoint_after_n1.checkpoint_id,
        agent_registry=registry,
        store=fake_store,
    )
    await resumed.run_flow()

    assert agents["agent1"].calls == 1  # not re-executed
    assert agents["agent2"].calls == 2  # re-forked frontier ran again
    assert agents["agent3"].calls == 2


@pytest.mark.asyncio
async def test_resume_locked_raises_flowlockederror(fake_store, registry):
    flow_id = "locked-flow"
    definition = _make_linear_definition()
    flow = AgentsFlow.from_definition(
        definition,
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=fake_store,
        flow_id=flow_id,
    )
    await flow.run_flow("go")

    await fake_store.acquire_lease(flow_id, "other-holder", ttl=60)

    with pytest.raises(FlowLockedError):
        await AgentsFlow.resume(flow_id, agent_registry=registry, store=fake_store)


@pytest.mark.asyncio
async def test_resume_missing_checkpoint_raises(fake_store, registry):
    with pytest.raises(CheckpointNotFoundError):
        await AgentsFlow.resume(
            "nonexistent-flow", agent_registry=registry, store=fake_store
        )


@pytest.mark.asyncio
async def test_suspend_produces_durable_suspended_checkpoint(agents, registry):
    fake_store = FakeCheckpointStore()
    durable_store = FakeCheckpointStore()
    flow_id = "suspend-test-flow"
    definition = _make_linear_definition()
    flow = AgentsFlow.from_definition(
        definition,
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=fake_store,
        durable_store=durable_store,
        flow_id=flow_id,
    )

    captured_checkpoint = {}

    await flow.run_flow("go")

    # suspend() requires an active run (self._active_ctx set + a bound
    # checkpointer) — both are only true while run_flow() is executing, so
    # exercise it via an on_complete hook, which runs inside the scheduler
    # before run_flow()'s finally block tears the checkpointer down.
    resumed = await AgentsFlow.resume(
        flow_id, agent_registry=registry, store=fake_store, durable_store=durable_store
    )

    async def call_suspend(ctx, result):
        captured_checkpoint["cp"] = await resumed.suspend()

    await resumed.run_flow(on_complete=(call_suspend,))

    cp = captured_checkpoint["cp"]
    assert cp.status == "suspended"
    durable_history = await durable_store.history(flow_id, limit=20)
    assert any(c.status == "suspended" for c in durable_history)
