# AI-Parrot — Architectural Context

## What is AI-Parrot
Async-first Python framework for building AI Agents and Chatbots.
Vendor-agnostic: supports OpenAI, Anthropic, Google GenAI, Groq, VertexAI,
HuggingFace via a unified `AbstractClient` interface.

---

## Core Abstractions (always inherit from these)

### AbstractClient
Unified interface for all LLM providers.
Location: `parrot/clients/abstract_client.py`
- Never call provider SDKs directly — always go through AbstractClient
- Implement `async def completion()`, `async def stream()`, `async def embed()`

### AbstractBot / Chatbot / Agent
Location: `parrot/bots/`
- `AbstractBot` — base class for all bots
- `Chatbot` — conversational, stateful, single-LLM
- `Agent` — tool-using, ReAct-style reasoning loop

### AbstractTool / @tool decorator
Location: `parrot/tools/`
- Simple functions: use `@tool` decorator
- Complex collections: inherit `AbstractToolkit`
- Every tool MUST have a docstring — it becomes the LLM's tool description

### AgentCrew
Location: `parrot/bots/orchestration/crew.py`
Three execution modes:
- `run_sequential()` — agents in chain, output feeds next
- `run_parallel()` — agents run concurrently, results merged
- `run_flow()` — DAG-based, dependencies declared via `task_flow()`

### Loaders
Location: `parrot/loaders/`
Transform documents (PDF, HTML, DOCX, etc.) into text chunks for RAG.
Inherit `BaseLoader`, implement `async def load() -> list[Document]`

### Vector Stores
- PgVector: `parrot/vectorstores/pgvector.py` — primary store
- ArangoDB: graph-based, in development

---

## Key Patterns to Follow

### Registering a new component
New bots/tools/clients are registered via decorators:
```python
from parrot.registry import register_agent

@register_agent("my-agent")
class MyAgent(Agent):
    ...
```

### Async everywhere
```python
# CORRECT
async def process(self, data: str) -> Result:
    result = await self.client.completion(data)
    return result

# WRONG — never block the event loop
def process(self, data: str) -> Result:
    return requests.post(...)
```

### Logging pattern
```python
import logging

class MyComponent:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def method(self):
        self.logger.info("Starting operation")
        self.logger.debug("Detail: %s", detail)
```

### Pydantic for all structured data
```python
from pydantic import BaseModel, Field

class ToolInput(BaseModel):
    query: str = Field(..., description="Used as tool description for LLM")
    top_k: int = Field(default=5, ge=1, le=20)
```

---

## What Lives Where
```
parrot/
├── clients/          # LLM provider wrappers (AbstractClient subclasses)
├── bots/             # Bot and Agent implementations
│   └── orchestration/  # AgentCrew, DAG execution
├── tools/            # Tool definitions and toolkits
├── loaders/          # Document loaders for RAG
├── vectorstores/     # PgVector, ArangoDB
├── handlers/         # HTTP handlers (aiohttp-based)
├── memory/           # Conversation memory (Redis-backed)
└── integrations/     # Telegram, MS Teams, Slack, MCP
```

---

## What NOT to Do
- Never use `requests` or `httpx` — use `aiohttp`
- Never subclass LangChain components — LangChain is removed
- Never store secrets in code — use environment variables
- Never add synchronous blocking code in async methods
- Never modify `abstract_client.py` without discussing first — it's the foundation

---

## Current Active Development
Branch: `finance-agents`
Main: `main`

Active areas (check these before modifying):
- `parrot/bots/orchestration/` — AgentCrew DAG execution
- `parrot/memory/` — Redis-based conversation memory
- `parrot/integrations/mcp/` — MCP server implementation
- `parrot/tools/` — Tool definitions and toolkits
- `parrot/integrations/` — Platform integrations (Whatsapp, Telegram, Slack, MS Teams)