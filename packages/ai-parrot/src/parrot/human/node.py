"""HumanDecisionNode — a flow node that pauses for human decisions."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from navconfig.logging import logging

from .models import (
    ConsensusMode,
    HumanInteraction,
    InteractionResult,
    InteractionStatus,
    InteractionType,
)


class HumanDecisionNode:
    """Pseudo-agent that pauses an AgentsFlow for human input.

    Implements the minimal agent interface (``name`` property and
    ``ask()`` coroutine) so it can be wrapped in a ``FlowNode`` and
    participate in the FSM-based workflow like any other agent.

    The human's response becomes the node's result, which downstream
    transition predicates can evaluate to determine branching.

    It also satisfies ``_ensure_agent_ready`` by exposing
    ``is_configured = True``, so the FSM never calls ``configure()``
    on it (which doesn't exist).

    For **multi-human consensus**, either:
    - Set ``target_humans`` and ``consensus_mode`` on the
      ``interaction_config``, or
    - Pass them as constructor kwargs (used when no config is given).

    Usage::

        from parrot.human import (
            HumanDecisionNode, HumanInteraction,
            ConsensusMode, InteractionType,
        )

        # Single approver
        approval_gate = HumanDecisionNode(
            name="approval_gate",
            manager=hitl_manager,
            interaction_config=HumanInteraction(
                question="Approve the research findings?",
                interaction_type=InteractionType.APPROVAL,
                target_humans=["telegram:12345"],
            ),
        )

        # Multi-human majority vote (no interaction_config)
        vote_gate = HumanDecisionNode(
            name="team_vote",
            manager=hitl_manager,
            target_humans=["telegram:111", "telegram:222", "telegram:333"],
            consensus_mode=ConsensusMode.MAJORITY,
        )

    Args:
        name: Unique name for this node within the flow.
        manager: HumanInteractionManager instance.
        interaction_config: Optional pre-configured HumanInteraction.
            If provided, each call to ask() copies it with a fresh
            interaction_id. If not provided, ask() builds a
            FREE_TEXT interaction from the runtime question.
        channel: Channel name to dispatch interactions through.
        target_humans: Default human IDs (used when no interaction_config).
        consensus_mode: How to consolidate multiple responses.
        source_agent: Name of the parent agent (for traceability).
        source_flow: Name of the parent flow (for traceability).
    """

    # Satisfy _ensure_agent_ready — prevents FSM from calling configure()
    is_configured: bool = True

    def __init__(
        self,
        name: str,
        manager: Any,
        interaction_config: Optional[HumanInteraction] = None,
        *,
        channel: str = "telegram",
        target_humans: Optional[List[str]] = None,
        consensus_mode: ConsensusMode = ConsensusMode.FIRST_RESPONSE,
        source_agent: Optional[str] = None,
        source_flow: Optional[str] = None,
    ) -> None:
        self._name = name
        self.manager = manager
        self.interaction_config = interaction_config
        self.channel = channel
        self.target_humans = target_humans or []
        self.consensus_mode = consensus_mode
        self.source_agent = source_agent
        self.source_flow = source_flow
        self.logger = logging.getLogger(f"parrot.human.node.{name}")
        # Attribute expected by FlowNode
        self.tool_manager = None

    @property
    def name(self) -> str:
        return self._name

    async def ask(
        self,
        question: str = "",
        **kwargs: Any,
    ) -> Any:
        """Called by FlowNode.execute() during workflow execution.

        Builds a ``HumanInteraction`` (merging the base config with the
        runtime question), dispatches it through the manager, and returns
        the consolidated human response.

        Each call generates a fresh ``interaction_id`` so that retries
        and loops never collide in Redis.

        Extra kwargs from the FlowNode context are logged but not
        consumed — they come from upstream node results passed by
        the FSM and are typically not relevant for human interactions.
        """
        if self.manager is None:
            raise RuntimeError(
                f"HumanDecisionNode '{self._name}' has no manager configured."
            )

        if kwargs:
            self.logger.debug(
                "Node '%s' received extra context keys: %s",
                self._name,
                list(kwargs.keys()),
            )

        # Build interaction with a FRESH interaction_id each time
        if self.interaction_config is not None:
            interaction = self.interaction_config.model_copy(
                update={
                    "interaction_id": str(uuid4()),
                    "source_node": self._name,
                    "source_agent": (
                        self.source_agent
                        or self.interaction_config.source_agent
                    ),
                    "source_flow": (
                        self.source_flow
                        or self.interaction_config.source_flow
                    ),
                }
            )
            # If the flow provides a dynamic question, append as context
            if question:
                interaction.context = (
                    f"{interaction.context or ''}\n\n"
                    f"Flow context:\n{question}"
                ).strip()
        else:
            # No pre-configured interaction — build from constructor
            # params and runtime question
            interaction = HumanInteraction(
                question=(
                    question
                    or f"Decision needed at node '{self._name}'"
                ),
                interaction_type=InteractionType.FREE_TEXT,
                target_humans=self.target_humans,
                consensus_mode=self.consensus_mode,
                source_node=self._name,
                source_agent=self.source_agent,
                source_flow=self.source_flow,
            )

        self.logger.info(
            "Requesting human decision for node '%s': %s "
            "(targets=%d, consensus=%s)",
            self._name,
            interaction.question,
            len(interaction.target_humans),
            interaction.consensus_mode.value,
        )

        try:
            result: InteractionResult = (
                await self.manager.request_human_input(
                    interaction,
                    channel=self.channel,
                )
            )
        except Exception:
            self.logger.exception(
                "Error requesting human input for node '%s'",
                self._name,
            )
            return None

        if result.escalated:
            self.logger.info(
                "Node '%s' was resolved via escalation.",
                self._name,
            )

        if result.status == InteractionStatus.TIMEOUT:
            self.logger.warning("Node '%s' timed out.", self._name)
            return None

        if result.status == InteractionStatus.CANCELLED:
            self.logger.warning("Node '%s' was cancelled.", self._name)
            return None

        # Warn if consensus returned a conflict dict
        value = result.consolidated_value
        if isinstance(value, dict) and value.get("conflict"):
            self.logger.warning(
                "Node '%s' consensus conflict: %d humans disagreed. "
                "Returning conflict dict for predicate evaluation.",
                self._name,
                len(value.get("responses", [])),
            )

        return value
