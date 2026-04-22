# OrchestratorAgent AIMessage Preservation

## Problem

OrchestratorAgent exposes specialist agents as tools via `AgentTool`. When a specialist
(e.g., PandasAgent) returns an `AIMessage` with rich data (`data`, `artifacts`,
`source_documents`, `code`, `images`), the `AgentTool._execute()` method extracts only
the string `output` and discards everything else. The LLM tool protocol is string-based,
so the rich payload never reaches the frontend.

**Concrete impact**: The frontend `AgentChat` component uses `AIMessage.data` to render
charts and tables. When a PandasAgent is used directly, charts render correctly. When
the same agent is accessed through an orchestrator, `data` is `None` and the frontend
falls back to plain text.

**Use case**: 4 PandasAgent finance agents (Pokemon, Epson, Roadshows, General) each
work correctly standalone. The CFO/CIO needs a single OrchestratorAgent entry point
that routes to the correct specialist without breaking the rich response contract.

## Design

### Approach: AIMessage Side-Channel in AgentResult

The LLM tool protocol remains string-based. `AgentTool._execute()` continues returning
`str` to the LLM. However, the full `AIMessage` is preserved in `AgentResult` as a side
channel. The orchestrator reads it after the tool-calling loop completes and reconstructs
the final response.

### Two Response Modes

**Pass-through** (single agent routed): The orchestrator returns the specialist's
`AIMessage` directly — zero data loss. This is the 90% case for the finance use case.

**Synthesis** (multi-agent): The orchestrator keeps the LLM's synthesized text output
but merges `data` from all specialists into a `{agent_name: data}` dictionary.

**Heuristic**: If exactly 1 agent was called and its `AIMessage` has rich content
(`data`, `artifacts`, `images`, or `code`), use pass-through. If exactly 1 agent was
called but its `AIMessage` has no rich content (text-only response), use synthesis
(the LLM's summary is likely more useful). If multiple agents were called, always
use synthesis.

## Changes by File

### 1. `parrot/models/crew.py` — AgentResult

Add `ai_message` field to `AgentResult`:

```python
@dataclass
class AgentResult:
    agent_id: str
    agent_name: str
    task: str
    result: Any                                # string output (for vectorization, cross-pollination)
    ai_message: Optional[AIMessage] = None     # NEW: full AIMessage preserved
    metadata: Dict[str, Any]
    execution_time: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    parent_execution_id: Optional[str] = None
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
```

- `result` keeps the string — used by `to_text()` for vectorization and by
  `_build_cross_pollination_context()` for LLM context injection.
- `ai_message` holds the complete specialist AIMessage. Optional for backward
  compatibility — non-orchestrated uses and non-AIMessage responses remain `None`.
- `to_text()` unchanged — still uses `result`.

### 2. `parrot/tools/agent.py` — AgentTool._execute()

Capture AIMessage before extracting string:

```python
async def _execute(self, **kwargs) -> str:
    # ... existing question/context setup ...
    
    response = await self.agent.ask(...)  # or conversation/invoke
    
    # NEW: preserve full AIMessage
    full_ai_message = None
    if isinstance(response, (AIMessage, AgentResponse)):
        full_ai_message = (
            response if isinstance(response, AIMessage)
            else response.response
        )
    
    # Existing: extract string content
    if isinstance(response, (AIMessage, AgentResponse)) or hasattr(response, 'content'):
        result = response.content
    elif hasattr(response, 'output'):
        result = response.output
    else:
        result = str(response)
    
    # Store with AIMessage
    if self.execution_memory:
        agent_result = AgentResult(
            agent_id=self.agent.name,
            agent_name=self.agent.name,
            task=question,
            result=result,
            ai_message=full_ai_message,    # NEW
            metadata={...},
            execution_time=execution_time
        )
        # ... existing mode/append logic ...
    
    return result  # string to LLM — unchanged
```

No changes to return type, schema, or tool protocol.

### 3. `parrot/bots/orchestration/agent.py` — OrchestratorAgent

#### 3a. Registry Integration

```python
from ...registry import agent_registry

class OrchestratorAgent(BasicAgent):
    
    def __init__(
        self,
        name: str = "OrchestratorAgent",
        orchestration_prompt: str = None,
        agent_names: Optional[List[str]] = None,
        **kwargs
    ):
        super().__init__(name=name, **kwargs)
        self.agent_tools: Dict[str, AgentTool] = {}
        self.specialist_agents: Dict[str, Union[BasicAgent, AbstractBot]] = {}
        self._pending_agent_names: List[str] = agent_names or []
        # ... existing prompt logic ...
    
    async def configure(self, app=None) -> None:
        await super().configure(app)
        for name in self._pending_agent_names:
            await self.add_agent_by_name(name)
        await self.register_specialist_agents()
    
    async def add_agent_by_name(
        self,
        agent_name: str,
        tool_name: str = None,
        description: str = None,
        **kwargs
    ) -> None:
        agent = await agent_registry.get_instance(agent_name)
        if agent is None:
            raise ValueError(f"Agent '{agent_name}' not found in registry")
        if hasattr(agent, 'configure') and not getattr(agent, '_configured', False):
            await agent.configure(app=self._app)
        self.add_agent(agent=agent, tool_name=tool_name, description=description, **kwargs)
```

Usage:
```python
# Declarative
orchestrator = OrchestratorAgent(
    name="FinanceOrchestrator",
    agent_names=["pokemon_finance", "epson_finance", "roadshows_finance", "general_finance"]
)

# Programmatic
await orchestrator.add_agent_by_name("pokemon_finance")
```

#### 3b. Custom ask() with Pass-through/Synthesis

```python
async def ask(self, question: str, **kwargs) -> AIMessage:
    self._init_execution_memory(question)
    response = await super().ask(question, **kwargs)
    agent_results = self._collect_agent_results()
    
    if not agent_results:
        return response
    
    if len(agent_results) == 1 and self._is_passthrough_eligible(response):
        return self._build_passthrough_response(response, agent_results)
    else:
        return self._build_synthesis_response(response, agent_results)

def _init_execution_memory(self, question: str):
    from ..flow.storage.memory import ExecutionMemory
    self._execution_memory = ExecutionMemory(original_query=question)
    for agent_tool in self.agent_tools.values():
        agent_tool.execution_memory = self._execution_memory

def _collect_agent_results(self) -> Dict[str, AgentResult]:
    return dict(self._execution_memory.results)

def _is_passthrough_eligible(self, response: AIMessage) -> bool:
    agent_result = list(self._execution_memory.results.values())[0]
    if agent_result.ai_message is None:
        return False
    specialist = agent_result.ai_message
    return bool(
        specialist.data is not None
        or specialist.artifacts
        or specialist.images
        or specialist.code
    )

def _build_passthrough_response(
    self,
    orchestrator_response: AIMessage,
    agent_results: Dict[str, AgentResult]
) -> AIMessage:
    agent_result = list(agent_results.values())[0]
    specialist_msg = agent_result.ai_message
    specialist_msg.session_id = orchestrator_response.session_id
    specialist_msg.turn_id = orchestrator_response.turn_id
    specialist_msg.input = orchestrator_response.input
    specialist_msg.metadata = {
        **specialist_msg.metadata,
        "orchestrated": True,
        "mode": "passthrough",
        "routed_to": agent_result.agent_name,
    }
    return specialist_msg

def _build_synthesis_response(
    self,
    orchestrator_response: AIMessage,
    agent_results: Dict[str, AgentResult]
) -> AIMessage:
    merged_data = {}
    merged_artifacts = []
    merged_sources = []
    
    for agent_name, agent_result in agent_results.items():
        if agent_result.ai_message is None:
            continue
        msg = agent_result.ai_message
        if msg.data is not None:
            merged_data[agent_name] = msg.data
        for artifact in (msg.artifacts or []):
            merged_artifacts.append({**artifact, "source_agent": agent_name})
        merged_sources.extend(msg.source_documents or [])
    
    if merged_data:
        orchestrator_response.data = merged_data
    if merged_artifacts:
        orchestrator_response.artifacts = merged_artifacts
    if merged_sources:
        orchestrator_response.source_documents = merged_sources
    
    orchestrator_response.metadata = {
        **orchestrator_response.metadata,
        "orchestrated": True,
        "mode": "synthesis",
        "agents_consulted": list(agent_results.keys()),
    }
    return orchestrator_response
```

## Data Flow

### Pass-through (single agent)

```
User → OrchestratorAgent.ask()
  → _init_execution_memory()
  → super().ask()
    → LLM chooses 1 agent tool
    → AgentTool._execute()
      → PandasAgent.ask() → AIMessage(data={DataFrame})
      → Stores AgentResult(result="text", ai_message=<full AIMessage>)
      → Returns "text" to LLM
    → LLM produces final text
  → _collect_agent_results() → 1 result with data
  → PASS-THROUGH
  → Returns specialist's AIMessage(data={DataFrame})
  → Frontend renders chart
```

### Synthesis (multi-agent)

```
User → OrchestratorAgent.ask()
  → _init_execution_memory()
  → super().ask()
    → LLM calls pokemon_finance + epson_finance
    → Both AgentTools store AgentResult with ai_message
    → LLM synthesizes text comparison
  → _collect_agent_results() → 2 results
  → SYNTHESIS
  → orchestrator_response.data = {
      "pokemon_finance": {DataFrame},
      "epson_finance": {DataFrame}
    }
  → orchestrator_response.output = "LLM synthesis text"
  → Frontend renders tabs per agent
```

## Frontend Contract

| `response.data` type | Frontend behavior |
|---|---|
| `list` | Render as-is (single dataset, existing) |
| `dict` with agent-name keys | Render as tabs/sections per agent (FEAT-098 compatible) |
| `None` | Text-only response, no charts |

## Files Changed

| File | Change | Risk |
|---|---|---|
| `parrot/models/crew.py` | Add `ai_message` field to `AgentResult` | Low — optional field, backward compatible |
| `parrot/tools/agent.py` | Capture AIMessage in `_execute()` | Low — no change to return type or protocol |
| `parrot/bots/orchestration/agent.py` | Registry integration + custom `ask()` | Medium — new behavior, needs tests |

## Out of Scope

- Making `AgentRegistry` a true singleton — separate follow-up
- Frontend changes for multi-data tabs rendering — covered by FEAT-098
- Streaming support for orchestrated responses — future enhancement
- AgentCrew integration with this pattern — separate concern
