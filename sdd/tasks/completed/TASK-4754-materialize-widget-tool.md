# TASK-4754: `MaterializeWidgetTool` — turn reference → linked (optionally pinned) widget

**Feature**: FEAT-757 — Materialize a chat turn as a linked widget
**Spec**: `sdd/specs/materialize-turn-linked-widget.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4753
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. This task builds the agent-facing tool `materialize_widget`. It is an `AbstractTool`, so it is
automatically an LLM tool, a renderer `callAgentFunction` target (every non-`a2ui_hidden` ToolManager tool is) and
a Python callable. The tool only orchestrates:

1. resolve the caller's turn;
2. run the pure helpers from TASK-4753;
3. delegate the build to the bot's own `qs_build_linked_surface` tool;
4. optionally pin through the bot's `publish_surface` tool.

Resolved decisions: no LLM fallback (Q1), explicit `session_id` arg (Q2), and opt-in registration per agent (Q4).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/materialize_widget.py` with `MaterializeWidgetArgs` and
  `MaterializeWidgetTool`.
- Write unit tests with fake bot / memory / sibling tools in
  `packages/ai-parrot-tools/tests/test_materialize_widget_tool.py`.

**NOT in scope**: the pure extraction logic (TASK-4753), the real-QuerySource round-trip test (TASK-4755), docs
(TASK-4756), auto-registration in any mixin or toolkit (Q4: opt-in), any change to `ToolManagerExecutor`,
`A2UICallContext`, `Agent.followup` or `AnswerMemory`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/materialize_widget.py` | CREATE | The tool |
| `packages/ai-parrot-tools/tests/test_materialize_widget_tool.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult  # verified: tools/abstract.py:251 (ToolResult); usage ui_surfaces.py:26
from parrot.outputs.a2ui.linked import has_data_sources                              # verified: linked/__init__.py:63
from parrot.outputs.a2ui.linked.materialize import (                                 # created by TASK-4753
    MaterializeWidgetResult, SlugOrigin, component_from_envelope, extract_slug_origin,
    REASON_TURN_NOT_FOUND, REASON_NO_SLUG_ORIGIN, REASON_MULTI_SOURCE_TURN, REASON_UNSUPPORTED_COMPONENT,
    REASON_NO_ENVELOPE, REASON_NO_QUERYSOURCE_TOOLKIT, REASON_BUILD_FAILED, REASON_NO_PUBLISH_SURFACE,
    REASON_PIN_FAILED,
)
from pydantic import Field
# tests only:
from parrot.memory import ConversationHistory, ConversationTurn                     # verified: memory/__init__.py:3
from parrot.memory.compaction.models import ToolInvocation, ToolStatus              # verified: compaction/models.py:24, :46
from parrot.tools.manager import ToolManager                                        # verified: tools/manager.py:289
from parrot.outputs.a2ui.runtime.adapters import ToolManagerExecutor                # verified: runtime/adapters.py:44
from parrot.auth.permission import build_principal_context                          # verified: auth/permission.py:166
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:
    a2ui_hidden: bool = False                               # line 334
    def __init__(self, name=None, description=None, ..., **kwargs)   # line 358
    self._current_pctx: Optional[Any]                       # line 425 — set by execute() from the "_permission_context" kwarg
    async def execute(self, *args, **kwargs) -> ToolResult  # line 916; pops "_permission_context" (≈line 939);
        # a non-ToolResult return value is wrapped as ToolResult(status="success", result=value) (≈1094);
        # ordinary exceptions become an error ToolResult; AuthorizationRequired / BudgetError / CredentialRequired
        # are RE-RAISED (≈1174-1196) — let them propagate, do not catch them.
class ToolResult(BaseModel):                                 # line 251: success, status, result, error, metadata

# packages/ai-parrot/src/parrot/auth/permission.py
class PermissionContext:                                     # line 81
    @property
    def user_id(self) -> str                                 # ≈line 129 (delegates to session.user_id)

# packages/ai-parrot/src/parrot/memory/abstract.py
class ConversationMemory:
    async def get_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None
                          ) -> Optional[ConversationHistory]          # line 429
class ConversationHistory:  turns: List[ConversationTurn]             # line 274-280
class ConversationTurn:     turn_id, user_id, user_message, tool_invocations, ...   # line 102

# Bot attributes the tool reads (getattr, never assume):
#   bot.conversation_memory  — bots/abstract.py:591 (Optional[ConversationMemory])
#   bot.memory_key_id        — chatbot_id used for histories (bots/abstract.py:352 comment, used at :2054/:2067)
#   bot.tool_manager.get_tool(name) -> Optional[tool]   — bots/abstract.py:383, tools/manager.py:1392

# Sibling tools (called through .execute, never imported):
#   "qs_build_linked_surface"(slug, component, request=None, tenant=None, snapshot=False, ...)
#       -> result {"a2ui_envelope": dict, "artifacts": [...]}          — parrot_tools/querysource/toolkit.py:351
#   "publish_surface"(kind, title, envelope, recipe_name=None, ...)
#       -> result {"surface_id", "kind", "refreshable"}                 — parrot_tools/ui_surfaces.py:76, :127
```

### Does NOT Exist
- ~~`MaterializeWidgetTool` / `parrot_tools.materialize_widget`~~ — this task creates them.
- ~~`bot.answer_memory` as an origin source~~ — `AnswerMemory` holds only `{question, answer}` (`memory/agent.py:15-22`); never use it here.
- ~~`ConversationMemory.get_turn(turn_id)`~~ — no such method; scan `history.turns`.
- ~~`A2UICallContext.session_id` reaching the tool~~ — `ToolManagerExecutor.call` passes only `permission_context`; `session_id` is an explicit arg (Q2).
- ~~library auto-registration of `PublishSurfaceTool`~~ — none exists; this tool is likewise opt-in.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/materialize_widget.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/test_materialize_widget_tool.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#ToolResult",
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationMemory.get_history",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.get_tool",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/runtime/adapters.py#ToolManagerExecutor",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.build_linked_surface",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **No LLM call anywhere in the path** (AC1). Never call `bot.ask`/`bot.followup`.
- **Identity**: user from `self._current_pctx.user_id` when a pctx is present, else the constructor-bound
  `user_id`; never from tool args (spec §7). Session from the `session_id` arg, else the constructor-bound one.
  A missing user, missing session, missing memory or unknown turn all produce `not_materializable` /
  `turn_not_found`. Do not distinguish them in the response (AC4).
- Forward `_permission_context=self._current_pctx` to both sibling `execute()` calls, so the toolkit's own
  authorization runs exactly as if the LLM had called it (AC6).
- Imports: `parrot_tools.*` / `parrot.*` explicitly (no `parrot.tools.<x>` redirect in new code).

---

## Implementation Blueprint

### Steps (in order)
1. Create `materialize_widget.py` from the block below — *why*: fixes the args schema and tool name that the
   renderer and the docs depend on.
2. Complete the `FILL IN` markers in the order they appear — *why*: each one is one step of the spec §2
   pipeline, and every early exit is a typed result.
3. Write the tests (fakes for bot, memory, tool_manager and sibling tools) and run the Validation Commands.

### `packages/ai-parrot-tools/src/parrot_tools/materialize_widget.py` (CREATE)
```python
"""materialize_widget — turn a chat turn into a refreshable linked widget without an LLM round-trip (FEAT-757)."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from parrot.outputs.a2ui.linked import has_data_sources
from parrot.outputs.a2ui.linked.materialize import (
    REASON_BUILD_FAILED,
    REASON_MULTI_SOURCE_TURN,
    REASON_NO_ENVELOPE,
    REASON_NO_PUBLISH_SURFACE,
    REASON_NO_QUERYSOURCE_TOOLKIT,
    REASON_NO_SLUG_ORIGIN,
    REASON_PIN_FAILED,
    REASON_TURN_NOT_FOUND,
    REASON_UNSUPPORTED_COMPONENT,
    MaterializeWidgetResult,
    component_from_envelope,
    extract_slug_origin,
)
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema

__all__ = ["MaterializeWidgetArgs", "MaterializeWidgetTool"]

BUILD_TOOL = "qs_build_linked_surface"
PUBLISH_TOOL = "publish_surface"


class MaterializeWidgetArgs(AbstractToolArgsSchema):
    """Arguments for materializing a chat turn as a linked widget."""

    turn_id: str = Field(description="The chat turn whose answer should become a refreshable widget.")
    envelope: dict[str, Any] | None = Field(
        default=None, description="The a2ui_envelope that turn displayed (the chat bubble already holds it)."
    )
    session_id: str | None = Field(default=None, description="Session of the turn; defaults to the bound session.")
    title: str | None = Field(default=None, description="Title for the pinned widget; defaults to the turn question.")
    pin: bool = Field(default=False, description="Also persist the linked widget as a refreshable pinned surface.")
    snapshot: bool = Field(
        default=False, description="Embed current rows (share links / offline export only); default definition-only."
    )


class MaterializeWidgetTool(AbstractTool):
    """Turn a previous chat answer (a chart, table or KPI) into a refreshable linked widget.

    Use it when the user asks to keep, pin or save an answer "so it stays up to date". Pass the ``turn_id`` of
    that answer and the envelope it displayed. The tool replays nothing through the model: it reads which query
    produced the data and rebuilds the same widget bound to that query. Set ``pin`` to also save it.
    """

    name = "materialize_widget"
    description = (
        "Turn a previous chat answer (chart, table or KPI) into a refreshable linked widget, optionally pinned. "
        "Pass turn_id and the envelope it displayed; no new query is invented."
    )
    args_schema = MaterializeWidgetArgs

    def __init__(self, bot: Any = None, user_id: str | None = None, session_id: str | None = None, **kwargs: Any):
        """Bind the tool to the agent whose turns and sibling tools it uses.

        Args:
            bot: The agent (provides ``conversation_memory``, ``memory_key_id`` and ``tool_manager``).
            user_id: Fallback identity when no permission context is present (direct Python use).
            session_id: Fallback session when the call does not pass one.
        """
        super().__init__(**kwargs)
        self._bot = bot
        self._user_id = user_id
        self._session_id = session_id

    async def _execute(
        self,
        *,
        turn_id: str,
        envelope: dict[str, Any] | None = None,
        session_id: str | None = None,
        title: str | None = None,
        pin: bool = False,
        snapshot: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = await self._materialize(turn_id, envelope, session_id, title, pin, snapshot)
        self.logger.info("materialize_widget turn=%s status=%s reason=%s", turn_id, result.status, result.reason)
        return result.model_dump(mode="json")

    async def _materialize(
        self, turn_id: str, envelope: dict | None, session_id: str | None, title: str | None, pin: bool, snapshot: bool
    ) -> MaterializeWidgetResult:
        """Run the spec §2 pipeline; every early exit is a typed result, never an exception (except auth)."""
        turn = await self._find_turn(turn_id, session_id or self._session_id)
        if turn is None:
            return MaterializeWidgetResult(status="not_materializable", reason=REASON_TURN_NOT_FOUND)
        if not envelope:
            return MaterializeWidgetResult(status="not_materializable", reason=REASON_NO_ENVELOPE)
        # FILL IN: origin = extract_slug_origin(turn.tool_invocations); map kind -> result:
        #   "already_linked" -> status "already_linked", a2ui_envelope=envelope, refreshable=has_data_sources(envelope)
        #   "multi_source"   -> "not_materializable" / REASON_MULTI_SOURCE_TURN
        #   "none"           -> "snapshot_only" / REASON_NO_SLUG_ORIGIN
        # then component_from_envelope(envelope) is None -> "snapshot_only" / REASON_UNSUPPORTED_COMPONENT.
        # Bounded by spec §2 steps 2-3 and AC3.
        # FILL IN: build — builder = self._sibling(BUILD_TOOL); None -> "not_materializable" /
        #   REASON_NO_QUERYSOURCE_TOOLKIT. Call await builder.execute(slug=..., component=..., request=origin.request
        #   or None, tenant=origin.tenant, snapshot=snapshot, _permission_context=self._current_pctx).
        #   A ToolResult with success False (or a non-dict result) -> "not_materializable" / REASON_BUILD_FAILED with
        #   message=result.error. Do NOT catch AuthorizationRequired. Bounded by AC1, AC6.
        # FILL IN: pin (only when pin=True) — publisher = self._sibling(PUBLISH_TOOL); None -> keep the built
        #   envelope, pinned=False, reason=REASON_NO_PUBLISH_SURFACE. Else await publisher.execute(kind="widget",
        #   title=title or turn.user_message[:80], envelope=<built a2ui_envelope>, _permission_context=...).
        #   Failure -> pinned=False, reason=REASON_PIN_FAILED, message=error; success -> surface_id, pinned=True.
        #   Bounded by AC2.
        # Final success: status "materialized", origin=origin, a2ui_envelope/artifacts from the build result,
        # refreshable=has_data_sources(<built envelope>).
        raise NotImplementedError

    async def _find_turn(self, turn_id: str, session_id: str | None) -> Any:
        """Return the caller's ConversationTurn with ``turn_id``, or None (unknown, not theirs, or no memory)."""
        pctx = self._current_pctx
        user_id = getattr(pctx, "user_id", None) if pctx is not None else None
        user_id = user_id or self._user_id
        memory = getattr(self._bot, "conversation_memory", None)
        if not user_id or not session_id or memory is None:
            return None
        history = await memory.get_history(user_id, session_id, chatbot_id=getattr(self._bot, "memory_key_id", None))
        if history is None:
            return None
        return next((t for t in history.turns if t.turn_id == turn_id), None)

    def _sibling(self, name: str) -> Any:
        """Look up a sibling tool on the bot's ToolManager (no import coupling to its toolkit)."""
        manager = getattr(self._bot, "tool_manager", None)
        return manager.get_tool(name) if manager is not None else None
```
**Why this shape**: identity comes only from the pctx or the binding, because the history key is what enforces
ownership (AC4, Q2). Sibling tools are called through `execute()` with the forwarded pctx, so authorization,
tenant routing and probe validation stay exactly the toolkit's (spec G2). `_execute` always returns a plain dict,
so the A2UI runtime maps it like any other tool result.

### FILL IN checklist
- [ ] `_materialize` origin/component mapping — spec §2 steps 2-3, AC3
- [ ] `_materialize` build via `qs_build_linked_surface` — AC1, AC6
- [ ] `_materialize` optional pin via `publish_surface` — AC2
- [ ] tests from the Test Specification

---

## Acceptance Criteria

- [ ] Happy path returns `materialized`, `refreshable=True`, and an envelope with data sources; a client double that fails on any `ask` proves no LLM call (AC1)
- [ ] `pin=True` calls `publish_surface` once with `kind="widget"` and returns `surface_id`, `pinned=True` (AC2)
- [ ] `snapshot_only` / `not_materializable` paths as in the Test Specification (AC3, AC4)
- [ ] `materialize_widget` appears in `ToolManagerExecutor(tm).list_functions()` (AC5)
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/materialize_widget.py` is clean

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/test_materialize_widget_tool.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_materialize_widget_tool.py
from types import SimpleNamespace

import pytest

from parrot.memory import ConversationHistory, ConversationTurn
from parrot.memory.compaction.models import ToolInvocation
from parrot.tools.abstract import ToolResult
from parrot_tools.materialize_widget import MaterializeWidgetTool

# Fakes: FakeMemory.get_history(user_id, session_id, chatbot_id=None) returns a ConversationHistory only for
# ("u1", "s1"); FakeTool(name, result) records execute(**kwargs) calls and returns the ToolResult; the bot is
# SimpleNamespace(conversation_memory=..., memory_key_id="agent", tool_manager=SimpleNamespace(get_tool=...),
# ask=<async fn that raises AssertionError>).

async def test_tool_materialized_happy_path(): ...
async def test_tool_turn_not_found_other_user(): ...         # bound user "u2" -> turn_not_found
async def test_tool_missing_session_id(): ...                # no arg, no bound session -> turn_not_found
async def test_tool_no_envelope(): ...                       # envelope=None -> not_materializable/no_envelope
async def test_tool_no_querysource_toolkit(): ...
async def test_tool_snapshot_only_no_origin(): ...           # builder never called
async def test_tool_already_linked(): ...
async def test_tool_pin_uses_publish_surface(): ...          # kind="widget", once
async def test_tool_pin_without_publish_tool(): ...          # pinned False, reason no_publish_surface
async def test_tool_pin_failure_reported(): ...              # reason pin_failed, envelope still returned
async def test_tool_builder_failure_is_reported(): ...       # ToolResult(success=False, error=...) -> build_failed
async def test_tool_identity_from_permission_context(): ... # execute(..., _permission_context=build_principal_context("u1", channel="a2ui"))
def test_tool_is_renderer_callable(): ...                    # ToolManager().register_tool(tool); ToolManagerExecutor(tm).list_functions()
```

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug materialize-turn-linked-widget --feature-id FEAT-757`)
2. **Read the spec** for full context.
3. **Check dependencies**: TASK-4753 must be `done` in `sdd/tasks/index/materialize-turn-linked-widget.json`.
4. **Verify the Codebase Contract** before writing code; update it first if anything moved.
5. **Update status** → `"in-progress"` (set `started_at`), commit only the index file.
6. **Implement** from the blueprint, completing every `# FILL IN:`.
7. **Verify** with the Validation Commands (`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`).
8. **Commit the code**, staging only the files listed above.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4754 materialize-turn-linked-widget verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note


- Task: TASK-4754
- Feature: materialize-turn-linked-widget
- Implementation SHA: 60f6bf3136df07adc615015f6923ec31044ca865
- Closed at (UTC): 2026-10-27T02:08:00+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 3 (terra x2 failed validation, then sol) · Duration: 614.7s · Tokens: n/a |
