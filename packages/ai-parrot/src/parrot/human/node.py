"""HumanDecisionNode — a flow node that pauses for human decisions."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4
from navconfig.logging import logging
from .models import (
    ConsensusMode,
    HumanInteraction,
    InteractionResult,
    InteractionStatus,
    InteractionType,
    Severity,
)

if TYPE_CHECKING:
    from .manager import HumanInteractionManager


class HumanDecisionNode:
    """Pseudo-agent that pauses an AgentsFlow for human input.

    Implements the minimal agent interface (``name`` property and
    ``ask()`` coroutine) so it can be wrapped in a ``FlowNode`` and
    participate in the FSM-based workflow like any other agent.

    The human's response becomes the node's result, which downstream
    transition predicates can evaluate to determine branching.

    On **successful completion**, ``ask()`` returns
    ``result.consolidated_value`` — the raw human answer (bool, str,
    list, dict, etc.).  On **timeout** or **cancellation** it returns
    the full :class:`~parrot.human.models.InteractionResult` so
    predicates can distinguish those states from a normal response by
    inspecting ``result.status``.  On unexpected infrastructure errors
    (e.g. Redis down) it re-raises so the FSM can apply its own failure
    policy rather than silently treating the failure as a blank response.

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
            interaction_type=InteractionType.APPROVAL,
        )

    Args:
        name: Unique name for this node within the flow.
        manager: HumanInteractionManager instance.
        interaction_config: Optional pre-configured HumanInteraction.
            If provided, each call to ask() copies it with a fresh
            interaction_id. If not provided, ask() builds an interaction
            from the runtime question.
        channel: Channel name to dispatch interactions through.
        target_humans: Default human IDs (used when no interaction_config).
        consensus_mode: How to consolidate multiple responses.
        interaction_type: Interaction type for the no-config path
            (default FREE_TEXT). Ignored when interaction_config is given.
        source_agent: Name of the parent agent (for traceability).
        source_flow: Name of the parent flow (for traceability).
        escalation_policy_id: Optional policy ID to attach to the built
            HumanInteraction.  When provided, the manager's escalation
            chain is activated for this interaction.  Constructor kwargs
            take precedence over any value in *interaction_config*.
        severity: Declared criticality level for the built interaction.
            Affects which tier the escalation chain starts at.
            Defaults to :attr:`Severity.NORMAL`.

    Example::

        node = HumanDecisionNode(
            name="hr_approval",
            manager=hitl_manager,
            escalation_policy_id="hr-policy",
            severity=Severity.HIGH,
        )
    """

    is_configured: bool = True  # Satisfies _ensure_agent_ready (FlowNode contract)

    def __init__(
        self,
        name: str,
        manager: Optional[HumanInteractionManager] = None,
        interaction_config: Optional[HumanInteraction] = None,
        *,
        channel: str = "telegram",
        target_humans: Optional[list[str]] = None,
        consensus_mode: ConsensusMode = ConsensusMode.FIRST_RESPONSE,
        interaction_type: InteractionType = InteractionType.FREE_TEXT,
        source_agent: Optional[str] = None,
        source_flow: Optional[str] = None,
        escalation_policy_id: Optional[str] = None,
        severity: Severity = Severity.NORMAL,
    ) -> None:
        self._name = name
        self.manager = manager
        self.interaction_config = interaction_config
        self.channel = channel
        self.target_humans = target_humans or []
        self.consensus_mode = consensus_mode
        self.interaction_type = interaction_type
        self.source_agent = source_agent
        self.source_flow = source_flow
        self.escalation_policy_id: Optional[str] = escalation_policy_id
        self.severity: Severity = severity
        self.logger = logging.getLogger(f"parrot.human.node.{name}")
        # Attribute expected by FlowNode (satisfies duck-typed agent interface)
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
        the result.

        Each call generates a fresh ``interaction_id`` so that retries
        and loops never collide in Redis.

        Returns:
            ``result.consolidated_value`` on successful completion
            (the raw human answer: bool, str, list, dict, etc.).
            The full :class:`~parrot.human.models.InteractionResult` on
            timeout or cancellation, so predicates can distinguish those
            states from a normal response by inspecting ``result.status``.

        Raises:
            RuntimeError: If no manager is configured, or if an
                unexpected infrastructure error occurs (e.g. Redis down).
                The FSM or caller is responsible for applying its own
                failure policy rather than silently receiving ``None``.

        Note:
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

        # Build interaction with a FRESH interaction_id each time.
        # All field updates are consolidated into a single model_copy() call
        # so the original interaction_config is never mutated.
        if self.interaction_config is not None:
            update: dict[str, Any] = {
                "interaction_id": str(uuid4()),
                "source_node": self._name,
                "source_agent": (
                    self.source_agent
                    if self.source_agent is not None
                    else self.interaction_config.source_agent
                ),
                "source_flow": (
                    self.source_flow
                    if self.source_flow is not None
                    else self.interaction_config.source_flow
                ),
                # Constructor kwargs win over interaction_config values
                # (explicit > inherited — mirrors target_humans override pattern)
                "policy_id": (
                    self.escalation_policy_id
                    if self.escalation_policy_id is not None
                    else self.interaction_config.policy_id
                ),
                "severity": (
                    self.severity
                    if self.severity != Severity.NORMAL
                    else self.interaction_config.severity
                ),
            }
            # If the flow provides a dynamic question, append as context
            if question:
                existing = self.interaction_config.context or ""
                update["context"] = (
                    f"{existing}\n\nFlow context:\n{question}"
                ).strip()
            interaction = self.interaction_config.model_copy(update=update)
        else:
            # No pre-configured interaction — build from constructor
            # params and runtime question
            interaction = HumanInteraction(
                question=(
                    question
                    or f"Decision needed at node '{self._name}'"
                ),
                interaction_type=self.interaction_type,
                target_humans=self.target_humans,
                consensus_mode=self.consensus_mode,
                source_node=self._name,
                source_agent=self.source_agent,
                source_flow=self.source_flow,
                policy_id=self.escalation_policy_id,
                severity=self.severity,
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
        except Exception as exc:
            self.logger.exception(
                "Error requesting human input for node '%s'",
                self._name,
            )
            raise RuntimeError(
                f"HumanDecisionNode '{self._name}' failed to obtain human input"
            ) from exc

        if result.escalated:
            self.logger.info(
                "Node '%s' was resolved via escalation.",
                self._name,
            )

        # Return the full InteractionResult for non-completed states so that
        # downstream predicates can distinguish timeout from cancellation.
        if result.status == InteractionStatus.TIMEOUT:
            self.logger.warning("Node '%s' timed out.", self._name)
            return result

        if result.status == InteractionStatus.CANCELLED:
            self.logger.warning("Node '%s' was cancelled.", self._name)
            return result

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
