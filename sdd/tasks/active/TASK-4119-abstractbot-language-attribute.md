# TASK-4119: Promote `language` to `AbstractBot`; remove Chatbot's `"en"` defaults

**Feature**: FEAT-638 — Bot-Level Output Language Directive
**Spec**: `sdd/specs/jiraspecialist-agent-multilang.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1**. Today `language` exists only on `Chatbot`
(`chatbot.py:244`, `:422`) and is **inert** — persisted and echoed, never reaching a
prompt. `Agent` and `JiraSpecialist` do not have it. The brainstorm decided to promote it
to `AbstractBot` as the single bot-level directive (a hard cut, no parallel
`default_language` attribute) and to change its default from `"en"` to `None`, where
`None` means "mirror the user" — today's behavior for LLM-authored text.

This task only establishes the attribute. Nothing reads it yet; TASK-4121 wires it into
the prompt and TASK-4124 into the Jira callbacks.

---

## Scope

- Add `self.language` to `AbstractBot.__init__`, directly after the personality attributes.
- Change both `Chatbot` assignment sites to default to `None` instead of `"en"`.
- Write tests proving the kwarg, the class-attribute override, and the `None` default.

**NOT in scope**: normalizing/validating the value (TASK-4118 provides that; TASK-4121
applies it at configure time — **never normalize in `__init__`**); `BotModel` /
`UserBotModel` defaults (TASK-4125); `chatbot.py:546` and `:594` (`save()` payload and
`get_configuration_summary()`) — they read `getattr(self, "language", "en")`, but the
attribute is now always set, so their `"en"` fallback can no longer trigger.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add `self.language` after `self.rationale` |
| `packages/ai-parrot/src/parrot/bots/chatbot.py` | MODIFY | Two `"en"` defaults → `None` |
| `packages/ai-parrot/tests/bots/test_bot_language_attribute.py` | CREATE | Attribute tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.basic import BasicBot          # verified: tests/unit/test_guardrails_input_migration.py:22
from parrot.bots.chatbot import Chatbot         # verified: chatbot.py:33  (class Chatbot(BaseBot))
from unittest.mock import MagicMock, patch
# abstract.py already imports Optional:          verified: abstract.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin,
                  EventEmitterMixin, ToolInterface, VectorInterface, ABC):   # line 201
    def __init__(self, name: str = "Nav", ..., **kwargs): ...               # line 274
    # personality idiom, lines 427-431:
    #   self.role = kwargs.get("role") or getattr(self, "role", None) or DEFAULT_ROLE
    #   self.rationale = kwargs.get("rationale") or getattr(self, "rationale", None) or DEFAULT_RATIONALE  # line 431

# packages/ai-parrot/src/parrot/bots/chatbot.py
class Chatbot(BaseBot):                                                    # line 33
    def _from_db(self, botobj, key, default: str = None) -> Any:           # line 167 — returns `value or default`
    async def from_manual_config(self) -> None:                            # line 181
        self.language = getattr(self, "language", "en")                    # line 244
    async def from_database(self, bot: Union[BotModel, None] = None) -> None:  # line 291
        self.language = self._from_db(bot, "language", default="en")       # line 422
    # from_manual_config only calls one method: self._initial_embedding_model(self._vector_store)

# Test helper pattern — tests/unit/test_guardrails_input_migration.py:34-43
def _patched_bot(**kwargs):
    with patch("parrot.bots.guardrails.builtin.prompt_injection._get_shared_injection_detector") as m:
        m.return_value = MagicMock(detect_injection=MagicMock(return_value=(False, 0.0)))
        return BasicBot(name="TestBot", **kwargs)
```

### Does NOT Exist
- ~~`AbstractBot.language`~~ — does not exist yet; this task creates it.
- ~~`AbstractBot.default_language`~~ / ~~`output_language` attribute~~ — not the name this feature uses. The attribute is `language`.
- ~~`DEFAULT_LANGUAGE` constant in abstract.py~~ — do not invent one; the default is a literal `None`.
- **Leak check (verified):** constructor `**kwargs` do NOT reach `LLMConfig.extra`. Only `self._llm_kwargs` (= `kwargs.get("llm_kwargs", {})`, `abstract.py:518`) is forwarded to `_resolve_llm_config` (`abstract.py:1544`). So `language=` cannot leak into a provider call; do not add any popping logic.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/chatbot.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_bot_language_attribute.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot",
    "sym:packages/ai-parrot/src/parrot/bots/chatbot.py#Chatbot.from_manual_config",
    "sym:packages/ai-parrot/src/parrot/bots/chatbot.py#Chatbot.from_database",
    "sym:packages/ai-parrot/src/parrot/bots/chatbot.py#Chatbot._from_db"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Follow the personality idiom exactly: `kwargs.get(...) or getattr(self, ...) or None`.
  This lets a subclass declare `language = "es"` as a class attribute, and a constructor
  kwarg override it — the same precedence `role`/`goal` already use.
- Store the **raw** value. Normalization happens at prompt-configure time (TASK-4121) so a
  value loaded later from the DB is validated the same way.
- `JiraSpecialist.__init__` copies its kwargs into `self._init_kwargs` before `super()`
  (`jira_specialist.py:240`), so `language=` survives `clone_for_user` with no extra work.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the `self.language` line in `abstract.py` — *why*: every bot, including `Agent`/`JiraSpecialist`, must own the attribute (spec AC1).
2. Change the two `chatbot.py` defaults — *why*: hard cut; `"en"` would otherwise force English the moment TASK-4121 wires the layer.
3. Write the tests — *why*: the default flip is a behavior change and needs a regression net.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        self.rationale = kwargs.get("rationale") or getattr(self, "rationale", None) or DEFAULT_RATIONALE' abstract.py)
# AFTER — insert below that line (verified: abstract.py:431)
        # FEAT-638: bot-level output language (raw ISO 639-1 value; None = mirror the user).
        # Normalized against an allowlist at prompt-configure time, never here.
        self.language: Optional[str] = kwargs.get("language") or getattr(self, "language", None) or None
```
**Why**: identical precedence to the five personality attributes directly above it.

### `packages/ai-parrot/src/parrot/bots/chatbot.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        self.language = getattr(self, "language", "en")' chatbot.py)
# REPLACE line 244 with:
        self.language = getattr(self, "language", None)

# occurrences: 1 (verified: grep -cF '        self.language = self._from_db(bot, "language", default="en")' chatbot.py)
# REPLACE line 422 with:
        self.language = self._from_db(bot, "language", default=None)
```
**Why**: spec AC2 — both sites drop `"en"`. `_from_db` returns `value or default`, so an
empty DB value also lands on `None`.

### `packages/ai-parrot/tests/bots/test_bot_language_attribute.py` (CREATE)
```python
"""Tests for the bot-level `language` attribute (FEAT-638 TASK-4119)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.bots.basic import BasicBot
from parrot.bots.chatbot import Chatbot


def _patched_bot(**kwargs):
    """Construct a BasicBot without loading the real pytector model."""
    with patch("parrot.bots.guardrails.builtin.prompt_injection._get_shared_injection_detector") as m:
        m.return_value = MagicMock(detect_injection=MagicMock(return_value=(False, 0.0)))
        return BasicBot(name="TestBot", **kwargs)


def test_language_defaults_to_none():
    assert _patched_bot().language is None


def test_language_kwarg_is_stored_raw():
    assert _patched_bot(language="es-MX").language == "es-MX"  # raw, not normalized


def test_language_class_attribute_is_honored():
    class SpanishBot(BasicBot):
        language = "es"
    # FILL IN: construct SpanishBot with the same pytector patch; assert .language == "es";
    #   and that an explicit language="en" kwarg overrides the class attribute — bounded by the
    #   personality-attribute precedence (kwarg > class attr > None).


@pytest.mark.asyncio
async def test_chatbot_manual_config_keeps_none():
    """Chatbot.from_manual_config no longer forces "en" (hard cut)."""
    bot = Chatbot.__new__(Chatbot)
    bot.logger = MagicMock()
    # FILL IN: stub ONLY what from_manual_config needs (patch bot._initial_embedding_model;
    #   set the few attributes it reads without a getattr default); await bot.from_manual_config();
    #   assert bot.language is None — bounded by spec AC2. Do not stub language itself.


def test_chatbot_from_db_language_default_is_none():
    # FILL IN: assert Chatbot._from_db(<bare instance>, MagicMock(spec=[]), "language", default=None) is None,
    #   and that a row whose language is "" also yields None — bounded by spec AC2.
    pass
```
**Why**: the class-attribute test proves `JiraSpecialist` subclasses can declare a team
language declaratively. The Chatbot test drives the real `from_manual_config` coroutine
rather than asserting on source text.

### FILL IN checklist
- [ ] `test_language_class_attribute_is_honored` — construction + precedence assertions
- [ ] `test_chatbot_manual_config_keeps_none` — minimal stubbing; never stub `language`
- [ ] `test_chatbot_from_db_language_default_is_none` — both absent and `""` cases

---

## Acceptance Criteria

- [ ] `AbstractBot` exposes `language: Optional[str]`, default `None`; `Agent` and `JiraSpecialist` inherit it.
- [ ] Precedence is kwarg > class attribute > `None`.
- [ ] `Chatbot` no longer defaults `language` to `"en"` at `chatbot.py:244` or `:422`.
- [ ] The value is stored raw (no normalization in `__init__`).
- [ ] Existing prompt integration tests still pass (`test_abstractbot_integration.py`).
- [ ] `ruff check` clean on both modified source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_bot_language_attribute.py -q`
- `pytest packages/ai-parrot/tests/bots/prompts/test_abstractbot_integration.py -q`

---

## Test Specification

See the `test_bot_language_attribute.py` blueprint block above.

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

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
