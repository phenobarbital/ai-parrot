# TASK-2037: Groq client — per-round accumulation + events

**Feature**: FEAT-397 — Per-Round Token Usage Observability
**Spec**: `sdd/specs/tokens-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2031, TASK-2033
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8. Same treatment as TASK-2034 for `GroqClient` in `groq.py`.

---

## Scope

- In `groq.py`'s `ask()` tool loop
  (`while result.tool_calls and conversation_turns < max_turns:`):
  - Per round: `CompletionUsage.from_groq(response.usage)`, accumulate via
    `+`, time each SDK call. Initial call = round 1.
  - After each round's tool execution: `self._emit_round_event(...)` with
    tool names, per-round usage, JSON-safe raw usage.
- Post-loop: accumulated total (with `extra_usage["rounds"]` when > 1)
  reaches the final `AIMessage` (currently `from_groq(response=response)`
  at ~line 593 — last response only) and `_emit_after_call` (~line 608).
- Groq's timing fields (`completion_time`, `prompt_time`, `queue_time`,
  `total_time`) accumulate via `__add__`'s None-aware sum — this client is
  the main beneficiary of the timing-sum semantics.
- Missing usage on a round → event with `usage=None`, skip accumulation.
- Unit tests: 3-round + single-round scenarios.

**NOT in scope**: `ask_stream`, other clients.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/groq.py` | MODIFY | Accumulate + emit in `ask()` loop |
| `packages/ai-parrot/tests/unit/clients/test_groq_multiround_usage.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import CompletionUsage      # models/basic.py:48
# _emit_round_event inherited from AbstractClient (TASK-2033)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/groq.py
# ask() at line 270.
# Tool loop: `while result.tool_calls and conversation_turns < max_turns:`
#   lines ~408-499 (max_turns=10 default)
#   response = self.client.chat.completions.create(**continue_args)  # line ~498, overwritten
# Final: AIMessageFactory.from_groq(response=response, ...)          # line ~593 (last only — bug)
# _emit_after_call at line ~608.

# packages/ai-parrot/src/parrot/models/basic.py
CompletionUsage.from_groq(usage: Any)                # line 118
#   getattr-based; also captures completion_time/prompt_time/queue_time/total_time
```

### Does NOT Exist
- ~~`CompletionUsage.from_response()`~~ — use `from_groq`
- ~~`response.usage` guaranteed dict~~ — SDK object; convert for raw_usage
- ~~`AIMessage.usage_history`~~ — do NOT add

---

## Implementation Notes

### Key Constraints
- Preserve single-round behavior bit-for-bit.
- Timing fields must survive accumulation (assert in tests: two rounds with
  `completion_time=0.5` each → total `1.0`).
- Round numbering consistent with TASK-2034/2035: initial call round 1,
  events for tool rounds after execution.

---

## Acceptance Criteria

- [ ] Mocked 3-round loop: usage = sum; `extra_usage["rounds"] == 3`; timing fields summed.
- [ ] Per-round events with tool names and raw usage.
- [ ] `AfterClientCallEvent` totals equal accumulated sums.
- [ ] Single-round call unchanged; no events.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/clients/test_groq_multiround_usage.py -v`
- [ ] Existing suite passes: `pytest packages/ai-parrot/tests/unit/clients/ -v -k groq`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/clients/test_groq_multiround_usage.py
# Mock chat.completions.create → three responses (100/10, 150/20, 200/30),
# first two with tool_calls, each with completion_time=0.5.
# Assert (450, 60), rounds == 3, completion_time == 1.5.
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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
