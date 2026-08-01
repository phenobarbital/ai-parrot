# TASK-2035: OpenAI client — per-round accumulation + events

**Feature**: FEAT-397 — Per-Round Token Usage Observability
**Spec**: `sdd/specs/tokens-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2031, TASK-2033
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Same treatment as TASK-2034 for `OpenAIClient` in
`gpt.py`. Note this client has TWO call paths (`_responses_completion`
and `_chat_completion`) — both feed the same tool loop and both must
accumulate.

---

## Scope

- In `gpt.py`'s `ask()` tool loop (`while getattr(result, "tool_calls", None):`):
  - Per round: `CompletionUsage.from_openai(response.usage)`, accumulate
    via `+`, time each SDK call.
  - Also capture the FIRST call's usage (made before the loop) — round 1
    is the initial call; loop iterations are rounds 2..N.
  - After each round's tool execution: `self._emit_round_event(...)` with
    tool-call names, per-round usage, and
    `raw_usage=<response.usage as plain dict>` (`model_dump()` /
    `.to_dict()` on the SDK object, or None if unavailable).
- Post-loop: accumulated total (with `extra_usage["rounds"]` when > 1
  round) reaches the final `AIMessage` and `_emit_after_call`.
- Missing per-round usage → event with `usage=None`, accumulator skips.
- Unit tests: 3-round and single-round scenarios on the chat-completions
  path; one accumulation test on the responses path.

**NOT in scope**: `ask_stream`, other clients.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | Accumulate + emit in `ask()` loop |
| `packages/ai-parrot/tests/unit/clients/test_openai_multiround_usage.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import CompletionUsage      # models/basic.py:48
# _emit_round_event inherited from AbstractClient (TASK-2033)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/gpt.py
# ask() at line 666.
# Tool loop: `while getattr(result, "tool_calls", None):` lines ~891-1004:
#   new API call via _responses_completion() or _chat_completion()  # lines ~998-1002
#   result = response.choices[0].message                            # line ~1004 (overwritten per round)
# Final: AIMessageFactory.from_openai(response=response, ...)       # line ~1040
#   → reads response.usage — LAST response only (the bug)
# _emit_after_call at line ~1057.

# packages/ai-parrot/src/parrot/models/basic.py
CompletionUsage.from_openai(usage: Any)              # line 109
#   getattr-based: prompt_tokens / completion_tokens / total_tokens
```

### Does NOT Exist
- ~~`CompletionUsage.from_response()`~~ — use `from_openai`
- ~~`response.usage` guaranteed dict~~ — it is an SDK object; convert for
  `raw_usage` (JSON-safe) via `model_dump()` when available, else omit
- ~~`AIMessage.usage_history`~~ — do NOT add

---

## Implementation Notes

### Key Constraints
- Both call paths accumulate identically — factor the per-round
  capture into a tiny local helper inside `ask()` if it avoids duplication.
- Preserve single-round behavior bit-for-bit.
- `raw_usage` must survive `json.dumps` (strict `to_dict()` check) —
  verify with the SDK object's `model_dump()` output.
- Round numbering: initial call = round 1; events fire only for tool
  rounds (after tool execution), consistent with TASK-2034.

---

## Acceptance Criteria

- [ ] Mocked 3-round loop: `AIMessage.usage` = sum of all 3 responses; `extra_usage["rounds"] == 3`.
- [ ] `ClientRoundEvent`s carry correct round numbers, tool names, and JSON-safe raw_usage.
- [ ] `AfterClientCallEvent` totals equal accumulated sums.
- [ ] Single-round call unchanged; no events.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/clients/test_openai_multiround_usage.py -v`
- [ ] Existing suite passes: `pytest packages/ai-parrot/tests/unit/clients/ -v -k openai`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/clients/test_openai_multiround_usage.py
# Mock the SDK to yield three responses with usages (100/10), (150/20), (200/30)
# where the first two carry tool_calls and the third does not.
# Assert accumulated (450, 60), rounds == 3, per-round events for rounds 1-2's
# tool executions, AfterClientCallEvent totals (450, 60).
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2031 and TASK-2033 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — line numbers approximate; re-grep loop anchors before editing
4. **Update status** in `sdd/tasks/index/tokens-observability.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill in the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Instrumented `gpt.py::ask()`: round 1 is the initial (pre-loop)
call (both `_responses_completion`/`_chat_completion` paths write through
the same `response.usage`), timed via `_lc_round_t0_gpt`; each subsequent
loop iteration (rounds 2..N) re-times, re-extracts, and accumulates via a
local `_lc_gpt_extract_usage()` helper (`CompletionUsage.from_openai` +
JSON-safe `raw_usage` via `usage_obj.model_dump()`, falling back to `None`
when unavailable). `self._emit_round_event(...)` fires after tool
execution for each round that had tool_calls, using round-scoped tool
names. Post-loop, the accumulated total overrides `ai_message.usage` and
sets `extra_usage["rounds"]` when `> 1` round — single-round calls
untouched. Created `tests/unit/clients/test_openai_multiround_usage.py`
(5 tests: 3-round chat-completions accumulation, single-round no-event,
after-call totals, missing-usage round, plus a dedicated Responses-API
path accumulation test using model="o3"). Ran `tests/unit/clients/`
(32 passed, `-k openai` → 5 passed).

**Deviations from spec**: none. Note (discovered while writing tests, not
a code change): `OpenAIClient.ask()` does not call `self._ensure_client()`
before using `self.client` — pre-existing, unrelated to this task (the
loop-local `client` property refactor also broke the old
`client.client = mock_instance` pattern used by
`tests/test_openai_client.py`, confirmed pre-existing via `git stash`).
Tests here work around it via the supported `get_client()` +
`_ensure_client()` mechanism; not fixed as it's out of this task's scope.
