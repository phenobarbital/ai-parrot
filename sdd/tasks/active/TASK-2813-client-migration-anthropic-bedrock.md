# TASK-2813: Client migration — `claude.py`, `claude_agent.py`, `bedrock.py`

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2812
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, group A (Anthropic API, Claude Agent SDK, AWS Bedrock).
Each override of `ask`/`ask_stream` drops `user_id`/`session_id`, accepts
`history`, replaces `_prepare_conversation_context(...)` with
`self._build_messages(prompt, files, history)`, deletes the
`_update_conversation_memory(...)` call, and overrides `_format_history`
only where the provider shape differs (Bedrock Converse). `claude.py` has
one extra path: `ask_to_image` calls `get_messages_for_api()` directly.

---

## Scope

- `clients/claude.py`: `ask` (`:446`; context `:487`; memory update `:730`), `ask_stream` (`:894`; `:943`; `:1193`), third update at `:1542` (find enclosing method), `ask_to_image` (`:1350`; direct `conversation_memory.get_history/create_history` + `get_messages_for_api()` at `:1400-1414`) → take `history=` and use `_format_history`, or drop history support explicitly (document choice).
- `clients/claude_agent.py`: `ask` (`:555`), `ask_stream` (`:730`) — signature only; check for any `conversation_memory` use (`grep` — none found today).
- `clients/bedrock.py`: `ask` (`:701`; context `:788`; update `:1029`), `ask_stream` (`:1078`; `:1139`; `:1299`). Override `_format_history` to the Converse shape `{"role": ..., "content": [{"text": ...}]}`; the docstring at `:416`/`:477` referencing `_prepare_conversation_context` must be rewritten.
- Any `turn_id = str(uuid.uuid4())` the clients generate stays only for `AIMessage.turn_id`.
- The `system_prompt` returned by the old helper is gone: pass the caller's `system_prompt` straight through.
- Tests: adapt existing client tests that pass ids (`tests/clients/test_anthropic_fallback.py`, `tests/clients/test_anthropic_sdk_097.py`, `tests/clients/test_claude_agent.py`, `tests/unit/test_anthropic_invoke.py`, `packages/ai-parrot/tests/clients/test_bedrock_*.py` ×6, `packages/ai-parrot/tests/unit/clients/test_bedrock_multiround_usage.py`, `test_claude_multiround_usage.py`) **only as far as needed to make them run**; the systematic sweep is TASK-2817.

**NOT in scope**: other clients; bots; `test_all_client_ask_signatures` (TASK-2815).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude.py` | MODIFY | signatures, `_build_messages`, remove memory writes, `ask_to_image` |
| `packages/ai-parrot/src/parrot/clients/claude_agent.py` | MODIFY | signatures |
| `packages/ai-parrot/src/parrot/clients/bedrock.py` | MODIFY | signatures, `_format_history` override, docstrings |
| `packages/ai-parrot/tests/unit/clients/test_bedrock_format_history.py` | CREATE | Converse shape test |
| (existing tests listed above) | MODIFY | minimal edits to run |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient       # clients/base.py:230 (post-TASK-2812: has _format_history/_build_messages, history=)
from parrot.memory.render import HistoryMessage      # TASK-2809
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/claude.py
    async def ask(...)                                                   # line 446
        messages, conversation_history, system_prompt = await self._prepare_conversation_context(prompt, files, user_id, session_id, system_prompt)  # line 487
        await self._update_conversation_memory(user_id, session_id, conversation_history, messages, system_prompt, turn_id, original_prompt, assistant_response_text, tools_used)  # line 730
    async def ask_stream(...)                                            # line 894 ; context :943 ; update :1193
    (third update)                                                       # line 1542 — identify enclosing method with awk before editing
    async def ask_to_image(...)                                          # line 1350 ; conversation_memory.get_history/create_history :1400-1410 ; messages = conversation_history.get_messages_for_api() :1414

# packages/ai-parrot/src/parrot/clients/claude_agent.py
    async def ask(...)                                                   # line 555
    async def ask_stream(...)  # type: ignore[override]                  # line 730

# packages/ai-parrot/src/parrot/clients/bedrock.py
    docstrings referencing _prepare_conversation_context                 # lines 416, 477
    async def ask(...)                                                   # line 701 ; context :788 ; update :1029
    async def ask_stream(...)                                            # line 1078 ; context :1139 ; update :1299
```

### Does NOT Exist
- ~~`self.conversation_memory`~~ on any client after TASK-2812 — every remaining reference is a bug to remove.
- ~~`_prepare_conversation_context` / `_update_conversation_memory`~~ — removed by TASK-2812.
- ~~`ConversationHistory.get_messages_for_api`~~ — removed by TASK-2809.
- ~~`user_id`/`session_id` on `AbstractClient.ask`~~ — removed by TASK-2812; an override that keeps them is an `inspect.signature` test failure in TASK-2815.

---

## Implementation Notes

### Pattern to Follow
```python
# before
messages, conversation_history, system_prompt = await self._prepare_conversation_context(
    prompt, files, user_id, session_id, system_prompt)
...
await self._update_conversation_memory(user_id, session_id, conversation_history, ...)

# after
messages = self._build_messages(prompt, files, history)
...
# (no memory write)
```
Bedrock:
```python
def _format_history(self, history):
    return [{"role": m.role, "content": [{"text": m.content}]} for m in history]
```

### Key Constraints
- Keep `AIMessageFactory.from_claude(...)` calls unchanged apart from removed variables.
- `grep -n "user_id\|session_id\|conversation_memory\|conversation_history" <file>` must be empty (or only in unrelated telemetry) for each of the three files when done.

---

## Acceptance Criteria

- [ ] Three files: no `user_id`/`session_id` in `ask`/`ask_stream` signatures; no memory references; `history` accepted and rendered.
- [ ] `test_bedrock_format_history` passes.
- [ ] The listed existing tests run (pass, or are adapted minimally with a TODO for TASK-2817).
- [ ] `ruff check` clean on the three files; `python -c "import parrot.clients.claude, parrot.clients.bedrock, parrot.clients.claude_agent"` OK.

---

## Test Specification

```python
def test_bedrock_format_history():
    c = BedrockClient.__new__(BedrockClient)   # or a fixture the bedrock tests already use
    out = AbstractClient._format_history.__get__(c)  # ensure override is used: call c._format_history directly
    msgs = c._format_history([HistoryMessage("user", "q"), HistoryMessage("assistant", "a")])
    assert msgs == [{"role": "user", "content": [{"text": "q"}]}, {"role": "assistant", "content": [{"text": "a"}]}]
```

---

## Agent Instructions

1. Read spec §3 M5 + §7 gotchas (`ask_to_image`). 2. Verify line numbers with `grep -n` first — they shift after TASK-2812.
3. One commit per file is fine. 4. Move to `completed/`, update index, fill note (state the `ask_to_image` decision).

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
