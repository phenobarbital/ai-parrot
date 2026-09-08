# TASK-2817: Test-suite migration to memory-less clients

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2816
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. Tests that construct clients with `conversation_memory=`,
call `client.ask(..., user_id=, session_id=)`, or assert client-side memory
writes must move to the new contract: `history=[HistoryMessage(...)]` and
assertions on `_format_history` / bot-side persistence. TASK-2813/2814/2815
made minimal edits so files *run*; this task makes the suites *right* and
green.

---

## Scope

- Sweep (re-run at task time — the list below is from `grep` on 2026-09-04):
  - `tests/clients/test_base_fallback.py`, `test_anthropic_fallback.py`, `test_openai_base_parity.py`, `test_anthropic_sdk_097.py`, `test_claude_agent.py`, `test_moonshot_client.py`, `test_openai_compatible_defaults.py`
  - `tests/unit/test_anthropic_invoke.py`, `test_stream_contract.py`, `test_google_document_understanding.py`
  - `packages/ai-parrot/tests/test_google_client.py`
  - `packages/ai-parrot/tests/clients/test_bedrock_advanced.py`, `test_bedrock_converse.py`, `test_bedrock_errors.py`, `test_bedrock_integration.py`, `test_bedrock_mantle.py`, `test_bedrock_thinking.py`, `test_nova.py`
  - `packages/ai-parrot/tests/unit/clients/test_bedrock_multiround_usage.py`, `test_claude_multiround_usage.py`, `test_gemini_multiround_usage.py`, `test_grok_multiround_usage.py`, `test_groq_multiround_usage.py`, `test_openai_multiround_usage.py`, `test_codex_agent.py`
  - `packages/ai-parrot/tests/bots/test_rag_conversation_integration.py`, `test_vector_context_integration.py`, `test_voicebot_contract.py`
  - `packages/ai-parrot/tests/memory/unified/test_bot_integration.py`
  - Server/integrations tests that matched only on `InMemoryConversation` for **bot** setup (`packages/ai-parrot-server/tests/handlers/test_a2ui_*.py`, `test_a2a_a2ui_dispatch.py`, `integration/test_a2ui_e2e.py`, `packages/ai-parrot-integrations/tests/.../test_operator_commands_readonly.py`) — verify they need no change; fix if they pass memory into a client.
- Replace client-side memory fixtures with `history=[HistoryMessage(...)]`; replace "client wrote a turn" assertions with `_format_history` output assertions or move them to bot-level tests.
- Any test asserting the old `[history, current]` duplication fix (FEAT-302, `tests/clients/test_base_fallback.py:122-170`) is re-expressed against `_build_messages`.
- Remove TODO markers left by TASK-2813/2814/2815.
- Run both suites and record the logs in `artifacts/logs/feat-524-task-2817-green.log`.

**NOT in scope**: production code (if a test reveals a bug, fix it in a separate commit and say so in the note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| (each file in the sweep) | MODIFY | new client contract |
| `artifacts/logs/feat-524-task-2817-green.log` | CREATE | evidence |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory import HistoryMessage, render_history, ConversationTurn, InMemoryConversation  # TASK-2809 exports
from parrot.clients.base import AbstractClient    # post-TASK-2812: ask(..., history=None, ...), _format_history, _build_messages
```

### Existing Signatures to Use
```python
# Post-FEAT-524 contract (created by TASK-2809/2811/2812/2816):
AbstractClient.ask(prompt, model, ..., system_prompt=None, history: Optional[Sequence[HistoryMessage]] = None, ...)
AbstractClient._format_history(history) -> List[Dict]      # default text blocks; overridden in Bedrock/Google/OpenAIBase
AbstractClient._build_messages(prompt, files, history) -> List[Dict]
AbstractBot.memory_key_id -> str ; AbstractBot.save_conversation_turn(user_id, session_id, turn)
ConversationTurn.from_ai_message(*, user_message, response, user_id, chatbot_id, ...)
# Repo pytest config: root pyproject.toml [tool.pytest.ini_options] testpaths=["tests"] (:211-216); packages/ai-parrot/pyproject.toml has its own (:850)
```

### Does NOT Exist
- ~~`client.conversation_memory`~~, ~~`client.start_conversation()`~~, ~~`client.get_conversation()`~~ — removed; tests using them must be rewritten, not skipped.
- ~~`user_id=`/`session_id=` on client `ask`~~ — `TypeError` now.
- ~~`ConversationHistory.get_messages_for_api()`~~ — removed.

---

## Implementation Notes

### Key Constraints
- Prefer rewriting a test to deleting it; delete only when the behaviour it covered no longer exists (client-side memory), and list every deletion in the note.
- Wrap runs: `timeout -s KILL 900 pytest tests/unit -q` and `timeout -s KILL 900 pytest packages/ai-parrot/tests -q` (unit suite hangs after the summary in this environment).
- Some client tests hit live APIs and are marked/skipped — keep their markers.

---

## Acceptance Criteria

- [ ] `grep -rln "conversation_memory=\|user_id=.*session_id=" tests packages/*/tests` shows only bot-level usages.
- [ ] Both suites green (or only pre-existing, documented failures unrelated to FEAT-524); log committed.
- [ ] `ruff check` clean on every touched test file.
- [ ] No TODO left from TASK-2813/2814/2815.

---

## Test Specification

Migration task — the deliverable is the green suite. Add, if missing, one shared fixture:
```python
@pytest.fixture
def two_turn_history():
    return [HistoryMessage("user", "q1"), HistoryMessage("assistant", "a1"),
            HistoryMessage("user", "q2"), HistoryMessage("assistant", "a2")]
```

---

## Agent Instructions

1. Re-run the sweep greps first. 2. Work file by file, one commit per test module or logical group.
3. Move to `completed/`, update index, fill note (deletions + any production bug found).

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**:
I re-ran the sweep rather than trusting the 2026-09-04 list, and drove the work off
**actual failures** (each suite run in the worktree AND in the `dev` checkout with the
same command, then set-diffed) rather than off grep hits. Most files on the task's list
turned out to need nothing: TASK-2813/2814/2815 were signature-compatible with how those
tests call the clients, so the suites were already green.

**Files that genuinely needed migrating (failed in the worktree, passed on `dev`):**
1. **`tests/clients/test_base_fallback.py`** — `TestPrepareConversationContext` (5 tests)
   called the removed helper directly. Rewritten as **`TestBuildMessages`** against
   `_build_messages`, exactly as spec §3 M7 asks. The FEAT-302 guarantees are preserved
   and sharpened: no-duplication, `[*history, current]` ordering, an explicit
   `json.dumps(messages).count("2+2") == 1` check, a new multi-turn chronological-order
   test, `[] == None` equivalence, the missing-file skip, and a new test asserting that
   **no system prompt is synthesized from history any more** (the removed helper used to
   invent a "You have access to the following conversation history…" prompt).
   → 22 passed.
2. **`tests/unit/test_stream_contract.py`** — the two Groq tests called
   `ask_stream(user_id=, session_id=)` (hard `TypeError`). Migrated to `history=`, the
   mocked `_prepare_conversation_context`/`_update_conversation_memory` replaced by a
   mocked `_build_messages`, and the "memory update must have been called" assertion —
   which no longer means anything — replaced by asserting the client **consumed the
   history it was handed** (`_build_messages.call_args.args[2] == [...]`).
   → 12 passed.
3. **`tests/unit/test_google_document_understanding.py`** —
   `test_stateful_mode_calls_prepare_context` asserted a removed method was invoked.
   Replaced by `test_stateful_mode_renders_supplied_history` (asserts
   `_format_history` is called with exactly the supplied history) plus a new
   `test_stateless_mode_ignores_supplied_history`. → 20 passed (was 19).

**Files with stale-but-harmless mocks, cleaned so they describe the real contract:**
`tests/clients/test_anthropic_fallback.py`, `tests/clients/test_openai_base_parity.py`,
`packages/ai-parrot/tests/test_google_client.py` — each assigned
`_prepare_conversation_context`/`_update_conversation_memory` onto a client instance.
Production no longer calls them, so the tests passed while stubbing nothing. Replaced
with `_build_messages` / `_dict_messages` stubs. All three suites still green
(11, 52, 61 passed).

**Files verified as needing no change:** the `packages/ai-parrot/tests/clients/test_bedrock_*.py`
set (6 files), `test_nova.py`, all six `*_multiround_usage.py`, `test_codex_agent.py`,
`test_moonshot_client.py`, `test_openai_compatible_defaults.py`, `test_anthropic_sdk_097.py`,
`test_claude_agent.py`, `tests/unit/test_anthropic_invoke.py`, the bot-side
`test_rag_conversation_integration.py` / `test_vector_context_integration.py` /
`test_voicebot_contract.py`, `tests/memory/unified/test_bot_integration.py`, and the
ai-parrot-server / ai-parrot-integrations A2UI tests. The `conversation_memory=` hits in
`tests/memory/unified/test_manager.py` are `UnifiedMemoryManager(conversation_memory=...)`
— a different, untouched API, correctly left alone. No TODO markers were left by
TASK-2813/2814/2815 to remove (none were needed).

**Final state — worktree vs `dev`, same command in both trees**
(full log: `artifacts/logs/feat-524-task-2817-green.log`):
| Suite | worktree | dev | new failures |
|---|---|---|---|
| `tests/clients` | 14 failed / 488 passed | 19 failed / 482 passed | **0** (5 fixed) |
| `tests/unit` | 63 failed / 777 passed | 64 failed / 775 passed | **0** (1 fixed) |
| `packages/ai-parrot/tests/clients` | 6 / 354 | 6 / 354 | **0** |
| `packages/ai-parrot/tests/unit/clients` | 8 / 283 | 8 / 275 | **0** |
| `packages/ai-parrot/tests/unit/bots` | 5 / 282 | 5 / 243 | **0** |
| `packages/ai-parrot/tests/unit/memory` | 62 passed | (new dir) | — |
| `packages/ai-parrot/tests/memory` | 158 passed | 158 passed | **0** |
| `packages/ai-parrot/tests/bots` | 74 / 1425 | 71 / 1428 | 3, all environmental |

Zero FEAT-524 regressions anywhere; **6 pre-existing failures fixed** as a side effect.
The `tests/bots` delta is the 3 `test_porygon_identity_migration` tests, which read
`agents/porygon.py` — `/agents/` is gitignored so it does not exist in any worktree.

**Deviations from spec**:
1. **No production code was changed** (as the task requires), with one consequence worth
   recording: `tests/clients/test_anthropic_fallback.py` still has **5 failures that also
   fail identically on `dev`** — `AttributeError: AbstractClient.client is now a
   loop-local property` — caused by FEAT-112, not by this feature. I migrated the stale
   FEAT-524 mocks in that file but deliberately did not fix the FEAT-112 breakage.
2. **`test_google_document_understanding`'s two new tests needed a
   `patch.object(type(client), "client", new_callable=PropertyMock)`** to be stable.
   They exercise more of the real `document_understanding` path than the test they
   replaced, which walks into pre-existing fixture pollution: `google_client` patches
   `get_client` at CLASS level and the SDK is memoized in the loop-local
   `_clients_by_loop` cache, so under a full-suite run `self.client` can resolve to
   another module's leftover bare `MagicMock` and blow up on `await`. The same pollution
   is what makes the pre-FEAT-524 version of that test fail on `dev`. Pinning the
   property makes the tests order-independent; the fixture itself is left alone.
3. **`artifacts/logs/feat-524-task-2817-green.log` is written but not committed** —
   `.gitignore:283` ignores `artifacts/`, same as TASK-2808's red log.
4. Note on capturing that log: `tests/unit` and `tests/bots` exhibit the known
   hang-after-summary, so `timeout -s KILL` discards buffered output when piped. The log
   redirects to a file first and greps afterwards.
