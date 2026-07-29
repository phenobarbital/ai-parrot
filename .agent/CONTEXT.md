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
Location: `parrot/bots/flows/crew/crew.py`
(moved from `parrot/bots/orchestration/crew.py` in FEAT-143)
Four execution modes:
- `run_sequential()` — agents in chain, output feeds next
- `run_parallel()` — agents run concurrently, results merged
- `run_flow()` — DAG-based, dependencies declared via `task_flow()`
- `run_loop()` — iterate until a stop condition is met
Build from a `CrewDefinition` via `AgentCrew.from_definition()`.

### AgentsFlow
Location: `parrot/bots/flows/flow/flow.py`
Event-driven DAG executor (FEAT-163 rewrite; the legacy
`parrot/bots/flow/` package was removed in FEAT-196). Operates on a graph
of `Node` instances from `parrot/bots/flows/core/`.
- Build programmatically with `add_node()` + `add_edge()` (explicit-edge
  mode: conditional routing via `predicate`, OR-join, skip-propagation), or
  declaratively with `AgentsFlow.from_definition(FlowDefinition, ...)`.
- Run with `run_flow(ctx)` where `ctx` is a `FlowContext` or a prompt string.
- Specialized nodes in `flows/flow/nodes.py`: `DecisionFlowNode` (CIO/BALLOT/
  CONSENSUS), `InteractiveDecisionNode`, plus `SynthesisNode`.
- Attach `on_node_event` listeners for lifecycle telemetry.
Inherits `PersistenceMixin` (not `SynthesisMixin`).

### ModelSwitchingMixin
Location: `parrot/bots/mixins/model_switching.py`
Dual-LLM model switching for any bot/agent (`class MyAgent(ModelSwitchingMixin, Agent)`).
Configure a `secondary_llm` (same formats as `llm`: `"provider:model"`, client
class/instance, or model_config dict) plus a `model_switch_mode`:
- `fallback` — primary serves every call; on error the same call is retried
  once on the secondary client (cross-provider failover, complementary to the
  client-level same-provider `fallback_model`).
- `contrastive` — both models answer concurrently; the merged `AIMessage`
  carries a combined labeled output and `metadata['model_switching']`
  attributes each answer (provider, model, usage, timing) to its model.
Built on the `AbstractBot.get_client()` / `execute_llm_call()` hooks (same
cooperative pattern as `IntentRouterMixin`). v1 limitation: `ask_stream`
always uses the primary client.

### Loaders
Location: `parrot/loaders/`
Transform documents (PDF, HTML, DOCX, etc.) into text chunks for RAG.
Inherit `BaseLoader`, implement `async def load() -> list[Document]`

### Vector Stores
- PgVector: `parrot/vectorstores/pgvector.py` — primary store
- ArangoDB: graph-based, in development

### Skills
Location: `parrot/skills/`
Lightweight, on-demand behavioral instructions an agent can load (two-tier:
a static `<available_skills>` prompt index + on-demand body retrieval).

Skill **discovery** (`SkillsDirectoryLoader` / `SkillFileRegistry`) recognises
both layouts per directory:
- **single-file**: `{dir}/{name}.md`
- **composite**: `{dir}/{name}/SKILL.md` + adjacent asset files (templates,
  scripts, examples) exposed via `SkillDefinition.assets_dir`.

The agent-facing tools are grouped into **two `AbstractToolkit`s** (FEAT-207),
each initialized once with its shared registry — never instantiate skill tools
individually:

- **`SkillFileToolkit`** — file-based skills, shares a `SkillFileRegistry`.
  Tools: `list_skill_commands` (live listing of skills with descriptions and
  `/trigger` commands), `load_skill` (body + asset manifest),
  `read_skill_asset` (sandboxed reader for a composite skill's bundled asset;
  path-traversal rejected, `SKILL.md` reserved for `load_skill`),
  `save_learned_skill` (only when a `learned_dir` is configured).
- **`SkillRegistryToolkit`** — DB-backed skill registry, shares a
  `SkillRegistry` store + `agent_id`. Tools: `search_skills`, `read_skill`,
  `list_skills`, and the write tools `document_skill` / `update_skill` (exposed
  only when `include_write_tools=True`).

`create_skill_tools(registry, agent_id, include_write_tools, file_registry,
learned_dir)` is the factory: it instantiates both toolkits and concatenates
their `get_tools()`. `SkillRegistryMixin` wires them into a bot automatically.

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
│   └── flows/          # Orchestration: AgentCrew (crew/), AgentsFlow (flow/),
│                       #   shared DAG primitives (core/). FEAT-143/163/196.
│                       #   Legacy bots/orchestration/ and bots/flow/ removed.
├── tools/            # Tool definitions and toolkits (AbstractTool, AbstractToolkit)
├── skills/           # On-demand skills: file/composite discovery + two
│                     #   AbstractToolkits — SkillFileToolkit (file-based) and
│                     #   SkillRegistryToolkit (DB store). See Core Abstractions.
├── loaders/          # Document loaders for RAG
├── embeddings/       # base/registry/catalog/matryoshka (base classes stay in core)
│                     #   concrete backends (google/huggingface/openai) ship from
│                     #   ai-parrot-embeddings via PEP 420 namespace merging;
│                     #   import paths are unchanged: from parrot.embeddings.X import Y
├── stores/           # AbstractStore + dispatch (supported_stores) + shared models
│                     #   (Document, SearchResult, StoreConfig, DistanceStrategy) —
│                     #   concrete vector-store backends (pgvector/milvus/arango/
│                     #   bigquery/faiss_store) ship from ai-parrot-embeddings.
│                     #   Sub-packages kb/, parents/, utils/ stay in core.
│                     #   Import paths unchanged: from parrot.stores.X import Y
├── rerankers/        # AbstractReranker + factory + lazy __getattr__ (core)
│                     #   concrete rerankers (local/llm) ship from
│                     #   ai-parrot-embeddings; import paths unchanged.
├── handlers/         # HTTP handlers (aiohttp-based)
├── memory/           # Conversation memory (Redis-backed)
└── integrations/     # Telegram, MS Teams, Slack, MCP
```

### ai-parrot-embeddings (satellite package — FEAT-201)

Concrete backend implementations live in a sibling distribution that
contributes to the same `parrot.*` namespace via **PEP 420 implicit
namespace packages**:

```
packages/ai-parrot-embeddings/src/parrot/
├── embeddings/   google.py, huggingface.py, openai.py
├── stores/       postgres.py, pgvector.py, milvus.py, arango.py, bigquery.py, faiss_store.py
└── rerankers/    local.py, llm.py
```

Install with: `pip install ai-parrot-embeddings[pgvector,milvus,huggingface]`
or via the rewritten host meta-extra: `pip install ai-parrot[all]`.
See `docs/migration/feat-201-ai-parrot-embeddings.md` for migration details.

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
- `parrot/bots/flows/` — AgentCrew + AgentsFlow DAG execution
- `parrot/memory/` — Redis-based conversation memory
- `parrot/integrations/mcp/` — MCP server implementation
- `parrot/tools/` — Tool definitions and toolkits
- `parrot/integrations/` — Platform integrations (Whatsapp, Telegram, Slack, MS Teams)