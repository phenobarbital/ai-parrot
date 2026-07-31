# TASK-2031: CompletionUsage.__add__ + AIMessage.total_usage()

**Feature**: FEAT-397 — Per-Round Token Usage Observability
**Spec**: `sdd/specs/tokens-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Modules 1 & 4 (merged: both are small model-layer primitives).
Multi-round tool loops need an accumulation primitive on `CompletionUsage`
and a stable `total_usage()` entry point on `AIMessage`. Every client task
(TASK-2034…2038) builds on `__add__`.

---

## Scope

- Implement `CompletionUsage.__add__(self, other) -> CompletionUsage`:
  - `prompt_tokens`, `completion_tokens`, `total_tokens`: int sum.
  - Timing fields (`completion_time`, `prompt_time`, `queue_time`,
    `total_time`): sum when either side is set; `None + None → None`;
    `None + x → x` (resolved in brainstorm: cumulative time).
  - `estimated_cost`: same None-aware sum.
  - `extra_usage`: shallow merge, right side wins on key conflict.
  - Returns a NEW instance; never mutates operands.
- Document the `extra_usage["rounds"]` convention in the class docstring
  (clients set it post-loop; this task only documents it).
- Implement `AIMessage.total_usage(self) -> CompletionUsage` returning
  `self.usage`, with a docstring explaining it is the multi-round total.
- Unit tests for both.

**NOT in scope**: any client loop changes (TASK-2034…2038), the
`ClientRoundEvent` (TASK-2032), setting `extra_usage["rounds"]` anywhere.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/basic.py` | MODIFY | Add `__add__` to `CompletionUsage` + docstring note |
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | Add `total_usage()` to `AIMessage` |
| `packages/ai-parrot/tests/unit/models/test_completion_usage_add.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import CompletionUsage      # models/basic.py:48
from parrot.models.responses import AIMessage        # models/responses.py:72
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/basic.py
class CompletionUsage(BaseModel):                    # line 48
    model_config = ConfigDict(populate_by_name=True) # line 66
    prompt_tokens: int       # line 70, validation_alias also accepts "input_tokens"
    completion_tokens: int   # line 73, validation_alias also accepts "output_tokens"
    total_tokens: int = 0    # line 76
    completion_time: Optional[float] = None  # line 79
    prompt_time: Optional[float] = None      # line 80
    queue_time: Optional[float] = None       # line 81
    total_time: Optional[float] = None       # line 82
    estimated_cost: Optional[float] = None   # line 85
    extra_usage: Dict[str, Any]              # line 88
    # computed read-only properties: input_tokens (line 96), output_tokens (line 102)
    # — these are @computed_field properties; do NOT try to set them in __add__.

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                          # line 72
    usage: CompletionUsage   # line 118 — stored field
```

### Does NOT Exist
- ~~`CompletionUsage.__add__`~~ — created by THIS task
- ~~`AIMessage.total_usage()`~~ — created by THIS task
- ~~`AIMessage.usage_history`~~ — rejected design; do NOT add
- ~~`CompletionUsage.rounds_count`~~ — no typed field; round count lives in `extra_usage["rounds"]` (set by client tasks, not here)

---

## Implementation Notes

### Pattern to Follow
```python
# Accumulation precedent: packages/ai-parrot/src/parrot/clients/gemma4.py:528-546
# builds a new CompletionUsage from summed fields each round.
```

### Key Constraints
- `input_tokens`/`output_tokens` are computed read-only aliases — construct
  the result via the canonical field names (`prompt_tokens=`,
  `completion_tokens=`).
- Return `NotImplemented` when `other` is not a `CompletionUsage` (standard
  dunder protocol), so `sum()` misuse fails loudly.
- Google-style docstrings, strict type hints.

---

## Acceptance Criteria

- [ ] `u1 + u2` sums token fields; result is a new instance.
- [ ] Timing/cost fields: None+None→None, None+x→x, x+y→x+y.
- [ ] `extra_usage` merges shallowly, right wins.
- [ ] `AIMessage.total_usage()` returns `self.usage` (identity).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/models/test_completion_usage_add.py -v`
- [ ] Existing model tests still pass: `pytest packages/ai-parrot/tests/unit/models/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/models/test_completion_usage_add.py
from parrot.models.basic import CompletionUsage

def test_add_tokens():
    a = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    b = CompletionUsage(prompt_tokens=20, completion_tokens=7, total_tokens=27)
    c = a + b
    assert (c.prompt_tokens, c.completion_tokens, c.total_tokens) == (30, 12, 42)
    assert c is not a and c is not b

def test_add_timing_none_aware():
    a = CompletionUsage(completion_time=1.0)
    b = CompletionUsage()
    assert (a + b).completion_time == 1.0
    assert (b + b).completion_time is None

def test_add_extra_merge_right_wins():
    a = CompletionUsage(extra_usage={"x": 1, "shared": "a"})
    b = CompletionUsage(extra_usage={"y": 2, "shared": "b"})
    assert (a + b).extra_usage == {"x": 1, "y": 2, "shared": "b"}

def test_total_usage_identity():
    from parrot.models.responses import AIMessage
    msg = AIMessage(input="q", output="a", model="m", provider="p",
                    usage=CompletionUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3))
    assert msg.total_usage() is msg.usage
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/tokens-observability.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill in the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
