"""
A2A Hybrid Orchestrator - Combines rule-based routing with LLM-driven orchestration.

This module provides an intelligent orchestrator that uses deterministic rules
when possible (fast, zero cost) and falls back to LLM-based decision making
for complex scenarios requiring reasoning about which agents to use.

Key Features:
    - Rule-based routing (via A2AProxyRouter) for known patterns
    - LLM fallback for complex/ambiguous requests
    - Parallel execution across multiple agents
    - Sequential pipelines with output chaining
    - Automatic agent selection based on skills and capabilities
    - Comprehensive statistics and observability

Example:
    # Setup
    mesh = A2AMeshDiscovery()
    await mesh.start()

    orchestrator = A2AOrchestrator(mesh)

    # Configure rules (tried first - fast, no cost)
    orchestrator.route_by_skill("data_analysis", "DataBot")
    orchestrator.route_by_tag("support", "SupportBot")

    # Configure LLM fallback (for complex decisions)
    orchestrator.set_fallback_llm(llm_client)

    # Execute - uses rules if possible, LLM if needed
    result = await orchestrator.run(
        "Analyze sales data and create a customer report",
        mode=OrchestrationMode.HYBRID
    )
"""
from __future__ import annotations
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
    TYPE_CHECKING,
)
import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pydantic import BaseModel, Field
from navconfig.logging import logging
from .client import A2AClient
from .mesh import A2AMeshDiscovery, RegisteredAgent
from .router import A2AProxyRouter
from .models import (
    Task,
    TaskState,
)
if TYPE_CHECKING:
    from ..clients.base import AbstractClient


class OrchestrationMode(str, Enum):
    """Mode of orchestration."""

    RULES_ONLY = "rules"        # Only use routing rules, fail if no match
    LLM_ONLY = "llm"            # Always use LLM to decide
    HYBRID = "hybrid"           # Rules first, LLM fallback
    PARALLEL = "parallel"       # Execute on multiple agents in parallel
    SEQUENTIAL = "sequential"   # Execute as pipeline (output → input)
    CONSENSUS = "consensus"     # Multiple agents, aggregate responses
    FIRST_SUCCESS = "first"     # Race multiple agents, return first success


class LLMDecisionStrategy(str, Enum):
    """Strategy for LLM-based agent selection."""

    SINGLE = "single"           # Select single best agent
    PARALLEL = "parallel"       # Select multiple for parallel execution
    SEQUENTIAL = "sequential"   # Select ordered list for pipeline
    ADAPTIVE = "adaptive"       # LLM decides execution strategy


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models for structured LLM responses
# ─────────────────────────────────────────────────────────────────────────────

class AgentSelection(BaseModel):
    """Single agent selection from LLM."""
    agent_name: str = Field(description="Name of the selected agent")
    confidence: float = Field(default=1.0, description="Confidence score 0-1")
    reasoning: str = Field(default="", description="Why this agent was selected")


class OrchestrationPlan(BaseModel):
    """Complete orchestration plan from LLM."""
    strategy: str = Field(
        description="Execution strategy: 'single', 'parallel', or 'sequential'"
    )
    agents: List[str] = Field(
        description="Ordered list of agent names to use"
    )
    reasoning: str = Field(
        default="",
        description="Explanation of the orchestration decision"
    )
    transform_between: bool = Field(
        default=False,
        description="For sequential: whether to transform output between agents"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentExecutionResult:
    """Result from a single agent execution."""
    agent_name: str
    success: bool
    response: Optional[str] = None
    task: Optional[Task] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestrationResult:
    """Complete result from orchestration."""
    success: bool
    mode_used: OrchestrationMode
    agents_used: List[str]
    responses: List[AgentExecutionResult]
    final_output: Optional[str] = None
    total_time_ms: float = 0.0
    llm_fallback_used: bool = False
    llm_decision: Optional[OrchestrationPlan] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def primary_response(self) -> Optional[str]:
        """Get the primary response (first successful or final output)."""
        if self.final_output:
            return self.final_output
        for r in self.responses:
            if r.success and r.response:
                return r.response
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "mode_used": self.mode_used.value,
            "agents_used": self.agents_used,
            "responses": [
                {
                    "agent": r.agent_name,
                    "success": r.success,
                    "response": r.response[:500] if r.response else None,
                    "error": r.error,
                    "latency_ms": r.latency_ms,
                }
                for r in self.responses
            ],
            "final_output": self.final_output[:1000] if self.final_output else None,
            "total_time_ms": round(self.total_time_ms, 2),
            "llm_fallback_used": self.llm_fallback_used,
            "llm_decision": self.llm_decision.model_dump() if self.llm_decision else None,
        }


@dataclass
class OrchestratorStats:
    """Statistics for the orchestrator."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rules_used: int = 0
    llm_fallback_used: int = 0
    parallel_executions: int = 0
    sequential_executions: int = 0
    total_latency_ms: float = 0.0
    agents_called: Dict[str, int] = field(default_factory=dict)
    mode_usage: Dict[str, int] = field(default_factory=dict)

    @property
    def avg_latency_ms(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": round(self.success_rate, 3),
            "rules_used": self.rules_used,
            "llm_fallback_used": self.llm_fallback_used,
            "parallel_executions": self.parallel_executions,
            "sequential_executions": self.sequential_executions,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "agents_called": dict(self.agents_called),
            "mode_usage": dict(self.mode_usage),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Main Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class A2AOrchestrator:
    """
    Hybrid orchestrator combining rule-based routing with LLM decision-making.

    This orchestrator provides intelligent request routing and multi-agent
    coordination. It uses deterministic rules when patterns are known and
    falls back to LLM-based reasoning for complex or ambiguous requests.

    Architecture:
        1. Rules Engine (via A2AProxyRouter): Fast, deterministic routing
        2. LLM Decision Engine: Complex reasoning about agent selection
        3. Execution Engine: Parallel/sequential agent invocation
        4. Aggregation Engine: Combine responses from multiple agents

    Usage Patterns:
        - RULES_ONLY: Pure rule-based routing, no LLM cost
        - LLM_ONLY: Always use LLM for decisions
        - HYBRID: Rules first, LLM fallback (recommended)
        - PARALLEL: Fan-out to multiple agents
        - SEQUENTIAL: Pipeline execution

    Example:
        orchestrator = A2AOrchestrator(mesh, default_mode=OrchestrationMode.HYBRID)

        # Add rules (fast path)
        orchestrator.route_by_skill("analysis", "AnalystBot")
        orchestrator.route_by_regex(r"urgent", "PriorityBot")

        # Set LLM fallback
        orchestrator.set_fallback_llm(claude_client)

        # Simple case: uses rules
        result = await orchestrator.run("Analyze this data")

        # Complex case: LLM decides
        result = await orchestrator.run(
            "Compare our Q3 performance with competitors and suggest improvements"
        )
    """

    # Default prompt for LLM decision making
    DEFAULT_DECISION_PROMPT = """You are an orchestrator that routes requests to specialized AI agents.

Available agents:
{agents_info}

Given the user's request, decide which agent(s) should handle it and how.

Respond with a JSON object:
{{
    "strategy": "single" | "parallel" | "sequential",
    "agents": ["agent_name1", "agent_name2"],
    "reasoning": "brief explanation of your decision",
    "transform_between": false
}}

Guidelines:
- Use "single" for straightforward requests matching one agent's expertise
- Use "parallel" when multiple perspectives or independent tasks are needed
- Use "sequential" when tasks must be done in order (output of one feeds the next)
- Set "transform_between" to true for sequential if outputs need adaptation

User request: {user_request}"""

    def __init__(
        self,
        mesh: A2AMeshDiscovery,
        *,
        name: str = "A2AOrchestrator",
        default_mode: OrchestrationMode = OrchestrationMode.HYBRID,
        default_timeout: float = 60.0,
        max_parallel_agents: int = 10,
        max_sequential_agents: int = 5,
        aggregate_parallel_responses: bool = True,
    ):
        """
        Initialize the orchestrator.

        Args:
            mesh: A2AMeshDiscovery instance for agent lookup
            name: Name for this orchestrator
            default_mode: Default orchestration mode
            default_timeout: Default timeout for agent calls
            max_parallel_agents: Maximum agents in parallel execution
            max_sequential_agents: Maximum agents in sequential pipeline
            aggregate_parallel_responses: Whether to combine parallel responses
        """
        self.mesh = mesh
        self.name = name
        self.default_mode = default_mode
        self.default_timeout = default_timeout
        self.max_parallel_agents = max_parallel_agents
        self.max_sequential_agents = max_sequential_agents
        self.aggregate_parallel_responses = aggregate_parallel_responses

        # Internal router for rule-based routing
        self._router = A2AProxyRouter(
            mesh,
            name=f"{name}_router",
            aggregate_skills=False,  # We handle aggregation
        )

        # LLM for complex decisions
        self._llm_client: Optional["AbstractClient"] = None
        self._decision_prompt: Optional[str] = None
        self._decision_model: Optional[str] = None

        # Client cache
        self._client_cache: Dict[str, A2AClient] = {}

        # Statistics
        self._stats = OrchestratorStats()

        self.logger = logging.getLogger(f"A2A.Orchestrator.{name}")

    # ─────────────────────────────────────────────────────────────────────────
    # Configuration
    # ─────────────────────────────────────────────────────────────────────────

    def route_by_skill(
        self,
        skill_id: str,
        target: Union[str, List[str]],
        **kwargs
    ) -> "A2AOrchestrator":
        """Add skill-based routing rule."""
        self._router.route_by_skill(skill_id, target, **kwargs)
        return self

    def route_by_tag(
        self,
        tag: str,
        target: Union[str, List[str]],
        **kwargs
    ) -> "A2AOrchestrator":
        """Add tag-based routing rule."""
        self._router.route_by_tag(tag, target, **kwargs)
        return self

    def route_by_regex(
        self,
        pattern: str,
        target: Union[str, List[str]],
        **kwargs
    ) -> "A2AOrchestrator":
        """Add regex-based routing rule."""
        self._router.route_by_regex(pattern, target, **kwargs)
        return self

    def set_default(self, agent_name: str) -> "A2AOrchestrator":
        """Set default agent for unmatched requests."""
        self._router.set_default(agent_name)
        return self

    def set_fallback_llm(
        self,
        llm_client: "AbstractClient",
        *,
        decision_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> "A2AOrchestrator":
        """
        Configure LLM for complex orchestration decisions.

        The LLM is used when:
        - No routing rule matches (in HYBRID mode)
        - Explicitly requested (LLM_ONLY mode)
        - Task requires multiple agents

        Args:
            llm_client: Parrot AbstractClient instance (Claude, GPT, etc.)
            decision_prompt: Custom prompt template for decisions
            model: Specific model to use for decisions

        Returns:
            Self for method chaining
        """
        self._llm_client = llm_client
        self._decision_prompt = decision_prompt
        self._decision_model = model
        self.logger.info("LLM fallback configured")
        return self

    def clear_llm(self) -> "A2AOrchestrator":
        """Remove LLM fallback configuration."""
        self._llm_client = None
        self._decision_prompt = None
        return self

    # ─────────────────────────────────────────────────────────────────────────
    # Main Execution
    # ─────────────────────────────────────────────────────────────────────────

    async def run(
        self,
        message: str,
        *,
        mode: Optional[OrchestrationMode] = None,
        agents: Optional[List[str]] = None,
        skill_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        context_id: Optional[str] = None,
        timeout: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OrchestrationResult:
        """
        Execute orchestration for a message.

        This is the main entry point. The orchestrator will:
        1. Try rule-based routing if applicable
        2. Fall back to LLM decision if needed (HYBRID mode)
        3. Execute on selected agent(s)
        4. Aggregate results if multiple agents used

        Args:
            message: The message/request to process
            mode: Override default orchestration mode
            agents: Explicit list of agents to use (bypasses routing)
            skill_id: Optional skill ID hint for routing
            tags: Optional tags for routing
            context_id: Optional context for multi-turn conversations
            timeout: Override default timeout
            metadata: Additional metadata

        Returns:
            OrchestrationResult with response(s) and execution details
        """
        start_time = time.monotonic()
        mode = mode or self.default_mode
        timeout = timeout or self.default_timeout

        self._stats.total_requests += 1
        self._stats.mode_usage[mode.value] = self._stats.mode_usage.get(mode.value, 0) + 1

        self.logger.debug(f"Orchestrating: mode={mode.value}, message={message[:100]}...")

        try:
            # If explicit agents provided, use them directly
            if agents:
                if len(agents) == 1:
                    result = await self._execute_single(
                        message, agents[0], context_id, timeout
                    )
                elif mode == OrchestrationMode.SEQUENTIAL:
                    result = await self._execute_sequential(
                        message, agents, context_id, timeout
                    )
                else:
                    result = await self._execute_parallel(
                        message, agents, context_id, timeout
                    )

            # Route based on mode
            elif mode == OrchestrationMode.RULES_ONLY:
                result = await self._execute_rules_only(
                    message, skill_id, tags, context_id, timeout
                )

            elif mode == OrchestrationMode.LLM_ONLY:
                result = await self._execute_llm_decision(
                    message, context_id, timeout
                )

            elif mode == OrchestrationMode.HYBRID:
                result = await self._execute_hybrid(
                    message, skill_id, tags, context_id, timeout
                )

            elif mode == OrchestrationMode.PARALLEL:
                # Parallel to all healthy agents
                all_agents = [a.card.name for a in self.mesh.list_healthy()]
                result = await self._execute_parallel(
                    message, all_agents[:self.max_parallel_agents], context_id, timeout
                )

            elif mode == OrchestrationMode.SEQUENTIAL:
                # LLM decides the sequence
                result = await self._execute_llm_decision(
                    message, context_id, timeout, force_sequential=True
                )

            elif mode == OrchestrationMode.CONSENSUS:
                result = await self._execute_consensus(
                    message, context_id, timeout
                )

            elif mode == OrchestrationMode.FIRST_SUCCESS:
                result = await self._execute_first_success(
                    message, context_id, timeout
                )

            else:
                raise ValueError(f"Unknown orchestration mode: {mode}")

            # Update stats
            result.total_time_ms = (time.monotonic() - start_time) * 1000
            result.mode_used = mode

            if result.success:
                self._stats.successful_requests += 1
                self._stats.total_latency_ms += result.total_time_ms
            else:
                self._stats.failed_requests += 1

            for agent_name in result.agents_used:
                self._stats.agents_called[agent_name] = \
                    self._stats.agents_called.get(agent_name, 0) + 1

            return result

        except Exception as e:
            self.logger.error(f"Orchestration failed: {e}", exc_info=True)
            self._stats.failed_requests += 1

            return OrchestrationResult(
                success=False,
                mode_used=mode,
                agents_used=[],
                responses=[],
                total_time_ms=(time.monotonic() - start_time) * 1000,
                metadata={"error": str(e)},
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Execution Modes
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute_rules_only(
        self,
        message: str,
        skill_id: Optional[str],
        tags: Optional[List[str]],
        context_id: Optional[str],
        timeout: float,
    ) -> OrchestrationResult:
        """Execute using only routing rules."""
        routing_result = self._router.find_target(message, skill_id=skill_id, tags=tags)

        if not routing_result.matched or not routing_result.target_agent:
            return OrchestrationResult(
                success=False,
                mode_used=OrchestrationMode.RULES_ONLY,
                agents_used=[],
                responses=[],
                metadata={"error": "No routing rule matched"},
            )

        self._stats.rules_used += 1

        return await self._execute_single(
            message,
            routing_result.target_agent.card.name,
            context_id,
            timeout,
        )

    async def _execute_hybrid(
        self,
        message: str,
        skill_id: Optional[str],
        tags: Optional[List[str]],
        context_id: Optional[str],
        timeout: float,
    ) -> OrchestrationResult:
        """Execute with rules first, LLM fallback."""
        # Try rules first
        routing_result = self._router.find_target(message, skill_id=skill_id, tags=tags)

        if routing_result.matched and routing_result.target_agent:
            self._stats.rules_used += 1
            return await self._execute_single(
                message,
                routing_result.target_agent.card.name,
                context_id,
                timeout,
            )

        # Fall back to LLM
        if not self._llm_client:
            # No LLM configured, try default agent
            if self._router._default_agent:
                return await self._execute_single(
                    message,
                    self._router._default_agent,
                    context_id,
                    timeout,
                )

            return OrchestrationResult(
                success=False,
                mode_used=OrchestrationMode.HYBRID,
                agents_used=[],
                responses=[],
                metadata={"error": "No rule matched and no LLM configured"},
            )

        self.logger.debug("No rule matched, falling back to LLM")
        self._stats.llm_fallback_used += 1

        result = await self._execute_llm_decision(message, context_id, timeout)
        result.llm_fallback_used = True
        return result

    async def _execute_llm_decision(
        self,
        message: str,
        context_id: Optional[str],
        timeout: float,
        force_sequential: bool = False,
    ) -> OrchestrationResult:
        """Use LLM to decide orchestration strategy."""
        if not self._llm_client:
            return OrchestrationResult(
                success=False,
                mode_used=OrchestrationMode.LLM_ONLY,
                agents_used=[],
                responses=[],
                metadata={"error": "No LLM client configured"},
            )

        # Build agents info for prompt
        agents_info = self._build_agents_info()

        # Create decision prompt
        prompt_template = self._decision_prompt or self.DEFAULT_DECISION_PROMPT
        prompt = prompt_template.format(
            agents_info=agents_info,
            user_request=message,
        )

        # Ask LLM for orchestration plan
        try:
            async with self._llm_client as client:
                response = await client.ask(
                    prompt=prompt,
                    system_prompt="You are an orchestration planner. Respond only with valid JSON.",
                    model=self._decision_model,
                    temperature=0.0,
                    max_tokens=500,
                )

            # Parse LLM response
            response_text = response.output if hasattr(response, 'output') else str(response)
            plan = self._parse_orchestration_plan(response_text)

            if force_sequential:
                plan.strategy = "sequential"

            self.logger.debug(f"LLM decision: {plan.strategy} with {plan.agents}")

        except Exception as e:
            self.logger.error(f"LLM decision failed: {e}")

            # Fallback: use first healthy agent
            healthy = self.mesh.list_healthy()
            if not healthy:
                return OrchestrationResult(
                    success=False,
                    mode_used=OrchestrationMode.LLM_ONLY,
                    agents_used=[],
                    responses=[],
                    metadata={"error": f"LLM decision failed: {e}"},
                )

            plan = OrchestrationPlan(
                strategy="single",
                agents=[healthy[0].card.name],
                reasoning="Fallback due to LLM error",
            )

        # Execute based on LLM plan
        if plan.strategy == "parallel":
            result = await self._execute_parallel(
                message,
                plan.agents[:self.max_parallel_agents],
                context_id,
                timeout,
            )
        elif plan.strategy == "sequential":
            result = await self._execute_sequential(
                message,
                plan.agents[:self.max_sequential_agents],
                context_id,
                timeout,
                transform_between=plan.transform_between,
            )
        else:  # single
            agent = plan.agents[0] if plan.agents else None  # pylint: disable=E1136
            if not agent:
                return OrchestrationResult(
                    success=False,
                    mode_used=OrchestrationMode.LLM_ONLY,
                    agents_used=[],
                    responses=[],
                    metadata={"error": "LLM selected no agents"},
                )
            result = await self._execute_single(message, agent, context_id, timeout)

        result.llm_decision = plan
        return result

    async def _execute_single(
        self,
        message: str,
        agent_name: str,
        context_id: Optional[str],
        timeout: float,
    ) -> OrchestrationResult:
        """Execute on a single agent."""
        start_time = time.monotonic()

        agent = self.mesh.get(agent_name)
        if not agent or not agent.healthy:
            return OrchestrationResult(
                success=False,
                mode_used=OrchestrationMode.RULES_ONLY,
                agents_used=[agent_name],
                responses=[AgentExecutionResult(
                    agent_name=agent_name,
                    success=False,
                    error=f"Agent {agent_name} not available",
                )],
            )

        try:
            client = await self._get_client(agent, timeout)
            task = await client.send_message(message, context_id=context_id)

            latency = (time.monotonic() - start_time) * 1000

            # Extract response text
            response_text = ""
            if task.artifacts and task.artifacts[0].parts:
                response_text = task.artifacts[0].parts[0].text or ""

            success = task.status.state == TaskState.COMPLETED
            error = None
            if task.status.state == TaskState.FAILED:
                error = task.status.message.get_text() if task.status.message else "Unknown error"

            exec_result = AgentExecutionResult(
                agent_name=agent_name,
                success=success,
                response=response_text,
                task=task,
                error=error,
                latency_ms=latency,
            )

            return OrchestrationResult(
                success=success,
                mode_used=OrchestrationMode.RULES_ONLY,
                agents_used=[agent_name],
                responses=[exec_result],
                final_output=response_text if success else None,
            )

        except Exception as e:
            latency = (time.monotonic() - start_time) * 1000
            return OrchestrationResult(
                success=False,
                mode_used=OrchestrationMode.RULES_ONLY,
                agents_used=[agent_name],
                responses=[AgentExecutionResult(
                    agent_name=agent_name,
                    success=False,
                    error=str(e),
                    latency_ms=latency,
                )],
            )

    async def _execute_parallel(
        self,
        message: str,
        agent_names: List[str],
        context_id: Optional[str],
        timeout: float,
    ) -> OrchestrationResult:
        """Execute on multiple agents in parallel."""
        self._stats.parallel_executions += 1

        async def call_agent(name: str) -> AgentExecutionResult:
            start = time.monotonic()
            agent = self.mesh.get(name)

            if not agent or not agent.healthy:
                return AgentExecutionResult(
                    agent_name=name,
                    success=False,
                    error=f"Agent {name} not available",
                )

            try:
                client = await self._get_client(agent, timeout)
                task = await client.send_message(message, context_id=context_id)

                response_text = ""
                if task.artifacts and task.artifacts[0].parts:
                    response_text = task.artifacts[0].parts[0].text or ""

                success = task.status.state == TaskState.COMPLETED
                error = None
                if task.status.state == TaskState.FAILED:
                    error = task.status.message.get_text() if task.status.message else "Error"

                return AgentExecutionResult(
                    agent_name=name,
                    success=success,
                    response=response_text,
                    task=task,
                    error=error,
                    latency_ms=(time.monotonic() - start) * 1000,
                )

            except Exception as e:
                return AgentExecutionResult(
                    agent_name=name,
                    success=False,
                    error=str(e),
                    latency_ms=(time.monotonic() - start) * 1000,
                )

        # Execute all in parallel
        results = await asyncio.gather(
            *[call_agent(name) for name in agent_names],
            return_exceptions=False
        )

        # Aggregate results
        successful = [r for r in results if r.success]
        all_success = len(successful) == len(results)
        any_success = len(successful) > 0

        # Combine responses if configured
        final_output = None
        if self.aggregate_parallel_responses and successful:
            final_output = self._aggregate_responses(successful)
        elif successful:
            final_output = successful[0].response

        return OrchestrationResult(
            success=any_success,
            mode_used=OrchestrationMode.PARALLEL,
            agents_used=agent_names,
            responses=list(results),
            final_output=final_output,
            metadata={
                "all_succeeded": all_success,
                "success_count": len(successful),
                "total_count": len(results),
            },
        )

    async def _execute_sequential(
        self,
        message: str,
        agent_names: List[str],
        context_id: Optional[str],
        timeout: float,
        transform_between: bool = False,
    ) -> OrchestrationResult:
        """Execute as sequential pipeline."""
        self._stats.sequential_executions += 1

        results: List[AgentExecutionResult] = []
        current_input = message

        for i, name in enumerate(agent_names):
            start = time.monotonic()
            agent = self.mesh.get(name)

            if not agent or not agent.healthy:
                results.append(AgentExecutionResult(
                    agent_name=name,
                    success=False,
                    error=f"Agent {name} not available",
                ))
                break

            try:
                client = await self._get_client(agent, timeout)
                task = await client.send_message(current_input, context_id=context_id)

                response_text = ""
                if task.artifacts and task.artifacts[0].parts:
                    response_text = task.artifacts[0].parts[0].text or ""

                success = task.status.state == TaskState.COMPLETED

                results.append(AgentExecutionResult(
                    agent_name=name,
                    success=success,
                    response=response_text,
                    task=task,
                    latency_ms=(time.monotonic() - start) * 1000,
                ))

                if not success:
                    break

                # Output becomes input for next agent
                if i < len(agent_names) - 1:
                    if transform_between:
                        # Could add transformation logic here
                        current_input = f"Previous analysis:\n{response_text}\n\nContinue processing."
                    else:
                        current_input = response_text

            except Exception as e:
                results.append(AgentExecutionResult(
                    agent_name=name,
                    success=False,
                    error=str(e),
                    latency_ms=(time.monotonic() - start) * 1000,
                ))
                break

        # Final output is last successful response
        final_output = None
        for r in reversed(results):
            if r.success and r.response:
                final_output = r.response
                break

        all_success = all(r.success for r in results) and len(results) == len(agent_names)

        return OrchestrationResult(
            success=all_success,
            mode_used=OrchestrationMode.SEQUENTIAL,
            agents_used=[r.agent_name for r in results],
            responses=results,
            final_output=final_output,
            metadata={
                "pipeline_completed": all_success,
                "stages_completed": sum(1 for r in results if r.success),
                "total_stages": len(agent_names),
            },
        )

    async def _execute_consensus(
        self,
        message: str,
        context_id: Optional[str],
        timeout: float,
    ) -> OrchestrationResult:
        """Execute on multiple agents and aggregate for consensus."""
        # Get all healthy agents (limited)
        healthy = self.mesh.list_healthy()[:self.max_parallel_agents]

        if not healthy:
            return OrchestrationResult(
                success=False,
                mode_used=OrchestrationMode.CONSENSUS,
                agents_used=[],
                responses=[],
                metadata={"error": "No healthy agents available"},
            )

        agent_names = [a.card.name for a in healthy]
        result = await self._execute_parallel(message, agent_names, context_id, timeout)

        # Consensus: combine successful responses
        successful = [r for r in result.responses if r.success]
        if successful:
            result.final_output = self._build_consensus(successful)

        result.mode_used = OrchestrationMode.CONSENSUS
        return result

    async def _execute_first_success(
        self,
        message: str,
        context_id: Optional[str],
        timeout: float,
    ) -> OrchestrationResult:
        """Race multiple agents, return first successful response."""
        healthy = self.mesh.list_healthy()[:self.max_parallel_agents]

        if not healthy:
            return OrchestrationResult(
                success=False,
                mode_used=OrchestrationMode.FIRST_SUCCESS,
                agents_used=[],
                responses=[],
                metadata={"error": "No healthy agents available"},
            )

        async def try_agent(agent: RegisteredAgent) -> Optional[AgentExecutionResult]:
            start = time.monotonic()
            try:
                client = await self._get_client(agent, timeout)
                task = await client.send_message(message, context_id=context_id)

                if task.status.state == TaskState.COMPLETED:
                    response_text = ""
                    if task.artifacts and task.artifacts[0].parts:
                        response_text = task.artifacts[0].parts[0].text or ""

                    return AgentExecutionResult(
                        agent_name=agent.card.name,
                        success=True,
                        response=response_text,
                        task=task,
                        latency_ms=(time.monotonic() - start) * 1000,
                    )
                return None
            except Exception:
                return None

        # Race all agents
        tasks = [asyncio.create_task(try_agent(a)) for a in healthy]

        # Wait for first success
        winner = None
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result and result.success:
                winner = result
                break

        # Cancel remaining tasks
        for task in tasks:
            if not task.done():
                task.cancel()

        if winner:
            return OrchestrationResult(
                success=True,
                mode_used=OrchestrationMode.FIRST_SUCCESS,
                agents_used=[winner.agent_name],
                responses=[winner],
                final_output=winner.response,
            )

        return OrchestrationResult(
            success=False,
            mode_used=OrchestrationMode.FIRST_SUCCESS,
            agents_used=[a.card.name for a in healthy],
            responses=[],
            metadata={"error": "No agent succeeded"},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ─────────────────────────────────────────────────────────────────────────

    def _build_agents_info(self) -> str:
        """Build agents description for LLM prompt."""
        lines = []
        for agent in self.mesh.list_healthy():
            skills = ", ".join(s.name for s in agent.card.skills[:5])
            tags = ", ".join(agent.card.tags[:5])
            lines.append(
                f"- {agent.card.name}: {agent.card.description[:100]}"
                f"\n  Skills: {skills or 'general'}"
                f"\n  Tags: {tags or 'none'}"
            )
        return "\n".join(lines) or "No agents available"

    def _parse_orchestration_plan(self, response: str) -> OrchestrationPlan:
        """Parse LLM response into OrchestrationPlan."""
        # Try to extract JSON from response
        try:
            # Handle markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            data = json.loads(response.strip())
            return OrchestrationPlan(**data)

        except (json.JSONDecodeError, ValueError) as e:
            self.logger.warning(f"Failed to parse LLM response: {e}")

            # Fallback: try to extract agent names
            healthy = self.mesh.list_healthy()
            if healthy:
                return OrchestrationPlan(
                    strategy="single",
                    agents=[healthy[0].card.name],
                    reasoning="Fallback due to parse error",
                )

            raise ValueError(f"Cannot parse orchestration plan: {e}")

    def _aggregate_responses(self, results: List[AgentExecutionResult]) -> str:
        """Aggregate multiple agent responses."""
        if len(results) == 1:
            return results[0].response or ""

        parts = []
        for r in results:
            if r.response:
                parts.append(f"**{r.agent_name}:**\n{r.response}")

        return "\n\n---\n\n".join(parts)

    def _build_consensus(self, results: List[AgentExecutionResult]) -> str:
        """Build consensus summary from multiple responses."""
        if len(results) == 1:
            return results[0].response or ""

        # Simple consensus: list all responses with agent attribution
        parts = [f"Consensus from {len(results)} agents:\n"]
        for i, r in enumerate(results, 1):
            if r.response:
                parts.append(f"\n[{r.agent_name}]: {r.response[:500]}")

        return "".join(parts)

    async def _get_client(
        self,
        agent: RegisteredAgent,
        timeout: float
    ) -> A2AClient:
        """Get or create client for agent."""
        if agent.url in self._client_cache:
            client = self._client_cache[agent.url]
            if client.is_connected:
                return client

        endpoint = self.mesh.get_endpoint(agent.url)

        client = A2AClient(
            agent.url,
            auth_token=endpoint.auth_token if endpoint else None,
            api_key=endpoint.api_key if endpoint else None,
            headers=endpoint.headers if endpoint else None,
            timeout=timeout,
        )

        await client.connect()
        self._client_cache[agent.url] = client

        return client

    async def close_clients(self) -> None:
        """Close all cached clients."""
        for client in self._client_cache.values():
            try:
                await client.disconnect()
            except Exception:
                pass
        self._client_cache.clear()

    # ─────────────────────────────────────────────────────────────────────────
    # Convenience Methods
    # ─────────────────────────────────────────────────────────────────────────

    async def ask(
        self,
        message: str,
        *,
        agent: Optional[str] = None,
        mode: Optional[OrchestrationMode] = None,
        **kwargs
    ) -> str:
        """
        Shortcut: get response as string.

        Args:
            message: Message to send
            agent: Optional specific agent
            mode: Optional mode override
            **kwargs: Additional arguments

        Returns:
            Response text

        Raises:
            RuntimeError: If orchestration fails
        """
        if agent:
            result = await self.run(message, agents=[agent], **kwargs)
        else:
            result = await self.run(message, mode=mode, **kwargs)

        if not result.success:
            error = result.metadata.get("error", "Unknown error")
            raise RuntimeError(f"Orchestration failed: {error}")

        return result.primary_response or ""

    async def fan_out(
        self,
        message: str,
        agents: List[str],
        **kwargs
    ) -> Dict[str, Union[str, Exception]]:
        """
        Send to multiple agents and collect responses.

        Args:
            message: Message to send
            agents: List of agent names
            **kwargs: Additional arguments

        Returns:
            Dict mapping agent name to response or exception
        """
        result = await self.run(
            message,
            agents=agents,
            mode=OrchestrationMode.PARALLEL,
            **kwargs
        )

        return {
            r.agent_name: r.response if r.success else Exception(r.error or "Failed")
            for r in result.responses
        }

    async def pipeline(
        self,
        message: str,
        agents: List[str],
        **kwargs
    ) -> str:
        """
        Execute sequential pipeline.

        Args:
            message: Initial message
            agents: Ordered list of agents
            **kwargs: Additional arguments

        Returns:
            Final output from last agent
        """
        result = await self.run(
            message,
            agents=agents,
            mode=OrchestrationMode.SEQUENTIAL,
            **kwargs
        )

        if not result.success:
            error = result.metadata.get("error", "Pipeline failed")
            raise RuntimeError(error)

        return result.final_output or ""

    # ─────────────────────────────────────────────────────────────────────────
    # Properties and Info
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> OrchestratorStats:
        """Get current statistics."""
        return self._stats

    @property
    def router(self) -> A2AProxyRouter:
        """Access the internal router for advanced configuration."""
        return self._router

    def get_info(self) -> Dict[str, Any]:
        """Get orchestrator state information."""
        return {
            "name": self.name,
            "default_mode": self.default_mode.value,
            "llm_configured": self._llm_client is not None,
            "rules_count": len(self._router._rules),
            "default_agent": self._router._default_agent,
            "mesh_agents": len(self.mesh),
            "mesh_healthy": len(self.mesh.list_healthy()),
            "cached_clients": len(self._client_cache),
            "stats": self._stats.to_dict(),
        }

    def __repr__(self) -> str:
        return (
            f"A2AOrchestrator("
            f"name={self.name!r}, "
            f"mode={self.default_mode.value}, "
            f"rules={len(self._router._rules)}, "
            f"llm={'yes' if self._llm_client else 'no'})"
        )
