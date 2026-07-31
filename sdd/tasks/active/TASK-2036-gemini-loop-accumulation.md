# TASK-2036: Gemini client — per-round accumulation + first-response usage fix

**Feature**: FEAT-397 — Per-Round Token Usage Observability
**Spec**: `sdd/specs/tokens-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2031, TASK-2033
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 — the largest behavioral change of the five clients.
`GoogleGenAIClient.ask()` currently builds `AIMessage.usage` from the
**initial** response (`from_gemini(response=response)` at ~line 3559),
completely ignoring the usage of every round inside
`_handle_multiturn_function_calls()`. This task must both accumulate
per-round AND rewire which usage reaches the final message.

---

## Scope

- In `_handle_multiturn_function_calls()` (`while iteration < max_iterations:`):
  - Per round: extract `usage_metadata` from each `chat.send_message(...)`
    response, build `CompletionUsage.from_gemini(<usage dict>)`, accumulate.
  - After each round's function execution: `self._emit_round_event(...)`
    with function names, per-round usage, raw usage-metadata dict.
  - Return (or otherwise expose) the accumulated `CompletionUsage` and
    round count to the caller — extend the method's return contract
    minimally (e.g., include it in the already-returned structure; re-read
    the method's current return shape first and follow it).
- In `ask()`: when the multiturn handler ran, the accumulated total
  (initial response usage + all loop rounds, `extra_usage["rounds"]` set)
  must reach the final `AIMessage` and `_emit_after_call` — NOT the initial
  response's usage.
- No-tool path: behavior unchanged.
- Rounds without `usage_metadata`: event with `usage=None`, skip accumulation.
- Unit tests: 3-round mocked chat + single-round + missing-usage round.

**NOT in scope**: `ask_stream`, `GeminiLiveClient`, other clients.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | Accumulate in multiturn handler; fix `ask()` usage source |
| `packages/ai-parrot/tests/unit/clients/test_gemini_multiround_usage.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import CompletionUsage      # models/basic.py:48
# _emit_round_event inherited from AbstractClient (TASK-2033)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/google/client.py
# ask() at line 2782.
# _handle_multiturn_function_calls() at line 1731:
#   loop `while iteration < max_iterations:` lines ~1766-2080 (max_iterations=15 default)
#   per-round call: chat.send_message(next_prompt_parts, config=current_config)  # line ~2028
# ask() builds final message from the INITIAL response:
#   AIMessageFactory.from_gemini(response=response, ...)   # line ~3559  ← THE BUG
#   from_gemini reads response.usage_metadata
# _emit_after_call at line ~3589.

# packages/ai-parrot/src/parrot/models/basic.py
CompletionUsage.from_gemini(usage: Dict[str, Any])   # line 162
#   reads prompt_token_count / candidates_token_count / total_token_count
#   (also accepts prompt_tokens/completion_tokens fallbacks)
```

### Does NOT Exist
- ~~accumulation or usage return in `_handle_multiturn_function_calls`~~ —
  created by THIS task; read the method's ACTUAL current return shape
  before extending it (it is long: ~1766-2080)
- ~~`response.usage_metadata` guaranteed dict~~ — it is an SDK object;
  convert to a plain dict for `from_gemini` / `raw_usage` (the existing
  from_gemini call sites show the conversion pattern — follow them)
- ~~`AIMessage.usage_history`~~ — do NOT add

---

## Implementation Notes

### Key Constraints
- READ FIRST: `_handle_multiturn_function_calls` is ~300 lines; map its
  return contract and every `return` statement before touching it.
- The initial `ask()` response's usage counts as round 1; handler rounds
  are 2..N. `extra_usage["rounds"]` = total SDK calls with usage.
- Preserve the no-function-call fast path exactly.
- `usage_metadata`→dict conversion must be JSON-safe for `raw_usage`.

---

## Acceptance Criteria

- [ ] Mocked 3-round multiturn: `AIMessage.usage` = initial + 2 loop rounds; `extra_usage["rounds"] == 3`.
- [ ] `ask()` no longer reports the initial response's usage on multiturn calls (regression test asserts the OLD value is NOT the final usage).
- [ ] Per-round `ClientRoundEvent`s with function names and raw usage dicts.
- [ ] `AfterClientCallEvent` totals equal accumulated sums.
- [ ] Single-round call unchanged; no events.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/clients/test_gemini_multiround_usage.py -v`
- [ ] Existing suite passes: `pytest packages/ai-parrot/tests/unit/clients/ -v -k "google or gemini"`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/clients/test_gemini_multiround_usage.py
# Mock chat.send_message to return responses with usage_metadata
# (prompt_token_count/candidates_token_count): (100,10), (150,20), (200,30)
# with function_calls on the first two. Assert accumulated (450,60),
# rounds == 3, and that the final usage != the initial response's usage.
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2031 and TASK-2033 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — line numbers approximate; re-grep anchors AND read the full multiturn handler before editing
4. **Update status** in `sdd/tasks/index/tokens-observability.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill in the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
