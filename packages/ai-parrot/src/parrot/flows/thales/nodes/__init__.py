"""Flow node classes for the "Thales" research flow (FEAT-425 Module 3).

Plain ``parrot.bots.flows.core.node.Node`` subclasses wired into an
``AgentsFlow`` programmatically (``add_node``/``add_edge`` — TASK-2231's
``definition.py``, not ``from_definition``). Each node type IS registered
in the global ``NODE_REGISTRY``, idempotently, via ``registry.
register_thales_node`` — verified during TASK-2231: ``AgentsFlow``'s
``checkpoint=True`` (FEAT-399) requires it regardless of assembly mode
(the same reason ``parrot.flows.dev_loop`` registers its own node types).
TASK-2229 (LLM nodes: planner, deck builder, slide spec) and TASK-2230
(fan-in nodes: bibliography, exec summary, final document, infographic)
share this package.
"""

from __future__ import annotations

from parrot.flows.thales.nodes.bibliography import BibliographyNode, format_apa
from parrot.flows.thales.nodes.deck_builder import DeckBuilderNode
from parrot.flows.thales.nodes.document import FinalDocumentNode
from parrot.flows.thales.nodes.infographic import InfographicNode
from parrot.flows.thales.nodes.planner import PlannerNode
from parrot.flows.thales.nodes.registry import register_thales_node
from parrot.flows.thales.nodes.slide_spec import SlideSpecNode
from parrot.flows.thales.nodes.summary import ExecSummaryNode

__all__ = [
    "BibliographyNode",
    "DeckBuilderNode",
    "ExecSummaryNode",
    "FinalDocumentNode",
    "InfographicNode",
    "PlannerNode",
    "SlideSpecNode",
    "format_apa",
    "register_thales_node",
]
