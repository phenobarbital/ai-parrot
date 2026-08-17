"""Flow node classes for the "Thales" research flow (FEAT-425 Module 3).

Plain ``parrot.bots.flows.core.node.Node`` subclasses injected via
``AgentsFlow.from_definition(node_factories=...)`` — the global
``NODE_REGISTRY`` is never touched (spec §7 patterns). Extended by
TASK-2230 with the fan-in nodes (bibliography, exec summary, final
document, infographic).
"""

from __future__ import annotations

from parrot.flows.thales.nodes.deck_builder import DeckBuilderNode
from parrot.flows.thales.nodes.planner import PlannerNode
from parrot.flows.thales.nodes.slide_spec import SlideSpecNode

__all__ = [
    "DeckBuilderNode",
    "PlannerNode",
    "SlideSpecNode",
]
