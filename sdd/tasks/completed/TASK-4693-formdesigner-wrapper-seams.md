# TASK-4693: Wrapper seams: card-first, commands, turn context (M7 part 2)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4688, TASK-4692
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7**, the wrapper part: additive, guarded seams in
`MSTeamsAgentWrapper` so a `TeamsFormDesignerMixin` agent is asked first, gets
its TurnContext-carrying commands registered, receives the wrapper's single
session store and config, and has every tool-capable `process_message` turn
wrapped in its request-local context (with queued cards flushed before the
normal response). An agent WITHOUT the mixin must take byte-identical paths.

Depends on TASK-4688 (`PICKER_ACTION_KEY`) and TASK-4692 (the mixin's full
surface: `apply_teams_config`, `bind_teams_identity`, `teams_commands`,
`formdesigner_turn`, `flush_formdesigner_cards`, `handle_formdesigner_card`,
`formdesigner_serving`). Wave 5.

**Decisions made at task time:**
1. **Gate on the class marker, not on bare `getattr`.** Many existing tests build
   the wrapper around a `MagicMock` agent (`test_mentions.py:47`,
   `test_msteams_whitelist_integration.py:83`…); `getattr(MagicMock(), "flush_formdesigner_cards")`
   returns a non-awaitable mock. `_formdesigner_agent()` returns the agent only when
   `getattr(type(agent), "formdesigner_serving", False) is True`, and also tolerates a
   wrapper built via `__new__` with no `agent` attribute (`test_formdesigner_wrapper.py:15`).
2. **Wiring goes after the FEAT-729 auth block**, not right after
   `agent_cmd_handler.register(...)` (spec said `:191`): `self._session_store` is
   only created at `wrapper.py:223`, and `bind_teams_identity` needs it.

**Cross-feature note**: FEAT-733 (unmerged) edits `wrapper.py` too
(TASK-4653/4655). Whichever lands second rebases; these seams are additive.

---

## Scope

- Import `PICKER_ACTION_KEY` from `.formdesigner_cards`.
- Add `_formdesigner_agent`, `_wire_formdesigner_agent`, `_formdesigner_turn`,
  `_flush_formdesigner_cards_if_ok` methods; call `_wire_formdesigner_agent()` once in `__init__`.
- In `_handle_card_submission`, immediately BEFORE the FEAT-551 `ENVELOPE_KEY`
  branch: ask the mixin when the data carries `ENVELOPE_KEY` or `PICKER_ACTION_KEY`;
  `True` → return; `False` → fall through unchanged.
- Wrap all FOUR `form_orchestrator.process_message` calls (inject closure ~514,
  a2ui_action ~557, `on_message_activity` ~794, `_process_transcribed_message` ~1144)
  in `async with self._formdesigner_turn(turn_context):` and flush on a non-error result
  inside the block, before the normal response is sent.
- Extend `tests/msteams/test_formdesigner_wrapper.py`.

**NOT in scope**: `models.py` / `manager.py` (TASK-4687); mixin internals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | agent-first card seam, command/identity wiring, process_message turn wrapping |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py` | MODIFY | seam routing + fallback tests |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (wrapper.py already has)
```python
import contextlib                                                # wrapper.py:11 — use contextlib.nullcontext()
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY     # wrapper.py:38 <- import anchor (occurrences: 1)
# NEW:
from .formdesigner_cards import PICKER_ACTION_KEY                # created by TASK-4688
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):                 # line 98
        self.agent = agent                                                  # line 140
        self._command_router: MSTeamsCommandRouter = MSTeamsCommandRouter() # line 189
        self._session_store = MSTeamsSessionStore(...)                      # line 223
        # Route                                                             # line 241 <- wiring anchor (occurrences: 1)
    async def _handle_card_submission(self, turn_context, dialog_context):  # line 482
                async def inject(*, session_id, user_id, agent_id, query):  # line 513 (occurrences: 1)
                    result = await self.form_orchestrator.process_message(  # line 514
                    return result                                           # line 522 (occurrences: 1)
            values = {                                                      # line 548 (a2ui_action branch)
            result = await self.form_orchestrator.process_message(          # line 557
        # FormDesigner standalone card (FEAT-551): …                         # line 574 <- seam anchor (occurrences: 1)
        if ENVELOPE_KEY in submitted_data:                                  # line 576
    async def on_message_activity(self, turn_context: TurnContext):         # line 657
        result = await self.form_orchestrator.process_message(              # line 794 (8 spaces; ALSO at 1144 -> ambiguous)
        # Handle result                                                     # line 803 (occurrences: 2 as substring — see blocks)
    async def _process_transcribed_message(self, turn_context, text, conversation_id) -> None:  # line 1121
        result = await self.form_orchestrator.process_message(              # line 1144
                "source": "voice_note",  # Mark source for analytics       # line 1150 (occurrences: 1)
        # Handle result (same as text flow)                                 # line 1154 (occurrences: 1)
    async def close_voice_transcriber(self) -> None:                        # line 1226 <- methods anchor (occurrences: 1)

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py
    def register(self, command: str, handler: Callable) -> None: ...        # line 56 — handler(turn_context)

# FormOrchestrator result: `.has_error` used at wrapper.py:804 (`if result.has_error:`)

# tests/msteams/test_formdesigner_wrapper.py
def _wrapper(allowed_hosts=("forms.test",)) -> MSTeamsAgentWrapper:  # line 15 — built via __new__, NO `agent` attribute
def _ctx(value: dict) -> MagicMock: ...                                # line 36
```

### Does NOT Exist
- ~~A card-submission hook on the agent~~ / ~~an agent→wrapper TurnContext command seam~~ — this task adds both.
- ~~`config.commands` passing a TurnContext~~ — `_make_custom_handler` passes kwargs only; do not route `/getform` through it.
- ~~`self._formdesigner_agent`~~ etc. — new names introduced here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._handle_card_submission",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper.on_message_activity",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._process_transcribed_message",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py#MSTeamsCommandRouter.register"
  ]
}
```

---

## Implementation Notes

- The two 8-space `result = await self.form_orchestrator.process_message(` lines are
  ambiguous on their own; the blocks below anchor each with its own unique following lines.
- Keep every existing line of each `process_message(...)` call; only indent it one level under the `async with`.

---

## Implementation Blueprint

### Steps (in order)
1. Import + helper methods — *why*: every seam goes through `_formdesigner_agent()`.
2. Wiring call — *why*: after `_session_store` exists.
3. Card seam — *why*: ask the mixin before FEAT-551's branch.
4. Wrap the four `process_message` sites — *why*: spec "M7 wraps every wrapper-owned process_message entry that can invoke tools".
5. Tests.

### `wrapper.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -c 'from parrot_formdesigner.renderers.teams import ENVELOPE_KEY' wrapper.py)
# AFTER — insert below `from parrot_formdesigner.renderers.teams import ENVELOPE_KEY` (verified: wrapper.py:38)
from .formdesigner_cards import PICKER_ACTION_KEY
```

### `wrapper.py` (MODIFY) — wiring
```python
# occurrences: 1 (verified: grep -c '        # Route' wrapper.py)
# BEFORE — insert above `        # Route` (verified: wrapper.py:241, right after the FEAT-729 auth block)
        # FEAT-734: TeamsFormDesignerMixin seams (no-op for agents without the mixin)
        self._wire_formdesigner_agent()

```

### `wrapper.py` (MODIFY) — card seam
```python
# occurrences: 1 (verified: grep -c '        # FormDesigner standalone card (FEAT-551)' wrapper.py)
# BEFORE — insert above `        # FormDesigner standalone card (FEAT-551): …` (verified: wrapper.py:574)
        # FEAT-734: a TeamsFormDesignerMixin agent handles its picker, wizard and envelope cards first.
        fd_agent = self._formdesigner_agent()
        if fd_agent is not None and (ENVELOPE_KEY in submitted_data or PICKER_ACTION_KEY in submitted_data):
            if await fd_agent.handle_formdesigner_card(turn_context, submitted_data):
                return

```

### `wrapper.py` (MODIFY) — helper methods
```python
# occurrences: 1 (verified: grep -c '    async def close_voice_transcriber(self) -> None:' wrapper.py)
# BEFORE — insert above `    async def close_voice_transcriber(self) -> None:` (verified: wrapper.py:1226)
    def _formdesigner_agent(self) -> Any | None:
        """The agent when it is a TeamsFormDesignerMixin (class marker), else None. MagicMock-safe."""
        agent = getattr(self, "agent", None)
        if agent is not None and getattr(type(agent), "formdesigner_serving", False) is True:
            return agent
        return None

    def _wire_formdesigner_agent(self) -> None:
        """Hand the mixin our config + single session store, and register its TurnContext commands."""
        agent = self._formdesigner_agent()
        if agent is None:
            return
        agent.apply_teams_config(self.config)
        agent.bind_teams_identity(self._session_store)
        for name, handler in agent.teams_commands().items():
            self._command_router.register(name, handler)
        self.logger.info("MSTeams[%s]: FormDesigner serving enabled", self.config.name)

    def _formdesigner_turn(self, turn_context: TurnContext) -> Any:
        """The mixin's request-local context manager, or a no-op one."""
        agent = self._formdesigner_agent()
        return agent.formdesigner_turn(turn_context) if agent is not None else contextlib.nullcontext()

    async def _flush_formdesigner_cards_if_ok(self, turn_context: TurnContext, result: Any) -> None:
        """Send cards queued by FormDesigner tools during a successful turn."""
        agent = self._formdesigner_agent()
        if agent is None or result is None or getattr(result, "has_error", False):
            return
        await agent.flush_formdesigner_cards(turn_context)

```

### `wrapper.py` (MODIFY) — the four `process_message` sites
```python
# Site 1 — inject closure. Anchor: `                async def inject(*, session_id, user_id, agent_id, query):`
#   (occurrences: 1, wrapper.py:513) through `                    return result` (occurrences: 1, :522).
#   REPLACE the body between them with:
                    async with self._formdesigner_turn(turn_context):
                        result = await self.form_orchestrator.process_message(
                            # FILL IN: the existing four argument lines, unchanged, one indent deeper
                        )
                        await self._flush_formdesigner_cards_if_ok(turn_context, result)
                    return result

# Site 2 — a2ui_action. Anchor: the `result = await self.form_orchestrator.process_message(` that follows
#   `            values = {` (occurrences: 1, :548) — at :557, 12-space indent (unique at that indent).
            async with self._formdesigner_turn(turn_context):
                result = await self.form_orchestrator.process_message(
                    # FILL IN: existing arguments unchanged
                )
                await self._flush_formdesigner_cards_if_ok(turn_context, result)

# Site 3 — on_message_activity. Disambiguate: the 8-space call at :794 whose context dict does NOT contain
#   "source": "voice_note" and which is followed by `        # Handle result` + `        if result.has_error:`
#   (the bare `        # Handle result` line, NOT `# Handle result (same as text flow)`). Same wrap as Site 2, 8-space base.

# Site 4 — _process_transcribed_message. Disambiguate by `                "source": "voice_note",  # Mark source for analytics`
#   (occurrences: 1, :1150) inside the call at :1144, followed by `        # Handle result (same as text flow)` (occurrences: 1).
#   Same wrap, 8-space base.
```
**Why**: flushing inside the block sends the form card before the model's normal response and before the turn's bearer is cleared; an error result or exception skips the flush and `bind_turn`'s `finally` discards the queue.

### `tests/msteams/test_formdesigner_wrapper.py` (MODIFY — append)
```python
class _FDAgent:
    """Minimal stand-in carrying the mixin's surface and marker."""
    formdesigner_serving = True
    # FILL IN: handle_formdesigner_card (AsyncMock-backed, configurable return), apply_teams_config,
    #   bind_teams_identity, teams_commands -> {"getform": AsyncMock()}, formdesigner_turn (asynccontextmanager
    #   recording enter/exit), flush_formdesigner_cards (AsyncMock)


async def test_wrapper_falls_back_without_mixin(): ...          # FILL IN: MagicMock agent -> legacy _handle_formdesigner_submit path
async def test_wrapper_asks_mixin_first(): ...                  # FILL IN: handler True -> legacy POST not called
async def test_mixin_declines_unknown_envelope_falls_back(): ...  # FILL IN: handler False -> legacy branch runs
async def test_picker_action_routed_to_mixin(): ...             # FILL IN: {PICKER_ACTION_KEY: "get_form"} reaches the mixin
def test_wire_registers_commands_and_binds_store(): ...         # FILL IN: call _wire_formdesigner_agent on a __new__ wrapper
async def test_toolkit_voice_and_card_continuations(): ...      # FILL IN: _process_transcribed_message and the a2ui_action
                                                                #   branch enter formdesigner_turn and flush on success; not on has_error
def test_magicmock_agent_is_not_treated_as_mixin(): ...         # FILL IN
```

### FILL IN checklist
- [ ] four `process_message` re-indents (arguments unchanged)
- [ ] `_FDAgent` fake and seven test bodies

---

## Acceptance Criteria

- [ ] Agent without the mixin (incl. `MagicMock`): identical behaviour; `test_formdesigner_roundtrip.py`, `test_formdesigner_submit.py` and existing wrapper tests pass unchanged.
- [ ] Mixin agent is asked first for `ENVELOPE_KEY` / `PICKER_ACTION_KEY` cards; `False` falls through.
- [ ] `/getform` and `/listforms` are registered on the command router with TurnContext handlers.
- [ ] All four `process_message` sites bind the turn context and flush only on success.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py -q`
- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py -q`
- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py -q`


---

## Test Specification

Seven appended tests in the blueprint (spec §4: `test_wrapper_falls_back_without_mixin`,
`test_mixin_declines_unknown_envelope_falls_back`, `test_toolkit_voice_and_card_continuations`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4693 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any


### Completion Note
Implemented by the sdd-coder pool; merged to the feature branch, file-fidelity gate green, merge-tier validation green, review recorded (0 corrections).
