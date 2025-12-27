# parrot/autonomy/orchestrator.py
"""
Autonomy Orchestrator for AI-Parrot.

Unified orchestration layer that manages autonomous execution of:
- Individual Agents
- AgentCrews (sequential, parallel, flow, loop modes)
- AgentFlows (DAG-based workflows)

Supports multiple trigger modes:
- Scheduled (APScheduler)
- Redis Jobs (dynamic injection)
- Event Bus (pub/sub)
- Webhooks (external triggers)
"""
from __future__ import annotations
from typing import (
    Dict, Any, Optional, List, Callable, Union, 
    Literal, TYPE_CHECKING
)
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import asyncio
import uuid

from navconfig.logging import logging

from .event_bus import EventBus, Event, EventPriority
from .redis_jobs import RedisJobInjector
from .webhooks import WebhookListener

if TYPE_CHECKING:
    from ..scheduler import SchedulerManager
    from ..manager import BotManager
    from ..registry import AgentRegistry
    from ..bots.orchestration import AgentCrew
    from ..bots.abstract import AbstractBot
    from ..handlers.crew.models import CrewDefinition, ExecutionMode


class ExecutionTarget(Enum):
    """Type of execution target."""
    AGENT = "agent"
    CREW = "crew"
    FLOW = "flow"  # Future: dedicated flow orchestration


@dataclass
class ExecutionRequest:
    """
    Represents a request to execute an agent or crew.
    
    This is the unified interface for all trigger modes.
    """
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Target identification
    target_type: ExecutionTarget = ExecutionTarget.AGENT
    target_id: str = ""                          # Agent name or crew name
    
    # Execution parameters
    task: str = ""                               # The prompt/query/task
    execution_mode: Optional[str] = None         # For crews: sequential, parallel, flow, loop
    
    # Crew-specific parameters
    agent_sequence: Optional[List[str]] = None   # For sequential/loop modes
    tasks: Optional[List[Dict[str, Any]]] = None # For parallel mode
    loop_condition: Optional[str] = None         # For loop mode
    max_iterations: int = 5                      # For loop mode
    synthesis_prompt: Optional[str] = None       # Optional synthesis after execution
    
    # Common parameters
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Callbacks
    callback_url: Optional[str] = None           # Webhook to notify on completion
    
    # Tracking
    created_at: datetime = field(default_factory=datetime.now)
    priority: int = 5                            # 1-10, lower = higher priority
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "target_type": self.target_type.value,
            "target_id": self.target_id,
            "task": self.task,
            "execution_mode": self.execution_mode,
            "agent_sequence": self.agent_sequence,
            "loop_condition": self.loop_condition,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "priority": self.priority
        }


@dataclass 
class ExecutionResult:
    """Result of an execution request."""
    request_id: str
    target_type: ExecutionTarget
    target_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    completed_at: datetime = field(default_factory=datetime.now)


class AutonomyOrchestrator:
    """
    Unified orchestrator for autonomous agent and crew execution.
    
    Provides a single interface to:
    - Execute individual agents
    - Execute AgentCrews in any mode (sequential, parallel, flow, loop)
    - Trigger executions via multiple channels (schedule, events, webhooks, jobs)
    
    Example:
```python
        orchestrator = AutonomyOrchestrator(
            bot_manager=bot_manager,
            redis_url="redis://localhost:6379"
        )
        await orchestrator.start()
        
        # Execute a single agent
        result = await orchestrator.execute_agent("ResearchAgent", "Find info about X")
        
        # Execute a crew
        result = await orchestrator.execute_crew(
            "research_team",
            task="Analyze market trends",
            mode="flow"
        )
        
        # Inject a job for async execution
        job_id = await orchestrator.inject_job(
            target_type="crew",
            target_id="writing_team", 
            task="Write a blog post about AI"
        )
```
    """
    
    def __init__(
        self,
        *,
        bot_manager: Optional["BotManager"] = None,
        agent_registry: Optional["AgentRegistry"] = None,
        scheduler_manager: Optional["SchedulerManager"] = None,
        redis_url: Optional[str] = None,
        use_event_bus: bool = True,
        use_webhooks: bool = True,
        default_user_id: str = "autonomy_system",
        default_session_prefix: str = "auto_"
    ):
        """
        Initialize the Autonomy Orchestrator.
        
        Args:
            bot_manager: BotManager instance (manages crews and bots)
            agent_registry: AgentRegistry instance (manages individual agents)
            scheduler_manager: Optional SchedulerManager for scheduled execution
            redis_url: Redis URL for job injection and distributed events
            use_event_bus: Enable event bus for pub/sub triggers
            use_webhooks: Enable webhook listener for external triggers
            default_user_id: Default user ID for executions
            default_session_prefix: Prefix for auto-generated session IDs
        """
        self.bot_manager = bot_manager
        self.agent_registry = agent_registry
        self.scheduler = scheduler_manager
        self.redis_url = redis_url
        
        # Components (initialized in start())
        self.event_bus: Optional[EventBus] = None
        self.job_injector: Optional[RedisJobInjector] = None
        self.webhook_listener: Optional[WebhookListener] = None
        
        # Configuration
        self._use_event_bus = use_event_bus
        self._use_webhooks = use_webhooks
        self._default_user_id = default_user_id
        self._default_session_prefix = default_session_prefix
        
        # Runtime state
        self._running = False
        self._agent_cache: Dict[str, "AbstractBot"] = {}
        self._execution_history: List[ExecutionResult] = []
        self._max_history = 1000
        
        self.logger = logging.getLogger("parrot.autonomy.orchestrator")
    
    # =========================================================================
    # Lifecycle
    # =========================================================================
    
    async def start(self):
        """Start all autonomy components."""
        self.logger.info("Starting Autonomy Orchestrator...")
        
        # Event Bus
        if self._use_event_bus:
            self.event_bus = EventBus(
                redis_url=self.redis_url,
                use_redis=bool(self.redis_url)
            )
            await self.event_bus.connect()
            self._setup_internal_event_handlers()
            self.logger.info("Event Bus initialized")
        
        # Redis Job Injector
        if self.redis_url:
            self.job_injector = RedisJobInjector(redis_url=self.redis_url)
            await self.job_injector.connect()
            await self.job_injector.start_listening(self._handle_injected_job)
            self.logger.info("Redis Job Injector initialized")
        
        # Webhook Listener
        if self._use_webhooks:
            self.webhook_listener = WebhookListener()
            self.webhook_listener.set_executor(self._webhook_executor)
            if self.event_bus:
                self.webhook_listener.set_event_bus(self.event_bus)
            self.logger.info("Webhook Listener initialized")
        
        self._running = True
        self.logger.info("Autonomy Orchestrator started successfully")
    
    async def stop(self):
        """Stop all autonomy components."""
        self._running = False
        
        if self.event_bus:
            await self.event_bus.close()
        
        if self.job_injector:
            await self.job_injector.close()
        
        self.logger.info("Autonomy Orchestrator stopped")
    
    def setup_routes(self, app):
        """Setup HTTP routes on the aiohttp application."""
        if self.webhook_listener:
            self.webhook_listener.setup(app)
    
    # =========================================================================
    # Public API: Direct Execution
    # =========================================================================
    
    async def execute_agent(
        self,
        agent_name: str,
        task: str,
        *,
        method_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs
    ) -> ExecutionResult:
        """
        Execute a single agent.
        
        Args:
            agent_name: Name of the registered agent
            task: The prompt/question to send to the agent
            method_name: Optional specific method to call (default: ask)
            user_id: User identifier
            session_id: Session identifier
            **kwargs: Additional arguments passed to the agent
            
        Returns:
            ExecutionResult with the agent's response
        """
        request = ExecutionRequest(
            target_type=ExecutionTarget.AGENT,
            target_id=agent_name,
            task=task,
            user_id=user_id or self._default_user_id,
            session_id=session_id or self._generate_session_id(),
            metadata={"method_name": method_name, **kwargs}
        )
        
        return await self._execute(request)
    
    async def execute_crew(
        self,
        crew_id: str,
        task: str,
        *,
        mode: Optional[Literal["sequential", "parallel", "flow", "loop"]] = None,
        agent_sequence: Optional[List[str]] = None,
        tasks: Optional[List[Dict[str, Any]]] = None,
        loop_condition: Optional[str] = None,
        max_iterations: int = 5,
        synthesis_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs
    ) -> ExecutionResult:
        """
        Execute an AgentCrew.
        
        Args:
            crew_id: Name/ID of the registered crew
            task: The main task/query for the crew
            mode: Execution mode (sequential, parallel, flow, loop)
                  If None, uses the crew's default mode from CrewDefinition
            agent_sequence: For sequential/loop modes, specific order of agents
            tasks: For parallel mode, list of {agent_id, query} dicts
            loop_condition: For loop mode, the stopping condition
            max_iterations: For loop mode, maximum iterations
            synthesis_prompt: Optional prompt to synthesize final results
            user_id: User identifier
            session_id: Session identifier
            **kwargs: Additional arguments passed to the crew
            
        Returns:
            ExecutionResult with the crew's CrewResult
            
        Example:
```python
            # Sequential execution
            result = await orchestrator.execute_crew(
                "writing_team",
                task="Write a blog post about AI",
                mode="sequential"
            )
            
            # Flow execution (uses DAG from CrewDefinition)
            result = await orchestrator.execute_crew(
                "research_crew",
                task="Analyze competitor landscape",
                mode="flow"
            )
            
            # Loop execution
            result = await orchestrator.execute_crew(
                "refinement_crew",
                task="Draft initial proposal",
                mode="loop",
                loop_condition="The proposal is complete and ready for review",
                max_iterations=3
            )
            
            # Parallel execution
            result = await orchestrator.execute_crew(
                "analysis_crew",
                task="Analyze data",
                mode="parallel",
                tasks=[
                    {"agent_id": "analyst1", "query": "Analyze sales data"},
                    {"agent_id": "analyst2", "query": "Analyze marketing data"},
                ]
            )
```
        """
        request = ExecutionRequest(
            target_type=ExecutionTarget.CREW,
            target_id=crew_id,
            task=task,
            execution_mode=mode,
            agent_sequence=agent_sequence,
            tasks=tasks,
            loop_condition=loop_condition,
            max_iterations=max_iterations,
            synthesis_prompt=synthesis_prompt,
            user_id=user_id or self._default_user_id,
            session_id=session_id or self._generate_session_id(),
            metadata=kwargs
        )
        
        return await self._execute(request)
    
    # =========================================================================
    # Public API: Job Injection
    # =========================================================================
    
    async def inject_job(
        self,
        target_type: Literal["agent", "crew"],
        target_id: str,
        task: str,
        *,
        priority: int = 5,
        schedule_at: Optional[datetime] = None,
        callback_url: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Inject a job for asynchronous execution.
        
        The job is queued in Redis and processed by the job listener.
        Useful for fire-and-forget executions or scheduled tasks.
        
        Args:
            target_type: "agent" or "crew"
            target_id: Name of the agent or crew
            task: The task/prompt
            priority: 1-10, lower = higher priority
            schedule_at: Optional datetime to schedule execution
            callback_url: Optional webhook URL to notify on completion
            **kwargs: Additional execution parameters
            
        Returns:
            job_id: Unique identifier for tracking the job
        """
        if not self.job_injector:
            raise RuntimeError(
                "Redis job injector not configured. "
                "Provide redis_url to AutonomyOrchestrator."
            )
        
        job_data = {
            "target_type": target_type,
            "target_id": target_id,
            "task": task,
            **kwargs
        }
        
        return await self.job_injector.inject_job(
            agent_name=target_id,  # Backward compatible field
            prompt=task,
            priority=priority,
            schedule_at=schedule_at,
            callback_url=callback_url,
            metadata=job_data
        )
    
    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of an injected job."""
        if not self.job_injector:
            return None
        return await self.job_injector.get_job_status(job_id)
    
    # =========================================================================
    # Public API: Webhooks
    # =========================================================================
    
    def register_webhook(
        self,
        path: str,
        target_type: Literal["agent", "crew"],
        target_id: str,
        *,
        secret: Optional[str] = None,
        transform_fn: Optional[Callable[[Dict], str]] = None,
        execution_mode: Optional[str] = None,
        **kwargs
    ):
        """
        Register a webhook endpoint that triggers an agent or crew.
        
        Args:
            path: URL path (e.g., "/github", "/stripe")
            target_type: "agent" or "crew"
            target_id: Name of the agent or crew
            secret: HMAC secret for signature validation
            transform_fn: Function to transform webhook payload to task/prompt
            execution_mode: For crews, the execution mode to use
            **kwargs: Additional WebhookEndpoint options
        """
        if not self.webhook_listener:
            raise RuntimeError("Webhook listener not configured")
        
        # Store target type in metadata
        metadata = kwargs.pop("metadata", {})
        metadata["target_type"] = target_type
        metadata["execution_mode"] = execution_mode
        
        return self.webhook_listener.register_endpoint(
            path=path,
            agent_name=target_id,  # Reuse existing field
            secret=secret,
            transform_fn=transform_fn,
            metadata=metadata,
            **kwargs
        )
    
    # =========================================================================
    # Public API: Events
    # =========================================================================
    
    def on_event(
        self,
        pattern: str,
        target_type: Literal["agent", "crew"],
        target_id: str,
        *,
        task_builder: Optional[Callable[[Event], str]] = None,
        execution_mode: Optional[str] = None,
        filter_fn: Optional[Callable[[Event], bool]] = None,
        **kwargs
    ) -> str:
        """
        Register an event handler that triggers an agent or crew.
        
        Args:
            pattern: Event pattern to match (e.g., "order.created", "*.completed")
            target_type: "agent" or "crew"
            target_id: Name of the agent or crew
            task_builder: Function to build task from event (default: JSON of payload)
            execution_mode: For crews, the execution mode to use
            filter_fn: Optional filter to conditionally handle events
            **kwargs: Additional execution parameters
            
        Returns:
            subscriber_id for unsubscribing
        """
        if not self.event_bus:
            raise RuntimeError("Event bus not configured")
        
        async def event_handler(event: Event):
            # Build task from event
            if task_builder:
                task = task_builder(event)
            else:
                import json
                task = f"Process event: {json.dumps(event.payload, indent=2)}"
            
            # Execute
            request = ExecutionRequest(
                target_type=ExecutionTarget.CREW if target_type == "crew" else ExecutionTarget.AGENT,
                target_id=target_id,
                task=task,
                execution_mode=execution_mode,
                metadata={
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "correlation_id": event.correlation_id,
                    **kwargs
                }
            )
            
            await self._execute(request)
        
        return self.event_bus.subscribe(
            pattern=pattern,
            handler=event_handler,
            filter_fn=filter_fn
        )
    
    async def emit_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        **kwargs
    ) -> int:
        """Emit an event to the bus."""
        if not self.event_bus:
            raise RuntimeError("Event bus not configured")
        return await self.event_bus.emit(event_type, payload, **kwargs)
    
    # =========================================================================
    # Internal: Unified Execution
    # =========================================================================
    
    async def _execute(self, request: ExecutionRequest) -> ExecutionResult:
        """
        Unified execution handler for all request types.
        """
        start_time = datetime.now()
        
        # Emit start event
        if self.event_bus:
            await self.event_bus.emit(
                f"{request.target_type.value}.execution.started",
                {
                    "request_id": request.request_id,
                    "target_id": request.target_id,
                    "task": request.task[:200] if request.task else "",
                },
                source="orchestrator",
                correlation_id=request.request_id
            )
        
        try:
            # Route to appropriate executor
            if request.target_type == ExecutionTarget.AGENT:
                result = await self._execute_agent(request)
            elif request.target_type == ExecutionTarget.CREW:
                result = await self._execute_crew(request)
            else:
                raise ValueError(f"Unknown target type: {request.target_type}")
            
            # Build success result
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            exec_result = ExecutionResult(
                request_id=request.request_id,
                target_type=request.target_type,
                target_id=request.target_id,
                success=True,
                result=result,
                execution_time_ms=execution_time,
                metadata=request.metadata
            )
            
            # Emit completion event
            if self.event_bus:
                await self.event_bus.emit(
                    f"{request.target_type.value}.execution.completed",
                    {
                        "request_id": request.request_id,
                        "target_id": request.target_id,
                        "execution_time_ms": execution_time,
                        "success": True
                    },
                    source="orchestrator",
                    correlation_id=request.request_id
                )
            
            # Track history
            self._add_to_history(exec_result)
            
            return exec_result
            
        except Exception as e:
            self.logger.error(
                f"Execution failed for {request.target_type.value} "
                f"'{request.target_id}': {e}",
                exc_info=True
            )
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            exec_result = ExecutionResult(
                request_id=request.request_id,
                target_type=request.target_type,
                target_id=request.target_id,
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
            
            # Emit failure event
            if self.event_bus:
                await self.event_bus.emit(
                    f"{request.target_type.value}.execution.failed",
                    {
                        "request_id": request.request_id,
                        "target_id": request.target_id,
                        "error": str(e)
                    },
                    source="orchestrator",
                    priority=EventPriority.HIGH,
                    correlation_id=request.request_id
                )
            
            self._add_to_history(exec_result)
            return exec_result
    
    async def _execute_agent(self, request: ExecutionRequest) -> Any:
        """Execute a single agent."""
        agent = await self._get_agent(request.target_id)
        
        method_name = request.metadata.get("method_name")
        
        if method_name and hasattr(agent, method_name):
            method = getattr(agent, method_name)
            return await method(request.task)
        else:
            return await agent.ask(
                request.task,
                user_id=request.user_id,
                session_id=request.session_id
            )
    
    async def _execute_crew(self, request: ExecutionRequest) -> Any:
        """Execute an AgentCrew."""
        crew, crew_def = await self._get_crew(request.target_id)
        
        # Determine execution mode
        mode = request.execution_mode
        if not mode and crew_def:
            mode = crew_def.execution_mode.value.lower()
        mode = mode or "sequential"
        
        # Common kwargs
        common_kwargs = {
            "user_id": request.user_id,
            "session_id": request.session_id,
            "synthesis_prompt": request.synthesis_prompt,
            **request.metadata
        }
        
        self.logger.info(
            f"Executing crew '{request.target_id}' in '{mode}' mode"
        )
        
        # Execute based on mode
        if mode == "sequential":
            return await crew.run_sequential(
                query=request.task,
                agent_sequence=request.agent_sequence,
                **common_kwargs
            )
        
        elif mode == "parallel":
            # Build tasks list
            tasks = request.tasks
            if not tasks:
                # Default: all agents get the same task
                tasks = [
                    {"agent_id": agent_id, "query": request.task}
                    for agent_id in crew.agents.keys()
                ]
            return await crew.run_parallel(
                tasks=tasks,
                **common_kwargs
            )
        
        elif mode == "flow":
            return await crew.run_flow(
                task=request.task,
                **common_kwargs
            )
        
        elif mode == "loop":
            if not request.loop_condition:
                raise ValueError(
                    "loop_condition is required for loop execution mode"
                )
            return await crew.run_loop(
                initial_task=request.task,
                condition=request.loop_condition,
                agent_sequence=request.agent_sequence,
                max_iterations=request.max_iterations,
                **common_kwargs
            )
        
        else:
            raise ValueError(f"Unknown execution mode: {mode}")
    
    # =========================================================================
    # Internal: Resource Management
    # =========================================================================
    
    async def _get_agent(self, agent_name: str) -> "AbstractBot":
        """Get an agent by name, with caching."""
        # Check cache
        if agent_name in self._agent_cache:
            return self._agent_cache[agent_name]
        
        agent = None
        
        # Try AgentRegistry first
        if self.agent_registry:
            agent = self.agent_registry.get_bot_instance(agent_name)
        
        # Try BotManager
        if not agent and self.bot_manager:
            agent = self.bot_manager._bots.get(agent_name)
        
        if not agent:
            raise ValueError(f"Agent '{agent_name}' not found")
        
        # Ensure configured
        if hasattr(agent, 'configure') and not self._agent_is_configured(agent):
            await agent.configure()
        
        # Cache
        self._agent_cache[agent_name] = agent
        return agent
    
    async def _get_crew(
        self, 
        crew_id: str
    ) -> tuple["AgentCrew", Optional["CrewDefinition"]]:
        """Get a crew by ID from BotManager."""
        if not self.bot_manager:
            raise RuntimeError(
                "BotManager not configured. "
                "Provide bot_manager to AutonomyOrchestrator for crew support."
            )
        
        crew_data = await self.bot_manager.get_crew(crew_id)
        
        if not crew_data:
            raise ValueError(f"Crew '{crew_id}' not found")
        
        crew, crew_def = crew_data
        
        # Auto-configure agents in crew
        for agent in crew.agents.values():
            if hasattr(agent, 'configure') and not self._agent_is_configured(agent):
                await agent.configure()
        
        return crew, crew_def
    
    def _agent_is_configured(self, agent: "AbstractBot") -> bool:
        """Check if an agent is configured."""
        if hasattr(agent, '_llm'):
            return agent._llm is not None
        return True
    
    # =========================================================================
    # Internal: Event Handlers
    # =========================================================================
    
    def _setup_internal_event_handlers(self):
        """Setup internal event bus handlers."""
        
        # Log all execution events
        @self.event_bus.on("*.execution.*")
        async def log_executions(event: Event):
            self.logger.debug(
                f"Execution event: {event.event_type} - "
                f"{event.payload.get('target_id')}"
            )
        
        # Chain reactive executions
        @self.event_bus.on("*.execution.completed")
        async def handle_completion(event: Event):
            # Future: implement reactive agent chains
            pass
    
    async def _handle_injected_job(self, job_data: Dict[str, Any]) -> Any:
        """Handle jobs injected via Redis."""
        metadata = job_data.get("metadata", {})
        target_type = metadata.get("target_type", "agent")
        target_id = job_data.get("agent_name") or metadata.get("target_id")
        task = job_data.get("prompt") or metadata.get("task")
        
        self.logger.info(
            f"Processing injected job: {target_type} '{target_id}'"
        )
        
        request = ExecutionRequest(
            target_type=ExecutionTarget.CREW if target_type == "crew" else ExecutionTarget.AGENT,
            target_id=target_id,
            task=task,
            execution_mode=metadata.get("execution_mode"),
            agent_sequence=metadata.get("agent_sequence"),
            loop_condition=metadata.get("loop_condition"),
            metadata=metadata
        )
        
        result = await self._execute(request)
        return result.result if result.success else {"error": result.error}
    
    async def _webhook_executor(
        self,
        agent_name: str,
        prompt: str,
        **kwargs
    ) -> Any:
        """Executor callback for webhook listener."""
        metadata = kwargs.get("metadata", {})
        target_type = metadata.get("target_type", "agent")
        execution_mode = metadata.get("execution_mode")
        
        if target_type == "crew":
            result = await self.execute_crew(
                crew_id=agent_name,
                task=prompt,
                mode=execution_mode
            )
        else:
            result = await self.execute_agent(
                agent_name=agent_name,
                task=prompt
            )
        
        return result.result if result.success else None
    
    # =========================================================================
    # Internal: Utilities
    # =========================================================================
    
    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        return f"{self._default_session_prefix}{uuid.uuid4().hex[:12]}"
    
    def _add_to_history(self, result: ExecutionResult):
        """Add result to execution history."""
        self._execution_history.append(result)
        if len(self._execution_history) > self._max_history:
            self._execution_history = self._execution_history[-self._max_history:]
    
    def get_execution_history(
        self,
        limit: int = 100,
        target_type: Optional[str] = None,
        success_only: bool = False
    ) -> List[ExecutionResult]:
        """Get execution history with optional filtering."""
        results = self._execution_history[-limit:]
        
        if target_type:
            target = ExecutionTarget(target_type)
            results = [r for r in results if r.target_type == target]
        
        if success_only:
            results = [r for r in results if r.success]
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        history = self._execution_history
        
        return {
            "running": self._running,
            "components": {
                "event_bus": self.event_bus is not None,
                "job_injector": self.job_injector is not None,
                "webhook_listener": self.webhook_listener is not None,
                "scheduler": self.scheduler is not None
            },
            "execution_stats": {
                "total": len(history),
                "successful": len([r for r in history if r.success]),
                "failed": len([r for r in history if not r.success]),
                "by_type": {
                    "agent": len([r for r in history if r.target_type == ExecutionTarget.AGENT]),
                    "crew": len([r for r in history if r.target_type == ExecutionTarget.CREW])
                }
            },
            "cached_agents": len(self._agent_cache)
        }