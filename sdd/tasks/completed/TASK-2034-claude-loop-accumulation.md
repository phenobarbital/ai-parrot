# TASK-2034: Claude client — per-round accumulation + events

**Feature**: FEAT-397 — Per-Round Token Usage Observability
**Spec**: `sdd/specs/tokens-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2031, TASK-2033
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Instrument the Anthropic client's `ask()` tool loop:
accumulate per-round usage, emit `ClientRoundEvent` per round, and make the
final `AIMessage.usage` / `AfterClientCallEvent` carry accumulated totals.

---

## Scope

- In `claude.py`'s `ask()` `while True:` loop:
  - Each round: build per-round `CompletionUsage.from_claude(result.get("usage", {}))`,
    accumulate via `+`, time the SDK call for the round's `duration_ms`.
  - After tool execution in a tool_use round: call
    `self._emit_round_event(tc, client_name=..., model=..., round_number=r,
    usage=per_round, raw_usage=result.get("usage"), tool_calls=<names>, duration_ms=...)`.
  - 1-indexed round numbers; NO event when the loop exits on the first
    response without tool_use (single-round call).
- Post-loop: set `extra_usage["rounds"] = <round count>` on the accumulated
  total when rounds > 1, and make the final `AIMessage` carry the
  accumulated total instead of only the last round's usage.
- `_emit_after_call` receives accumulated `input_tokens` / `output_tokens`.
- Rounds where the provider returned no usage: skip accumulation for that
  round, still emit the event with `usage=None`.
- Unit tests with a mocked SDK (3-round scenario + single-round scenario).

**NOT in scope**: `ask_stream` instrumentation (follow-up feature),
other clients, the helper itself (TASK-2033).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude.py` | MODIFY | Accumulate + emit in `ask()` loop |
| `packages/ai-parrot/tests/unit/clients/test_claude_multiround_usage.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import CompletionUsage      # models/basic.py:48
# _emit_round_event inherited from AbstractClient (TASK-2033)
# CompletionUsage.__add__ from TASK-2031
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/claude.py
# ask() at line 412.
# Tool loop: `while True:` at lines ~534-623:
#   result = await self._sdk_create(payload)       # line ~537, result is a dict
#   result.get("stop_reason") == "tool_use"        # line ~553 → tool round
#   break when stop_reason != "tool_use"           # line ~623
# Final message: AIMessageFactory.from_claude(response=result, ...)  # line ~668
#   → from_claude reads result.get("usage", {}) — LAST round only (the bug)
# _emit_after_call at line ~689 with the final AIMessage's usage.

# packages/ai-parrot/src/parrot/models/basic.py
CompletionUsage.from_claude(usage: Dict[str, Any])   # line 131
#   maps input_tokens/output_tokens keys; stashes full dict in extra_usage

# AbstractClient (clients/base.py):
#   _emit_before_call returns tc (TraceContext)     # lines 423-478
#   _emit_round_event(tc, *, client_name, model, round_number,
#                     usage, raw_usage, tool_calls, duration_ms)  # TASK-2033
#   _emit_after_call(tc, *, ..., input_tokens, output_tokens, ...)  # lines 480-523
```

### Does NOT Exist
- ~~`AIMessage.usage_history`~~ — do NOT add; totals only
- ~~`CompletionUsage.from_response()`~~ — use `from_claude`
- ~~automatic accumulation in AIMessageFactory~~ — the CLIENT accumulates
  and must override/pass the accumulated usage into the final message

---

## Implementation Notes

### Pattern to Follow
```python
# Accumulation: gemma4.py:528-546 (running total, new instance per round).
# Round timing: time.perf_counter() around the SDK call, same as the
# existing duration_ms handling in ask().
```

### Key Constraints
- Preserve existing behavior for single-round calls bit-for-bit (usage
  identical, no ClientRoundEvent, no extra_usage["rounds"]).
- The accumulated total must reach BOTH the AIMessage and _emit_after_call.
- Set `extra_usage["rounds"]` AFTER the final accumulation (it must not be
  clobbered by a later `+`).
- `raw_usage` must be a plain dict (Claude's usage is already a dict).

---

## Acceptance Criteria

- [ ] Mocked 3-round loop: `AIMessage.usage` = sum of 3 rounds; `extra_usage["rounds"] == 3`.
- [ ] 3-round loop emits exactly 2+ `ClientRoundEvent`s per spec semantics (one per tool round, after tool execution) with correct 1-indexed `round_number` and tool names.
- [ ] `AfterClientCallEvent.input_tokens/output_tokens` equal accumulated sums.
- [ ] Single-round call: no `ClientRoundEvent`, usage identical to pre-feature.
- [ ] Round with missing usage: event fires with token fields None; total unaffected.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/clients/test_claude_multiround_usage.py -v`
- [ ] Existing suite passes: `pytest packages/ai-parrot/tests/unit/clients/ -v -k claude`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/clients/test_claude_multiround_usage.py
# Mock self._sdk_create to return, in order:
#   {"stop_reason": "tool_use",  "usage": {"input_tokens": 100, "output_tokens": 10}, "content": [<tool_use block>]}
#   {"stop_reason": "tool_use",  "usage": {"input_tokens": 150, "output_tokens": 20}, "content": [<tool_use block>]}
#   {"stop_reason": "end_turn",  "usage": {"input_tokens": 200, "output_tokens": 30}, "content": [<text block>]}
# Assert: msg.usage.prompt_tokens == 450, completion_tokens == 60,
#         msg.usage.extra_usage["rounds"] == 3,
#         captured ClientRoundEvents have round_number 1 and 2 (tool rounds),
#         AfterClientCallEvent totals == (450, 60).
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2031 and TASK-2033 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — line numbers are approximate (~); re-grep the loop anchors before editing
4. **Update status** in `sdd/tasks/index/tokens-observability.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill in the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Instrumented the `while True:` tool loop in `claude.py::ask()`
(lines ~534-660 post-edit): per-round timing (`_lc_round_t0`), per-round
`CompletionUsage.from_claude()` build + `+`-accumulation (skipped when
`result.get("usage")` is falsy), round-scoped tool-name collection, and a
`self._emit_round_event(...)` call after tool execution for `tool_use`
rounds only (not the final round). Post-loop, the accumulated total
overrides `ai_message.usage` and sets `extra_usage["rounds"]` when
`round_number > 1` — single-round calls are untouched (bit-for-bit
identical, verified by test). `_emit_after_call` picks up the accumulated
totals automatically via the existing `getattr(ai_message, 'usage', ...)`
read. Created `tests/unit/clients/test_claude_multiround_usage.py` (4
tests: 3-round accumulation, single-round no-event, after-call totals,
missing-usage round) — all pass. Ran `tests/unit/clients/` (27 passed,
`-k claude` → 4 passed, matching the task's acceptance criterion). Also
ran the top-level `tests/test_anthropic_client.py` and confirmed (via
`git stash`) that its 4 failures are pre-existing and unrelated — a
Pydantic `AIMessage(content=...)` construction missing required fields,
present identically before this task's changes.

**Deviations from spec**: none
