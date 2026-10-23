# TASK-4676: Declare the coverage field, the length caps and the reason codes

**Feature**: FEAT-737 — Plausibility coverage reporting and prompt length caps
**Spec**: `sdd/specs/services-plausibility-tech-debt.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. This is the model layer the rest of FEAT-737 builds
on: `PlausibilityReport.not_examined` is where coverage gaps get recorded, and
`LLMValidationConfig.max_answer_chars` / `max_reason_chars` are the knobs
TASK-4677 reads when it builds the prompt and stores a verdict.

This task resolves nothing observable on its own — it only makes the fields
exist. TASK-4677 populates them, and carries the `Discovered-from` links for
both ledger issues because it is the task that makes the behaviour real.

---

## Scope

- Add `max_answer_chars: int = Field(default=500, ge=1)` and
  `max_reason_chars: int = Field(default=300, ge=1)` to `LLMValidationConfig`.
- Add `not_examined: dict[str, str] = Field(default_factory=dict)` to
  `PlausibilityReport`, with the docstring the spec fixes.
- Add the two module-level reason-code constants `NOT_EXAMINED_MAX_FIELDS` and
  `NOT_EXAMINED_UNRENDERABLE`.
- Add one test proving `not_examined` reaches the client through
  `wire_report()` (i.e. it is NOT an audit-only field).

**NOT in scope**:
- Anything in `services/plausibility.py` — the `select_fields` split, the
  truncation helper and the `check()` composition are all TASK-4677.
- Adding `not_examined` to `PLAUSIBILITY_AUDIT_FIELDS`. The spec decided it is
  client-facing (§2 "Why client-facing, not audit-only"); do not change that set.
- `audio/engine.py` — out of scope for the whole feature (spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` | MODIFY | Two config caps, the report field, the two reason-code constants |
| `packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py` | MODIFY | Prove `not_examined` survives `wire_report()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py:9-13
from typing import TYPE_CHECKING, Any, Literal
from pydantic import BaseModel, Field, field_validator
from .types import FieldType

# verified: packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py:3
from parrot_formdesigner.core.llm_validation import PLAUSIBILITY_AUDIT_FIELDS, PlausibilityReport, wire_report
```

`Field` and `Any` are **already imported** in `llm_validation.py` — this task
adds no new import to the production file.

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py
class LLMValidationConfig(BaseModel):                                       # line 28
    enabled: bool = False                                                   # line 31
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)                   # line 32
    on_error: Literal["skip", "block"] = "skip"                             # line 33
    on_implausible: Literal["annotate", "review", "reject"] = "annotate"    # line 34
    model: str | None = None                                                # line 42
    timeout_s: float = Field(default=8.0, gt=0.0)                           # line 43
    max_fields: int = Field(default=50, ge=1)                               # line 44
    exclude_field_types: list[FieldType] = Field(...)                       # line 45

class PlausibilityReport(BaseModel):                                        # line 70
    status: Literal["ok", "skipped", "blocked"]                             # line 73
    reason: str | None = None                                               # line 74
    model: str | None = None                                                # line 75
    threshold: float                                                        # line 76
    latency_ms: int | None = None                                           # line 77
    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)     # line 78
    resolved_model: str | None = None                                       # line 79
    provider: str | None = None                                             # line 85
    usage: dict[str, Any] | None = None                                     # line 87

PLAUSIBILITY_AUDIT_FIELDS: frozenset[str] = frozenset({"resolved_model", "provider", "usage"})  # line 124
def wire_report(report: PlausibilityReport, **dump_kwargs: Any) -> dict[str, Any]:              # line 127
```

```python
# packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py
def _report() -> PlausibilityReport:  # line 6 — builds a report with every audit field set
def test_audit_fields_excluded() -> None:   # line 19
def test_other_fields_identical() -> None:  # line 24
def test_extra_exclude_is_widened() -> None:  # line 31
```

### Does NOT Exist

- ~~`PlausibilityReport.unchecked`~~ / ~~`.skipped_fields`~~ / ~~`.coverage`~~ / ~~`.not_checked`~~ — the field is named `not_examined`, nothing else.
- ~~`LLMValidationConfig.max_prompt_chars`~~ / ~~`.max_chars`~~ / ~~`.max_answer_length`~~ — the names are `max_answer_chars` and `max_reason_chars`.
- ~~`llm_validation.NOT_EXAMINED_REASONS`~~ — no container/enum is added; just the two `str` constants.
- ~~`PlausibilityVerdict.truncated`~~ — not added by this feature.
- `PlausibilityVerdict._clamp` exists (line 55-67) but this task does **not** touch it.

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
      "path": "packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#LLMValidationConfig",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#PlausibilityReport",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#wire_report"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Pydantic v2 only; `Field(...)` with explicit bounds (`ge=1`) so an invalid
  config fails at construction, not at prompt-build time.
- 120-column lines; `black` formats, `ruff check` gates.
- Field docstrings follow the file's existing style: a `"""…"""` string
  immediately *below* the field (see `resolved_model` at lines 79-84).
- Defaults are chosen to be inert for existing forms: 500 characters is far
  longer than any realistic form answer, so turning this on changes no current
  behaviour — it only bounds the pathological case.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py:79-88` —
  the field-plus-docstring pattern to copy for `not_examined`.
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py:121-124` —
  the existing module-constant block to put the reason codes beside.

---

## Implementation Blueprint

### Steps (in order)
1. Add the two cap fields to `LLMValidationConfig` after `exclude_field_types` — *why*: they are limits like `max_fields`, so they belong with the other bounds, and appending keeps every existing positional/keyword use of the model valid.
2. Add `not_examined` as the last field of `PlausibilityReport` — *why*: a defaulted field appended at the end keeps every persisted report in `audio/session_store.py` deserializable.
3. Add the two reason-code constants next to `PLAUSIBILITY_AUDIT_FIELDS` — *why*: TASK-4677 and the tests must spell the codes from one place, never as inline literals.
4. Add the `wire_report` test — *why*: AC9 is the one claim about this field that a reader cannot check by eye, since `wire_report` excludes by an allow-list that lives in another constant.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` (MODIFY — config caps)
```python
# occurrences: 1 (verified: grep -c '    exclude_field_types: list[FieldType] = Field(default_factory=lambda: list(_DEFAULT_EXCLUDED))' packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py)
# AFTER — insert below `    exclude_field_types: list[FieldType] = Field(default_factory=lambda: list(_DEFAULT_EXCLUDED))` (verified: core/llm_validation.py:45)
    max_answer_chars: int = Field(default=500, ge=1)
    """Max characters of a rendered answer placed in the prompt (FEAT-737).

    Longer text is truncated with a trailing ``…`` so the model can see the
    answer was cut rather than silently judging a fragment as if it were whole.
    """
    max_reason_chars: int = Field(default=300, ge=1)
    """Max characters kept from the model's returned ``reason`` (FEAT-737).

    Bounds what a verbose or adversarial response can persist into the audit
    record and echo back to the client.
    """
```
**Why this shape**: both are hard bounds on untrusted-length text, so they sit
with `max_fields` as the third and fourth limit on the config rather than in a
nested block. `ge=1` means a caller cannot configure a zero-length cap that
would erase every answer. The defaults must stay 500/300 — AC1 names them, and
they are deliberately high enough that no existing form changes behaviour.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` (MODIFY — report field)
```python
# occurrences: 1 (verified: grep -c '    """Token usage of the call (``AIMessage.usage``), JSON-dumped."""' packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py)
# AFTER — insert below `    """Token usage of the call (``AIMessage.usage``), JSON-dumped."""` (verified: core/llm_validation.py:88)
    not_examined: dict[str, str] = Field(default_factory=dict)
    """Eligible field ids the model never saw, by reason code (FEAT-737).

    Keys are field ids; values are ``NOT_EXAMINED_MAX_FIELDS`` or
    ``NOT_EXAMINED_UNRENDERABLE``. Empty on a ``skipped``/``blocked`` report —
    those statuses already say the whole batch went unexamined. A
    ``status="ok"`` report with a non-empty map means PARTIAL coverage:
    ``items`` is authoritative only for the field ids absent from this map.
    """
```
**Why**: the anchor is the `usage` *docstring*, not the `usage` field line —
inserting after the field line would split the field from its own docstring.
Appending at the end of the model keeps older persisted reports loadable.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` (MODIFY — reason codes)
```python
# occurrences: 1 (verified: grep -c 'PLAUSIBILITY_AUDIT_FIELDS: frozenset[str] = frozenset({"resolved_model", "provider", "usage"})' packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py)
# AFTER — insert below `PLAUSIBILITY_AUDIT_FIELDS: frozenset[str] = frozenset({"resolved_model", "provider", "usage"})` (verified: core/llm_validation.py:124)

#: ``PlausibilityReport.not_examined`` reason: cut by ``LLMValidationConfig.max_fields`` (FEAT-737).
NOT_EXAMINED_MAX_FIELDS: str = "max_fields_cap"

#: ``PlausibilityReport.not_examined`` reason: the answer could not be rendered as
#: prompt text (dict answers, or lists holding dicts/lists) — FEAT-737.
NOT_EXAMINED_UNRENDERABLE: str = "unrenderable_answer"
```
**Why**: the literal strings are part of the wire contract (they reach the
client through `wire_report`), so they are named once here. Do **not** add them
to `PLAUSIBILITY_AUDIT_FIELDS`, and do not add `not_examined` to it either —
that set is vendor-identity only (FEAT-732 spec §7 R10).

### `packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_extra_exclude_is_widened() -> None:' packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py)
# AFTER — insert below the body of `def test_extra_exclude_is_widened() -> None:` (verified: tests/unit/test_plausibility_wire_report.py:31-33)


def test_not_examined_reaches_the_client() -> None:
    """``not_examined`` is coverage data, not vendor data — it is NOT audit-only."""
    # FILL IN: build a report with a non-empty not_examined and assert the key
    # survives wire_report(..., mode="json") with its reason code intact, and
    # that "not_examined" is absent from PLAUSIBILITY_AUDIT_FIELDS — bounded by AC9.
```
**Why**: `wire_report()` strips exactly `PLAUSIBILITY_AUDIT_FIELDS`, so the only
way a reader can confirm the spec's client-facing decision held is a test that
round-trips a populated map. Import the reason-code constant rather than writing
`"unrenderable_answer"` inline.

### FILL IN checklist
- [ ] `test_plausibility_wire_report.py::test_not_examined_reaches_the_client` — construct the populated report and assert both halves (key survives, field not in the audit set); bounded by AC9.

---

## Acceptance Criteria

- [ ] `LLMValidationConfig(max_answer_chars=0)` raises; the default is 500 (spec AC1).
- [ ] `LLMValidationConfig(max_reason_chars=0)` raises; the default is 300 (spec AC1).
- [ ] `PlausibilityReport(status="ok", threshold=0.7).not_examined == {}` (spec AC2).
- [ ] `NOT_EXAMINED_MAX_FIELDS == "max_fields_cap"` and `NOT_EXAMINED_UNRENDERABLE == "unrenderable_answer"` are importable from `parrot_formdesigner.core.llm_validation` (spec AC2).
- [ ] `"not_examined" not in PLAUSIBILITY_AUDIT_FIELDS` and it appears in `wire_report()` output (spec AC9).
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py`
- [ ] Both Validation Commands pass.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py
from parrot_formdesigner.core.llm_validation import (
    NOT_EXAMINED_UNRENDERABLE,
    PLAUSIBILITY_AUDIT_FIELDS,
    PlausibilityReport,
    wire_report,
)


def test_not_examined_reaches_the_client() -> None:
    """``not_examined`` is coverage data, not vendor data — it is NOT audit-only."""
    report = PlausibilityReport(
        status="ok", threshold=0.7, items={}, not_examined={"doc": NOT_EXAMINED_UNRENDERABLE}
    )
    assert "not_examined" not in PLAUSIBILITY_AUDIT_FIELDS
    wire = wire_report(report, mode="json")
    assert wire["not_examined"] == {"doc": "unrenderable_answer"}
```

The three existing tests in this file must keep passing unchanged —
`test_other_fields_identical` compares `wire_report` against
`model_dump(exclude=PLAUSIBILITY_AUDIT_FIELDS)`, which stays true for a widened
model as long as `not_examined` is not added to the audit set.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug services-plausibility-tech-debt --feature-id FEAT-737`)
2. **Read the spec** at `sdd/specs/services-plausibility-tech-debt.spec.md` (§2, §3 Module 1, §5 AC1/AC2/AC9)
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** before writing any code; re-run the three
   `grep -c` anchor checks in the blueprint and correct the `path:NN` if a count
   still matches but the line moved. A count of `0` means drift — stop and report.
5. **Update status** in `sdd/tasks/index/services-plausibility-tech-debt.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; complete the one `FILL IN`
7. **Verify** the acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/parrot-formdesigner/src` prefixed (the shared `.venv` is
   editable-installed against the MAIN checkout, so a bare `pytest` inside a
   worktree imports the wrong branch)
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4676 services-plausibility-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: Claude Opus 5.5 (/sdd-fix SDD lane, FEAT-737)
**Date**: 2026-10-24
**Notes**: Added `LLMValidationConfig.max_answer_chars` (default 500, ge=1) and
`max_reason_chars` (default 300, ge=1); added `PlausibilityReport.not_examined`
(`dict[str, str]`, default `{}`) as the model's last field so persisted reports in
`audio/session_store.py` stay loadable; added the `NOT_EXAMINED_MAX_FIELDS` /
`NOT_EXAMINED_UNRENDERABLE` reason-code constants next to
`PLAUSIBILITY_AUDIT_FIELDS`. `PLAUSIBILITY_AUDIT_FIELDS` itself is unchanged
(still exactly `resolved_model`/`provider`/`usage`), so `not_examined` reaches the
client — the spec §2 decision.

Two tests added to `tests/unit/test_plausibility_wire_report.py`
(`test_not_examined_reaches_the_client`, `test_not_examined_defaults_empty`); the
three pre-existing tests in that file pass unchanged, including
`test_other_fields_identical`, which compares `wire_report` against
`model_dump(exclude=PLAUSIBILITY_AUDIT_FIELDS)` and therefore proves the widened
model did not leak into the audit set.

Verified: 16 passed across both Validation Commands; `ruff check` clean; `black`
applied (it joined the new test's report construction onto one 120-col line).
AC1/AC2/AC9 checked directly — defaults are 500/300, `max_answer_chars=0` and
`max_reason_chars=0` both raise `ValidationError`, and the imported module
resolved from the worktree (not the main checkout) as printed by `m.__file__`.

**Deviations from spec**: none
