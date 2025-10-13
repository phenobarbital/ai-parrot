"""
Agent Crew with Finite State Machine Orchestration
==================================================
Enhanced workflow orchestration using python-statemachine for complex agent flows
with conditional transitions, error handling, and state-based execution control.

Features:
- State-based agent lifecycle (idle → ready → running → completed/failed)
- Conditional transitions with custom predicates
- Error recovery with fallback agents
- Dynamic prompt building based on context and dependencies
- Shared results and context across agents
- On-success and on-error routing
"""
from __future__ import annotations
from typing import (
    List, Dict, Any, Union, Optional, Set, Callable, Iterable, Awaitable
)
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import uuid
from datetime import datetime
from statemachine import State, StateMachine
from navconfig.logging import logging

from ..agent import BasicAgent
from ..abstract import AbstractBot
from ...tools.manager import ToolManager
from ...tools.agent import AgentContext
from ...models.responses import AIMessage, AgentResponse
from ...models.crew import (
    CrewResult,
    AgentExecutionInfo,
    build_agent_metadata,
    determine_run_status,
)


# Type aliases for better readability
AgentRef = Union[str, BasicAgent, AbstractBot]
DependencyResults = Dict[str, str]
PromptBuilder = Callable[[AgentContext, DependencyResults], Union[str, Awaitable[str]]]


class TransitionCondition(str, Enum):
    """Predefined transition conditions."""
    ON_SUCCESS = "on_success"
    ON_ERROR = "on_error"
    ON_TIMEOUT = "on_timeout"
    ON_CONDITION = "on_condition"  # Custom condition
    ALWAYS = "always"  # Unconditional transition


class AgentTaskMachine(StateMachine):
    """
    Finite state machine describing the lifecycle of an agent execution.

    States:
        idle: Agent is created but not scheduled
        ready: All dependencies satisfied, ready to execute
        running: Agent is currently executing
        completed: Agent finished successfully
        failed: Agent execution failed
        blocked: Agent cannot proceed (missing dependencies or resources)

    Transitions:
        schedule: idle → ready (when dependencies are met)
        start: ready → running (begin execution)
        succeed: running → completed (successful completion)
        fail: running/ready/idle → failed (error occurred)
        block: idle/ready → blocked (dependencies not met)
        unblock: blocked → ready (dependencies now satisfied)
        retry: failed → ready (retry after failure)
    """

    idle = State("idle", initial=True)
    ready = State("ready")
    running = State("running")
    completed = State("completed", final=True)
    failed = State("failed")
    blocked = State("blocked")

    # Primary transitions
    schedule = idle.to(ready)
    start = ready.to(running)
    succeed = running.to(completed)
    fail = running.to(failed) | ready.to(failed) | idle.to(failed)
    block = idle.to(blocked) | ready.to(blocked)
    unblock = blocked.to(ready)
    retry = failed.to(ready)

    def __init__(self, agent_name: str, **kwargs):
        self.agent_name = agent_name
        super().__init__(**kwargs)

    def on_enter_running(self):
        """Called when entering running state."""
        logging.debug(f"Agent {self.agent_name} started execution")

    def on_enter_completed(self):
        """Called when entering completed state."""
        logging.info(f"Agent {self.agent_name} completed successfully")

    def on_enter_failed(self):
        """Called when entering failed state."""
        logging.error(f"Agent {self.agent_name} execution failed")


@dataclass
class FlowTransition:
    """
    Represents a transition from one agent to another with conditions.

    A transition defines:
    - What triggers it (condition)
    - Where it goes (target agents)
    - How to prepare the input (instruction/prompt_builder)
    - What to do on success/failure
    """

    source: str  # Source agent name
    targets: Set[str]  # Target agent names
    condition: TransitionCondition = TransitionCondition.ON_SUCCESS
    instruction: Optional[str] = None
    prompt_builder: Optional[PromptBuilder] = None
    predicate: Optional[Callable[[Any], Union[bool, Awaitable[bool]]]] = None
    priority: int = 0  # Higher priority transitions are evaluated first
    metadata: Optional[AgentExecutionInfo] = None

    async def should_activate(self, result: Any, error: Optional[Exception] = None) -> bool:
        """
        Determine if this transition should be activated based on the condition.

        Args:
            result: The result from the source agent
            error: Any error that occurred during source agent execution

        Returns:
            True if the transition should be activated
        """
        if self.condition == TransitionCondition.ALWAYS:
            return True

        if self.condition == TransitionCondition.ON_SUCCESS:
            return error is None

        if self.condition == TransitionCondition.ON_ERROR:
            return error is not None

        if self.condition == TransitionCondition.ON_CONDITION and self.predicate:
            pred_result = self.predicate(result)
            if asyncio.iscoroutine(pred_result):
                return await pred_result
            return bool(pred_result)

        return False

    async def build_prompt(
        self,
        context: AgentContext,
        dependencies: DependencyResults
    ) -> str:
        """
        Build the prompt for target agents using the prompt_builder or instruction.

        Args:
            context: The execution context
            dependencies: Results from dependency agents

        Returns:
            The constructed prompt string
        """
        if self.prompt_builder:
            prompt = self.prompt_builder(context, dependencies)
            return await prompt if asyncio.iscoroutine(prompt) else prompt

        if self.instruction:
            return self.instruction

        # Default: use original query with dependency context
        parts = [f"Task: {context.original_query}"]

        if dependencies:
            parts.append("\nContext from previous agents:")
            for agent_name, result in dependencies.items():
                parts.extend((f"\n--- {agent_name} ---", str(result)))

        return "\n".join(parts)


@dataclass
class FlowNode:
    """
    Represents an agent in the FSM-based workflow.

    A FlowNode wraps an agent with:
    - State machine for lifecycle management
    - Dependencies on other agents
    - Transitions to other agents
    - Execution metadata and results
    """

    agent: Union[BasicAgent, AbstractBot]
    fsm: AgentTaskMachine
    dependencies: Set[str] = field(default_factory=set)
    outgoing_transitions: List[FlowTransition] = field(default_factory=list)
    result: Optional[Any] = None
    response: Optional[Any] = None
    error: Optional[Exception] = None
    execution_time: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)
    agent_info: Optional[AgentExecutionInfo] = None
    transitions_processed: bool = False  # Track if transitions have been activated

    @property
    def name(self) -> str:
        """Get the agent name."""
        return self.agent.name

    @property
    def is_terminal(self) -> bool:
        """Check if this node has no outgoing transitions."""
        return len(self.outgoing_transitions) == 0

    @property
    def can_retry(self) -> bool:
        """Check if this node can be retried."""
        return self.retry_count < self.max_retries and self.fsm.current_state == self.fsm.failed

    def add_transition(self, transition: FlowTransition) -> None:
        """Add an outgoing transition from this node."""
        self.outgoing_transitions.append(transition)
        # Sort by priority (descending)
        self.outgoing_transitions.sort(key=lambda t: t.priority, reverse=True)

    async def get_active_transitions(
        self,
        error: Optional[Exception] = None
    ) -> List[FlowTransition]:
        """
        Get all transitions that should be activated based on current result/error.

        Returns:
            List of transitions that match their activation conditions
        """
        active = []
        for transition in self.outgoing_transitions:
            if await transition.should_activate(self.result, error):
                active.append(transition)
        return active

    async def execute(self,  prompt:str, ctx: Dict[str, Any]) -> Any:
        """Execute the agent with context from previous agents."""
        return await self.agent.ask(
            question=prompt,
            **ctx
        )


class AgentsFlow:
    """
    Enhanced Agent Crew with Finite State Machine orchestration.

    This implementation provides sophisticated workflow control with:
    - State-based agent lifecycle management
    - Conditional transitions (on_success, on_error, custom conditions)
    - Error recovery and retry logic
    - Dynamic prompt building
    - Parallel execution where possible
    - Detailed execution tracking and logging

    Example:
        >>> crew = AgentsFlow(name="ResearchCrew")
        >>>
        >>> # Add agents
        >>> researcher = crew.add_agent(research_agent)
        >>> analyzer = crew.add_agent(analysis_agent)
        >>> writer = crew.add_agent(writer_agent)
        >>> error_handler = crew.add_agent(recovery_agent)
        >>>
        >>> # Define flow with conditional transitions
        >>> crew.task_flow(
        ...     source=researcher,
        ...     targets=analyzer,
        ...     instruction="Analyze the research findings"
        ... )
        >>>
        >>> # Add error handling
        >>> crew.task_flow(
        ...     source=analyzer,
        ...     targets=error_handler,
        ...     condition=TransitionCondition.ON_ERROR
        ... )
        >>>
        >>> # Execute workflow
        >>> result = await crew.run_flow("Research AI trends in 2025")
    """

    def __init__(
        self,
        name: str = "AgentsFlow",
        agents: Optional[List[Union[BasicAgent, AbstractBot]]] = None,
        shared_tool_manager: Optional[ToolManager] = None,
        max_parallel_tasks: int = 10,
        default_max_retries: int = 3,
        execution_timeout: Optional[float] = None,
        truncation_length: Optional[int] = None,
    ):
        """
        Initialize the FSM-based Agent Crew.

        Args:
            name: Name of the crew
            agents: List of agents to add initially
            shared_tool_manager: Shared tool manager for all agents
            max_parallel_tasks: Maximum concurrent agent executions
            default_max_retries: Default retry count for failed agents
            execution_timeout: Maximum time (seconds) for workflow execution
        """
        self.name = name
        self.nodes: Dict[str, FlowNode] = {}
        self.shared_tool_manager = shared_tool_manager or ToolManager()
        self.max_parallel_tasks = max_parallel_tasks
        self.default_max_retries = default_max_retries
        self.execution_timeout = execution_timeout
        self.logger = logging.getLogger(f"parrot.crews.fsm.{self.name}")
        self.semaphore = asyncio.Semaphore(max_parallel_tasks)
        self.truncation_length = truncation_length or 200
        # Execution tracking
        self.execution_log: List[Dict[str, Any]] = []
        self.current_context: Optional[AgentContext] = None
        self._agent_locks: Dict[int, asyncio.Lock] = {}

        # Add initial agents
        if agents:
            for agent in agents:
                self.add_agent(agent)

    def add_agent(
        self,
        agent: Union[BasicAgent, AbstractBot],
        agent_id: Optional[str] = None,
        max_retries: Optional[int] = None
    ) -> FlowNode:
        """
        Add an agent to the crew and return its FlowNode.

        Args:
            agent: The agent to add
            agent_id: Optional custom ID (defaults to agent.name)
            max_retries: Maximum retry attempts for this agent

        Returns:
            The created FlowNode for this agent
        """
        agent_id = agent_id or agent.name

        if agent_id in self.nodes:
            self.logger.warning(f"Agent '{agent_id}' already exists, skipping")
            return self.nodes[agent_id]

        # Create FSM for this agent
        fsm = AgentTaskMachine(agent_name=agent_id)

        # Create FlowNode
        node = FlowNode(
            agent=agent,
            fsm=fsm,
            max_retries=max_retries or self.default_max_retries
        )

        self.nodes[agent_id] = node

        # Share tools with new agent
        if self.shared_tool_manager:
            for tool_name in self.shared_tool_manager.list_tools():
                tool = self.shared_tool_manager.get_tool(tool_name)
                if tool and not agent.tool_manager.get_tool(tool_name):
                    agent.tool_manager.add_tool(tool, tool_name)

        self.logger.info(f"Added agent '{agent_id}' to crew")
        return node

    def _resolve_agent_ref(self, ref: AgentRef) -> str:
        """Convert an AgentRef to an agent name string."""
        return ref if isinstance(ref, str) else ref.name

    def task_flow(
        self,
        source: AgentRef,
        targets: Optional[Union[AgentRef, Iterable[AgentRef]]] = None,
        *,
        condition: TransitionCondition = TransitionCondition.ON_SUCCESS,
        instruction: Optional[str] = None,
        prompt_builder: Optional[PromptBuilder] = None,
        predicate: Optional[Callable[[Any], Union[bool, Awaitable[bool]]]] = None,
        priority: int = 0,
        **metadata
    ) -> FlowNode:
        """
        Define transitions from source agent to target agent(s).

        This method builds the workflow graph by defining how agents connect
        and under what conditions. It supports:
        - Unconditional transitions (always execute targets after source)
        - Success-based transitions (only execute targets if source succeeds)
        - Error-based transitions (only execute targets if source fails)
        - Custom conditional transitions (with predicate function)

        Args:
            source: Source agent (agent object, name, or FlowNode)
            targets: Target agent(s) to transition to (None for terminal node)
            condition: When to activate this transition
            instruction: Static instruction/prompt for target agents
            prompt_builder: Dynamic prompt builder function
            predicate: Custom condition predicate for ON_CONDITION transitions
            priority: Transition priority (higher = evaluated first)
            **metadata: Additional metadata for this transition

        Returns:
            The source FlowNode for method chaining

        Examples:
            # Simple success-based transition
            crew.task_flow(researcher, analyzer)

            # Error handling transition
            crew.task_flow(
                analyzer,
                error_handler,
                condition=TransitionCondition.ON_ERROR,
                instruction="Handle the error and retry"
            )

            # Conditional branching with predicate
            crew.task_flow(
                classifier,
                [processor_a, processor_b],
                condition=TransitionCondition.ON_CONDITION,
                predicate=lambda result: "category_a" in result.lower()
            )

            # Dynamic prompt building
            def build_analysis_prompt(ctx, deps):
                research = deps.get('researcher', '')
                return f"Analyze this research in detail:\n{research}"

            crew.task_flow(
                researcher,
                analyzer,
                prompt_builder=build_analysis_prompt
            )

            # Method chaining for complex flows
            crew.task_flow(start, process).task_flow(process, analyze).task_flow(analyze, end)
        """
        source_name = self._resolve_agent_ref(source)

        if source_name not in self.nodes:
            raise ValueError(f"Source agent '{source_name}' not found in crew")

        source_node = self.nodes[source_name]

        # Handle terminal node (no targets)
        if targets is None:
            self.logger.info(f"Agent '{source_name}' is a terminal node")
            return source_node

        # Normalize targets to a list
        if not isinstance(targets, (list, tuple, set)):
            targets = [targets]

        target_names = {self._resolve_agent_ref(t) for t in targets}

        # Validate all targets exist
        for target_name in target_names:
            if target_name not in self.nodes:
                raise ValueError(f"Target agent '{target_name}' not found in crew")

        # Create transition
        transition = FlowTransition(
            source=source_name,
            targets=target_names,
            condition=condition,
            instruction=instruction,
            prompt_builder=prompt_builder,
            predicate=predicate,
            priority=priority,
            metadata=metadata
        )

        source_node.add_transition(transition)

        # Update dependencies in target nodes
        for target_name in target_names:
            target_node = self.nodes[target_name]

            if self._would_create_cycle(source_name, target_name):
                self.logger.debug(
                    "Skipping dependency %s → %s to avoid circular dependency",
                    source_name,
                    target_name
                )
                continue

            target_node.dependencies.add(source_name)

        self.logger.info(
            f"Added {condition.value} transition: {source_name} → {target_names}"
        )

        return source_node

    def on_success(
        self,
        source: AgentRef,
        targets: Union[AgentRef, Iterable[AgentRef]],
        **kwargs
    ) -> FlowNode:
        """Convenience method for ON_SUCCESS transitions."""
        return self.task_flow(
            source,
            targets,
            condition=TransitionCondition.ON_SUCCESS,
            **kwargs
        )

    def on_error(
        self,
        source: AgentRef,
        targets: Union[AgentRef, Iterable[AgentRef]],
        **kwargs
    ) -> FlowNode:
        """Convenience method for ON_ERROR transitions."""
        return self.task_flow(
            source,
            targets,
            condition=TransitionCondition.ON_ERROR,
            **kwargs
        )

    def on_condition(
        self,
        source: AgentRef,
        targets: Union[AgentRef, Iterable[AgentRef]],
        predicate: Callable[[Any], Union[bool, Awaitable[bool]]],
        **kwargs
    ) -> FlowNode:
        """Convenience method for ON_CONDITION transitions."""
        return self.task_flow(
            source,
            targets,
            condition=TransitionCondition.ON_CONDITION,
            predicate=predicate,
            **kwargs
        )

    async def run_flow(
        self,
        initial_task: str,
        entry_point: Optional[AgentRef] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_iterations: int = 100,
        **shared_data
    ) -> CrewResult:
        """
        Execute the workflow starting from the entry point.

        The workflow execution follows these steps:
        1. Initialize all agents to idle state
        2. Schedule entry point agent(s) to ready state
        3. Execute ready agents (respecting max_parallel_tasks)
        4. Evaluate transitions based on results/errors
        5. Schedule next agents based on activated transitions
        6. Repeat until all terminal nodes complete or max_iterations reached

        Args:
            initial_task: The initial task/prompt for the workflow
            entry_point: Starting agent(s) (defaults to agents with no dependencies)
            user_id: User identifier for tracking
            session_id: Session identifier
            max_iterations: Maximum execution rounds (safety limit)
            **shared_data: Additional shared data for all agents

        Returns:
            CrewResult: Standardized execution payload containing outputs,
            metadata, and execution logs.

        Raises:
            RuntimeError: If workflow gets stuck or exceeds max_iterations
            TimeoutError: If execution_timeout is exceeded
        """
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'

        # Initialize execution context
        self.current_context = AgentContext(
            user_id=user_id,
            session_id=session_id,
            original_query=initial_task,
            shared_data=shared_data,
            agent_results={}
        )

        self.execution_log = []
        start_time = asyncio.get_event_loop().time()

        # Reset all agents to idle state by creating new FSM instances
        for node in self.nodes.values():
            # Create a new FSM instance to reset to initial state
            node.fsm = AgentTaskMachine(agent_name=node.agent.name)
            node.result = None
            node.response = None
            node.error = None
            node.retry_count = 0
            node.transitions_processed = False  # Reset transition processing flag
            node.metadata = None

        # Determine entry points
        entry_agents = self._get_entry_agents(entry_point)

        if not entry_agents:
            raise ValueError("No entry point agents found. Specify entry_point or add agents with no dependencies.")

        self.logger.info(f"Starting workflow with entry points: {entry_agents}")

        # Schedule entry point agents
        for agent_name in entry_agents:
            node = self.nodes[agent_name]
            node.fsm.schedule()

        # Main execution loop
        iteration = 0
        while iteration < max_iterations:
            # Check timeout
            if self.execution_timeout:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > self.execution_timeout:
                    raise TimeoutError(
                        f"Workflow execution exceeded timeout of {self.execution_timeout}s"
                    )

            # Get agents ready to execute
            ready_agents = self._get_ready_agents()

            if not ready_agents:
                # Check if we're done
                if self._is_workflow_complete():
                    break

                # Check if we're stuck
                if not self._has_active_agents():
                    raise RuntimeError(
                        f"Workflow is stuck at iteration {iteration}. "
                        f"No ready agents and no active agents. "
                        f"This may indicate missing transitions or unsatisfied dependencies."
                    )

                # Wait for active agents
                await asyncio.sleep(0.1)
                iteration += 1
                continue

            # Execute ready agents in parallel
            await self._execute_agents_parallel(ready_agents)

            # Process completed agents and activate transitions
            await self._process_transitions()

            iteration += 1

        if iteration >= max_iterations:
            raise RuntimeError(
                f"Workflow exceeded max iterations ({max_iterations}). "
                f"Possible infinite loop or very complex workflow."
            )

        end_time = asyncio.get_event_loop().time()

        agent_ids: List[str] = []
        for entry in self.execution_log:
            agent_name = entry.get("agent_id") or entry.get("agent_name")
            if agent_name and agent_name not in agent_ids:
                agent_ids.append(agent_name)

        for agent_name in self.nodes:
            if agent_name not in agent_ids:
                agent_ids.append(agent_name)

        responses: Dict[str, Any] = {}
        agents_info: List[AgentExecutionInfo] = []
        results_payload: List[Any] = []
        errors: Dict[str, str] = {}
        last_output: Optional[Any] = None

        for agent_name in agent_ids:
            node = self.nodes.get(agent_name)
            if not node:
                continue

            if node.result is not None:
                results_payload.append(node.result)
                responses[agent_name] = node.response
                metadata = (
                    node.metadata
                    if isinstance(node.metadata, AgentExecutionInfo)
                    else build_agent_metadata(
                        agent_name,
                        node.agent,
                        node.response,
                        node.result,
                        node.execution_time,
                        'completed'
                    )
                )
                agents_info.append(metadata)
                last_output = node.result
            else:
                results_payload.append(node.result)
                responses[agent_name] = node.response
                status_value = 'failed' if node.error is not None else 'pending'
                error_message = str(node.error) if node.error else None
                if error_message:
                    errors[agent_name] = error_message
                metadata = (
                    node.metadata
                    if isinstance(node.metadata, AgentExecutionInfo)
                    else build_agent_metadata(
                        agent_name,
                        node.agent,
                        node.response,
                        node.result,
                        node.execution_time,
                        status_value,
                        error_message
                    )
                )
                agents_info.append(metadata)

        success_count = sum(info.status == 'completed' for info in agents_info)
        failure_count = sum(info.status == 'failed' for info in agents_info)
        status = determine_run_status(success_count, failure_count)

        # Get final output from terminal nodes
        terminal_results = [
            node.result
            for node in self.nodes.values()
            if node.is_terminal and node.fsm.current_state == node.fsm.completed
        ]
        final_output = terminal_results[-1] if terminal_results else ''

        return CrewResult(
            output=final_output or last_output,
            response=responses,
            results=results_payload,
            agent_ids=agent_ids,
            agents=agents_info,
            errors=errors,
            execution_log=self.execution_log,
            total_time=end_time - start_time,
            status=status,
            metadata={
                'mode': 'fsm',
                'iterations': iteration,
                'completed': success_count,
                'failed': failure_count
            }
        )


    def _get_entry_agents(self, entry_point: Optional[AgentRef]) -> Set[str]:
        """Determine which agents should be entry points."""
        if entry_point:
            if isinstance(entry_point, (list, tuple, set)):
                return {self._resolve_agent_ref(e) for e in entry_point}
            return {self._resolve_agent_ref(entry_point)}

        # Find agents with no dependencies
        return {
            name for name, node in self.nodes.items()
            if not node.dependencies
        }

    def _get_ready_agents(self) -> Set[str]:
        """Get all agents in ready state."""
        return {
            name for name, node in self.nodes.items()
            if node.fsm.current_state == node.fsm.ready
        }

    def _has_active_agents(self) -> bool:
        """Check if any agents are currently running."""
        return any(
            node.fsm.current_state == node.fsm.running
            for node in self.nodes.values()
        )

    def _truncate_text(self, text: Optional[str], *, enabled: bool = True) -> str:
        """Truncate text using configured length."""
        if text is None or not enabled:
            return text or ""

        if self.truncation_length is None or self.truncation_length <= 0:
            return text

        if len(text) <= self.truncation_length:
            return text

        return f"{text[:self.truncation_length]}..."

    def _is_workflow_complete(self) -> bool:
        """Check if all terminal nodes have completed or failed (without retries)."""
        terminal_nodes = [
            node for node in self.nodes.values() if node.is_terminal
        ]

        if terminal_nodes:
            # Terminal nodes are complete if they're in completed state OR
            # in failed state with no retries remaining
            return all(
                node.fsm.current_state == node.fsm.completed or
                (node.fsm.current_state == node.fsm.failed and not node.can_retry)
                for node in terminal_nodes
            )

        # If no terminal nodes defined, check if all nodes are done
        return all(
            node.fsm.current_state == node.fsm.completed or
            (node.fsm.current_state == node.fsm.failed and not node.can_retry)
            for node in self.nodes.values()
        )

    async def _execute_agents_parallel(self, agent_names: Set[str]) -> None:
        """Execute multiple agents in parallel."""
        tasks = []

        for agent_name in agent_names:
            node = self.nodes[agent_name]
            node.fsm.start()  # Transition to running state
            tasks.append(self._execute_single_agent(agent_name))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_single_agent(self, agent_name: str) -> None:
        """Execute a single agent and update its state."""
        node = self.nodes[agent_name]
        node.started_at = datetime.now()

        try:
            # Ensure agent is configured
            await self._ensure_agent_ready(node.agent)

            # Build prompt based on dependencies
            prompt = await self._build_agent_prompt(node)

            # Execute with semaphore for rate limiting
            async with self.semaphore:
                start_time = asyncio.get_event_loop().time()

                response = await node.execute(
                    prompt=prompt,
                    ctx={
                        "session_id": self.current_context.session_id,
                        "user_id": self.current_context.user_id,
                        **self.current_context.shared_data
                    }
                )

                end_time = asyncio.get_event_loop().time()
                node.execution_time = end_time - start_time

            # Extract result
            result = self._extract_result(response)
            node.result = result
            node.response = response
            node.completed_at = datetime.now()
            # Build agent execution info
            node.agent_info = build_agent_metadata(
                agent_id=agent_name,
                agent=node.agent,
                response=response,
                output=result,
                execution_time=node.execution_time,
                status='completed',
                error=None
            )

            # Store in context
            self.current_context.agent_results[agent_name] = result

            # Transition to completed
            node.fsm.succeed()

            # Log execution
            self.execution_log.append({
                "agent_id": agent_name,
                "agent_name": agent_name,
                "state": "completed",
                "execution_time": node.execution_time,
                "input": self._truncate_text(prompt),
                "output": self._truncate_text(result),
                "started_at": node.started_at.isoformat(),
                "completed_at": node.completed_at.isoformat(),
                "result_length": len(str(result)),
                "success": True
            })

            self.logger.info(
                f"Agent '{agent_name}' completed in {node.execution_time:.2f}s"
            )

        except Exception as e:
            node.error = e
            node.completed_at = datetime.now()
            node.fsm.fail()
            node.response = None
            # Build agent execution info for failure
            node.agent_info = build_agent_metadata(
                agent_id=agent_name,
                agent=node.agent,
                response=None,
                output=None,
                execution_time=node.execution_time or 0.0,
                status='failed',
                error=str(e)
            )

            self.execution_log.append({
                "agent_id": agent_name,
                "agent_name": agent_name,
                "state": "failed",
                "error": str(e),
                "started_at": node.started_at.isoformat() if node.started_at else None,
                "completed_at": node.completed_at.isoformat(),
                "retry_count": node.retry_count,
                "success": False
            })

            self.logger.error(
                f"Agent '{agent_name}' failed: {e}",
                exc_info=True
            )

    async def _process_transitions(self) -> None:
        """Process transitions for all completed/failed agents."""
        for agent_name, node in self.nodes.items():
            # Only process nodes that just completed or failed AND haven't been processed yet
            if node.fsm.current_state not in [node.fsm.completed, node.fsm.failed]:
                continue

            # Skip if transitions already processed
            if node.transitions_processed:
                continue

            # Get active transitions
            error = node.error if node.fsm.current_state == node.fsm.failed else None
            active_transitions = await node.get_active_transitions(error)

            if not active_transitions:
                # Check for retry on failure
                if node.fsm.current_state == node.fsm.failed and node.can_retry:
                    self.logger.info(
                        f"Retrying agent '{agent_name}' (attempt {node.retry_count + 1}/{node.max_retries})"
                    )
                    node.retry_count += 1
                    node.fsm.retry()
                    # Don't mark as processed - allow retry to execute
                    node.transitions_processed = False
                else:
                    # Mark as processed if no transitions and no retry
                    node.transitions_processed = True
                continue

            # Activate transitions
            transition_activated = False
            for transition in active_transitions:
                if await self._activate_transition(transition):
                    transition_activated = True

            # Mark transitions as processed only when activation succeeded
            node.transitions_processed = transition_activated

    async def _activate_transition(self, transition: FlowTransition) -> bool:
        """Activate a transition and schedule target agents.

        Returns:
            True if at least one target agent was scheduled or reactivated.
        """
        scheduled_any = False

        for target_name in transition.targets:
            target_node = self.nodes[target_name]
            scheduled = False

            if not self._are_dependencies_satisfied(target_node):
                self.logger.debug(
                    "Dependencies for '%s' not yet satisfied after transition from '%s'",
                    target_name,
                    transition.source
                )
                continue

            if target_node.fsm.current_state == target_node.fsm.idle:
                target_node.fsm.schedule()
                scheduled = True
            elif target_node.fsm.current_state == target_node.fsm.blocked:
                target_node.fsm.unblock()
                scheduled = True
            elif target_node.fsm.current_state == target_node.fsm.failed and target_node.can_retry:
                target_node.fsm.retry()
                scheduled = True
            elif target_node.fsm.current_state == target_node.fsm.ready:
                scheduled = True

            if scheduled:
                self.logger.debug(
                    f"Scheduled agent '{target_name}' via transition from '{transition.source}'"
                )
                scheduled_any = True

        return scheduled_any

    def _would_create_cycle(self, source_name: str, target_name: str) -> bool:
        """Check if adding a dependency would introduce a cycle."""
        if source_name == target_name:
            return True

        visited = set()
        stack = [source_name]

        while stack:
            current = stack.pop()
            if current == target_name:
                return True
            if current in visited:
                continue
            visited.add(current)

            current_node = self.nodes.get(current)
            if not current_node:
                continue

            stack.extend(current_node.dependencies)

        return False

    def _are_dependencies_satisfied(self, node: FlowNode) -> bool:
        """Check if all dependencies for a node are satisfied."""
        for dep_name in node.dependencies:
            dep_node = self.nodes[dep_name]
            if dep_node.fsm.current_state != dep_node.fsm.completed:
                return False
        return True

    async def _build_agent_prompt(self, node: FlowNode) -> str:
        """Build the prompt for an agent based on its dependencies and transitions."""
        # Gather results from dependencies
        dependencies = {}
        for dep_name in node.dependencies:
            dep_node = self.nodes[dep_name]
            if dep_node.result is not None:
                dependencies[dep_name] = dep_node.result

        # Find the transition that activated this agent
        activating_transition = None
        for dep_name in node.dependencies:
            dep_node = self.nodes[dep_name]
            for transition in dep_node.outgoing_transitions:
                if node.name in transition.targets:
                    activating_transition = transition
                    break
            if activating_transition:
                break

        # Use transition's prompt builder if available
        if activating_transition:
            return await activating_transition.build_prompt(
                self.current_context,
                dependencies
            )

        # Default prompt building
        if not dependencies:
            return self.current_context.original_query

        parts = [
            f"Task: {self.current_context.original_query}\n",
            "\nContext from previous agents:",
        ]

        for dep_name, result in dependencies.items():
            parts.extend((f"\n--- {dep_name} ---", str(result)))

        return "\n".join(parts)

    async def _ensure_agent_ready(self, agent: Union[BasicAgent, AbstractBot]) -> None:
        """Ensure agent is configured before execution."""
        if hasattr(agent, "is_configured") and agent.is_configured:
            return

        agent_id = id(agent)
        lock = self._agent_locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._agent_locks[agent_id] = lock

        async with lock:
            if not (hasattr(agent, "is_configured") and agent.is_configured):
                self.logger.info(f"Auto-configuring agent '{agent.name}'")
                await agent.configure()

    def _extract_result(self, response: Any) -> str:
        """Extract result string from response."""
        if isinstance(response, (AIMessage, AgentResponse)) or hasattr(response, 'content'):
            return response.content
        return str(response)

    def visualize_workflow(self, format: str = "mermaid") -> str:
        """
        Generate a visual representation of the workflow.

        Args:
            format: Output format ("mermaid" for Mermaid diagrams)

        Returns:
            String representation of the workflow diagram
        """
        if format == "mermaid":
            lines = ["graph TD"]

            for agent_name, node in self.nodes.items():
                # Node style based on state
                if node.fsm.current_state == node.fsm.completed:
                    lines.append(f"    {agent_name}[{agent_name}]:::completed")
                elif node.fsm.current_state == node.fsm.failed:
                    lines.append(f"    {agent_name}[{agent_name}]:::failed")
                elif node.fsm.current_state == node.fsm.running:
                    lines.append(f"    {agent_name}[{agent_name}]:::running")
                else:
                    lines.append(f"    {agent_name}[{agent_name}]")

                # Transitions
                for transition in node.outgoing_transitions:
                    for target in transition.targets:
                        arrow_label = transition.condition.value
                        lines.append(f"    {agent_name} -->|{arrow_label}| {target}")

            # Styles
            lines.extend([
                "    classDef completed fill:#90EE90",
                "    classDef failed fill:#FFB6C1",
                "    classDef running fill:#87CEEB"
            ])

            return "\n".join(lines)

        raise ValueError(f"Unsupported format: {format}")

    def get_workflow_stats(self) -> Dict[str, Any]:
        """Get statistics about the workflow."""
        total_nodes = len(self.nodes)
        states_count = {}

        for node in self.nodes.values():
            state_name = node.fsm.current_state.name
            states_count[state_name] = states_count.get(state_name, 0) + 1

        return {
            "total_agents": total_nodes,
            "states": states_count,
            "execution_log_entries": len(self.execution_log),
            "has_context": self.current_context is not None
        }
