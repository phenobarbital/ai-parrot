"""End-to-end AgentsFlow checkpointing tests (FEAT-399, TASK-2053, spec §4).

Exercises the real `RedisCheckpointStore` (ephemeral) and
`DurableCheckpointStore` (sqlite, durable) together — "fresh objects"
per test simulate a process restart between suspend/kill and resume.
Skipped cleanly when no Redis server is reachable at `REDIS_URL`.
"""
import socket
from urllib.parse import urlparse

import pytest
from parrot.bots.flows.core.checkpoint.store.durable import DurableCheckpointStore
from parrot.bots.flows.core.checkpoint.store.redis import RedisCheckpointStore
from parrot.bots.flows.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    NodeDefinition,
)
from parrot.bots.flows.flow.flow import AgentsFlow
from parrot.conf import REDIS_URL


def _redis_available() -> bool:
    parsed = urlparse(REDIS_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_available(), reason="Redis is not reachable at REDIS_URL"
)


class CountingAgent:
    """AgentLike stub counting `.ask()` invocations (see test_suspend_resume.py
    for why this suite never uses `start`/`end` typed nodes)."""

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
    def __init__(self, agents: dict) -> None:
        self._agents = agents

    def get_bot_instance(self, name: str) -> object:
        return self._agents.get(name)


def _make_linear_definition(flow_name: str) -> FlowDefinition:
    return FlowDefinition(
        flow=flow_name,
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
async def redis_store():
    store = RedisCheckpointStore()
    yield store
    await store.close()


@pytest.fixture
def durable_store(tmp_path):
    return DurableCheckpointStore(driver="sqlite", dsn=str(tmp_path / "e2e_ckpt.db"))


@pytest.mark.asyncio
async def test_e2e_checkpoint_kill_resume(agents, registry, redis_store):
    flow_id = "e2e-kill-resume-flow"
    await redis_store.delete_flow(flow_id)
    definition = _make_linear_definition(flow_id)

    flow = AgentsFlow.from_definition(
        definition,
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=redis_store,
        flow_id=flow_id,
    )
    await flow.run_flow("go")
    assert agents["agent1"].calls == 1
    assert agents["agent2"].calls == 1
    assert agents["agent3"].calls == 1

    # Resume "in fresh objects" — a brand new store instance + a brand new
    # AgentsFlow reconstructed purely from the checkpoint (simulates a
    # process restart). Resuming from the latest (fully-completed)
    # checkpoint must not re-execute any node.
    fresh_store = RedisCheckpointStore()
    resumed = await AgentsFlow.resume(
        flow_id, agent_registry=registry, store=fresh_store
    )
    result = await resumed.run_flow()

    assert agents["agent1"].calls == 1
    assert agents["agent2"].calls == 1
    assert agents["agent3"].calls == 1
    assert result.status.value == "completed"

    await redis_store.delete_flow(flow_id)
    await fresh_store.close()


@pytest.mark.asyncio
async def test_e2e_refork_from_historical_checkpoint(agents, registry, redis_store):
    flow_id = "e2e-refork-flow"
    await redis_store.delete_flow(flow_id)
    definition = _make_linear_definition(flow_id)

    flow = AgentsFlow.from_definition(
        definition,
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=redis_store,
        flow_id=flow_id,
    )
    await flow.run_flow("go")

    history = await redis_store.history(flow_id, limit=20)
    checkpoint_after_n1 = next(
        cp for cp in history
        if "n1" in cp.context.completed_tasks and "n2" not in cp.context.completed_tasks
    )

    resumed = await AgentsFlow.resume(
        flow_id,
        checkpoint_after_n1.checkpoint_id,
        agent_registry=registry,
        store=RedisCheckpointStore(),
    )
    await resumed.run_flow()

    assert agents["agent1"].calls == 1  # not re-executed
    assert agents["agent2"].calls == 2  # downstream re-ran
    assert agents["agent3"].calls == 2

    await redis_store.delete_flow(flow_id)


@pytest.mark.asyncio
async def test_e2e_durable_write_through(agents, registry, redis_store, durable_store):
    flow_id = "e2e-write-through-flow"
    await redis_store.delete_flow(flow_id)
    definition = _make_linear_definition(flow_id)

    flow = AgentsFlow.from_definition(
        definition,
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=redis_store,
        durable_store=durable_store,
        durable=True,
        flow_id=flow_id,
    )
    await flow.run_flow("go")

    ephemeral_history = await redis_store.history(flow_id, limit=20)
    durable_history = await durable_store.history(flow_id, limit=20)
    assert len(ephemeral_history) == 3
    assert len(durable_history) == 3
    assert {c.checkpoint_id for c in ephemeral_history} == {
        c.checkpoint_id for c in durable_history
    }

    await redis_store.delete_flow(flow_id)


@pytest.mark.asyncio
async def test_e2e_suspend_dump_resume_from_durable(
    agents, registry, redis_store, durable_store
):
    flow_id = "e2e-suspend-dump-flow"
    await redis_store.delete_flow(flow_id)
    definition = _make_linear_definition(flow_id)

    flow = AgentsFlow.from_definition(
        definition,
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=redis_store,
        durable_store=durable_store,
        flow_id=flow_id,
    )
    await flow.run_flow("go")

    resumed = await AgentsFlow.resume(
        flow_id,
        agent_registry=registry,
        store=redis_store,
        durable_store=durable_store,
    )

    captured = {}

    async def call_suspend(ctx, result):
        captured["cp"] = await resumed.suspend()

    await resumed.run_flow(on_complete=(call_suspend,))

    assert captured["cp"].status == "suspended"

    # Flush ephemeral entirely — resume must still work purely from durable.
    await redis_store.delete_flow(flow_id)

    resumed_from_durable = await AgentsFlow.resume(
        flow_id,
        agent_registry=registry,
        store=RedisCheckpointStore(),
        durable_store=durable_store,
    )
    result = await resumed_from_durable.run_flow()
    assert result.status.value == "completed"


@pytest.mark.asyncio
async def test_e2e_memory_refs_reattach(registry, redis_store):
    from parrot.bots.flows.core.checkpoint import MemoryRefs
    from parrot.bots.flows.core.checkpoint.checkpointer import FlowCheckpointer
    from parrot.bots.flows.core.context import FlowContext

    flow_id = "e2e-memory-refs-flow"
    await redis_store.delete_flow(flow_id)
    definition = _make_linear_definition(flow_id)
    refs = MemoryRefs(session_id="sess-42", chatbot_id="bot-7", user_id="user-9")

    # Write one checkpoint carrying memory_refs directly via a checkpointer
    # (simplest way to exercise the memory_refs round-trip end-to-end).
    checkpointer = FlowCheckpointer(
        flow_id=flow_id,
        flow_name=flow_id,
        definition=definition,
        store=redis_store,
        memory_refs=refs,
    )
    ctx = FlowContext(initial_task="go")
    ctx.mark_completed("n1", result="r1")
    listener = checkpointer.make_listener(ctx)
    listener("node_completed", "n1", {})
    await checkpointer.aclose()

    resumed = await AgentsFlow.resume(flow_id, agent_registry=registry, store=redis_store)
    assert resumed._checkpoint_memory_refs == refs

    await redis_store.delete_flow(flow_id)
