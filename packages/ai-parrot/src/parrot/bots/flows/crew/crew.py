"""AgentCrew — Parallel, Sequential, Flow, and Loop-Based Execution.

Moved from ``parrot.bots.orchestration.crew`` to ``parrot.bots.flows.crew``
(FEAT-143). All result models have been migrated:
  - ``CrewResult`` → ``FlowResult``
  - ``AgentExecutionInfo`` → ``NodeExecutionInfo``
  - ``build_agent_metadata`` → ``build_node_metadata``
  - ``AgentResult`` → ``NodeResult``

The original ``orchestration/crew.py`` is left in place for review.

TASK-980: ``AgentContext`` removed; sequential/loop/parallel modes now use
``FlowContext`` for execution state tracking.

Module-level constant ``_INTERNAL_SHARED_KEYS`` lists keys that are placed
in ``FlowContext.shared_data`` for framework bookkeeping and must NOT be
forwarded as kwargs to agent calls.
"""
from __future__ import annotations
from typing import (
    List, Dict, Any, Union, Optional, Literal, Set, Callable, Tuple,
    TYPE_CHECKING,
)
from datetime import datetime

if TYPE_CHECKING:
    from ....models.crew_definition import CrewDefinition
from ....models.crew_definition import ExecutionMode
import contextlib
import asyncio
import uuid
from tqdm.asyncio import tqdm as async_tqdm
from navconfig.logging import logging
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611 # noqa

from ...agent import BasicAgent
from ...abstract import AbstractBot
from ....clients import AbstractClient
from ....clients.factory import SUPPORTED_CLIENTS
from ....clients.google import GoogleGenAIClient
from ....tools.manager import ToolManager
from ....tools.agent import AgentTool
from ....tools.abstract import AbstractTool
from ....models.responses import (
    AIMessage,
    AgentResponse
)
from ....models.status import AgentStatus

# Canonical result models (replacing parrot.models.crew)
from ..core.result import (
    FlowResult,
    NodeExecutionInfo,
    NodeResult,
    build_node_metadata,
    determine_run_status,
)
from ..core.storage import (
    CrewExecutionDocument,
    ExecutionMemory,
    PersistenceMixin,
    SynthesisMixin,
)
from ..core.storage.backends import ResultStorage
from ..core.storage.synthesis import SYNTHESIS_PROMPT
from ..core.context import FlowContext  # noqa: F401 — re-export for backward compat
from ..core.types import (
    AgentRef,  # noqa: F401 — re-export for backward compat
    CrewHookCallback,
    DependencyResults,  # noqa: F401 — re-export for backward compat
    PromptBuilder,  # noqa: F401 — re-export for backward compat
)
from ..core.fsm import AgentTaskMachine
from ..tools import ResultRetrievalTool
from .nodes import CrewAgentNode

__all__ = [
    "AgentCrew",
    "AgentNode",
    # Re-exports from flows.core for backward compatibility
    "FlowContext",
    "AgentRef",
    "DependencyResults",
    "PromptBuilder",
]


# CrewAgentNode is imported from .nodes (extracted in TASK-977)
# Backward-compatibility alias: AgentNode = CrewAgentNode
AgentNode = CrewAgentNode

# Keys placed in FlowContext.shared_data for framework bookkeeping.
# These must NOT be forwarded to agent calls (agent.ask / .conversation / .invoke)
# because they contain non-serialisable internal objects (ExecutionMemory, dicts, …).
_INTERNAL_SHARED_KEYS: frozenset = frozenset(
    {'execution_memory', 'shared_state', 'crew_execution_id'}
)


class AgentCrew(PersistenceMixin, SynthesisMixin):
    """
    Enhanced AgentCrew supporting multiple execution modes.

    This crew orchestrator provides multiple ways to execute agents:

    1. SEQUENTIAL (run_sequential): Agents execute in a pipeline, where each
    agent processes the output of the previous agent. This is useful for
    multi-stage processing where each stage refines or transforms the data.

    2. PARALLEL (run_parallel): Multiple agents execute simultaneously on
    different tasks using asyncio.gather(). This is useful when you have
    multiple independent analyses or tasks that can be performed concurrently.

    3. FLOW (run_flow): Agents execute based on a dependency graph (DAG),
    automatically parallelizing independent agents while respecting dependencies.
    This is the most flexible mode, supporting complex workflows like:
    - One agent → multiple agents (fan-out/parallel processing)
    - Multiple agents → one agent (fan-in/synchronization)
    - Complex multi-stage pipelines with parallel branches

    4. LOOP (run_loop): Agents execute sequentially in repeated iterations,
    reusing the previous iteration's output as the next iteration's input until
    an LLM-evaluated stopping condition is satisfied or a safety limit is
    reached.

    Features:
    - Shared tool manager across agents
    - Comprehensive execution logging
    - Result aggregation and context passing
    - Error handling and recovery
    - Optional LLM for result synthesis
    - Rate limiting with semaphores
    - Circular dependency detection
    """

    # Default truncation length for logging and summaries
    default_truncation_length: int = 200

    def __init__(
        self,
        name: str = "AgentCrew",
        agents: List[Union[BasicAgent, AbstractBot]] = None,
        shared_tool_manager: ToolManager = None,
        max_parallel_tasks: int = 10,
        llm: Optional[Union[str, AbstractClient]] = None,
        auto_configure: bool = True,
        truncation_length: Optional[int] = None,
        truncate_context_summary: bool = True,
        embedding_model: Any = None,
        enable_analysis: bool = False,
        dimension: int = 384,  # NEW
        index_type: str = "Flat",  # NEW: "Flat", "FlatIP", o "HNSW"
        agent_execution_timeout: float = 600.0, # Timeout in seconds per agent execution
        persist_results: bool = True,
        result_storage: Union[str, "ResultStorage", None] = None,
        persist_agent_results: bool = True,
        tenant: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize the AgentCrew.

        Args:
            name: Name of the crew
            agents: List of agents to add to the crew
            shared_tool_manager: Optional shared tool manager for all agents
            max_parallel_tasks: Maximum number of parallel tasks (for rate limiting)
            persist_results: Opt-out for ALL result persistence (crew + per-agent).
            result_storage: Backend name/instance for ``ResultStorage`` resolution.
            persist_agent_results: Granular opt-out for per-agent incremental
                persistence only (FEAT-306); has no effect when
                ``persist_results`` is already ``False``.
            tenant: Tenant identifier for multi-tenant isolation (FEAT-307).
                Persisted on every saved execution (see ``_save_result()``
                call sites in ``run_*``). Defaults to ``"global"`` when not
                provided — matching ``CrewDefinition.tenant``'s own default.
                ``from_definition()`` wires this automatically from the
                definition's ``tenant`` field.
        """
        self.name = name or 'AgentCrew'
        self.agents: Dict[str, Union[BasicAgent, AbstractBot]] = {}
        self._auto_configure: bool = auto_configure
        # internal tools:
        self.tools: List[AbstractTool] = []
        self.shared_tool_manager = shared_tool_manager or ToolManager()
        self.max_parallel_tasks = max_parallel_tasks
        self.execution_log: List[Dict[str, Any]] = []
        self.logger = logging.getLogger(f"parrot.crews.{self.name}")
        self.semaphore = asyncio.Semaphore(max_parallel_tasks)
        if isinstance(llm, str):
            client_cls = SUPPORTED_CLIENTS.get(llm.lower(), None)
            self._llm = client_cls(**kwargs) if client_cls else None
        elif isinstance(llm, AbstractClient):
            self._llm = llm  # Optional LLM for orchestration tasks
        else:
            client_cls = SUPPORTED_CLIENTS.get('google')
            self._llm = client_cls(**kwargs) if client_cls else None
        self.truncation_length = (
            truncation_length
            if truncation_length is not None
            else self.__class__.default_truncation_length
        )
        self.truncate_context_summary = truncate_context_summary
        # Workflow graph for flow-based execution
        self.workflow_graph: Dict[str, CrewAgentNode] = {}
        self.initial_agent: Optional[str] = None
        self.final_agents: Set[str] = set()
        self.use_tqdm: bool = kwargs.get('use_tqdm', True)
        # Internal tracking of per-agent initialization guards
        self._agent_locks: Dict[int, asyncio.Lock] = {}
        # Execution Memory:
        self.enable_analysis = enable_analysis
        self.embedding_model = embedding_model if enable_analysis else None
        self.execution_memory = ExecutionMemory(
            embedding_model=embedding_model,
            dimension=dimension,
            index_type=index_type
        )
        # Register Retrieval Tool
        self.retrieval_tool = ResultRetrievalTool(
            self.execution_memory
        )
        if self._llm:
            try:
                self._llm.register_tool(self.retrieval_tool)
            except Exception as e:
                self.logger.warning(
                    f"Failed to register retrieval tool: {e}"
                )
        self._summary = None
        self.last_crew_result: Optional[FlowResult] = None
        self._last_execution_id: Optional[str] = None
        self._last_user_id: Optional[str] = None
        self._last_session_id: Optional[str] = None
        self.agent_execution_timeout = agent_execution_timeout
        
        # Status Tracking
        self._agent_statuses: Dict[str, Dict[str, Any]] = {}
        
        # Result persistence (FEAT-147)
        self._persist_results: bool = persist_results
        self._result_storage_arg: Union[str, "ResultStorage", None] = result_storage
        self._result_storage: Optional["ResultStorage"] = (
            result_storage if isinstance(result_storage, ResultStorage) else None
        )
        self._persist_tasks: set[asyncio.Task] = set()
        # Granular per-agent persistence opt-out (FEAT-306)
        self._persist_agent_results: bool = persist_agent_results
        # Tenant identifier for multi-tenant isolation (FEAT-307)
        self._tenant: str = tenant or "global"

        # Lifecycle hooks (FEAT-157)
        self._on_complete_hooks: List[CrewHookCallback] = []
        self._on_error_hooks: List[CrewHookCallback] = []

        # Add agents if provided
        if agents:
            for agent in agents:
                self.add_agent(agent)
                self.workflow_graph[agent.name] = CrewAgentNode(
                    agent=agent, node_id=agent.name
                )

    @property
    def agent_statuses(self) -> Dict[str, Dict[str, Any]]:
        """
        Get the status of all agents.
        """
        return self._agent_statuses

    def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of a specific agent.
        """
        return self._agent_statuses.get(agent_id)

    def build_execution_document(self) -> Optional["CrewExecutionDocument"]:
        """Assemble the document for the LAST run from in-process state (LLM-free).

        Deterministic, LLM-free reconstruction (FEAT-306) built from
        ``self.execution_memory`` + ``self.last_crew_result`` — no storage
        round-trip required.

        Returns:
            The ``CrewExecutionDocument`` for the most recent run, or
            ``None`` when no run has completed yet.
        """
        if self.last_crew_result is None:
            return None
        # metadata['mode'] holds the short form ('sequential', 'loop',
        # 'parallel', 'flow'); the persisted document's `method` field uses
        # the full run_* name (e.g. 'run_sequential') — normalise so
        # build_execution_document() matches CrewExecutionDocument.from_storage()
        # for the same run (TASK-1770 e2e equality requirement).
        _mode = self.last_crew_result.metadata.get('mode', 'unknown')
        _method = _mode if _mode.startswith('run_') else f'run_{_mode}'
        return CrewExecutionDocument.from_memory(
            execution_id=self._last_execution_id,
            crew_name=self.name,
            method=_method,
            memory=self.execution_memory,
            result=self.last_crew_result,
            user_id=self._last_user_id,
            session_id=self._last_session_id,
        )

    # ── Lifecycle hooks (FEAT-157) ────────────────────────────────────────

    def on_complete(self, callback: CrewHookCallback) -> None:
        """Register a callback to fire when crew execution completes.

        Fires for status ``'completed'`` and ``'partial'``. Callbacks receive
        ``(crew_name, result)`` and may be sync or async.

        Hooks fire in registration order. If a hook raises, the exception is
        caught and logged — it does **not** prevent the result from returning.

        Args:
            callback: Callable with signature
                ``(crew_name: str, result: FlowResult) -> None``.
        """
        self._on_complete_hooks.append(callback)

    def on_error(self, callback: CrewHookCallback) -> None:
        """Register a callback to fire when crew execution has errors.

        Fires for status ``'failed'`` and ``'partial'``. Callbacks receive
        ``(crew_name, result)`` and may be sync or async.

        Hooks fire in registration order. If a hook raises, the exception is
        caught and logged — it does **not** prevent the result from returning.

        Args:
            callback: Callable with signature
                ``(crew_name: str, result: FlowResult) -> None``.
        """
        self._on_error_hooks.append(callback)

    async def _fire_hooks(self, result: Any) -> None:
        """Dispatch lifecycle hooks based on result status.

        Called by all ``run_*()`` methods after ``FlowResult`` is built,
        before the persist block and ``return`` statement.

        - ``'completed'``: on_complete hooks only
        - ``'partial'``: both on_complete AND on_error hooks
        - ``'failed'``: on_error hooks only

        Exceptions in individual hooks are caught and logged — they never
        block the result from being returned to the caller.

        Args:
            result: The ``FlowResult`` produced by the run.
        """
        hooks_to_fire: List[CrewHookCallback] = []
        if result.status in ('completed', 'partial'):
            hooks_to_fire.extend(self._on_complete_hooks)
        if result.status in ('failed', 'partial'):
            hooks_to_fire.extend(self._on_error_hooks)

        for hook in hooks_to_fire:
            try:
                ret = hook(self.name, result)
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception as exc:
                self.logger.error(
                    "Error in crew lifecycle hook %r: %s", hook, exc
                )

    def _schedule_agent_persist(
        self,
        agent_result: "NodeResult",
        *,
        execution_id: str,
        method: str,
        user_id: str,
        session_id: str,
    ) -> None:
        """Schedule the incremental per-agent persist as a tracked task (FEAT-306).

        Mirrors the fire-and-forget + ``_persist_tasks`` bookkeeping pattern
        used for the final crew-level persist, so ``aclose()`` drains both
        planes of writes.

        Args:
            agent_result: The ``NodeResult`` that was just added to
                ``execution_memory``.
            execution_id: Crew-level execution id for this run.
            method: Execution method name (e.g. ``"run_sequential"``).
            user_id: User identifier propagated to the stored document.
            session_id: Session identifier propagated to the stored document.
        """
        _agent_task = asyncio.get_running_loop().create_task(
            self._save_agent_result(
                agent_result,
                execution_id=execution_id,
                method=method,
                user_id=user_id,
                session_id=session_id,
            )
        )
        self._persist_tasks.add(_agent_task)
        _agent_task.add_done_callback(self._persist_tasks.discard)

    def _register_agents_as_tools(self):
        """
        Register each agent as a tool in the LLM's tool manager.
        """
        if not self._llm:
            return

        for agent_id, agent in self.agents.items():
            try:
                agent_tool = agent.as_tool(
                    tool_name=f"agent_{agent_id}",
                    tool_description=(
                        f"Agent {agent.name}: {agent.description} "
                        f"Re-execute to gather additional information. "
                        f"Use when the user needs more details or updated data from this agent."
                    ),
                    use_conversation_method=False  # no conversation history
                )

                # Add to LLM's tool manager
                if hasattr(self._llm, 'tool_manager'):
                    self._llm.tool_manager.add_tool(agent_tool)
            except Exception as e:
                self.logger.warning(
                    f"Failed to register {agent.name} as tool: {e}"
                )

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_definition(
        cls,
        crew_def: "CrewDefinition",
        *,
        class_resolver: Callable[[str], Optional[type]],
        tool_resolver: Optional[Callable[[str], Optional[AbstractTool]]] = None,
        **kwargs,
    ) -> "AgentCrew":
        """Create an AgentCrew from a CrewDefinition.

        Args:
            crew_def: The crew definition to build from.
            class_resolver: Callable that maps agent class name str to the
                concrete class. When it returns ``None`` the agent falls back
                to ``BasicAgent``.
            tool_resolver: Optional callable that maps tool name str to an
                ``AbstractTool`` instance. When ``None`` shared tools are
                skipped.
            **kwargs: Extra kwargs forwarded to ``AgentCrew.__init__``
                (e.g. ``llm``, ``auto_configure``).

        Returns:
            A fully configured ``AgentCrew`` instance.
        """
        agents = []
        for agent_def in crew_def.agents:
            agent_class = class_resolver(agent_def.agent_class)
            if agent_class is None:
                agent_class = BasicAgent
            agent = agent_class(
                name=agent_def.name or agent_def.agent_id,
                tools=list(agent_def.tools),
                **agent_def.config,
            )
            if agent_def.system_prompt:
                agent.system_prompt = agent_def.system_prompt
            agents.append(agent)

        # Allow callers to override max_parallel_tasks/tenant via kwargs.
        max_parallel_tasks = kwargs.pop(
            "max_parallel_tasks", crew_def.max_parallel_tasks
        )
        tenant = kwargs.pop("tenant", crew_def.tenant)
        crew = cls(
            name=crew_def.name,
            agents=agents,
            max_parallel_tasks=max_parallel_tasks,
            tenant=tenant,
            **kwargs,
        )

        if tool_resolver:
            for tool_name in crew_def.shared_tools:
                if tool := tool_resolver(tool_name):
                    crew.add_shared_tool(tool, tool_name)

        if crew_def.execution_mode == ExecutionMode.FLOW and crew_def.flow_relations:
            for relation in crew_def.flow_relations:
                source_ids = (
                    relation.source
                    if isinstance(relation.source, list)
                    else [relation.source]
                )
                target_ids = (
                    relation.target
                    if isinstance(relation.target, list)
                    else [relation.target]
                )
                source_agents = cls._resolve_agents_by_ids(crew.agents, source_ids)
                target_agents_list = cls._resolve_agents_by_ids(crew.agents, target_ids)
                if source_agents and target_agents_list:
                    crew.task_flow(
                        source_agents if len(source_agents) > 1 else source_agents[0],
                        target_agents_list if len(target_agents_list) > 1 else target_agents_list[0],
                    )
        return crew

    @staticmethod
    def _resolve_agents_by_ids(
        agents_dict: Dict[str, Any],
        agent_ids: List[str],
    ) -> List[Any]:
        """Return agent instances for the given agent IDs, skipping missing ones.

        Args:
            agents_dict: Mapping of agent name/id to agent instance (i.e.
                ``crew.agents``).
            agent_ids: List of agent IDs/names to look up.

        Returns:
            List of resolved agent instances. May be shorter than ``agent_ids``
            when some IDs are not found in ``agents_dict``.
        """
        return [agents_dict[aid] for aid in agent_ids if aid in agents_dict]

    def add_agent(self, agent: Union[BasicAgent, AbstractBot], agent_id: str = None) -> None:
        """Add an agent to the crew."""
        agent_id = agent_id or agent.name
        self.agents[agent_id] = agent

        # Share tools with new agent
        if self.shared_tool_manager:
            for tool_name in self.shared_tool_manager.list_tools():
                tool = self.shared_tool_manager.get_tool(tool_name)
                if tool and not agent.tool_manager.get_tool(tool_name):
                    agent.tool_manager.add_tool(tool, tool_name)

        # wrap agent as tool for use by main Agent:
        agent_tool = AgentTool(
            agent=agent,
            tool_name=agent_id,
            tool_description=getattr(agent, 'description', f"Execute {agent.name}"),
            use_conversation_method=True,
            execution_memory=self.execution_memory
        )

        self.tools.append(agent_tool)
        self.logger.info(f"Added agent '{agent_id}' to crew")
        # Log tools available to the agent
        try:
            agent_tools = agent.tool_manager.list_tools()
            self.logger.debug("Agent '%s' (ID: %s) initial tools: %s", agent.name, agent_id, agent_tools)
        except Exception as e:
            self.logger.debug(
                "Error listing tools for agent '%s': %s", agent_id, e
            )

        # Register as tool in LLM orchestrator (if exists)
        if self._llm:
            self._register_agents_as_tools()

        # Initialize status tracking
        self._agent_statuses[agent_id] = {
            "status": AgentStatus.IDLE.value,
            "last_active": datetime.now(),
            "task": None,
            "result": None,
            "error": None
        }

        # Subscribe to agent events
        agent.add_event_listener(
            agent.EVENT_STATUS_CHANGED, self._handle_agent_event
        )
        agent.add_event_listener(
            agent.EVENT_TASK_STARTED, self._handle_agent_event
        )
        agent.add_event_listener(
            agent.EVENT_TASK_COMPLETED, self._handle_agent_event
        )
        agent.add_event_listener(
            agent.EVENT_TASK_FAILED, self._handle_agent_event
        )

        self.logger.info(f"Agents added and tracking initialized for '{agent_id}'")

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent from the crew."""
        if agent_id in self.agents:
            del self.agents[agent_id]
            self.logger.info(
                f"Removed agent '{agent_id}' from crew"
            )
            return True
        return False

    def add_shared_tool(self, tool: AbstractTool, tool_name: str = None) -> None:
        """Add a tool shared across all agents."""
        self.shared_tool_manager.add_tool(tool, tool_name)

        # Add to all existing agents
        for agent in self.agents.values():
            if not agent.tool_manager.get_tool(tool_name or tool.name):
                agent.tool_manager.add_tool(tool, tool_name)

    async def _handle_agent_event(self, event_name: str, **kwargs) -> None:
        """Handle events from agents to update internal status tracking."""
        agent_name = kwargs.get("agent_name")
        # Map agent name to ID if needed, but we used ID as key.
        # Assuming agent.name matches key, or we need to find key by agent name?
        # In add_agent, we used agent_id as key. agent.name might be different.
        # Let's try to match.
        target_id = None
        if agent_name in self._agent_statuses:
            target_id = agent_name
        else:
            # Reverse lookup (slow but safe)
            for aid, agent in self.agents.items():
                if agent.name == agent_name:
                    target_id = aid
                    break
        
        if not target_id:
            return

        status_info = self._agent_statuses[target_id]
        status_info["last_active"] = datetime.now()

        if event_name == "task_started":
            status_info["status"] = AgentStatus.WORKING.value
            status_info["task"] = kwargs.get("task")
            status_info["started_at"] = datetime.now()
            self.logger.debug(f"Agent {target_id} started task")

        elif event_name == "task_completed":
            status_info["status"] = AgentStatus.COMPLETED.value
            # We mark as COMPLETED so UI shows it's done. Reusability should handle state reset elsewhere if needed.
            status_info["completed_at"] = datetime.now()
            # Capture result if provided
            if "result" in kwargs:
                status_info["result"] = kwargs["result"]
                self.logger.debug(f"Agent {target_id} completed task with result length {len(str(kwargs['result']))}")
            else:
                self.logger.warning(f"Agent {target_id} completed task but no result in event")

        elif event_name == "task_failed":
            status_info["status"] = AgentStatus.FAILED.value
            status_info["error"] = kwargs.get("error")
            status_info["completed_at"] = datetime.now()
            self.logger.error(f"Agent {target_id} failed: {kwargs.get('error')}")

        elif event_name == "status_changed":
            new_status = kwargs.get("status")
            if new_status:
                # Map string status to enum if needed, or just store
                status_info["status"] = new_status

    def get_agent_statuses(self) -> List[dict]:
        """Get current status of all agents."""
        statuses = []
        for agent_id, info in self._agent_statuses.items():
            # Get agent name
            agent = self.agents.get(agent_id)
            name = agent.name if agent else agent_id
            
            statuses.append({
                "agent_id": agent_id,
                "agent_name": name,
                "status": info["status"],
                "task": info["task"],
                "started_at": info.get("started_at", "").isoformat() if isinstance(info.get("started_at"), datetime) else None,
                "completed_at": info.get("completed_at", "").isoformat() if isinstance(info.get("completed_at"), datetime) else None,
                "error": info["error"]
            })
        return statuses

    def get_agent_result(self, agent_id: str) -> Optional[NodeResult]:
        """Return the most recent ``NodeResult`` for *agent_id*, or ``None``.

        Queries ``ExecutionMemory`` first (covers all execution modes that
        store results there).  Falls back to scanning ``last_crew_result``
        for the agent's ``NodeExecutionInfo`` when memory is not available.

        Args:
            agent_id: The agent's registered identifier.

        Returns:
            A ``NodeResult`` if the agent ran in the last execution, or
            ``None`` if no result is found.
        """
        if self.execution_memory:
            node_result = self.execution_memory.get_results_by_agent(agent_id)
            if node_result is not None:
                return node_result

        # Fallback: reconstruct a minimal NodeResult from NodeExecutionInfo
        if self.last_crew_result:
            for agent_info in self.last_crew_result.agents:
                if agent_info.agent_id == agent_id:
                    return NodeResult(
                        node_id=agent_id,
                        node_name=agent_info.agent_name,
                        task="",
                        result=agent_info.result,
                        metadata={
                            'status': agent_info.status,
                            'source': 'last_crew_result',
                        },
                        execution_time=agent_info.execution_time,
                    )
        return None

    def task_flow(self, source_agent: Any, target_agents: Any):
        """
        Define a task flow from source agent(s) to target agent(s).

        This method builds the workflow graph by defining dependencies between agents.
        It supports flexible configurations for different workflow patterns:

        - Single to multiple (fan-out): One agent's output goes to multiple agents
          for parallel processing
        - Multiple to single (fan-in): Multiple agents' outputs are aggregated by
          a single agent
        - Single to single: Simple sequential dependency

        The workflow graph is used by run_flow() to determine execution order and
        identify opportunities for parallel execution.

        Args:
            source_agent: The agent (or list of agents) that must complete first
            target_agents: The agent (or list of agents) that depend on source completion

        Examples:
            # Single source to multiple targets (parallel execution after writer completes)
            crew.task_flow(writer, [editor1, editor2])

            # Multiple sources to single target (final_reviewer waits for both editors)
            crew.task_flow([editor1, editor2], final_reviewer)

            # Single to single (simple sequential dependency)
            crew.task_flow(writer, editor1)
        """
        # Normalize inputs to lists for uniform processing
        sources = source_agent if isinstance(source_agent, list) else [source_agent]
        targets = target_agents if isinstance(target_agents, list) else [target_agents]

        # Build the dependency graph
        for source in sources:
            source_name = source.name
            node = self.workflow_graph[source_name]

            for target in targets:
                target_name = target.name
                target_node = self.workflow_graph[target_name]
                # Add dependency: target depends on source
                # This means target cannot execute until source completes
                target_node.dependencies.add(source_name)
                # Track successors for the source
                # This helps us traverse the graph forward
                node.successors.add(target_name)

        # Automatically detect initial and final agents based on the graph structure
        self._update_flow_metadata()

    def _update_flow_metadata(self):
        """
        Update metadata about the workflow (initial and final agents).

        Initial agents are those with no dependencies - they can start immediately.
        Final agents are those with no successors - the workflow is complete when they finish.

        This metadata is used by run_flow() to know when to start and when to stop.
        """
        # Find agents with no dependencies (initial agents)
        agents_with_deps = {
            name for name, node in self.workflow_graph.items()
            if node.dependencies
        }
        potential_initial = set(self.workflow_graph.keys()) - agents_with_deps

        if potential_initial and not self.initial_agent:
            # For now, assume single entry point. Could be extended for multiple entry points.
            self.initial_agent = next(iter(potential_initial))

        # Find agents with no successors (final agents)
        self.final_agents = {
            name for name, node in self.workflow_graph.items()
            if not node.successors
        }

    async def _execute_parallel_agents(
        self,
        agent_names: Set[str],
        context: FlowContext,
        on_agent_complete: Optional[Callable] = None,
    ) -> FlowResult:
        """
        Execute multiple agents in parallel and collect their results.

        This is the internal method that enables parallel execution of agents
        within the flow-based execution mode. It's called by run_flow() whenever
        multiple agents are ready to execute simultaneously.

        Args:
            agent_names: Set of agent names that are ready to execute
            context: The current FlowContext tracking execution state
        Returns:
            CrewResult with results from all executed agents
        """
        tasks = []
        agent_name_map = []

        for agent_name in agent_names:
            node = self.workflow_graph[agent_name]
            # get readiness of agent in AgentNode:
            agent = node.agent
            if agent_name not in self.agents:
                self.logger.warning(
                    f"Agent '{agent_name}' not found in crew, skipping"
                )
                continue
            await self._ensure_agent_ready(agent)
            # Double-check dependencies are satisfied (defensive programming)
            if context.can_execute(agent_name, node.dependencies):
                # Wire FSM: schedule + start before execution
                if node.fsm and str(node.fsm.current_state.id) == "idle":
                    node.fsm.schedule()
                if node.fsm and str(node.fsm.current_state.id) == "ready":
                    node.fsm.start()
                context.active_tasks.add(agent_name)
                # FEAT-163: execute_in_context removed; use execute(ctx, deps, **kwargs).
                # deps is the accumulated results dict from context.
                tasks.append(
                    node.execute(
                        context,
                        context.results,
                        timeout=self.agent_execution_timeout,
                    )
                )
                agent_name_map.append(agent_name)

        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and handle errors
        execution_results = {}
        for agent_name, result in zip(agent_name_map, results):
            node = self.workflow_graph[agent_name]
            if isinstance(result, Exception):
                context.errors[agent_name] = result
                context.active_tasks.discard(agent_name)
                # Transition FSM to failed (guard against double-transition)
                if node.fsm and str(node.fsm.current_state.id) != "failed":
                    node.fsm.fail()
                self.logger.error(
                    f"Error executing {agent_name}: {result}"
                )
                context.responses[agent_name] = None
                context.agent_metadata[agent_name] = build_node_metadata(
                    agent_name,
                    node.agent,
                    None,
                    None,
                    0.0,
                    'failed',
                    str(result)
                )
                self.execution_log.append({
                    'agent_id': agent_name,
                    'agent_name': node.agent.name,
                    'output': str(result),
                    'execution_time': 0,
                    'success': False,
                    'error': str(result)
                })

                # Save failed execution to memory (via shared_data)
                _exec_mem = context.shared_data.get('execution_memory')
                if _exec_mem:
                    _uid = context.shared_data.get('user_id', 'crew_user')
                    _sid = context.shared_data.get('session_id', 'unknown')
                    agent_result = NodeResult(
                        node_id=agent_name,
                        node_name=node.agent.name,
                        task=context.initial_task,
                        result=str(result),
                        metadata={
                            'success': False,
                            'error': str(result),
                            'mode': 'flow',
                            'user_id': _uid,
                            'session_id': _sid,
                        },
                        execution_time=0.0
                    )
                    _exec_mem.add_result(agent_result, vectorize=False)

                    # Persist per-agent result incrementally (FEAT-306) — skip
                    # silently when the helper is used outside a run_flow()
                    # invocation (no crew_execution_id threaded in shared_data).
                    _crew_execution_id = context.shared_data.get('crew_execution_id')
                    if _crew_execution_id:
                        self._schedule_agent_persist(
                            agent_result, execution_id=_crew_execution_id,
                            method='run_flow', user_id=_uid, session_id=_sid,
                        )
            else:
                output = result.get('output') if isinstance(result, dict) else result
                raw_response = result.get('response') if isinstance(result, dict) else result
                execution_time = result.get('execution_time', 0.0) if isinstance(result, dict) else 0.0
                metadata = build_node_metadata(
                    agent_name,
                    node.agent,
                    raw_response,
                    output,
                    execution_time,
                    'completed'
                )
                context.mark_completed(
                    agent_name,
                    output,
                    raw_response,
                    metadata
                )
                # Transition FSM to completed
                if node.fsm and str(node.fsm.current_state.id) == "running":
                    node.fsm.succeed()
                context.active_tasks.discard(agent_name)
                execution_results[agent_name] = output

                # Fire per-agent callback right after FSM succeeds
                if on_agent_complete:
                    await on_agent_complete(agent_name, output, context)
                self.execution_log.append({
                    'agent_id': agent_name,
                    'agent_name': node.agent.name,
                    'input': self._truncate_text(result.get('prompt', '') if isinstance(result, dict) else ''),
                    'output': self._truncate_text(output),
                    'execution_time': execution_time,
                    'success': True
                })

                # Save successful execution to memory (via shared_data)
                _exec_mem = context.shared_data.get('execution_memory')
                if _exec_mem:
                    _uid = context.shared_data.get('user_id', 'crew_user')
                    _sid = context.shared_data.get('session_id', 'unknown')
                    agent_input = result.get('prompt', '') if isinstance(result, dict) else context.initial_task
                    agent_result = NodeResult(
                        node_id=agent_name,
                        node_name=node.agent.name,
                        task=agent_input,
                        result=output,
                        metadata={
                            'success': True,
                            'mode': 'flow',
                            'user_id': _uid,
                            'session_id': _sid,
                            'result_type': type(output).__name__
                        },
                        execution_time=execution_time
                    )
                    # Vectorize only if analysis enabled
                    _exec_mem.add_result(
                        agent_result,
                        vectorize=True
                    )
                    # Update execution order
                    if agent_name not in _exec_mem.execution_order:
                        _exec_mem.execution_order.append(agent_name)

                    # Persist per-agent result incrementally (FEAT-306) — skip
                    # silently when the helper is used outside a run_flow()
                    # invocation (no crew_execution_id threaded in shared_data).
                    _crew_execution_id = context.shared_data.get('crew_execution_id')
                    if _crew_execution_id:
                        self._schedule_agent_persist(
                            agent_result, execution_id=_crew_execution_id,
                            method='run_flow', user_id=_uid, session_id=_sid,
                        )

        return execution_results

    async def _get_ready_agents(self, context: FlowContext) -> Set[str]:
        """
        Get all agents that are ready to execute based on their dependencies.

        An agent is ready if:
        1. All its dependencies are completed
        2. It hasn't been executed yet
        3. It's not currently executing

        This method is called repeatedly by run_flow() to determine which agents
        can execute in the next wave of parallel execution.
        """
        return {
            agent_name
            for agent_name, node in self.workflow_graph.items()
            if (
                agent_name not in context.completed_tasks
                and agent_name not in context.active_tasks
                and agent_name not in context.errors
                and context.can_execute(agent_name, node.dependencies)
            )
        }

    def _agent_is_configured(self, agent: Union[BasicAgent, AbstractBot]) -> bool:
        """Check if an agent is configured, using a lock to prevent race conditions."""
        status = getattr(agent, "is_configured", False)
        if callable(status):
            with contextlib.suppress(TypeError):
                status = status()
        return bool(status)

    async def _ensure_agent_ready(self, agent: Union[BasicAgent, AbstractBot]) -> None:
        """Ensure the agent is configured before execution.

        Agents require their underlying LLM client to be instantiated before
        they can answer questions. Many examples explicitly call
        ``await agent.configure()`` during setup, but it is easy to forget this
        step when building complex flows programmatically. When configuration
        is skipped the agent's ``_llm`` attribute remains ``None`` (or points to
        an un-instantiated client class), leading to runtime errors such as
        ``'NoneType' object does not support the asynchronous context manager
        protocol`` when ``agent.ask`` is executed.

        To make the crew orchestration more robust we lazily configure agents
        the first time they are used. We guard the configuration with a
        per-agent lock so that concurrent executions of the same agent do not
        race to configure it multiple times.
        """

        if self._agent_is_configured(agent):
            return

        agent_id = id(agent)
        lock = self._agent_locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._agent_locks[agent_id] = lock

        async with lock:
            if not self._agent_is_configured(agent):
                try:
                    self.logger.info(
                        f"Auto-configuring agent '{agent.name}'"
                    )
                    await agent.configure()
                    self.logger.info(
                        f"Agent '{agent.name}' configured successfully"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Failed to configure agent '{agent.name}': {e}",
                        exc_info=True,
                    )
                    raise



    async def _execute_agent(
        self,
        agent: Union[BasicAgent, AbstractBot],
        query: str,
        session_id: str,
        user_id: str,
        index: int,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Any:
        """Execute a single agent with proper rate limiting and error handling.

        This internal method wraps the agent execution with a semaphore for
        rate limiting and handles the different execution methods that agents
        might implement.

        Args:
            agent: The agent to execute.
            query: The prompt/question to send to the agent.
            session_id: Session identifier propagated to the agent.
            user_id: User identifier propagated to the agent.
            index: Positional index of the agent in the sequence (used to
                build a unique sub-session ID).
            model: Optional model override forwarded to the agent.
            max_tokens: Optional token limit forwarded to the agent.
            **kwargs: Arbitrary additional keyword arguments forwarded to the
                agent call (replaces the former ``AgentContext.shared_data``
                spread).

        Returns:
            The raw response from the agent (``AIMessage``, ``AgentResponse``,
            or other type depending on the agent implementation).
        """
        await self._ensure_agent_ready(agent)
        async with self.semaphore:
            if hasattr(agent, 'ask'):
                return await agent.ask(
                    question=query,
                    session_id=f"{session_id}_agent_{index}",
                    user_id=user_id,
                    use_conversation_history=True,
                    model=model,
                    max_tokens=max_tokens,
                    **kwargs
                )
            if hasattr(agent, 'conversation'):
                return await agent.conversation(
                    question=query,
                    session_id=f"{session_id}_agent_{index}",
                    user_id=user_id,
                    use_conversation_history=True,
                    model=model,
                    max_tokens=max_tokens,
                    **kwargs
                )
            if hasattr(agent, 'invoke'):
                return await agent.invoke(
                    question=query,
                    session_id=f"{session_id}_agent_{index}",
                    user_id=user_id,
                    use_conversation_history=False,
                    **kwargs
                )
            else:
                raise ValueError(
                    f"Agent {agent.name} does not support conversation, ask, or invoke methods"
                )

    def _extract_result(self, response: Any) -> str:
        """Extract result string from response."""
        if isinstance(response, (AIMessage, AgentResponse)) or hasattr(
            response, 'content'
        ):
            return response.content
        else:
            return str(response)

    def _build_context_summary(self, context: FlowContext) -> str:
        """Build a human-readable summary of results accumulated so far.

        Reads from ``FlowContext.results`` (keyed by node_id → result string).
        Used by sequential and loop modes when ``pass_full_context=True`` to
        give downstream agents visibility into what prior agents produced.

        Args:
            context: The current execution context for this run/iteration.

        Returns:
            Multi-line string with one ``- <node_id>: <truncated_result>``
            entry per completed node, or an empty string if no results yet.
        """
        summaries = []
        for agent_name, result in context.results.items():
            truncated = self._truncate_text(
                result,
                enabled=self.truncate_context_summary
            )
            summaries.append(f"- {agent_name}: {truncated}")
        return "\n".join(summaries)

    def _truncate_text(self, text: Optional[str], *, enabled: bool = True) -> str:
        """Truncate text using configured length."""
        if text is None or not enabled:
            return text or ""

        if self.truncation_length is None or self.truncation_length <= 0:
            return text

        if len(text) <= self.truncation_length:
            return text

        return f"{text[:self.truncation_length]}..."

    def _build_loop_first_agent_prompt(
        self,
        *,
        initial_task: str,
        iteration_input: str,
        iteration_number: int,
    ) -> str:
        """Compose the prompt for the first agent in each loop iteration."""
        if iteration_number == 1:
            return iteration_input

        return (
            f"Initial task: {initial_task}\n"
            f"This is loop iteration {iteration_number}."
            f"\nPrevious iteration output:\n{iteration_input}"
        )

    def _build_shared_state_summary(self, shared_state: Dict[str, Any]) -> str:
        """Create a human-readable summary from the shared loop state."""
        history = shared_state.get('history', [])
        if not history:
            return "No prior agent outputs."

        lines = []
        for entry in history[-10:]:
            iteration = entry.get('iteration')
            agent_id = entry.get('agent_id')
            output = entry.get('output')
            lines.append(
                f"Iteration {iteration} - {agent_id}: {self._truncate_text(str(output))}"
            )
        return "\n".join(lines)

    async def _evaluate_loop_condition(
        self,
        *,
        condition: str,
        shared_state: Dict[str, Any],
        last_output: Optional[str],
        iteration: int,
        user_id: Optional[str],
        session_id: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> bool:
        """Ask the configured LLM whether the loop condition has been satisfied."""
        if not condition:
            return False

        history_summary = []
        for entry in shared_state.get('history', []):
            iteration_no = entry.get('iteration')
            agent_id = entry.get('agent_id')
            output = entry.get('output')
            history_summary.append(
                f"Iteration {iteration_no} - {agent_id}: {output}"
            )

        history_text = "\n".join(history_summary) or "(no outputs yet)"
        prompt = (
            "You are monitoring an autonomous team of agents running in a loop.\n"
            f"Initial task: {shared_state.get('initial_task')}\n"
            f"Stopping condition: {condition}\n"
            f"Current iteration: {iteration}\n"
            "Shared state history:\n"
            f"{history_text}\n\n"
            f"Most recent output: {last_output}\n\n"
            "Decide if the loop should stop. Respond with a single word:"
            " YES to stop the loop because the condition is met, or NO to"
            " continue running."
        )

        try:
            async with self._llm as client:
                response = await client.ask(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    user_id=user_id,
                    session_id=f"{session_id}_loop_condition",
                    use_conversation_history=False
                )
        except Exception as exc:
            self.logger.error(
                f"Failed to evaluate loop condition with LLM: {exc}",
                exc_info=True
            )
            return False

        decision_text = self._extract_result(response).strip().lower()
        if not decision_text:
            return False

        if decision_text.startswith('yes') or ' stop' in decision_text:
            return True

        return False



    # -------------------------------
    # Execution Methods (run_parallel, sequential, loop, flow)
    # -------------------------------

    async def run_sequential(
        self,
        query: str,
        user_id: str = None,
        session_id: str = None,
        pass_full_context: bool = True,
        generate_summary: bool = True,
        synthesis_prompt: Optional[str] = None,
        agent_sequence: List[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        model: Optional[str] = 'gemini-2.5-pro',
        **kwargs
    ) -> FlowResult:
        """
        Execute agents in sequence (pipeline pattern).

        In sequential execution, agents form a pipeline where each agent processes
        the output of the previous agent. This is like an assembly line where each
        station performs its specific task on the work-in-progress before passing
        it to the next station.

        This mode is useful when:
        - Each agent refines or transforms the previous agent's output
        - You have a clear multi-stage process (e.g., research → summarize → format)
        - Later agents need the complete context of all previous work

        Args:
            query: The initial query/task to start the pipeline
            agent_sequence: Ordered list of agent IDs to execute (None = all agents in order)
            user_id: User identifier for tracking and logging
            session_id: Session identifier for conversation history
            pass_full_context: If True, each agent sees all previous results;
                if False, each agent only sees the immediately previous result
            generate_summary: Whether to generate a summary of all results
            synthesis_prompt: Optional prompt to synthesize all results with LLM
            model: LLM model to use for synthesis (if synthesis_prompt provided)
            max_tokens: Max tokens for synthesis (if synthesis_prompt provided)
            temperature: Temperature for synthesis LLM
            **kwargs: Additional arguments passed to each agent

        Returns:
            Dictionary containing:
                - final_result: The output from the last agent
                - execution_log: Detailed log of each agent's execution
                - agent_results: Dictionary mapping agent_id to its result
                - success: Whether all agents executed successfully
        """
        if not self.agents:
            return FlowResult(
                output='No agents in crew',
                execution_log=[],
                status='failed',
                total_time=0.0,
                metadata={'mode': 'sequential'}
            )

        # Determine agent sequence
        if agent_sequence is None:
            agent_sequence = list(self.agents.keys())

        # Setup session identifiers
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'
        # Crew-level execution id (FEAT-306) — links this run's per-agent
        # writes to the consolidated CrewExecutionDocument.
        execution_id = str(uuid.uuid4())

        # Initialize execution memory
        self.execution_memory = ExecutionMemory(
            original_query=query,
            embedding_model=self.embedding_model if self.enable_analysis else None,
            dimension=getattr(self, 'dimension', 384),
            index_type=getattr(self, 'index_type', 'Flat')
        )
        # Set execution order for sequential mode
        agent_sequence_ids = agent_sequence if agent_sequence is not None else list(self.agents.keys())
        self.execution_memory.execution_order = [
            agent_id for agent_id in agent_sequence_ids
            if agent_id in self.agents
        ]

        # Initialize context to track execution across agents
        current_input = query
        context = FlowContext(
            initial_task=query,
            shared_data={
                **kwargs,
                'execution_memory': self.execution_memory,
            },
        )

        self.execution_log = []
        start_time = asyncio.get_running_loop().time()

        responses: Dict[str, Any] = {}
        results: List[Any] = []
        agent_ids: List[str] = []
        agents_info: List[NodeExecutionInfo] = []
        errors: Dict[str, str] = {}
        success_count = 0
        failure_count = 0

        # Execute agents in sequence
        for i, agent_id in enumerate(agent_sequence):
            if agent_id not in self.agents:
                self.logger.warning(f"Agent '{agent_id}' not found in crew, skipping")
                continue

            agent = self.agents[agent_id]

            # Wire FSM transitions for this node
            node = self.workflow_graph.get(agent_id)
            if node and node.fsm:
                node.fsm.schedule()
                node.fsm.start()

            try:
                agent_start_time = asyncio.get_running_loop().time()

                # Prepare input based on context passing mode
                if i == 0:
                    # First agent gets the initial query
                    agent_input = query
                elif pass_full_context:
                    # Pass full context of all previous agents' work
                    context_summary = self._build_context_summary(context)
                    agent_input = f"""Original query: {query}
Previous processing:
{context_summary}

Current task: {current_input}"""
                else:
                    # Pass only the immediately previous result
                    agent_input = current_input

                # Run pre-action hooks if available
                if node:
                    await node.run_pre_actions(prompt=agent_input)

                # Execute agent — strip framework-internal keys from shared_data
                # (e.g. 'execution_memory') so they never leak into agent calls.
                _agent_kwargs = {
                    k: v for k, v in context.shared_data.items()
                    if k not in _INTERNAL_SHARED_KEYS
                }
                response: AIMessage = await self._execute_agent(
                    agent, agent_input, session_id, user_id, i,
                    model=model, max_tokens=max_tokens,
                    **_agent_kwargs
                )

                result = self._extract_result(response)
                agent_end_time = asyncio.get_running_loop().time()
                execution_time = agent_end_time - agent_start_time

                # Run post-action hooks if available
                if node:
                    await node.run_post_actions(result=response)

                # Log execution details
                log_entry = {
                    'agent_id': agent_id,
                    'agent_name': agent.name,
                    'agent_index': i,
                    'input': self._truncate_text(agent_input),
                    'output': self._truncate_text(result),
                    'full_output': result,
                    'execution_time': execution_time,
                    'success': True
                }
                self.execution_log.append(log_entry)

                # Store result and prepare for next agent
                context.mark_completed(agent_id, result=result, response=response)
                current_input = result
                responses[agent_id] = response
                agents_info.append(
                    build_node_metadata(
                        agent_id,
                        agent,
                        response,
                        result,
                        execution_time,
                        'completed'
                    )
                )
                results.append(result)
                agent_ids.append(agent_id)

                # Save successful execution to memory
                agent_result = NodeResult(
                    node_id=agent_id,
                    node_name=agent.name,
                    task=agent_input,
                    result=result,
                    metadata={
                        'success': True,
                        'mode': 'sequential',
                        'user_id': user_id,
                        'session_id': session_id,
                        'index': i,
                        'result_type': type(result).__name__
                    },
                    execution_time=execution_time
                )
                # Vectorize only if analysis enabled
                self.execution_memory.add_result(
                    agent_result,
                    vectorize=True
                )
                self._schedule_agent_persist(
                    agent_result, execution_id=execution_id, method='run_sequential',
                    user_id=user_id, session_id=session_id,
                )

                # FSM: mark node as completed
                if node and node.fsm:
                    node.fsm.succeed()

                success_count += 1

            except Exception as e:
                error_msg = f"Error executing agent {agent_id}: {str(e)}"
                self.logger.error(error_msg, exc_info=True)

                # FSM: mark node as failed
                if node and node.fsm:
                    node.fsm.fail()

                log_entry = {
                    'agent_id': agent_id,
                    'agent_name': agent.name,
                    'agent_index': i,
                    'input': current_input,
                    'output': error_msg,
                    'execution_time': 0,
                    'success': False,
                    'error': str(e)
                }
                self.execution_log.append(log_entry)
                current_input = error_msg
                errors[agent_id] = str(e)
                agents_info.append(
                    build_node_metadata(
                        agent_id,
                        agent,
                        None,
                        error_msg,
                        0.0,
                        'failed',
                        str(e)
                    )
                )
                results.append(error_msg)
                agent_ids.append(agent_id)

                # Save failed execution to memory
                agent_result = NodeResult(
                    node_id=agent_id,
                    node_name=agent.name,
                    task=current_input,
                    result=error_msg,
                    metadata={
                        'success': False,
                        'error': str(e),
                        'mode': 'sequential',
                        'user_id': user_id,
                        'session_id': session_id,
                        'index': i
                    },
                    execution_time=0.0
                )
                self.execution_memory.add_result(
                    agent_result,
                    vectorize=False
                )
                self._schedule_agent_persist(
                    agent_result, execution_id=execution_id, method='run_sequential',
                    user_id=user_id, session_id=session_id,
                )

                failure_count += 1

        end_time = asyncio.get_running_loop().time()
        total_time = end_time - start_time
        status = determine_run_status(success_count, failure_count)

        result = FlowResult(
            output=current_input,
            responses=responses,
            nodes=agents_info,
            errors=errors,
            execution_log=self.execution_log,
            total_time=total_time,
            status=status,
            metadata={'mode': 'sequential', 'agent_sequence': agent_sequence}
        )
        result.metadata['execution_id'] = execution_id

        if generate_summary and not synthesis_prompt:
            synthesis_prompt = SYNTHESIS_PROMPT

        if generate_summary:
            summary = await self._synthesize_results(
                crew_result=result,
                synthesis_prompt=synthesis_prompt,
                llm=self._llm,
                user_id=user_id,
                session_id=session_id,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs
            )
            if summary is not None:
                result.summary = summary
                result.metadata.update(
                    {
                        'synthesized': True,
                        'synthesis_prompt': synthesis_prompt,
                    }
                )

        # Fire lifecycle hooks (FEAT-157)
        await self._fire_hooks(result)

        # Track last run's result + execution id for build_execution_document() (FEAT-306)
        self.last_crew_result = result
        self._last_execution_id = execution_id
        self._last_user_id = user_id
        self._last_session_id = session_id

        # Save consolidated execution document (fire-and-forget, tracked for lifecycle cleanup)
        document = CrewExecutionDocument.from_memory(
            execution_id=execution_id,
            crew_name=self.name,
            method='run_sequential',
            memory=self.execution_memory,
            result=result,
            user_id=user_id,
            session_id=session_id,
        )
        _persist_task = asyncio.get_running_loop().create_task(
            self._save_result(
                document,
                'run_sequential',
                execution_id=execution_id,
                user_id=user_id,
                session_id=session_id,
                prompt=query,
                tenant=getattr(self, '_tenant', 'global'),
            )
        )
        self._persist_tasks.add(_persist_task)
        _persist_task.add_done_callback(self._persist_tasks.discard)

        return result

    async def run_loop(
        self,
        initial_task: str,
        condition: str,
        max_iterations: int = 2,
        user_id: str = None,
        session_id: str = None,
        agent_sequence: Optional[List[str]] = None,
        pass_full_context: bool = True,
        generate_summary: bool = True,
        synthesis_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        **kwargs
    ) -> FlowResult:
        """Execute agents iteratively until the stopping condition is met.

        Loop execution reuses the final output from each iteration as the input
        for the next iteration. After every iteration the crew uses the
        configured LLM to decide if the provided condition has been satisfied.

        Args:
            initial_task: The initial task/question that triggers the loop.
            condition: Natural language description of the success criteria.
            agent_sequence: Ordered list of agent IDs for each iteration
                (defaults to all registered agents in insertion order).
            max_iterations: Safety limit on number of iterations to run.
            user_id: Optional identifier propagated to agents and LLM.
            session_id: Optional identifier propagated to agents and LLM.
            pass_full_context: If True, downstream agents receive summaries of
                previous outputs from the current iteration.
            generate_summary: If True, downstream agents receive summaries of
                previous outputs from the current iteration.
            synthesis_prompt: Optional prompt to synthesize final results.
            model: Optional model override forwarded to each agent call.
            max_tokens: Token limit when synthesizing or evaluating condition.
            temperature: Temperature used for synthesis or condition evaluation.
            **kwargs: Additional parameters forwarded to agent executions.

        Returns:
            CrewResult describing the entire loop execution history.

        Raises:
            ValueError: If no agents are registered or no LLM is configured to
                evaluate the stopping condition.
        """
        if not self.agents:
            return FlowResult(
                output='No agents in crew',
                execution_log=[],
                status='failed',
                total_time=0.0,
                metadata={'mode': 'loop', 'iterations': 0, 'condition_met': False}
            )

        if not self._llm:
            # Let's create an LLM session if none is provided:
            self._llm = GoogleGenAIClient(
                model='gemini-2.5-pro',
                max_tokens=8192
            )

        agent_sequence = agent_sequence or list(self.agents.keys())
        if not agent_sequence:
            return FlowResult(
                output='No agents configured for loop execution',
                execution_log=[],
                status='failed',
                total_time=0.0,
                metadata={'mode': 'loop', 'iterations': 0, 'condition_met': False}
            )

        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'
        # Crew-level execution id (FEAT-306) — named `crew_execution_id` here
        # to avoid shadowing the per-iteration `execution_id` local variable
        # used below (f"{agent_id}#iteration{n}", an ExecutionMemory node key).
        crew_execution_id = str(uuid.uuid4())

        # Initialize execution memory
        self.execution_memory = ExecutionMemory(
            original_query=initial_task,
            embedding_model=self.embedding_model if self.enable_analysis else None,
            dimension=getattr(self, 'dimension', 384),
            index_type=getattr(self, 'index_type', 'Flat')
        )
        # Set execution order for loop mode (agents in sequence, repeated per iteration)
        self.execution_memory.execution_order = [
            agent_id for agent_id in agent_sequence
            if agent_id in self.agents
        ]

        self.execution_log = []
        overall_start = asyncio.get_running_loop().time()

        shared_state: Dict[str, Any] = {
            'initial_task': initial_task,
            'history': [],
            'iteration_outputs': [],
            'last_output': initial_task,
        }

        responses: Dict[str, Any] = {}
        results: List[Any] = []
        agent_ids: List[str] = []
        agents_info: List[NodeExecutionInfo] = []
        errors: Dict[str, str] = {}
        success_count = 0
        failure_count = 0

        current_input = initial_task
        condition_met = False

        iterations_run = 0

        for iteration_index in range(max_iterations):
            self.logger.notice(
                f'Starting iteration {iteration_index + 1}/{max_iterations}'
            )
            iterations_run = iteration_index + 1

            # Fresh FSM per iteration (completed is a final state, so
            # we cannot reuse the same FSM across iterations)
            for agent_id in agent_sequence:
                node = self.workflow_graph.get(agent_id)
                if node:
                    node.fsm = AgentTaskMachine(agent_name=node.agent.name)

            context = FlowContext(
                initial_task=initial_task,
                shared_data={
                    **kwargs,
                    'shared_state': shared_state,
                    'execution_memory': self.execution_memory,
                },
            )

            iteration_success = True
            for agent_position, agent_id in enumerate(agent_sequence):
                if agent_id not in self.agents:
                    self.logger.warning(
                        f"Agent '{agent_id}' not found in crew during loop execution, skipping"
                    )
                    iteration_success = False
                    execution_id = f"{agent_id}#iteration{iterations_run}"
                    error_message = 'Agent not found'
                    self.execution_log.append({
                        'agent_id': agent_id,
                        'execution_id': execution_id,
                        'iteration': iterations_run,
                        'agent_name': agent_id,
                        'agent_index': agent_position,
                        'input': self._truncate_text(current_input),
                        'output': error_message,
                        'execution_time': 0.0,
                        'success': False,
                        'error': error_message,
                    })
                    agents_info.append(
                        build_node_metadata(
                            execution_id,
                            None,
                            None,
                            None,
                            0.0,
                            'failed',
                            error_message,
                        )
                    )
                    results.append(error_message)
                    agent_ids.append(execution_id)
                    errors[execution_id] = error_message

                    # Save failed execution to memory
                    agent_result = NodeResult(
                        node_id=execution_id,
                        node_name=agent_id,
                        task=current_input,
                        result=error_message,
                        metadata={
                            'success': False,
                            'error': error_message,
                            'mode': 'loop',
                            'iteration': iterations_run,
                            'user_id': user_id,
                            'session_id': session_id,
                            'agent_position': agent_position
                        },
                        execution_time=0.0
                    )
                    self.execution_memory.add_result(
                        agent_result,
                        vectorize=False
                    )
                    self._schedule_agent_persist(
                        agent_result, execution_id=crew_execution_id, method='run_loop',
                        user_id=user_id, session_id=session_id,
                    )

                    failure_count += 1
                    continue

                agent = self.agents[agent_id]
                await self._ensure_agent_ready(agent)

                # Wire FSM: schedule + start before execution
                node = self.workflow_graph.get(agent_id)
                if node and node.fsm:
                    node.fsm.schedule()
                    node.fsm.start()

                if agent_position == 0:
                    agent_input = self._build_loop_first_agent_prompt(
                        initial_task=initial_task,
                        iteration_input=current_input,
                        iteration_number=iterations_run,
                    )
                elif pass_full_context:
                    context_summary = self._build_context_summary(context)
                    shared_summary = self._build_shared_state_summary(shared_state)
                    agent_input = (
                        f"Original task: {initial_task}\n"
                        f"Loop iteration: {iterations_run}\n"
                        f"Shared state so far:\n{shared_summary}\n\n"
                        f"Previous results this iteration:\n{context_summary}\n\n"
                        f"Continue the work based on the latest result: {current_input}"
                    ).strip()
                else:
                    agent_input = current_input

                try:
                    agent_start = asyncio.get_running_loop().time()

                    # Run pre-action hooks if available
                    if node:
                        await node.run_pre_actions(prompt=agent_input)

                    # Strip framework-internal keys from shared_data
                    _agent_kwargs = {
                        k: v for k, v in context.shared_data.items()
                        if k not in _INTERNAL_SHARED_KEYS
                    }
                    response = await self._execute_agent(
                        agent,
                        agent_input,
                        session_id,
                        user_id,
                        agent_position,
                        model=model,
                        max_tokens=max_tokens,
                        **_agent_kwargs
                    )

                    result = self._extract_result(response)
                    agent_end = asyncio.get_running_loop().time()
                    execution_time = agent_end - agent_start

                    # Run post-action hooks if available
                    if node:
                        await node.run_post_actions(result=response)

                    execution_id = f"{agent_id}#iteration{iterations_run}"
                    log_entry = {
                        'agent_id': agent_id,
                        'execution_id': execution_id,
                        'iteration': iterations_run,
                        'agent_name': agent.name,
                        'agent_index': agent_position,
                        'input': self._truncate_text(agent_input),
                        'output': self._truncate_text(result),
                        'full_output': result,
                        'execution_time': execution_time,
                        'success': True,
                    }
                    self.execution_log.append(log_entry)

                    context.mark_completed(agent_id, result=result, response=response)
                    current_input = result
                    responses[execution_id] = response
                    agents_info.append(
                        build_node_metadata(
                            execution_id,
                            agent,
                            response,
                            result,
                            execution_time,
                            'completed'
                        )
                    )
                    results.append(result)
                    agent_ids.append(execution_id)
                    shared_state['history'].append({
                        'iteration': iterations_run,
                        'agent_id': agent_id,
                        'output': result,
                    })

                    # Save successful execution to memory
                    agent_result = NodeResult(
                        node_id=execution_id,
                        node_name=agent.name,
                        task=agent_input,
                        result=result,
                        metadata={
                            'success': True,
                            'mode': 'loop',
                            'iteration': iterations_run,
                            'user_id': user_id,
                            'session_id': session_id,
                            'agent_position': agent_position,
                            'result_type': type(result).__name__
                        },
                        execution_time=execution_time
                    )
                    # Vectorize only if analysis enabled
                    self.execution_memory.add_result(
                        agent_result,
                        vectorize=True
                    )
                    self._schedule_agent_persist(
                        agent_result, execution_id=crew_execution_id, method='run_loop',
                        user_id=user_id, session_id=session_id,
                    )

                    success_count += 1
                    # Transition FSM to completed
                    if node and node.fsm and str(node.fsm.current_state.id) == "running":
                        node.fsm.succeed()
                except Exception as exc:
                    execution_id = f"{agent_id}#iteration{iterations_run}"
                    # Transition FSM to failed
                    if node and node.fsm and str(node.fsm.current_state.id) != "failed":
                        node.fsm.fail()
                    error_msg = f"Error executing agent {agent_id}: {exc}"
                    self.logger.error(error_msg, exc_info=True)
                    self.execution_log.append({
                        'agent_id': agent_id,
                        'execution_id': execution_id,
                        'iteration': iterations_run,
                        'agent_name': agent.name,
                        'agent_index': agent_position,
                        'input': self._truncate_text(agent_input),
                        'output': error_msg,
                        'execution_time': 0.0,
                        'success': False,
                        'error': str(exc)
                    })
                    agents_info.append(
                        build_node_metadata(
                            execution_id,
                            agent,
                            None,
                            None,
                            0.0,
                            'failed',
                            str(exc)
                        )
                    )
                    results.append(error_msg)
                    agent_ids.append(execution_id)
                    errors[execution_id] = str(exc)

                    # Save failed execution to memory
                    agent_result = NodeResult(
                        node_id=execution_id,
                        node_name=agent.name,
                        task=agent_input,
                        result=error_msg,
                        metadata={
                            'success': False,
                            'error': str(exc),
                            'mode': 'loop',
                            'iteration': iterations_run,
                            'user_id': user_id,
                            'session_id': session_id,
                            'agent_position': agent_position
                        },
                        execution_time=0.0
                    )
                    self.execution_memory.add_result(
                        agent_result,
                        vectorize=False
                    )
                    self._schedule_agent_persist(
                        agent_result, execution_id=crew_execution_id, method='run_loop',
                        user_id=user_id, session_id=session_id,
                    )

                    failure_count += 1
                    iteration_success = False
                    current_input = error_msg

            shared_state['last_output'] = current_input
            shared_state['iteration_outputs'].append(current_input)
            if condition:
                condition_met = await self._evaluate_loop_condition(
                    condition=condition,
                    shared_state=shared_state,
                    last_output=current_input,
                    iteration=iterations_run,
                    user_id=user_id,
                    session_id=session_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            else:
                condition_met = False

            if condition_met:
                break

            if not iteration_success:
                self.logger.debug(
                    f"Loop iteration {iterations_run} completed with errors; continuing until condition is met or max iterations reached"
                )

            current_input = shared_state['last_output']

        overall_end = asyncio.get_running_loop().time()

        last_output = shared_state['last_output'] if shared_state['iteration_outputs'] else initial_task
        status = determine_run_status(success_count, failure_count)

        result = FlowResult(
            output=last_output,
            responses=responses,
            nodes=agents_info,
            errors=errors,
            execution_log=self.execution_log,
            total_time=overall_end - overall_start,
            status=status,
            metadata={
                'mode': 'loop',
                'iterations': iterations_run,
                'max_iterations': max_iterations,
                'condition': condition,
                'condition_met': condition_met,
                'shared_state': shared_state,
            }
        )
        result.metadata['execution_id'] = crew_execution_id

        if generate_summary and not synthesis_prompt:
            synthesis_prompt = SYNTHESIS_PROMPT

        if generate_summary:
            summary = await self._synthesize_results(
                crew_result=result,
                synthesis_prompt=synthesis_prompt,
                llm=self._llm,
                user_id=user_id,
                session_id=session_id,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs
            )
            if summary is not None:
                result.summary = summary
                result.metadata.update(
                    {
                        'synthesized': True,
                        'synthesis_prompt': synthesis_prompt,
                    }
                )

        # Fire lifecycle hooks (FEAT-157)
        await self._fire_hooks(result)

        # Track last run's result + execution id for build_execution_document() (FEAT-306)
        self.last_crew_result = result
        self._last_execution_id = crew_execution_id
        self._last_user_id = user_id
        self._last_session_id = session_id

        # Save consolidated execution document (fire-and-forget, tracked for lifecycle cleanup)
        document = CrewExecutionDocument.from_memory(
            execution_id=crew_execution_id,
            crew_name=self.name,
            method='run_loop',
            memory=self.execution_memory,
            result=result,
            user_id=user_id,
            session_id=session_id,
        )
        _persist_task = asyncio.get_running_loop().create_task(
            self._save_result(
                document,
                'run_loop',
                execution_id=crew_execution_id,
                user_id=user_id,
                session_id=session_id,
                prompt=initial_task,
                tenant=getattr(self, '_tenant', 'global'),
            )
        )
        self._persist_tasks.add(_persist_task)
        _persist_task.add_done_callback(self._persist_tasks.discard)

        return result

    async def run_parallel(
        self,
        tasks: List[Dict[str, Any]],
        all_results: Optional[bool] = True,
        user_id: str = None,
        session_id: str = None,
        generate_summary: bool = True,
        synthesis_prompt: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        **kwargs
    ) -> FlowResult:
        """
        Execute multiple agents in parallel using asyncio.gather().

        In parallel execution, all agents run simultaneously on their respective tasks.
        This is like having multiple independent workers each handling their own job,
        all working at the same time without waiting for each other.

        This mode is useful when:
        - You have multiple independent analyses to perform
        - Agents don't depend on each other's results
        - You want to maximize throughput and minimize total execution time
        - Each agent is working on a different aspect of the same problem

        Args:
            tasks: List of task dictionaries, each containing:
                - 'agent_id': ID of the agent to execute
                - 'query': The query/task for that agent
            user_id: User identifier for tracking
            session_id: Session identifier
            synthesis_prompt: Optional prompt to synthesize all results with LLM
            max_tokens: Max tokens for synthesis (if synthesis_prompt provided)
            temperature: Temperature for synthesis LLM
            all_results: Whether to return all results or just the final result
            generate_summary: Whether to generate a summary of all results
            **kwargs: Additional arguments passed to all agents

        Returns:
            CrewResult: Standardized execution payload containing outputs,
            metadata, and execution logs.
        """
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'
        # Crew-level execution id (FEAT-306).
        execution_id = str(uuid.uuid4())
        original_query = tasks[0]['query'] if tasks else ""

        # initialize execution log
        self.execution_memory = ExecutionMemory(
            original_query=original_query,
            embedding_model=self.embedding_model if self.enable_analysis else None,
            dimension=getattr(self, 'dimension', 384),
            index_type=getattr(self, 'index_type', 'Flat')
        )
        # Set execution order for parallel mode (all agents at same level)
        self.execution_memory.execution_order = [
            task.get('agent_id') for task in tasks
            if task.get('agent_id') in self.agents
        ]

        context = FlowContext(
            initial_task=original_query,
            shared_data={
                **kwargs,
                'execution_memory': self.execution_memory,
            },
        )

        self.execution_log = []
        responses: Dict[str, Any] = {}
        results_payload: List[Any] = []
        agent_ids: List[str] = []
        agents_info: List[NodeExecutionInfo] = []
        errors: Dict[str, str] = {}
        success_count = 0
        failure_count = 0
        last_output = None

        # Create async tasks for parallel execution
        async_tasks = []
        task_metadata = []

        for i, task in enumerate(tasks):
            agent_id = task.get('agent_id')
            query = task.get('query')

            if agent_id not in self.agents:
                self.logger.warning(f"Agent '{agent_id}' not found, skipping")
                continue

            agent = self.agents[agent_id]
            node = self.workflow_graph.get(agent_id)
            task_metadata.append({
                'agent_id': agent_id,
                'agent_name': agent.name,
                'query': query,
                'index': i
            })

            # Build per-task agent kwargs: strip internal bookkeeping keys so
            # ExecutionMemory / shared_state never reach agent.ask(**kwargs).
            _agent_kwargs = {
                k: v for k, v in context.shared_data.items()
                if k not in _INTERNAL_SHARED_KEYS
            }

            async def _run_with_hooks(
                _agent=agent, _query=query, _idx=i, _node=node,
                _kwargs=_agent_kwargs,
            ):
                """Wrap _execute_agent with pre/post action hooks."""
                if _node:
                    await _node.run_pre_actions(prompt=_query)
                resp = await self._execute_agent(
                    _agent, _query, session_id, user_id, _idx,
                    max_tokens=max_tokens,
                    **_kwargs
                )
                if _node:
                    await _node.run_post_actions(result=resp)
                return resp

            async_tasks.append(_run_with_hooks())

        if not async_tasks:
            return FlowResult(
                output=None,
                status='failed',
                errors={'__crew__': 'No valid tasks to execute'},
                metadata={'mode': 'parallel'}
            )

        # Wire FSM transitions: schedule + start all nodes before gather
        for meta in task_metadata:
            node = self.workflow_graph.get(meta['agent_id'])
            if node and node.fsm:
                node.fsm.schedule()
                node.fsm.start()

        # Execute all tasks in parallel using asyncio.gather()
        # This is the key to parallel execution - all coroutines run concurrently
        start_time = asyncio.get_running_loop().time()
        results = await asyncio.gather(*async_tasks, return_exceptions=True)
        end_time = asyncio.get_running_loop().time()

        # Process results from all parallel executions
        parallel_results = {}

        for i, (result, metadata) in enumerate(zip(results, task_metadata)):
            agent_id = metadata['agent_id']
            agent_name = metadata['agent_name']
            agent_ids.append(agent_id)
            _query = metadata['query']
            execution_time = end_time - start_time  # Total parallel time

            if isinstance(result, Exception):
                # Handle exceptions from failed agents
                error_msg = f"Error: {str(result)}"
                parallel_results[agent_id] = error_msg
                errors[agent_id] = str(result)
                # Transition FSM to failed (guard against double-transition)
                node = self.workflow_graph.get(agent_id)
                if node and node.fsm and str(node.fsm.current_state.id) != "failed":
                    node.fsm.fail()
                # Save failed execution to memory
                agent_result = NodeResult(
                    node_id=agent_id,
                    node_name=agent_name,
                    task=_query,
                    result=error_msg,
                    metadata={
                        'success': False,
                        'error': str(result),
                        'mode': 'parallel',
                        'user_id': user_id,
                        'session_id': session_id
                    },
                    execution_time=0.0
                )
                self.execution_memory.add_result(
                    agent_result,
                    vectorize=False
                )
                self._schedule_agent_persist(
                    agent_result, execution_id=execution_id, method='run_parallel',
                    user_id=user_id, session_id=session_id,
                )
                log_entry = {
                    'agent_id': agent_id,
                    'agent_name': agent_name,
                    'agent_index': i,
                    'input': _query,
                    'output': error_msg,
                    'execution_time': 0,
                    'success': False,
                    'error': str(result)
                }
                agents_info.append(
                    build_node_metadata(
                        agent_id,
                        self.agents.get(agent_id),
                        None,
                        error_msg,
                        0.0,
                        'failed',
                        str(result)
                    )
                )
                results_payload.append(error_msg)

                responses[agent_id] = None
                failure_count += 1
            else:
                # Handle successful agent execution
                extracted_result = self._extract_result(result)
                parallel_results[agent_id] = extracted_result
                context.mark_completed(agent_id, result=extracted_result, response=result)
                _query = metadata['query']

                # Save successful execution to memory
                agent_result = NodeResult(
                    node_id=agent_id,
                    node_name=agent_name,
                    task=_query,
                    result=extracted_result,
                    metadata={
                        'success': True,
                        'mode': 'parallel',
                        'user_id': user_id,
                        'session_id': session_id,
                        'index': i,
                        'result_type': type(extracted_result).__name__
                    },
                    execution_time=execution_time
                )
                # Vectorize only if analysis enabled (handled internally by ExecutionMemory)
                self.execution_memory.add_result(
                    agent_result,
                    vectorize=True
                )
                self._schedule_agent_persist(
                    agent_result, execution_id=execution_id, method='run_parallel',
                    user_id=user_id, session_id=session_id,
                )

                log_entry = {
                    'agent_id': agent_id,
                    'agent_name': agent_name,
                    'agent_index': i,
                    'input': _query,
                    'output': self._truncate_text(extracted_result),
                    'full_output': extracted_result,
                    'execution_time': end_time - start_time,  # Total parallel time
                    'success': True
                }
                agents_info.append(
                    build_node_metadata(
                        agent_id,
                        self.agents.get(agent_id),
                        result,
                        extracted_result,
                        end_time - start_time,
                        'completed'
                    )
                )
                results_payload.append(extracted_result)
                responses[agent_id] = result
                last_output = extracted_result
                success_count += 1
                # Transition FSM to completed
                node = self.workflow_graph.get(agent_id)
                if node and node.fsm:
                    node.fsm.succeed()

            self.execution_log.append(log_entry)
        status = determine_run_status(success_count, failure_count)

        output = results_payload if all_results else last_output

        result = FlowResult(
            output=output,
            responses=responses,
            nodes=agents_info,
            errors=errors,
            execution_log=self.execution_log,
            total_time=end_time - start_time,
            status=status,
            metadata={
                'mode': 'parallel',
                'task_count': len(agent_ids),
                'requested_tasks': len(tasks),
            }
        )
        result.metadata['execution_id'] = execution_id
        if generate_summary and not synthesis_prompt:
            synthesis_prompt = SYNTHESIS_PROMPT
        if generate_summary:
            summary = await self._synthesize_results(
                crew_result=result,
                synthesis_prompt=synthesis_prompt,
                llm=self._llm,
                user_id=user_id,
                session_id=session_id,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs
            )
            if summary is not None:
                result.summary = summary
                result.metadata.update(
                    {
                        'synthesized': True,
                        'synthesis_prompt': synthesis_prompt,
                    }
                )

        # Fire lifecycle hooks (FEAT-157)
        await self._fire_hooks(result)

        # Track last run's result + execution id for build_execution_document() (FEAT-306)
        self.last_crew_result = result
        self._last_execution_id = execution_id
        self._last_user_id = user_id
        self._last_session_id = session_id

        # Save consolidated execution document (fire-and-forget, tracked for lifecycle cleanup)
        document = CrewExecutionDocument.from_memory(
            execution_id=execution_id,
            crew_name=self.name,
            method='run_parallel',
            memory=self.execution_memory,
            result=result,
            user_id=user_id,
            session_id=session_id,
        )
        _persist_task = asyncio.get_running_loop().create_task(
            self._save_result(
                document,
                'run_parallel',
                execution_id=execution_id,
                user_id=user_id,
                session_id=session_id,
                prompt=original_query,
                tenant=getattr(self, '_tenant', 'global'),
            )
        )
        self._persist_tasks.add(_persist_task)
        _persist_task.add_done_callback(self._persist_tasks.discard)

        return result

    async def run_flow(
        self,
        initial_task: str,
        max_iterations: int = 100,
        generate_summary: bool = True,
        synthesis_prompt: Optional[str] = None,
        user_id: str = None,
        session_id: str = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        on_agent_complete: Optional[Callable] = None,
        **kwargs
    ) -> FlowResult:
        """
        Execute the workflow using the defined task flows (DAG-based execution).

        Flow-based execution is the most sophisticated mode. It executes agents based
        on a Directed Acyclic Graph (DAG) of dependencies, automatically parallelizing
        independent agents while respecting dependencies.

        Think of this like a project management system where:
        - Some tasks can start immediately (no dependencies)
        - Some tasks must wait for specific other tasks to complete (dependencies)
        - When multiple tasks can run, they execute in parallel (optimization)
        - The workflow completes when all final tasks are done

        This mode is useful when:
        - You have complex workflows with both sequential and parallel elements
        - Different agents depend on specific other agents' outputs
        - You want automatic parallelization wherever possible
        - Your workflow follows patterns like:
          * Writer → [Editor1, Editor2] → Final Reviewer
          * [Research1, Research2, Research3] → Synthesizer
          * Complex multi-stage pipelines with branching and merging

        The workflow execution follows these steps:
        1. Start with agents that have no dependencies (initial agents)
        2. Execute ready agents in parallel when possible
        3. Wait for dependencies before executing dependent agents
        4. Continue until all final agents complete
        5. Handle errors and detect stuck workflows

        Args:
            initial_task: The initial task/prompt to start the workflow
            max_iterations: Maximum number of execution rounds (safety limit to prevent infinite loops)
            generate_summary: If True, downstream agents receive summaries of
                previous outputs from the current iteration.
            synthesis_prompt: Optional prompt to synthesize all results with LLM
            user_id: User identifier (used for synthesis)
            session_id: Session identifier (used for synthesis)
            max_tokens: Max tokens for synthesis
            temperature: Temperature for synthesis LLM
            **kwargs: Additional keyword arguments to pass to the LLM.
            on_agent_complete: Optional callback function called when an agent completes.
                Signature: async def callback(agent_name: str, result: Any, context: FlowContext)

        Returns:
            CrewResult: Standardized execution payload containing outputs,
            metadata, and execution logs.

        Raises:
            ValueError: If no initial agent is found (no workflow defined)
            RuntimeError: If workflow gets stuck or exceeds max_iterations
        """
        # Setup session identifiers
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'
        # Crew-level execution id (FEAT-306).
        execution_id = str(uuid.uuid4())

        # Initialize execution memory
        self.execution_memory = ExecutionMemory(
            original_query=initial_task,
            embedding_model=self.embedding_model if self.enable_analysis else None,
            dimension=getattr(self, 'dimension', 384),
            index_type=getattr(self, 'index_type', 'Flat')
        )
        # Set execution order for flow mode (will be updated as agents complete)
        self.execution_memory.execution_order = []

        # Initialize execution context to track the workflow state.
        # Framework metadata (execution_memory, user_id, session_id) lives in
        # shared_data — consistent with run_sequential / run_loop / run_parallel.
        # 'crew_execution_id' (FEAT-306) threads the crew-level execution id
        # into _execute_parallel_agents() for incremental per-agent persistence.
        context = FlowContext(
            initial_task=initial_task,
            shared_data={
                'execution_memory': self.execution_memory,
                'user_id': user_id,
                'session_id': session_id,
                'crew_execution_id': execution_id,
            },
        )

        self.execution_log = []
        start_time = asyncio.get_running_loop().time()

        # Validate workflow before starting
        if not self.initial_agent:
            raise ValueError(
                "No initial agent found. Define task flows first using task_flow()."
            )

        iteration = 0
        while iteration < max_iterations:
            # Find agents ready to execute (all dependencies satisfied)
            ready_agents = await self._get_ready_agents(context)

            if not ready_agents:
                # Check if we're done - all final agents have completed
                if self.final_agents.issubset(context.completed_tasks):
                    break

                # Check if we're stuck - no ready agents but also no active agents
                if not context.active_tasks:
                    # If there are errors, the workflow is partial/failed —
                    # downstream agents are blocked by failed dependencies.
                    if context.errors:
                        self.logger.warning(
                            "Workflow stopped: failed agents %s block downstream. "
                            "Completed: %s, Expected final: %s",
                            set(context.errors.keys()),
                            context.completed_tasks,
                            self.final_agents,
                        )
                        break
                    raise RuntimeError(
                        f"Workflow is stuck. Completed: {context.completed_tasks}, "
                        f"Expected final: {self.final_agents}. "
                        f"This usually indicates a circular dependency or missing agents."
                    )

                # Wait for active tasks to complete
                await asyncio.sleep(0.1)
                continue

            # Execute all ready agents in parallel.
            # Results are tracked in context; the return dict is not needed.
            await self._execute_parallel_agents(
                ready_agents, context, on_agent_complete=on_agent_complete
            )

            iteration += 1

        if iteration >= max_iterations:
            raise RuntimeError(
                f"Workflow exceeded max iterations ({max_iterations}). "
                f"Completed: {context.completed_tasks}, "
                f"Expected: {self.final_agents}"
            )

        end_time = asyncio.get_running_loop().time()
        error_messages: Dict[str, str] = {
            agent: str(err)
            for agent, err in context.errors.items()
        }
        completion_order = context.completion_order or list(context.completed_tasks)

        agents_info: List[NodeExecutionInfo] = []
        for agent_name in completion_order:
            metadata = context.agent_metadata.get(agent_name)
            if metadata:
                agents_info.append(metadata)

        success_count = sum(
            info.status == 'completed' for info in agents_info
        )
        failure_count = sum(info.status == 'failed' for info in agents_info)

        for agent_name, error in error_messages.items():
            if agent_name not in completion_order:
                node = self.workflow_graph.get(agent_name)
                agent_obj = node.agent if node else None
                metadata = build_node_metadata(
                    agent_name,
                    agent_obj,
                    context.responses.get(agent_name),
                    context.results.get(agent_name),
                    0.0,
                    'failed',
                    error
                )
                agents_info.append(metadata)
                failure_count += 1

        last_output = None
        if completion_order:
            last_agent = completion_order[-1]
            last_output = context.results.get(last_agent)

        status = determine_run_status(success_count, failure_count)

        result = FlowResult(
            output=last_output,
            responses=context.responses,
            nodes=agents_info,
            errors=error_messages,
            execution_log=self.execution_log,
            total_time=end_time - start_time,
            status=status,
            metadata={'mode': 'flow', 'iterations': iteration}
        )
        result.metadata['execution_id'] = execution_id
        if generate_summary and not synthesis_prompt:
            synthesis_prompt = SYNTHESIS_PROMPT
        if generate_summary:
            summary = await self._synthesize_results(
                crew_result=result,
                synthesis_prompt=synthesis_prompt,
                llm=self._llm,
                user_id=user_id,
                session_id=session_id,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs
            )
            if summary is not None:
                result.summary = summary
                result.metadata.update(
                    {
                        'synthesized': True,
                        'synthesis_prompt': synthesis_prompt,
                    }
                )

        # Fire lifecycle hooks (FEAT-157)
        await self._fire_hooks(result)

        # Track last run's result + execution id for build_execution_document() (FEAT-306)
        self.last_crew_result = result
        self._last_execution_id = execution_id
        self._last_user_id = user_id
        self._last_session_id = session_id

        # Save consolidated execution document (fire-and-forget, tracked for lifecycle cleanup)
        document = CrewExecutionDocument.from_memory(
            execution_id=execution_id,
            crew_name=self.name,
            method='run_flow',
            memory=self.execution_memory,
            result=result,
            user_id=user_id,
            session_id=session_id,
        )
        _persist_task = asyncio.get_running_loop().create_task(
            self._save_result(
                document,
                'run_flow',
                execution_id=execution_id,
                user_id=user_id,
                session_id=session_id,
                prompt=initial_task,
                tenant=getattr(self, '_tenant', 'global'),
            )
        )
        self._persist_tasks.add(_persist_task)
        _persist_task.add_done_callback(self._persist_tasks.discard)

        return result

    def visualize_workflow(self) -> str:
        """
        Generate a text representation of the workflow graph.

        This is useful for debugging and understanding the structure of your
        workflow before executing it. It shows each agent, what it depends on,
        and what depends on it.

        Could be extended to use graphviz for visual diagrams.
        """
        lines = ["Workflow Graph:", "=" * 50]

        for agent_name, node in self.workflow_graph.items():
            deps = f"depends on: {node.dependencies}" if node.dependencies else "initial"
            successors = f"→ {node.successors}" if node.successors else "(final)"
            lines.append(f"  {agent_name}: {deps} {successors}")

        return "\n".join(lines)

    async def validate_workflow(self) -> bool:
        """
        Validate the workflow for common issues.

        This method checks for:
        - Circular dependencies (agent A depends on B, B depends on A)
        - Disconnected agents (agents not reachable from initial agents)

        It's recommended to call this before executing run_flow() to catch
        configuration errors early.

        Raises:
            ValueError: If circular dependency is detected

        Returns:
            True if workflow is valid
        """
        def has_cycle(start: str, visited: Set[str], rec_stack: Set[str]) -> bool:
            """
            Detect cycles using depth-first search with recursion stack.

            This is a classic graph algorithm for detecting cycles in directed graphs.
            We track both visited nodes (to avoid redundant work) and the current
            recursion stack (to detect back edges that indicate cycles).
            """
            visited.add(start)
            rec_stack.add(start)

            node = self.workflow_graph[start]
            for successor in node.successors:
                if successor not in visited:
                    if has_cycle(successor, visited, rec_stack):
                        return True
                elif successor in rec_stack:
                    # Found a back edge - this is a cycle
                    return True

            rec_stack.remove(start)
            return False

        visited = set()
        for agent_name in self.workflow_graph:
            if agent_name not in visited and has_cycle(agent_name, visited, set()):
                raise ValueError(
                    f"Circular dependency detected involving {agent_name}. "
                    f"Circular dependencies create infinite loops and are not allowed."
                )

        return True

    def get_execution_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the last execution.

        This provides high-level metrics about the execution, useful for
        monitoring and optimization.
        """
        if not self.execution_log:
            return {'message': 'No executions yet'}

        total_time = sum(log['execution_time'] for log in self.execution_log)
        success_count = sum(bool(log['success']) for log in self.execution_log)

        return {
            'total_agents': len(self.agents),
            'executed_agents': len(self.execution_log),
            'successful_agents': success_count,
            'total_execution_time': total_time,
            'average_time_per_agent': (
                total_time / len(self.execution_log) if self.execution_log else 0
            )
        }

    async def run(
        self,
        task: Union[str, Dict[str, str]],
        synthesis_prompt: Optional[str] = None,
        user_id: str = None,
        session_id: str = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        **kwargs
    ) -> AIMessage:
        """
        Execute all agents in parallel with a task, then synthesize results with LLM.

        This is a simplified interface for the common pattern:
        1. Multiple agents research/gather information in parallel
        2. LLM synthesizes all findings into a coherent response

        Args:
            task: The task/prompt for agents. Can be:
                - str: Same prompt for all agents
                - dict: Custom prompt per agent {agent_id: prompt}
            synthesis_prompt: Prompt for LLM to synthesize results.
                            If None, uses default synthesis prompt.
                            Aliases: conclusion, summary_prompt, final_prompt
            user_id: User identifier
            session_id: Session identifier
            max_tokens: Max tokens for synthesis LLM
            temperature: Temperature for synthesis LLM
            **kwargs: Additional arguments passed to LLM

        Returns:
            AIMessage: Synthesized response from the LLM

        Example:
            >>> crew = AgentCrew(
            ...     agents=[info_agent, price_agent, review_agent],
            ...     llm=ClaudeClient()
            ... )
            >>> result = await crew.task(
            ...     task="Research iPhone 15 Pro",
            ...     synthesis_prompt="Create an executive summary"
            ... )
            >>> print(result.content)

        Raises:
            ValueError: If no LLM is configured for synthesis
        """
        if not self._llm:
            raise ValueError(
                "No LLM configured for synthesis. "
                "Pass llm parameter to AgentCrew constructor: "
                "AgentCrew(agents=[...], llm=ClaudeClient())"
            )

        if not self.agents:
            raise ValueError(
                "No agents in crew. Add agents first."
            )

        # Setup session
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'

        # Prepare tasks for each agent
        tasks_list = []

        if isinstance(task, str):
            # Same task for all agents
            tasks_list.extend(
                {'agent_id': agent_id, 'query': task}
                for agent_id, _ in self.agents.items()
            )
        elif isinstance(task, dict):
            # Custom task per agent
            for agent_id, agent_task in task.items():
                if agent_id in self.agents:
                    tasks_list.append({
                        'agent_id': agent_id,
                        'query': agent_task
                    })
                else:
                    self.logger.warning(
                        f"Agent '{agent_id}' in task dict not found in crew"
                    )
        else:
            raise ValueError(
                f"task must be str or dict, got {type(task)}"
            )

        # Execute agents in parallel
        self.logger.info(
            f"Executing {len(tasks_list)} agents in parallel for research"
        )

        parallel_result = await self.run_parallel(
            tasks=tasks_list,
            user_id=user_id,
            session_id=session_id,
            **kwargs
        )

        if not parallel_result['success']:
            raise RuntimeError(
                f"Parallel execution failed: {parallel_result.get('error', 'Unknown error')}"
            )

        # Build context from all agent results
        context_parts = ["# Research Findings from Specialist Agents\n"]

        for agent_id, result in parallel_result['results'].items():
            agent = self.agents[agent_id]
            agent_name = agent.name

            context_parts.extend((f"\n## {agent_name}\n", result, "\n---\n"))

        research_context = "\n".join(context_parts)

        # Default synthesis prompt if none provided
        if not synthesis_prompt:
            synthesis_prompt = """Based on the research findings from our specialist agents above,
provide a comprehensive synthesis that:
1. Integrates all the key findings
2. Highlights the most important insights
3. Identifies any patterns or contradictions
4. Provides actionable conclusions

Create a clear, well-structured response."""

        # Build final prompt for LLM
        final_prompt = f"""{research_context}

{synthesis_prompt}"""

        # Call LLM for synthesis
        self.logger.info("Synthesizing results with LLM coordinator")

        async with self._llm as client:
            synthesis_response = await client.ask(
                prompt=final_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                user_id=user_id,
                session_id=f"{session_id}_synthesis",
                **kwargs
            )

        # Enhance response with crew metadata
        if hasattr(synthesis_response, 'metadata'):
            synthesis_response.metadata['crew_name'] = self.name
            synthesis_response.metadata['agents_used'] = list(parallel_result['results'].keys())
            synthesis_response.metadata['total_execution_time'] = parallel_result['total_execution_time']

        # Save result (fire-and-forget, tracked for lifecycle cleanup)
        _persist_task = asyncio.get_running_loop().create_task(
            self._save_result(
                synthesis_response,
                'run',
                user_id=user_id,
                session_id=session_id,
                prompt=task if isinstance(task, str) else str(task),
                tenant=getattr(self, '_tenant', 'global'),
            )
        )
        self._persist_tasks.add(_persist_task)
        _persist_task.add_done_callback(self._persist_tasks.discard)

        return synthesis_response

    def clear_memory(self, keep_summary=False):
        """Limpia execution memory y FAISS"""
        self.execution_memory.clear()
        # self.faiss_store.clear()
        if not keep_summary:
            self._summary = None

    def get_memory_snapshot(self) -> Dict:
        """Retorna estado completo del memory para inspección"""
        return {
            "results": self.execution_memory.results,
            "summary": self._summary,
            "execution_order": self.execution_memory.execution_order
        }

    def _build_ask_context(
        self,
        semantic_results: List[Tuple[str, NodeResult, float]],
        textual_context: Dict[str, Any],
        question: str
    ) -> Dict[str, Any]:
        """
        Construye el contexto combinado para el LLM principal.

        Integra resultados de búsqueda semántica (FAISS), contexto textual
        del CrewResult, información de agentes disponibles, y metadata de ejecución.
        """
        context = {
            'question': question,
            'semantic_matches': [],
            'crew_summary': {},
            'agents_available': [],
            'execution_metadata': {}
        }

        # 1. Procesar resultados semánticos de FAISS
        seen_agents = set()
        for chunk_text, agent_result, score in semantic_results:
            if agent_result.agent_id not in seen_agents:
                context['semantic_matches'].append({
                    'agent_id': agent_result.agent_id,
                    'agent_name': agent_result.agent_name,
                    'relevant_content': chunk_text,
                    'similarity_score': round(score, 3),
                    'task_executed': agent_result.task,
                    'execution_time': agent_result.execution_time
                })
                seen_agents.add(agent_result.agent_id)

        # 2. Agregar contexto del CrewResult
        if textual_context:
            context['crew_summary'] = {
                'final_output': textual_context.get('final_output', ''),
                'relevant_logs': textual_context.get('relevant_logs', []),
                'relevant_agents': [
                    {
                        'agent_id': info.agent_id,
                        'agent_name': info.agent_name,
                        'status': info.status,
                        'execution_time': info.execution_time
                    }
                    for info in textual_context.get('relevant_agents', [])
                ]
            }

        # 3. Listar agentes disponibles para re-ejecución
        context['agents_available'] = [
            {
                'agent_id': agent_id,
                'agent_name': agent.name,
                'tool_name': f"agent_{agent_id}",
                'previous_result': (
                    self.execution_memory.get_results_by_agent(agent_id).result
                    if self.execution_memory.get_results_by_agent(agent_id)
                    else None
                )
            }
            for agent_id, agent in self.agents.items()
        ]

        # 4. Metadata de ejecución
        if self.last_crew_result:
            context['execution_metadata'] = {
                'total_agents': len(self.agents),
                'execution_mode': self.last_crew_result.metadata.get('mode', 'unknown'),
                'total_time': self.last_crew_result.total_time,
                'status': self.last_crew_result.status,
                'completed_agents': len([
                    a for a in self.last_crew_result.agents if a.status == 'completed'
                ]),
                'failed_agents': len([
                    a for a in self.last_crew_result.agents if a.status == 'failed'
                ])
            }

        return context

    def _build_ask_system_prompt(self, enable_reexecution: bool = True) -> str:
        """Construye el system prompt para el LLM principal en ask()."""
        base_prompt = f"""You are an intelligent orchestrator for the AgentCrew named "{self.name}".

Your role is to answer questions about the execution results from a team of specialized agents.
You have access to:

1. **Execution History**: Detailed results from each agent's previous execution
2. **Semantic Search**: Relevant content chunks from agent outputs based on similarity
3. **Crew Metadata**: Execution times, status, and workflow information

**IMPORTANT GUIDELINES:**

1. **Answer directly**: Use the provided context to answer the user's question accurately
2. **Cite sources**: Reference which agent(s) provided the information
3. **Be precise**: If information is not in the results, clearly state so
4. **Synthesize**: Combine information from multiple agents when relevant
"""

        if enable_reexecution:
            base_prompt += """
5. **Re-execute when needed**: If the user asks for MORE information or the existing results
   are insufficient, you can call the agent tools to get fresh data. When re-executing:
   - Use the tool named "agent_<agent_id>" to re-execute that specific agent
   - Pass a clear, focused query that addresses what information is missing
   - The agent will receive: original query + their previous result + your new question
   - Re-executed results REPLACE previous results in the execution memory

**Available Agent Tools:**
You have access to tools for each agent in the crew. Use them strategically when:
- User explicitly asks for "more information" or "additional details"
- Current results don't answer the question completely
- User wants to explore a new angle not covered in original execution

**Tool Usage Pattern:**
```
Call: agent_<agent_id>(query="Specific question for this agent")
```

The agent will provide updated information that supersedes their previous result.
"""
        else:
            base_prompt += """
5. **No re-execution**: You can only answer based on existing results.
   If information is missing, inform the user they need to run the crew again.
"""

        base_prompt += """
**Response Format:**
- Start with a direct answer to the user's question
- Reference agent sources: "According to [Agent Name]..." or "[Agent Name] found that..."
- Use markdown for readability (headers, lists, bold for key points)
- If re-executing agents, explain what new information you're gathering

Remember: You're a knowledge orchestrator, not just a data retriever. Synthesize,
analyze, and present information in the most helpful way for the user.
"""

        return base_prompt.strip()

    def _build_ask_user_prompt(self, question: str, context: Dict[str, Any]) -> str:
        """Construye el user prompt con la pregunta y contexto recuperado."""
        prompt_parts = [
            "# User Question",
            f"{question}",
            "",
            "---",
            ""
        ]

        # 1. Resultados semánticos (más importantes primero)
        if context.get('semantic_matches'):
            prompt_parts.extend([
                "# Relevant Information from Agents (Semantic Search)",
                ""
            ])

            for i, match in enumerate(context['semantic_matches'], 1):
                prompt_parts.extend([
                    f"## Match {i}: {match['agent_name']} (Similarity: {match['similarity_score']})",
                    f"**Task Executed**: {match['task_executed']}",
                    f"**Execution Time**: {match['execution_time']:.2f}s",
                    "",
                    "**Relevant Content**:",
                    "```",
                    match['relevant_content'],
                    "```",
                    ""
                ])
        else:
            prompt_parts.extend([
                "# Relevant Information from Agents",
                "*No semantically similar content found. Answering based on crew summary.*",
                ""
            ])

        # 2. Resumen del crew (si existe)
        crew_summary = context.get('crew_summary', {})
        if crew_summary.get('final_output'):
            prompt_parts.extend([
                "---",
                "",
                "# Final Crew Output",
                crew_summary['final_output'],
                ""
            ])

        if crew_summary.get('relevant_agents'):
            prompt_parts.extend([
                "## Agents Involved",
                ""
            ])
            prompt_parts.extend(
                f"- **{agent_info['agent_name']}** ({agent_info['status']}, {agent_info['execution_time']:.2f}s)"
                for agent_info in crew_summary['relevant_agents']
            )
            prompt_parts.append("")

        # 3. Metadata de ejecución
        if exec_meta := context.get('execution_metadata', {}):
            prompt_parts.extend([
                "---",
                "",
                "# Execution Metadata",
                f"- **Mode**: {exec_meta.get('execution_mode', 'unknown')}",
                f"- **Total Agents**: {exec_meta.get('total_agents', 0)}",
                f"- **Completed**: {exec_meta.get('completed_agents', 0)}",
                f"- **Failed**: {exec_meta.get('failed_agents', 0)}",
                f"- **Total Time**: {exec_meta.get('total_time', 0):.2f}s",
                f"- **Status**: {exec_meta.get('status', 'unknown')}",
                ""
            ])

        # 4. Agentes disponibles para re-ejecución
        if agents_available := context.get('agents_available', []):
            prompt_parts.extend([
                "---",
                "",
                "# Available Agents for Re-execution",
                ""
            ])
            for agent_info in agents_available:
                has_result = agent_info['previous_result'] is not None
                status_emoji = "✅" if has_result else "⚠️"

                prompt_parts.append(
                    f"{status_emoji} **{agent_info['agent_name']}** "
                    f"(tool: `{agent_info['tool_name']}`)"
                )

                if has_result:
                    # Truncar resultado previo
                    prev_result = str(agent_info['previous_result'])
                    if len(prev_result) > 200:
                        prev_result = f"{prev_result[:200]}..."
                    prompt_parts.append(f"  - Previous result: {prev_result}")
                else:
                    prompt_parts.append("  - No previous execution")

            prompt_parts.append("")

        # 5. Instrucciones finales
        prompt_parts.extend([
            "---",
            "",
            "**Instructions**: Based on the information above, answer the user's question. ",
            "If you need additional information and agent re-execution is enabled, ",
            "call the appropriate agent tools with specific queries.",
            ""
        ])

        return "\n".join(prompt_parts)

    def _textual_search(
        self,
        query: str,
        crew_result: Optional[FlowResult] = None
    ) -> Dict[str, Any]:
        """Búsqueda textual básica en el CrewResult usando keywords."""
        if crew_result is None:
            crew_result = self.last_crew_result

        if not crew_result:
            return {}

        # Extraer keywords simples (minúsculas, sin stopwords comunes)
        stopwords = {
            'el', 'la', 'de', 'que', 'en', 'y', 'a', 'los', 'las',
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'
        }

        keywords = [
            word.lower()
            for word in query.split()
            if len(word) > 2 and word.lower() not in stopwords
        ]

        if not keywords:
            keywords = [query.lower()]

        context = {
            'final_output': crew_result.output,
            'relevant_logs': [],
            'relevant_agents': []
        }

        # Buscar en execution_log
        for log_entry in crew_result.execution_log:
            log_text = json_encoder(log_entry).lower()

            # Si encuentra al menos 2 keywords o 1 keyword en logs cortos
            matches = sum(kw in log_text for kw in keywords)
            if matches >= 2 or (matches >= 1 and len(log_entry) < 500):
                context['relevant_logs'].append(log_entry)

        # Limitar logs relevantes a los más importantes
        context['relevant_logs'] = context['relevant_logs'][:5]

        # Buscar en agent metadata
        for agent_info in crew_result.agents:
            agent_text = f"{agent_info.agent_name} {agent_info.agent_id}".lower()

            if any(kw in agent_text for kw in keywords):
                context['relevant_agents'].append(agent_info)

        return context

    async def ask(
        self,
        question: str,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        top_k: int = 5,
        score_threshold: float = 0.7,
        enable_agent_reexecution: bool = True,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **llm_kwargs
    ) -> AIMessage:
        """
        Interactive execution query against the crew's execution memory.

        This method allows users to ask questions about the results of previous
        agent executions. It combines semantic search over the execution memory
        with textual search in the last CrewResult to build a context for the LLM.
        The LLM then generates a response based on this context.

        Args:
            question: User question about the results
            user_id: User identification (optional)
            session_id: Session identifier (optional)
            top_k: number of top semantic results to retrieve
            score_threshold: Score for semantic results
            enable_agent_reexecution: Allow re-executing agents via tools
            max_tokens: Maximum tokens for LLM response
            temperature: LLM Temperature
            **llm_kwargs: Additional arguments for LLM

        Returns:
            AIMessage: response of LLM.

        Raises:
            ValueError: Error if LLM is not configured or not results.

        Example:
            >>> crew = AgentCrew(agents=[...], llm=GoogleGenAIClient())
            >>> await crew.run_parallel(...)
            >>> response = await crew.ask("What found the Research Agent?")
            >>> print(response.content)
        """
        # 1. Validaciones
        if not self._llm:
            raise ValueError(
                "No LLM configured for ask(). "
                "Pass llm parameter to AgentCrew constructor."
            )

        if not self.execution_memory.results:
            raise ValueError(
                "No execution results available. Run crew first using "
                "run_sequential(), run_parallel(), run_flow(), or run_loop()."
            )

        self.logger.info(
            f"Processing ask() query: {question[:100]}..."
        )
        start_time = asyncio.get_running_loop().time()

        # 2. Búsqueda semántica en FAISS (ExecutionMemory)
        self.logger.debug(
            f"Performing semantic search with top_k={top_k}"
        )
        semantic_results = self.execution_memory.search_similar(
            query=question,
            top_k=top_k
        )

        # Filtrar por score_threshold
        semantic_results = [
            (chunk, result, score)
            for chunk, result, score in semantic_results
            if score >= score_threshold
        ]

        self.logger.info(
            f"Found {len(semantic_results)} semantic matches above threshold {score_threshold}"
        )

        # 3. Búsqueda textual en CrewResult
        textual_context = self._textual_search(
            query=question,
            crew_result=self.last_crew_result
        )

        # 4. Construir contexto combinado
        context = self._build_ask_context(
            semantic_results=semantic_results,
            textual_context=textual_context,
            question=question
        )

        # 5. Construir prompts
        system_prompt = self._build_ask_system_prompt(
            enable_reexecution=enable_agent_reexecution
        )

        user_prompt = self._build_ask_user_prompt(
            question=question,
            context=context
        )

        # 6. Ejecutar LLM principal
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_ask_user'

        self.logger.info(
            f"Calling LLM orchestrator (tools_enabled={enable_agent_reexecution})"
        )

        async with self._llm as client:
            response = await client.ask(
                prompt=user_prompt,
                system_prompt=system_prompt,
                use_tools=enable_agent_reexecution,
                use_conversation_history=False,
                max_tokens=max_tokens or 8192,
                temperature=temperature or 0.2,
                user_id=user_id,
                session_id=f"{session_id}_ask",
                **llm_kwargs
            )

        # 7. Agregar metadata a la respuesta
        end_time = asyncio.get_running_loop().time()

        if not hasattr(response, 'metadata'):
            response.metadata = {}

        response.metadata.update(
            {
                'ask_execution_time': end_time - start_time,
                'semantic_results_count': len(semantic_results),
                'semantic_results': [
                    {
                        'agent_id': result.agent_id,
                        'agent_name': result.agent_name,
                        'score': float(score),
                    }
                    for _, result, score in semantic_results
                ],
                'agents_consulted': list(
                    {result.agent_id for _, result, _ in semantic_results}
                ),
                'textual_context_used': bool(textual_context.get('relevant_logs')),
                'reexecution_enabled': enable_agent_reexecution,
                'crew_name': self.name,
            }
        )

        # Detectar si hubo re-ejecuciones (tool calls)
        if hasattr(response, 'tool_calls') and response.tool_calls:
            reexecuted_agents = []
            for call in response.tool_calls:
                tool_name = call.get('name', '') if isinstance(call, dict) else getattr(call, 'name', '')  # noqa
                if tool_name.startswith('agent_'):
                    agent_id = tool_name.replace('agent_', '')
                    reexecuted_agents.append(agent_id)

            if reexecuted_agents:
                response.metadata['agents_reexecuted'] = reexecuted_agents
                self.logger.info(
                    f"Agents re-executed during ask(): {reexecuted_agents}"
                )

        self.logger.info(
            f"ask() completed in {end_time - start_time:.2f}s"
        )

        # Save result (fire-and-forget, tracked for lifecycle cleanup)
        _persist_task = asyncio.get_running_loop().create_task(
            self._save_result(
                response,
                'ask',
                user_id=user_id,
                session_id=session_id,
                prompt=question,
                tenant=getattr(self, '_tenant', 'global'),
            )
        )
        self._persist_tasks.add(_persist_task)
        _persist_task.add_done_callback(self._persist_tasks.discard)

        return response

    # =================== SUMMARY() SYSTEM METHODS ===================
    def _chunk_results_adaptive(
        self,
        max_tokens_per_chunk: int = 4000
    ) -> List[List[NodeResult]]:
        """
        Divide resultados en chunks adaptativos respetando execution_order.

        Estrategia:
        - Respetar orden de ejecución estrictamente
        - Estimar tokens por resultado (~4 chars = 1 token)
        - Agrupar hasta max_tokens_per_chunk
        - Omitir resultados con errores

        Args:
            max_tokens_per_chunk: Máximo de tokens por chunk

        Returns:
            Lista de chunks, cada chunk es lista de AgentResult
        """
        chunks = []
        current_chunk = []
        current_tokens = 0

        # Iterar en orden de ejecución
        for agent_id in self.execution_memory.execution_order:
            result = self.execution_memory.get_results_by_agent(agent_id)

            if not result:
                continue

            # Omitir resultados con errores
            if hasattr(result, 'metadata') and result.metadata.get('status') == 'failed':
                self.logger.debug(f"Skipping failed agent: {agent_id}")
                continue

            # Estimar tokens (método simple: ~4 chars = 1 token)
            result_text = result.to_text()
            estimated_tokens = len(result_text) // 4

            # Si agregar este resultado excede el límite y ya hay resultados en el chunk
            if current_tokens + estimated_tokens > max_tokens_per_chunk and current_chunk:
                chunks.append(current_chunk)
                current_chunk = [result]
                current_tokens = estimated_tokens
            else:
                current_chunk.append(result)
                current_tokens += estimated_tokens

        # Agregar último chunk si no está vacío
        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _format_result_for_report(
        self,
        result: NodeResult,
        include_metadata: bool = False
    ) -> str:
        """
        Formatea un AgentResult como markdown para el reporte.

        Args:
            result: NodeResult a formatear
            include_metadata: Si incluir metadata (tiempo, status, etc.)

        Returns:
            String markdown formateado
        """
        parts = [
            f"## {result.agent_name}",
            "",
            f"**Task**: {result.task}",
            ""
        ]

        if include_metadata:
            parts.extend([
                f"**Execution Time**: {result.execution_time:.2f}s",
                f"**Timestamp**: {result.timestamp.isoformat()}",
                ""
            ])

        # Formatear resultado
        result_content = str(result.result)

        # Si es muy largo, agregar en bloque de código
        if len(result_content) > 500:
            parts.extend([
                "**Result**:",
                "```",
                result_content,
                "```"
            ])
        else:
            parts.extend([
                "**Result**:",
                result_content
            ])

        parts.append("")  # Línea en blanco al final

        return "\n".join(parts)

    def _generate_full_report(self) -> str:
        """
        Genera reporte completo concatenando todos los resultados.

        No usa LLM, simplemente formatea y concatena en orden.
        Omite agentes con errores.

        Returns:
            String markdown con reporte completo
        """
        self.logger.info("Generating full report (no LLM)...")

        report_parts = [
            f"# {self.name} - Full Execution Report",
            "",
            f"**Generated**: {datetime.now().isoformat()}",
            ""
        ]

        # Agregar metadata del último crew result si existe
        if self.last_crew_result:
            report_parts.extend([
                "## Execution Summary",
                "",
                f"- **Mode**: {self.last_crew_result.metadata.get('mode', 'unknown')}",
                f"- **Total Agents**: {len(self.agents)}",
                f"- **Status**: {self.last_crew_result.status}",
                f"- **Total Time**: {self.last_crew_result.total_time:.2f}s",
                "",
                "---",
                ""
            ])

        report_parts.extend(("## Agent Results", ""))
        results_added = 0
        for agent_id in self.execution_memory.execution_order:
            result = self.execution_memory.get_results_by_agent(agent_id)

            if not result:
                continue

            # Omitir errores
            if hasattr(result, 'metadata') and result.metadata.get('status') == 'failed':
                continue

            formatted = self._format_result_for_report(result, include_metadata=False)
            report_parts.append(formatted)
            report_parts.append("---")
            report_parts.append("")
            results_added += 1

        self.logger.info(f"Full report generated with {results_added} agent results")

        return "\n".join(report_parts)

    async def _generate_executive_summary(
        self,
        summary_prompt: Optional[str] = None,
        max_tokens_per_chunk: int = 4000,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **llm_kwargs
    ) -> str:
        """
        Genera executive summary usando LLM iterativo con chunks.

        Proceso:
        1. Dividir resultados en chunks
        2. Para cada chunk: LLM genera mini-summary
        3. Final pass: LLM combina mini-summaries en executive summary

        Garantiza completitud sin truncamiento por max_tokens.

        Args:
            summary_prompt: Prompt personalizado (usa default si None)
            max_tokens_per_chunk: Tokens máximos por chunk
            user_id: User ID
            session_id: Session ID

        Returns:
            String markdown con executive summary
        """
        if not self._llm:
            raise ValueError(
                "No LLM configured. Pass llm parameter to AgentCrew constructor."
            )

        self.logger.info("Generating executive summary with iterative LLM...")

        # Default summary prompt
        if not summary_prompt:
            summary_prompt = """Based on the research findings from our specialist agents above,
provide a comprehensive synthesis that:
1. Integrates all the key findings
2. Highlights the most important insights
3. Identifies any patterns or contradictions
4. Provides actionable conclusions

Create a clear, well-structured response."""

        # 1. Dividir en chunks
        chunks = self._chunk_results_adaptive(max_tokens_per_chunk)

        if not chunks:
            return "No results available to summarize."

        self.logger.info(
            f"Processing {len(chunks)} chunks for executive summary"
        )

        # 2. Procesar cada chunk con progress feedback
        mini_summaries = []
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_summary_user'
        # Progress tracking
        if self.use_tqdm:
            chunk_iterator = async_tqdm(
                enumerate(chunks, 1),
                total=len(chunks),
                desc="Summarizing chunks"
            )
        else:
            chunk_iterator = enumerate(chunks, 1)
        for chunk_idx, chunk in chunk_iterator:
            if not self.use_tqdm:
                self.logger.info(f"Processing chunk {chunk_idx}/{len(chunks)}...")

            # Construir contexto del chunk
            chunk_context_parts = [
                f"# Chunk {chunk_idx} of {len(chunks)} - Agent Results",
                ""
            ]

            for result in chunk:
                formatted = self._format_result_for_report(
                    result,
                    include_metadata=False
                )
                chunk_context_parts.append(formatted)

            chunk_context = "\n".join(chunk_context_parts)

            # Prompt para mini-summary
            chunk_prompt = f"""{chunk_context}
---
**Task**: Provide a concise summary of the key findings from these agents.
Focus on main insights and important information. This summary will be combined
with other summaries to create a final executive summary.

Keep your summary clear, structured, and focused on the most valuable information."""

            # Llamar LLM
            async with self._llm as client:
                try:
                    response = await client.ask(
                        prompt=chunk_prompt,
                        use_conversation_history=False,
                        max_tokens=8192,
                        temperature=0.3,
                        user_id=user_id,
                        session_id=f"{session_id}_chunk_{chunk_idx}",
                        **llm_kwargs
                    )
                    mini_summaries.append({
                        'chunk_idx': chunk_idx,
                        'summary': response.content,
                        'agents': [r.agent_name for r in chunk]
                    })
                except Exception as e:
                    self.logger.error(f"Error processing chunk {chunk_idx}: {e}")
                    # Agregar placeholder
                    mini_summaries.append({
                        'chunk_idx': chunk_idx,
                        'summary': f"[Error processing chunk {chunk_idx}]",
                        'agents': [r.agent_name for r in chunk]
                    })

        # 3. Final pass: Combinar mini-summaries
        self.logger.info("Generating final executive summary...")

        final_context_parts = [
            f"# {self.name} - Agent Summaries to Synthesize",
            ""
        ]

        for mini in mini_summaries:
            final_context_parts.extend([
                f"## Summary Part {mini['chunk_idx']}",
                f"*Agents: {', '.join(mini['agents'])}*",
                "",
                mini['summary'],
                "",
                "---",
                ""
            ])

        final_context = "\n".join(final_context_parts)

        # Final synthesis prompt
        final_prompt = f"""{final_context}

---

{summary_prompt}

**Important**: Create a cohesive executive summary that synthesizes ALL the information
above. Ensure the summary:
- Is well-structured with clear sections
- Integrates findings from all agent summaries
- Highlights the most critical insights
- Provides actionable recommendations
- Maintains a professional, executive-level tone"""

        # Final LLM call
        async with self._llm as client:
            final_response = await client.ask(
                prompt=final_prompt,
                use_conversation_history=False,
                max_tokens=llm_kwargs.get('max_tokens', 8192),
                temperature=0.3,
                user_id=user_id,
                session_id=f"{session_id}_final",
                **llm_kwargs
            )

        self.logger.info("Executive summary generated successfully")

        # Construir reporte final con metadata
        final_report_parts = [
            f"# {self.name} - Executive Summary",
            "",
            f"**Generated**: {datetime.now().isoformat()}",
            ""
        ]

        if self.last_crew_result:
            final_report_parts.extend([
                "## Execution Overview",
                "",
                f"- **Mode**: {self.last_crew_result.metadata.get('mode', 'unknown')}",
                f"- **Total Agents**: {len(self.agents)}",
                f"- **Status**: {self.last_crew_result.status}",
                f"- **Chunks Processed**: {len(chunks)}",
                "",
                "---",
                ""
            ])

        final_report_parts.extend([
            "## Summary",
            "",
            final_response.content
        ])

        return "\n".join(final_report_parts)

    async def summary(
        self,
        mode: Literal["full_report", "executive_summary"] = "executive_summary",
        summary_prompt: Optional[str] = None,
        max_tokens_per_chunk: int = 4000,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **llm_kwargs
    ) -> str:
        """
        Genera reporte completo o executive summary de todos los resultados.

        Dos modos de operación:

        1. **full_report** (sin LLM):
        - Itera en orden por execution_memory.execution_order
        - Concatena todos los resultados formateados
        - Retorna documento completo markdown
        - Rápido, no requiere LLM

        2. **executive_summary** (con LLM iterativo):
        - Divide resultados en chunks (respetando max_tokens)
        - LLM procesa cada chunk → genera mini-summary
        - Combina mini-summaries → executive summary final
        - Garantiza completitud sin truncamiento
        - Usa progress feedback (tqdm si disponible)

        Características:
        - Respeta execution_order estrictamente
        - Omite agentes con errores
        - No incluye metadata por default (simplificado)
        - Retorna markdown estructurado

        Args:
            mode: Tipo de reporte ('full_report' o 'executive_summary')
            summary_prompt: Prompt personalizado para executive summary
                        (usa default si None)
            max_tokens_per_chunk: Tokens máximos por chunk para executive_summary
            user_id: User identifier
            session_id: Session identifier
            **llm_kwargs: Argumentos adicionales para LLM

        Returns:
            String markdown con el reporte completo

        Raises:
            ValueError: Si mode='executive_summary' pero no hay LLM configurado
            ValueError: Si no hay resultados en execution_memory

        Example:
            >>> # Full report sin LLM
            >>> report = await crew.summary(mode="full_report")
            >>> print(report)

            >>> # Executive summary con LLM
            >>> summary = await crew.summary(
            ...     mode="executive_summary",
            ...     summary_prompt="Create executive summary highlighting ROI"
            ... )
            >>> print(summary)
        """
        # Validaciones
        if not self.execution_memory.results:
            raise ValueError(
                "No execution results available. Run crew first using "
                "run_sequential(), run_parallel(), run_flow(), or run_loop()."
            )

        if mode == "executive_summary" and not self._llm:
            try:
                # Default to Google GenAI if no LLM provided
                self.logger.warning(
                    "No LLM provided for executive summary. Defaulting to Google GenAI."
                )
                self._llm = SUPPORTED_CLIENTS['google']()
            except Exception as ex:
                self.logger.error(f"Failed to initialize default LLM: {ex}")
                raise ValueError(
                    "executive_summary mode requires LLM. "
                    "Either use mode='full_report' or pass llm to AgentCrew constructor."
                ) from ex

        self.logger.info(
            f"Generating {mode} from {len(self.execution_memory.results)} results"
        )

        # Ejecutar según modo
        if mode == "full_report":
            result = self._generate_full_report()
        else:  # executive_summary
            result = await self._generate_executive_summary(
                summary_prompt=summary_prompt,
                max_tokens_per_chunk=max_tokens_per_chunk,
                user_id=user_id,
                session_id=session_id,
                **llm_kwargs
            )

        # Save in self._summary
        self._summary = result

        return result
