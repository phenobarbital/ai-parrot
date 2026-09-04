# TASK-2812: `AbstractClient` hard cut — memory-less clients, `history=` parameter

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2809
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. The base client loses every trace of conversation memory
and of `user_id`/`session_id`, and gains `history: Optional[Sequence[HistoryMessage]]`
plus two helpers: `_format_history()` (provider shape, overridable) and
`_build_messages()` (formatted history + current turn). Hard cut: no
deprecation kwargs, no shims (spec §1 Goals; decision recorded in §8).

This task changes **only** `clients/base.py`. The 13 concrete clients still
override `ask()` with the old signature and still call the removed helpers
until TASK-2813/2814/2815 — so after this task the concrete clients are
temporarily broken at call time (not at import time, as long as the helper
calls are inside method bodies). Verify `python -c "import parrot.clients"`
still passes and note the expected breakage in the completion note. The
per-spec worktree runs tasks sequentially, so nothing ships in this state.

---

## Scope

- REMOVE from `packages/ai-parrot/src/parrot/clients/base.py`:
  - imports `ConversationHistory, ConversationMemory, FileConversationMemory, InMemoryConversation` (`:28-31`; check `:27-32` for the exact block);
  - `conversation_memory` ctor param (`:362`) and `self.conversation_memory = conversation_memory or InMemoryConversation()` (`:406`);
  - `_get_chatbot_key` (`:1174`), `start_conversation` (`:1179`), `get_conversation` (`:1191`), `clear_conversation` (`:1201`), `delete_conversation` (`:1208`), `list_user_conversations` (`:1216`);
  - `_prepare_conversation_context` (`:2269-2373`) and `_update_conversation_memory` (`:2375-2407`).
- MODIFY `ask` (`:1638`) and `ask_stream` (`:1679`): drop `user_id`, `session_id`; add `history: Optional[Sequence[HistoryMessage]] = None` right after `system_prompt`. Update the docstrings.
- ADD `_format_history(self, history: Sequence[HistoryMessage]) -> List[Dict[str, Any]]`:
  default `[{"role": m.role, "content": [{"type": "text", "text": m.content}]} for m in history]`.
- ADD `_build_messages(self, prompt: str, files, history) -> List[Dict[str, Any]]`:
  `self._format_history(history or ()) + [self._prepare_messages(prompt, files)[0]]`, preserving the
  missing-file filter from the old helper (`:2353-2366`) — files that do not exist are logged and skipped.
- Type import: `from parrot.memory.render import HistoryMessage` (leaf module; verify it does not pull Redis).
- Tests: `packages/ai-parrot/tests/unit/clients/test_abstract_client_memoryless.py`.

**NOT in scope**: concrete clients, bots, tests of concrete clients.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | removals + `history` + two helpers |
| `packages/ai-parrot/tests/unit/clients/test_abstract_client_memoryless.py` | CREATE | tests below |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient          # clients/base.py:230
from parrot.memory.render import HistoryMessage         # created by TASK-2809
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
from ..memory import (ConversationHistory, ConversationMemory, InMemoryConversation, FileConversationMemory)  # ~:27-32 ← remove
class AbstractClient(EventEmitterMixin, ABC):                                   # line 230
    def __init__(self, conversation_memory: Optional[ConversationMemory] = None, preset=None, tools=None,
                 use_tools=False, debug=True, tool_manager=None, **kwargs)       # line 360
        self.conversation_memory = conversation_memory or InMemoryConversation() # line 406 ← remove
    def _get_chatbot_key(self, chatbot_id=None) -> Optional[str]                 # line 1174 ← remove
    async def start_conversation / get_conversation / clear_conversation / delete_conversation / list_user_conversations  # 1179/1191/1201/1208/1216 ← remove
    def _prepare_messages(self, prompt, files=None) -> List[Dict[str, Any]]      # line 1582  KEEP (encodes current turn + files)
    async def ask(self, prompt, model, max_tokens=None, temperature=0.7, files=None, system_prompt=None,
                  structured_output=None, user_id=None, session_id=None, tools=None, use_tools=None,
                  deep_research=False, background=False, lazy_loading=False) -> MessageResponse   # line 1638
    async def ask_stream(...)                                                    # line 1679
    async def _prepare_conversation_context(self, prompt, files, user_id, session_id, system_prompt, stateless=False)  # line 2269 ← remove
        # missing-file filter to preserve                                        # lines 2353-2366
        # new_user_message = self._prepare_messages(prompt, safe_files)[0]       # line 2369
    async def _update_conversation_memory(...)                                   # line 2375 ← remove
```

### Does NOT Exist
- ~~`AbstractClient._format_history`~~, ~~`_build_messages`~~, ~~`history=`~~ — you create them.
- ~~`AbstractClient.chatbot_id`~~ — never set anywhere.
- ~~`stateless` as a named `ask()` parameter~~ — it was a parameter of the removed helper only; do not re-add it. (`parrot_tools/security/summarizer.py:272,416` pass `stateless=True` to a concrete client's `ask` — TASK-2816 deletes those.)
- ~~`parrot/clients/abstract_client.py`~~ — stale path in `.agent/CONTEXT.md`.

---

## Implementation Notes

### Pattern to Follow
```python
def _format_history(self, history: Sequence[HistoryMessage]) -> List[Dict[str, Any]]:
    return [{"role": m.role, "content": [{"type": "text", "text": m.content}]} for m in history]

def _build_messages(self, prompt: str, files: Optional[List[Union[str, Path]]],
                    history: Optional[Sequence[HistoryMessage]]) -> List[Dict[str, Any]]:
    safe_files = self._existing_files(files)           # extracted from old :2353-2366
    messages = self._format_history(history or ())
    messages.append(self._prepare_messages(prompt, safe_files)[0])
    return messages
```

### Key Constraints
- Zero references to `parrot.memory` storage classes remain in `clients/base.py`.
- `grep -n "user_id\|session_id" packages/ai-parrot/src/parrot/clients/base.py` → only lines unrelated to `ask` (e.g. telemetry) or none; document survivors.
- Keep FEAT-302's guarantee: current turn encoded exactly once, after history.

---

## Acceptance Criteria

- [ ] `test_client_has_no_memory_surface`: `AbstractClient` lacks `conversation_memory`, `_prepare_conversation_context`, `_update_conversation_memory`, `start_conversation`, `get_conversation`, `clear_conversation`, `delete_conversation`, `list_user_conversations`, `_get_chatbot_key`.
- [ ] `test_ask_signature`: `inspect.signature(AbstractClient.ask).parameters` has `history`, lacks `user_id`/`session_id`; same for `ask_stream`.
- [ ] `test_format_history_default_shape`; `test_build_messages_history_then_prompt` (order, single current turn, missing file skipped with a logged error).
- [ ] `python -c "import parrot.clients, parrot.memory"` OK; `ruff check packages/ai-parrot/src/parrot/clients/base.py` clean.
- [ ] Completion note lists which concrete-client tests are expected red until TASK-2815.

---

## Test Specification

```python
def test_client_has_no_memory_surface():
    for name in ("conversation_memory", "_prepare_conversation_context", "_update_conversation_memory",
                 "start_conversation", "get_conversation", "clear_conversation", "delete_conversation",
                 "list_user_conversations", "_get_chatbot_key"):
        assert not hasattr(AbstractClient, name), name

def test_build_messages_history_then_prompt(tmp_path):
    c = StubClient()
    hist = [HistoryMessage("user", "q1"), HistoryMessage("assistant", "a1")]
    msgs = c._build_messages("q2", [str(tmp_path / "missing.pdf")], hist)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[-1]["content"][0]["text"] == "q2"
```

---

## Agent Instructions

1. Read spec §2 New Public Interfaces + §3 M4. 2. Verify contract lines. 3. Tests first.
4. Commit only listed files. 5. Move to `completed/`, update index, fill note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
