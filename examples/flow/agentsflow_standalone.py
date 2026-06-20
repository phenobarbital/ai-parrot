"""
AgentsFlow Standalone Examples
==============================
Demonstrates the *new-style* DAG executor ``AgentsFlow`` (FEAT-163 / FEAT-196)
on its own — **not** the AgentCrew ``run_flow()`` mode.

``AgentsFlow`` is an event-driven scheduler over a graph of ``Node`` instances.
Unlike ``AgentCrew`` (which wires agents into one of four canned execution
modes), ``AgentsFlow`` lets you wire an arbitrary DAG node-by-node and
edge-by-edge, with:

  * **Auto-parallelization** — independent nodes run concurrently; a fast node
    never waits for a slow sibling.
  * **Conditional routing** — edges carry a ``predicate`` (a Python callable or
    a CEL string) so a node can pick which branch fires.
  * **OR-join + skip-propagation** — a join node dispatches once *all* incoming
    edges are resolved and *at least one* fired; if none fired it is skipped
    and the skip cascades downstream.
  * **Lifecycle events** — attach ``on_node_event`` listeners to observe
    ``flow_started`` / ``node_started`` / ``node_completed`` / ``node_failed`` /
    ``node_skipped`` / ``flow_completed`` without touching the engine.

Two ways to build a flow are shown:
  * EXAMPLE 1 — programmatic ``add_node()`` / ``add_edge()`` (explicit-edge
    mode): a research → analyze fan-in DAG.
  * EXAMPLE 2 — conditional routing with a predicate edge + OR-join merge,
    demonstrating that only the taken branch runs and the skip propagates.

Correct import path (post FEAT-196):
    from parrot.bots.flows import AgentsFlow, FlowEdge          # executor + edge
    from parrot.bots.flows.core import AgentNode, FlowContext   # graph primitives

NOTE: the legacy ``parrot.bots.flow`` (singular) package was **deleted** by
FEAT-196. Any example still importing from it is stale.

Usage:
    source .venv/bin/activate
    python examples/flow/agentsflow_standalone.py

Requires an API key for the configured provider (default: Google GenAI):
    GOOGLE_API_KEY    -> Gemini   (USE_LLM = "google")
Switch ``USE_LLM`` below to use a different provider you have a key for.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from parrot.bots import BasicAgent
from parrot.bots.flows import AgentsFlow
from parrot.bots.flows.core import AgentNode, FlowContext


# Provider used for every agent in these examples. Change this to any provider
# you have credentials for ("anthropic", "openai", "groq", ...).
USE_LLM = "google"


# ============================================================================
# Lifecycle listener — observes the scheduler without touching the engine
# ============================================================================

def lifecycle_listener(event: str, node_id: str, info: Dict[str, Any]) -> None:
    """Print a one-line trace for every scheduler lifecycle event.

    Matches the ``on_node_event`` contract: ``(event, node_id, info)``. Flow
    level events carry ``node_id == ""``. Exceptions raised here are caught and
    logged by the engine — telemetry can never break a run.

    Args:
        event: One of ``flow_started`` | ``node_started`` | ``node_completed``
            | ``node_failed`` | ``node_skipped`` | ``flow_completed``.
        node_id: The node the event refers to ("" for flow-level events).
        info: Extra payload (``duration_ms`` on completions, ``status`` and
            outcome counts on ``flow_completed``, etc.).
    """
    if node_id:
        suffix = ""
        if "duration_ms" in info:
            suffix = f" ({info['duration_ms']:.0f} ms)"
        print(f"  · [{event:<15}] {node_id}{suffix}")
    else:
        status = info.get("status", "")
        print(f"  · [{event:<15}] flow={info.get('flow')} {status}")


# ============================================================================
# EXAMPLE 1: Fan-in DAG (auto-parallelization + OR-join)
# ============================================================================

async def example_fan_in_dag() -> None:
    """Two researchers run in parallel; an analyst merges both outputs.

    Graph::

        market_researcher ─┐
                           ├──▶ analyst
        tech_researcher  ─┘

    ``market_researcher`` and ``tech_researcher`` have no edge between them, so
    the scheduler dispatches them concurrently. ``analyst`` has two incoming
    edges and only fires once both have resolved (OR-join), receiving both
    results as dependency context.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Fan-in DAG (parallel research → analyst)")
    print("=" * 70 + "\n")

    market_researcher = BasicAgent(
        name="market_researcher",
        system_prompt=(
            "You are a market analyst. Given a product idea, list the top 3 "
            "market opportunities in 2-3 concise bullet points."
        ),
        use_llm=USE_LLM,
    )
    tech_researcher = BasicAgent(
        name="tech_researcher",
        system_prompt=(
            "You are a technical analyst. Given a product idea, list the top 3 "
            "technical risks in 2-3 concise bullet points."
        ),
        use_llm=USE_LLM,
    )
    analyst = BasicAgent(
        name="analyst",
        system_prompt=(
            "You are a strategy lead. Combine the market opportunities and the "
            "technical risks you are given into a single go / no-go recommendation."
        ),
        use_llm=USE_LLM,
    )

    # Agents must be configured before the flow runs them.
    for agent in (market_researcher, tech_researcher, analyst):
        await agent.configure()

    flow = AgentsFlow("product-review", on_node_event=lifecycle_listener)

    # node_id is the graph-unique address; AgentNode.name delegates to agent.name.
    flow.add_node(AgentNode(node_id="market", agent=market_researcher))
    flow.add_node(AgentNode(node_id="tech", agent=tech_researcher))
    flow.add_node(AgentNode(node_id="analyst", agent=analyst))

    # Declaring edges switches the scheduler into explicit-edge mode.
    flow.add_edge("market", "analyst")
    flow.add_edge("tech", "analyst")

    ctx = FlowContext(initial_task="A real-time AI voice avatar for customer support")
    result = await flow.run_flow(ctx)

    print(f"\nStatus       : {result.status.value}")
    print(f"Total time   : {result.total_time:.2f}s")
    print(f"Nodes run    : {[n.node_id for n in result.nodes]}")
    analyst_out = result.responses.get("analyst", {})
    text = analyst_out.get("output") if isinstance(analyst_out, dict) else analyst_out
    print(f"\nAnalyst recommendation:\n{str(text)[:600]}")


# ============================================================================
# EXAMPLE 2: Conditional routing (predicate edges + skip-propagation)
# ============================================================================

async def example_conditional_routing() -> None:
    """A router picks a branch; only the taken branch runs, the other is skipped.

    Graph::

        router ─(== "billing")─▶ billing_agent ─┐
               ─(== "tech")────▶ tech_agent ─────┤──▶ responder
                                                 (OR-join)

    The router classifies the request. Each predicate edge fires only when the
    router's output matches. The branch whose predicate is False is *skipped*,
    and because ``responder`` uses an OR-join it still fires from the branch
    that did run.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Conditional routing (predicate edges + OR-join)")
    print("=" * 70 + "\n")

    router = BasicAgent(
        name="router",
        system_prompt=(
            "Classify the user's request as exactly one lowercase word: "
            "'billing' or 'tech'. Reply with ONLY that single word."
        ),
        use_llm=USE_LLM,
    )
    billing_agent = BasicAgent(
        name="billing_agent",
        system_prompt="You handle billing questions. Answer briefly and helpfully.",
        use_llm=USE_LLM,
    )
    tech_agent = BasicAgent(
        name="tech_agent",
        system_prompt="You handle technical support. Answer briefly and helpfully.",
        use_llm=USE_LLM,
    )
    responder = BasicAgent(
        name="responder",
        system_prompt="Rewrite the specialist's answer as a polite final reply to the customer.",
        use_llm=USE_LLM,
    )

    for agent in (router, billing_agent, tech_agent, responder):
        await agent.configure()

    flow = AgentsFlow("support-router", on_node_event=lifecycle_listener)
    flow.add_node(AgentNode(node_id="router", agent=router))
    flow.add_node(AgentNode(node_id="billing", agent=billing_agent))
    flow.add_node(AgentNode(node_id="tech", agent=tech_agent))
    flow.add_node(AgentNode(node_id="responder", agent=responder))

    # A predicate inspects the SOURCE node's result. AgentNode returns a dict
    # ({'output': ..., 'response': ..., ...}), so read the 'output' text.
    def routed_to(label: str):
        def _predicate(source_result: Any) -> bool:
            text = (
                source_result.get("output", "")
                if isinstance(source_result, dict)
                else str(source_result)
            )
            return label in text.lower()
        return _predicate

    flow.add_edge("router", "billing", predicate=routed_to("billing"))
    flow.add_edge("router", "tech", predicate=routed_to("tech"))
    flow.add_edge("billing", "responder")
    flow.add_edge("tech", "responder")

    ctx = FlowContext(initial_task="My invoice charged me twice this month, can you help?")
    result = await flow.run_flow(ctx)

    ran = [n.node_id for n in result.nodes]
    print(f"\nStatus       : {result.status.value}")
    print(f"Nodes run    : {ran}")
    print(f"Skipped      : {[n for n in ('billing', 'tech') if n not in ran]}")
    responder_out = result.responses.get("responder", {})
    text = responder_out.get("output") if isinstance(responder_out, dict) else responder_out
    print(f"\nFinal reply:\n{str(text)[:600]}")


# ============================================================================
# Main
# ============================================================================

async def main() -> None:
    """Run the AgentsFlow standalone examples."""
    print("\n" + "=" * 70)
    print("AgentsFlow — Standalone DAG Examples")
    print("=" * 70)

    try:
        await example_fan_in_dag()
        await example_conditional_routing()
        print("\n" + "=" * 70)
        print("ALL EXAMPLES COMPLETED")
        print("=" * 70 + "\n")
    except Exception as exc:  # noqa: BLE001 - example-level catch-all
        print(f"\n❌ Error: {exc}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
