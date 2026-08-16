"""
AgentsFlow State Checkpointing — Kill & Resume Example (FEAT-399)
==================================================================
Demonstrates the two-tier checkpointing plane added on top of the
``AgentsFlow`` DAG executor: opt-in per-node checkpoints to Redis
(ephemeral tier), ``AgentsFlow.resume()`` continuing a run from its last
completed node, and re-forking from an older historical checkpoint.

Two scenarios are shown:
  * EXAMPLE 1 — run a 3-node linear flow with ``checkpoint=True``, then
    call ``AgentsFlow.resume()`` on a **fresh** ``AgentsFlow`` instance
    (built purely from the checkpoint's embedded ``FlowDefinition``,
    matching what a restarted process would do). Node-call counters
    prove completed nodes are never re-executed.
  * EXAMPLE 2 — re-fork from an *older* checkpoint (``checkpoint_id``
    from right after the first node), showing the downstream nodes
    re-run from that point while the earlier node is skipped.

A commented-out block shows the durable tier (``durable=True`` write-
through to a second store) and the graceful-shutdown hook
(``FlowRecoveryService.attach_to_app``) — see the inline comments for
how to switch the durable backend to Postgres/Mongo.

Requires a **local Redis** server (the ephemeral checkpoint tier) —
set ``REDIS_URL`` if it isn't on the default ``redis://localhost:6379/1``
(see ``parrot.conf.REDIS_URL``). No LLM API key is required: this
example uses a lightweight ``AgentLike`` stub (not a real ``BasicAgent``)
so it runs standalone with just Redis, purely to demonstrate the
checkpoint/resume mechanics.

Usage:
    source .venv/bin/activate
    docker run -d --rm -p 6379:6379 redis:7-alpine   # if you don't already have one
    python examples/flow/agentsflow_checkpointing.py
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from parrot.bots.flows.core.checkpoint.store.redis import RedisCheckpointStore
from parrot.bots.flows.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    NodeDefinition,
)
from parrot.bots.flows.flow.flow import AgentsFlow

# ============================================================================
# A minimal AgentLike stub — no LLM/API key required for this example.
# Counts invocations so the "not re-executed" claim is directly observable.
# ============================================================================

class CountingAgent:
    """Satisfies the ``AgentLike`` protocol (``name`` + async ``invoke``/``ask``)."""

    def __init__(self, name: str, reply: str) -> None:
        self._name = name
        self._reply = reply
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def invoke(self, prompt: str, **kwargs: Any) -> Any:
        self.calls += 1
        return self._reply

    async def ask(self, question: str = "", **kwargs: Any) -> Any:
        self.calls += 1
        return type("Response", (), {"content": self._reply})()


class StaticRegistry:
    """Minimal ``AgentRegistry``-compatible lookup (sync ``get_bot_instance``)."""

    def __init__(self, agents: dict[str, CountingAgent]) -> None:
        self._agents = agents

    def get_bot_instance(self, name: str) -> Any:
        return self._agents.get(name)


def build_linear_definition(flow_name: str) -> FlowDefinition:
    """A 3-node linear flow: research -> draft -> polish."""
    return FlowDefinition(
        flow=flow_name,
        nodes=[
            NodeDefinition(id="research", type="agent", agent_ref="researcher"),
            NodeDefinition(id="draft", type="agent", agent_ref="writer"),
            NodeDefinition(id="polish", type="agent", agent_ref="editor"),
        ],
        edges=[
            EdgeDefinition(**{"from": "research", "to": "draft", "condition": "on_success"}),
            EdgeDefinition(**{"from": "draft", "to": "polish", "condition": "on_success"}),
        ],
    )


def print_calls(agents: dict[str, CountingAgent]) -> None:
    for name, agent in agents.items():
        print(f"  · {name:<12} calls={agent.calls}")


# ============================================================================
# EXAMPLE 1: Kill & resume — completed nodes are never re-executed
# ============================================================================

async def example_kill_and_resume() -> None:
    """Run a flow with checkpoint=True, then resume it in a *fresh* AgentsFlow.

    ``AgentsFlow.resume()`` loads the latest checkpoint, rebuilds the flow
    via ``from_definition(checkpoint.definition, ...)``, and seeds a fresh
    ``FlowContext`` marking every node in ``completion_order`` as already
    completed — the scheduler naturally skips them and dispatches only the
    frontier. Since a real crash/restart isn't simulated here, resuming the
    *latest* (fully-completed) checkpoint demonstrates the same guarantee:
    zero additional agent calls.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Kill & resume (checkpoint=True)")
    print("=" * 70 + "\n")

    flow_id = f"checkpointing-example-{uuid.uuid4().hex[:8]}"
    agents = {
        "researcher": CountingAgent("researcher", "Researched the topic."),
        "writer": CountingAgent("writer", "Drafted the article."),
        "editor": CountingAgent("editor", "Polished the final copy."),
    }
    registry = StaticRegistry(agents)
    definition = build_linear_definition(flow_id)

    # checkpoint_store defaults to Redis (FLOW_CHECKPOINT_STORE=redis) —
    # pass an explicit instance here just to make the tier obvious.
    store = RedisCheckpointStore()

    flow = AgentsFlow.from_definition(
        definition,
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=store,
        flow_id=flow_id,
    )
    result = await flow.run_flow("Write a short article about asyncio")
    print(f"First run status: {result.status.value}")
    print_calls(agents)

    # Simulate a process restart: resume() takes only flow_id + a *fresh*
    # AgentRegistry — no reference to the original `flow` object at all.
    resumed = await AgentsFlow.resume(flow_id, agent_registry=registry, store=store)
    await resumed.run_flow()

    print("\nAfter resume() (nothing re-ran — all counts unchanged):")
    print_calls(agents)

    await store.delete_flow(flow_id)
    await store.close()


# ============================================================================
# EXAMPLE 2: Re-fork from a historical checkpoint
# ============================================================================

async def example_refork_from_history() -> None:
    """Resume from an *older* checkpoint_id — downstream nodes re-run.

    History is bounded (``FLOW_CHECKPOINT_HISTORY``, default 10) — re-fork
    targets must be within that retained window.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Re-fork from a historical checkpoint")
    print("=" * 70 + "\n")

    flow_id = f"checkpointing-refork-{uuid.uuid4().hex[:8]}"
    agents = {
        "researcher": CountingAgent("researcher", "Researched the topic."),
        "writer": CountingAgent("writer", "Drafted the article."),
        "editor": CountingAgent("editor", "Polished the final copy."),
    }
    registry = StaticRegistry(agents)
    definition = build_linear_definition(flow_id)
    store = RedisCheckpointStore()

    flow = AgentsFlow.from_definition(
        definition,
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=store,
        flow_id=flow_id,
    )
    await flow.run_flow("Write a short article about asyncio")
    print("First run:")
    print_calls(agents)

    # Find the checkpoint written right after "research" completed (i.e.
    # before "draft" ran) and re-fork from there.
    history = await store.history(flow_id, limit=10)
    checkpoint_after_research = next(
        cp for cp in history
        if "research" in cp.context.completed_tasks
        and "draft" not in cp.context.completed_tasks
    )

    resumed = await AgentsFlow.resume(
        flow_id, checkpoint_after_research.checkpoint_id, agent_registry=registry, store=store
    )
    await resumed.run_flow()

    print("\nAfter re-fork (researcher NOT re-run; writer/editor re-ran):")
    print_calls(agents)

    await store.delete_flow(flow_id)
    await store.close()


# ============================================================================
# Durable tier + graceful shutdown (illustrative — not executed by main())
# ============================================================================

async def _durable_tier_and_shutdown_snippet() -> None:  # pragma: no cover - docs only
    """Illustrates `durable=True` write-through and the shutdown hook.

    Not called by ``main()`` — this function exists purely as copy-pasteable
    documentation; it isn't part of the runnable demo.
    """
    from parrot.bots.flows.core.checkpoint.recovery import get_recovery_service
    from parrot.bots.flows.core.checkpoint.store.durable import DurableCheckpointStore

    # Durable tier: swap driver="sqlite" for "postgres" or "mongodb" to use
    # a different backend (DurableCheckpointStore is one parametrized class
    # covering all three via asyncdb).
    durable_store = DurableCheckpointStore(driver="sqlite", dsn="flow_checkpoints.db")

    flow = AgentsFlow(
        name="durable-example",
        checkpoint=True,
        durable=True,  # write-through every checkpoint to BOTH tiers
        durable_store=durable_store,
    )
    print(f"Configured durable flow: {flow.name} (flow_id={flow.flow_id})")

    # Inside an aiohttp app's setup(): suspend every active checkpointed
    # flow within FLOW_CHECKPOINT_SHUTDOWN_DEADLINE (15s default) on
    # graceful shutdown. `AgentsFlow.run_flow()` registers itself with this
    # service automatically whenever `checkpoint=True` — nothing else to
    # wire up per-flow. `app` here is your aiohttp `web.Application`.
    app = ...
    get_recovery_service().attach_to_app(app)

    # Explicit suspend + dump mid-run (e.g. from a custom signal handler):
    # await flow.suspend()


# ============================================================================
# Main
# ============================================================================

async def main() -> None:
    """Run the AgentsFlow checkpointing examples."""
    print("\n" + "=" * 70)
    print("AgentsFlow — State Checkpointing Examples (FEAT-399)")
    print("=" * 70)

    try:
        await example_kill_and_resume()
        await example_refork_from_history()
        print("\n" + "=" * 70)
        print("ALL EXAMPLES COMPLETED")
        print("=" * 70 + "\n")
    except Exception as exc:  # noqa: BLE001 - example-level catch-all
        print(f"\n❌ Error: {exc}")
        print(
            "Is a local Redis server running? "
            "docker run -d --rm -p 6379:6379 redis:7-alpine"
        )
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
