# TASK-2038: Grok client — per-round accumulation + events

**Feature**: FEAT-397 — Per-Round Token Usage Observability
**Spec**: `sdd/specs/tokens-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2031, TASK-2033
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9. Same treatment as TASK-2034 for `GrokClient` in `grok.py`.
Grok's xai_sdk returns protobuf usage objects — extra care converting to a
JSON-safe `raw_usage` dict.

---

## Scope

- In `grok.py`'s `ask()` tool loop (`while current_turn < max_turns:`):
  - Per round: `CompletionUsage.from_grok(response.usage)`, accumulate via
    `+`, time each `chat.sample()` call.
  - After each round's tool execution: `self._emit_round_event(...)` with
    tool names, per-round usage, and a JSON-safe `raw_usage` dict built via
    getattr extraction (mirror `from_grok`'s protobuf branch — do NOT pass
    the protobuf object).
- Post-loop: accumulated total (with `extra_usage["rounds"]` when > 1)
  reaches the final `AIMessage` (currently
  `CompletionUsage.from_grok(final_response.usage)` at ~line 343 — last
  only) and `_emit_after_call` (~line 370).
- Missing usage on a round → event with `usage=None`, skip accumulation.
- Unit tests: 3-round + single-round scenarios.

**NOT in scope**: `ask_stream`, other clients.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/grok.py` | MODIFY | Accumulate + emit in `ask()` loop |
| `packages/ai-parrot/tests/unit/clients/test_grok_multiround_usage.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import CompletionUsage      # models/basic.py:48
# _emit_round_event inherited from AbstractClient (TASK-2033)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/grok.py
# ask() at line 188.
# Tool loop: `while current_turn < max_turns:` lines ~277-317 (max_turns=10)
#   response = await chat.sample()                   # line ~281, appended to chat per round
# Final usage: CompletionUsage.from_grok(final_response.usage)  # line ~343 (last only — bug)
# _emit_after_call at line ~370.

# packages/ai-parrot/src/parrot/models/basic.py
CompletionUsage.from_grok(usage: Any)                # line 239
#   handles BOTH dict and xai_sdk protobuf via getattr; protobuf branch
#   extracts reasoning_tokens, cached_prompt_text_tokens, prompt_image_tokens
#   into extra_usage — REUSE this extraction shape for raw_usage.
```

### Does NOT Exist
- ~~passing the protobuf usage object as `raw_usage`~~ — FORBIDDEN: fails
  the strict `to_dict()` json.dumps check; build a plain dict
- ~~`CompletionUsage.from_response()`~~ — use `from_grok`
- ~~`AIMessage.usage_history`~~ — do NOT add

---

## Implementation Notes

### Key Constraints
- Simplest raw_usage source: `per_round.extra_usage` already holds the
  getattr-extracted dict from `from_grok` — reuse it rather than
  re-extracting.
- Preserve single-round behavior bit-for-bit.
- Round numbering consistent with siblings.

---

## Acceptance Criteria

- [ ] Mocked 3-round loop: usage = sum; `extra_usage["rounds"] == 3`.
- [ ] Per-round events with JSON-safe raw_usage (json.dumps in test).
- [ ] `AfterClientCallEvent` totals equal accumulated sums.
- [ ] Single-round call unchanged; no events.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/clients/test_grok_multiround_usage.py -v`
- [ ] Existing suite passes: `pytest packages/ai-parrot/tests/unit/clients/ -v -k grok`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/clients/test_grok_multiround_usage.py
# Mock chat.sample() → three responses (usage 100/10, 150/20, 200/30),
# first two with tool_calls. Use a stub usage object exposing
# prompt_tokens/completion_tokens/total_tokens attributes (protobuf-like).
# Assert (450, 60), rounds == 3, and json.dumps(raw_usage) succeeds
# for every captured ClientRoundEvent.
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
