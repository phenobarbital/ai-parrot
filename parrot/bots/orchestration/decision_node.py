"""DecisionFlowNode — Multi-agent decision orchestrator for AgentsFlow workflows.

This module provides a consensus-based decision component that integrates with
the AgentsFlow FSM system. It enables multi-agent decision-making, voting, and
escalation to Human-in-the-Loop for critical decisions.
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from navconfig.logging import logging
from pydantic import BaseModel, Field

from ..abstract import AbstractBot
from ..agent import BasicAgent
from ...tools.manager import ToolManager


# =============================================================================
# Enums
# =============================================================================


class DecisionMode(str, Enum):
    """Operating mode for decision-making process."""

    CIO = "cio"  # Single coordinator, can escalate to HITL
    BALLOT = "ballot"  # Multi-agent voting with optional weights
    CONSENSUS = "consensus"  # Agents read each other's decisions, coordinator synthesizes


class DecisionType(str, Enum):
    """Types of decisions the node can make."""

    BINARY = "binary"  # YES/NO
    APPROVAL = "approval"  # APPROVE/REJECT/ESCALATE
    MULTI_CHOICE = "multi_choice"  # Option A/B/C/D...
    CUSTOM = "custom"  # Custom Pydantic model


class VoteWeight(str, Enum):
    """Pre-defined vote weighting strategies."""

    EQUAL = "equal"  # All votes equal weight
    SENIORITY = "seniority"  # Weight by agent order (first = highest)
    CONFIDENCE = "confidence"  # Weight by confidence score in response
    CUSTOM = "custom"  # Custom weights dict


# =============================================================================
# Decision Schema Models (for structured LLM output)
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
        pattern="^(APPROVE|REJECT|ESCALATE)$", description="APPROVE, REJECT, or ESCALATE"
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
# Result Models
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
# Configuration Models
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

    enabled: bool = True

    # Trigger conditions
    on_low_confidence: Optional[float] = Field(
        None, description="Escalate if confidence < this value"
    )
    on_split_vote: bool = Field(True, description="Escalate on evenly split votes")
    on_explicit_keyword: bool = Field(True, description="Escalate on ESCALATE keyword")

    # HITL configuration
    hitl_manager: Any = Field(None, exclude=True, description="HumanInteractionManager instance")
    target_humans: List[str] = Field(default_factory=list, description="Human identifiers")
    timeout_seconds: float = Field(7200.0, description="HITL timeout in seconds")

    # Fallback
    fallback_decision: Optional[Any] = Field(None, description="Fallback decision value")

    class Config:
        arbitrary_types_allowed = True


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

    mode: DecisionMode
    decision_type: DecisionType

    # Decision schema
    decision_schema: Optional[type[BaseModel]] = Field(None, exclude=True)

    # Voting configuration
    vote_weight_strategy: VoteWeight = VoteWeight.EQUAL
    custom_weights: Optional[Dict[str, float]] = None
    minimum_votes: Optional[int] = None

    # Consensus configuration
    coordinator_agent_name: Optional[str] = None
    cross_pollination_rounds: int = 1

    # Escalation
    escalation_policy: Optional[EscalationPolicy] = None

    # Decision options
    options: Optional[List[Dict[str, Any]]] = None

    class Config:
        arbitrary_types_allowed = True


# =============================================================================
# DecisionFlowNode
# =============================================================================


class DecisionFlowNode:
    """Decision orchestrator node for AgentsFlow workflows.

    NOT an agent itself - a container that orchestrates multiple agents
    to make decisions. FSM-compatible via duck typing (name, ask(),
    tool_manager, is_configured).

    Three operating modes:
    - CIO: Single coordinator agent decides, can escalate to HITL
    - BALLOT: Multiple agents vote, results aggregated with optional weighting
    - CONSENSUS: Agents read each other's decisions, coordinator synthesizes

    Example Usage:
        # CIO Mode - single decision maker with escalation
        admin_gate = DecisionFlowNode(
            name="admin_approval_gate",
            agents={"approver": approval_agent},
            config=DecisionNodeConfig(
                mode=DecisionMode.CIO,
                decision_type=DecisionType.BINARY,
                decision_schema=BinaryDecision,
                escalation_policy=EscalationPolicy(
                    on_low_confidence=0.7,
                    fallback_decision="NO"
                )
            )
        )

        # Ballot Mode - weighted voting
        investment_committee = DecisionFlowNode(
            name="investment_vote",
            agents={
                "macro": macro_agent,
                "risk": risk_agent,
                "technical": technical_agent
            },
            config=DecisionNodeConfig(
                mode=DecisionMode.BALLOT,
                decision_type=DecisionType.APPROVAL,
                decision_schema=ApprovalDecision,
                vote_weight_strategy=VoteWeight.CUSTOM,
                custom_weights={"risk": 1.5, "macro": 1.2, "technical": 1.0}
            )
        )

    Args:
        name: Unique identifier for this decision node.
        agents: Dict of agent_name -> agent instances participating in decision.
        config: DecisionNodeConfig with mode and parameters.
        shared_tool_manager: Optional shared ToolManager (for compatibility).
        default_question_template: Template for decision prompt if not provided.
    """

    # FSM compatibility attributes
    is_configured: bool = True  # Bypass FSM configuration
    tool_manager: Optional[ToolManager] = None

    def __init__(
        self,
        name: str,
        agents: Dict[str, Union[BasicAgent, AbstractBot]],
        config: DecisionNodeConfig,
        shared_tool_manager: Optional[ToolManager] = None,
        default_question_template: Optional[str] = None,
    ):
        """Initialize the DecisionFlowNode.

        Args:
            name: Unique identifier for this decision node.
            agents: Dict of agent_name -> agent instances.
            config: Configuration for the decision node.
            shared_tool_manager: Optional shared ToolManager.
            default_question_template: Template for default prompts.
        """
        self._name = name
        self.agents = agents
        self.config = config
        self.tool_manager = shared_tool_manager
        self.default_question_template = default_question_template or (
            "Please make a decision on the following: {question}"
        )
        self.logger = logging.getLogger(f"parrot.decision_node.{name}")

        # Validate configuration
        self._validate_config()

    @property
    def name(self) -> str:
        """Agent name property (required by FSM)."""
        return self._name

    async def ask(
        self,
        question: str = "",
        **ctx: Any,
    ) -> DecisionResult:
        """Execute decision-making process (called by FlowNode.execute()).

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
            f"Decision node '{self._name}' executing in {self.config.mode.value} mode"
        )

        try:
            # Route to appropriate decision mode
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
                f"Decision node '{self._name}' completed: {result.final_decision} "
                f"(confidence={result.confidence:.2f}, time={result.execution_time:.2f}s)"
            )

            return result

        except Exception as e:
            self.logger.exception(f"Error in decision node '{self._name}'")
            raise

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
        """Execute CIO mode: Single coordinator agent makes decision.

        Can escalate to HITL based on escalation policy.

        Args:
            question: The decision question.
            ctx: Execution context.

        Returns:
            DecisionResult with final decision.
        """
        agent_name = list(self.agents.keys())[0]
        agent = self.agents[agent_name]

        # Ensure agent is configured
        await self._ensure_agent_ready(agent)

        # Execute decision
        prompt = self._build_decision_prompt(question, ctx)

        kwargs = {}
        if self.config.decision_schema:
            kwargs["structured_output"] = self.config.decision_schema

        response = await agent.ask(question=prompt, **ctx, **kwargs)

        # Extract decision
        decision_obj = self._extract_decision(response)

        # Check escalation policy
        should_escalate = await self._check_escalation(
            decision_obj, votes={agent_name: decision_obj}
        )

        if should_escalate:
            return await self._escalate_to_hitl(question, ctx, decision_obj)

        return DecisionResult(
            mode=DecisionMode.CIO,
            final_decision=decision_obj.decision if hasattr(decision_obj, "decision") else decision_obj,
            confidence=decision_obj.confidence if hasattr(decision_obj, "confidence") else 1.0,
            votes={agent_name: decision_obj.decision if hasattr(decision_obj, "decision") else decision_obj},
            agent_responses={agent_name: decision_obj.model_dump() if hasattr(decision_obj, "model_dump") else decision_obj},
            escalated=False,
        )

    async def _execute_ballot_mode(
        self, question: str, ctx: Dict[str, Any]
    ) -> DecisionResult:
        """Execute Ballot mode: Multiple agents vote, results aggregated with weighting.

        Args:
            question: The decision question.
            ctx: Execution context.

        Returns:
            DecisionResult with aggregated vote results.

        Raises:
            RuntimeError: If quorum not met.
        """
        # Execute all agents in parallel
        prompt = self._build_decision_prompt(question, ctx)

        tasks = []
        agent_names = []

        kwargs = {}
        if self.config.decision_schema:
            kwargs["structured_output"] = self.config.decision_schema

        for agent_name, agent in self.agents.items():
            await self._ensure_agent_ready(agent)
            tasks.append(agent.ask(question=prompt, **ctx, **kwargs))
            agent_names.append(agent_name)

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect votes
        votes: Dict[str, Any] = {}
        agent_responses: Dict[str, Any] = {}

        for agent_name, response in zip(agent_names, responses):
            if isinstance(response, Exception):
                self.logger.error(f"Agent {agent_name} failed: {response}")
                continue

            decision_obj = self._extract_decision(response)
            decision_value = decision_obj.decision if hasattr(decision_obj, "decision") else decision_obj
            votes[agent_name] = decision_value
            agent_responses[agent_name] = (
                decision_obj.model_dump() if hasattr(decision_obj, "model_dump") else decision_obj
            )

        # Check quorum
        if self.config.minimum_votes and len(votes) < self.config.minimum_votes:
            raise RuntimeError(
                f"Quorum not met: {len(votes)}/{self.config.minimum_votes} votes"
            )

        # Aggregate votes with weighting
        final_decision, vote_dist, consensus = self._aggregate_votes(votes)

        # Calculate weighted confidence
        confidence = self._calculate_weighted_confidence(agent_responses)

        # Check escalation
        should_escalate = await self._check_escalation(
            None, votes=votes, vote_distribution=vote_dist
        )

        if should_escalate:
            return await self._escalate_to_hitl(question, ctx, None, votes=votes)

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
        """Execute Consensus mode: Agents read each other's decisions, coordinator synthesizes.

        Args:
            question: The decision question.
            ctx: Execution context.

        Returns:
            DecisionResult with coordinator's final decision.
        """
        coordinator_name = self.config.coordinator_agent_name
        analyst_names = [n for n in self.agents.keys() if n != coordinator_name]

        # Phase 1: Initial votes (parallel)
        initial_votes = await self._collect_initial_votes(analyst_names, question, ctx)

        # Phase 2: Cross-pollination rounds
        for round_num in range(self.config.cross_pollination_rounds):
            self.logger.info(f"Cross-pollination round {round_num + 1}")

            # Each agent sees all other votes and can revise
            revision_tasks = []
            for agent_name in analyst_names:
                other_votes = {k: v for k, v in initial_votes.items() if k != agent_name}

                revision_prompt = self._build_revision_prompt(
                    question, other_votes, round_num + 1
                )

                agent = self.agents[agent_name]

                kwargs = {}
                if self.config.decision_schema:
                    kwargs["structured_output"] = self.config.decision_schema

                revision_tasks.append(agent.ask(question=revision_prompt, **ctx, **kwargs))

            revised_responses = await asyncio.gather(*revision_tasks, return_exceptions=True)

            # Update votes with revisions
            for agent_name, response in zip(analyst_names, revised_responses):
                if not isinstance(response, Exception):
                    decision_obj = self._extract_decision(response)
                    initial_votes[agent_name] = (
                        decision_obj.model_dump() if hasattr(decision_obj, "model_dump") else decision_obj
                    )

        # Phase 3: Coordinator synthesis
        coordinator = self.agents[coordinator_name]
        await self._ensure_agent_ready(coordinator)

        synthesis_prompt = self._build_synthesis_prompt(question, initial_votes)

        kwargs = {}
        if self.config.decision_schema:
            kwargs["structured_output"] = self.config.decision_schema

        final_response = await coordinator.ask(question=synthesis_prompt, **ctx, **kwargs)

        final_decision_obj = self._extract_decision(final_response)

        # Aggregate for consensus level
        vote_decisions = {}
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
            final_decision=final_decision_obj.decision if hasattr(final_decision_obj, "decision") else final_decision_obj,
            confidence=final_decision_obj.confidence if hasattr(final_decision_obj, "confidence") else 1.0,
            votes=vote_decisions,
            vote_distribution=vote_dist,
            consensus_level=consensus,
            agent_responses=initial_votes,
            escalated=False,
            metadata={"coordinator": coordinator_name},
        )

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _ensure_agent_ready(self, agent: Union[BasicAgent, AbstractBot]) -> None:
        """Ensure agent is configured before execution.

        Args:
            agent: The agent to configure.
        """
        if hasattr(agent, "is_configured") and not agent.is_configured:
            if hasattr(agent, "configure"):
                await agent.configure()

    def _extract_decision(self, response: Any) -> Any:
        """Extract decision object from agent response.

        Args:
            response: The agent response.

        Returns:
            The extracted decision object.
        """
        # Handle different response types
        if isinstance(response, BaseModel):
            return response
        elif hasattr(response, "content"):
            # AIMessage or similar
            return response.content
        elif isinstance(response, dict):
            # Try to parse as decision schema
            if self.config.decision_schema:
                try:
                    return self.config.decision_schema(**response)
                except Exception:
                    return response
            return response
        else:
            return response

    def _build_decision_prompt(self, question: str, ctx: Dict[str, Any]) -> str:
        """Build the decision prompt for agents.

        Args:
            question: The decision question.
            ctx: Execution context.

        Returns:
            The formatted prompt.
        """
        context_str = self._format_context(ctx)

        prompt = f"""Based on the following information, make a decision:

{question}

Context:
{context_str}
"""
        return prompt

    def _build_revision_prompt(
        self, question: str, other_votes: Dict[str, Any], round_num: int
    ) -> str:
        """Build revision prompt for consensus mode.

        Args:
            question: The original question.
            other_votes: Votes from other agents.
            round_num: Current revision round number.

        Returns:
            The formatted revision prompt.
        """
        other_votes_str = self._format_other_votes(other_votes)

        prompt = f"""Revise your decision considering peer feedback:

Original question: {question}

Other agents' decisions:
{other_votes_str}

Round {round_num} of {self.config.cross_pollination_rounds}. Revise your decision or confirm your original position.
"""
        return prompt

    def _build_synthesis_prompt(
        self, question: str, all_votes: Dict[str, Any]
    ) -> str:
        """Build synthesis prompt for coordinator.

        Args:
            question: The original question.
            all_votes: All agent votes.

        Returns:
            The formatted synthesis prompt.
        """
        votes_str = self._format_other_votes(all_votes)

        prompt = f"""As coordinator, synthesize the following decisions into a final decision:

Original question: {question}

All agents' decisions:
{votes_str}

Provide your final synthesized decision.
"""
        return prompt

    def _format_context(self, ctx: Dict[str, Any]) -> str:
        """Format context dict for prompt.

        Args:
            ctx: The context dict.

        Returns:
            Formatted context string.
        """
        if not ctx:
            return "(No additional context)"

        lines = []
        for key, value in ctx.items():
            if key not in ["structured_output"]:  # Skip internal keys
                lines.append(f"- {key}: {value}")

        return "\n".join(lines) if lines else "(No additional context)"

    def _format_other_votes(self, votes: Dict[str, Any]) -> str:
        """Format votes dict for prompt.

        Args:
            votes: The votes dict.

        Returns:
            Formatted votes string.
        """
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
        """Collect initial votes from analysts in parallel.

        Args:
            analyst_names: Names of analyst agents.
            question: The decision question.
            ctx: Execution context.

        Returns:
            Dict of agent_name -> vote response.
        """
        prompt = self._build_decision_prompt(question, ctx)

        tasks = []
        kwargs = {}
        if self.config.decision_schema:
            kwargs["structured_output"] = self.config.decision_schema

        for agent_name in analyst_names:
            agent = self.agents[agent_name]
            await self._ensure_agent_ready(agent)
            tasks.append(agent.ask(question=prompt, **ctx, **kwargs))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        votes = {}
        for agent_name, response in zip(analyst_names, responses):
            if not isinstance(response, Exception):
                decision_obj = self._extract_decision(response)
                votes[agent_name] = (
                    decision_obj.model_dump() if hasattr(decision_obj, "model_dump") else decision_obj
                )
            else:
                self.logger.error(f"Agent {agent_name} failed: {response}")

        return votes

    def _aggregate_votes(
        self, votes: Dict[str, Any]
    ) -> tuple[Any, Dict[str, int], str]:
        """Aggregate votes with optional weighting.

        Args:
            votes: Dict of agent_name -> decision_value.

        Returns:
            Tuple of (final_decision, vote_distribution, consensus_level).
        """
        weights = self._get_vote_weights()

        # Count weighted votes
        weighted_counts: Dict[Any, float] = {}

        for agent_name, vote in votes.items():
            weight = weights.get(agent_name, 1.0)
            # Convert vote to hashable key
            vote_key = str(vote)
            weighted_counts[vote_key] = weighted_counts.get(vote_key, 0.0) + weight

        # Find winner
        if not weighted_counts:
            return None, {}, "DIVIDED"

        winner_key = max(weighted_counts.items(), key=lambda x: x[1])[0]

        # Get actual vote value (find first matching vote)
        final_decision = None
        for vote in votes.values():
            if str(vote) == winner_key:
                final_decision = vote
                break

        # Calculate distribution (unweighted for clarity)
        vote_dist = Counter(str(v) for v in votes.values())

        # Determine consensus level
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
        """Get vote weights based on strategy.

        Returns:
            Dict of agent_name -> weight.
        """
        if self.config.vote_weight_strategy == VoteWeight.EQUAL:
            return {name: 1.0 for name in self.agents.keys()}

        elif self.config.vote_weight_strategy == VoteWeight.CUSTOM:
            return self.config.custom_weights or {}

        elif self.config.vote_weight_strategy == VoteWeight.SENIORITY:
            # First agent gets highest weight
            weights = {}
            for i, name in enumerate(self.agents.keys()):
                weights[name] = 1.0 / (i + 1)
            return weights

        elif self.config.vote_weight_strategy == VoteWeight.CONFIDENCE:
            # Weights determined at runtime from agent responses
            # (handled separately in aggregation)
            return {name: 1.0 for name in self.agents.keys()}

        else:
            return {name: 1.0 for name in self.agents.keys()}

    def _calculate_weighted_confidence(self, agent_responses: Dict[str, Any]) -> float:
        """Calculate weighted average confidence from agent responses.

        Args:
            agent_responses: Dict of agent_name -> response dict.

        Returns:
            Weighted average confidence (0.0 to 1.0).
        """
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
        decision_obj: Optional[BaseModel],
        votes: Optional[Dict[str, Any]] = None,
        vote_distribution: Optional[Dict[str, int]] = None,
    ) -> bool:
        """Check if decision should escalate to HITL.

        Args:
            decision_obj: The decision object from agent.
            votes: Dict of votes (for ballot mode).
            vote_distribution: Vote distribution (for split vote detection).

        Returns:
            True if escalation should occur, False otherwise.
        """
        policy = self.config.escalation_policy
        if not policy or not policy.enabled:
            return False

        # Check low confidence
        if decision_obj and policy.on_low_confidence:
            confidence = decision_obj.confidence if hasattr(decision_obj, "confidence") else 1.0
            if confidence < policy.on_low_confidence:
                self.logger.info(f"Escalating due to low confidence: {confidence}")
                return True

        # Check split vote
        if policy.on_split_vote and vote_distribution:
            counts = sorted(vote_distribution.values(), reverse=True)
            if len(counts) >= 2 and counts[0] == counts[1]:
                self.logger.info("Escalating due to split vote")
                return True

        # Check explicit escalation
        if policy.on_explicit_keyword and decision_obj:
            decision = decision_obj.decision if hasattr(decision_obj, "decision") else decision_obj
            if decision == "ESCALATE":
                self.logger.info("Escalating due to explicit ESCALATE decision")
                return True

        return False

    async def _escalate_to_hitl(
        self,
        question: str,
        ctx: Dict[str, Any],
        decision_obj: Optional[BaseModel],
        votes: Optional[Dict[str, Any]] = None,
    ) -> DecisionResult:
        """Escalate decision to Human-in-the-Loop.

        Creates HumanDecisionNode on-the-fly and executes it.

        Args:
            question: The decision question.
            ctx: Execution context.
            decision_obj: The agent's decision object.
            votes: Vote dict (for ballot mode).

        Returns:
            DecisionResult with escalated decision.
        """
        policy = self.config.escalation_policy

        if not policy or not policy.hitl_manager:
            self.logger.warning(
                "Escalation triggered but no HITL manager configured, using fallback decision"
            )
            return DecisionResult(
                mode=self.config.mode,
                final_decision=policy.fallback_decision if policy else None,
                confidence=0.0,
                escalated=True,
                escalation_reason="No HITL manager available",
                votes=votes or {},
                agent_responses={},
            )

        try:
            from ...human import HumanDecisionNode, HumanInteraction, InteractionType

            # Build context for human
            context_parts = [f"Question: {question}"]
            if decision_obj:
                decision_value = decision_obj.decision if hasattr(decision_obj, "decision") else decision_obj
                confidence = decision_obj.confidence if hasattr(decision_obj, "confidence") else 1.0
                context_parts.append(
                    f"\nAgent decision: {decision_value} (confidence: {confidence:.2f})"
                )
            if votes:
                context_parts.append(f"\nVotes: {votes}")

            # Create HITL node
            hitl_node = HumanDecisionNode(
                name=f"{self._name}_escalation",
                manager=policy.hitl_manager,
                interaction_config=HumanInteraction(
                    question=question,
                    context="\n".join(context_parts),
                    interaction_type=self._map_decision_type_to_interaction(),
                    target_humans=policy.target_humans,
                    timeout=policy.timeout_seconds,
                ),
            )

            # Execute HITL decision
            human_decision = await hitl_node.ask(question, **ctx)

            if human_decision is None:
                # Timeout or cancellation - use fallback
                return DecisionResult(
                    mode=self.config.mode,
                    final_decision=policy.fallback_decision,
                    confidence=0.0,
                    escalated=True,
                    escalation_reason="HITL timeout",
                    votes=votes or {},
                )

            return DecisionResult(
                mode=self.config.mode,
                final_decision=human_decision,
                confidence=1.0,  # Human decision has full confidence
                escalated=True,
                escalation_reason="Policy-triggered escalation",
                votes=votes or {},
                agent_responses={},
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
            )

    def _map_decision_type_to_interaction(self):
        """Map DecisionType to InteractionType for HITL.

        Returns:
            InteractionType enum value.
        """
        try:
            from ...human import InteractionType

            if self.config.decision_type == DecisionType.BINARY:
                return InteractionType.SINGLE_CHOICE
            elif self.config.decision_type == DecisionType.APPROVAL:
                return InteractionType.APPROVAL
            elif self.config.decision_type == DecisionType.MULTI_CHOICE:
                return InteractionType.SINGLE_CHOICE
            else:
                return InteractionType.FREE_TEXT
        except ImportError:
            return "single_choice"  # Fallback string
