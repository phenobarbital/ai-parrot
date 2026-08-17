"""PlannerNode — thesis -> ResearchAngles (FEAT-425 Module 3).

Splits the user's thesis into a configurable number of research angles via
LLM structured output. Never silently proceeds with fewer than
``config.num_decks`` angles (spec §7 risk): a short first response triggers
exactly ONE explicit re-prompt, then deterministic padding by decomposing
the widest (first) angle — no generic retry framework.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Set

from pydantic import BaseModel, Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.thales.models import ResearchAngle, ThalesConfig
from parrot.flows.thales.nodes.registry import register_thales_node


class _AnglesEnvelope(BaseModel):
    """Structured-output envelope: a plain list is not itself annotatable."""

    angles: list[ResearchAngle] = Field(default_factory=list)


def _extract_angles(message: Any) -> list[ResearchAngle]:
    """Extract the ``_AnglesEnvelope.angles`` list from a client response.

    ``AbstractClient.ask(..., structured_output=_AnglesEnvelope)`` populates
    ``AIMessage.structured_output`` (or, for some client paths, ``.data``).
    """
    for attr in ("structured_output", "data"):
        candidate = getattr(message, attr, None)
        if isinstance(candidate, _AnglesEnvelope):
            return list(candidate.angles)
        if isinstance(candidate, dict):
            return list(_AnglesEnvelope.model_validate(candidate).angles)
    raise ValueError("Client response did not contain a structured angles list.")


def _build_prompt(thesis: str, count: int, *, retry: bool) -> str:
    """Build the planner prompt, explicit about the required angle count."""
    base = (
        f"Thesis: {thesis!r}\n\n"
        f"Split this thesis into exactly {count} distinct research angles. "
        "Each angle needs an angle_id, a short title, a specific sub-thesis "
        "question, and a rationale for why it matters."
    )
    if retry:
        base += (
            f"\n\nYour previous response returned fewer than {count} angles. "
            f"Return AT LEAST {count} angles this time — this is a hard "
            "requirement."
        )
    return base


@register_thales_node("thales.planner")
class PlannerNode(Node):
    """Thesis -> ``list[ResearchAngle]`` (LLM structured output).

    Args:
        node_id: Unique identifier within the graph.
        config: The run's :class:`ThalesConfig` (thesis + ``num_decks`` floor).
        client: An ``AbstractClient``-like object exposing an async
            ``ask(prompt, *, structured_output=...)`` method. Injected via
            ``node_factories`` (TASK-2231) — this class never constructs
            its own client.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if ``None``.
    """

    node_id: str
    config: ThalesConfig
    client: Any
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
        """Produce ``>= config.num_decks`` research angles.

        Returns:
            A JSON-encoded list of ``ResearchAngle`` dicts.
        """
        angles = await self._plan_angles()
        return json.dumps([angle.model_dump(mode="json") for angle in angles])

    async def _plan_angles(self) -> list[ResearchAngle]:
        """Run the plan-then-degrade sequence described in the module docstring."""
        target = self.config.num_decks
        angles = await self._ask_for_angles(target, retry=False)
        if len(angles) < target:
            angles = await self._ask_for_angles(target, retry=True)
        if len(angles) < target:
            angles = self._pad_by_decomposition(angles, target)
        return angles

    async def _ask_for_angles(self, count: int, *, retry: bool) -> list[ResearchAngle]:
        prompt = _build_prompt(self.config.thesis, count, retry=retry)
        message = await self.client.ask(prompt, structured_output=_AnglesEnvelope)
        return _extract_angles(message)

    def _pad_by_decomposition(
        self, angles: list[ResearchAngle], target: int
    ) -> list[ResearchAngle]:
        """Deterministically decompose the widest angle until ``len >= target``.

        Never silently proceeds with fewer than ``target`` angles (spec §7).
        """
        padded = list(angles)
        if not padded:
            padded = [
                ResearchAngle(
                    angle_id="angle-1",
                    title=self.config.thesis,
                    question=self.config.thesis,
                    rationale="Fallback angle — planner returned no angles.",
                )
            ]
        base = padded[0]
        index = 1
        while len(padded) < target:
            padded.append(
                ResearchAngle(
                    angle_id=f"{base.angle_id}-sub{index}",
                    title=f"{base.title} (sub-angle {index})",
                    question=f"{base.question} — sub-aspect {index}",
                    rationale=(
                        f"Decomposed from '{base.title}' to satisfy the "
                        f"minimum deck count of {target}."
                    ),
                )
            )
            index += 1
        return padded
