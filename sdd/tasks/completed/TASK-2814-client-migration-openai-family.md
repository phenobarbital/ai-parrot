# TASK-2814: Client migration — OpenAI-compatible family, Grok, HF, Gemma4, Z.AI

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2812
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, group B: `gpt.py`, `openai_base.py`, `groq.py`, `zai.py`,
`hf.py`, `gemma4.py`, and `grok.py` — the latter carries its **own** memory
logic instead of the base helpers (`grok.py:265/423/505/570`) and must lose
it entirely. Same mechanical change as TASK-2813; the default
`_format_history` (text content blocks) fits the OpenAI-style message
shape — verify per client whether it expects `content` as a plain string
and override to `{"role", "content": m.content}` where needed.

---

## Scope

Per file, for every `ask`/`ask_stream` override: drop `user_id`/`session_id`,
add `history`, replace `_prepare_conversation_context` with
`self._build_messages(prompt, files, history)`, delete
`_update_conversation_memory` calls, pass `system_prompt` through unchanged.

- `clients/openai_base.py`: `ask` `:522` (ctx `:582`, upd `:727`), `ask_stream` `:904` (ctx `:956`, upd `:1170`). Decide the `_format_history` shape once here — the OpenAI-compatible subclasses inherit it.
- `clients/gpt.py`: `ask` `:683` (ctx `:746`, upd `:974`), `ask_stream` `:1031` (ctx `:1079`, upd `:1458`), third path ctx `:1501` / upd `:1572` (find enclosing method).
- `clients/groq.py`: `ask` `:333`, `ask_stream` `:748`; five ctx calls `:358, :775, :1069, :1177, :1306`; five updates `:696, :867, :1106, :1239, :1342` (find enclosing methods — some are non-`ask` helpers that must also take `history` or drop it).
- `clients/zai.py`: `ask` `:408`, `ask_stream` `:624`; ctx `:137` (enclosing method?), updates `:557, :850`.
- `clients/hf.py`: `ask` `:355` (ctx `:394`, upd `:488`), `ask_stream` `:523`.
- `clients/gemma4.py`: `ask` `:463` (ctx `:510`, upd `:630`), `ask_stream` `:668`.
- `clients/grok.py`: `ask` `:191`, `ask_stream` `:440`; remove the two `if self.conversation_memory and user_id and session_id:` blocks (`:265`, `:505`) and both `add_turn` calls (`:423`, `:570`); render `history` via `_build_messages`.
- Minimal test edits so `tests/clients/test_openai_base_parity.py`, `test_openai_compatible_defaults.py`, `test_moonshot_client.py`, `packages/ai-parrot/tests/unit/clients/test_openai_multiround_usage.py`, `test_groq_multiround_usage.py`, `test_grok_multiround_usage.py`, `test_codex_agent.py` run; full sweep is TASK-2817.
- Add `packages/ai-parrot/tests/unit/clients/test_grok_no_private_memory.py`: AST/grep test asserting `grok.py` has no `conversation_memory` token.

**NOT in scope**: Google/Live clients (TASK-2815); Anthropic/Bedrock (TASK-2813); bots.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY | signatures, `_format_history` decision |
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | signatures, 3 paths |
| `packages/ai-parrot/src/parrot/clients/groq.py` | MODIFY | signatures, 5 paths |
| `packages/ai-parrot/src/parrot/clients/zai.py` | MODIFY | signatures |
| `packages/ai-parrot/src/parrot/clients/hf.py` | MODIFY | signatures |
| `packages/ai-parrot/src/parrot/clients/gemma4.py` | MODIFY | signatures |
| `packages/ai-parrot/src/parrot/clients/grok.py` | MODIFY | remove private memory logic |
| `packages/ai-parrot/tests/unit/clients/test_grok_no_private_memory.py` | CREATE | grep/AST guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient       # clients/base.py:230 (post-TASK-2812)
from parrot.memory.render import HistoryMessage      # TASK-2809
```

### Existing Signatures to Use
```python
# All line numbers as of dev@2026-09-04 BEFORE TASK-2812; re-grep before editing.
# openai_base.py : ask :522 | ask_stream :904 | ctx :582,:956 | upd :727,:1170
# gpt.py         : ask :683 | ask_stream :1031 | ctx :746,:1079,:1501 | upd :974,:1458,:1572
# groq.py        : ask :333 | ask_stream :748 | ctx :358,:775,:1069,:1177,:1306 | upd :696,:867,:1106,:1239,:1342
# zai.py         : ask :408 | ask_stream :624 | ctx :137 | upd :557,:850
# hf.py          : ask :355 | ask_stream :523 | ctx :394 | upd :488
# gemma4.py      : ask :463 | ask_stream :668 | ctx :510 | upd :630
# grok.py        : ask :191 | ask_stream :440 | own memory: `if self.conversation_memory and user_id and session_id:` :265,:505 ; add_turn :423,:570
#                  turn = ConversationTurn(turn_id=..., user_id=..., user_message=prompt, assistant_response=ai_message.to_text, ...) :415-422 ← delete
```

### Does NOT Exist
- ~~`self.conversation_memory`~~, ~~`_prepare_conversation_context`~~, ~~`_update_conversation_memory`~~ — gone after TASK-2812.
- ~~`ConversationTurn` import in any client~~ — must be removed from `grok.py`.
- ~~`user_id`/`session_id` on `ask`~~ — removed; keeping them fails TASK-2815's signature test.

---

## Implementation Notes

### Pattern to Follow
See TASK-2813. For OpenAI-style APIs that reject list `content` for plain text, override once in `OpenAIBaseClient`:
```python
def _format_history(self, history):
    return [{"role": m.role, "content": m.content} for m in history]
```
Check what `_prepare_messages()` produces for the current turn in these clients and keep history consistent with it.

### Key Constraints
- Find the enclosing method of every ctx/upd line with `awk 'NR<=L && /^    (async )?def /{d=NR": "$0} END{print d}'` before editing; several are helper methods (`invoke`, `ask_with_tools`, image/audio paths) that must also switch to `history=` or explicitly drop history.
- `grep -n "user_id\|session_id\|conversation_memory\|conversation_history\|ConversationTurn" <file>` empty for all seven files when done.

---

## Acceptance Criteria

- [ ] Seven files: no ids in `ask`/`ask_stream` signatures; no memory references; `history` rendered via `_build_messages`.
- [ ] `test_grok_no_private_memory` passes.
- [ ] Listed existing tests run (pass or minimally adapted with TODO for TASK-2817).
- [ ] `ruff check` clean; `python -c "import parrot.clients.gpt, parrot.clients.groq, parrot.clients.grok, parrot.clients.zai, parrot.clients.hf, parrot.clients.gemma4, parrot.clients.openai_base"` OK.

---

## Test Specification

```python
def test_grok_has_no_private_memory_path():
    src = Path(parrot.clients.grok.__file__).read_text()
    assert "conversation_memory" not in src and "ConversationTurn" not in src
```

---

## Agent Instructions

1. Read spec §3 M5. 2. Re-grep all line numbers. 3. One commit per client.
4. Move to `completed/`, update index, fill note (list every non-`ask` helper you changed).

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**:
All 7 files migrated: 14 `ask`/`ask_stream` signatures now take
`history: Optional[Sequence[HistoryMessage]]` and neither id; 13
`_prepare_conversation_context(...)` calls became `self._build_messages(prompt, files,
history)`; 14 `_update_conversation_memory(...)` calls deleted. Verified: the grep for
`conversation_memory|_prepare_conversation_context|_update_conversation_memory|get_messages_for_api`
returns **zero** lines across all seven files, and an `inspect.signature` sweep confirms
all 14 entry points.

- **`_format_history` shape decision (the task asks for it once, here):** the OpenAI
  family **inherits the base implementation unchanged**. The OpenAI chat-completions
  wire protocol accepts `content` as a list of typed parts, which is exactly what the
  base emits (`[{"type": "text", "text": ...}]`), and it is also what these clients'
  own `_prepare_messages` already produces for the current turn — so history and current
  turn stay uniformly shaped with no override. Only Bedrock Converse (TASK-2813) and
  Google (TASK-2815) need one.
- **`grok.py`** — private memory path fully removed: both
  `if self.conversation_memory and user_id and session_id:` history-replay blocks and
  both hand-rolled `ConversationTurn(...)` + `add_turn(...)` writes, plus the now-dead
  `from ..memory import ConversationTurn`. Grok does not use `_build_messages` (the xAI
  SDK wants `chat.append()` calls, not a message list), so it iterates the rendered
  `history` and dispatches on `message.role`.
  **Bug found and fixed in passing:** grok's replay read `turn.input` / `turn.output` —
  attributes `ConversationTurn` does not have (they are `user_message` /
  `assistant_response`). That replay would have raised `AttributeError` on any second
  turn. `HistoryMessage` removes the guesswork.
  Grok's `ask` `turn_id` is now passed to `AIMessageFactory.create_message(turn_id=...)`
  instead of being dropped — spec §3 M5 says a client-generated `turn_id` is kept "only
  for `AIMessage.turn_id`", and this makes `ConversationTurn.from_ai_message()` able to
  reuse it.
- **`hf.py`** — had its own `_get_conversation_history(user_id, session_id)`, which was a
  **stub that always returned `[]`** ("This would be implemented based on your memory
  system"). Replaced with `_history_as_turns(history)`, adapting `HistoryMessage` to the
  flat `{"role", "content"}` dicts `_prepare_prompt` wants. This client never actually
  replayed history before; now it does. Its `_build_messages` result was unused (it
  builds a flat prompt string), so that call was dropped rather than left dead.
- **`zai.py`** — **name collision resolved.** It already owned a private
  `async def _build_messages(prompt, files, user_id, session_id, system_prompt)` that
  would now shadow `AbstractClient._build_messages` (added in TASK-2812). Renamed to
  `_build_zai_messages`, made synchronous (it never awaited anything), and rewritten to
  **delegate** to the base helper before adding its two Z.AI-specific extras (leading
  `system` message + content normalization). Both call sites updated.
- **`gpt.py::ask_to_image`** — same decision as `claude.py`'s: keeps history support via
  `history=` + `_format_history`, honouring its existing `no_memory=True` flag. Not
  listed in the task's scope but it called the removed helper, so it had to move.
- **`groq.py`'s three stateless analysis helpers** (`summarize_text`,
  `analyze_sentiment`, `analyze_product_review`) — the task flagged these as "non-`ask`
  helpers that must also take `history` or drop it". **Decision: drop.** They are
  one-shot analyses of a supplied text; replaying an unrelated chat history into a
  summarization prompt was never intentional. They now pass `None` explicitly with a
  comment. Their `user_id`/`session_id` parameters remain (they only reach
  `AIMessageFactory` as response metadata) and they are not `ask`/`ask_stream`, so the
  M5 signature test does not cover them.
- Tests: `test_grok_no_private_memory.py` (8 passed) — AST + token guard over
  `conversation_memory` / `ConversationTurn` / `add_turn` / `get_conversation` /
  `get_messages_for_api`, an import check that only `HistoryMessage` comes from
  `parrot.memory`, the signature check, and an AST assertion that both entry points
  actually read `history` and append assistant turns.
- Suite movement: client suites went **10 newly-red → 4** (18 failed / 454 passed vs the
  14 failed / 416 passed `dev` baseline). The remaining 4 are all
  `test_gemini_multiround_usage.py` → TASK-2815. `test_grok_multiround_usage`,
  `test_openai_multiround_usage` and `test_bedrock_mantle` are now green. As in
  TASK-2813, **no existing test needed editing** — the "minimal test edits" part of the
  scope proved unnecessary.
- Lint: a full `ruff` diff against the same files on `dev` shows **zero new findings**,
  and two pre-existing ones incidentally fixed (`grok.py` E402, `openai_base.py` unused
  `typing.Optional`). The 10 findings that remain are all identical to `dev`.

**Deviations from spec**:
1. **Ids preserved via the FEAT-228 ContextVars, not deleted** — same approach as
   TASK-2813 and for the same reason. 29 references across the 7 files
   (`AIMessageFactory(user_id=, session_id=)`, `HumanInteractionInterrupt.session_id`)
   are metadata/telemetry, not conversation storage, so they now read
   `current_user_id.get()` / `current_session_id.get()`. `BaseBot` binds both at the top
   of every call, so the values are unchanged. Uses inside `resume(session_id, ...)`
   were left alone — different API, explicit parameter.
2. **Dead locals removed.** 20 lines (`tools_used`, `assistant_response_text`,
   `assistant_content`, `conversation_session`, `system_prompt`, `all_tool_calls`) whose
   only consumer was a deleted memory write. Two of them were multi-line assignments
   whose closing paren had to be cleaned up by hand, and `openai_base.ask_stream`'s
   `if assistant_content:` guard was removed entirely — it guarded nothing but the write,
   and a comment is not a valid Python block body. All 10 client modules were re-checked
   with `ast.parse` afterwards.
3. **`gpt.py::ask_to_image` and `groq.py`'s three analysis helpers** were touched beyond
   the task's literal `ask`/`ask_stream` scope, because they called the removed base
   helpers and would otherwise be `AttributeError` at runtime.
