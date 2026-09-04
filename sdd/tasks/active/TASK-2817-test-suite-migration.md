# TASK-2817: Test-suite migration to memory-less clients

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: pending
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

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
