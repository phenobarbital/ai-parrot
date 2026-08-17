"""DeckBuilderNode — per-angle OR-join fan-in -> ResearchDeck (FEAT-425 Module 3).

Deterministic aggregation (no LLM): combines one angle's research-node
outputs (TASK-2227 normalizers, JSON-encoded ``list[Finding]``) into one
``ResearchDeck``. Tolerates ANY subset of sources failing — a source is
recorded in ``failed_sources`` rather than aborting the angle; the deck is
dropped (via a sentinel the runner recognizes) only when ALL sources fail.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Set

from pydantic import Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.thales.models import Finding, ResearchAngle, ResearchDeck
from parrot.flows.thales.nodes.registry import register_thales_node

#: Sentinel key: when present (and truthy) in a DeckBuilderNode's JSON
#: output, the runner (TASK-2231) drops the deck and logs the warning
#: instead of adding it to `ThalesResult.decks`.
DROPPED_DECK_SENTINEL = "_thales_dropped_deck"


@register_thales_node("thales.deck_builder")
class DeckBuilderNode(Node):
    """OR-join fan-in: one angle's research node outputs -> ``ResearchDeck``.

    Args:
        node_id: Unique identifier within the graph.
        angle: The research angle this deck answers.
        sources: Per-angle dependency labels expected in ``deps`` (default
            ``["web", "deep", "arxiv"]`` — TASK-2231 wires the actual
            per-angle research node_ids to match these labels).
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if ``None``.
    """

    node_id: str
    angle: ResearchAngle
    sources: list[str] = Field(default_factory=lambda: ["web", "deep", "arxiv"])
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook."""
        if self.fsm is None:
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

    @property
    def name(self) -> str:
        """Node identifier."""
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> str:
        """Build a ``ResearchDeck`` from the surviving sources (OR-join).

        Args:
            ctx: The current flow execution context (unused — this node
                is pure aggregation, no LLM call).
            deps: Mapping of source label -> that research node's raw
                ``execute()`` output: a JSON-encoded ``list[Finding]`` on
                success, or any non-parseable string (e.g. an upstream
                exception marker) on failure — both degrade the same way.

        Returns:
            The ``ResearchDeck`` as JSON, or the drop-sentinel JSON when
            every source failed.
        """
        findings: list[Finding] = []
        tools_used: list[str] = []
        failed_sources: list[str] = []

        for source in self.sources:
            raw = deps.get(source)
            source_findings = self._parse_findings(raw)
            if source_findings is None:
                failed_sources.append(source)
                continue
            findings.extend(source_findings)
            tools_used.append(source)

        if not findings:
            return json.dumps(
                {
                    DROPPED_DECK_SENTINEL: True,
                    "angle_id": self.angle.angle_id,
                    "failed_sources": failed_sources,
                }
            )

        deck = ResearchDeck(
            angle=self.angle,
            findings=findings,
            tools_used=tools_used,
            failed_sources=failed_sources,
        )
        return deck.model_dump_json()

    @staticmethod
    def _parse_findings(raw: Optional[str]) -> Optional[list[Finding]]:
        """Parse a research node's raw output into ``Finding``s, or ``None`` on failure."""
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, list):
            return None
        try:
            return [Finding.model_validate(item) for item in payload]
        except Exception:  # noqa: BLE001 - any malformed item degrades the source
            return None
