"""LLM-driven catalog->query agent over the governed semantic layer (FEAT-769 M3).

This is the example that proves the binding the rest of the subsystem depends on: the
``sl_*`` tools fail closed unless ``ask(permission_context=...)`` supplies a context that
matches the one bound by ``bind_semantic_context``.

Usage::

    python examples/agents/semantic/llm_metrics_agent.py --smoke          # no LLM, no network
    python examples/agents/semantic/llm_metrics_agent.py "revenue by region"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import _common

from parrot.bots import Agent
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context
from parrot.semantic.models import SemanticQuery
from parrot.semantic.toolkit import SemanticLayerToolkit

LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = """You answer questions about sales metrics using ONLY the sl_* tools.
Always discover the catalog first: call sl_list_models, then sl_get_dimensions for the model
you chose, and only then sl_query_metrics. Never invent a metric, a dimension or a figure.
If a member you need is not granted, say so plainly and stop — do not guess a substitute."""


def build_agent(toolkit: SemanticLayerToolkit) -> Agent:
    """Build an Agent exposing only the semantic layer's tools.

    Args:
        toolkit: A governed toolkit built by :func:`_common.build_toolkit`.

    Returns:
        An unconfigured Agent; the caller awaits ``configure()`` before the first ask.
    """
    return Agent(name="SemanticMetricsAgent", system_prompt=SYSTEM_PROMPT, tools=toolkit.get_tools())


async def smoke(toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity) -> dict[str, Any]:
    """Walk catalog -> dimensions -> query deterministically, with no LLM and no network.

    The calls are direct toolkit methods, which bypass ``_pre_execute`` by design
    (only ``ask()`` populates ``_permission_context``); the semantic context is still
    bound, because the tool bodies resolve the current subject from it.

    Args:
        toolkit: The governed toolkit.
        identity: The trusted fixture identity.

    Returns:
        A JSON-safe summary of the three steps.
    """
    async with bind_semantic_context(identity.ctx, identity=identity):
        models = await toolkit.list_models()
        dimensions = await toolkit.get_dimensions("orders", metrics=["order_count"])
        result = await toolkit.query_metrics(
            SemanticQuery(model="orders", metrics=["order_count"], dimensions=["region"])
        )
    return {
        "models": [model["name"] for model in models],
        "dimensions": [dimension["name"] for dimension in dimensions],
        "row_count": result.row_count,
    }


async def ask_llm(agent: Agent, question: str, identity: SemanticRequestIdentity) -> Any:
    """Drive the sl_* tools through the real governed dispatch path.

    Wraps ``bind_semantic_context(identity.ctx, identity=identity)`` around
    ``agent.ask(question, permission_context=identity.ctx)``. Omitting EITHER binding
    raises ``SemanticAccessError("context_required")`` at ``toolkit.py:110-116``: the
    supplied kwarg and the bound context must both be present and equal.

    Args:
        agent: A configured Agent built by :func:`build_agent`.
        question: The user's natural-language question.
        identity: The trusted fixture identity; its ``ctx`` is both bound and supplied.

    Returns:
        The agent's ``AIMessage``.
    """
    async with bind_semantic_context(identity.ctx, identity=identity):
        return await agent.ask(question, permission_context=identity.ctx)


async def main() -> None:
    """Run the deterministic smoke walk, or answer one question with an LLM."""
    parser = argparse.ArgumentParser(description="LLM-driven semantic metrics agent")
    parser.add_argument("--smoke", action="store_true", help="Run the deterministic walk (no LLM)")
    parser.add_argument("question", nargs="*", help="Question for the agent")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        warehouse = _common.build_warehouse(Path(directory))
        identity = _common.example_identity("analyst-1", "session-1", "eu")
        with _common.connection_env(warehouse):
            toolkit = _common.build_toolkit(warehouse)
            if args.smoke or not args.question:
                summary = await smoke(toolkit, identity)
                print(json.dumps(summary, indent=2))
                return
            agent = build_agent(toolkit)
            await agent.configure()
            answer = await ask_llm(agent, " ".join(args.question), identity)
            print(answer)


if __name__ == "__main__":
    asyncio.run(main())
