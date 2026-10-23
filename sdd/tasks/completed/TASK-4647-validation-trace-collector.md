# TASK-4647: `ValidationTraceCollector`, `schema_fingerprint()` and `cap_trace()`

**Feature**: FEAT-732 — FormDesigner validation audit trail
**Spec**: `sdd/specs/formdesigner-validation-audit-trail.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4644
**Assigned-to**: unassigned

---

## Context

The validator (TASK-4648, TASK-4649) needs somewhere to write what it checks, and the
pipeline (TASK-4650) needs that evidence sealed, fingerprinted and size-bounded before it
lands in `FormSubmission.context`. This task builds those three pure, I/O-free pieces in
a new module. Implements spec §2 A/C/E and §3 Module 2. It touches no existing behaviour.

---

## Scope

- Create `services/validation_trace.py` with:
  - `ValidationTraceCollector` — `record_form`, `record_resolution`, `record`,
    `skip_remaining`, `finish` (spec §2 New Public Interfaces, plus `skip_remaining`).
  - `callable_identity(fn)` — a stable, process-independent name for a callable.
  - `schema_fingerprint(form)` — sha256 over the validation-relevant schema subset,
    walking the **validator's own** traversal.
  - `cap_trace(trace, *, max_bytes)` — deterministic, failure-preserving truncation.
- Export them from `services/__init__.py`.
- Unit-test all four.

**NOT in scope**:
- Calling the collector from `FormValidator` — TASK-4648 / TASK-4649.
- Writing the trace into `context` — TASK-4650.
- `skip_remaining`, and the `skip_reason=` keyword on `record_form`, are the two
  additions beyond the spec skeleton; neither renames anything. Every name the skeleton
  fixes is kept exactly.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validation_trace.py` | CREATE | Collector, identity, fingerprint, cap |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py` | MODIFY | Export the public names |
| `packages/parrot-formdesigner/tests/unit/services/test_validation_trace.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ..core.audit_trail import (           # created by TASK-4644
    AuditDetail, CheckId, CheckOutcome, CheckRecord, FieldTrace, SkipReason, ValidationTrace,
)
from ..core.schema import FormField, FormSchema, FormSubsection   # verified: core/schema.py:67,411,205
# INSIDE schema_fingerprint() only — a LOCAL import, because services/validators.py will
# import this module at top level (TASK-4648) and a module-level import here would cycle:
from .validators import FormValidator      # verified: services/validators.py:200
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class FormValidator:                                              # line 200
    def __init__(self) -> None: ...                               # line 217 — only sets self.logger; cheap
    def _collect_fields(self, section: FormSection) -> list[FormField]: ...   # line 1337
    #   flattens section.iter_fields() (subsections included) + GROUP `children`;
    #   DELIBERATELY EXCLUDES ARRAY `item_template` (docstring lines 1357-1368).
    #   item_template is used ONLY by traversal/extras helpers (lines 354-1424) and is
    #   NEVER validated on submit — so excluding it is exactly "the rules that ran".

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormField(BaseModel):                                       # line 67
    field_id: str; field_type: FieldType; required: bool          # lines 130-131, 135
    constraints: FieldConstraints | None                          # line 138
    options: list[FieldOption] | None                             # line 139
    depends_on: DependencyRule | None                             # line 141
    post_depends: list[PostDependency] | None                     # line 142
    relation: RelationSpec | None                                 # line 145
    meta: dict[str, Any] | None                                   # line 146
    content_type: str | None; accept_content_types: list[str] | None   # lines 147-148
    answer_envelope: Literal["voice"] | None                      # line 149
class FormSubsection(BaseModel):                                  # line 205
    subsection_id: str; fields: list[FormField]; depends_on: DependencyRule | None   # lines 228, 231-232
class FormSection(BaseModel):                                     # line 239
    section_id: str; fields: list[SectionItem]; depends_on: DependencyRule | None    # lines 261, 264-265
class FormSchema(BaseModel):                                      # line 411
    form_uid: uuid.UUID; form_id: str; version: str               # lines 465, 467
    unknown_fields: UnknownFieldsPolicy                            # line 487 — an Enum; use .value

# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
class FieldConstraints(BaseModel):                                # line 21
    pattern_message: LocalizedString | None    # line 50 — presentation text: EXCLUDE from the hash
    anchor_labels: dict[int, LocalizedString] | None   # line 68 — presentation text: EXCLUDE

# Validator meta keys that DEFINE checks (include them, and only them, from `meta`):
#   meta["cross_field_validators"] : list[Callable]   — services/validators.py:1281
#   meta["async_validator"]        : Callable         — services/validators.py:1320
#   meta["rest"]                   : REST spec dict    — services/validators.py:1226
```

### Does NOT Exist
- ~~`parrot_formdesigner.services.validation_trace`~~ — this task creates it.
- ~~`FormSchema.iter_fields_recursive()` as the fingerprint traversal~~ — it exists
  (`AnswerPlausibilityChecker.eligible_fields` uses it, `plausibility.py:95`) but walks a
  **different** field set. Never use it here (spec §7 R2).
- ~~`walk_fields()` (core/schema.py:277) as the fingerprint traversal~~ — its docstring
  calls it "the ONE canonical recursive traversal" and says it supersedes
  `_collect_fields`. **Do not believe it for this purpose**: it includes ARRAY
  `item_template`, which the validator excludes and never validates. Using it would hash
  rules that never ran.
- ~~`FormValidator.collect_fields()`~~ (public) — only the private `_collect_fields` exists.
- ~~a JSON encoder for callables~~ — `json.dumps(default=str)` on a function yields
  `<function f at 0x7f…>`, a memory address: **non-deterministic across processes**.
  Callables must go through `callable_identity()` before serialization.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/validation_trace.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/services/test_validation_trace.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator._collect_fields",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSubsection",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py#FieldConstraints"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pure in-memory: no I/O, no `await`, no logging of field values.
- Deterministic: same form → same fingerprint in any process; same trace → same capped
  payload. Sort wherever order is not semantic.
- `record()` is idempotent per `(field_id, check)`: the last write wins **and keeps the
  check's original position** (a plain `dict` assignment does this).

---

## Implementation Blueprint

### Steps (in order)
1. Write the module header, `callable_identity` and the collector — *why*: TASK-4648 is
   blocked on exactly these names.
2. Write `schema_fingerprint` — *why*: reconstructability (spec §2 C, AC6).
3. Write `cap_trace` — *why*: spec §2 E, AC8/AC9.
4. Export, test, run the Validation Commands.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/validation_trace.py` (CREATE — part 1)
```python
"""Deterministic validation trace: collector, schema fingerprint, size cap (FEAT-732).

Pure in-memory bookkeeping. ``FormValidator`` records into a collector it is
handed explicitly; ``SubmissionPipeline`` seals, caps and persists the result.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from ..core.audit_trail import (
    AuditDetail,
    CheckId,
    CheckOutcome,
    CheckRecord,
    FieldTrace,
    SkipReason,
    ValidationTrace,
)
from ..core.schema import FormField, FormSchema, FormSubsection

__all__ = ["ValidationTraceCollector", "callable_identity", "cap_trace", "schema_fingerprint"]


def callable_identity(fn: Any) -> str:
    """Return a stable, process-independent name for a callable.

    ``"callable:<module>.<qualname>"``. Lambdas and partials get a coarse but
    deterministic name — never a memory address.
    """
    module = getattr(fn, "__module__", None) or "?"
    qualname = getattr(fn, "__qualname__", None) or type(fn).__qualname__
    return f"callable:{module}.{qualname}"


class ValidationTraceCollector:
    """Accumulates deterministic validation evidence for one ``validate`` call."""

    def __init__(
        self, *, detail: AuditDetail, locale: str, clock: Callable[[], datetime] | None = None
    ) -> None:
        """Build a collector. ``detail`` must not be ``OFF`` — callers skip construction instead."""
        if detail is AuditDetail.OFF:
            raise ValueError("ValidationTraceCollector is never built for detail=off")
        self.detail = detail
        self.locale = locale
        self._started = time.monotonic()
        self._validated_at = (clock or (lambda: datetime.now(timezone.utc)))()
        self._form_checks: dict[CheckId, CheckRecord] = {}
        self._fields: dict[str, dict[str, Any]] = {}

    def _field(self, field_id: str) -> dict[str, Any]:
        """Return (creating on first use) the mutable entry for ``field_id``."""
        return self._fields.setdefault(
            field_id, {"visible": True, "required": False, "records": {}}
        )
```
**Why**: `detail=OFF` is rejected rather than silently tolerated — the pipeline's contract
is "no collector when off", and an OFF collector would make AC2 (byte-identical context)
impossible to reason about.

### `services/validation_trace.py` (CREATE — part 2, the recording API)
```python
    def record_form(
        self,
        check: CheckId,
        outcome: CheckOutcome,
        *,
        message: str | None = None,
        skip_reason: SkipReason | None = None,
    ) -> None:
        """Record a form-level check (circular dependencies, rule integrity).

        ``skip_reason`` is required when ``outcome`` is SKIP — e.g. rule integrity
        after a circular-dependency failure returned early (spec AC3).
        """
        # FILL IN: same SKIP-needs-reason rule as record(); drop `message` unless FAIL.
        self._form_checks[check] = CheckRecord(
            check=check, outcome=outcome, message=message, skip_reason=skip_reason
        )

    def record_resolution(self, field_id: str, *, visible: bool, required: bool) -> None:
        """Record what the rule resolution decided for one field, before any value check."""
        entry = self._field(field_id)
        entry["visible"], entry["required"] = visible, required
        entry["records"][CheckId.RESOLUTION_VISIBLE] = CheckRecord(
            check=CheckId.RESOLUTION_VISIBLE, outcome=CheckOutcome.PASS, bound=f"visible={visible}"
        )
        entry["records"][CheckId.RESOLUTION_REQUIRED] = CheckRecord(
            check=CheckId.RESOLUTION_REQUIRED, outcome=CheckOutcome.PASS, bound=f"required={required}"
        )

    def record(
        self,
        field_id: str,
        check: CheckId,
        outcome: CheckOutcome,
        *,
        bound: str | None = None,
        skip_reason: SkipReason | None = None,
        message: str | None = None,
    ) -> None:
        """Record one field-level check. Idempotent per (field_id, check): the last write wins."""
        # FILL IN: build the CheckRecord and store it under entry["records"][check].
        #   Raise ValueError when outcome is SKIP and skip_reason is None — spec AC3:
        #   every skip carries a reason. Drop `message` unless outcome is FAIL.

    def skip_remaining(
        self, field_id: str, checks: Iterable[tuple[CheckId, str | None]], reason: SkipReason
    ) -> None:
        """Record SKIP(``reason``) for every ``(check, bound)`` not already recorded for ``field_id``.

        Used at early returns: the checks a field declares but never reached are
        evidence ("never got there"), not silence.
        """
        # FILL IN: for each (check, bound) not already in entry["records"], call
        #   self.record(field_id, check, CheckOutcome.SKIP, bound=bound, skip_reason=reason).
        #   NEVER overwrite a check already recorded — that is the whole point.
```

### `services/validation_trace.py` (CREATE — part 3, sealing)
```python
    def finish(
        self, form: FormSchema, *, fingerprint: str, ruleset_version: str, is_valid: bool
    ) -> ValidationTrace:
        """Seal the collector into a ``ValidationTrace``, applying the ``detail`` projection.

        ``summary``: per field ``checks_ran`` (ids whose outcome is not SKIP) and
        ``failures``; ``records`` empty. ``full``: ``records`` carries every record,
        SKIPs included. ``form_checks`` is kept at both levels.
        """
        fields: list[FieldTrace] = []
        # FILL IN: build one FieldTrace per entry in self._fields, in insertion order,
        #   with required_effective/visible_effective from the entry, checks_ran = non-SKIP
        #   check ids, failures = FAIL records, records = all records only when
        #   self.detail is AuditDetail.FULL. Count checks_run (non-SKIP, fields + form)
        #   and checks_failed (FAIL, fields + form). Bounded by spec AC1/AC3.
        checks_run = 0
        checks_failed = 0
        return ValidationTrace(
            detail=self.detail,
            form_uid=form.form_uid,
            form_id=form.form_id,
            form_version=form.version,
            schema_fingerprint=fingerprint,
            ruleset_version=ruleset_version,
            locale=self.locale,
            validated_at=self._validated_at,
            duration_ms=int((time.monotonic() - self._started) * 1000),
            checks_run=checks_run,
            checks_failed=checks_failed,
            is_valid=is_valid,
            form_checks=list(self._form_checks.values()),
            fields=fields,
        )
```

### `services/validation_trace.py` (CREATE — part 4, fingerprint)
```python
_EXCLUDED_CONSTRAINT_KEYS = {"pattern_message", "anchor_labels"}  # presentation text, not rules
_CHECK_DEFINING_META_KEYS = ("cross_field_validators", "async_validator", "rest")


def _jsonable(value: Any) -> Any:
    """Pydantic model → JSON dict; anything else unchanged."""
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _validation_meta(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep only the meta keys that define a check; callables become identities."""
    # FILL IN: return None when meta is falsy or holds none of _CHECK_DEFINING_META_KEYS.
    #   cross_field_validators → [callable_identity(fn) for fn in value];
    #   async_validator → callable_identity(value); rest → _jsonable(value).
    #   Any OTHER meta key (UI hints) is ignored — it must not move the hash.


def _field_subset(field: FormField) -> dict[str, Any]:
    """The validation-relevant projection of one field."""
    # FILL IN: return a dict with field_id, field_type (.value), required,
    #   constraints (model_dump(mode="json", exclude=_EXCLUDED_CONSTRAINT_KEYS) or None),
    #   options (sorted str(opt.value), or None), depends_on, post_depends (list), relation
    #   (all via _jsonable), content_type, accept_content_types, answer_envelope,
    #   meta (_validation_meta). Labels/descriptions/placeholders are EXCLUDED.


def schema_fingerprint(form: FormSchema) -> str:
    """Return ``"sha256:<hex>"`` over the validation-relevant subset of ``form``.

    Walks the SAME field set ``FormValidator.validate`` iterates (per-section
    ``_collect_fields``, ARRAY ``item_template`` excluded), so the hash covers
    exactly the rules that ran. Section and subsection ``depends_on`` are
    included: they hide fields and so relax ``required``.
    """
    from .validators import FormValidator  # local: validators imports this module at top level

    validator = FormValidator()
    sections = [
        {
            "section_id": section.section_id,
            "depends_on": _jsonable(section.depends_on),
            "subsections": [
                {"subsection_id": item.subsection_id, "depends_on": _jsonable(item.depends_on)}
                for item in section.fields
                if isinstance(item, FormSubsection)
            ],
            "fields": [_field_subset(f) for f in validator._collect_fields(section)],
        }
        for section in form.sections
    ]
    payload = {"unknown_fields": form.unknown_fields.value, "sections": sections}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
```
**Why**: `default=str` is a backstop for enums/UUIDs only; callables are converted before
they reach it (see Does NOT Exist). Section order and field order are semantic (they are
the validation order) and are kept; option values are a set and are sorted.

### `services/validation_trace.py` (CREATE — part 5, cap)
```python
_COUNTER_SLACK = 64  # bytes reserved for truncated/omitted_* digits growing


def _size(payload: Any) -> int:
    """UTF-8 length of the compact JSON encoding."""
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def cap_trace(trace: ValidationTrace, *, max_bytes: int) -> dict[str, Any]:
    """Serialize ``trace`` to a JSON-safe dict within ``max_bytes`` of UTF-8 JSON.

    Drops field entries deterministically — fields with no failure first, then
    failing fields, each group by ``field_id`` — setting ``truncated`` and the
    ``omitted_*`` counters. Failures are dropped last: a trace that omits a
    failure is worse than useless. Never returns a payload larger than ``max_bytes``.
    Callers pass ``AuditTrailConfig.effective_max_bytes``.
    """
    payload = trace.model_dump(mode="json")
    if _size(payload) <= max_bytes:
        return payload
    # FILL IN: compute each field entry's serialized size ONCE (+1 for its comma), order the
    #   drop list as documented, subtract sizes until total + _COUNTER_SLACK <= max_bytes,
    #   accumulate omitted_fields and omitted_checks (= len(checks_ran) of dropped entries),
    #   set truncated=True, then VERIFY with _size(); drop one more while still over.
    #   Last resort (header + form_checks alone over the cap): set each form_checks
    #   "message" to None — the header alone is ~700 B, under the 1024-byte floor that
    #   AuditTrailConfig enforces. Do NOT re-serialize per removal (O(n²) on wide forms).
    return payload
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .validators import FormValidator, ValidationResult' services/__init__.py)
# BEFORE — insert above `from .validators import FormValidator, ValidationResult` (verified: services/__init__.py:32)
from .validation_trace import ValidationTraceCollector, callable_identity, cap_trace, schema_fingerprint
```
```python
# occurrences: 1 (verified: grep -c '    "ValidationResult",' services/__init__.py)
# AFTER — insert below `    "ValidationResult",` (verified: services/__init__.py:55)
    "ValidationTraceCollector",
    "callable_identity",
    "cap_trace",
    "schema_fingerprint",
```
**Why**: importing `validation_trace` from the package `__init__` *before* `validators` is
safe — `validation_trace` imports `validators` only lazily inside `schema_fingerprint`.

### FILL IN checklist
- [ ] `record` — SKIP-without-reason raises; message only on FAIL; bounded by AC3.
- [ ] `skip_remaining` — never overwrites; bounded by AC5.
- [ ] `finish` — summary/full projection and counters; bounded by AC1/AC3.
- [ ] `_validation_meta`, `_field_subset` — subset rules; bounded by AC6.
- [ ] `cap_trace` — single-pass sizing + verify; bounded by AC8/AC8b.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] `record` keeps one record per `(field_id, check)` (last write wins, original position kept).
- [ ] `skip_remaining` never overwrites an already-recorded check.
- [ ] `finish` under `summary` has empty `records` and non-SKIP `checks_ran`; under `full`
      `records` includes SKIPs; counters exclude SKIPs.
- [ ] `schema_fingerprint` is identical across two fresh forms built from the same dict,
      changes when `max_length` changes, is unchanged when only a `label` changes, and is
      unchanged when only an ARRAY `item_template` constraint changes (spec AC6).
- [ ] Two fingerprints of a form whose `meta["cross_field_validators"]` holds a function
      are equal (no memory address leaks into the hash).
- [ ] `cap_trace` on a 200-field `full` trace with `max_bytes=8192` returns ≤ 8192 bytes,
      `truncated=True`, non-zero `omitted_*`, and keeps every failing field while any
      passing field was dropped.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_validation_trace.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_validation_trace.py
import json

import pytest

from parrot_formdesigner.core.audit_trail import AuditDetail, CheckId, CheckOutcome, SkipReason
from parrot_formdesigner.services.validation_trace import (
    ValidationTraceCollector, callable_identity, cap_trace, schema_fingerprint,
)

# FILL IN: a `_form(**overrides)` helper building a FormSchema with one section holding a
#   required TEXT field (constraints max_length=120, pattern "^[A-Z]+$"), a SELECT with two
#   options, and an ARRAY whose item_template has its own max_length.

class TestCollector:
    def test_last_write_wins(self): ...
    def test_skip_requires_reason(self): ...            # pytest.raises(ValueError)
    def test_skip_remaining_never_overwrites(self): ...
    def test_summary_projection(self): ...
    def test_full_projection_keeps_skips(self): ...
    def test_off_detail_rejected(self): ...

class TestFingerprint:
    def test_deterministic(self): ...
    def test_changes_with_constraint(self): ...
    def test_label_change_does_not_move_hash(self): ...
    def test_excludes_array_item_template(self): ...
    def test_callable_meta_is_stable(self): ...         # uses a module-level def, twice

class TestCap:
    def test_under_cap_untouched(self): ...
    def test_respects_max_bytes(self): ...              # len(json.dumps(out, separators=(",", ":")).encode()) <= cap
    def test_marks_truncation(self): ...
    def test_drops_failures_last(self): ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug formdesigner-validation-audit-trail --feature-id FEAT-732`
2. **Read the spec** — §2 A/C/E, §3 Module 2, §7 R2/R5/R6.
3. **Check dependencies** — TASK-4644 must be `done`.
4. **Verify the Codebase Contract** — re-run every `grep -c`; confirm `_collect_fields` still excludes `item_template`.
5. **Update status** → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the three listed files.
9. **Close** — `scripts/sdd/close_task.sh TASK-4647 formdesigner-validation-audit-trail verified`.
10. **Completion Note** — note `skip_remaining` as the one addition to the spec skeleton.

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by seat gpt-5.6-sol (codex), attempt 1 (uid 9037fa0234324350a9fe8d00cc439a9a), duration 206s
**Date**: 2026-10-23
**Notes**: services/validation_trace.py: ValidationTraceCollector, schema_fingerprint, callable_identity, cap_trace; exported from services. Merge-tier validation green. Orchestrator diff review: no fixes needed. Closed with close_task.sh (engine exposes no durable review-evidence ref for finalize_task).

**Deviations from spec**: none
