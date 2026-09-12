# TASK-3188: AttemptTelemetry transport models

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, first file, and the resolution of §10 R3 (silent payload
loss). Rich telemetry cannot travel on a `dispatch.completed` payload:
`action_from_dispatch_event` copies exactly seven whitelisted scalars out of
`payload["usage"]` into the closed `DispatchCompleted` model, and
`_apply_to_session_host` swallows any validation error by design
(`dispatchers/_shared.py:118-124`) — so extra keys vanish with no error.

This task creates the typed payload that travels by an explicit hook instead.
It is a new standalone file with no dependencies, which makes it safely
parallel with the other foundation tasks.

---

## Scope

- Create `parrot/flows/dev_loop/models/telemetry.py` with `MAX_TURN_SERIES`,
  `TurnUsage` and `AttemptTelemetry`.
- Write unit tests for the series cap and for a turn with unknown usage.

**NOT in scope**: emitting it (TASK-3189), persisting it (TASK-3191/3193), the
`AttemptRecord` fields (TASK-3192). Nothing imports this module yet.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/telemetry.py` | CREATE | Transport models |
| `packages/ai-parrot/tests/flows/dev_loop/test_attempt_telemetry_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field   # pydantic is a core dependency
```
Nothing from `parrot.*` is needed: this module is intentionally dependency-free
so it cannot create an import cycle with `dispatchers/llm.py`.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py
class LLMCodeDispatchProfile(BaseModel):                             # line 10
    max_turns: int = Field(default=24, ge=1, le=100)                 # line 23  <-- the 100 cap
    max_tokens: int = Field(default=8192, ge=256, le=32768)          # line 24

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
@staticmethod
def _extract_usage(response) -> tuple[Optional[CompletionUsage], Optional[Dict[str, Any]]]:  # line 1089
#   returns (None, None) when the provider reported no usage for the round
if usage is not None: accumulated = ... + usage                       # lines 331-333
#   ^ a round with no usage is SKIPPED; the subtotal survives, so a non-null
#     aggregate does not prove complete reporting
salvaged, salvage_usage, salvage_error = await self._salvage_final_output(...)  # line 552
#   ^ the post-loop salvage call: one more turn beyond max_turns
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop.models.telemetry`~~ — this task creates it. `models/` today
  holds `llm.py`, `nova.py` and siblings; verify with `ls packages/ai-parrot/src/parrot/flows/dev_loop/models/`.
- ~~`TurnUsage` / `AttemptTelemetry` anywhere in the tree~~ — new names.
- ~~`CompletionUsage.round_number`~~ — `parrot.models.basic.CompletionUsage` has no
  round concept; that is exactly why `TurnUsage` exists.
- ~~`List[List[int]]` for the series~~ — rejects a turn with unknown usage. Do not use it
  here or in any downstream model (spec §10 R6).

---

## Implementation Notes

### Key Constraints
- Token fields MUST be `Optional[int]`. A provider that reports no usage for a
  round is normal (`_extract_usage` returns `None`), and a `0` there would be a
  lie that silently biases every percentile computed downstream.
- `MAX_TURN_SERIES = 101`, not a round number: `max_turns` is capped at 100 by
  the profile plus the one post-loop salvage call. Chosen so the series can
  never be truncated.
- Pydantic v2 style (`Field`, `max_length` on the list), matching the sibling
  models in this package.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py` — the sibling
  model module's docstring/field style to match.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module with both models and the constant — *why*: they are one contract and splitting them across files would invite a circular import later.
2. Set `MAX_TURN_SERIES = 101` and say why in its docstring — *why*: a future reader will otherwise "round it up" to 128 or down to 60 and either truncate real data or waste the line budget TASK-3191 depends on.
3. Add the two tests — *why*: the unknown-usage case is the exact defect the adversarial review found in the first draft.

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/telemetry.py` (CREATE)
```python
"""Per-attempt telemetry transport for coding-agent dispatch loops (FEAT-554).

These models travel from `LLMCodeDispatcher` to the bound session host through
an explicit hook, NOT through a `dispatch.completed` payload: that path copies
only seven whitelisted scalars into the closed `DispatchCompleted` model and
swallows validation failures by design (`dispatchers/_shared.py:118-124`), so
extra keys would be dropped in silence (spec §10 R3).
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

MAX_TURN_SERIES: int = 101
"""Every turn a loop can possibly produce.

`LLMCodeDispatchProfile.max_turns` is capped at 100 (verified:
parrot/flows/dev_loop/models/llm.py:23) plus the one post-loop salvage call
(verified: parrot/flows/dev_loop/dispatchers/llm.py:552). Sized to never
truncate a real series rather than as a size heuristic; the persisted line
budget in `sdd_coder/telemetry.py` is sized to fit it.
"""


class TurnUsage(BaseModel):
    """One turn's reported usage inside a coding-agent loop.

    Token fields are nullable because `_extract_usage` returns ``None`` when a
    provider reports no usage for a round (verified:
    parrot/flows/dev_loop/dispatchers/llm.py:1089) and the loop continues. A
    ``None`` here is a KNOWN GAP, never a zero: it is counted in
    `AttemptTelemetry.turns_with_unknown_usage` and makes the attempt
    ineligible as a calibration sample (spec §10 R5-R6).
    """

    round_number: int = Field(..., ge=1)
    input_tokens: Optional[int] = Field(None, ge=0)
    output_tokens: Optional[int] = Field(None, ge=0)


class AttemptTelemetry(BaseModel):
    """Terminal telemetry for ONE dispatch attempt — success, failure or salvage."""

    resolved_model: str = Field("", max_length=200)
    turns: int = Field(0, ge=0)
    terminal: Literal["completed", "failed", "salvaged"] = "completed"
    error_class: str = Field("", max_length=120)
    provider_input_tokens: Optional[int] = Field(None, ge=0)
    provider_output_tokens: Optional[int] = Field(None, ge=0)
    turn_series: List[TurnUsage] = Field(default_factory=list, max_length=MAX_TURN_SERIES)
    turns_with_unknown_usage: int = Field(0, ge=0)
    budget_report: Optional[Dict[str, Any]] = None
    """`BudgetReport.model_dump()` when an observational ledger was bound, else None."""
```
**Why this shape**: `error_class` carries only the exception type, never the message — the dataset is counters-only and `AttemptRecord.error` already holds the full string for human debugging (spec §10 R5). `budget_report` is a plain dict rather than a typed `BudgetReport` so this module stays free of `parrot.clients` imports and cannot cycle. `terminal` distinguishes salvage from clean completion because a salvaged attempt consumed an extra turn beyond `max_turns` and reads differently in the analysis.

### FILL IN checklist
*(none — fully determined)*

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_loop.models.telemetry import AttemptTelemetry, TurnUsage, MAX_TURN_SERIES` works.
- [ ] `MAX_TURN_SERIES == 101`.
- [ ] `TurnUsage(round_number=7)` validates with both token fields `None`.
- [ ] `AttemptTelemetry(turn_series=[TurnUsage(round_number=i) for i in range(1, 103)])` raises `ValidationError` (over the cap).
- [ ] `TurnUsage(round_number=0)` and `TurnUsage(round_number=1, input_tokens=-1)` both raise `ValidationError`.
- [ ] The module imports nothing from `parrot.clients` or `parrot.flows.dev_loop.dispatchers`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_attempt_telemetry_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/models/telemetry.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_attempt_telemetry_models.py
import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.models.telemetry import MAX_TURN_SERIES, AttemptTelemetry, TurnUsage


class TestTurnUsage:
    def test_unknown_usage_is_representable(self):
        turn = TurnUsage(round_number=7)
        assert turn.input_tokens is None and turn.output_tokens is None

    def test_round_number_is_one_indexed(self):
        with pytest.raises(ValidationError):
            TurnUsage(round_number=0)


class TestAttemptTelemetry:
    def test_series_cap(self):
        # FILL IN: build MAX_TURN_SERIES + 1 turns and assert ValidationError;
        # then MAX_TURN_SERIES turns and assert it validates — bounded by AC
        raise NotImplementedError

    def test_defaults_are_empty_not_zero(self):
        # FILL IN: assert provider_* default to None (not 0) and budget_report
        # to None — bounded by "a None is a known gap, never a zero"
        raise NotImplementedError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 Data Models, §3 Module 2, §10 R3/R6.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `models/telemetry.py` does not already exist.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; change no field name or type.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3188-attempt-telemetry-models.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
