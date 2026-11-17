# HOTFIX-chatstorage-turn-record-gaps-4: Provider clients set `AIMessage.response_time` in `ask()`

**Feature**: chatstorage-turn-record-gaps — close the turn-record gaps between conversation history and ChatStorage
**Spec**: `sdd/briefs/chatstorage-turn-record-gaps.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`AIMessage.response_time` (seconds) exists, and `ConversationTurn.from_ai_message` copies it into
turn metadata, but no provider client sets it, so stored turns have `metadata.response_time: null`
(brief, Problem 4). Decision 3 of the brief: each provider client sets it from its own timer.

Every client already measures the call: its `ask()` ends with one
`await self._emit_after_call(..., duration_ms=...)`. The same elapsed value, in seconds, goes on the
message the method returns.

## Scope

In the `ask()` method of each client below, set `response_time` on the `AIMessage` that `ask()`
returns, using the same elapsed time the method passes as `duration_ms` to `_emit_after_call`
(`response_time = duration_ms / 1000`, a `float` in seconds):

| Client file | `ask()` | `_emit_after_call` in `ask()` |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | line 3324 | line 4128 |
| `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py` | line 486 | line 801 |
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | line 781 | line 1079 |
| `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py` | line 686 | line 1005 |
| `packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py` | line 333 | line 728 |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py` | line 1030 | line 1496 |

- Compute the elapsed value once and use it for both `duration_ms` and `response_time`.
- Set it only when the message's `response_time` is still `None`.
- If a client's `ask()` has more than one return path that builds an `AIMessage`, cover the path
  that reaches the `_emit_after_call` named above; list any path left uncovered in the Completion Note.

**NOT in scope**: `ask_stream()`, `invoke()`, `resume()`, batch and media methods; the
`AIMessageFactory.from_*` signatures; `clients/base.py`; clients not in the table; the bot layer.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | MODIFY | Set `response_time` on the returned `AIMessage` in `ask()` |
| `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py` | MODIFY | Set `response_time` on the returned `AIMessage` in `ask()` |
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY | Set `response_time` on the returned `AIMessage` in `ask()` |
| `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py` | MODIFY | Set `response_time` on the returned `AIMessage` in `ask()` |
| `packages/ai-parrot-client-groq/src/parrot/clients/groq/client.py` | MODIFY | Set `response_time` on the returned `AIMessage` in `ask()` |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py` | MODIFY | Set `response_time` on the returned `AIMessage` in `ask()` |
| `packages/ai-parrot/tests/unit/clients/test_client_response_time.py` | CREATE | Regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ 80cc849fac, 2026-11-17)

- `packages/ai-parrot/src/parrot/models/responses.py:163` — `response_time: Optional[float] = Field(default=None, description="Time taken to generate the response (in seconds)")`
- `packages/ai-parrot/src/parrot/models/responses.py:1116` — `response_time=response_time,` (the only existing writer: the generic factory parameter)
- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:3412` — `ask_started = time.perf_counter()`
- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:4132` — `duration_ms=(time.perf_counter() - ask_started) * 1000,`
- The `ask(` and `await self._emit_after_call(` line numbers in the Scope table were read from
  origin/dev @ 80cc849fac. Re-check each one before editing; the files are large and move often.
- `ConversationTurn.from_ai_message` reads `getattr(response, "response_time", None)`
  (`packages/ai-parrot/src/parrot/memory/abstract.py`).
- Client test helpers: `packages/ai-parrot/tests/unit/clients/fakes.py`; signature sweep in
  `packages/ai-parrot/tests/unit/clients/test_all_client_ask_signatures.py`.

### Does NOT Exist

- `AIMessageFactory.from_gemini`, `from_openai`, `from_claude`, `from_groq` and `from_bedrock` take
  no `response_time` parameter.
- No shared timing helper on `AbstractClient`.

## Acceptance Criteria

- [ ] **AC-1**: For each client in the table that can be driven with the existing fakes or a mocked
      SDK call, `ask()` returns an `AIMessage` whose `response_time` is a `float >= 0`.
- [ ] **AC-2**: `response_time * 1000` equals the `duration_ms` reported on that call's
      `AfterClientCallEvent` (same measurement, within float tolerance).
- [ ] **AC-3**: A turn built with `ConversationTurn.from_ai_message` from such a message has a
      non-null `metadata["response_time"]`.
- [ ] **AC-4**: A client that cannot be exercised offline is listed in the Completion Note with the
      reason; it is still edited.
- [ ] **AC-5**: `test_all_client_ask_signatures.py` still passes.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src:packages/ai-parrot-client-anthropic/src:packages/ai-parrot-client-openai/src:packages/ai-parrot-client-groq/src:packages/ai-parrot-client-amazon/src pytest packages/ai-parrot/tests/unit/clients/test_client_response_time.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/clients/test_all_client_ask_signatures.py -q`

## Agent Instructions

1. Work in this worktree only; re-verify every line number above before editing.
2. `ruff check --fix` on the touched files; run the validation commands. Do not reformat whole
   client files with `black`; match the surrounding formatting.
3. Commit only the listed files: `fix(chatstorage-turn-record-gaps): HOTFIX-chatstorage-turn-record-gaps-4 — client response_time`.

## Completion Note

Pending.
