# TASK-2813: Client migration — `claude.py`, `claude_agent.py`, `bedrock.py`

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: done
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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**:
- **`claude.py`** — `ask`, `ask_stream`, `ask_to_image` all take
  `history: Optional[Sequence[HistoryMessage]]` and no ids;
  `_prepare_conversation_context(...)` → `self._build_messages(prompt, files, history)`;
  both `_update_conversation_memory(...)` calls deleted (replaced by explanatory
  comments). Two locals that died with those writes (`assistant_response_text` in `ask`,
  `tools_used` in `ask_stream`) removed so ruff stays clean. The caller's
  `system_prompt` is now passed straight through — the old helper's synthesized
  "You have access to the following conversation history" system prompt is gone with it,
  which is the point (history is messages now, not prose).
- **`claude_agent.py`** — signatures only, as expected: it never touched
  `conversation_memory`.
- **`bedrock.py`** — signatures + both memory writes removed + new `_format_history`
  override emitting Converse `{"role", "content": [{"text": ...}]}`, placed next to the
  existing `_prepare_messages` override so the whole message list is uniformly
  Converse-shaped before `_to_bedrock_messages` runs. The two docstrings that named
  `AbstractClient._prepare_conversation_context` (`:416`, `:477`) rewritten to name
  `_build_messages`.
- **`ask_to_image` decision (the task asks me to state it): history support KEPT**, not
  dropped. It takes `history=` and renders it with `self._format_history(history or ())`.
  It cannot use `_build_messages` because its current turn is an image payload assembled
  inline rather than a `_prepare_messages()` text turn — so only the history half is
  formatted there and the image turn is appended afterwards. Comment in the code says so.
- Tests: `test_bedrock_format_history.py` (5 passed) covers the Converse shape, that the
  override is genuinely distinct from the base implementation, the empty case, uniform
  shaping through `_build_messages`, and the memoryless signatures.
- Suite movement: the client suites went from **71 newly-red after TASK-2812 → 10**
  (`packages/ai-parrot/tests/clients` + `tests/unit/clients`: 24 failed / 440 passed vs
  the 14 failed / 416 passed `dev` baseline). Every bedrock-converse, claude and
  claude-agent test in the TASK-2812 red list now passes **without needing any test
  edits** — the migration was signature-compatible with how those tests call the clients,
  so the "adapt existing tests minimally" part of the scope turned out to be unnecessary.
- The 10 still-red are all outside this task: `test_grok_multiround_usage` (4),
  `test_gemini_multiround_usage` (4), `test_openai_multiround_usage` (1) → TASK-2814/2815;
  and `test_bedrock_mantle.py::test_ask_delegates_to_openai_machinery` (1) which, despite
  its name, fails inside **`openai_base.py:582`** (`BedrockMantleClient` inherits the
  OpenAI machinery, not the Converse client) → TASK-2814.
- `ruff check` clean on all three source files and the new test;
  `import parrot.clients.claude, parrot.clients.bedrock, parrot.clients.claude_agent` OK.
- AC grep: `conversation_memory|conversation_history|_prepare_conversation_context|_update_conversation_memory|get_messages_for_api`
  returns **zero** lines in all three files.

**Deviations from spec**:
1. **`user_id`/`session_id` were still needed for non-memory purposes, so they are now
   read from the FEAT-228 ContextVars** (`parrot.observability.context.current_user_id` /
   `current_session_id`) instead of being deleted outright. `BaseBot.ask` already binds
   both at the top of every call, so the values are identical to what used to be passed
   explicitly — no behaviour change, and the signatures comply with the M5 test. Sites:
   - `AIMessageFactory.from_claude/from_bedrock(user_id=, session_id=)` — response
     metadata on the returned `AIMessage`, not conversation storage.
   - `HumanInteractionInterrupt.session_id` (claude ×2, bedrock ×2) — the resume handle
     for a suspended tool call.
   - `claude_agent.py`'s CLI-session map (`_cli_session_for` / `_remember_cli_session`)
     and `_build_options(session_id=...)` — **provider-side** session state, which spec §1
     Non-Goals explicitly keeps out of scope. Dropping it would have broken multi-turn
     `--resume` for the Claude Code CLI.
   Occurrences inside `resume(session_id, ...)` were left alone throughout: that is a
   different API with its own explicit parameter.
2. **`claude_agent.py` accepts `history=` but deliberately does not replay it**, and says
   so in both docstrings. The Claude Code CLI maintains its own server-side conversation
   and is resumed with `--resume`; re-sending ai-parrot's rendered history would duplicate
   every turn. The parameter exists for `AbstractClient` conformance (the M5 signature
   test in TASK-2815).
3. The convenience wrappers `summarize_text` / `translate_text` / `extract_key_points` /
   `analyze_sentiment` in `claude.py` keep their `user_id`/`session_id` parameters. They
   are stateless one-shot calls that never touched conversation memory — the ids only
   reach `AIMessageFactory` as response metadata — and they are not `ask`/`ask_stream`,
   so neither spec §5's acceptance criterion nor the M5 signature test covers them.
   Changing them would be scope creep.
