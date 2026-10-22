# TASK-4124: Route `JiraSpecialist`'s hardcoded messages through the catalog

**Feature**: FEAT-638 — Bot-Level Output Language Directive
**Spec**: `sdd/specs/jiraspecialist-agent-multilang.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4119, TASK-4122, TASK-4123
**Assigned-to**: unassigned

---

## Context

Implements the call-site half of spec §3 **Module 4**. Five places in `jira_specialist.py`
hardcode Spanish in Python f-strings (`:935`, `:944-948`, `:966-967`, `:1076-1080`,
`:1094-1100`). They become `render_message(key, self.language, ...)` calls against the
catalog from TASK-4123.

**Behavior change (decided, spec §8 S1):** with `language` unset these messages now render
**English** — the framework default. The existing Spanish deployment preserves its output by
setting `language="es"`; the Spanish catalog rows are byte-identical to today's strings
(verified mechanically when TASK-4123 was written).

**Intentional fix:** today the success toast hardcodes `"In Progress"` while the transition
itself targets the *configurable* `self._standup_config.in_progress_transition`. The rewrite
passes that config value as the protected `status` placeholder, so the message now names the
status actually transitioned to. Output is unchanged for the default config (`"In Progress"`).

This task also extends the synthetic-package loader in `test_jira_specialist_grounding.py`:
that test replaces `parrot.bots` and `parrot.bots.prompts` with stubs, so once
`jira_specialist.py` imports `parrot.bots.jira_messages` (which imports
`parrot.bots.prompts.language`) both real modules must be registered there or the whole
test module fails to import.

---

## Scope

- Import `render_message` in `jira_specialist.py` and replace all five hardcoded message sites.
- Update `test_jira_callbacks.py`: the unset-language skip toast is now English; add Spanish and escalation cases.
- Register `parrot.bots.prompts.language` and `parrot.bots.jira_messages` in `test_jira_specialist_grounding.py`'s loader.

**NOT in scope**: the LLM-facing prompts in `jira_specialist.py` (e.g. the `ask_human`
instructions around `:596-680` and `:1599-1622`) — those are governed by the
`output_language` prompt layer, not this catalog; any other module's hardcoded strings.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | Import + 5 call sites → `render_message` |
| `packages/ai-parrot/tests/test_jira_callbacks.py` | MODIFY | English default + Spanish + escalation tests |
| `packages/ai-parrot/tests/test_jira_specialist_grounding.py` | MODIFY | Register the two new real modules in the synthetic loader |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.jira_messages import render_message   # created by TASK-4123
# Existing, in tests/test_jira_callbacks.py:7:
from parrot.bots.jira_specialist import JiraSpecialist, Developer, CallbackResult, CallbackContext, DailyStandupConfig
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
from parrot.bots._types import AgentDispatcher          # line 34 — import anchor
class Developer(BaseModel):                             # id, name, username, jira_username: str;
    ...                                                 # telegram_chat_id: int; manager_chat_id: Optional[int]
class DailyStandupConfig(BaseModel):
    in_progress_transition: str = Field(default="In Progress", ...)   # line 132
    response_window_hours: int = Field(default=2, ...)
class JiraSpecialist(Agent):                            # line 152
    self._standup_config = DailyStandupConfig()          # set in __init__
    self.language                                        # from AbstractBot (TASK-4119)
    async def on_ticket_selected(self, callback: CallbackContext) -> CallbackResult:  # line 909
    async def on_ticket_skipped(self, callback: CallbackContext) -> CallbackResult:   # ~line 958
    async def escalate_non_responders(self, manager_chat_id: Optional[int] = None) -> Dict[str, Any]:  # line 1006
        # needs self._wrapper; loads self._developers if empty; r = await self._get_redis();
        # per dev: r.exists(f"standup:dispatched:{today}:{dev.id}") then r.exists(f"standup:responded:{today}:{dev.id}")
        # nudge → self._wrapper.send_interactive_message(chat_id=..., text=..., keyboard=..., parse_mode=...)
        # manager → self._wrapper.bot.send_message(chat_id=..., text=..., parse_mode=...)

# packages/ai-parrot/tests/test_jira_specialist_grounding.py
#   _load_prompts_module() defines nested _load_direct(mod_name, path) (line ~109) and
#   _prompts_root = _WORKTREE / "src/parrot/bots/prompts";
    prompts_pkg = _mk("parrot.bots.prompts")            # line 126 — anchor
```

### Does NOT Exist
- ~~A real `parrot.bots` / `parrot.bots.prompts` package inside `test_jira_specialist_grounding.py`~~ — both are synthetic stubs; that is why the two real modules must be registered explicitly.
- ~~`render_message(..., status="In Progress")` as a literal~~ — pass `self._standup_config.in_progress_transition`.
- ~~`self._standup_config.status`~~ — the field is `in_progress_transition`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/jira_specialist.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_jira_callbacks.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_jira_specialist_grounding.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/jira_specialist.py#JiraSpecialist.on_ticket_selected",
    "sym:packages/ai-parrot/src/parrot/bots/jira_specialist.py#JiraSpecialist.on_ticket_skipped",
    "sym:packages/ai-parrot/src/parrot/bots/jira_specialist.py#JiraSpecialist.escalate_non_responders",
    "sym:packages/ai-parrot/src/parrot/bots/jira_specialist.py#DailyStandupConfig",
    "sym:packages/ai-parrot/src/parrot/bots/jira_specialist.py#Developer"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Use `self.language` (not `getattr`): `JiraSpecialist` always runs `AbstractBot.__init__`.
  The grounding test's stub `_AgentBase` lacks it, but that test never calls these callbacks.
- After this task, none of these Spanish fragments may remain in `jira_specialist.py`:
  `Error transicionando`, `ha sido marcado como`, `A trabajar`, `Entendido`, `entendido.`,
  `aún no has seleccionado`, `Escalación Daily Standup`, `Puede que necesiten`.
- In the grounding-test loader, register `language` **before** `jira_messages`, and both
  **after** `prompts_pkg = _mk("parrot.bots.prompts")` — otherwise the import system tries
  to load the real, heavy `parrot.bots.prompts` package.

---

## Implementation Blueprint

### Steps (in order)
1. Add the import — *why*: single entry point for operational text.
2. Replace the five sites — *why*: spec AC "no hardcoded Spanish literal remains".
3. Extend the grounding-test loader — *why*: otherwise that module fails at import.
4. Update/add callback tests — *why*: the unset default flipped to English (S1).

### `packages/ai-parrot/src/parrot/bots/jira_specialist.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -cF 'from parrot.bots._types import AgentDispatcher' jira_specialist.py)
# AFTER — insert below that line (verified: jira_specialist.py:34)
from parrot.bots.jira_messages import render_message
```

### `packages/ai-parrot/src/parrot/bots/jira_specialist.py` (MODIFY — on_ticket_selected)
```python
# occurrences: 1 (verified: grep -cF '                answer_text=f"⚠️ Error transicionando {ticket_key}",' jira_specialist.py)
# REPLACE line 935 with:
                answer_text=render_message("transition_error", self.language, ticket_key=ticket_key),

# occurrences: 1 (verified: grep -cF '        # 3. Return result — edits original message + shows toast' jira_specialist.py)
# AFTER — insert below that comment (verified: jira_specialist.py:942):
        status = self._standup_config.in_progress_transition  # protected placeholder, never translated

# REPLACE lines 944-949 (`answer_text=f"✅ {ticket_key} → In Progress",` through the closing `),`
#   of edit_message — anchor occurrences: 1, verified: grep -cF '            answer_text=f"✅ {ticket_key} → In Progress",') with:
            answer_text=render_message("transition_ok", self.language, ticket_key=ticket_key, status=status),
            edit_message=render_message(
                "transition_edit", self.language, name=callback.display_name, ticket_key=ticket_key, status=status
            ),
```

### `packages/ai-parrot/src/parrot/bots/jira_specialist.py` (MODIFY — on_ticket_skipped)
```python
# occurrences: 1 (verified: grep -cF '            answer_text="👍 Entendido",' jira_specialist.py)
# REPLACE line 966 AND the edit_message line below it (967) with:
            answer_text=render_message("skip_ok", self.language),
            edit_message=render_message("skip_edit", self.language, name=callback.display_name),
```

### `packages/ai-parrot/src/parrot/bots/jira_specialist.py` (MODIFY — escalate_non_responders)
```python
# Nudge — occurrences: 1 (verified: grep -cF 'aún no has seleccionado tu ticket ' jira_specialist.py)
# REPLACE the whole `text=( ... ),` argument at lines 1076-1080 with:
                    text=render_message("nudge", self.language, name=dev.name),

# Manager — occurrences: 1 (verified: grep -cF 'Escalación Daily Standup' jira_specialist.py)
# REPLACE the whole `text=( ... ),` argument at lines 1094-1100 with:
                    text=render_message("escalation", self.language, hours=hours, names=names),
```
**Why**: keyword names match the `protected` sets in `JIRA_MESSAGES` exactly — a mismatch
raises `KeyError` by design.

### `packages/ai-parrot/tests/test_jira_specialist_grounding.py` (MODIFY — loader)
```python
# occurrences: 1 (verified: grep -cF '    prompts_pkg = _mk("parrot.bots.prompts")' test_jira_specialist_grounding.py)
# AFTER — insert below that line (verified: test_jira_specialist_grounding.py:126)
    # FEAT-638: jira_specialist imports parrot.bots.jira_messages, which imports
    # parrot.bots.prompts.language. Register both REAL modules now that the synthetic
    # package exists — language first, because jira_messages imports it.
    _load_direct("parrot.bots.prompts.language", _prompts_root / "language.py")
    _load_direct("parrot.bots.jira_messages", _prompts_root.parent / "jira_messages.py")
```

### `packages/ai-parrot/tests/test_jira_callbacks.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        self.assertIn("Entendido", result.answer_text)' test_jira_callbacks.py)
# REPLACE line 84 with:
        self.assertIn("Got it", result.answer_text)  # FEAT-638: unset language renders English

# ADD these methods to TestJiraSpecialistCallbacks (patches from asyncSetUp are still active):
    def _ctx(self, prefix, payload):
        return CallbackContext(prefix=prefix, payload=payload, chat_id=100, user_id=200,
                               message_id=300, first_name="Test User")

    async def test_on_ticket_skipped_spanish(self):
        agent = JiraSpecialist(language="es")
        agent.set_wrapper(self.mock_wrapper)
        result = await agent.on_ticket_skipped(self._ctx("tskp", {"d": "dev1"}))
        self.assertIn("Entendido", result.answer_text)

    async def test_on_ticket_selected_spanish_keeps_status(self):
        agent = JiraSpecialist(language="es")
        agent.set_wrapper(self.mock_wrapper)
        agent.ask = AsyncMock()
        result = await agent.on_ticket_selected(self._ctx("tsel", {"t": "NAV-123", "d": "dev1"}))
        self.assertIn("NAV-123", result.answer_text)
        self.assertIn("In Progress", result.answer_text)       # protected status survives
        self.assertIn("ha sido marcado como", result.edit_message)

    async def test_escalation_messages_follow_language(self):
        # FILL IN: agent = JiraSpecialist(language="es"); set_wrapper(self.mock_wrapper);
        #   agent._developers = [Developer(id="d1", name="Ana", username="ana", jira_username="ana@x",
        #   telegram_chat_id=1, manager_chat_id=2)];
        #   self.mock_redis_instance.exists = AsyncMock(side_effect=lambda k: k.startswith("standup:dispatched"));
        #   await agent.escalate_non_responders(); assert the send_interactive_message text equals
        #   render_message("nudge", "es", name="Ana") and the bot.send_message text contains
        #   "Escalación Daily Standup". If redis wiring proves too entangled, instead patch
        #   parrot.bots.jira_specialist.render_message with a spy and assert it was called with
        #   ("nudge", "es", ...) and ("escalation", "es", ...) — bounded by spec AC "Python-authored text follows language".
```

### FILL IN checklist
- [ ] `test_escalation_messages_follow_language` — redis-driven test (preferred) or spy fallback

---

## Acceptance Criteria

- [ ] All five sites call `render_message(...)` with `self.language`; no listed Spanish fragment remains in `jira_specialist.py`.
- [ ] The success toast/edit use `self._standup_config.in_progress_transition` as the protected `status`.
- [ ] Unset language → English toasts; `language="es"` → today's exact Spanish output.
- [ ] `test_jira_specialist_grounding.py` still imports and passes with the extended loader.
- [ ] `test_jira_callbacks.py` passes, including the new Spanish and escalation cases.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/jira_specialist.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_jira_callbacks.py -q`
- `pytest packages/ai-parrot/tests/test_jira_specialist_grounding.py -q`
- `pytest packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py -q`

---

## Test Specification

See the `test_jira_callbacks.py` blueprint block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug jiraspecialist-agent-multilang --feature-id FEAT-638`)
2. **Read the spec** at `sdd/specs/jiraspecialist-agent-multilang.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/jiraspecialist-agent-multilang.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Re-run each blueprint `grep -c` anchor check; a count of `0` means the anchor is gone — stop and report
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/jiraspecialist-agent-multilang.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src` (add `packages/ai-parrot-server/src` for server files)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> jiraspecialist-agent-multilang verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (codex gpt-5.6-terra, 1 attempt)
**Date**: 2026-10-08
**Notes**: jira_specialist.py call sites use catalog; test_jira_callbacks 5 pass, prompt_builder 7 pass.

**Deviations from spec**: none
