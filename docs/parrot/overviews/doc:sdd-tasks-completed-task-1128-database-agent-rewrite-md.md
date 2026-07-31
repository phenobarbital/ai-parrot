---
type: Wiki Overview
title: 'TASK-1128: Rewrite DatabaseAgent on BasicAgent + Structured Output + Toolkit
  Gating'
id: doc:sdd-tasks-completed-task-1128-database-agent-rewrite-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Modules 4 + 5** of FEAT-164 (spec §3 "Module 4" and "Module
relates_to:
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.bots.database
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.prompts
  rel: mentions
- concept: mod:parrot.bots.database.retries
  rel: mentions
- concept: mod:parrot.bots.database.toolkits
  rel: mentions
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
---

# TASK-1128: Rewrite DatabaseAgent on BasicAgent + Structured Output + Toolkit Gating

**Feature**: FEAT-164 — DatabaseAgent Homologation
**Spec**: `sdd/specs/database-agent-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1125, TASK-1126, TASK-1127
**Assigned-to**: unassigned

---

## Context

Implements **Modules 4 + 5** of FEAT-164 (spec §3 "Module 4" and "Module
5"). This is the centrepiece of the feature.

`DatabaseAgent` currently inherits from `AbstractBot` and its `ask()` never
calls the LLM — it just routes + executes + formats. This task:

1. Switches `DatabaseAgent` to inherit from `BasicAgent`.
2. Adds `_prompt_builder = _build_database_prompt_builder()` (from
   TASK-1126) as a class attribute, mirroring `PandasAgent` at
   `bots/data.py:314`.
3. Rewrites `ask()` to be a real LLM-backed flow: build context → render
   system prompt → `self._llm.ask(structured_output=QueryResponse)` →
   unpack into `AIMessage`.
4. Adds `get_default_components(role)` as an instance method delegating
   to the module helper at `database/models.py:446`.
5. Accepts `retry_config: Optional[QueryRetryConfig]` (replacing the dead
   `enable_retry` parameter — hard rename per resolved Open Question #2).
6. Registers `DatabaseAgentToolkit` (from TASK-1127) during `configure()`
   and gates each of its 16 tools by the active `OutputComponent` flags
   (Module 4 logic).

---

## Scope

- Change base class: `class DatabaseAgent(AbstractBot)` →
  `class DatabaseAgent(BasicAgent)` at `bots/database/agent.py:33`.
- Remove the `system_prompt_template = DB_AGENT_PROMPT` line (the
  legacy template is being deleted by TASK-1126).
- Set `_prompt_builder = _build_database_prompt_builder()` as a class
  attribute.
- Rewrite `__init__` to accept `retry_config: Optional[QueryRetryConfig]
  = None` and forward unknown kwargs via `**kwargs` to `BasicAgent`.
  **Remove** `enable_retry: bool` parameter (hard rename per Open
  Question #2 resolution).
- Rewrite `ask()` per spec §2 "Architectural Design — Overview" and
  the `PandasAgent.ask()` flow at `bots/data.py:905`.
- Add `get_default_components(self, user_role)` instance method.
- In `configure()`, instantiate `DatabaseAgentToolkit()` and store as
  `self._internal_toolkit`. Compute the active toolset for an `ask()`
  request based on `route.components` (gating per Module 4 — see
  Implementation Notes).
- Preserve existing `configure()` side effects: `CacheManager.create_partition`,
  `SchemaQueryRouter.register_database`, toolkit lifecycle starts.
- Preserve `cleanup()` behaviour.
- `ask_stream` continues to delegate to `ask` (non-goal in §1).

**NOT in scope**:
- Toolkit-level retry implementation (Module 6 / TASK-1129).
- Deleting `abstract.py` (Module 7 / TASK-1130).
- New example (Module 8 / TASK-1131).
- CHANGELOG entry (Module 9 / TASK-1132).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | REWRITE | New base class, structured-output ask(), toolkit gating. |
| `packages/ai-parrot/tests/bots/database/test_database_agent.py` | CREATE or MODIFY | Add the test specifications below. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (re-verify each line numbers before use)

```python
from parrot.bots.agent import BasicAgent              # bots/agent.py:37
from parrot.bots.prompts.builder import PromptBuilder  # bots/prompts/builder.py:20
from parrot.bots.database.prompts import (
    _build_database_prompt_builder,                    # added by TASK-1126
)
from parrot.bots.database.models import (
    UserRole,                  # bots/database/models.py:17
    OutputComponent,           # bots/database/models.py:26
    QueryIntent,               # bots/database/models.py:74
    RouteDecision,             # bots/database/models.py:266
    get_default_components,    # bots/database/models.py:446
    components_from_string,    # bots/database/models.py:466
)
from parrot.bots.database import (
    QueryResponse,             # added by TASK-1125
    QueryDataset,              # added by TASK-1125
)
from parrot.bots.database.toolkits import (
    DatabaseAgentToolkit,      # added by TASK-1127
    DatabaseToolkit,           # toolkits/base.py:78
)
from parrot.bots.database.retries import (
    QueryRetryConfig,          # retries.py:17
)
from parrot.models.outputs import StructuredOutputConfig   # models/outputs.py:73
from parrot.models import AIMessage, CompletionUsage       # re-verify the exact path
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/agent.py:37
class BasicAgent(Chatbot, NotificationMixin):
    system_prompt_template: str = AGENT_PROMPT             # line ~78
    def __init__(
        self,
        name: str = "...",
        agent_id: Optional[str] = None,
        use_llm: bool = True,
        llm: Optional[Any] = None,
        tools: Optional[List[AbstractTool]] = None,
        system_prompt: Optional[str] = None,
        human_prompt: Optional[str] = None,
        use_tools: bool = True,
        instructions: Optional[str] = None,
        dataframes: Optional[Any] = None,
        **kwargs,
    ): ...                                                  # line ~80
    async def create_system_prompt(self, **kwargs) -> str: ...  # line ~1179

# packages/ai-parrot/src/parrot/bots/data.py — reference implementations
class PandasAgent(BasicAgent):                             # line 314
    _prompt_builder = _build_pandas_prompt_builder()       # class attribute
    async def ask(...) -> AIMessage:                       # line 905
        # ... assemble context, render prompt,
        # ... call self._llm.ask(structured_output=...),
        # ... unpack into AIMessage with .data, .response, .is_structured

# packages/ai-parrot/src/parrot/bots/database/agent.py — CURRENT (to be rewritten)
class DatabaseAgent(AbstractBot):                          # line 33
    _default_temperature: float = 0.0                      # line 50
    max_tokens: int = 8192                                 # line 51
    system_prompt_template = DB_AGENT_PROMPT               # line 52  ← REMOVE
    async def configure(self, app=None) -> None: ...       # line 87
    async def cleanup(self) -> None: ...                   # line 141
    async def ask(self, query, ..., enable_retry=True): ...# line 154  ← REWRITE
```

### Does NOT Exist

- ~~`BasicAgent._prompt_builder`~~ — not defined on `BasicAgent` itself.
  Only subclasses (e.g. `PandasAgent`) set it. This task MUST set it on
  `DatabaseAgent` — do not assume inheritance provides it.
- ~~`DatabaseAgent._llm.ask` is currently invoked~~ — it is not. Today's
  `ask()` is router-with-formatting only.
- ~~`DatabaseAgent.retry_config`~~ — current attribute does not exist;
  `enable_retry: bool` was a dead parameter. This task introduces
  `self.retry_config: Optional[QueryRetryConfig]`.
- ~~`DatabaseAgent.get_default_components`~~ — only the module helper
  `database/models.py:446` exists today.
- ~~`OutputComponent` per-tool tag attribute~~ — `OutputComponent` is a
  `Flag` enum at `models.py:26`; mapping it to specific toolkit methods
  is a NEW responsibility introduced by this task (see Tool Gating below).

---

## Implementation Notes

### Pattern to Follow — `ask()` body

Read `packages/ai-parrot/src/parrot/bots/data.py:905-1110` carefully.
The PandasAgent flow is the canonical template:

1. Resolve effective `user_role`, `output_components`, route via
   `SchemaQueryRouter`.
2. If `output_components` is `None`, call
   `self.get_default_components(user_role)` (acceptance criterion).
3. Assemble dynamic context (database name, schema summary, query).
4. `system = await self.create_system_prompt(**dynamic_ctx)` — this
   uses `_prompt_builder` automatically through `BasicAgent`.
5. Build `structured_output = StructuredOutputConfig(output_type=QueryResponse)`
   (unless caller overrode via `structured_output=` kwarg).
6. Compute the active tool subset (see Tool Gating below) and pass to
   `self._llm.ask(use_tools=True, tools=active_tools, ...)`.
7. Unpack the returned `QueryResponse` into an `AIMessage` mirroring
   `data.py:1100–1110`:
   - `ai_message.is_structured = True`
   - `ai_message.response = qr.explanation`
   - `ai_message.data = qr.data.data.to_dataframe()` if
     `qr.data and qr.data.data` else `None`
   - Attach the full `QueryResponse` to `ai_message.output` (same field
     `PandasAgent` uses).
8. **Fallback**: if the LLM returned free text instead of a parsed
   `QueryResponse`, return an `AIMessage` with `is_structured=False`
   wrapping the raw text (mirroring `data.py:1100–1101`).
9. **Edge case**: when `self.toolkits` is empty, return an `AIMessage`
   whose embedded `QueryResponse.explanation` is a clear error
   message and `query/data` are `None` (acceptance criterion).

### Tool Gating (Module 4 — integrated here)

Inside `configure()` build a static mapping
`_COMPONENT_TO_TOOL_NAMES: Dict[OutputComponent, set[str]]` — one entry
per `OutputComponent` flag, listing which of the 16 `DatabaseAgentToolkit`
tools are relevant for that component. Suggested mapping (refine if
spec §2 is more specific):

| OutputComponent flag | Tools to expose |
|---|---|
| `SQL_QUERY` | `extract_sql_from_response`, `extract_table_name_from_query` |
| `OPTIMIZATION_TIPS` | `generate_optimization_tips`, `generate_basic_optimization_tips`, `generate_table_specific_tips`, `extract_performance_metrics` |
| `EXPLAIN_PLAN` | `format_explain_plan`, `extract_performance_metrics` |
| `SCHEMA_DOCS` | `generate_create_table_statement`, `simplify_column_type`, `extract_table_names_from_metadata`, `get_schema_counts_direct` |
| `EXAMPLES` | `generate_examples` |
| `QUERY_HISTORY` | `format_query_history` |
| `TEXT_RESPONSE` | `format_as_text`, `is_explanatory_response`, `parse_tips` |

Inside `ask()`:
```python
active_components = route.components or default_components
exposed_tool_names: set[str] = set()
for flag in OutputComponent:
    if flag in active_components:
        exposed_tool_names |= self._component_to_tool_names.get(flag, set())
active_tools = self._internal_toolkit.tools_subset(exposed_tool_names)
```

If `AbstractToolkit` does not expose a `tools_subset(names)` helper,
filter inline by iterating the toolkit's `@tool`-decorated attributes.

### Key Constraints

- `self.logger` (inherited from `BasicAgent`) for all diagnostics — no
  `print`.
- Preserve `self._llm` attribute name (BasicAgent uses it).
- `**kwargs` pass-through to `BasicAgent.__init__` to avoid breaking
  the `handlers/database/helpers.py:24` factory.
- Don't touch any code outside `bots/database/agent.py` (and the test
  file) except its `__init__.py` re-exports if needed.

### Known Risks

- **Base-class change ripple** — `BasicAgent.__init__` accepts a
  specific kwarg set. Callers passing kwargs unknown to `BasicAgent`
  will start raising `TypeError`. Mitigation: keep `**kwargs` and audit
  `handlers/database/helpers.py:24` if integration tests start failing.
- **Structured-output reliability** — some providers occasionally return
  free text. The fallback path handles this.
- **Frontend integration** — `outputs/formats/base.py:326` reads
  `PandasAgentResponse.data` directly. Consumers that read
  `AIMessage.output.data` will now find a `QueryDataset`, not a
  `PandasTable`. Document this in the release note (TASK-1132) — not
  this task's responsibility, but be aware when implementing
  `AIMessage` unpacking.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/data.py:305–325` — prompt builder
  factory.
- `packages/ai-parrot/src/parrot/bots/data.py:314` — `_prompt_builder`
  class attribute pattern.
- `packages/ai-parrot/src/parrot/bots/data.py:905–1110` — `ask()` flow.
- `packages/ai-parrot/src/parrot/bots/database/agent.py:33–280` —
  current implementation (to be rewritten).
- `packages/ai-parrot/src/parrot/bots/database/router.py:28` —
  `SchemaQueryRouter` (unchanged contract).

---

## Acceptance Criteria

- [ ] `issubclass(DatabaseAgent, BasicAgent) is True`.
- [ ] `DatabaseAgent._prompt_builder` is a `PromptBuilder` instance at
      the class level.
- [ ] `system_prompt_template = DB_AGENT_PROMPT` line removed.
- [ ] `DatabaseAgent.__init__` accepts `retry_config:
      Optional[QueryRetryConfig] = None` and does NOT accept
      `enable_retry`.
- [ ] `DatabaseAgent.get_default_components(role)` returns the same
      value as the module helper `models.py:446`.
- [ ] `DatabaseAgent.ask()` invokes `self._llm.ask(...)` with
      `structured_output=StructuredOutputConfig(output_type=QueryResponse)`
      and `use_tools=True`.
- [ ] When the caller omits `output_components`, `ask()` calls
      `self.get_default_components(...)`.
- [ ] `DatabaseAgentToolkit` is instantiated and stored as
      `self._internal_toolkit` during `configure()`.
- [ ] LLM's tool list for a given `ask()` is a SUBSET of
      `DatabaseAgentToolkit` filtered by active `OutputComponent` flags.
- [ ] All listed unit tests pass:
      `pytest packages/ai-parrot/tests/bots/database/test_database_agent.py -v`.
- [ ] `tests/manager/test_bot_cleanup_lifecycle.py` continues to pass
      (no regression in lifecycle).
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/database/agent.py` clean.
- [ ] `mypy --strict packages/ai-parrot/src/parrot/bots/database/agent.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/database/test_database_agent.py
from unittest.mock import AsyncMock, MagicMock
import pytest
from parrot.bots.agent import BasicAgent
from parrot.bots.database import DatabaseAgent, QueryDataset, QueryResponse
from parrot.bots.database.models import OutputComponent, UserRole, get_default_components
from parrot.bots.prompts.builder import PromptBuilder
from parrot.models.outputs import StructuredOutputConfig


def test_database_agent_inherits_basicagent():
    assert issubclass(DatabaseAgent, BasicAgent)


def test_database_agent_has_prompt_builder_attr():
    assert isinstance(DatabaseAgent._prompt_builder, PromptBuilder)


def test_database_agent_get_default_components_delegates():
    agent = DatabaseAgent(toolkits=[])
    assert agent.get_default_components(UserRole.DATA_ANALYST) == \
        get_default_components(UserRole.DATA_ANALYST)


@pytest.mark.asyncio
async def test_database_agent_ask_calls_client_ask(mock_llm_client, fake_postgres_toolkit):
    """With a mocked _llm.ask, ask() invokes client.ask(structured_output=QueryResponse,
    use_tools=True)."""
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    agent._llm = mock_llm_client
    await agent.configure()
    await agent.ask("list tables")
    call_kwargs = mock_llm_client.ask.call_args.kwargs
    assert call_kwargs.get("use_tools") is True
    sout = call_kwargs.get("structured_output")
    assert isinstance(sout, StructuredOutputConfig)
    assert sout.output_type is QueryResponse


@pytest.mark.asyncio
async def test_database_agent_ask_unpacks_structured_output_into_aimessage(
    mock_llm_client, fake_postgres_toolkit
):
    qr = QueryResponse(
        explanation="ok",
        query="SELECT 1",
        data=None,
    )
    mock_llm_client.ask.return_value = MagicMock(
        is_structured=True, output=qr, response="ok", data=None,
    )
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    agent._llm = mock_llm_client
    await agent.configure()
    msg = await agent.ask("hi")
    assert msg.is_structured is True
    assert msg.response == "ok"


@pytest.mark.asyncio
async def test_database_agent_ask_no_toolkits_returns_error_response(mock_llm_client):
    agent = DatabaseAgent(toolkits=[])
    agent._llm = mock_llm_client
    await agent.configure()
    msg = await agent.ask("hi")
    qr = msg.output
    assert isinstance(qr, QueryResponse)
    assert qr.query is None and qr.data is None
    assert "no toolkit" in qr.explanation.lower() or "no database" in qr.explanation.lower()


@pytest.mark.asyncio
async def test_internal_toolkit_gating_excludes_unrequested_tools(
    mock_llm_client, fake_postgres_toolkit
):
    """Given OutputComponent.SQL_QUERY only, optimization tips tools must NOT
    appear in the tools list passed to client.ask."""
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    agent._llm = mock_llm_client
    await agent.configure()
    await agent.ask("hi", output_components=OutputComponent.SQL_QUERY)
    tools = mock_llm_client.ask.call_args.kwargs.get("tools") or []
    tool_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in tools}
    assert "generate_optimization_tips" not in tool_names
    assert "extract_sql_from_response" in tool_names
```

Fixtures required (place in `tests/bots/database/conftest.py`):

```python
# tests/bots/database/conftest.py
@pytest.fixture
def fake_postgres_toolkit():
    """In-memory PostgresToolkit with two seeded tables."""
    ...

@pytest.fixture
def mock_llm_client():
    """AbstractClient stub recording client.ask payloads, returning canned QueryResponse."""
    ...
```

---

## Agent Instructions

1. Read the spec end-to-end — §2 (Architectural Design), §3 (Modules 4
   & 5), §6 (Codebase Contract), §7 (Implementation Notes).
2. Verify TASK-1125, TASK-1126, TASK-1127 are already complete (their
   files exist in `sdd/tasks/completed/`).
3. Before editing `agent.py`, re-read `bots/data.py:305–1110` to ground
   the PandasAgent pattern in current code (not 2026-05-12 line numbers).
4. Build the rewrite incrementally: base class change → `__init__` →
   `configure()` → `ask()`. Run tests after each milestone.
5. Run `pytest tests/manager/test_bot_cleanup_lifecycle.py -v` to
   confirm no lifecycle regression.
6. Run `ruff check` and `mypy --strict` on the agent module.
7. Move this file to `sdd/tasks/completed/` and update the per-spec
   index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-05-13
**Notes**: All 13 unit tests pass. DatabaseAgent now inherits from BasicAgent, uses _build_database_prompt_builder() as class-level _prompt_builder, accepts retry_config, implements get_default_components(), registers DatabaseAgentToolkit in configure(), and gates tools by OutputComponent flags in ask(). Added create_system_prompt() override for test-stub compatibility.
**Deviations from spec**: Added `create_system_prompt()` override as a fallback for the test environment where BasicAgent is stubbed. Added explicit `self.logger` initialization in `__init__` for the same reason. Module-level `_COMPONENT_TO_TOOL_NAMES` dict instead of per-configure-call (semantically equivalent). Tool gating uses bound method iteration (not `get_tools()`) because `AbstractToolkit._generate_tools()` only collects async methods.
