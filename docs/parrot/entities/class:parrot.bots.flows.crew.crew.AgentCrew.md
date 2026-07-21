---
type: Wiki Entity
title: AgentCrew
id: class:parrot.bots.flows.crew.crew.AgentCrew
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Enhanced AgentCrew supporting multiple execution modes.
relates_to:
- concept: class:parrot.bots.flows.core.storage.persistence.PersistenceMixin
  rel: extends
- concept: class:parrot.bots.flows.core.storage.synthesis.SynthesisMixin
  rel: extends
---

# AgentCrew

Defined in [`parrot.bots.flows.crew.crew`](../summaries/mod:parrot.bots.flows.crew.crew.md).

```python
class AgentCrew(PersistenceMixin, SynthesisMixin)
```

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

## Methods

- `def agent_statuses(self) -> Dict[str, Dict[str, Any]]` — Get the status of all agents.
- `def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]` — Get the status of a specific agent.
- `def build_execution_document(self) -> Optional['CrewExecutionDocument']` — Assemble the document for the LAST run from in-process state (LLM-free).
- `def on_complete(self, callback: CrewHookCallback) -> None` — Register a callback to fire when crew execution completes.
- `def on_error(self, callback: CrewHookCallback) -> None` — Register a callback to fire when crew execution has errors.
- `def from_definition(cls, crew_def: 'CrewDefinition', *, class_resolver: Callable[[str], Optional[type]], tool_resolver: Optional[Callable[[str], Optional[AbstractTool]]]=None, **kwargs) -> 'AgentCrew'` — Create an AgentCrew from a CrewDefinition.
- `def add_agent(self, agent: Union[BasicAgent, AbstractBot], agent_id: str=None) -> None` — Add an agent to the crew.
- `def add_tool_node(self, tool: AbstractTool, node_id: str, *, args: Optional[List[Any]]=None, kwargs: Optional[Dict[str, Any]]=None, description: Optional[str]=None) -> ToolNode` — Add a deterministic tool-execution node as a crew member.
- `def remove_agent(self, agent_id: str) -> bool` — Remove an agent (or tool node) from the crew.
- `def add_shared_tool(self, tool: AbstractTool, tool_name: str=None) -> None` — Add a tool shared across all agents.
- `def get_agent_statuses(self) -> List[dict]` — Get current status of all agents.
- `def get_agent_result(self, agent_id: str) -> Optional[NodeResult]` — Return the most recent ``NodeResult`` for *agent_id*, or ``None``.
- `def task_flow(self, source_agent: Any, target_agents: Any)` — Define a task flow from source agent(s) to target agent(s).
- `async def run_sequential(self, query: str, user_id: str=None, session_id: str=None, pass_full_context: bool=True, generate_summary: bool=True, synthesis_prompt: Optional[str]=None, agent_sequence: List[str]=None, max_tokens: int=8192, temperature: float=0.1, model: Optional[str]='gemini-2.5-pro', **kwargs) -> FlowResult` — Execute agents in sequence (pipeline pattern).
- `async def run_loop(self, initial_task: str, condition: str, max_iterations: int=2, user_id: str=None, session_id: str=None, agent_sequence: Optional[List[str]]=None, pass_full_context: bool=True, generate_summary: bool=True, synthesis_prompt: Optional[str]=None, model: Optional[str]=None, max_tokens: int=8192, temperature: float=0.1, **kwargs) -> FlowResult` — Execute agents iteratively until the stopping condition is met.
- `async def run_parallel(self, tasks: List[Dict[str, Any]], all_results: Optional[bool]=True, user_id: str=None, session_id: str=None, generate_summary: bool=True, synthesis_prompt: Optional[str]=None, max_tokens: int=8192, temperature: float=0.1, **kwargs) -> FlowResult` — Execute multiple agents in parallel using asyncio.gather().
- `async def run_flow(self, initial_task: str, max_iterations: int=100, generate_summary: bool=True, synthesis_prompt: Optional[str]=None, user_id: str=None, session_id: str=None, max_tokens: int=8192, temperature: float=0.1, on_agent_complete: Optional[Callable]=None, **kwargs) -> FlowResult` — Execute the workflow using the defined task flows (DAG-based execution).
- `def visualize_workflow(self) -> str` — Generate a text representation of the workflow graph.
- `async def validate_workflow(self) -> bool` — Validate the workflow for common issues.
- `def get_execution_summary(self) -> Dict[str, Any]` — Get a summary of the last execution.
- `async def run(self, task: Union[str, Dict[str, str]], synthesis_prompt: Optional[str]=None, user_id: str=None, session_id: str=None, max_tokens: int=8192, temperature: float=0.1, **kwargs) -> AIMessage` — Execute all agents in parallel with a task, then synthesize results with LLM.
- `def clear_memory(self, keep_summary=False)` — Limpia execution memory y FAISS
- `def get_memory_snapshot(self) -> Dict` — Retorna estado completo del memory para inspección
- `async def ask(self, question: str, *, user_id: Optional[str]=None, session_id: Optional[str]=None, top_k: int=5, score_threshold: float=0.7, enable_agent_reexecution: bool=True, max_tokens: Optional[int]=None, temperature: Optional[float]=None, **llm_kwargs) -> AIMessage` — Interactive execution query against the crew's execution memory.
- `async def summary(self, mode: Literal['full_report', 'executive_summary']='executive_summary', summary_prompt: Optional[str]=None, max_tokens_per_chunk: int=4000, user_id: Optional[str]=None, session_id: Optional[str]=None, **llm_kwargs) -> str` — Genera reporte completo o executive summary de todos los resultados.
