# TASK-2815: Client migration — Google, Google analysis mixin, Live + all-clients signature test

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2812, TASK-2813, TASK-2814
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, group C. `google/client.py` and `google/analysis.py`
build provider history by hand (`UserContent`/`ModelContent`) in several
places and do not always go through `get_messages_for_api`, so they are the
easiest to miss. `live.py` only loses the `conversation_memory` ctor kwarg
and its docstrings. Because this is the last client group, it also adds the
parametrized `test_all_client_ask_signatures` that enforces the new
signature across **every** concrete client (spec §4 M5 row) — which is why
it depends on TASK-2813/2814.

---

## Scope

- `clients/google/client.py`: `ask` `:2975` (ctx `:3095`, upd `:3714`; note the comment at `:3358` referencing the old helper), `ask_stream` `:3901` (ctx `:3992`, upd `:4434`), third path ctx `:5031` / upd `:5164` (find enclosing method). Override `_format_history` → `[UserContent(parts=[Part.from_text(...)]) / ModelContent(...)]` (verify the exact `google.genai.types` constructors already used in the file).
- `clients/google/analysis.py`: ctx `:259`, `:808`; upd `:476`, `:900`; hand-built history loops at `:282-292` and `:821-823` → replace with `self._format_history(history)`.
- `clients/live.py`: `ask` `:1492`, `ask_stream` `:1699` signatures; ctor kwarg `conversation_memory` `:558`, forwarded `:593`; docstrings `:9`, `:503-507` ("reuses conversation_memory").
- CREATE `packages/ai-parrot/tests/unit/clients/test_all_client_ask_signatures.py`: parametrized over every concrete `AbstractClient` subclass importable from `parrot.clients` (enumerate via `parrot.clients.factory` or a hard list of the 13 modules + `google/client.py`), assert `ask` and `ask_stream` signatures have `history`, lack `user_id` and `session_id`; also assert no subclass defines `conversation_memory` in `__init__`'s signature.
- CREATE `packages/ai-parrot/tests/unit/clients/test_google_format_history.py`.
- Minimal edits so `packages/ai-parrot/tests/test_google_client.py`, `tests/unit/test_google_document_understanding.py`, `packages/ai-parrot/tests/unit/clients/test_gemini_multiround_usage.py`, `packages/ai-parrot/tests/clients/test_nova.py` run (sweep in TASK-2817).

**NOT in scope**: bots; other clients.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | signatures, `_format_history`, 3 paths |
| `packages/ai-parrot/src/parrot/clients/google/analysis.py` | MODIFY | 2 paths + 2 hand-built history loops |
| `packages/ai-parrot/src/parrot/clients/live.py` | MODIFY | ctor kwarg, signatures, docstrings |
| `packages/ai-parrot/tests/unit/clients/test_all_client_ask_signatures.py` | CREATE | cross-client guard |
| `packages/ai-parrot/tests/unit/clients/test_google_format_history.py` | CREATE | Google shape |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient       # clients/base.py:230 (post-TASK-2812)
from parrot.memory.render import HistoryMessage      # TASK-2809
# google.genai types: see existing imports at top of clients/google/analysis.py (UserContent, ModelContent used at :282,:292,:821,:823)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/google/client.py  (pre-TASK-2812 numbers; re-grep)
    async def ask(...)        # line 2975 ; ctx :3095 ; comment referencing helper :3358 ; upd :3714
    async def ask_stream(...) # line 3901 ; ctx :3992 ; upd :4434
    (third path)              # ctx :5031 ; upd :5164
# packages/ai-parrot/src/parrot/clients/google/analysis.py
    ctx :259 ; hand-built history: history.append(UserContent(parts=parts)) :282 / ModelContent :292 ; upd :476
    ctx :808 ; UserContent :821 / ModelContent :823 ; upd :900
# packages/ai-parrot/src/parrot/clients/live.py
    module docstring "Reuses tool_manager, conversation_memory, preset system"   # line 9
    class docstring                                                             # lines 503-507
    def __init__(..., conversation_memory: Optional[ConversationMemory] = None, ...)   # line 558 ; forwarded :593
    async def ask(...)        # line 1492
    async def ask_stream(self, *args, **kwargs)   # line 1699
# concrete client modules (13): base, bedrock, claude_agent, claude, gemma4, google/client, gpt, grok, groq, hf, live, openai_base, zai
```

### Does NOT Exist
- ~~`self.conversation_memory`~~ etc. — removed by TASK-2812.
- ~~`GoogleClient._format_history`~~ — you create it; today the mapping is inline in `analysis.py`.
- ~~a registry of "all client classes" for tests~~ — check `parrot/clients/factory.py` (exists, 9.5K) for a provider map before hard-coding the list.

---

## Implementation Notes

### Pattern to Follow
```python
def _format_history(self, history):
    out = []
    for m in history:
        part = types.Part.from_text(text=m.content)          # verify constructor in this file
        out.append(types.UserContent(parts=[part]) if m.role == "user" else types.ModelContent(parts=[part]))
    return out
```
Signature test:
```python
@pytest.mark.parametrize("cls", ALL_CLIENT_CLASSES, ids=lambda c: c.__name__)
def test_all_client_ask_signatures(cls):
    for meth in ("ask", "ask_stream"):
        params = inspect.signature(getattr(cls, meth)).parameters
        if "kwargs" in params and len(params) <= 3:   # live.ask_stream(*args, **kwargs) passthrough
            continue
        assert "history" in params and "user_id" not in params and "session_id" not in params, (cls, meth)
```

### Key Constraints
- `grep -rn "user_id\|session_id\|conversation_memory\|conversation_history" packages/ai-parrot/src/parrot/clients/` must be empty when this task closes (this is spec acceptance criterion 3/4).
- Google `analysis.py` is a mixin: it must call `self._format_history` (resolved on the concrete client), not import the Google client class.

---

## Acceptance Criteria

- [ ] `test_all_client_ask_signatures` green for every concrete client.
- [ ] `test_google_format_history` green.
- [ ] `grep -rn "conversation_memory\|_update_conversation_memory\|_prepare_conversation_context\|get_messages_for_api\|user_id\|session_id" packages/ai-parrot/src/parrot/clients/` → zero lines (document any telemetry-only survivor and justify).
- [ ] Listed existing tests run; `ruff check` clean; imports OK.

---

## Test Specification

See Pattern above; plus:
```python
def test_google_format_history():
    msgs = GoogleClientStub()._format_history([HistoryMessage("user", "q"), HistoryMessage("assistant", "a")])
    assert type(msgs[0]).__name__ == "UserContent" and type(msgs[1]).__name__ == "ModelContent"
```

---

## Agent Instructions

1. Read spec §3 M5 + §7 gotcha "Google analysis.py". 2. Re-grep line numbers. 3. One commit per file + one for the tests.
4. Move to `completed/`, update index, fill note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
