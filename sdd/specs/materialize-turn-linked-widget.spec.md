---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, docs]
tags: [a2ui, linked-surfaces, ui-surfaces, widgets, agent-functions, querysource, pin]
---

# Feature Specification: Materialize a chat turn as a linked widget

**Feature ID**: FEAT-757
**Date**: 2026-10-27
**Author**: Jesus Lara (drafted with Claude)
**Status**: draft
**Target version**: ai-parrot next minor (ai-parrot / ai-parrot-tools)
**Exploration doc**: none — seeded from the NAV-10382 review (§4b "From an inline answer to a persisted widget",
`docs/frontend/agentdashboard-a2ui-reference.md` §6 / §8.6–8.7). No brainstorm/proposal exists for this slug.

---

## 1. Motivation & Business Requirements

### Problem Statement

An inline chart/table/KPI in a chat bubble is **baked**: the bubble holds a complete `a2ui_envelope`
(`CreateSurface`, dual-emitted since FEAT-473) whose rows were copied into `dataModel`. That is a photograph of one
turn. Anything that must be revisited with fresh data is a *pinned surface* (FEAT-492/598) that is **refreshable**,
and a surface is refreshable only if it has a re-runnable origin — a recipe reference, or linked data sources in
`metadata.extensions.parrot_data_sources` (`has_data_sources()`).

Today the only way to turn "this answer" into "a refreshable version of this answer" is for the frontend to *craft a
prompt*: a follow-up on the same session carrying `turn_id` + the on-screen `data`, such as `/widget worked hours by
month` or "make this a persistable widget", and hope the agent calls `qs_build_linked_surface` with the right slug,
placeholders and component. That is:

- **non-deterministic** — an LLM re-derives the slug, filters and shape from prose, and can drift from what the
  user actually saw;
- **expensive** — a full LLM turn to do a mechanical translation (the data origin is already recorded);
- **fragile for the frontend** — every client re-invents the prompt, per agent and per skill vocabulary.

The data origin is *already known* server-side: the turn's `tool_invocations` record the exact
`qs_execute_slug(slug, placeholders, filter, …, tenant)` call that produced the rows, and the on-screen envelope
records the chosen component. What is missing is one canonical entry point that joins the two.

### Goals

- G1. One canonical, **LLM-free** entry point, `materialize_widget`, that turns a turn reference (`turn_id`, plus the
  on-screen envelope the bubble already holds) into a **linked** widget envelope — optionally pinned — so the
  frontend sends a turn reference, never a crafted prompt.
- G2. Reuse, do not re-implement: the linked envelope is produced by the existing `qs_build_linked_surface`
  (authorization, tenant routing, probe validation unchanged); pinning reuses the existing `publish_surface` lane
  (linked validation + fail-closed guard + save-time snapshot).
- G3. Invocable three ways from the same tool: renderer `callAgentFunction` (every `ToolManager` tool already is),
  an LLM tool call (typing "pin this" works), and direct Python.
- G4. An **honest, typed result** for every outcome — `materialized`, `already_linked`, `snapshot_only`,
  `not_materializable` — with a machine-readable `reason`, so the frontend can fall back to "Pin as snapshot"
  (`POST /api/v1/ui/surfaces`) instead of guessing.
- G5. Ownership is enforced by construction: the turn is looked up under the *caller's* `(user_id, session_id)`;
  a turn that is not the caller's is "not found".

### Non-Goals (explicitly out of scope)

- NG1. **No LLM fallback.** If the turn has no re-runnable data origin the tool says so (`snapshot_only`); it does
  not silently re-ask the agent, and there is no opt-in re-ask mode (decided, Q1).
- NG2. No new agent and no change to `Agent.followup()` / `AnswerMemory` — `followup` stays the "Explain this"
  mechanism; this feature does not route through it.
- NG3. No persistence of the inline envelope on the turn (`ConversationTurn` has no envelope field). v1 takes the
  envelope from the caller.
- NG4. No metric registry / default-shape decider and no follow-up chips (separate NAV-10382 gaps, tracked by their
  own proposals).
- NG5. No new HTTP route. The surfaces plane (`POST /api/v1/ui/surfaces`, refresh, share) is unchanged.
- NG6. No bundled `/pin` skill in v1 — a skill is a prompt to an LLM, and the point of this feature is that no
  prompt is needed. The LLM-callable tool already covers "pin this" typed in chat.
- NG7. No derived/join/python-transform reconstruction. Only a plain slug origin (optionally with the toolkit's own
  request grammar) is materialized; multi-source dashboards are `not_materializable` (reason `multi_source_turn`).

---

## 2. Architectural Design

### Overview

`materialize_widget` is an `AbstractTool` (so it is simultaneously an LLM tool, a renderer-callable agent function
and a Python callable) with a thin orchestration body over three existing pieces and one new pure function:

1. **Resolve the turn** under the caller's identity: `bot.conversation_memory.get_history(user_id, session_id,
   chatbot_id=bot.memory_key_id)` → find `turn.turn_id == turn_id`. Not found ⇒ `not_materializable`
   (`turn_not_found`) — also the answer for another user's turn, by key construction.
2. **Extract the origin** (new, pure, in core: `parrot/outputs/a2ui/linked/materialize.py`):
   `extract_slug_origin(tool_invocations)` picks the **last completed** `qs_execute_slug` invocation and returns a
   `SlugOrigin(slug, tenant, request)` where `request` carries `placeholders/filter/fields/ordering/grouping/limit`
   (offset dropped). If the last relevant invocation is already `qs_build_linked_surface` / `qs_build_linked_dashboard`
   the turn is already linked ⇒ `already_linked`. If there are slug executions against more than one distinct
   `(slug, tenant, request)` ⇒ `multi_source_turn`. If there is no slug execution ⇒ `snapshot_only`
   (`no_slug_origin`, e.g. a pandas/ad-hoc frame).
3. **Derive the component** (same module): `component_from_envelope(envelope)` takes the root component of the
   on-screen `CreateSurface` (`Chart` / `DataTable` / `KPICard`; others ⇒ `snapshot_only`
   `unsupported_component`) and strips data bindings and baked rows — `build_linked_surface` re-adds the binding.
4. **Build the linked envelope** by delegating to the bot's own `qs_build_linked_surface` tool
   (`bot.tool_manager.get_tool("qs_build_linked_surface")`) with `(slug, component, request, tenant, snapshot)`.
   Delegation means tenant allowlists, `describe_slug`, probe validation and `LinkedSurfaceService` semantics are the
   toolkit's, not re-implemented here. No QuerysourceToolkit on the bot ⇒ `not_materializable`
   (`no_querysource_toolkit`).
5. **Optionally pin** (`pin=True`): delegate to the bot's `publish_surface` tool (`kind="widget"`) with the linked
   envelope. A surface so pinned is `refreshable` (it has data sources). No `publish_surface` tool ⇒ the linked
   envelope is still returned with `pinned=False`, `reason="no_publish_surface"` — the frontend can pin it itself.

The result is a typed `MaterializeWidgetResult`; the envelope is returned under `a2ui_envelope` + `artifacts`, the
same shape `qs_build_linked_surface` returns, so the A2UI runtime surfaces it with no special casing.

### Component Diagram

```
 frontend ── callAgentFunction("materialize_widget", {turn_id, session_id, envelope, pin?}) ──┐
 LLM  ────── tool call (same args)  ─────────────────────────────────────────────────────────┤
                                                                                            ▼
                                                                          MaterializeWidgetTool
                                                                            │
   caller's (user, session) ─▶ conversation_memory.get_history ─▶ turn ──────┤
                                                                            │ turn.tool_invocations
                                                                            ▼
                                                  extract_slug_origin()  (pure, parrot.outputs.a2ui.linked.materialize)
                                                  component_from_envelope()
                                                                            │
                                    SlugOrigin + component ─────────────────┤
                                                                            ▼
                                      tool_manager.get_tool("qs_build_linked_surface")  ──▶ linked envelope
                                                                            │ pin=True
                                                                            ▼
                                      tool_manager.get_tool("publish_surface") ──▶ surface_id (refreshable)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `QuerysourceToolkit.build_linked_surface` (`qs_build_linked_surface`) | calls | the only builder; unchanged |
| `PublishSurfaceTool` / `InfographicAuthoringMixin.publish_surface` | calls | the only pin lane; unchanged |
| `ToolManager.get_tool` | calls | sibling-tool lookup, no import coupling |
| `ConversationMemory.get_history` / `ConversationTurn.tool_invocations` | reads | origin source of truth |
| `ToolManagerExecutor` (`outputs/a2ui/runtime/adapters.py`) | none (automatic) | every non-`a2ui_hidden` tool is already a renderer function |
| `has_data_sources()` | calls | decides `refreshable` / `already_linked` |

### Data Models

```python
class SlugOrigin(BaseModel):
    slug: str
    tenant: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)  # placeholders/filter/fields/ordering/grouping/limit

class MaterializeWidgetResult(BaseModel):
    status: Literal["materialized", "already_linked", "snapshot_only", "not_materializable"]
    reason: str | None = None            # machine-readable, see §7
    a2ui_envelope: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    surface_id: str | None = None        # set only when pinned
    pinned: bool = False
    refreshable: bool = False
    origin: SlugOrigin | None = None
```

### New Public Interfaces

```python
class MaterializeWidgetTool(AbstractTool):
    name = "materialize_widget"
    async def _execute(self, *, turn_id: str, envelope: dict | None = None, session_id: str | None = None,
                       title: str | None = None, pin: bool = False, snapshot: bool = False, **kwargs) -> dict: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: origin + component extraction | yes | pure functions and the two models above; reason strings fixed in §7; no I/O | — |
| M2: `MaterializeWidgetTool` | yes | orchestration order, sibling-tool delegation, ownership rule, explicit `session_id` arg (Q2) and result mapping are fixed here | — |
| M3: docs | yes | add one section to the two docs listed in §6 Edit Sites | — |

### Module 1: Origin and component extraction (pure)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/materialize.py` (new)
- **Responsibility**: Given a turn's `tool_invocations` and an on-screen envelope, decide the data origin and the component to relink. No I/O, no LLM, no imports of tools or server code (core one-way import rule).
- **Depends on**: `ToolInvocation` (`parrot/memory/compaction/models.py:46`), `has_data_sources` (`linked/__init__.py:63`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/linked/materialize.py  (new)
  EXECUTE_TOOL = "qs_execute_slug"                                   # verified: toolkit.py:84 (tool_prefix "qs") + :253
  LINKED_TOOLS = frozenset({"qs_build_linked_surface", "qs_build_linked_dashboard"})  # verified: toolkit.py:3-5
  SUPPORTED_ROOTS = frozenset({"Chart", "DataTable", "KPICard"})     # verified: builders.py:528 docstring / toolkit.py:361
  NEUTRAL_TOOLS: frozenset[str]   # read-only tools tolerated between the query and the answer (Q3, see §7)

  class SlugOrigin(BaseModel): ...
  class OriginOutcome(BaseModel):
      kind: Literal["slug", "already_linked", "multi_source", "none"]
      origin: SlugOrigin | None = None

  def extract_slug_origin(invocations: Sequence[ToolInvocation]) -> OriginOutcome:
      """Last COMPLETED qs_execute_slug wins; a trailing linked build means 'already_linked'; >1 distinct
      (slug, tenant, request) means 'multi_source'; none means 'none'. Failed/errored invocations are ignored."""

  def component_from_envelope(envelope: Mapping[str, Any]) -> dict[str, Any] | None:
      """Root component (id 'root' or first) with data bindings and baked rows removed; None when the root is not
      in SUPPORTED_ROOTS or the envelope has no components."""
  ```

### Module 2: `MaterializeWidgetTool`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/materialize_widget.py` (new)
- **Responsibility**: The agent-facing tool: resolve the caller's turn, run M1, delegate to `qs_build_linked_surface` and optionally `publish_surface`, return a `MaterializeWidgetResult` dump.
- **Depends on**: Module 1; `AbstractTool`/`AbstractToolArgsSchema` (`parrot/tools/abstract.py`); sibling tools via `ToolManager.get_tool` (`tools/manager.py:1392`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/materialize_widget.py  (new)
  class MaterializeWidgetArgs(AbstractToolArgsSchema):
      turn_id: str = Field(description="The chat turn whose answer to make refreshable.")
      envelope: dict[str, Any] | None = Field(default=None, description="The on-screen a2ui_envelope of that turn.")
      session_id: str | None = Field(default=None, description="Session of the turn; defaults to the bound session.")
      title: str | None = None
      pin: bool = False
      snapshot: bool = False   # forwarded to qs_build_linked_surface (share links / offline export only)

  class MaterializeWidgetTool(AbstractTool):
      """Turn a chat turn into a refreshable linked widget WITHOUT an LLM round-trip. ..."""  # LLM-facing description
      name = "materialize_widget"
      args_schema = MaterializeWidgetArgs
      def __init__(self, bot: Any = None, user_id: str | None = None, session_id: str | None = None, **kwargs): ...
      async def _execute(self, *, turn_id: str, envelope=None, session_id=None, title=None, pin=False,
                         snapshot=False, **kwargs) -> dict[str, Any]: ...
  ```

### Module 3: Documentation
- **Path**: `docs/frontend/agentdashboard-a2ui-reference.md`, `docs/outputs/a2ui-linked-surfaces.md` (modify)
- **Responsibility**: Document the wire call (`callAgentFunction` with `catalogId` set), args, the four statuses and the "fall back to snapshot pin" rule; update §8.6 and the linked-surfaces doc.
- **Depends on**: Modules 1–2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_extract_origin_last_completed_wins` | M1 | two `qs_execute_slug` calls with the same slug/request → one origin |
| `test_extract_origin_ignores_errored` | M1 | an errored invocation after a good one does not replace it |
| `test_extract_origin_already_linked` | M1 | trailing `qs_build_linked_surface` → `already_linked` |
| `test_extract_origin_multi_source` | M1 | two distinct slugs → `multi_source` |
| `test_extract_origin_none` | M1 | no slug invocation (pandas turn) → `none` |
| `test_extract_origin_neutral_tools_tolerated` | M1 | `qs_describe_slug` / `load_skill` between query and answer still yields the origin |
| `test_extract_origin_non_neutral_tool_blocks` | M1 | a pandas/python tool call in the turn → `none` (`no_slug_origin`) |
| `test_tool_missing_session_id` | M2 | no arg and no bound session → `turn_not_found` |
| `test_extract_origin_drops_offset_keeps_tenant` | M1 | `offset` omitted, `tenant` preserved |
| `test_component_strips_bindings_and_rows` | M1 | `Chart`/`DataTable`/`KPICard` lose binding + rows, keep type/axes/title |
| `test_component_unsupported_root` | M1 | `Infographic` root → `None` |
| `test_tool_materialized_happy_path` | M2 | fake bot + fake `qs_build_linked_surface` → `materialized`, `refreshable=True` |
| `test_tool_turn_not_found_other_user` | M2 | another user's turn id → `not_materializable` / `turn_not_found` |
| `test_tool_no_querysource_toolkit` | M2 | bot without the tool → `no_querysource_toolkit` |
| `test_tool_snapshot_only_no_origin` | M2 | pandas turn → `snapshot_only` / `no_slug_origin`, no builder call |
| `test_tool_pin_uses_publish_surface` | M2 | `pin=True` → `publish_surface` called once with `kind="widget"` |
| `test_tool_pin_without_publish_tool` | M2 | envelope returned, `pinned=False`, `reason="no_publish_surface"` |
| `test_tool_builder_failure_is_reported` | M2 | `QuerysourceToolkitError` → `not_materializable` / `build_failed`, message preserved |
| `test_tool_is_renderer_callable` | M2 | `ToolManagerExecutor.list_functions()` lists `materialize_widget` |

### Integration Tests
| Test | Description |
|---|---|
| `test_materialize_then_refresh_roundtrip` | real `QuerysourceToolkit` over a stub catalog + in-memory surface store: execute slug → materialize with `pin=True` → surface row `refreshable` and its envelope passes `LinkedSurfaceService.validate_for_persistence` |

### Validation Contract

tests:
- packages/ai-parrot/tests/outputs/a2ui/linked/test_materialize.py
- packages/ai-parrot-tools/tests/test_materialize_widget_tool.py
- packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py
- packages/ai-parrot-tools/tests/test_publish_surface_tool_linked.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def slug_turn():
    """A ConversationTurn whose tool_invocations hold one completed qs_execute_slug call."""
    return ConversationTurn(
        turn_id="t1", user_id="u1", user_message="worked hours by month", assistant_response="…",
        tool_invocations=[ToolInvocation(tool_name="qs_execute_slug",
                                         input={"slug": "flex_hours_query_pbi", "tenant": "flex", "limit": 500})],
    )
```

---

## 5. Acceptance Criteria

- [ ] AC1. A turn produced by one `qs_execute_slug` call, with a `Chart`/`DataTable`/`KPICard` on screen, materializes to a linked envelope (`has_data_sources(envelope)` is true) via `qs_build_linked_surface`, with **no LLM call** in the path (asserted by a client double that fails on any `ask`).
- [ ] AC2. With `pin=True` the widget is persisted through `publish_surface` as `kind="widget"`, the result carries `surface_id` and `refreshable=True`.
- [ ] AC3. A turn with no slug origin returns `snapshot_only` / `no_slug_origin` and builds nothing; a turn with several distinct slug executions returns `not_materializable` / `multi_source_turn`.
- [ ] AC4. Another user's `turn_id` (or an unknown id) returns `not_materializable` / `turn_not_found`; the response never discloses whether the id exists for someone else.
- [ ] AC5. The tool appears in `ToolManagerExecutor.list_functions()` and is invocable through `callAgentFunction` with the default catalog; it can be hidden with `a2ui_hidden`.
- [ ] AC6. Authorization is unchanged: a slug the caller may not use fails inside `qs_build_linked_surface` and is reported as `build_failed`; nothing is saved.
- [ ] AC7. `extract_slug_origin` and `component_from_envelope` are pure (no network, no event loop) and have the unit coverage in §4.
- [ ] AC8. Docs describe the call, args, statuses and the snapshot-pin fallback; no breaking change to `qs_*`, `publish_surface` or the surfaces HTTP API.
- [ ] AC9. `ruff check` clean on touched files; the Validation Contract tests pass.

---

## 6. Codebase Contract

> Verified against base commit `2fdf94351` (dev) on 2026-10-27.

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema              # verified: ui_surfaces.py:25-26 usage
from parrot.outputs.a2ui.linked import has_data_sources                            # verified: linked/__init__.py:63
from parrot.memory import ConversationTurn                                         # verified: memory/__init__.py:3
from parrot.memory.compaction.models import ToolInvocation                         # verified: compaction/models.py:46
from parrot.auth.permission import PermissionContext, build_principal_context      # verified: auth/permission.py:81, :166
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/memory/compaction/models.py
@dataclass
class ToolInvocation:                                         # line 46
    tool_name: str; input: Dict[str, Any]; output: Optional[str] = None
    status: ToolStatus = ToolStatus.COMPLETED; error: Optional[str] = None  # ToolStatus.COMPLETED / errored

# packages/ai-parrot/src/parrot/memory/abstract.py
class ConversationTurn:                                       # line 102 (turn_id, user_id, tool_invocations, metadata, chatbot_id)
class ConversationHistory:                                    # line 274 (turns: List[ConversationTurn])
class ConversationMemory:
    async def get_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> Optional[ConversationHistory]  # line 429

# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):                    # line 76; tool_prefix = "qs" (84)
    async def execute_slug(self, slug, placeholders=None, filter=None, fields=None, ordering=None, grouping=None,
                           limit=None, offset=None, refresh=False, tenant=None) -> ExecutionResult   # line 253
    async def build_linked_surface(self, slug, component, request=None, tenant=None, snapshot=False,
                                   surface_id=None, target_key=None, refresh=None, transform=None) -> dict[str, Any]  # line 351
        # returns {"a2ui_envelope": ..., "artifacts": [...]}

# packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py
class PublishSurfaceTool(AbstractTool):                       # line 65; name = "publish_surface" (76)
    async def _execute(self, *, kind, title, envelope, recipe_name=None, recipe_owner=None,
                       recipe_params=None, overwrite=False, **kwargs) -> dict   # line 127; returns {"surface_id","kind","refreshable"}

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def get_tool(self, tool_name: str) -> Optional[Any]       # line 1392
    def register_tool(...)                                    # line 853

# packages/ai-parrot/src/parrot/outputs/a2ui/runtime/adapters.py
class ToolManagerExecutor:   # list_functions(): every tool except a2ui_hidden → FunctionDefinition(allowed_callers="rendererOrAgent")
# packages/ai-parrot/src/parrot/outputs/a2ui/runtime/dispatch.py:259  _dispatch_call_agent_function
```
Tool attributes available at execute time: `AbstractTool._current_pctx` (`tools/abstract.py:425`), `a2ui_hidden` (`:334`).

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MaterializeWidgetTool` | `qs_build_linked_surface` | `bot.tool_manager.get_tool("qs_build_linked_surface")` | `tools/manager.py:1392`, `bots/abstract.py:383` |
| `MaterializeWidgetTool` | `publish_surface` | `bot.tool_manager.get_tool("publish_surface")` | `ui_surfaces.py:76` |
| `MaterializeWidgetTool` | turn history | `bot.conversation_memory.get_history(...)`, `bot.memory_key_id` | `memory/abstract.py:429`, `bots/abstract.py:591` |
| renderer | tool | `callAgentFunction` → `ToolManagerExecutor.call` | `adapters.py`, `dispatch.py:259` |

### Does NOT Exist (Anti-Hallucination)
- ~~`materialize_widget` / `MaterializeWidgetTool` / `materialize_turn`~~ — no such symbol anywhere in `packages/*/src`, `agents/`, `sdd/`, `docs/` (grep, 2026-10-27).
- ~~a bundled `/pin` skill~~ — none exists; the only widget skill is `agents/flex_dashboard/skills/widget/SKILL.md` (agents/ is gitignored).
- ~~`ConversationTurn.envelope` / `ConversationTurn.a2ui_envelope`~~ — `memory/abstract.py` has no A2UI field; the inline envelope is **not** persisted on the turn.
- ~~`AnswerMemory` holding tool calls~~ — `AnswerMemory` stores only `{question, answer}` (`memory/agent.py:15-22`) and is written only by `PandasAgent` (`bots/data.py:2096`); do not use it as the origin source.
- ~~`QuerysourceToolkit.materialize*`~~ — not a method; this feature does not add one.
- `PublishSurfaceTool` is **not** auto-registered by any library code (`grep "PublishSurfaceTool("` finds only its definition); agent authors register it explicitly — `MaterializeWidgetTool` follows the same convention.

### Edit Sites (Blueprint Anchors)

Verified against: `2fdf94351`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/materialize.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/materialize_widget.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_materialize.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/test_materialize_widget_tool.py` | CREATE | — | — | — |
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | `### 8.6 Actions and agent functions from the renderer` | `:972` | 1 |
| `docs/outputs/a2ui-linked-surfaces.md` | MODIFY | `## 4. Refresh policy and snapshots` | `:149` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first; Pydantic v2 models; `self.logger`, no `print`; Google-style docstrings; the tool's docstring is the LLM-facing description.
- Sibling-tool lookup through `ToolManager.get_tool` — no import of `QuerysourceToolkit` or server code from the new tool, so the tool also works with a differently-named builder later.
- Reason vocabulary is a closed set, defined once as constants in M1 and reused by M2: `turn_not_found`, `no_slug_origin`, `multi_source_turn`, `unsupported_component`, `no_envelope`, `no_querysource_toolkit`, `build_failed`, `no_publish_surface`.
- Permission/identity: user from `self._current_pctx` (via `PermissionContext.session`; **verify the attribute path at task time**), falling back to the constructor-bound `user_id`; never from tool args.

### Known Risks / Gotchas
- **Session plumbing (Q2, resolved).** `ToolManagerExecutor.call` passes only `permission_context`; the A2UI `session_id` (`A2UICallContext`) does not reach the tool. Decision: `session_id` is an explicit arg (the frontend always has it), and ownership is still safe because the history key includes the pctx-derived `user_id`. A missing `session_id` with no constructor-bound one ⇒ `not_materializable` / `turn_not_found`.
- **Idempotency of the origin.** The recorded `qs_execute_slug` input is *post-normalization* (Stage 0 canonicalization, `ToolInvocation.input`); `limit` was capped at `max_rows`. The linked widget will fetch with the renderer's own paging — document that `limit` is advisory.
- **Offloaded inputs.** Oversized tool inputs may be offloaded by compaction (`omitted`); treat an invocation with offloaded `input` as unusable (`no_slug_origin`) rather than guessing.
- **Wrong-widget risk.** If a turn ran `qs_execute_slug` for exploration and then charted a pandas-derived frame, the last slug is not necessarily the plotted data. v1 rule (Q3, resolved): any invocation in the turn outside `NEUTRAL_TOOLS` makes the turn `snapshot_only` / `no_slug_origin` rather than relinked. `NEUTRAL_TOOLS` = `qs_list_slugs`, `qs_describe_slug`, `qs_get_dialect_reference`, `qs_list_components`, `qs_validate_pipeline`, plus the working-memory/skill read tools (`read_omitted_content`, `list_skill_commands`, `load_skill`, `read_skill_asset`, `search_skills`, `read_skill`, `list_skills`) — exact names re-verified at task time. `qs_execute_slug`, `qs_build_linked_surface`/`_dashboard` are handled by the origin logic itself; `qs_run_multiquery`/`qs_save_multiquery` are NOT neutral.
- **Linked envelopes are definition-only by default** (`rows: []`, `snapshot_at: null`); pinning performs the save-time snapshot in the owner's context (`publish_surface`), so a guardless bot fails closed (`LinkedGuardRequired`) — surfaced as `build_failed`/`no_publish_surface`-class errors, never a crash.
- `Agent.followup()` reads `AnswerMemory`, which is in-memory per process; that is why this design reads `conversation_memory` instead.

### External Dependencies
None new.

---

## 8. Open Questions

- [x] Q1. Add an opt-in LLM re-ask lane for `snapshot_only` turns? — *Resolved 2026-10-27 (Jesus Lara)*: no. v1 is strictly deterministic; the tool returns `snapshot_only` and the frontend pins a snapshot. Reflected in NG1, §2 Overview and AC3.
- [x] Q2. Where does `session_id` come from on the renderer lane? — *Resolved 2026-10-27 (Jesus Lara)*: explicit `session_id` arg; no change to `ToolManagerExecutor`/`A2UICallContext`. Ownership stays safe because the history key includes the pctx-derived `user_id`. Reflected in `MaterializeWidgetArgs` and §7.
- [x] Q3. Which tools may sit between `qs_execute_slug` and the answer? — *Resolved 2026-10-27 (Jesus Lara)*: only the read-only `qs_*` family plus working-memory/skill read tools (`NEUTRAL_TOOLS` in M1, listed in §7). Any other invocation in the turn ⇒ `snapshot_only` / `no_slug_origin`.
- [x] Q4. Auto-register the tool in `InfographicAuthoringMixin.configure`? — *Resolved 2026-10-27 (Jesus Lara)*: no, opt-in per agent (`MaterializeWidgetTool(bot=self)`), like `PublishSurfaceTool`; M3 docs show the registration snippet.
- [x] Q5. Persist the inline envelope on the turn so the frontend can send only `turn_id`? — *Deferred (NG3)*: out of this feature; v1 takes the envelope from the caller. Candidate follow-up spec.

---

## 9. Design Research Cross-Check

> Status: skipped (no accepted exploration document — this spec was seeded from a review note, not a brainstorm/proposal).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree for the whole spec (`feat-FEAT-757-materialize-turn-linked-widget`); `sdd-coder` gives each task its own sub-worktree.
- **Module dependency graph**: M2 → M1 (M2 imports `SlugOrigin`, `extract_slug_origin`, `component_from_envelope`, and the reason constants from M1). M3 → M1, M2 (documents their final names). M1 has no in-spec dependency.
- **Shared files**: none — every module owns distinct files.
- **Exclusive resources**: none (no extension rebuild, lockfile or migration).
- **Cross-feature dependencies**: none unmerged — FEAT-598 (linked surfaces), FEAT-492 (ui_surfaces) and FEAT-469 (A2UI runtime) are on `dev`.
