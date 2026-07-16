---
type: Wiki Overview
title: 'TASK-1753: Bridge wiring + config knobs + lazy exports'
id: doc:sdd-tasks-completed-task-1753-bridge-wiring-config-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of FEAT-303 (spec §3). Wires the Semantic UI Model
relates_to:
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.semantic
  rel: mentions
- concept: mod:parrot.utils
  rel: mentions
---

# TASK-1753: Bridge wiring + config knobs + lazy exports

**Feature**: FEAT-303 — UX for Custom Engine Copilot Agents (Semantic UI Model → Adaptive Cards)
**Spec**: `sdd/specs/ux-custom-engine-copilot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1752
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of FEAT-303 (spec §3). Wires the Semantic UI Model
into the live turn pipeline: `ParrotM365Agent._handle_message()` detects a
`SemanticUIResult` on the agent's response and sends a card instead of plain
text, with bulletproof fallback. Adds the operator config knobs and exposes
the new public names via the package's lazy-export mechanism.

---

## Scope

- **`agent.py`** — modify `_handle_message()` (currently line 214; success
  send at line 298):
  - Replace ONLY the success-path send
    (`await self._send_text(context, str(response.content))`) with a card
    seam:
    1. Extract the semantic result: `response.structured_output` if it is a
       `SemanticUIResult` instance, else `response.data` if it is one, else
       `None`. Use `isinstance` — no dict duck-typing (spec §7).
    2. If `None`, or `self._cards_enabled` is False → existing
       `_send_text(context, str(response.content))` behavior, unchanged.
    3. Otherwise render via `cards.render_card(result,
       max_table_rows=..., max_card_bytes=...)`, build the attachment with
       `cards.build_card_attachment()`, and send ONE
       `Activity(type=message, text=cards.render_text(result),
       attachments=[...])` (same envelope as `_emit_adaptive_card`,
       agent.py:733-737).
    4. Wrap the entire card branch in try/except: on ANY exception, log with
       `exc_info=True` and fall back to
       `_send_text(context, cards.render_text(result))` — and if even that
       raises (it must not, but belt-and-braces),
       `_send_text(context, str(response.content))`. No exception may escape
       into the outer `CredentialRequired` handler's generic error branch
       masquerading as an agent failure.
  - Do NOT touch the `except` branch handling `CredentialRequired`
    (agent.py:299-351) nor the `finally` (line 352-353).
  - Card knobs reach the agent via new constructor parameters with safe
    defaults: `enable_semantic_cards: bool = True`,
    `max_table_rows: int = 15`, `max_card_bytes: int = 25_000` (stored as
    `self._cards_enabled`, `self._max_table_rows`, `self._max_card_bytes`).
  - Import `semantic`/`cards` lazily INSIDE the method or at module top —
    module top is acceptable ONLY because neither imports
    `microsoft_agents.*` (verify before choosing top-level).
- **`models.py`** — append three dataclass fields to `MSAgentSDKConfig` with
  defaults and docstring entries: `enable_semantic_cards: bool = True`,
  `max_table_rows: int = 15`, `max_card_bytes: int = 25_000`.
- **`wrapper.py`** — pass the three config values through to the
  `ParrotM365Agent` constructor where the wrapper instantiates the bridge
  (locate the instantiation site; it constructs `agent_class or
  ParrotM365Agent` with keyword args).
- **`__init__.py`** — add to `_LAZY_EXPORTS`:
  `"SemanticUIResult": ".semantic"`, `"UIAction": ".semantic"`,
  `"render_card": ".cards"`, `"render_text": ".cards"`.
- Write unit tests in
  `packages/ai-parrot-integrations/tests/unit/test_msagent_semantic_bridge.py`.

**NOT in scope**: invoke handling for `adaptiveCard/action` (TASK-1754);
renderer internals (TASK-1752); integration/e2e tests and docs (TASK-1755).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` | MODIFY | Card seam in `_handle_message()`; constructor knobs |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py` | MODIFY | Three new `MSAgentSDKConfig` fields |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py` | MODIFY | Thread config knobs into bridge construction |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/__init__.py` | MODIFY | Lazy exports for new public names |
| `packages/ai-parrot-integrations/tests/unit/test_msagent_semantic_bridge.py` | CREATE | Unit tests for the seam + config |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.
> Do NOT invent, guess, or assume anything not listed here. Verified 2026-07-14
> against `dev` @ 16b30ee1a.

### Verified Imports
```python
# From TASK-1751/1752 (dependencies):
from parrot.integrations.msagentsdk.semantic import SemanticUIResult
from parrot.integrations.msagentsdk import cards

# SDK imports stay lazy INSIDE methods (existing pattern, agent.py:131, 704, 788):
from microsoft_agents.activity import Activity, ActivityTypes, TextFormatTypes
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py
class ParrotM365Agent:                                    # line 21
    def __init__(self, parrot_agent: AbstractBot, welcome_message: Optional[str] = None,
                 resolver=None, audit_ledger=None, broker=None, identity_mapper=None,
                 suspended_store=None, conv_ref_store=None, adapter=None,
                 agent_app_id: Optional[str] = None) -> None: ...   # line 46
        # ADD the three card kwargs at the END with defaults (keyword-only is fine).
    async def _handle_message(self, context) -> None: ... # line 214
        # THE SEAM — success path today (lines 290-298):
        #   try:
        #       response = await self.parrot_agent.ask(
        #           question=text.strip(), session_id=session_id, user_id=user_id,
        #           ctx=request_ctx, permission_context=pctx)
        #       await self._send_text(context, str(response.content))   # ← replace this line only
        #   except Exception as exc:   # CredentialRequired handling — DO NOT TOUCH (299-351)
        #   finally: _pctx_var.reset(token)                             # DO NOT TOUCH (352-353)
    async def _emit_adaptive_card(self, context, capture_url, provider) -> None:  # line 680
        # Envelope pattern to copy for the card send (lines 729-738):
        #   reply = Activity(type=ActivityTypes.message, text=<fallback text>,
        #                    attachments=[adaptive_card_attachment])
        #   await context.send_activity(reply)
    @staticmethod
    async def _send_text(context, text: str) -> None: ... # line 771

# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py
@dataclass
class MSAgentSDKConfig:                                   # line 11
    name: str                                             # line 71 (required)
    chatbot_id: str                                       # line 72 (required)
    # ... optional fields with defaults through at least:
    endpoint: Optional[str] = None                        # line 83
    # APPEND new fields AFTER the existing defaulted fields (dataclass rule:
    # defaulted fields cannot precede non-defaulted ones — all new fields
    # have defaults, so appending at the end of the field list is safe).

# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/__init__.py
_LAZY_EXPORTS = {                                          # line 18
    "MSAgentSDKConfig": ".models",
    "ParrotM365Agent": ".agent",
    "MSAgentSDKWrapper": ".wrapper",
}
__all__ = list(_LAZY_EXPORTS.keys())                       # line 24
# PEP 562 __getattr__ resolves names from _LAZY_EXPORTS (lines 27-34).

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                # line 72
    data: Optional[Any]                                    # line 86
    structured_output: Optional[Any]                       # line 194
    @property
    def content(self) -> Any: ...                          # line 235

# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py
class MSAgentSDKWrapper:                                   # line 63
    def __init__(self, agent, config: MSAgentSDKConfig, app, broker=None,
                 identity_mapper=None, agent_class: Optional[type] = None): # line 88
    # Find the ParrotM365Agent construction inside __init__ (search for
    # "ParrotM365Agent(" or "agent_class(") and thread the three knobs from
    # self.config with getattr(..., default) so older configs keep working.
```

### Does NOT Exist
- ~~`MSAgentSDKConfig.enable_semantic_cards` / `.max_table_rows` /
  `.max_card_bytes`~~ — YOU add them in this task.
- ~~`AIMessage.semantic_result` or `AIMessage.card`~~ — no such fields; the
  carriers are `structured_output` (priority) then `data`.
- ~~`OutputMode.ADAPTIVE_CARD`~~ — detection is by `isinstance` on the
  response carrier, NOT by output mode. Do not add enum members.
- ~~An existing generic card-send helper on `ParrotM365Agent`~~ —
  `_emit_adaptive_card()` is hardcoded for the static-key auth card; copy its
  envelope, do not reuse/refactor it (out of scope).
- ~~`adaptiveCard/action` routing in `on_turn()`~~ — TASK-1754 adds it; not
  present and not this task's concern.

---

## Implementation Notes

### Pattern to Follow
```python
# Card seam sketch (inside the try:, replacing line 298 only):
semantic_result = self._extract_semantic_result(response)   # new small helper
if semantic_result is None or not self._cards_enabled:
    await self._send_text(context, str(response.content))
else:
    await self._send_semantic_card(context, semantic_result, response)  # new helper

# _send_semantic_card: render → attachment → Activity(text=render_text(...),
# attachments=[...]) → send; full try/except fallback chain per Scope step 4.
# Keep helpers small and private; follow existing method-section comment style.
```

### Key Constraints
- The plain-text path must remain **byte-identical** for non-card responses —
  regression-tested by the existing suite (`test_msagent_cards.py` asserts on
  `_send_text` behavior indirectly).
- `_send_invoke_response`, auth cards, suspend/resume: untouched.
- Log at INFO when a card is sent (`result_type`, action count) and at ERROR
  (with `exc_info=True`) when falling back — never log card content (may
  contain user data).
- Lazy exports: adding names to `_LAZY_EXPORTS` + `__all__` is enough; the
  existing `__getattr__` handles resolution. Also add the names under
  `TYPE_CHECKING` imports (pattern at `__init__.py:41-44`).

### References in Codebase
- `packages/ai-parrot-integrations/tests/unit/test_msagent_cards.py` —
  `FakeTurnContext` (line 43) and `_make_agent()` (line 69) test doubles plus
  the `parrot.utils` stubbing pattern (lines 25-36) — REUSE these patterns
  (import or replicate) for the new bridge tests.

---

## Acceptance Criteria

- [ ] `SemanticUIResult` on `structured_output` → card Activity with
  attachment + text fallback populated
- [ ] `SemanticUIResult` on `data` (and not on `structured_output`) → same
- [ ] Non-card responses → `_send_text(str(response.content))` unchanged
- [ ] `enable_semantic_cards=False` → plain text even with a model present
- [ ] Renderer exception → text fallback via `render_text`; no exception
  escapes `_handle_message`
- [ ] `from parrot.integrations.msagentsdk import SemanticUIResult, UIAction, render_card, render_text` works
- [ ] Existing package tests still green:
  `pytest packages/ai-parrot-integrations/tests/unit/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/unit/test_msagent_semantic_bridge.py
# Reuse FakeTurnContext / stub patterns from test_msagent_cards.py.

class TestCardSeam:
    async def test_handle_message_sends_card(self):
        # bot.ask returns AIMessage-like with structured_output=SemanticUIResult
        # → one send_activity call; activity.attachments[0].contentType is adaptive;
        #   activity.text == render_text(result)
        ...

    async def test_handle_message_data_fallback_carrier(self): ...

    async def test_handle_message_plain_text_unchanged(self):
        # response without model → _send_text path (attachments absent)
        ...

    async def test_render_error_falls_back_to_text(self, monkeypatch):
        # monkeypatch cards.render_card to raise → activity is plain text of
        # render_text(result); no exception propagates
        ...

    async def test_semantic_cards_disabled(self): ...


class TestConfig:
    def test_new_config_fields_defaults(self):
        cfg = MSAgentSDKConfig(name="x", chatbot_id="y")
        assert cfg.enable_semantic_cards is True
        assert cfg.max_table_rows == 15
        assert cfg.max_card_bytes == 25_000


def test_lazy_exports():
    import parrot.integrations.msagentsdk as m
    assert "SemanticUIResult" in m.__all__
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1751 and TASK-1752 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Re-read `agent.py:214-353` and confirm the seam line numbers still hold
   - Confirm `_LAZY_EXPORTS` shape in `__init__.py`
4. **Update status** in `sdd/tasks/index/ux-custom-engine-copilot.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met (run the FULL unit suite, not
   just the new file)
7. **Move this file** to `sdd/tasks/completed/TASK-1753-bridge-wiring-config.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Added `_extract_semantic_result()` (checks `structured_output`
then `data`, `isinstance` only) and `_send_semantic_card()` helpers to
`agent.py`; the seam replaces only the success-path `_send_text` call at
the former line 298, wrapped in a full try/except/except fallback chain
(render error → `_send_text(render_text(result))` → last-resort
`_send_text(str(response.content))`). `CredentialRequired` except-branch
and `finally` block untouched (verified by diff). Added three constructor
kwargs (`enable_semantic_cards`, `max_table_rows`, `max_card_bytes`)
stored as `self._cards_enabled`/`_max_table_rows`/`_max_card_bytes`.
`models.py` gained the matching `MSAgentSDKConfig` fields with the same
defaults. `wrapper.py` threads them into the bridge construction via
`getattr(config, ..., default)` for backward compatibility with older
configs. `__init__.py` `_LAZY_EXPORTS`/`TYPE_CHECKING` gained
`SemanticUIResult`, `UIAction`, `render_card`, `render_text`. Full
existing package suite green (55/55 including the 5 new bridge tests);
ruff clean. New bridge tests use `monkeypatch.setitem(sys.modules, ...)`
rather than `patch.dict(sys.modules, ...)` — the latter snapshots and
restores the *entire* `sys.modules` dict on exit, which evicted real
heavy imports (e.g. `numpy`, pulled in transitively via
`parrot.auth.permission`) performed inside the `with` block and broke
later tests with "cannot load module more than once per process";
`monkeypatch.setitem` only touches the specific stubbed keys.

**Deviations from spec**: none
