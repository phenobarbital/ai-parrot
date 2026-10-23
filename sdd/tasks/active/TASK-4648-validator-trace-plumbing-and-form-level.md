# TASK-4648: Validator — `trace=` plumbing, form-level checks, rule resolution, sealing

**Feature**: FEAT-732 — FormDesigner validation audit trail
**Spec**: `sdd/specs/formdesigner-validation-audit-trail.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4647
**Assigned-to**: unassigned

---

## Context

`FormValidator.validate` decides which checks apply but keeps no record of the ones that
pass. This task threads an **explicit** `ValidationTraceCollector` through the validator
(spec §2 A — a keyword argument, never a `ContextVar`), records the two form-level checks
and the per-field rule resolution, and seals the trace onto a new `ValidationResult.trace`
field. Per-field value checks inside `validate_field` are TASK-4649. Implements the first
half of spec §3 Module 3.

---

## Scope

- Add `ValidationResult.trace: ValidationTrace | None = None`.
- Add `trace: ValidationTraceCollector | None = None` (keyword-only) to `validate()` and
  `validate_field()`, and forward it through `validate_field`'s recursive voice call.
- In `validate()`: record `FORM_CIRCULAR_DEPENDENCIES` and `FORM_RULE_INTEGRITY`; record
  each field's resolution before validating it; record the relaxed `required` of a hidden
  field as `FIELD_REQUIRED` SKIP `NOT_DISPLAYED`; seal the trace on **every** return.
- Add the private `_seal()` helper.
- Write unit tests.

**NOT in scope**:
- Any recording inside `validate_field`'s body (required, coerce, constraints, type,
  options, cross-field, async, remote, REST) — TASK-4649. Here `validate_field` only
  *accepts and forwards* `trace`.
- Persistence — TASK-4650.

**Deliberate deviation from the spec skeleton docstring** (record it in the Completion
Note): on the two form-level early returns (`__circular__`, `__rules__`) the trace carries
the form-level checks and **`fields=[]`**, not one EARLY_RETURN skip per field. Rule
resolution never ran on those paths, so every field's `visible_effective` /
`required_effective` would have to be invented. The trace stays fully reconstructable:
`form_checks` says where validation stopped and `schema_fingerprint` names every field
that was never examined. Spec AC5 ("a sealed trace naming the failed form-level check")
is met exactly.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | Imports, `ValidationResult.trace`, `trace=` kwarg, form-level + resolution recording, `_seal()` |
| `packages/parrot-formdesigner/tests/unit/services/test_validator_trace_form.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# added to services/validators.py:
from ..core.audit_trail import CheckId, CheckOutcome, SkipReason, ValidationTrace   # created by TASK-4644
from ..version import __version__ as _RULESET_VERSION    # verified: parrot_formdesigner/version.py:5
from .validation_trace import ValidationTraceCollector, schema_fingerprint   # created by TASK-4647
```
No cycle: `validation_trace` imports `validators` only lazily, inside `schema_fingerprint`.

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
from .unknown_fields import compute_extra_data          # line 27  ← import anchor (last import)
class ValidationResult(BaseModel):                      # line 160
    extra_data: dict[str, Any] = Field(default_factory=dict)   # line 177  ← anchor
class FormValidator:                                    # line 200
    async def validate(self, form, data, *, locale="en", auth_context=None,
                       location_vars=None, visit_context=None) -> ValidationResult:   # line 221
        visit_context: dict[str, Any] | None = None,    # line 229  ← signature anchor (unique)
        circular_errors = self._detect_circular_dependencies(form)   # line 256 ← anchor
        # lines 257-259: if circular_errors: errors["__circular__"] = ...; return ValidationResult(...)
        rule_errors = self.validate_rules(form)         # line 262 ← anchor
        # lines 263-265: if rule_errors: errors["__rules__"] = ...; return ValidationResult(...)
        resolution = await RuleEvaluator().resolve(...)  # line 287
        for field in all_fields:                         # line 296
            effective_required = resolution.required.get(field.field_id, field.required) and resolution.visible.get(
                field.field_id, True
            )                                            # lines 297-299
            field_errors = await self.validate_field(..., required=effective_required,)   # lines 300-307
        return ValidationResult(                         # line 360 ← final return
            is_valid=len(errors) == 0, ...
    async def validate_field(self, field, value, *, all_data=None, locale="en",
                             auth_context=None, required=None) -> list[str]:          # line 367
        # recursive voice-envelope call, lines 414-421, ends with `required=required,` (line 420)
    def _collect_fields(self, section) -> list[FormField]: ...   # line 1337

# services/rule_evaluator.py
class RuleResolution(BaseModel):                         # line 53
    visible: dict[str, bool]; required: dict[str, bool]  # lines 70-71
```

### Does NOT Exist
- ~~`ValidationResult.trace`~~ — this task adds it.
- ~~`FormValidator.validate(..., trace=)`~~ / ~~`validate_field(..., trace=)`~~ — added here.
- ~~`self._trace`~~ / ~~`FormValidator.last_trace`~~ — **never store the collector on the
  validator instance.** One `FormValidator` serves concurrent requests
  (`app["submission_pipeline"]` is built once per app, `api/routes.py:367`); instance
  state would cross-contaminate traces. Pass it down as an argument only.
- ~~a `ContextVar` for the active collector~~ — none exists and none is added (spec §2 A).
- ~~`FormValidator._declared_checks()`~~ — not in this task; TASK-4649 adds it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/services/test_validator_trace_form.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#ValidationResult",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator.validate",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator.validate_field",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/rule_evaluator.py#RuleResolution"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Zero behaviour change without a collector**: every `if trace is not None:` guard keeps
  the old path byte-identical, and `validate_field` still returns `list[str]` (spec AC18).
- Seal on **every** return path of `validate()` — three of them.
- The two early-return lines are identical text (lines 259 and 265, `grep -c` = 2): never
  anchor on them; anchor on the unique line *above* each.

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports — *why*: everything below uses them.
2. Add `ValidationResult.trace` — *why*: spec §2 A, "ValidationResult is the single handoff".
3. Add `trace=` to both signatures and forward it in the recursion — *why*: TASK-4649 and
   TASK-4650 both build on the kwarg existing.
4. Add `_seal()`, then instrument the form-level checks and the per-field loop — *why*:
   spec AC4/AC5.
5. Test, then run the Validation Commands.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c 'from .unknown_fields import compute_extra_data' services/validators.py)
# AFTER — insert below `from .unknown_fields import compute_extra_data` (verified: services/validators.py:27)
from ..core.audit_trail import CheckId, CheckOutcome, SkipReason, ValidationTrace
from ..version import __version__ as _RULESET_VERSION
from .validation_trace import ValidationTraceCollector, schema_fingerprint
```

### `services/validators.py` (MODIFY — `ValidationResult`)
```python
# occurrences: 1 (verified: grep -c '    extra_data: dict\[str, Any\] = Field(default_factory=dict)' services/validators.py)
# AFTER — insert below `    extra_data: dict[str, Any] = Field(default_factory=dict)` (verified: services/validators.py:177)
    trace: ValidationTrace | None = None
```
Also add to the class docstring `Attributes:` (lines 163-172):
`trace: Sealed deterministic evidence (FEAT-732), or ``None`` when no collector was passed.`

### `services/validators.py` (MODIFY — `validate` signature)
```python
# occurrences: 1 (verified: grep -c '        visit_context: dict\[str, Any\] | None = None,' services/validators.py)
# AFTER — insert below `        visit_context: dict[str, Any] | None = None,` (verified: services/validators.py:229)
        trace: ValidationTraceCollector | None = None,
```
Add to the docstring `Args:`: `trace: Optional collector (FEAT-732). When given, the result
carries a sealed ``ValidationTrace``; when ``None`` validation is unchanged.`

### `services/validators.py` (MODIFY — form-level checks)
```python
# occurrences: 1 (verified: grep -c '        circular_errors = self._detect_circular_dependencies(form)' services/validators.py)
# REPLACE the 4 lines starting at `        circular_errors = self._detect_circular_dependencies(form)` (verified: :256-259) with:
        circular_errors = self._detect_circular_dependencies(form)
        if trace is not None:
            trace.record_form(
                CheckId.FORM_CIRCULAR_DEPENDENCIES,
                CheckOutcome.FAIL if circular_errors else CheckOutcome.PASS,
                message="; ".join(circular_errors) or None,
            )
        if circular_errors:
            errors["__circular__"] = circular_errors
            if trace is not None:
                trace.record_form(
                    CheckId.FORM_RULE_INTEGRITY, CheckOutcome.SKIP, skip_reason=SkipReason.EARLY_RETURN
                )
            return self._seal(form, trace, ValidationResult(is_valid=False, errors=errors, sanitized_data=sanitized))
```
```python
# occurrences: 1 (verified: grep -c '        rule_errors = self.validate_rules(form)' services/validators.py)
# REPLACE the 4 lines starting at `        rule_errors = self.validate_rules(form)` (verified: :262-265) with:
        rule_errors = self.validate_rules(form)
        if trace is not None:
            trace.record_form(
                CheckId.FORM_RULE_INTEGRITY,
                CheckOutcome.FAIL if rule_errors else CheckOutcome.PASS,
                message="; ".join(rule_errors) or None,
            )
        if rule_errors:
            errors["__rules__"] = rule_errors
            return self._seal(form, trace, ValidationResult(is_valid=False, errors=errors, sanitized_data=sanitized))
```

### `services/validators.py` (MODIFY — per-field loop, lines 296-307)
```python
# FILL IN: disambiguate — attach to the loop by its unique 3-line head:
#     for field in all_fields:
#         effective_required = resolution.required.get(field.field_id, field.required) and resolution.visible.get(
#             field.field_id, True
#   (verified: services/validators.py:296-298; `required=effective_required,` at :306 is unique, grep -c = 1)
# 1) Directly below the `)` that closes the effective_required expression (line 299), insert:
            visible = resolution.visible.get(field.field_id, True)
            if trace is not None:
                trace.record_resolution(field.field_id, visible=visible, required=effective_required)
# 2) Add `trace=trace,` below `                required=effective_required,` (line 306).
# 3) Directly below the closing `)` of that validate_field call (line 307), insert:
            if trace is not None and not visible and resolution.required.get(field.field_id, field.required):
                # The form would have demanded it, but never showed it: the relaxation is evidence.
                trace.record(
                    field.field_id, CheckId.FIELD_REQUIRED, CheckOutcome.SKIP, skip_reason=SkipReason.NOT_DISPLAYED
                )
```
**Why**: the override runs *after* `validate_field`, so once TASK-4649 makes `validate_field`
record `FIELD_REQUIRED` SKIP `NOT_APPLICABLE` for a not-required field, the collector's
last-write-wins upgrades it to `NOT_DISPLAYED` exactly when the schema-or-rule required it
and the rule hid it. A hidden field that was optional anyway keeps `NOT_APPLICABLE` — no
relaxation happened.

### `services/validators.py` (MODIFY — final return, line 360)
```python
# occurrences: 1 (verified: 2-line context '        return ValidationResult(\n            is_valid=len(errors) == 0,' occurs once)
# REPLACE `        return ValidationResult(` (line 360) with `        return self._seal(form, trace, ValidationResult(`
# and close the extra parenthesis after the existing `)` that ends the ValidationResult(...) call (line 365).
```

### `services/validators.py` (MODIFY — `validate_field` signature + recursion)
```python
# occurrences: 1 (verified: 2-line context
#   '        auth_context: AuthContext | None = None,\n        required: bool | None = None,\n' occurs once — the
#   other `required: bool | None = None,` at :1197 belongs to _validate_rest_field and has `label: str,` above it)
# AFTER — insert below `        required: bool | None = None,` at line 375 (NOT line 1197):
        trace: ValidationTraceCollector | None = None,
```
```python
# occurrences: 1 (verified: grep -c '                required=required,' services/validators.py)
# AFTER — insert below `                required=required,` (verified: services/validators.py:420, inside the recursive call)
                trace=trace,
```
Add to the `validate_field` docstring `Args:`: `trace: Optional collector (FEAT-732),
forwarded into the voice-envelope recursion. Never changes the return value.`

### `services/validators.py` (MODIFY — `_seal` helper)
```python
# occurrences: 1 (verified: grep -c '    async def validate_field(' services/validators.py)
# BEFORE — insert above `    async def validate_field(` (verified: services/validators.py:367)
    @staticmethod
    def _seal(
        form: FormSchema, trace: ValidationTraceCollector | None, result: ValidationResult
    ) -> ValidationResult:
        """Attach the sealed trace to ``result`` (FEAT-732); a no-op without a collector."""
        if trace is None:
            return result
        result.trace = trace.finish(
            form,
            fingerprint=schema_fingerprint(form),
            ruleset_version=_RULESET_VERSION,
            is_valid=result.is_valid,
        )
        return result
```

### FILL IN checklist
- [ ] Per-field loop disambiguation — attach to the 3-line head; bounded by "one record per field per check".
- [ ] Test bodies below; bounded by spec AC4, AC5, AC18.

---

## Acceptance Criteria

- [ ] `validate(form, data)` without `trace=` returns a result with `trace is None` and
      otherwise identical to before (spec AC18).
- [ ] With a collector, `result.trace` is a `ValidationTrace` whose `schema_fingerprint`
      equals `schema_fingerprint(form)` and `ruleset_version` equals the package `__version__`.
- [ ] A clean form records both form checks as PASS.
- [ ] `__circular__` → `FORM_CIRCULAR_DEPENDENCIES` FAIL, `FORM_RULE_INTEGRITY` SKIP
      `EARLY_RETURN`, `fields == []`, `is_valid is False` (spec AC5).
- [ ] `__rules__` → `FORM_RULE_INTEGRITY` FAIL, `fields == []` (spec AC5).
- [ ] A required field hidden by a rule → `visible_effective is False`,
      `required_effective is False`, and under `full` a `FIELD_REQUIRED` SKIP `NOT_DISPLAYED`
      record (spec AC4).
- [ ] Every field `validate()` visited has a `FieldTrace` with both `RESOLUTION_*` records.
- [ ] `validate_field(field, value)` without `trace=` still returns `list[str]`.
- [ ] Existing suites below stay green.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_validator_trace_form.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/services/test_validator_visibility.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/services/test_validator_extra_data.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/services/test_rule_validation.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_validator_trace_form.py
import pytest

from parrot_formdesigner.core.audit_trail import AuditDetail, CheckId, CheckOutcome, SkipReason
from parrot_formdesigner.services.validation_trace import ValidationTraceCollector, schema_fingerprint
from parrot_formdesigner.services.validators import FormValidator
from parrot_formdesigner.version import __version__

# FILL IN: reuse the builders, copied (not imported) from existing suites —
#   circular form: tests/unit/services/test_validator_extra_data.py:60-73 (`circular_form` fixture)
#   rules-ordering form: tests/unit/services/test_rule_validation.py:340-357
#   hidden-field form: _field/_rule/_form helpers at tests/unit/services/test_validator_visibility.py:24-41


def _collector(detail: AuditDetail = AuditDetail.SUMMARY) -> ValidationTraceCollector:
    return ValidationTraceCollector(detail=detail, locale="en")


async def test_no_collector_no_trace(): ...
async def test_trace_sealed_with_fingerprint_and_version(): ...
async def test_clean_form_records_both_form_checks_pass(): ...
async def test_circular_early_return_seals_trace(): ...
async def test_rules_early_return_seals_trace(): ...
async def test_relaxed_required_is_recorded_summary(): ...   # flags only
async def test_relaxed_required_is_recorded_full(): ...      # + FIELD_REQUIRED SKIP NOT_DISPLAYED
async def test_every_visited_field_has_resolution_records(): ...
async def test_validate_field_signature_unchanged(): ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug formdesigner-validation-audit-trail --feature-id FEAT-732`
2. **Read the spec** — §2 A, §3 Module 3, §5 AC4/AC5/AC18.
3. **Check dependencies** — TASK-4647 (and through it TASK-4644) must be `done`.
4. **Verify the Codebase Contract** — re-run every `grep -c`; the line numbers shift as you edit, so locate by anchor text, not by number.
5. **Update status** → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the two listed files.
9. **Close** — `scripts/sdd/close_task.sh TASK-4648 formdesigner-validation-audit-trail verified`.
10. **Completion Note** — record the `fields=[]` deviation on form-level early returns.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: on form-level early returns the trace carries `fields=[]` (see Scope).
