"""Flow node classes for the "Thales" research flow (FEAT-425 Module 3).

Plain ``parrot.bots.flows.core.node.Node`` subclasses injected via
``AgentsFlow.from_definition(node_factories=...)`` — the global
``NODE_REGISTRY`` is never touched (spec §7 patterns). TASK-2229 (LLM
nodes: planner, deck builder, slide spec) and TASK-2230 (fan-in nodes:
bibliography, exec summary, final document, infographic) share this
package.
"""

from __future__ import annotations

from parrot.flows.thales.nodes.bibliography import BibliographyNode, format_apa
from parrot.flows.thales.nodes.deck_builder import DeckBuilderNode
from parrot.flows.thales.nodes.document import FinalDocumentNode
from parrot.flows.thales.nodes.infographic import InfographicNode
from parrot.flows.thales.nodes.planner import PlannerNode
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
]
