---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: DatabaseAgent Homologation

**Date**: 2026-05-12
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`DatabaseAgent` (`packages/ai-parrot/src/parrot/bots/database/agent.py:33`, 415 LOC)
is structurally behind the current AI-Parrot agent conventions, while the legacy
`AbstractDBAgent` (`packages/ai-parrot/src/parrot/bots/database/abstract.py:54`,
3071 LOC) still exists in parallel — fragmenting the codebase and confusing
downstream consumers.

Concrete gaps in the current `DatabaseAgent`:

- **No `PromptBuilder` integration.** It inherits directly from `AbstractBot`
  and renders prompts through a single `string.Template` against the legacy
  `DB_AGENT_PROMPT` constant (`agent.py:346`). `PandasAgent` was already
  migrated to composable layers via `PromptBuilder.default()` plus
  domain-specific layers (`bots/data.py:305–311`). The two agents now disagree
  on how prompts are assembled.
- **`ask()` never calls the LLM.** `DatabaseAgent.ask()` (lines 154–247) only
  runs route + `toolkit.execute_query()` + a text formatter. No `client.ask()`
  call exists. The agent is, in practice, a router-with-formatting and not an
  LLM-backed agent at all.
- **`QueryRetryConfig` is unwired.** Both `QueryRetryConfig`
  (`database/retries.py:17`) and `SQLRetryHandler` (`retries.py:101`) exist
  but are never instantiated or referenced from `agent.py`. The
  `enable_retry: bool = True` parameter on `ask()` is dead.
- **`get_default_components(user_role)` is unused at the agent layer.** The
  helper exists at `database/models.py:446` but `DatabaseAgent.ask()` never
  invokes it; instead it falls back to whatever the router decided.
- **`database/prompts.py` is not in `PromptBuilder` format.** Five legacy
  `$placeholder` templates (`prompts.py:1, 47, 58, 90, 123`) — none wrapped
  as `PromptLayer` objects.
- **No structured output contract.** `PandasAgent` returns a strict
  `PandasAgentResponse` (`bots/data.py:138`) via `StructuredOutputConfig`.
  `DatabaseAgent` returns an unstructured `AIMessage` whose content is a
  string-formatted blob (`agent.py:415`).
- **Useful methods trapped in deprecated class.** `AbstractDBAgent` carries
  ~16 utility methods (explain-plan formatting, optimization-tip generation,
  query examples, schema docs, SQL extraction, type simplification, etc.)
  that have no equivalent in the toolkit layer. They are useful but
  inaccessible to the new agent.
- **Backwards-compat drag.** The legacy `AbstractDBAgent` is still imported
  by exactly one file — `examples/database/base.py:3` — which itself is
  partially broken (imports a non-existent `SQLAgent`). No production code
  uses `AbstractDBAgent`.

**Who is affected**: AI-Parrot maintainers and downstream consumers of
`DatabaseAgent` (`handlers/database/helpers.py:24`, `parrot/__init__.py`
exports, `tests/manager/test_bot_cleanup_lifecycle.py`).

**Why now**: `PandasAgent` migration set the template; running with two
incompatible agent patterns is a maintenance trap.

---

## Constraints & Requirements

- **Async-first**: all DB operations remain async; no blocking I/O.
- **Vendor-agnostic**: agent must work with any `AbstractClient` LLM provider
  (OpenAI, Anthropic, Google, Groq, etc.) — same as today.
- **Multi-toolkit support preserved**: `DatabaseAgent` must continue to
  accept a list of `DatabaseToolkit` instances and route across them via
  `SchemaQueryRouter` (`database/router.py`).
- **`AbstractBot` lifecycle compatibility**: `configure()` / `cleanup()`
  contracts and the `handlers/database/helpers.py` lookup (which uses
  `isinstance(bot, DatabaseAgent)`) must keep working.
- **No backwards-compat shim** for `AbstractDBAgent` — hard delete is acceptable.
- **Structured output is mandatory** for the default `ask()` path: must return
  a `QueryResponse` Pydantic model carrying `data`, `query`, and
  `explanation` (alignment with `PandasAgentResponse`).
- **Retry semantics**: when a toolkit `execute_query` raises a retryable
  error, the toolkit-level `SQLRetryHandler` enriches the context (sample
  data); the agent re-asks the LLM with that context until `max_retries`.
- **Per `feedback_bots_vs_agents.md`**: `DatabaseAgent` is a concrete agent
  and should keep its `@register_agent` decorator if it has one (it does not
  currently — verify in spec); the abstract base lives in `bots/database/`.

---

## Options Explored

### Option A: BasicAgent + PromptBuilder + Internal DatabaseAgentToolkit

Mirror the `PandasAgent` pattern end-to-end.

- Change base class from `AbstractBot` → `BasicAgent` (`bots/agent.py:37`).
  Inherits `create_system_prompt`, conversation memory, `_build_vector_context`,
  `_on_pre_ask`, `configure_llm`, structured-output plumbing, tool wiring.
- Define a module-level `_build_database_prompt_builder()` factory that
  starts from `PromptBuilder.default()` and adds DB-specific layers:
  - `IDENTITY_LAYER` (already in default) carries `$role`, `$backstory`.
  - New `DATABASE_CONTEXT_LAYER` — REQUEST phase — renders the toolkit
    inventory (databases, schemas, types) per call.
  - New `DATABASE_SAFETY_LAYER` — CONFIGURE phase — ports the "CRITICAL
    INSTRUCTIONS" block from `DB_AGENT_PROMPT` lines 32–40.
  - New `SCHEMA_GROUNDING_LAYER` — REQUEST phase — injects the schema
    excerpts discovered for the current query (replaces `$vector_context`
    in the legacy template).
  - New `DATABASE_INSTRUCTIONS_LAYER` — CONFIGURE phase — operating
    principles + tool-use protocol (the parts of `DB_AGENT_PROMPT` that
    aren't safety).
  - Reuse `SQL_DIALECT_LAYER` (`prompts/domain_layers.py:29`) — already
    exists.
- Set `_prompt_builder = _build_database_prompt_builder()` as a class
  attribute (same shape as PandasAgent at `data.py:330`).
- Rewrite `ask()` to follow the `PandasAgent.ask()` shape (`data.py:905`):
  build context → build system prompt via `create_system_prompt` →
  `client.ask(structured_output=StructuredOutputConfig(output_type=QueryResponse))`
  → unpack `response.output` into the returned `AIMessage`.
- Define `QueryResponse(BaseModel)` in `database/models.py` with fields
  `explanation: str`, `query: Optional[str]`, `data: Optional[PandasTable]`,
  `data_variable: Optional[str]`, `data_variables: Optional[List[str]]`.
  Reuse `PandasTable` from `bots/data.py:44` (already split-format-safe).
- Add `DatabaseAgent.get_default_components(role)` instance method that
  delegates to the module-level helper at `models.py:446` (user-requested:
  both surfaces).
- Create a new internal toolkit `DatabaseAgentToolkit` in
  `bots/database/toolkits/_internal.py` that captures **only the MISSING
  methods** identified in research (16 helpers — see Code Context). Methods
  exposed as `@tool` functions so the LLM can call them when relevant:
  `format_explain_plan`, `generate_optimization_tips`, `generate_examples`,
  `extract_sql_from_response`, `simplify_column_type`, etc.
- Wire `QueryRetryConfig` into the toolkit base. When `execute_query`
  raises a retryable exception, `SQLRetryHandler.retry_query` fetches
  sample data, attaches it to a `RetryContext` object, and the agent
  re-asks the LLM with that context up to `max_retries`.
- Delete `bots/database/abstract.py` (3071 LOC) and update
  `examples/database/base.py` to use `DatabaseAgent` directly.

✅ **Pros:**
- Single agent pattern across the codebase (Pandas + Database identical
  shape). Easier mental model for contributors.
- Inherits 6+ context-building helpers from `BasicAgent`/`Chatbot`/`BaseBot`
  for free — no reinvention.
- Structured output unlocks frontend rendering (the same `outputs/formats/`
  pipeline that handles `PandasAgentResponse` already understands
  `data`/`explanation`/`data_variable`).
- Hard-delete `AbstractDBAgent` removes 3000+ LOC of dead-end code.
- Composable layers let consumers swap individual pieces
  (`builder.remove("tools")`, custom safety layer for read-only deployments,
  etc.) without forking the whole prompt.

❌ **Cons:**
- Base-class change ripples through MRO — any consumer that
  `isinstance`-checks against `AbstractBot` continues to work (Liskov), but
  consumers that introspect `system_prompt_template` see a new path.
- `BasicAgent` brings tools/LLM machinery that DatabaseAgent didn't need
  before — slightly heavier object. Worth it for the homogeneity.
- Two new layer constants land in `prompts/domain_layers.py`. Bigger file.
- Migrating 16 MISSING methods into a new toolkit is non-trivial; the
  spec phase needs to lock the exact list (already covered by user
  decision: "only what's missing from existing toolkits").

📊 **Effort:** **Medium-High** (single-week feature: ~3 days code, ~1 day
example + cleanup).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic >=2` | `QueryResponse`, `PandasTable` reuse | already a project dep |
| `navconfig` | Example credentials path | already a project dep; user-requested |
| `querysource.conf.async_database_url` | Example DSN | already used in `examples/db/pg.py:14` |

🔗 **Existing Code to Reuse:**
- `parrot/bots/prompts/builder.py:20` — `PromptBuilder` core.
- `parrot/bots/prompts/layers.py:50` — `PromptLayer` dataclass.
- `parrot/bots/prompts/domain_layers.py:29` — `SQL_DIALECT_LAYER` (drop in
  as-is for DB dialect hint).
- `parrot/bots/prompts/domain_layers.py:67` — `STRICT_GROUNDING_LAYER`
  (used by PandasAgent — reuse for DB grounding).
- `parrot/bots/data.py:44` — `PandasTable` model (reuse for `QueryResponse.data`).
- `parrot/bots/data.py:305` — `_build_pandas_prompt_builder` (template for
  `_build_database_prompt_builder`).
- `parrot/bots/data.py:905` — `PandasAgent.ask()` (template for
  `DatabaseAgent.ask()`).
- `parrot/models/outputs.py:72` — `StructuredOutputConfig`.
- `parrot/bots/database/retries.py:17` — `QueryRetryConfig`, `SQLRetryHandler`.
- `parrot/bots/database/models.py:446` — `get_default_components` helper.
- `parrot/bots/database/router.py` — `SchemaQueryRouter` (keep as-is).
- `parrot/bots/database/toolkits/` — entire toolkit hierarchy (keep as-is;
  add `_internal.py` only).

---

### Option B: Stay on AbstractBot, swap prompts only

Minimal-disturbance refactor.

- Keep `class DatabaseAgent(AbstractBot)`.
- Replace the `string.Template` rendering at `agent.py:345–357` with a
  `PromptBuilder` field constructed on `__init__`.
- Convert each `DB_AGENT_PROMPT` block into a layer, but keep the rest of
  the agent (routing, formatting, no LLM call) intact.
- Bolt the missing AbstractDBAgent helpers directly onto `DatabaseAgent`
  as private methods (no new toolkit).
- Implement `ask()` to call the LLM in a separate dedicated method
  (`_invoke_llm`) but preserve the current router/formatter path.

✅ **Pros:**
- Smallest surface-area change. Existing `isinstance(bot, DatabaseAgent)`
  call sites untouched.
- Faster to ship; doesn't touch base class.

❌ **Cons:**
- Doesn't fix the structural divergence from `PandasAgent`. Two agents
  continue to use different base classes and lifecycle patterns.
- Reimplements (poorly) the conversation-memory / vector-context plumbing
  that `BasicAgent` already provides. Future drift guaranteed.
- Methods piled directly on `DatabaseAgent` (no internal toolkit) means
  the LLM can't call them as tools — they remain inert helpers.
- Goes against `feedback_bots_vs_agents.md` philosophy (concrete agents
  inherit; the base layer is `AbstractBot`/`BasicAgent`).

📊 **Effort:** **Low-Medium** (~2 days).

📦 **Libraries / Tools:** same as Option A.

🔗 **Existing Code to Reuse:** same files as Option A, but `_build_pandas_prompt_builder` is studied, not mirrored.

---

### Option C: Two-phase migration with a thin shim

Land Option A behind a feature gate so callers can opt in per release.

- Step 1 (this feature): keep `DatabaseAgent` as it is, add
  `DatabaseAgentV2(BasicAgent)` with the new shape alongside it. Update
  `handlers/database/helpers.py` to accept either class via a `Union`.
- Step 2 (follow-up feature): flip the export so `DatabaseAgent` is the
  alias for V2, deprecate V1 with a warning.
- Step 3: delete V1 + `AbstractDBAgent` together.

✅ **Pros:**
- Lowest blast radius per merge. Three small PRs instead of one larger one.
- Provides a window to spot regressions in dependent repositories before
  hard-deleting anything.

❌ **Cons:**
- Three feature cycles of overhead for what's already a low-risk migration
  (only one external file — already broken — imports the legacy class).
- Goes against `CLAUDE.md` "no backwards-compat hacks" guidance and the
  user's Round-2 directive ("hard delete").
- Doubles the agent count in the registry for the duration of the migration
  — confusing for consumers.

📊 **Effort:** **High** (~3× the wall-clock of Option A across three
features).

📦 **Libraries / Tools:** same.

🔗 **Existing Code to Reuse:** same.

---

## Recommendation

**Option A** is recommended.

The user's Round-1 and Round-2 answers already pre-select this shape
(`BasicAgent` base, triage-and-port methods into a new internal toolkit
covering only what's missing, `PandasTable + data_variable` structured
output, toolkit-level retry, hard delete of `AbstractDBAgent`). What the
brainstorm adds is the layer decomposition and the
`_build_database_prompt_builder` factory shape so the spec phase has a
concrete starting point.

The tradeoff being accepted: `BasicAgent` is a heavier base than
`AbstractBot`, and the change touches the MRO. The payoff: structural
parity with `PandasAgent`, free conversation memory + vector context +
structured output, and the death of 3000+ LOC of legacy code in a single
PR. Option B's "minimum-disturbance" framing is illusory because it
postpones a divergence cost that compounds with every new agent. Option C
trades blast radius for cycle time, but with only one (broken) external
consumer of `AbstractDBAgent`, the blast radius is already nil.

---

## Feature Description

### User-Facing Behavior

A consumer instantiates `DatabaseAgent` with one or more toolkits (a
`PostgresToolkit` is the canonical default in the example) and a
`QueryRetryConfig`. They call `await agent.configure()` and then
`await agent.ask("show me the top 10 customers by revenue")`.

The agent returns an `AIMessage` whose `.output` is a `QueryResponse`
Pydantic model:

```python
class QueryResponse(BaseModel):
    explanation: str
    query: Optional[str]                  # SQL/DSL the agent ran
    data: Optional[PandasTable]           # inline rows when ≤10 rows
    data_variable: Optional[str]          # variable name for >10 rows
    data_variables: Optional[List[str]]   # multi-dataset case
```

For multi-toolkit setups, the agent's `SchemaQueryRouter` selects the
target database; the user does not need to know which toolkit handled
the query.

The `outputs/formats/` pipeline already understands the
`explanation`/`data`/`data_variable` shape (it was built for
`PandasAgentResponse`) — frontend rendering "just works" without
DatabaseAgent-specific format handlers.

### Internal Behavior

1. **Init**: `DatabaseAgent` inherits from `BasicAgent`. Sets
   `_prompt_builder` to a builder produced by
   `_build_database_prompt_builder()`.
2. **Configure**: `configure()` calls `super().configure()` to set up
   memory + LLM + tools; then runs the existing toolkit start-up loop
   (cache partitions, `SchemaQueryRouter` registration). Calls
   `self._prompt_builder.configure({...})` with static vars (role,
   backstory, allowed dialects).
3. **Ask**: `ask(query, …)` flow, ported from `PandasAgent.ask()`:
   - Resolve user role; if `output_components` is `None`, call
     `self.get_default_components(role)` which delegates to the module
     helper.
   - Route the query: `route = await self.query_router.route(...)`.
   - Build vector/user/KB context via inherited helpers.
   - If `route.needs_metadata_discovery`, call
     `target_toolkit.search_schema(query)` and inject the YAML into the
     `SCHEMA_GROUNDING_LAYER` REQUEST context.
   - Render the system prompt with `self.create_system_prompt(...)` (uses
     the prompt builder under the hood).
   - Call `client.ask(prompt=query, system_prompt=…,
     structured_output=StructuredOutputConfig(output_type=QueryResponse),
     use_tools=True)`.
   - The LLM may call any tool registered by the toolkits, plus the new
     `DatabaseAgentToolkit` helpers (`format_explain_plan`, etc.).
   - Map `response.output: QueryResponse` onto the returned `AIMessage`
     (the same pattern at `data.py:1100`).
4. **Retry**: When `target_toolkit.execute_query` raises a retryable
   exception, the toolkit's `SQLRetryHandler` fetches sample data and
   attaches it to the agent's pre-LLM context for the next iteration.
   Retry loop is bounded by `QueryRetryConfig.max_retries` (default 3).

### Edge Cases & Error Handling

- **Toolkit start fails during `configure()`**: log warning, continue with
  remaining toolkits (current behavior — `agent.py:132`).
- **No toolkits registered**: `ask()` returns an `AIMessage` with an
  explanatory error in `QueryResponse.explanation` and `query=None`,
  `data=None`.
- **LLM doesn't honour structured output**: `client.ask` already handles
  retries on schema-mismatch — defer to that. If the final response is
  not a `QueryResponse`, fall through to a free-text `AIMessage` with
  `is_structured=False`.
- **Retry exhausted**: final `QueryResponse.explanation` documents the
  error chain; `query` carries the last attempted SQL; `data=None`.
- **Schema-search returns nothing**: pass an empty
  `SCHEMA_GROUNDING_LAYER`; let the LLM ask for clarification.
- **Multi-statement / DDL query**: existing
  `SQLToolkit._check_query_safety` (per research,
  `toolkits/sql.py:287`) blocks unsafe statements; agent surfaces the
  rejection through `QueryResponse.explanation`.
- **Big result sets**: when row count > 10, the LLM is instructed (via
  `DATABASE_INSTRUCTIONS_LAYER`) to set `data_variable` and skip the
  inline `data`. The agent fetches the variable from the tool's local
  scope, identical to `PandasAgent._inject_multi_data_from_variables`
  (`data.py:1115`).

---

## Capabilities

### New Capabilities
- `database-agent-prompt-builder`: composable layer stack for `DatabaseAgent`.
- `database-agent-structured-output`: `QueryResponse` Pydantic contract.
- `database-agent-internal-toolkit`: `DatabaseAgentToolkit` exposing the
  formerly-trapped AbstractDBAgent utilities.
- `database-agent-retry-loop`: agent-level integration of
  `QueryRetryConfig` + `SQLRetryHandler`.
- `database-agent-default-components`: `get_default_components` method on
  the agent + helper-level integration in `ask()`.

### Modified Capabilities
- (None — this is the first formal capability registration for
  `DatabaseAgent`.)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/database/agent.py` | rewrites (base class + ask) | from `AbstractBot` to `BasicAgent`; new prompt builder; LLM-backed `ask()`. |
| `parrot/bots/database/abstract.py` | **deleted** | 3071 LOC removed. |
| `parrot/bots/database/__init__.py` | modified | drop `AbstractDBAgent` from package surface (it isn't currently exported, but the import in `examples/database/base.py` proves it leaks); export `QueryResponse`. |
| `parrot/bots/database/prompts.py` | rewritten as layers | the five `$placeholder` constants become four `PromptLayer` instances (`DATABASE_CONTEXT_LAYER`, `DATABASE_SAFETY_LAYER`, `SCHEMA_GROUNDING_LAYER`, `DATABASE_INSTRUCTIONS_LAYER`). Keep the legacy constants for one release with a `# DEPRECATED` comment? — **No**, per Round-2: hard delete. |
| `parrot/bots/database/toolkits/_internal.py` | **new** | houses migrated MISSING helpers as `@tool` methods. |
| `parrot/bots/database/retries.py` | minor | no API change; just consumed by the agent now. |
| `parrot/bots/database/models.py` | extended | add `QueryResponse` Pydantic model. |
| `parrot/bots/prompts/domain_layers.py` | extended | add 3 DB-specific layers (DATABASE_CONTEXT, DATABASE_SAFETY, DATABASE_INSTRUCTIONS); `SCHEMA_GROUNDING_LAYER` could live in `database/prompts.py` since it's REQUEST-phase and DB-specific. Spec phase to choose. |
| `parrot/handlers/database/helpers.py` | none | uses `isinstance(bot, DatabaseAgent)` — Liskov holds. |
| `tests/manager/test_bot_cleanup_lifecycle.py` | verify | re-run after rebase; no API change expected. |
| `examples/database/base.py` | rewritten | switch to `DatabaseAgent` + `PostgresToolkit`, mirror the new example script. |
| `examples/db/pg.py` | unchanged or replaced | imports `parrot.bots.db.sql.SQLAgent` — this path is broken anyway; the new comprehensive example supersedes it. |
| `examples/database/{NEW}` | **new** | comprehensive script using `DatabaseAgent` + navconfig + `async_database_url`. |

---

## Code Context

### User-Provided Code

No code was pasted during discovery — the user described requirements in
prose. All references below are from the verified codebase research pass.

### Verified Codebase References

#### Classes & Signatures

```python
# packages/ai-parrot/src/parrot/bots/database/agent.py:33
class DatabaseAgent(AbstractBot):
    _default_temperature: float = 0.0       # line 50
    max_tokens: int = 8192                   # line 51
    system_prompt_template = DB_AGENT_PROMPT # line 52

    def __init__(
        self,
        name: str = "DatabaseAgent",
        toolkits: Optional[List[DatabaseToolkit]] = None,
        default_user_role: UserRole = UserRole.DATA_ANALYST,
        vector_store: Optional[AbstractStore] = None,
        redis_url: Optional[str] = None,
        system_prompt_template: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...                           # line 54

    async def configure(self, app: Any = None) -> None: ...  # line 87
    async def cleanup(self) -> None: ...                     # line 141
    async def ask(self, query: str, **kwargs: Any) -> AIMessage: ...  # line 154
```

```python
# packages/ai-parrot/src/parrot/bots/agent.py:37
class BasicAgent(Chatbot, NotificationMixin):
    system_prompt_template: str = AGENT_PROMPT  # line 78
    async def create_system_prompt(self, **kwargs) -> str: ...  # line 1179
```

```python
# packages/ai-parrot/src/parrot/bots/prompts/builder.py:20
class PromptBuilder:
    @classmethod
    def default(cls) -> PromptBuilder: ...   # line 45
    @classmethod
    def agent(cls) -> PromptBuilder: ...     # line 91
    def add(self, layer: PromptLayer) -> PromptBuilder: ...     # line 116
    def remove(self, name: str) -> PromptBuilder: ...           # line 128
    def configure(self, context: Dict[str, Any]) -> None: ...   # line 184
    def build(self, context: Dict[str, Any]) -> str: ...        # line 204
```

```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py:50
@dataclass(frozen=True)
class PromptLayer:
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase
    condition: Optional[Callable]
    required_vars: Optional[List[str]]

# class LayerPriority(IntEnum):  # line 22
#   IDENTITY=10, PRE_INSTRUCTIONS=15, SECURITY=20, KNOWLEDGE=30,
#   USER_SESSION=40, TOOLS=50, OUTPUT=60, BEHAVIOR=70, CUSTOM=80

# class RenderPhase(str, Enum):  # line 35
#   CONFIGURE = "configure"      # line 46
#   REQUEST   = "request"        # line 47
```

```python
# packages/ai-parrot/src/parrot/bots/data.py:44
class PandasTable(BaseModel):
    columns: List[str]
    rows: List[List[Scalar]]

# packages/ai-parrot/src/parrot/bots/data.py:138
class PandasAgentResponse(BaseModel):
    explanation: str
    data: Optional[PandasTable] = None
    data_variable: Optional[str] = None
    data_variables: Optional[List[str]] = None
    code: Optional[Union[str, Dict[str, Any]]] = None

# packages/ai-parrot/src/parrot/bots/data.py:305
def _build_pandas_prompt_builder() -> PromptBuilder:
    builder = PromptBuilder.default()
    builder.add(DATAFRAME_CONTEXT_LAYER)
    builder.add(STRICT_GROUNDING_LAYER)
    builder.add(PANDAS_INSTRUCTIONS_LAYER)
    return builder

# packages/ai-parrot/src/parrot/bots/data.py:330
class PandasAgent(BasicAgent):
    _prompt_builder = _build_pandas_prompt_builder()
```

```python
# packages/ai-parrot/src/parrot/models/outputs.py:72
@dataclass
class StructuredOutputConfig:
    output_type: type
    format: OutputFormat = OutputFormat.JSON
    custom_parser: Optional[Callable[[str], Any]] = None
```

```python
# packages/ai-parrot/src/parrot/bots/database/retries.py:17
class QueryRetryConfig:
    def __init__(
        self,
        max_retries: int = 3,
        retry_on_errors: Optional[List[str]] = None,
        sample_data_on_error: bool = True,
        max_sample_rows: int = 3,
        database_type: str = "sql",
    ): ...

# packages/ai-parrot/src/parrot/bots/database/retries.py:101
class SQLRetryHandler(RetryHandler):
    async def retry_query(self, query: str, error: Exception, attempt: int) -> Optional[str]: ...  # line 208
```

```python
# packages/ai-parrot/src/parrot/bots/database/models.py:205
class QueryExecutionResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    row_count: int = 0
    execution_time_ms: float
    columns: List[str] = Field(default_factory=list)
    query_plan: Optional[str] = None
    error_message: Optional[str] = None
    schema_used: str
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

# packages/ai-parrot/src/parrot/bots/database/models.py:446
def get_default_components(user_role: UserRole) -> OutputComponent: ...
```

#### Verified Imports

```python
from parrot.bots.agent import BasicAgent                          # agent.py:37
from parrot.bots.prompts.builder import PromptBuilder             # builder.py:20
from parrot.bots.prompts.layers import (
    PromptLayer, LayerPriority, RenderPhase,
)                                                                  # layers.py:22,35,50
from parrot.bots.prompts.domain_layers import (
    SQL_DIALECT_LAYER, STRICT_GROUNDING_LAYER,
)                                                                  # domain_layers.py:29,67
from parrot.bots.data import PandasTable                           # data.py:44
from parrot.models.outputs import StructuredOutputConfig           # outputs.py:72
from parrot.bots.database.retries import QueryRetryConfig, SQLRetryHandler  # retries.py:17,101
from parrot.bots.database.models import (
    UserRole, OutputComponent, QueryExecutionResponse,
    get_default_components,
)                                                                  # models.py:17,26,205,446
from parrot.bots.database.toolkits import (
    DatabaseToolkit, PostgresToolkit, SQLToolkit,
)                                                                  # toolkits/__init__.py
```

#### AbstractDBAgent Method Triage (from research)

Methods on `parrot/bots/database/abstract.py` (line numbers shown), with
the disposition the spec phase will lock down. Per user direction:
**only port what's MISSING from existing toolkits.**

| Line | Method | Disposition |
|---|---|---|
| 195 | `connect_database` | COVERED — `toolkits/base.py:330` |
| 238 | `analyze_schema` | COVERED — `toolkits/base.py:266,289` |
| 263 | `get_table_metadata` | COVERED — `toolkits/base.py:266` |
| 270 | `get_schema_overview` | COVERED — `toolkits/postgres.py:177` |
| 670 | `_use_schema_search_tool` | COVERED — `toolkits/base.py:289` |
| 696 | `_discover_metadata` | COVERED — `toolkits/sql.py:90` |
| 793 | `_extract_table_name_from_query` | **PORT** to `DatabaseAgentToolkit` |
| 827 | `_generate_schema` | COVERED — `toolkits/postgres.py:573` |
| 859 | `_query_generation` | COVERED — `toolkits/sql.py:121` |
| 938 | `_is_explanatory_response` | **PORT** |
| 981 | `_execute_query_explain` | COVERED — `toolkits/sql.py:228` |
| 1047 | `_format_explain_plan` | **PORT** |
| 1265 | `_generate_query` | COVERED — `toolkits/sql.py:121` |
| 1310 | `_process_query` | COVERED — `toolkits/sql.py:163` |
| 1518 | `_format_table_documentation` | COVERED — `models.py:131` |
| 1619 | `_generate_create_table_statement` | **PORT** |
| 1668 | `_build_schema_context` | COVERED — `toolkits/base.py + postgres.py:573` |
| 1789 | `_simplify_column_type` | **PORT** |
| 1813 | `_generate_table_specific_tips` | **PORT** |
| 1855 | `_get_schema_counts_direct` | **PORT** |
| 1884 | `_validate_user_sql` | COVERED — `toolkits/sql.py:249` |
| 1922 | `_execute_query` | COVERED — `toolkits/base.py:308` |
| 2038 | `_execute_query_internal` | OBSOLETE — drop |
| 2103 | `_execute_query_safe` | COVERED — `toolkits/base.py:245` |
| 2130 | `_fix_query` | COVERED — `retries.py:208` |
| 2233 | `_format_query_history` | **PORT** |
| 2246 | `_validate_schema_security` | COVERED — `toolkits/sql.py:287` |
| 2268 | `_extract_sql_from_response` | **PORT** |
| 2323 | `_format_as_text` | **PORT** |
| 2419 | `_format_response` | **PORT** (or split per-role) |
| 2517 | `_to_structured_format` | COVERED — `QueryExecutionResponse` |
| 2541 | `_extract_performance_metrics` | **PORT** |
| 2680 | `_generate_optimization_tips` | **PORT** |
| 2802 | `_parse_tips` | **PORT** |
| 2844 | `_generate_basic_optimization_tips` | **PORT** |
| 2869 | `_extract_table_names_from_metadata` | **PORT** |
| 2878 | `_generate_examples` | **PORT** |
| 2962 | `_create_error_response` | OBSOLETE — drop (replaced by `QueryResponse`) |
| 3007 | `_update_conversation_memory` | COVERED — `AbstractBot` |

**Total to port into `DatabaseAgentToolkit`: 16 methods.**
**Drop outright: 2 methods.**
**Covered by existing layer: 21 methods.**

#### Key Attributes & Constants

- `DB_AGENT_PROMPT` → `parrot/bots/database/prompts.py:1` (to be decomposed
  into 4 layers).
- `BASIC_HUMAN_PROMPT` → `prompts.py:47` (unused except possibly in
  `AbstractDBAgent`; spec to confirm and likely drop).
- `DATA_ANALYSIS_PROMPT` → `prompts.py:58` (orphan; drop).
- `DATABASE_EDUCATION_PROMPT` → `prompts.py:90` (orphan; drop).
- `DATABASE_TROUBLESHOOTING_PROMPT` → `prompts.py:123` (orphan; drop).
- `IDENTITY_LAYER` → `prompts/layers.py:120`.
- `SQL_DIALECT_LAYER` → `prompts/domain_layers.py:29` (reuse).
- `STRICT_GROUNDING_LAYER` → `prompts/domain_layers.py:67` (reuse).

### Does NOT Exist (Anti-Hallucination)

- ~~`DatabaseAgent._prompt_builder`~~ — class attribute not present today
  (`bots/database/agent.py:33`). Spec must introduce it.
- ~~`DatabaseAgent` calls `client.ask`~~ — current `ask()` (lines 154–247)
  never invokes the LLM. Spec must add the call.
- ~~`DatabaseAgent` uses `QueryRetryConfig`~~ — class exists in
  `retries.py:17`, never instantiated by the agent. Spec wires it.
- ~~`BasicAgent._prompt_builder`~~ — set only on subclasses
  (PandasAgent at `data.py:330`); the base class doesn't define it.
- ~~`SQLAgent`~~ — referenced by `examples/database/base.py:3` but does
  not exist in `parrot/bots/database/`. The example is already broken.
- ~~`DATABASE_CONTEXT_LAYER`, `DATABASE_SAFETY_LAYER`,
  `SCHEMA_GROUNDING_LAYER`, `DATABASE_INSTRUCTIONS_LAYER`~~ — no
  database-specific `PromptLayer` constants exist in
  `prompts/domain_layers.py` or anywhere else. Spec must create them.
- ~~`QueryResponse`~~ — does not exist in `database/models.py` or
  elsewhere. Spec must add it.
- ~~`DatabaseAgentToolkit`~~ — no such class. Spec creates it at
  `bots/database/toolkits/_internal.py`.
- ~~`AbstractDBAgent` exported from `parrot.bots.database`~~ — not in
  `__init__.py`'s `__all__` (verified `__init__.py:34–49`), yet
  `examples/database/base.py` successfully imports it because Python
  resolves the attribute via the module file. Hard delete is safe; the
  example must be rewritten.

---

## Parallelism Assessment

- **Internal parallelism**: Limited. Most of the changes converge on a
  single file (`bots/database/agent.py`) plus its tightly-coupled
  neighbours (`prompts.py`, `models.py`, `toolkits/_internal.py`). The
  example script and the AbstractDBAgent deletion are the only pieces
  that can run in genuine parallel.
- **Cross-feature independence**: Should not conflict with active SDD
  work. `PandasAgent` is the only adjacent agent and it lives in
  `bots/data.py` (separate file). No in-flight spec touches
  `bots/database/`. (Verify in `/sdd-status` during the spec phase.)
- **Recommended isolation**: **per-spec** (single worktree, all tasks
  sequential).
- **Rationale**: The tasks form a dependency chain — `QueryResponse`
  model must exist before the structured-output wiring; the layer
  constants must exist before `_build_database_prompt_builder`; the
  toolkit must exist before the agent registers it; the example needs
  all of the above. Splitting into multiple worktrees creates merge
  friction with negligible parallelism gain.

---

## Open Questions

- [x] Where should the new database-specific `PromptLayer` constants live
  — in `parrot/bots/prompts/domain_layers.py` (alongside the existing
  domain layers, consistent placement) or in a new module
  `parrot/bots/database/prompt_layers.py` (DB-scoped, keeps generic
  layers file cleaner)? — *Owner: Jesus Lara*: or in existing `parrot/bots/database/prompts.py`
- [x] Should `QueryResponse.data` reuse `PandasTable` directly, or wrap
  it in a thin `QueryDataset` model that also carries `row_count`,
  `execution_time_ms`, and `columns`? Wrapper adds DB-specific metadata
  at the cost of one indirection. — *Owner: Jesus Lara*: wrap a thin `QueryDataset` model
- [x] Does the new example script demonstrate single-toolkit Postgres
  only (matching the existing `examples/db/pg.py` shape), or should it
  also include a BigQuery toolkit to demonstrate multi-toolkit routing?
  User answered **single-toolkit + navconfig** in Round 2 — closing
  with that, but spec can revisit if a second example is wanted. —
  *Owner: Jesus Lara*: single-toolkit Postgres only; multi-toolkit
  example deferred to a follow-up: Multi-toolkit routing support.
- [x] How aggressively should the LLM call `DatabaseAgentToolkit.*`
  tools? The methods are useful but expensive (extra LLM round-trips).
  Default: register them but gate via the existing role/intent system
  (only enable `generate_optimization_tips` when
  `OutputComponent.OPTIMIZATION_TIPS` is in the route). — *Owner: Jesus Lara*: Agree with defaults.
- [x] After deletion of `AbstractDBAgent`, do we need a compatibility
  release note for downstream Navigator consumers, or is dev-branch
  documentation enough? — *Owner: Jesus Lara*: release note.
