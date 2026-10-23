# TASK-4649: Validator — record every per-field check inside `validate_field`

**Feature**: FEAT-732 — FormDesigner validation audit trail
**Spec**: `sdd/specs/formdesigner-validation-audit-trail.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4648
**Assigned-to**: unassigned

---

## Context

This is the task that turns "it passed validation" into "it passed these 14 checks".
TASK-4648 made `validate_field` *accept and forward* a `trace=` collector; this task makes
it *record* each check it evaluates — required, relation shape, coercion, the eight
`FieldConstraints` bounds, type, option set, cross-field, async, remote response and REST —
each as PASS, FAIL or SKIP-with-reason, under the stable `CheckId` vocabulary. Implements
the second half of spec §3 Module 3 and spec §2 B.

---

## Scope

- Add `FormValidator._declared_checks(field) -> list[tuple[CheckId, str | None]]`: the
  checks the validator *would* evaluate for this field's type and declaration, in
  validation order, each with its bound string.
- Add a local `_rec(...)` recorder inside `validate_field`, and record every check.
- At each of `validate_field`'s early returns, call `trace.skip_remaining(...)` so the
  checks the field declares but never reached are recorded as SKIP with a reason.
- Write unit tests.

**NOT in scope**:
- `validate()`'s form-level checks, rule-resolution records and the `NOT_DISPLAYED`
  override — already done by TASK-4648.
- Changing **any** validation outcome. The original `if` blocks stay byte-identical; this
  task only adds `m = len(errors)` markers before them and `_rec(...)` calls after them.

### Recording rules (the decisions this task implements — do not re-decide them)
| Situation | Record |
|---|---|
| A check the field does not declare (e.g. no `max_length`) | **nothing** — the fingerprint proves it absent |
| Field not required (after rule resolution) | `FIELD_REQUIRED` SKIP `NOT_APPLICABLE` (TASK-4648 upgrades it to `NOT_DISPLAYED` when a rule hid a would-be-required field) |
| Required and empty | `FIELD_REQUIRED` FAIL, then `skip_remaining(..., EARLY_RETURN)` |
| Not required and empty | `skip_remaining(..., EMPTY_OPTIONAL)` |
| Declared bound, value cannot carry it (`min_length` on a number, `min_items` on a scalar…) | SKIP `WRONG_VALUE_SHAPE` |
| `allowed_mime_types` on a FileEnvelope value | SKIP `NOT_APPLICABLE` (the envelope carries its own `content_type`) |
| `allowed_mime_types` on a legacy string value with no `{field_id}__mime` key | SKIP `NO_MIME_SIDECHANNEL` — today the check silently does nothing here; the trace now says so |
| Cross-field validators declared but `all_data` empty | SKIP `NOT_APPLICABLE` |
| Relation-shape or coercion failure | that check FAIL, then `skip_remaining(..., EARLY_RETURN)` |
| Voice envelope malformed | `FIELD_VOICE_ENVELOPE` FAIL, then `skip_remaining(..., EARLY_RETURN)` |
| Voice envelope valid | `FIELD_VOICE_ENVELOPE` PASS, then the recursion records the scalar's checks |
| REMOTE_RESPONSE / REST field | only `FIELD_REMOTE_RESPONSE` / `FIELD_REST`, PASS or FAIL from the returned list |

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | `_declared_checks()`, `_rec`, per-check recording, early-return skips |
| `packages/parrot-formdesigner/tests/unit/services/test_validator_trace_fields.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# TASK-4648 already added, at the top of services/validators.py:
from ..core.audit_trail import CheckId, CheckOutcome, SkipReason, ValidationTrace
from .validation_trace import ValidationTraceCollector, schema_fingerprint
# THIS task widens the second line to:
from .validation_trace import ValidationTraceCollector, callable_identity, schema_fingerprint   # callable_identity: TASK-4647
# Already imported in validators.py: FieldType (line 23), file_type_allowed (line 19), Callable (line 14)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
# Line numbers are PRE-TASK-4648 — that task inserts lines above validate_field.
# Locate every edit by its anchor text (all verified unique, grep -c = 1).
    async def validate_field(self, field, value, *, all_data=None, locale="en",
                             auth_context=None, required=None, trace=None) -> list[str]:   # line 367 (+trace from TASK-4648)
        label = _resolve_localized(field.label, locale) or field.field_id        # line 396
        return await self._validate_remote_response(field, value, label, auth_context=auth_context)   # line 400
        return self._validate_rest_field(field, value, label, is_required)        # line 404
        #   lines 408-421 — voice envelope: `return [f"{label} has an invalid voice answer"]` (413),
        #                   then `return await self.validate_field(` (414) — the recursion
        if is_required and is_empty:                                              # line 432 (return errors at 434)
        if is_empty:\n            return errors                                   # lines 437-438
        if field.relation is not None and field.relation.mode == "reference":     # line 448
                return relation_errors                                            # line 451
        # lines 453-458 — coercion try/except; `errors.append(str(exc))\n            return errors`
        text_value = self._constrainable_text(coerced, field)                     # line 468
        if field.constraints:  c = field.constraints                              # lines 469-470
            if c.min_length is not None and text_value is not None:               # line 471
            if c.max_length is not None and text_value is not None:               # line 474
            if c.min_value is not None and isinstance(coerced, (int, float)):     # line 477
            if c.max_value is not None and isinstance(coerced, (int, float)):     # line 480
            if c.pattern is not None and text_value is not None:                  # line 483
            if c.min_items is not None and isinstance(coerced, list):             # line 487
            if c.max_items is not None and isinstance(coerced, list):             # line 490
            if (c.allowed_mime_types and field.field_type in (FieldType.FILE, FieldType.IMAGE)
                    and not _is_file_envelope_shaped(coerced)):                   # lines 493-497
                mime = all_data.get(f"{field.field_id}__mime") if all_data else None   # line 501
                if mime and not file_type_allowed(c.allowed_mime_types, mime, None):   # line 508
        type_errors = self._validate_by_type(coerced, field, label)               # line 512
        # SELECT/MULTI_SELECT option validation                                   # line 515
        # Cross-field validation via meta                                         # line 527
        # Async remote validation via meta                                        # line 532
        return errors                                                             # line 537 (then `def _validate_relation_shape` at 539)

# packages/parrot-formdesigner/src/parrot_formdesigner/core/relations.py
class RelationSpec(BaseModel):                           # line 50 — .mode ("reference"|"embed"), .cardinality ("one"|"many")

# packages/parrot-formdesigner/src/parrot_formdesigner/services/validation_trace.py  (TASK-4647)
class ValidationTraceCollector:
    def record(self, field_id, check, outcome, *, bound=None, skip_reason=None, message=None) -> None: ...
    def skip_remaining(self, field_id, checks: Iterable[tuple[CheckId, str | None]], reason: SkipReason) -> None: ...
def callable_identity(fn: Any) -> str: ...
```

### Does NOT Exist
- ~~`FormValidator._declared_checks()`~~ — this task adds it.
- ~~a per-check return value from `_validate_by_type` / `_run_cross_field_validation` /
  `_run_async_validator`~~ — they return `list[str]` only; PASS/FAIL is inferred from
  whether `errors` grew since the marker. Do **not** change their signatures.
- ~~`CheckRecord` for undeclared checks~~ — never recorded (see the rules table).
- ~~`trace.record_many()`~~ / ~~`trace.mark()`~~ — not collector methods; use `record` and
  `skip_remaining` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/services/test_validator_trace_fields.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator.validate_field",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator._validate_by_type",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator._run_cross_field_validation",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator._run_async_validator",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/relations.py#RelationSpec"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Behaviour-preserving**: no original condition, message or return value changes. A
  diff that edits an existing `errors.append(...)` line is wrong.
- Bound strings are evidence an auditor reads: `"max_length=120"`, `"pattern=^[A-Z]+$"`,
  `"allowed_mime_types=image/*,application/pdf"`, `"options=3"`, `"type=email"`,
  `"cardinality=one"`, and for callables the `callable_identity` values joined with `,`.
  Never put a submitted *value* into a bound or a skip — only the rule.
- `message` is the localised error text on FAIL only (spec §7 R7: it never feeds `CheckId`).

---

## Implementation Blueprint

### Steps (in order)
1. Widen the `validation_trace` import — *why*: `_declared_checks` needs `callable_identity`.
2. Add `_declared_checks()` — *why*: `skip_remaining` at every early return needs the full
   list of what the field *would* have checked.
3. Add `_rec` right after `label = ...` — *why*: one helper keeps each insertion to one line.
4. Instrument top-to-bottom: remote/REST → voice → required → empty → relation → coerce →
   constraints → type → options → cross-field → async — *why*: matching the code's own
   order makes `_declared_checks` order and record order agree.
5. Test, then run the Validation Commands.

### `services/validators.py` (MODIFY — import)
```python
# occurrences: 1 (verified after TASK-4648: grep -c 'from .validation_trace import ValidationTraceCollector, schema_fingerprint' services/validators.py)
# REPLACE that line with:
from .validation_trace import ValidationTraceCollector, callable_identity, schema_fingerprint
```

### `services/validators.py` (MODIFY — `_declared_checks`)
```python
# occurrences: 1 (verified: grep -c '    def _validate_relation_shape(self, field: FormField, value: Any, label: str) -> list\[str\]:' services/validators.py)
# BEFORE — insert above `    def _validate_relation_shape(...)` (verified: services/validators.py:539)
    _BOUNDED_CONSTRAINTS: tuple[tuple[str, CheckId], ...] = (
        ("min_length", CheckId.CONSTRAINT_MIN_LENGTH),
        ("max_length", CheckId.CONSTRAINT_MAX_LENGTH),
        ("min_value", CheckId.CONSTRAINT_MIN_VALUE),
        ("max_value", CheckId.CONSTRAINT_MAX_VALUE),
        ("pattern", CheckId.CONSTRAINT_PATTERN),
        ("min_items", CheckId.CONSTRAINT_MIN_ITEMS),
        ("max_items", CheckId.CONSTRAINT_MAX_ITEMS),
    )

    def _declared_checks(self, field: FormField) -> list[tuple[CheckId, str | None]]:
        """Return the (check, bound) pairs ``validate_field`` would evaluate for ``field``.

        In validation order. Only checks the field's type and declaration make
        reachable — an undeclared bound is not listed (FEAT-732 recording rules).
        """
        if field.field_type == FieldType.REMOTE_RESPONSE:
            return [(CheckId.FIELD_REMOTE_RESPONSE, None)]
        if field.field_type == FieldType.REST:
            return [(CheckId.FIELD_REST, None)]
        checks: list[tuple[CheckId, str | None]] = [(CheckId.FIELD_REQUIRED, None)]
        # FILL IN, in this order, each only when declared/reachable:
        #   FIELD_RELATION_SHAPE  "cardinality=<one|many>"  — relation and relation.mode == "reference"
        #   FIELD_COERCE          "type=<field_type.value>" — always
        #   each _BOUNDED_CONSTRAINTS entry whose value is not None — "<attr>=<value>"
        #   CONSTRAINT_ALLOWED_MIME_TYPES "allowed_mime_types=<a,b>" — non-empty and type in (FILE, IMAGE)
        #   FIELD_TYPE            "type=<field_type.value>" — always
        #   FIELD_OPTION_SET      "options=<n>"             — options and type in (SELECT, MULTI_SELECT)
        #   FIELD_CROSS_FIELD     ",".join(callable_identity(fn) ...) — meta.get("cross_field_validators") non-empty
        #   FIELD_ASYNC_VALIDATOR callable_identity(meta["async_validator"]) — "async_validator" in meta
        return checks
```

### `services/validators.py` (MODIFY — the `_rec` recorder)
```python
# occurrences: 1 (verified: grep -c '        label = _resolve_localized(field.label, locale) or field.field_id' services/validators.py)
# AFTER — insert below `        label = _resolve_localized(field.label, locale) or field.field_id` (verified: services/validators.py:396)
        fid = field.field_id

        def _rec(
            check: CheckId,
            mark: int,
            *,
            declared: bool = True,
            applies: bool = True,
            bound: str | None = None,
            skip_reason: SkipReason = SkipReason.WRONG_VALUE_SHAPE,
        ) -> None:
            """FEAT-732: record one check; PASS/FAIL inferred from whether ``errors`` grew since ``mark``."""
            if trace is None or not declared:
                return
            if not applies:
                trace.record(fid, check, CheckOutcome.SKIP, bound=bound, skip_reason=skip_reason)
                return
            new = errors[mark:]
            trace.record(
                fid, check, CheckOutcome.FAIL if new else CheckOutcome.PASS, bound=bound,
                message=new[0] if new else None,
            )

        def _skip_rest(reason: SkipReason) -> None:
            """FEAT-732: everything this field declares but never reached."""
            if trace is not None:
                trace.skip_remaining(fid, self._declared_checks(field), reason)
```
**Why**: `errors` is declared on the line *above* `label`, so the closure sees the live list.
`_rec` is a no-op without a collector, so the untraced path pays one attribute check.

### `services/validators.py` (MODIFY — early returns)
```python
# REMOTE_RESPONSE — REPLACE (occurrences 1, line 400)
            return await self._validate_remote_response(field, value, label, auth_context=auth_context)
# WITH
            remote_errors = await self._validate_remote_response(field, value, label, auth_context=auth_context)
            if trace is not None:
                trace.record(fid, CheckId.FIELD_REMOTE_RESPONSE,
                             CheckOutcome.FAIL if remote_errors else CheckOutcome.PASS,
                             message=remote_errors[0] if remote_errors else None)
            return remote_errors

# REST — REPLACE (occurrences 1, line 404) `return self._validate_rest_field(field, value, label, is_required)`
# FILL IN: same shape as REMOTE_RESPONSE, with CheckId.FIELD_REST.

# Voice envelope — BEFORE `                    return [f"{label} has an invalid voice answer"]` (line 413), insert:
                    if trace is not None:
                        trace.record(fid, CheckId.FIELD_VOICE_ENVELOPE, CheckOutcome.FAIL,
                                     message=f"{label} has an invalid voice answer")
                    _skip_rest(SkipReason.EARLY_RETURN)
# and BEFORE `            return await self.validate_field(` (line 414), insert:
            if trace is not None:
                trace.record(fid, CheckId.FIELD_VOICE_ENVELOPE, CheckOutcome.PASS)
```
```python
# Required — REPLACE the 3 lines starting `        if is_required and is_empty:` (lines 432-434) with:
        if trace is not None:
            if is_required:
                trace.record(fid, CheckId.FIELD_REQUIRED, CheckOutcome.FAIL if is_empty else CheckOutcome.PASS,
                             bound="required=True", message=f"{label} is required" if is_empty else None)
            else:
                trace.record(fid, CheckId.FIELD_REQUIRED, CheckOutcome.SKIP, skip_reason=SkipReason.NOT_APPLICABLE)
        if is_required and is_empty:
            errors.append(f"{label} is required")
            _skip_rest(SkipReason.EARLY_RETURN)
            return errors

# Empty optional — REPLACE `        if is_empty:\n            return errors` (lines 437-438) with:
        if is_empty:
            _skip_rest(SkipReason.EMPTY_OPTIONAL)
            return errors
```
```python
# Relation shape — the block at lines 448-451. FILL IN:
#   record FIELD_RELATION_SHAPE FAIL (+ _skip_rest(EARLY_RETURN)) just before
#   `                return relation_errors`, and PASS right after the `if relation_errors:` block.
#   Bound "cardinality=<field.relation.cardinality>".
# Coercion — the try/except at lines 454-458. FILL IN:
#   in the except, before `return errors`: _rec(CheckId.FIELD_COERCE, mark, bound=...) then _skip_rest(EARLY_RETURN);
#   after the try/except: _rec(CheckId.FIELD_COERCE, mark, bound=...). Take `mark = len(errors)` before `try:`.
```
```python
# Constraints — the pattern, shown for min_length. Apply it to all eight blocks (lines 471-509).
# BEFORE `            if c.min_length is not None and text_value is not None:` (line 471):
            m = len(errors)
# AFTER that block's last line (`errors.append(f"{label} must be at least {c.min_length} characters")`):
            _rec(CheckId.CONSTRAINT_MIN_LENGTH, m, declared=c.min_length is not None,
                 applies=text_value is not None, bound=f"min_length={c.min_length}")
# FILL IN: the other seven, with `applies=` mirroring each block's own guard:
#   max_length / pattern → text_value is not None
#   min_value / max_value → isinstance(coerced, (int, float))
#   min_items / max_items → isinstance(coerced, list)
#   allowed_mime_types → declared = bool(c.allowed_mime_types) and field.field_type in (FILE, IMAGE);
#       envelope-shaped → SKIP NOT_APPLICABLE; no `mime` → SKIP NO_MIME_SIDECHANNEL; else PASS/FAIL.
#       `mime` is computed INSIDE that block (line 501): record from inside it.
```
```python
# Type — BEFORE `        type_errors = self._validate_by_type(coerced, field, label)` (line 512): `m = len(errors)`;
#   AFTER `        errors.extend(type_errors)` (line 513): _rec(CheckId.FIELD_TYPE, m, bound=f"type={field.field_type.value}")
# Options — BEFORE `        # SELECT/MULTI_SELECT option validation` (line 515): `m = len(errors)`;
#   AFTER the if/elif block (ends line 525): _rec(CheckId.FIELD_OPTION_SET, m,
#       declared=bool(field.options) and field.field_type in (FieldType.SELECT, FieldType.MULTI_SELECT),
#       bound=f"options={len(field.options or [])}")
# Cross-field — BEFORE `        # Cross-field validation via meta` (line 527): `m = len(errors)`; AFTER its block:
#   FILL IN: declared = bool(field.meta and field.meta.get("cross_field_validators")),
#            applies = bool(all_data), skip_reason=SkipReason.NOT_APPLICABLE, bound = identities joined by ","
# Async — BEFORE `        # Async remote validation via meta` (line 532): `m = len(errors)`; AFTER its block:
#   FILL IN: declared = bool(field.meta and "async_validator" in field.meta), bound = callable_identity(...)
```
**Why** this marker pattern rather than restructuring each `if`: every original guard and
message stays byte-identical, so the only behavioural surface this task adds is the trace.

### FILL IN checklist
- [ ] `_declared_checks` — the eight conditional entries; bounded by the rules table.
- [ ] REST early return; relation shape; coercion — bounded by "FAIL then `_skip_rest(EARLY_RETURN)`".
- [ ] The seven remaining constraint recorders — `applies=` mirrors each block's own guard.
- [ ] `allowed_mime_types` three-way skip — bounded by the rules table.
- [ ] Cross-field / async recorders.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] Every existing validator suite passes **unchanged** (no outcome changes).
- [ ] A required pattern-constrained TEXT answered validly records, in order,
      `FIELD_REQUIRED`, `FIELD_COERCE`, `CONSTRAINT_PATTERN` (+ any other declared bound),
      `FIELD_TYPE`, all PASS; under `full` each carries its bound.
- [ ] A violated `max_length` records `CONSTRAINT_MAX_LENGTH` FAIL with the error as `message`.
- [ ] An unanswered optional field records `FIELD_REQUIRED` SKIP `NOT_APPLICABLE` and every
      other declared check SKIP `EMPTY_OPTIONAL` (spec "test_empty_optional_skips_downstream").
- [ ] A required empty field records `FIELD_REQUIRED` FAIL and the rest SKIP `EARLY_RETURN`.
- [ ] A coercion failure records `FIELD_COERCE` FAIL and the rest SKIP `EARLY_RETURN`.
- [ ] REMOTE_RESPONSE and REST fields record exactly one check each.
- [ ] A spoken answer records `FIELD_VOICE_ENVELOPE` PASS **once** plus the scalar's checks
      against the same `field_id`.
- [ ] `allowed_mime_types` on a FILE string value with no `__mime` key records SKIP
      `NO_MIME_SIDECHANNEL`.
- [ ] An undeclared bound never appears in `records` or `checks_ran`.
- [ ] No submitted value appears in any `bound` or `skip_reason`.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_validator_trace_fields.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/services/test_validator_visibility.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/services/test_validator_relation.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/services/test_validators_rest.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_validator_envelope_any_type.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_validator_trace_fields.py
import pytest

from parrot_formdesigner.core.audit_trail import AuditDetail, CheckId, CheckOutcome, SkipReason
from parrot_formdesigner.services.validation_trace import ValidationTraceCollector
from parrot_formdesigner.services.validators import FormValidator


def _full() -> ValidationTraceCollector:
    return ValidationTraceCollector(detail=AuditDetail.FULL, locale="en")


def _records(trace, field_id):
    """{CheckId: CheckRecord} for one field of a sealed trace."""
    entry = next(f for f in trace.fields if f.field_id == field_id)
    return {r.check: r for r in entry.records}

# FILL IN: build forms inline (FormField/FormSection/FormSchema — see
#   tests/unit/services/test_validator_visibility.py:24-41 for the minimal helpers). For the
#   voice case reuse the envelope shape from tests/formdesigner/test_validator_envelope_any_type.py.

async def test_full_records_bound_per_check(): ...
async def test_failed_bound_records_message(): ...
async def test_empty_optional_skips_downstream(): ...
async def test_required_empty_skips_rest_as_early_return(): ...
async def test_coercion_failure_skips_rest(): ...
async def test_remote_response_records_one_check(): ...   # monkeypatch _validate_remote_response
async def test_rest_records_one_check(): ...
async def test_voice_envelope_recursion_keeps_trace(): ...
async def test_mime_without_sidechannel_is_explicit(): ...
async def test_undeclared_bound_not_recorded(): ...
async def test_no_value_leaks_into_bounds(): ...           # submit a distinctive value, assert it is absent
```

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug formdesigner-validation-audit-trail --feature-id FEAT-732`
2. **Read the spec** — §2 B, §3 Module 3, §7 R7.
3. **Check dependencies** — TASK-4648 must be `done` (it adds the `trace=` kwarg this task reads).
4. **Verify the Codebase Contract** — re-run every `grep -c`; locate edits by anchor text.
5. **Update status** → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`. If any
   pre-existing validator test changes outcome, you edited a guard — revert and re-apply the marker pattern.
8. **Commit the code** — stage only the two listed files.
9. **Close** — `scripts/sdd/close_task.sh TASK-4649 formdesigner-validation-audit-trail verified`.
10. **Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by seat gpt-5.6-terra (codex), attempt 1 (uid 73742696609545a79f44429e877e5cdb), duration 301s
**Date**: 2026-10-23
**Notes**: Per-field check recording in FormValidator.validate_field (all CheckIds, skip reasons, _declared_checks). Merge-tier validation green. Closed with close_task.sh (engine exposes no durable review-evidence ref for finalize_task).

**Deviations from spec**: none
