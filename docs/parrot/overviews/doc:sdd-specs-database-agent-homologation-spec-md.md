---
type: Wiki Overview
title: 'Feature Specification: DatabaseAgent Homologation'
id: doc:sdd-specs-database-agent-homologation-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 415 LOC) is structurally behind the rest of the AI-Parrot agent fleet,
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.bots.data
  rel: mentions
- concept: mod:parrot.bots.database
  rel: mentions
- concept: mod:parrot.bots.database.cache
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.retries
  rel: mentions
- concept: mod:parrot.bots.database.router
  rel: mentions
- concept: mod:parrot.bots.database.toolkits
  rel: mentions
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.domain_layers
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: DatabaseAgent Homologation

**Feature ID**: FEAT-164
**Date**: 2026-05-12
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.5.x (current dev cycle)

---

## 1. Motivation & Business Requirements

### Problem Statement

`DatabaseAgent` (`packages/ai-parrot/src/parrot/bots/database/agent.py:33`,
415 LOC) is structurally behind the rest of the AI-Parrot agent fleet,
while the legacy `AbstractDBAgent`
(`packages/ai-parrot/src/parrot/bots/database/abstract.py:54`, 3071 LOC)
still exists in parallel. Concrete gaps:

- **No `PromptBuilder` integration.** Today's agent renders prompts
  through a single `string.Template` against the legacy `DB_AGENT_PROMPT`
  constant (`agent.py:346`). `PandasAgent` was already migrated to
  composable layers via `PromptBuilder.default()` plus domain layers
  (`bots/data.py:305–311`). The two agents disagree on prompt assembly.
- **`ask()` never calls the LLM.** `DatabaseAgent.ask()` (`agent.py:154–247`)
  only runs route + `toolkit.execute_query()` + a text formatter. No
  `client.ask()` call exists. The agent is, in practice, a
  router-with-formatting and not an LLM-backed agent.
- **`QueryRetryConfig` is unwired.** Both `QueryRetryConfig`
  (`retries.py:17`) and `SQLRetryHandler` (`retries.py:101`) exist but
  are never instantiated from `agent.py`. The `enable_retry: bool = True`
  parameter on `ask()` is dead.
- **`get_default_components(user_role)` is unused at the agent layer.**
  The helper exists at `database/models.py:446` but the agent never
  invokes it; it falls back to whatever the router decided.
- **`database/prompts.py` is not in `PromptBuilder` format.** Five legacy
  `$placeholder` templates — none wrapped as `PromptLayer` objects.
- **No structured output contract.** `PandasAgent` returns a strict
  `PandasAgentResponse` (`bots/data.py:138`); `DatabaseAgent` returns a
  string-formatted blob.
- **Useful methods trapped in deprecated class.** `AbstractDBAgent` carries
  ~16 utility methods (explain-plan formatting, optimization tips, query
  examples, schema docs, SQL extraction, type simplification, etc.) that
  have no equivalent in the toolkit layer.
- **Backwards-compat drag.** Legacy `AbstractDBAgent` is imported by
  exactly one file — `examples/database/base.py:3` — which itself is
  partially broken (imports a non-existent `SQLAgent`). No production
  code uses `AbstractDBAgent`.

### Goals

- Homologate `DatabaseAgent` to the `PandasAgent` shape: inherit from
  `BasicAgent`, render system prompts via a composable `PromptBuilder`
  stack, return a strict structured `QueryResponse`.
- Make `ask()` a real LLM-backed agent flow (it currently isn't).
- Wire `QueryRetryConfig` so retry behaviour is observable.
- Migrate the still-useful 16 utility methods from `AbstractDBAgent`
  into a dedicated **internal toolkit** that the LLM can call as tools
  (gated by role/intent).
- Hard-delete `AbstractDBAgent` and the orphan example
  (`examples/database/base.py`) and ship a fresh comprehensive example
  for the new shape.
- Document the change in a release note for downstream Navigator
  consumers.

### Non-Goals (explicitly out of scope)

- **Multi-toolkit example.** This feature ships a single-toolkit Postgres
  example only. A multi-toolkit (Postgres + BigQuery) demonstration is
  deferred to a follow-up feature.
- **Streaming structured output.** `ask_stream` retains its current
  delegate-to-`ask` behaviour. A first-class streaming path is
  out of scope.
- **A backwards-compat shim or `DeprecationWarning` release** for
  `AbstractDBAgent`. Rejected in brainstorm Option C — see
  `proposals/database-agent-homologation.brainstorm.md` Option C.
- **New caching layer.** The existing `CacheManager` + `CachePartition`
  (`database/cache.py:43, 373`) wiring is preserved as-is.

---

## 2. Architectural Design

### Overview

Mirror `PandasAgent` end-to-end. `DatabaseAgent` becomes a `BasicAgent`
subclass with a class-level `_prompt_builder` built by
`_build_database_prompt_builder()`. Its `ask()` follows the
`PandasAgent.ask()` flow: assemble context → render system prompt via
`create_system_prompt` → call the LLM with
`StructuredOutputConfig(output_type=QueryResponse)` → unpack the
structured output into the returned `AIMessage`.

A new **internal toolkit** at
`packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py`
captures the 16 still-useful helpers from `AbstractDBAgent` as
`@tool`-decorated methods on a `DatabaseAgentToolkit` class. The toolkit
is auto-registered by the agent during `configure()` and exposes its
tools to the LLM, gated by the existing `OutputComponent` / `QueryIntent`
routing system (e.g. `generate_optimization_tips` is only enabled when
`OutputComponent.OPTIMIZATION_TIPS` is in the route's components).

`QueryRetryConfig` is consumed at the toolkit layer: when
`SQLToolkit.execute_query` raises a retryable error, `SQLRetryHandler`
fetches sample data and the agent re-asks the LLM with the enriched
context up to `max_retries`.

`QueryResponse` wraps a new `QueryDataset` model that carries the
`PandasTable`-shaped `data`, plus DB-specific metadata (`row_count`,
`execution_time_ms`, `columns`).

Database-specific `PromptLayer` constants land in
`packages/ai-parrot/src/parrot/bots/database/prompts.py` (the file is
repurposed; its legacy `$placeholder` constants are removed).

Finally, `bots/database/abstract.py` (3071 LOC) and the broken example
`examples/database/base.py` are deleted; a fresh `examples/database/`
script using `DatabaseAgent` + `PostgresToolkit` + navconfig replaces
them.

### Component Diagram

```
                    ┌────────────────────────────┐
                    │   BasicAgent (existing)    │
                    │   bots/agent.py:37         │
                    └────────────┬───────────────┘
                                 │ inherits
                                 ▼
        ┌────────────────────────────────────────────┐
        │           DatabaseAgent (refactored)       │
        │           bots/database/agent.py           │
        │                                            │
        │   _prompt_builder ◄── PromptBuilder.default│
        │   query_router    ◄── SchemaQueryRouter    │
        │   cache_manager   ◄── CacheManager         │
        │   toolkits        ◄── List[DatabaseToolkit]│
        │   _internal_toolkit ◄── DatabaseAgentToolkit│
        │   retry_config    ◄── QueryRetryConfig     │
        └──────────┬─────────────────────┬───────────┘
                   │                     │
       configure() │                     │ ask(query, ...)
                   ▼                     ▼
    ┌──────────────────────┐   ┌────────────────────────┐
    │ Layer stack assembled│   │ build context → render │
    │ DB_CONTEXT (REQUEST) │   │ system prompt → LLM    │
    │ DB_SAFETY (CONFIG)   │   │ ask(structured_output= │
    │ DB_SCHEMA (REQUEST)  │   │   QueryResponse) →     │
    │ DB_INSTRUCT(CONFIG)  │   │ unpack into AIMessage  │
    │ SQL_DIALECT (CONFIG) │   └─────────┬──────────────┘
    └──────────────────────┘             │
                                         │ retry on retryable error
                                         ▼
                            ┌─────────────────────────┐
                            │  SQLRetryHandler        │
                            │  (toolkit-level)        │
                            │  retries.py:101         │
                            └─────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BasicAgent` (`bots/agent.py:37`) | **new base class** | `DatabaseAgent` switches from `AbstractBot` to `BasicAgent`. Liskov: `isinstance(bot, DatabaseAgent)` callsites unaffected. |
| `PromptBuilder` (`bots/prompts/builder.py:20`) | uses | `_build_database_prompt_builder()` returns `PromptBuilder.default()` + DB-specific layers. |
| `StructuredOutputConfig` (`models/outputs.py:73`) | uses | `ask()` passes `output_type=QueryResponse`. |
| `PandasTable` (`bots/data.py:44`) | wraps | `QueryDataset.data: PandasTable`. |
| `SchemaQueryRouter` (`database/router.py:28`) | uses | Routing decision drives toolkit selection + components. |
| `DatabaseToolkit` (`toolkits/base.py:78`) | uses | Unchanged contract; agent iterates `self.toolkits`. |
| `SQLToolkit` (`toolkits/sql.py:45`) | uses | Source of `execute_query`, `generate_query`, `validate_query`, etc. |
| `PostgresToolkit` (`toolkits/postgres.py:28`) | uses | Default toolkit in the example. |
| `QueryRetryConfig` / `SQLRetryHandler` (`retries.py:17, 101`) | wires | Bound to `SQLToolkit.execute_query` retries; agent observes context. |
| `CacheManager` / `CachePartition` (`cache.py:43, 373`) | unchanged | Existing partition-creation flow preserved in `configure()`. |
| `get_default_components` (`models.py:446`) | wires + duplicates surface | `DatabaseAgent.get_default_components(role)` is a thin delegator. |
| `parrot/handlers/database/helpers.py:24` | unchanged | Imports `DatabaseAgent`; uses `isinstance`. No change. |
| `parrot/__init__.py` | extends export | Add `QueryResponse`, `QueryDataset` to re-exports if `DatabaseAgent` is already exported. |
| `examples/database/base.py` | **replaced** | Hard delete; replaced with `examples/database/postgres_agent.py` (or similar). |
| `examples/db/pg.py` | left as-is | Imports a non-existent `SQLAgent` from a deprecated path; this feature does NOT fix it (out of scope). |

### Data Models

```python
# packages/ai-parrot/src/parrot/bots/database/models.py
# (new additions; existing models untouched)

class QueryDataset(BaseModel):
    """Result dataset for a single executed query.

    Wraps PandasTable with DB-specific metadata so consumers can
    distinguish a 'no results' empty table from a non-tabular response.
    """

    data: Optional[PandasTable] = Field(
        default=None,
        description="Tabular result rows; null for non-tabular responses.",
    )
    columns: List[str] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: Optional[float] = None


class QueryResponse(BaseModel):
    """Structured LLM output for DatabaseAgent.ask()."""

    explanation: str = Field(
        description="Human-readable summary of the query and its result."
    )
    query: Optional[str] = Field(
        default=None,
        description="The SQL/DSL the agent generated and executed.",
    )
    data: Optional[QueryDataset] = Field(
        default=None,
        description="Inline dataset; populated when row_count <= inline_threshold.",
    )
    data_variable: Optional[str] = Field(
        default=None,
        description="Variable name holding the result DataFrame (for large datasets).",
    )
    data_variables: Optional[List[str]] = Field(
        default=None,
        description="Multi-dataset variant; list of variable names.",
    )
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/bots/database/agent.py (rewritten)
class DatabaseAgent(BasicAgent):
    _prompt_builder = _build_database_prompt_builder()  # class attribute
    _default_temperature: float = 0.0
    max_tokens: int = 8192

    def __init__(
        self,
        name: str = "DatabaseAgent",
        toolkits: Optional[List[DatabaseToolkit]] = None,
        default_user_role: UserRole = UserRole.DATA_ANALYST,
        vector_store: Optional[AbstractStore] = None,
        redis_url: Optional[str] = None,
        retry_config: Optional[QueryRetryConfig] = None,
        **kwargs: Any,
    ) -> None: ...

    async def configure(self, app: Any = None) -> None: ...
    async def cleanup(self) -> None: ...

    async def ask(
        self,
        query: str,
        user_role: Optional[UserRole] = None,
        database: Optional[str] = None,
        context: Optional[str] = None,
        output_components: Optional[Union[str, OutputComponent]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        return_structured: bool = True,
        structured_output: Optional[Any] = None,
        **kwargs: Any,
    ) -> AIMessage: ...

    def get_default_components(
        self, user_role: Optional[UserRole] = None
    ) -> OutputComponent: ...

    async def conversation(self, question: str, **kwargs: Any) -> AIMessage: ...
    async def invoke(self, question: str, **kwargs: Any) -> AIMessage: ...
    async def ask_stream(self, question: str, **kwargs: Any): ...
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py (new)
class DatabaseAgentToolkit(AbstractToolkit):
    """LLM-facing helpers ported from AbstractDBAgent.

    Tools registered when corresponding OutputComponent flags are
    requested by the route. Each method below is exposed as a
    callable LLM tool.
    """

    @tool
    def format_explain_plan(self, plan_json: str) -> str: ...

    @tool
    def simplify_column_type(self, raw_type: str) -> str: ...

    @tool
    def extract_sql_from_response(self, response_text: str) -> str: ...

    @tool
    def extract_table_name_from_query(self, query: str) -> Optional[str]: ...

    @tool
    def extract_table_names_from_metadata(self, metadata_context: str) -> List[str]: ...

    @tool
    def generate_create_table_statement(self, table_yaml: str) -> str: ...

    @tool
    async def generate_optimization_tips(
        self, sql_query: str, query_plan: str
    ) -> List[str]: ...

    @tool
    def generate_basic_optimization_tips(
        self, sql_query: str, query_plan: str
    ) -> List[str]: ...

    @tool
    def generate_table_specific_tips(
        self, table_yaml: str
    ) -> List[str]: ...

    @tool
    async def generate_examples(
        self, schema_context: str, intent: str
    ) -> List[str]: ...

    @tool
    def extract_performance_metrics(self, explain_analyze: str) -> Dict[str, Any]: ...

    @tool
    def format_as_text(self, data: Any, components: OutputComponent) -> str: ...

    @tool
    def format_query_history(self, history: List[Dict[str, Any]]) -> str: ...

    @tool
    def parse_tips(self, response_text: str) -> List[str]: ...

    @tool
    def is_explanatory_response(self, response_text: str) -> bool: ...

    @tool
    async def get_schema_counts_direct(
        self, schema_name: str
    ) -> Tuple[int, int]: ...
```

```python
# packages/ai-parrot/src/parrot/bots/database/prompts.py (rewritten)
# Old $placeholder constants are removed. The file now exports
# database-specific PromptLayer constants.

DATABASE_CONTEXT_LAYER: PromptLayer       # priority KNOWLEDGE+5, REQUEST phase
DATABASE_SAFETY_LAYER: PromptLayer        # priority SECURITY+5, CONFIGURE phase
SCHEMA_GROUNDING_LAYER: PromptLayer       # priority KNOWLEDGE+10, REQUEST phase
DATABASE_INSTRUCTIONS_LAYER: PromptLayer  # priority PRE_INSTRUCTIONS+1, CONFIGURE phase

def _build_database_prompt_builder() -> PromptBuilder:
    """Factory mirroring _build_pandas_prompt_builder() (data.py:305)."""
    ...
```

---

## 3. Module Breakdown

### Module 1: `QueryDataset` & `QueryResponse` models
- **Path**: `packages/ai-parrot/src/parrot/bots/database/models.py`
- **Responsibility**: Add the two new Pydantic models that define the
  structured output contract. Keep existing `QueryExecutionResponse`
  untouched (toolkit-layer model — different concern).
- **Depends on**: `PandasTable` from `bots/data.py:44`.

### Module 2: Database-specific PromptLayer constants
- **Path**: `packages/ai-parrot/src/parrot/bots/database/prompts.py`
- **Responsibility**: Replace the five legacy `$placeholder` constants
  with four `PromptLayer` instances and a `_build_database_prompt_builder()`
  factory function. The DB-layer file is the home for DB-specific layers
  per resolved Open Question #1.
- **Depends on**: `PromptLayer`, `LayerPriority`, `RenderPhase`
  (`bots/prompts/layers.py`), `PromptBuilder` (`bots/prompts/builder.py`).
- **Reuses**: `SQL_DIALECT_LAYER` (`prompts/domain_layers.py:29`),
  `STRICT_GROUNDING_LAYER` (`prompts/domain_layers.py:67`).

### Module 3: `DatabaseAgentToolkit` (internal toolkit)
- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py`
- **Responsibility**: Bundle the 16 still-useful helpers from
  `AbstractDBAgent` as `@tool`-decorated methods. Inherit from
  `AbstractToolkit`. Each tool registers with the agent through the
  standard toolkit lifecycle (`start`, `stop`).
- **Depends on**: Module 1 (for return types), `AbstractToolkit`
  (`parrot/tools/...`), `OutputComponent` (`database/models.py:26`).

### Module 4: Internal-toolkit gating
- **Path**: integrated into Module 5 (`agent.py`)
- **Responsibility**: When the agent configures its LLM tool-set, only
  expose tools whose corresponding `OutputComponent` is set in the
  route's components. E.g. `generate_optimization_tips` is exposed only
  when `OutputComponent.OPTIMIZATION_TIPS` ∈ `route.components`. Resolved
  Open Question #4.
- **Depends on**: Module 3, `SchemaQueryRouter` (`router.py:28`).

### Module 5: `DatabaseAgent` rewrite
- **Path**: `packages/ai-parrot/src/parrot/bots/database/agent.py`
- **Responsibility**:
  - Change base class to `BasicAgent`.
  - Set `_prompt_builder` from Module 2.
  - Rewrite `ask()` to follow `PandasAgent.ask()` (`bots/data.py:905`)
    shape: assemble context → `create_system_prompt` →
    `client.ask(structured_output=…)` → unpack `QueryResponse` into
    `AIMessage` (mirroring `data.py:1100–1110`).
  - Add `get_default_components(role)` instance method delegating to
    `models.py:446`.
  - Accept and store `retry_config: Optional[QueryRetryConfig]`.
  - Register `DatabaseAgentToolkit` automatically during `configure()`.
- **Depends on**: Modules 1, 2, 3, 4.

### Module 6: Toolkit-level retry wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`
  (or the closest layer that owns `execute_query`)
- **Responsibility**: When `execute_query` raises an exception, consult
  the toolkit's `retry_config` (injected from the agent). If retryable,
  call `SQLRetryHandler.retry_query` for sample-data enrichment and
  surface a `RetryContext` payload to the caller. The agent uses that
  payload to re-ask the LLM up to `max_retries` times.
- **Depends on**: `QueryRetryConfig`, `SQLRetryHandler` (`retries.py:17, 101`).
- **Note**: The retry handler already exists. What's missing is the
  binding between agent and toolkit and the agent-side re-ask loop.

### Module 7: Delete `AbstractDBAgent`
- **Path**: `packages/ai-parrot/src/parrot/bots/database/abstract.py`
- **Responsibility**: Remove the entire file (3071 LOC). Drop any
  re-exports from `bots/database/__init__.py`. The file is currently
  not in `__init__.py:__all__`, but `examples/database/base.py:3`
  imports it directly — fix that import in Module 8.
- **Depends on**: Modules 3 & 5 (must land first so the methods worth
  saving are already migrated).

### Module 8: New comprehensive example
- **Path**: `packages/ai-parrot/examples/database/postgres_agent.py` (new)
- **Responsibility**: Single-toolkit Postgres script using navconfig
  + `querysource.conf.async_database_url`. Demonstrates:
  - `DatabaseAgent` instantiation with a single `PostgresToolkit`.
  - `await agent.configure()` lifecycle.
  - Three flavours of `ask()`: schema exploration, NL → SQL, raw SQL
    validation.
  - Inspecting `response.output: QueryResponse` (explanation, query,
    data, data_variable).
  - Demonstrating retry behaviour by feeding a deliberately incorrect
    column name and observing the re-ask cycle.
- **Depends on**: Modules 1–6.
- **Replaces**: `examples/database/base.py` (deleted in this module).

### Module 9: Release note
- **Path**: `packages/ai-parrot/CHANGELOG.md` (or the canonical project
  changelog; spec-phase to confirm the path during the task batch)
- **Responsibility**: Add a release-note entry for v0.5.x documenting:
  - `AbstractDBAgent` deletion.
  - `DatabaseAgent` base-class change to `BasicAgent`.
  - New `QueryResponse` structured-output contract.
  - Migration path for any downstream Navigator consumer (none known,
    but the note is required per resolved Open Question #5).
- **Depends on**: Modules 1–8 in spirit; this is the last module before
  the feature is closed.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_query_dataset_serialises_pandas_table` | 1 | Round-trip `PandasTable` → `QueryDataset` → JSON → `QueryDataset` preserves rows/columns/row_count. |
| `test_query_response_pydantic_schema_includes_explanation_query_data` | 1 | `QueryResponse.model_json_schema()` exposes the three required fields. |
| `test_query_response_data_variable_path` | 1 | `QueryResponse` accepts `data=None` + `data_variable="result_df"` without errors. |
| `test_database_prompt_builder_factory_assembles_layers` | 2 | `_build_database_prompt_builder()` returns a `PromptBuilder` whose `layer_names` include `database_context`, `database_safety`, `schema_grounding`, `database_instructions` plus the `default()` baseline. |
| `test_database_prompt_layers_render_with_minimal_context` | 2 | `builder.configure(min_static_ctx); builder.build(min_dynamic_ctx)` does not raise. |
| `test_internal_toolkit_tools_have_docstrings` | 3 | Every `@tool` method on `DatabaseAgentToolkit` carries a non-empty docstring (LLM tool-description contract). |
| `test_internal_toolkit_format_explain_plan_handles_json_string` | 3 | Smoke test for `format_explain_plan` with a representative Postgres EXPLAIN JSON. |
| `test_internal_toolkit_simplify_column_type` | 3 | `numeric(10,2)` → `numeric`, `varchar(255)` → `varchar`, `timestamp without time zone` → `timestamp`. |
| `test_internal_toolkit_gating_excludes_unrequested_tools` | 4 | Given a `RouteDecision` with `components=OutputComponent.SQL_QUERY` only, the toolkit registers `extract_sql_from_response` but not `generate_optimization_tips`. |
| `test_database_agent_inherits_basicagent` | 5 | `issubclass(DatabaseAgent, BasicAgent)` is `True`. |
| `test_database_agent_has_prompt_builder_attr` | 5 | `DatabaseAgent._prompt_builder` exists as a class attribute and is a `PromptBuilder`. |
| `test_database_agent_get_default_components_delegates` | 5 | `agent.get_default_components(UserRole.DATA_ANALYST)` equals `get_default_components(UserRole.DATA_ANALYST)` (module helper). |
| `test_database_agent_ask_calls_client_ask` | 5 | With a mocked `_llm.ask`, `DatabaseAgent.ask("hi")` invokes `client.ask(...)` with `structured_output.output_type == QueryResponse` and `use_tools=True`. |
| `test_database_agent_ask_unpacks_structured_output_into_aimessage` | 5 | Given a mocked LLM that returns a `QueryResponse`, the returned `AIMessage` carries `response.is_structured == True`, `response.response == query_response.explanation`, and `response.data` resembles `query_response.data.data` as a DataFrame. |
| `test_database_agent_ask_no_toolkits_returns_error_response` | 5 | With `toolkits=[]`, `ask()` returns an `AIMessage` whose `QueryResponse.explanation` contains an error message and `query/data` are `None`. |
| `test_sqltoolkit_retry_loop_invokes_handler_on_retryable_error` | 6 | A `SQLToolkit.execute_query` raising an `InvalidTextRepresentationError` triggers `SQLRetryHandler.retry_query` once per attempt, up to `max_retries`. |
| `test_sqltoolkit_retry_loop_skips_non_retryable_error` | 6 | A generic `ValueError` bypasses the retry handler and propagates immediately. |
| `test_abstractdbagent_deleted_from_init` | 7 | `from parrot.bots.database import AbstractDBAgent` raises `ImportError`. |
| `test_abstract_module_file_absent` | 7 | `Path('parrot/bots/database/abstract.py').exists()` is `False`. |

### Integration Tests

| Test | Description |
|---|---|

…(truncated)…
