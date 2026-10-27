# TASK-4623: `on_implausible` policy field + pure `implausible_fields()` classifier

**Feature**: FEAT-728 — FormBuilder LLM-validation enforcement policy + LLM quota
**Spec**: `sdd/specs/formbuilder-llm-validation-enforcement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. FEAT-649 ships an LLM plausibility verdict that nothing acts
on outside the voice channel. This task adds the knob that says what to do with
an implausible answer (`LLMValidationConfig.on_implausible`) and the single pure
function that decides which answers tripped it
(`implausible_fields(report)`). Everything downstream — the pipeline gate
(TASK-4624), the HTTP mapping (TASK-4625), the audio path (TASK-4628) — reads
these two things and nothing else, so they must land first and must stay
I/O-free.

---

## Scope

- Add `on_implausible: Literal["annotate", "review", "reject"] = "annotate"` to
  `LLMValidationConfig`.
- Add the module-level function `implausible_fields(report: PlausibilityReport) -> list[str]`.
- Re-export `implausible_fields` from `parrot_formdesigner.core`.
- Write unit tests for the default, the two flagging rules, the strict `<`
  boundary and the non-`ok` short-circuit.

**NOT in scope**: the gate itself (`SubmissionPipeline.gate_for`, TASK-4624);
any HTTP/response change (TASK-4625); the quota (TASK-4626/4627); a per-field
policy override (spec Non-Goal); touching `AnswerPlausibilityChecker`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` | MODIFY | Add the `on_implausible` field and the `implausible_fields()` classifier |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | Re-export `implausible_fields` (import block + `__all__`) |
| `packages/parrot-formdesigner/tests/unit/test_llm_validation_policy.py` | CREATE | Unit tests for the field default and the classifier |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Literal                                   # verified: core/llm_validation.py:10
from pydantic import BaseModel, Field, field_validator        # verified: core/llm_validation.py:12
from .types import FieldType                                  # verified: core/llm_validation.py:13
# test side:
from parrot_formdesigner.core.llm_validation import (          # verified: core/llm_validation.py:28,62,39
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
    implausible_fields,          # added by THIS task
)
from parrot_formdesigner.core import implausible_fields        # after the __init__ re-export below
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py
class LLMValidationConfig(BaseModel):                     # line 28
    """Per-form LLM plausibility settings (``FormSchema.llm_validation``)."""
    enabled: bool = False                                 # line 31
    threshold: float = Field(default=0.7, ge=0.0, le=1.0) # line 32
    on_error: Literal["skip", "block"] = "skip"           # line 33  <-- insertion anchor
    model: str | None = None                              # line 34
    timeout_s: float = Field(default=8.0, gt=0.0)         # line 35
    max_fields: int = Field(default=50, ge=1)             # line 36
    exclude_field_types: list[FieldType]                  # line 37

class PlausibilityVerdict(BaseModel):                     # line 39
    plausible: bool                                       # line 42
    confidence: float = Field(ge=0.0, le=1.0)             # line 43
    reason: str                                           # line 44

class PlausibilityReport(BaseModel):                      # line 62
    status: Literal["ok", "skipped", "blocked"]           # line 65
    reason: str | None = None                             # line 66
    model: str | None = None                              # line 67
    threshold: float                                      # line 68   (no default — tests must pass it)
    latency_ms: int | None = None                         # line 69
    items: dict[str, PlausibilityVerdict]                 # line 70

def llm_validation_enabled(form: FormSchema, field: FormField) -> bool:   # line 73

# packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py
from .llm_validation import (            # lines 60-65
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
    llm_validation_enabled,              # line 64  <-- import anchor
)
__all__ = [ ..., "llm_validation_enabled", ... ]          # line 97  <-- __all__ anchor
```

### Does NOT Exist

- ~~`LLMValidationConfig.on_implausible`~~ — THIS task adds it. `on_error`
  (line 33) is a different knob: it governs LLM *unavailability* only.
- ~~`PlausibilityReport.flagged`~~ / ~~`.implausible`~~ / ~~`.failed_fields`~~ —
  not fields on the model; flagging is computed, never stored.
- ~~`PlausibilityReport.status == "rejected"`~~ — the Literal is only
  `"ok" | "skipped" | "blocked"` (line 65). Do NOT add a status value.
- ~~`PlausibilityVerdict.threshold`~~ — the threshold lives on the *report*
  (line 68), not on each verdict.
- ~~`FormField.llm_validation_policy`~~ — no per-field policy exists (spec
  Non-Goal); only `field.llm_validation: bool | None` (`core/schema.py:153`).
- ~~`implausible_fields(report, config)`~~ — the signature takes the report
  ALONE. Adding a config parameter is a contract break for TASK-4624/4625/4628.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/test_llm_validation_policy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#LLMValidationConfig",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#PlausibilityReport",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#PlausibilityVerdict",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#llm_validation_enabled"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- `implausible_fields()` must be **pure**: no I/O, no logging, no config
  argument, no mutation of the report. Three callers depend on calling it twice
  (dry-run and commit) and getting the same answer.
- The comparison is **strict `<`**: `confidence == threshold` passes. This
  mirrors `audio/engine.py:975`; a `<=` here would make voice and HTTP disagree
  on the same verdict.
- Return a **sorted** list — downstream error dicts and test assertions depend
  on a stable order.
- A report whose `status` is not `"ok"` returns `[]`. `skipped`/`blocked`
  reports already have their own path (`on_error`), and flagging them here
  would double-handle an LLM failure as an implausible answer.
- Pydantic v2 `Literal` for the policy, never a bare `str`.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py:969-979`
  — the existing flagging rule this function must reproduce exactly.
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py:73-82`
  — `llm_validation_enabled`: the module's existing "small pure helper" shape.

---

## Implementation Blueprint

### Steps (in order)

1. Add the `on_implausible` field directly below `on_error` in
   `LLMValidationConfig` — *why*: the two knobs are read together and keeping
   them adjacent makes the "unavailability vs implausibility" split obvious to
   the next reader.
2. Add `implausible_fields()` below `llm_validation_enabled` — *why*: both are
   module-level pure helpers over the models above them; the file's existing
   layout puts models first, helpers last.
3. Re-export it from `core/__init__.py` (import block **and** `__all__`) —
   *why*: every other `core.llm_validation` public name is re-exported there; a
   missing entry would make `from parrot_formdesigner.core import …` fail for
   this one symbol only.
4. Write the unit tests — *why*: AC1/AC2 are the only guard on the strict `<`
   boundary and the non-`ok` short-circuit, which are easy to "simplify" later.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` (MODIFY — 1 of 2)

```python
# occurrences: 1 (verified: grep -c '    on_error: Literal["skip", "block"] = "skip"' packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py)
# AFTER — insert below `    on_error: Literal["skip", "block"] = "skip"` (verified: core/llm_validation.py:33)
    on_implausible: Literal["annotate", "review", "reject"] = "annotate"
    """What to do with an answer the model judged implausible.

    ``annotate`` (default) stores it with the verdict attached — FEAT-649
    behaviour, unchanged; ``review`` refuses the submission until the client
    reconfirms; ``reject`` always refuses. Distinct from ``on_error``, which
    governs LLM *unavailability* only.
    """
```

**Why this shape**: the default `"annotate"` is what makes the whole feature
backwards compatible (AC3) — every form written before FEAT-728 keeps storing
implausible answers and answering `200`. Do NOT reorder the existing fields, and
do NOT give the Literal a fourth value: `gate_for()` (TASK-4624) exhaustively
matches these three.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` (MODIFY — 2 of 2)

```python
# occurrences: 1 (verified: grep -c 'def llm_validation_enabled(form: FormSchema, field: FormField) -> bool:' packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py)
# AFTER — append below the body of `def llm_validation_enabled(form: FormSchema, field: FormField) -> bool:` (verified: core/llm_validation.py:73, body ends at :82)


def implausible_fields(report: PlausibilityReport) -> list[str]:
    """Field ids whose verdict trips the enforcement gate, sorted.

    A field trips when the model judged it ``not plausible``, or when its
    ``confidence`` is strictly below ``report.threshold`` — the threshold
    travels on the report itself (set by ``AnswerPlausibilityChecker.check``,
    services/plausibility.py:205-207), so no config is needed here.

    Args:
        report: One plausibility batch outcome.

    Returns:
        Sorted field ids. Empty for any report whose ``status`` is not
        ``"ok"``: a ``skipped`` or ``blocked`` report belongs to the
        ``on_error`` path, never to the gate's.
    """
    if report.status != "ok":
        return []
    return sorted(
        field_id
        for field_id, verdict in report.items.items()
        if not verdict.plausible or verdict.confidence < report.threshold
    )
```

**Why**: this is the single definition of "implausible" for every channel. The
early return on `status != "ok"` is what keeps an LLM outage from being reported
to the user as a bad answer. Keep it a generator inside `sorted()` — no
intermediate list, no logging (this function runs on the submit hot path).

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` (MODIFY — 1 of 2)

```python
# occurrences: 1 (verified: grep -c '    llm_validation_enabled,' packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py)
# AFTER — insert below `    llm_validation_enabled,` inside the `from .llm_validation import (` block (verified: core/__init__.py:64)
    implausible_fields,
```

**Why**: alphabetical order is not used in this block (it ends with the helper
function), so append the new helper after the existing one.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` (MODIFY — 2 of 2)

```python
# occurrences: 1 (verified: grep -c '    "llm_validation_enabled",' packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py)
# AFTER — insert below `    "llm_validation_enabled",` in `__all__` (verified: core/__init__.py:97)
    "implausible_fields",
```

**Why**: `__all__` mirrors the import block above it; both must list the symbol
or `from parrot_formdesigner.core import implausible_fields` fails.

### `packages/parrot-formdesigner/tests/unit/test_llm_validation_policy.py` (CREATE)

```python
"""Unit tests for the on_implausible policy field and implausible_fields() (FEAT-728, TASK-4623)."""

from __future__ import annotations

import pytest
from parrot_formdesigner.core.llm_validation import (
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
    implausible_fields,
)


def _report(status: str = "ok", threshold: float = 0.7, **items: PlausibilityVerdict) -> PlausibilityReport:
    """A report carrying the given verdicts; ``threshold`` has no model default."""
    return PlausibilityReport(status=status, threshold=threshold, items=dict(items))


def _verdict(plausible: bool = True, confidence: float = 1.0) -> PlausibilityVerdict:
    return PlausibilityVerdict(plausible=plausible, confidence=confidence, reason="")


class TestPolicyField:
    def test_on_implausible_defaults_to_annotate(self) -> None:
        """A config written before FEAT-728 still validates, with today's behaviour."""
        # FILL IN: assert the default on both an empty config and a dict that omits the key
        #          — bounded by AC1 (backwards compatibility)

    def test_on_implausible_rejects_unknown_value(self) -> None:
        """The Literal refuses anything outside annotate|review|reject."""
        # FILL IN: pytest.raises(ValidationError) on on_implausible="hold" — bounded by AC1


class TestImplausibleFields:
    def test_flags_not_plausible(self) -> None:
        """plausible=False trips regardless of confidence."""
        # FILL IN: one verdict plausible=False, confidence=1.0 — bounded by AC2

    def test_flags_below_threshold(self) -> None:
        """confidence < threshold trips."""
        # FILL IN — bounded by AC2

    def test_threshold_boundary_is_strict(self) -> None:
        """confidence == threshold passes (mirrors audio/engine.py:975)."""
        # FILL IN — bounded by AC2 and the strict-`<` constraint

    def test_returns_sorted_ids(self) -> None:
        """Several flagged fields come back sorted."""
        # FILL IN — bounded by AC2

    @pytest.mark.parametrize("status", ["skipped", "blocked"])
    def test_empty_for_non_ok_status(self, status: str) -> None:
        """A skipped/blocked report flags nothing even with flagged verdicts in items."""
        # FILL IN — bounded by AC2 (the on_error path must stay separate)

    def test_empty_report_is_empty(self) -> None:
        """An ok report with no items flags nothing."""
        # FILL IN — bounded by AC2
```

**Why this shape**: `PlausibilityReport.threshold` has **no default** (line 68),
so every test must pass it — the `_report` helper exists to stop that being
rediscovered per test. The parametrized non-`ok` test is the regression guard for
the early return.

### FILL IN checklist

- [ ] `test_llm_validation_policy.py::TestPolicyField::test_on_implausible_defaults_to_annotate` — assert the default; bounded by AC1
- [ ] `test_llm_validation_policy.py::TestPolicyField::test_on_implausible_rejects_unknown_value` — `ValidationError` on a bad literal; bounded by AC1
- [ ] `test_llm_validation_policy.py::TestImplausibleFields::*` — six bodies; bounded by AC2 (strict `<`, sorted output, non-`ok` → `[]`)

---

## Acceptance Criteria

- [ ] `LLMValidationConfig.on_implausible` exists, is `Literal["annotate", "review", "reject"]`, defaults to `"annotate"`, and an existing config payload that omits the key still validates (spec AC1).
- [ ] `implausible_fields(report)` takes the report alone, performs no I/O, flags `not plausible` or `confidence < report.threshold`, returns `[]` for any `status != "ok"`, and returns a sorted list (spec AC2).
- [ ] `confidence == report.threshold` does NOT trip the gate.
- [ ] `from parrot_formdesigner.core import implausible_fields` works.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py packages/parrot-formdesigner/tests/unit/test_llm_validation_policy.py`

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_llm_validation_policy.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -q`

---

## Test Specification

See the CREATE block above — it is the scaffold. Every `FILL IN` body must
assert against the real models (no mocks needed: these are pure Pydantic
objects and one pure function).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug formbuilder-llm-validation-enforcement --feature-id FEAT-728`)
2. **Read the spec** at the path listed above (§3 Module 1, §7 Known Risks)
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** before writing any code: re-run each
   `grep -c` in the blueprint blocks. A count of `0` means the anchor moved —
   stop and report the drift rather than inventing an attachment point.
5. **Update status** in `sdd/tasks/index/formbuilder-llm-validation-enforcement.json`
   → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; complete every `# FILL IN:` marker. Tests
   inside a worktree need `PYTHONPATH=packages/parrot-formdesigner/src`.
7. **Verify** the Validation Commands pass
8. **Commit the code** — stage only the three files this task lists
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4623 formbuilder-llm-validation-enforcement verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Delivered by seat gpt-5.6-terra (codex), 1 attempt, 149s. Merge-tier validation green (189 passed). Reviewed by worker: no defects. Review recorded: coder-review:c99c304af5bed63fb7f4bc12.
