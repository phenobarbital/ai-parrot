"""flows/flow/nodes.py — Decision + Interactive node types (FEAT-196 / TASK-1311).

Rewrites DecisionFlowNode, InteractiveDecisionNode, and all related types
as subclasses of parrot.bots.flows.core.node.Node (frozen Pydantic).

Public symbol names and attribute shapes are preserved exactly from the
legacy parrot/bots/flow/decision_node.py and interactive_node.py.
Internal implementation adopts NodeResult, FlowContext.shared_data, and
build_node_metadata from the canonical parrot.bots.flows.core package.

Mirrors the layout of parrot/bots/flows/crew/nodes.py — single file
containing all decision + interactive node types for this subpackage.

Classes:
    DecisionMode — Enum: CIO, BALLOT, CONSENSUS
    DecisionType — Enum: BINARY, APPROVAL, MULTI_CHOICE, CUSTOM
    VoteWeight — Enum: EQUAL, SENIORITY, CONFIDENCE, CUSTOM
    BinaryDecision — Pydantic model for YES/NO decisions
    ApprovalDecision — Pydantic model for APPROVE/REJECT/ESCALATE decisions
    MultiChoiceDecision — Pydantic model for multi-option decisions
    DecisionResult — Structured result from a decision node
    EscalationPolicy — Configuration for HITL escalation
    DecisionNodeConfig — Configuration for DecisionFlowNode
    DecisionFlowNode — Multi-agent decision orchestrator (subclasses Node)
    InteractiveDecisionNode — CLI interactive decision node (subclasses Node)
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ..core.context import FlowContext
from ..core.fsm import AgentTaskMachine
from ..core.node import Node
from ..core.result import NodeResult, build_node_metadata
from ..core.types import DependencyResults


# =============================================================================
# Enums (preserved verbatim from legacy decision_node.py)
# =============================================================================


class DecisionMode(str, Enum):
    """Operating mode for decision-making process."""

    CIO = "cio"
    BALLOT = "ballot"
    CONSENSUS = "consensus"


class DecisionType(str, Enum):
    """Types of decisions the node can make."""

    BINARY = "binary"
    APPROVAL = "approval"
    MULTI_CHOICE = "multi_choice"
    CUSTOM = "custom"


class VoteWeight(str, Enum):
    """Pre-defined vote weighting strategies."""

    EQUAL = "equal"
    SENIORITY = "seniority"
    CONFIDENCE = "confidence"
    CUSTOM = "custom"


# =============================================================================
# Decision Schema Models (preserved verbatim from legacy decision_node.py)
# =============================================================================


class BinaryDecision(BaseModel):
    """Binary YES/NO decision schema.

    Attributes:
        decision: The decision value (YES or NO).
        confidence: Confidence level from 0.0 to 1.0.
        reasoning: Explanation for the decision.
    """

    decision: str = Field(pattern="^(YES|NO)$", description="YES or NO")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence level")
    reasoning: str = Field(description="Explanation for the decision")


class ApprovalDecision(BaseModel):
    """Approval gate decision schema.

    Attributes:
        decision: The decision value (APPROVE, REJECT, or ESCALATE).
        confidence: Confidence level from 0.0 to 1.0.
        reasoning: Explanation for the decision.
        escalation_reason: Optional reason for escalation.
    """

    decision: str = Field(
        pattern="^(APPROVE|REJECT|ESCALATE)$",
        description="APPROVE, REJECT, or ESCALATE",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence level")
    reasoning: str = Field(description="Explanation for the decision")
    escalation_reason: Optional[str] = Field(
        None, description="Reason for escalation if applicable"
    )


class MultiChoiceDecision(BaseModel):
    """Multi-option choice decision schema.

    Attributes:
        decision: The chosen option key.
        confidence: Confidence level from 0.0 to 1.0.
        reasoning: Explanation for the decision.
        alternatives_considered: List of other options considered.
    """

    decision: str = Field(description="The chosen option key")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence level")
    reasoning: str = Field(description="Explanation for the decision")
    alternatives_considered: List[str] = Field(
        default_factory=list, description="Other options considered"
    )


# =============================================================================
# Result Models (preserved verbatim from legacy decision_node.py)
# =============================================================================


class DecisionResult(BaseModel):
    """Structured result from a decision node.

    Attributes:
        decision_id: Unique identifier for this decision.
        mode: The decision mode used (CIO, BALLOT, CONSENSUS).
        final_decision: The actual decision value.
        confidence: Overall confidence level (0.0 to 1.0).
        votes: Dict of agent_name -> decision_value.
        vote_distribution: Dict of decision_value -> count.
        consensus_level: Consensus level (UNANIMOUS, MAJORITY, etc.).
        escalated: Whether the decision was escalated to HITL.
        escalation_reason: Reason for escalation if applicable.
        agent_responses: Dict of agent_name -> full response dict.
        execution_time: Total execution time in seconds.
        metadata: Additional metadata.
    """

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    mode: DecisionMode
    final_decision: Any
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    # Voting details (populated for BALLOT/CONSENSUS modes)
    votes: Dict[str, Any] = Field(default_factory=dict)
    vote_distribution: Dict[str, int] = Field(default_factory=dict)
    consensus_level: Optional[str] = None

    # Escalation tracking
    escalated: bool = False
    escalation_reason: Optional[str] = None

    # Audit trail
    agent_responses: Dict[str, Any] = Field(default_factory=dict)
    execution_time: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Configuration Models (preserved verbatim from legacy decision_node.py)
# =============================================================================


class EscalationPolicy(BaseModel):
    """Defines when and how to escalate to HITL.

    Attributes:
        enabled: Whether escalation is enabled.
        on_low_confidence: Confidence threshold below which to escalate.
        on_split_vote: Whether to escalate on evenly split votes.
        on_explicit_keyword: Whether to escalate when decision is ESCALATE.
        hitl_manager: HumanInteractionManager instance (not serialized).
        target_humans: List of human identifiers for escalation.
        timeout_seconds: Timeout for HITL response.
        fallback_decision: Decision to use if HITL unavailable or times out.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    enabled: bool = True

    on_low_confidence: Optional[float] = Field(
        None, description="Escalate if confidence < this value"
    )
    on_split_vote: bool = Field(True, description="Escalate on evenly split votes")
    on_explicit_keyword: bool = Field(True, description="Escalate on ESCALATE keyword")

    hitl_manager: Any = Field(None, exclude=True, description="HumanInteractionManager instance")
    target_humans: List[str] = Field(default_factory=list, description="Human identifiers")
    timeout_seconds: float = Field(7200.0, description="HITL timeout in seconds")

    fallback_decision: Optional[Any] = Field(None, description="Fallback decision value")


class DecisionNodeConfig(BaseModel):
    """Configuration for DecisionFlowNode.

    Attributes:
        mode: Operating mode (CIO, BALLOT, CONSENSUS).
        decision_type: Type of decision (BINARY, APPROVAL, MULTI_CHOICE, CUSTOM).
        decision_schema: Pydantic model for structured output.
        vote_weight_strategy: How to weight votes (for BALLOT/CONSENSUS).
        custom_weights: Custom weight values per agent.
        minimum_votes: Minimum number of votes required (quorum).
        coordinator_agent_name: Name of coordinator agent (for CONSENSUS).
        cross_pollination_rounds: Number of revision rounds (for CONSENSUS).
        escalation_policy: Escalation configuration.
        options: Available options (for MULTI_CHOICE).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    mode: DecisionMode
    decision_type: DecisionType

    decision_schema: Optional[type] = Field(None, exclude=True)

    vote_weight_strategy: VoteWeight = VoteWeight.EQUAL
    custom_weights: Optional[Dict[str, float]] = None
    minimum_votes: Optional[int] = None

    coordinator_agent_name: Optional[str] = None
    cross_pollination_rounds: int = 1

    escalation_policy: Optional[EscalationPolicy] = None

    options: Optional[List[Dict[str, Any]]] = None


# =============================================================================
# DecisionFlowNode — frozen Pydantic Node subclass (FEAT-196 TASK-1311)
# =============================================================================


class DecisionFlowNode(Node):
    """Decision orchestrator node for AgentsFlow workflows.

    Rewritten from legacy parrot.bots.flow.decision_node.DecisionFlowNode
    to subclass parrot.bots.flows.core.node.Node (frozen Pydantic).

    NOT an agent itself — a container that orchestrates multiple agents
    to make decisions. Three operating modes:
    - CIO: Single coordinator agent decides, can escalate to HITL
    - BALLOT: Multiple agents vote, results aggregated with optional weighting
    - CONSENSUS: Agents read each other's decisions, coordinator synthesizes

    The frozen Pydantic model stores per-configuration state as fields.
    Per-run mutable state uses FlowContext.shared_data[self.node_id].

    Args:
        node_id: Unique identifier within the flow graph.
        agents: Dict of agent_name -> agent instances participating in decision.
        config: DecisionNodeConfig with mode and parameters.
        default_question_template: Template for decision prompt if not provided.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Optional pre-constructed FSM (auto-created if None).
    """

    # ── Pydantic fields (frozen — assign in __init__ via model_post_init) ──
    agents: Dict[str, Any] = Field(default_factory=dict)
    """Participating agents. Typed as Dict[str, Any] to allow any agent type."""

    config: DecisionNodeConfig = Field(
        ...,
        description="Decision node configuration (mode, type, weights, etc.)",
    )

    default_question_template: str = Field(
        default="Please make a decision on the following: {question}",
        description="Template for default prompts.",
    )

    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and initialise logger."""
        super().model_post_init(__context)
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier (name == node_id for decision nodes)."""
        return self.node_id

    # ── Public API (mirrors legacy DecisionFlowNode.ask) ─────────────────

    async def ask(
        self,
        question: str = "",
        **ctx: Any,
    ) -> DecisionResult:
        """Execute decision-making process with pre/post action hooks.

        Routes to appropriate decision mode handler and returns
        DecisionResult for transition predicate evaluation.

        Args:
            question: The decision prompt/question.
            **ctx: Context from upstream nodes (session_id, user_id, etc.).

        Returns:
            DecisionResult with final_decision for predicate routing.

        Raises:
            ValueError: If unknown decision mode.
            RuntimeError: If quorum not met or other execution errors.
        """
        start_time = time.time()

        self.logger.info(
            "Decision node %r executing in %s mode",
            self.node_id,
            self.config.mode.value,
        )

        await self.run_pre_actions(prompt=question, **ctx)

        try:
            if self.config.mode == DecisionMode.CIO:
                result = await self._execute_cio_mode(question, ctx)
            elif self.config.mode == DecisionMode.BALLOT:
                result = await self._execute_ballot_mode(question, ctx)
            elif self.config.mode == DecisionMode.CONSENSUS:
                result = await self._execute_consensus_mode(question, ctx)
            else:
                raise ValueError(f"Unknown decision mode: {self.config.mode}")

            result.execution_time = time.time() - start_time
            result.metadata["context"] = ctx

            self.logger.info(
                "Decision node %r completed: %s (confidence=%.2f, time=%.2fs)",
                self.node_id,
                result.final_decision,
                result.confidence,
                result.execution_time,
            )

            await self.run_post_actions(result=result, **ctx)
            return result

        except Exception as exc:
            self.logger.exception("Error in decision node %r: %s", self.node_id, exc)
            raise

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> NodeResult:
        """Execute the decision node within a FlowContext DAG.

        Wraps the ask() result in a NodeResult for uniform handling
        by the AgentsFlow scheduler.

        Args:
            ctx: The current flow execution context.
            deps: Results from completed dependencies.
            **kwargs: Extra execution context forwarded to ask().

        Returns:
            NodeResult wrapping the DecisionResult.
        """
        import time as _time  # noqa: PLC0415

        start = _time.time()
        question = getattr(ctx, "initial_task", "") or ""
        decision_result = await self.ask(question=question, **kwargs)
        elapsed = _time.time() - start

        return NodeResult(
            node_id=self.node_id,
            node_name=self.name,
            task=question,
            result=decision_result,
            metadata=build_node_metadata(
                node_id=self.node_id,
                agent=None,
                response=decision_result,
                output=decision_result.final_decision,
                execution_time=elapsed,
                status="completed",
            ).to_dict(),
            execution_time=elapsed,
        )

    # ── Private implementation (preserved from legacy decision_node.py) ───

    def _validate_config(self) -> None:
        """Validate configuration consistency.

        Raises:
            ValueError: If configuration is invalid.
        """
        if self.config.mode == DecisionMode.CIO:
            if len(self.agents) != 1:
                raise ValueError(
                    f"CIO mode requires exactly 1 agent, got {len(self.agents)}"
                )

        if self.config.mode == DecisionMode.CONSENSUS:
            if not self.config.coordinator_agent_name:
                raise ValueError("CONSENSUS mode requires coordinator_agent_name")
            if self.config.coordinator_agent_name not in self.agents:
                raise ValueError(
                    f"Coordinator '{self.config.coordinator_agent_name}' not in agents"
                )

        if self.config.vote_weight_strategy == VoteWeight.CUSTOM:
            if not self.config.custom_weights:
                raise ValueError("CUSTOM weight strategy requires custom_weights dict")

    async def _execute_cio_mode(
        self, question: str, ctx: Dict[str, Any]
    ) -> DecisionResult:
        """Execute CIO mode: Single coordinator agent makes decision."""
        agent_name = list(self.agents.keys())[0]
        agent = self.agents[agent_name]

        await self._ensure_agent_ready(agent)

        prompt = self._build_decision_prompt(question, ctx)

        kwargs: Dict[str, Any] = {}
        if self.config.decision_schema:
            kwargs["structured_output"] = self.config.decision_schema

        response = await agent.ask(question=prompt, **ctx, **kwargs)

        decision_obj = self._extract_decision(response)

        should_escalate = await self._check_escalation(
            decision_obj, votes={agent_name: decision_obj}
        )

        if should_escalate:
            return await self._escalate_to_hitl(question, ctx, decision_obj)

        return DecisionResult(
            mode=DecisionMode.CIO,
            final_decision=(
                decision_obj.decision
                if hasattr(decision_obj, "decision")
                else decision_obj
            ),
            confidence=(
                decision_obj.confidence
                if hasattr(decision_obj, "confidence")
                else 1.0
            ),
            votes={
                agent_name: (
                    decision_obj.decision
                    if hasattr(decision_obj, "decision")
                    else decision_obj
                )
            },
            agent_responses={
                agent_name: (
                    decision_obj.model_dump()
                    if hasattr(decision_obj, "model_dump")
                    else decision_obj
                )
            },
            escalated=False,
        )

    async def _execute_ballot_mode(
        self, question: str, ctx: Dict[str, Any]
    ) -> DecisionResult:
        """Execute Ballot mode: Multiple agents vote, results aggregated."""
        prompt = self._build_decision_prompt(question, ctx)

        tasks = []
        agent_names = []

        kwargs: Dict[str, Any] = {}
        if self.config.decision_schema:
            kwargs["structured_output"] = self.config.decision_schema

        for agent_name, agent in self.agents.items():
            await self._ensure_agent_ready(agent)
            tasks.append(agent.ask(question=prompt, **ctx, **kwargs))
            agent_names.append(agent_name)

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        votes: Dict[str, Any] = {}
        agent_responses: Dict[str, Any] = {}

        for agent_name, response in zip(agent_names, responses):
            if isinstance(response, Exception):
                self.logger.error("Agent %s failed: %s", agent_name, response)
                continue

            decision_obj = self._extract_decision(response)
            decision_value = (
                decision_obj.decision
                if hasattr(decision_obj, "decision")
                else decision_obj
            )
            votes[agent_name] = decision_value
            agent_responses[agent_name] = (
                decision_obj.model_dump()
                if hasattr(decision_obj, "model_dump")
                else decision_obj
            )

        if self.config.minimum_votes and len(votes) < self.config.minimum_votes:
            raise RuntimeError(
                f"Quorum not met: {len(votes)}/{self.config.minimum_votes} votes"
            )

        final_decision, vote_dist, consensus = self._aggregate_votes(votes)
        confidence = self._calculate_weighted_confidence(agent_responses)

        should_escalate = await self._check_escalation(
            None, votes=votes, vote_distribution=vote_dist
        )

        if should_escalate:
            return await self._escalate_to_hitl(
                question,
                ctx,
                None,
                votes=votes,
                vote_distribution=vote_dist,
                consensus_level=consensus,
            )

        return DecisionResult(
            mode=DecisionMode.BALLOT,
            final_decision=final_decision,
            confidence=confidence,
            votes=votes,
            vote_distribution=vote_dist,
            consensus_level=consensus,
            agent_responses=agent_responses,
            escalated=False,
        )

    async def _execute_consensus_mode(
        self, question: str, ctx: Dict[str, Any]
    ) -> DecisionResult:
        """Execute Consensus mode: Agents read each other's decisions, coordinator synthesizes."""
        coordinator_name = self.config.coordinator_agent_name
        analyst_names = [n for n in self.agents.keys() if n != coordinator_name]

        initial_votes = await self._collect_initial_votes(analyst_names, question, ctx)

        for round_num in range(self.config.cross_pollination_rounds):
            self.logger.info("Cross-pollination round %d", round_num + 1)

            revision_tasks = []
            for agent_name in analyst_names:
                other_votes = {k: v for k, v in initial_votes.items() if k != agent_name}
                revision_prompt = self._build_revision_prompt(
                    question, other_votes, round_num + 1
                )
                agent = self.agents[agent_name]
                kwargs: Dict[str, Any] = {}
                if self.config.decision_schema:
                    kwargs["structured_output"] = self.config.decision_schema
                revision_tasks.append(agent.ask(question=revision_prompt, **ctx, **kwargs))

            revised_responses = await asyncio.gather(*revision_tasks, return_exceptions=True)

            for agent_name, response in zip(analyst_names, revised_responses):
                if not isinstance(response, Exception):
                    decision_obj = self._extract_decision(response)
                    initial_votes[agent_name] = (
                        decision_obj.model_dump()
                        if hasattr(decision_obj, "model_dump")
                        else decision_obj
                    )

        coordinator = self.agents[coordinator_name]
        await self._ensure_agent_ready(coordinator)

        synthesis_prompt = self._build_synthesis_prompt(question, initial_votes)

        kwargs2: Dict[str, Any] = {}
        if self.config.decision_schema:
            kwargs2["structured_output"] = self.config.decision_schema

        final_response = await coordinator.ask(question=synthesis_prompt, **ctx, **kwargs2)

        final_decision_obj = self._extract_decision(final_response)

        vote_decisions: Dict[str, Any] = {}
        for k, v in initial_votes.items():
            if isinstance(v, dict) and "decision" in v:
                vote_decisions[k] = v["decision"]
            elif hasattr(v, "decision"):
                vote_decisions[k] = v.decision
            else:
                vote_decisions[k] = v

        _, vote_dist, consensus = self._aggregate_votes(vote_decisions)

        return DecisionResult(
            mode=DecisionMode.CONSENSUS,
            final_decision=(
                final_decision_obj.decision
                if hasattr(final_decision_obj, "decision")
                else final_decision_obj
            ),
            confidence=(
                final_decision_obj.confidence
                if hasattr(final_decision_obj, "confidence")
                else 1.0
            ),
            votes=vote_decisions,
            vote_distribution=vote_dist,
            consensus_level=consensus,
            agent_responses=initial_votes,
            escalated=False,
            metadata={"coordinator": coordinator_name},
        )

    # ── Helper methods (preserved from legacy decision_node.py) ──────────

    async def _ensure_agent_ready(self, agent: Any) -> None:
        """Ensure agent is configured before execution."""
        if hasattr(agent, "is_configured") and not agent.is_configured:
            if hasattr(agent, "configure"):
                await agent.configure()

    def _extract_decision(self, response: Any) -> Any:
        """Extract decision object from agent response.

        Resolution order:
        1. Pre-parsed structured output on the AIMessage.
        2. The raw decision schema if response is already a matching Pydantic model.
        3. A plain dict that can be coerced into the decision schema.
        4. Fall back to response.content (text) or the raw response.
        """
        schema = self.config.decision_schema

        for attr in ("structured_output", "output"):
            value = getattr(response, attr, None)
            if value is None:
                continue
            if schema and isinstance(value, schema):
                return value
            if isinstance(value, BaseModel):
                return value
            if isinstance(value, dict) and schema:
                try:
                    return schema(**value)
                except Exception:
                    pass

        if schema and isinstance(response, schema):
            return response
        if isinstance(response, BaseModel) and not hasattr(response, "content"):
            return response

        if isinstance(response, dict):
            if schema:
                try:
                    return schema(**response)
                except Exception:
                    return response
            return response

        content = getattr(response, "content", None)
        if content is not None:
            return content

        return response

    def _build_decision_prompt(self, question: str, ctx: Dict[str, Any]) -> str:
        """Build the decision prompt for agents."""
        context_str = self._format_context(ctx)
        return f"""Based on the following information, make a decision:\n\n{question}\n\nContext:\n{context_str}\n"""

    def _build_revision_prompt(
        self, question: str, other_votes: Dict[str, Any], round_num: int
    ) -> str:
        """Build revision prompt for consensus mode."""
        other_votes_str = self._format_other_votes(other_votes)
        return (
            f"Revise your decision considering peer feedback:\n\n"
            f"Original question: {question}\n\n"
            f"Other agents' decisions:\n{other_votes_str}\n\n"
            f"Round {round_num} of {self.config.cross_pollination_rounds}. "
            f"Revise your decision or confirm your original position.\n"
        )

    def _build_synthesis_prompt(
        self, question: str, all_votes: Dict[str, Any]
    ) -> str:
        """Build synthesis prompt for coordinator."""
        votes_str = self._format_other_votes(all_votes)
        return (
            f"As coordinator, synthesize the following decisions into a final decision:\n\n"
            f"Original question: {question}\n\n"
            f"All agents' decisions:\n{votes_str}\n\n"
            f"Provide your final synthesized decision.\n"
        )

    def _format_context(self, ctx: Dict[str, Any]) -> str:
        """Format context dict for prompt."""
        if not ctx:
            return "(No additional context)"
        lines = [
            f"- {key}: {value}"
            for key, value in ctx.items()
            if key not in ("structured_output",)
        ]
        return "\n".join(lines) if lines else "(No additional context)"

    def _format_other_votes(self, votes: Dict[str, Any]) -> str:
        """Format votes dict for prompt."""
        lines = []
        for agent_name, vote in votes.items():
            if isinstance(vote, dict):
                decision = vote.get("decision", vote)
                reasoning = vote.get("reasoning", "")
                confidence = vote.get("confidence", "")
                vote_str = f"{agent_name}: {decision}"
                if confidence:
                    vote_str += f" (confidence: {confidence})"
                if reasoning:
                    vote_str += f"\n  Reasoning: {reasoning}"
                lines.append(vote_str)
            else:
                lines.append(f"{agent_name}: {vote}")
        return "\n".join(lines)

    async def _collect_initial_votes(
        self, analyst_names: List[str], question: str, ctx: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Collect initial votes from analysts in parallel."""
        prompt = self._build_decision_prompt(question, ctx)
        tasks = []
        kwargs: Dict[str, Any] = {}
        if self.config.decision_schema:
            kwargs["structured_output"] = self.config.decision_schema

        for agent_name in analyst_names:
            agent = self.agents[agent_name]
            await self._ensure_agent_ready(agent)
            tasks.append(agent.ask(question=prompt, **ctx, **kwargs))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        votes: Dict[str, Any] = {}
        for agent_name, response in zip(analyst_names, responses):
            if not isinstance(response, Exception):
                decision_obj = self._extract_decision(response)
                votes[agent_name] = (
                    decision_obj.model_dump()
                    if hasattr(decision_obj, "model_dump")
                    else decision_obj
                )
            else:
                self.logger.error("Agent %s failed: %s", agent_name, response)

        return votes

    def _aggregate_votes(
        self, votes: Dict[str, Any]
    ) -> tuple[Any, Dict[str, int], str]:
        """Aggregate votes with optional weighting.

        Returns:
            Tuple of (final_decision, vote_distribution, consensus_level).
        """
        weights = self._get_vote_weights()
        weighted_counts: Dict[Any, float] = {}

        for agent_name, vote in votes.items():
            weight = weights.get(agent_name, 1.0)
            vote_key = str(vote)
            weighted_counts[vote_key] = weighted_counts.get(vote_key, 0.0) + weight

        if not weighted_counts:
            return None, {}, "DIVIDED"

        winner_key = max(weighted_counts.items(), key=lambda x: x[1])[0]

        final_decision = None
        for vote in votes.values():
            if str(vote) == winner_key:
                final_decision = vote
                break

        vote_dist = Counter(str(v) for v in votes.values())

        total_votes = len(votes)
        max_count = max(vote_dist.values())

        if max_count == total_votes:
            consensus = "UNANIMOUS"
        elif max_count >= total_votes * 0.8:
            consensus = "STRONG_MAJORITY"
        elif max_count >= total_votes * 0.6:
            consensus = "MAJORITY"
        elif max_count == total_votes - max_count:
            consensus = "DEADLOCK"
        else:
            consensus = "DIVIDED"

        return final_decision, dict(vote_dist), consensus

    def _get_vote_weights(self) -> Dict[str, float]:
        """Get vote weights based on strategy."""
        if self.config.vote_weight_strategy == VoteWeight.EQUAL:
            return {name: 1.0 for name in self.agents.keys()}
        elif self.config.vote_weight_strategy == VoteWeight.CUSTOM:
            return self.config.custom_weights or {}
        elif self.config.vote_weight_strategy == VoteWeight.SENIORITY:
            return {name: 1.0 / (i + 1) for i, name in enumerate(self.agents.keys())}
        else:
            return {name: 1.0 for name in self.agents.keys()}

    def _calculate_weighted_confidence(self, agent_responses: Dict[str, Any]) -> float:
        """Calculate weighted average confidence from agent responses."""
        confidences = []
        for response in agent_responses.values():
            if isinstance(response, dict):
                conf = response.get("confidence", 1.0)
            elif hasattr(response, "confidence"):
                conf = response.confidence
            else:
                conf = 1.0
            confidences.append(conf)
        return sum(confidences) / len(confidences) if confidences else 1.0

    async def _check_escalation(
        self,
        decision_obj: Optional[Any],
        votes: Optional[Dict[str, Any]] = None,
        vote_distribution: Optional[Dict[str, int]] = None,
    ) -> bool:
        """Check if decision should escalate to HITL."""
        policy = self.config.escalation_policy
        if not policy or not policy.enabled:
            return False

        if decision_obj and policy.on_low_confidence:
            confidence = (
                decision_obj.confidence
                if hasattr(decision_obj, "confidence")
                else 1.0
            )
            if confidence < policy.on_low_confidence:
                self.logger.info("Escalating due to low confidence: %s", confidence)
                return True

        if policy.on_split_vote and vote_distribution:
            counts = sorted(vote_distribution.values(), reverse=True)
            if len(counts) >= 2 and counts[0] == counts[1]:
                self.logger.info("Escalating due to split vote")
                return True

        if policy.on_explicit_keyword and decision_obj:
            decision = (
                decision_obj.decision
                if hasattr(decision_obj, "decision")
                else decision_obj
            )
            if decision == "ESCALATE":
                self.logger.info("Escalating due to explicit ESCALATE decision")
                return True

        return False

    async def _escalate_to_hitl(
        self,
        question: str,
        ctx: Dict[str, Any],
        decision_obj: Optional[Any],
        votes: Optional[Dict[str, Any]] = None,
        vote_distribution: Optional[Dict[str, int]] = None,
        consensus_level: Optional[str] = None,
    ) -> DecisionResult:
        """Escalate decision to Human-in-the-Loop."""
        policy = self.config.escalation_policy

        if not policy or not policy.hitl_manager:
            self.logger.warning(
                "Escalation triggered but no HITL manager configured, using fallback"
            )
            return DecisionResult(
                mode=self.config.mode,
                final_decision=policy.fallback_decision if policy else None,
                confidence=0.0,
                escalated=True,
                escalation_reason="No HITL manager available",
                votes=votes or {},
                agent_responses={},
                vote_distribution=vote_distribution or {},
                consensus_level=consensus_level,
            )

        try:
            from parrot.bots.human import (  # noqa: PLC0415
                HumanDecisionNode,
                HumanInteraction,
            )

            context_parts = [f"Question: {question}"]
            if decision_obj:
                decision_value = (
                    decision_obj.decision
                    if hasattr(decision_obj, "decision")
                    else decision_obj
                )
                confidence = (
                    decision_obj.confidence
                    if hasattr(decision_obj, "confidence")
                    else 1.0
                )
                context_parts.append(
                    f"\nAgent decision: {decision_value} (confidence: {confidence:.2f})"
                )
            if votes:
                context_parts.append(f"\nVotes: {votes}")

            hitl_node = HumanDecisionNode(
                name=f"{self.node_id}_escalation",
                manager=policy.hitl_manager,
                interaction_config=HumanInteraction(
                    question=question,
                    context="\n".join(context_parts),
                    interaction_type=self._map_decision_type_to_interaction(),
                    target_humans=policy.target_humans,
                    timeout=policy.timeout_seconds,
                ),
            )

            human_decision = await hitl_node.ask(question, **ctx)

            if human_decision is None:
                return DecisionResult(
                    mode=self.config.mode,
                    final_decision=policy.fallback_decision,
                    confidence=0.0,
                    escalated=True,
                    escalation_reason="HITL timeout",
                    votes=votes or {},
                    vote_distribution=vote_distribution or {},
                    consensus_level=consensus_level,
                )

            return DecisionResult(
                mode=self.config.mode,
                final_decision=human_decision,
                confidence=1.0,
                escalated=True,
                escalation_reason="Policy-triggered escalation",
                votes=votes or {},
                agent_responses={},
                vote_distribution=vote_distribution or {},
                consensus_level=consensus_level,
                metadata={"hitl_response": human_decision},
            )

        except ImportError:
            self.logger.warning("HITL components not available, using fallback decision")
            return DecisionResult(
                mode=self.config.mode,
                final_decision=policy.fallback_decision,
                confidence=0.0,
                escalated=True,
                escalation_reason="HITL not available",
                votes=votes or {},
                vote_distribution=vote_distribution or {},
                consensus_level=consensus_level,
            )

    def _map_decision_type_to_interaction(self) -> Any:
        """Map DecisionType to InteractionType for HITL."""
        try:
            from parrot.bots.human import InteractionType  # noqa: PLC0415

            if self.config.decision_type == DecisionType.BINARY:
                return InteractionType.SINGLE_CHOICE
            elif self.config.decision_type == DecisionType.APPROVAL:
                return InteractionType.APPROVAL
            elif self.config.decision_type == DecisionType.MULTI_CHOICE:
                return InteractionType.SINGLE_CHOICE
            else:
                return InteractionType.FREE_TEXT
        except ImportError:
            return "single_choice"


# =============================================================================
# InteractiveDecisionNode — frozen Pydantic Node subclass (FEAT-196 TASK-1311)
# =============================================================================


class InteractiveDecisionNode(Node):
    """A Flow node that asks the user a multiple-choice question in the CLI.

    Rewritten from legacy parrot.bots.flow.interactive_node.InteractiveDecisionNode
    to subclass parrot.bots.flows.core.node.Node (frozen Pydantic).

    Instead of using an LLM to decide routing, this node presents a list
    of options directly to the user in the terminal and returns the selection.

    Args:
        node_id: Unique identifier within the flow graph.
        question: The prompt text shown to the user.
        options: A list of string options to choose from.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Optional pre-constructed FSM (auto-created if None).
    """

    question: str = Field(..., description="The prompt text shown to the user.")
    options: List[str] = Field(default_factory=list, description="Options to choose from.")
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and initialise logger."""
        super().model_post_init(__context)
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier (name == node_id for interactive nodes)."""
        return self.node_id

    async def ask(self, question: str = "", **ctx: Any) -> DecisionResult:
        """Prompt the user in the terminal using questionary.

        Ignores the incoming question string, using self.question instead,
        since this node acts as a static menu prompt.

        Args:
            question: Ignored; self.question is used instead.
            **ctx: Execution context forwarded to pre/post actions.

        Returns:
            DecisionResult with the user's selection in final_decision.
        """
        await self.run_pre_actions(prompt=self.question, **ctx)

        loop = asyncio.get_running_loop()

        def _prompt_user() -> str:
            try:
                import questionary  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "questionary is required for InteractiveDecisionNode. "
                    "Install it with: pip install questionary"
                ) from exc
            return questionary.select(self.question, choices=self.options).ask()

        selected_option = await loop.run_in_executor(None, _prompt_user)

        if not selected_option:
            selected_option = "unknown"

        result = DecisionResult(
            mode=DecisionMode.CIO,
            final_decision=selected_option.lower(),
            confidence=1.0,
            votes={self.node_id: selected_option.lower()},
            agent_responses={self.node_id: selected_option},
            metadata={"interactive": True, "raw_selection": selected_option},
        )

        await self.run_post_actions(result=result, **ctx)
        return result

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> NodeResult:
        """Execute the interactive decision node within a FlowContext DAG.

        Wraps the ask() result in a NodeResult for uniform handling
        by the AgentsFlow scheduler.

        Args:
            ctx: The current flow execution context.
            deps: Results from completed dependencies.
            **kwargs: Extra execution context forwarded to ask().

        Returns:
            NodeResult wrapping the DecisionResult.
        """
        import time as _time  # noqa: PLC0415

        start = _time.time()
        decision_result = await self.ask(question=self.question, **kwargs)
        elapsed = _time.time() - start

        return NodeResult(
            node_id=self.node_id,
            node_name=self.name,
            task=self.question,
            result=decision_result,
            metadata=build_node_metadata(
                node_id=self.node_id,
                agent=None,
                response=decision_result,
                output=decision_result.final_decision,
                execution_time=elapsed,
                status="completed",
            ).to_dict(),
            execution_time=elapsed,
        )

    async def configure(self) -> None:
        """No-op — nothing to configure."""


# =============================================================================
# Public __all__
# =============================================================================

__all__ = [
    # Enums
    "DecisionMode",
    "DecisionType",
    "VoteWeight",
    # Decision schema models
    "BinaryDecision",
    "ApprovalDecision",
    "MultiChoiceDecision",
    # Result model
    "DecisionResult",
    # Configuration
    "EscalationPolicy",
    "DecisionNodeConfig",
    # Node types
    "DecisionFlowNode",
    "InteractiveDecisionNode",
]
