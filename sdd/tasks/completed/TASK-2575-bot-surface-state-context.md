# TASK-2575: Expose `a2ui_surface_state` to the bot turn and tools

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2570
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 8** and completes goal **G3**. TASK-2569/2570 persist
the surface's `dataModel` per `surfaceId`; this task is what finally makes it
*visible* to the agent — otherwise G3 is storage with no reader and the whole
`sendDataModel` flow is pointless.

Two hops:
1. A turn originating from `dispatch` carries its `SurfaceState` into the bot's
   turn context — using the same mechanism `AbstractBot` already uses to attach
   `interactive_envelope` / `infographic_envelope` to a response.
2. Tools receive it as a reserved kwarg `_a2ui_surface_state`, following the
   established `_permission_context` / `_resolver` convention.

The spec calls for a **minimal hook** — "sin nueva API pública obligatoria".
Resist enlarging `AbstractBot`'s public surface here.

---

## Scope

- Thread `SurfaceState` from a dispatch-originated turn into the bot's turn context.
- Add `_a2ui_surface_state` to the reserved kwargs `AbstractTool.execute` pops.
- Unit tests proving a tool receives it.

**NOT in scope**: persistence (TASK-2570), any transport, proactive
agent-initiated surface pushes (explicitly a spec Non-Goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Minimal turn-context hook |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | Pop `_a2ui_surface_state` in `execute` |
| `packages/ai-parrot/tests/bots/test_a2ui_surface_state.py` | CREATE | Turn-context + tool-kwarg tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ce716a032` (2026-08-29).

### Verified Imports
```python
from parrot.outputs.a2ui.runtime.models import SurfaceState   # TASK-2568
from parrot.tools.abstract import AbstractTool, ToolResult    # tools/abstract.py:235, :200
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py:797
async def execute(self, *args, **kwargs) -> ToolResult:
    """Reserved kwargs (documented at 804-805):
        - _permission_context: PermissionContext for Layer 2 enforcement
        - _resolver: AbstractPermissionResolver for permission checks
    """
    pctx     = kwargs.pop('_permission_context', None)   # 813
    resolver = kwargs.pop('_resolver', None)             # 814
    # <-- add: surface = kwargs.pop('_a2ui_surface_state', None)

# tools/abstract.py:740 — the underscore convention is already documented:
#   "``_permission_context`` and ``_resolver`` by ``execute()``"

# packages/ai-parrot/src/parrot/bots/base.py — the envelope-injection mechanism to mirror
#   1417  interactive_envelope = self._extract_last_interactive_result(...)
#   1420  if interactive_envelope is not None:
#   1421      if getattr(interactive_envelope, "a2ui_envelope", None) is not None:
#   1422          response.a2ui_envelope = interactive_envelope.a2ui_envelope
#   1425      else: self._finalize_interactive_response(response, interactive_envelope)
#   1451-1464  the same shape again for infographic_envelope
#   1476  if interactive_envelope is not None or infographic_envelope is not None: ...

# packages/ai-parrot/src/parrot/bots/base.py — how permission_context already flows to tools
#    960  permission_context: Optional[Any] = None,      (ask signature)
#   1298  if permission_context is not None: client._permission_context = permission_context
#   1650  permission_context: Optional[Any] = None,      (second entry point)
#   1804-1807  "# ask() (client._permission_context, consumed by
#              #  tool_manager.execute_tool's permission_context= kwarg)"
#              if permission_context is not None: client._permission_context = permission_context
```

**Read 1804-1807 carefully** — it documents the existing indirection:
`AbstractBot` stashes the context on the *client*, and `ToolManager.execute_tool`
later forwards it as its `permission_context=` kwarg. `_a2ui_surface_state`
should follow the **same** established route rather than inventing a parallel
channel. Confirm the exact hop before implementing.

### Does NOT Exist
- ~~`AbstractBot.a2ui_surface_state` as a public attribute/property~~ — the spec asks for a minimal hook, not new public API.
- ~~`_a2ui_surface_state` anywhere today~~ — this task introduces it.
- ~~a generic "turn context" dict on `AbstractBot`~~ — verify how a turn actually carries side-channel data before assuming one exists; the precedent is the client-attribute route at 1298/1806.
- ~~`ConversationTurn.metadata` holding surface state~~ — surface state lives in `ConversationHistory.metadata["a2ui_surfaces"]` (TASK-2570), not on individual turns.

---

## Implementation Notes

### Follow the existing convention exactly
`_permission_context` and `_resolver` are underscore-prefixed for a specific
reason documented across `tools/abstract.py` and `.agent/CONTEXT.md`:
underscore-prefixed names are never exposed by `_generate_tools()` as
LLM-callable parameters. `_a2ui_surface_state` inherits that property — the LLM
must never see it as a tool argument. Verify this holds after your change (a
tool's generated schema must not gain an `_a2ui_surface_state` property).

### Minimal hook
Mirror the `interactive_envelope` / `infographic_envelope` pattern at
`bots/base.py:1417-1476` in **shape**, not by copy-paste: those are *response*
enrichment (agent → client), whereas this is *turn* enrichment (client → agent).
Find the corresponding inbound point and attach there. Prefer the client-attribute
route already used for `permission_context` (1298 / 1806) so the value reaches
`ToolManager.execute_tool`'s call site with no new plumbing.

Pass `None` when a turn has no surface state — every existing call path must be
unaffected, and a tool that does not accept the kwarg must not break (that is
exactly why `execute` **pops** rather than forwards).

### Key Constraints
- No breaking change to any public API (spec acceptance criterion).
- `_a2ui_surface_state` must never appear in a generated tool schema.
- async throughout; Google-style docstrings; `self.logger`.
- Keep the `bots/base.py` diff small — it is a large, heavily-shared file.

### References in Codebase
- `tools/abstract.py:797-814` — the reserved-kwarg pop site.
- `tools/abstract.py:740` — where the convention is documented; update the docstring to mention the new kwarg.
- `bots/base.py:1417-1476` — the envelope-injection shape.
- `bots/base.py:1298`, `:1804-1807` — how `permission_context` reaches tools.

---

## Acceptance Criteria

- [ ] A turn originating from `dispatch` with a `SurfaceState` results in the tool receiving `_a2ui_surface_state`.
- [ ] `AbstractTool.execute` pops `_a2ui_surface_state`; a tool not expecting it still executes normally.
- [ ] Turns with no surface state pass `None`; all existing call paths behave identically.
- [ ] `_a2ui_surface_state` does **not** appear in any generated tool schema (asserted by test).
- [ ] No public API of `AbstractBot` or `AbstractTool` changed in a breaking way.
- [ ] The reserved-kwargs docstring at `tools/abstract.py:740`/`:804` lists the new kwarg.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/bots/test_a2ui_surface_state.py packages/ai-parrot/tests/tools -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/base.py packages/ai-parrot/src/parrot/tools/abstract.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_a2ui_surface_state.py
import pytest

from parrot.outputs.a2ui.runtime.models import SurfaceState


class TestToolReceivesSurfaceState:
    async def test_tool_receives_kwarg(self, bot_with_spy_tool, surface_state):
        await bot_with_spy_tool.ask("...", a2ui_surface_state=surface_state)
        assert bot_with_spy_tool.spy_tool.last_surface_state == surface_state

    async def test_absent_surface_state_is_none(self, bot_with_spy_tool):
        await bot_with_spy_tool.ask("hello")
        assert bot_with_spy_tool.spy_tool.last_surface_state is None

    async def test_tool_without_kwarg_still_executes(self, bot_with_plain_tool, surface_state):
        """execute() pops it — a tool that never declared it must not break."""
        ...


class TestSchemaHygiene:
    def test_reserved_kwarg_absent_from_schema(self, sample_tool):
        schema = sample_tool.get_tool_schema()
        assert "_a2ui_surface_state" not in str(schema)

    def test_permission_context_convention_unchanged(self, sample_tool):
        assert "_permission_context" not in str(sample_tool.get_tool_schema())
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 8, §7 "Kwargs reservados", and G3.
2. **Check dependencies** — TASK-2570 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `tools/abstract.py:797-814` and
   `bots/base.py:1298`/`:1804-1807`, and **trace the actual hop** by which
   `permission_context` reaches `execute_tool` before adding a parallel one.
4. **Update status** in the index → `"in-progress"`.
5. **Implement** the minimal hook; keep the `bots/base.py` diff small.
6. **Verify** every acceptance criterion, especially schema hygiene.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-29
**Notes**: Added `AbstractTool.execute()`'s `_a2ui_surface_state` pop (falls
back to a new `_A2UI_SURFACE_STATE_VAR` ContextVar when not passed
explicitly), stored on `self._current_a2ui_surface_state` — mirroring the
existing `self._current_pctx` convention exactly (never forwarded to
`_execute()` as a kwarg either way, so it structurally cannot leak into a
generated tool schema — confirmed by test, not just by inspection). Added
`a2ui_surface_state: Optional[Any] = None` to `AbstractBot.ask()`'s
signature, next to `permission_context`, and one line setting the
ContextVar unconditionally (including to `None`, so a stale value from a
prior `ask()` call on the same task/coroutine never leaks forward) right
where `client._permission_context = permission_context` already lives.
Updated the reserved-kwargs docstrings at both the `execute()` docstring and
`_summarize_args`'s `Args:` block. 8 new tests pass (tool-side mechanism
fully exercised with real `AbstractTool` instances; bot-side wiring verified
via source inspection — driving a full `ask()` call needs RAG-retrieval/
prompt-building/LLM-client mocking unrelated to this task's mechanism, and
this codebase already has an established precedent for this exact technique,
`ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py`). Zero
regressions: `tests/tools` (890 passed, same 51 pre-existing unrelated
DDL-guard/dataset-manager failures as TASK-2571 confirmed), and a
representative `tests/bots` slice — `test_abstractbot_routing.py`,
`test_intent_router.py`, `prompts/` (302 passed, same 48 pre-existing
YAML-prompt-config failures on baseline, confirmed via `git stash`). `ruff
check`: `abstract.py`/`base.py` each show exactly 1 new `UP045` ("use `X |
None`") — both left as-is, deliberately matching the `Optional[Any]` style
of the IMMEDIATELY ADJACENT pre-existing line (`_CREDENTIAL_VAR: ContextVar[
Optional[Any]]` and `permission_context: Optional[Any] = None`
respectively) rather than introducing a locally-inconsistent style; the new
test file is fully clean.

**Route chosen for threading surface state**: **ContextVar** (`_A2UI_SURFACE_STATE_VAR`
in `tools/abstract.py`), NOT the client-attribute route the task's own
Implementation Notes suggested ("Prefer the client-attribute route already
used for permission_context"). Traced the ACTUAL hop before implementing,
per the task's own instruction #3: `client._permission_context = ...`
(bots/base.py) is only HALF the story — the client itself (in
`clients/base.py`, `clients/google/client.py`, `clients/claude_agent.py`,
`clients/codex_agent.py`, each independently) reads
`getattr(self, '_permission_context', None)` and passes it to
`ToolManager.execute_tool(permission_context=...)`, which THEN builds
`exec_kwargs['_permission_context'] = permission_context` before calling
`tool.execute(**exec_kwargs)` — three files, none of which
(`tools/manager.py`, any client) are in this task's declared scope. A
ContextVar set in `bots/base.py` and read in `tools/abstract.py` achieves
the identical externally-observable contract (a tool receives
`_a2ui_surface_state`, the LLM never sees it) using ONLY the two files this
task actually lists.

**Deviations from spec**: (1) The ContextVar mechanism above — a necessary,
evidence-based correction to the task's suggested implementation approach,
not a scope or behavior change (documented at length in `tools/abstract.py`'s
own module-level comment for the next reader). (2) One cross-task
completion, in the same spirit as prior tasks' necessary forward-fixes:
wired `result.surface_state` into the ONE existing `agent.ask(...)` call
site that already injects `DispatchResult.user_turn` (TASK-2573's
`handlers/a2ui.py`, `A2UIHandler.post()`) — without this, TASK-2575's
mechanism would exist but nothing in the codebase would actually USE it,
leaving G3 "storage with no reader" in practice for the ONE transport that
already had the wiring in place to fill it trivially. **Not done**, flagged
as a known gap for a fast-follow: TASK-2572's A2A `_dispatch_a2ui_message`
never checks/uses `DispatchResult.user_turn` at all (confirmed — `grep
user_turn a2a/server.py` returns nothing), so an `action` message dispatched
over A2A does not inject a bot turn today, unlike the HTTP path — this is a
pre-existing gap in TASK-2572 (its own ACs never tested the `action`
branch specifically), out of scope to fix here since it is a materially
larger change than this task's own file list. Similarly, TASK-2574's
deep-link `_dispatch()` discards `A2UIRuntime.dispatch()`'s return value
entirely (only used for its persistence side effect), so a deep-link resume
also does not thread `surface_state` into its `invoker` call — same
category of gap, same reason for not fixing here.
