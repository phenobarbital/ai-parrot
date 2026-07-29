---
type: Wiki Entity
title: AutonomousOrchestrator
id: class:parrot.autonomous.orchestrator.AutonomousOrchestrator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified orchestrator for autonomous agent and crew execution.
---

# AutonomousOrchestrator

Defined in [`parrot.autonomous.orchestrator`](../summaries/mod:parrot.autonomous.orchestrator.md).

```python
class AutonomousOrchestrator
```

Unified orchestrator for autonomous agent and crew execution.
    
    Provides a single interface to:
    - Execute individual agents
    - Execute AgentCrews in any mode (sequential, parallel, flow, loop)
    - Trigger executions via multiple channels (schedule, events, webhooks, jobs)
    
    Example:
```python
        orchestrator = AutonomousOrchestrator(
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

## Methods

- `async def start(self, ledger: 'Optional[EventLedger]'=None, *, resume_on_start: bool=False) -> None` — Start all autonomy components.
- `async def stop(self)` — Stop all autonomy components.
- `def setup_routes(self, app)` — Setup HTTP routes on the aiohttp application.
- `def add_hook(self, hook: BaseHook) -> str` — Register an external hook that triggers executions.
- `async def execute_agent(self, agent_name: str, task: str, *, method_name: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, **kwargs) -> ExecutionResult` — Execute a single agent.
- `async def execute_crew(self, crew_id: str, task: str, *, mode: Optional[Literal['sequential', 'parallel', 'flow', 'loop']]=None, agent_sequence: Optional[List[str]]=None, tasks: Optional[List[Dict[str, Any]]]=None, loop_condition: Optional[str]=None, max_iterations: int=5, synthesis_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, **kwargs) -> ExecutionResult` — Execute an AgentCrew.
- `async def resume_agent(self, session_id: str, user_input: str, state: Dict[str, Any]) -> ExecutionResult` — Resume an agent that was paused for human interaction.
- `async def inject_job(self, target_type: Literal['agent', 'crew'], target_id: str, task: str, *, priority: int=5, schedule_at: Optional[datetime]=None, callback_url: Optional[str]=None, **kwargs) -> str` — Inject a job for asynchronous execution.
- `async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]` — Get the status of an injected job.
- `def register_webhook(self, path: str, target_type: Literal['agent', 'crew'], target_id: str, *, secret: Optional[str]=None, transform_fn: Optional[Callable[[Dict], str]]=None, execution_mode: Optional[str]=None, **kwargs)` — Register a webhook endpoint that triggers an agent or crew.
- `def on_event(self, pattern: str, target_type: Literal['agent', 'crew'], target_id: str, *, task_builder: Optional[Callable[[Event], str]]=None, execution_mode: Optional[str]=None, filter_fn: Optional[Callable[[Event], bool]]=None, **kwargs) -> str` — Register an event handler that triggers an agent or crew.
- `async def emit_event(self, event_type: str, payload: Dict[str, Any], **kwargs) -> int` — Emit an event to the bus.
- `def get_execution_history(self, limit: int=100, target_type: Optional[str]=None, success_only: bool=False) -> List[ExecutionResult]` — Get execution history with optional filtering.
- `def get_stats(self) -> Dict[str, Any]` — Get orchestrator statistics.
- `async def resume(self, ledger: 'EventLedger') -> int` — Re-enqueue incomplete executions found in the ledger.
