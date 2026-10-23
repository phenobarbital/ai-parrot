# TASK-4644: Audit-trail core models + `FormSchema.audit_trail`

**Feature**: FEAT-732 — FormDesigner validation audit trail
**Spec**: `sdd/specs/formdesigner-validation-audit-trail.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-732 closes two audit-trail gaps in `parrot-formdesigner`; the first is that the
deterministic validator leaves no record of which checks ran. This task declares the
**data vocabulary** every other task builds on: the detail levels, the stable check
identifiers, the per-check and per-field records, the per-form config block, and the
sealed trace model. It implements spec §3 Module 1 and the models fixed verbatim in
spec §2 "Data Models". It is a root of the task graph — nothing else in FEAT-732 is
needed first.

---

## Scope

- Create `core/audit_trail.py` with `AuditDetail`, `CheckId`, `CheckOutcome`,
  `SkipReason`, `CheckRecord`, `FieldTrace`, `DEFAULT_MAX_BYTES`, `AuditTrailConfig`
  (with the `effective_max_bytes` property) and `ValidationTrace`.
- Add `FormSchema.audit_trail: AuditTrailConfig | None = None`, directly below
  `llm_validation`.
- Export every new public name from `core/__init__.py`.
- Write unit tests for defaults, the per-detail cap resolution, the frozen `CheckId`
  values, and the independence from `llm_validation`.

**NOT in scope**:
- The collector, fingerprint and cap logic (TASK-4647).
- Any change to `FormValidator` (TASK-4648, TASK-4649).
- Loading `audit_trail` from YAML-defined forms: `extractors/yaml.py:199` builds
  `llm_validation` explicitly and will **not** pick up the new block. JSON/dict forms
  get it for free through `FormSchema.model_validate`. Leave the YAML extractor alone
  — it is a follow-up, recorded in the Completion Note, not this task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/audit_trail.py` | CREATE | All audit-trail models and enums |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | Import `AuditTrailConfig`; add `FormSchema.audit_trail` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | Export the new names |
| `packages/parrot-formdesigner/tests/unit/test_audit_trail_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field            # already used throughout core/
from .types import FieldType                     # verified: core/types.py:16 (not needed by audit_trail.py)
from .llm_validation import LLMValidationConfig  # verified: core/schema.py:26 — the import to sit beside
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
from .llm_validation import LLMValidationConfig        # line 26
class FormSchema(BaseModel):                           # line 411
    version: str = "1.0"                               # line 467
    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP   # line 487
    llm_validation: LLMValidationConfig | None = None  # line 491  ← anchor

# packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py
from .llm_validation import (                          # line 60  ← anchor (block ends at line 66)
    LLMValidationConfig, PlausibilityReport, PlausibilityVerdict,
    llm_validation_enabled, implausible_fields,
)
__all__ = [                                            # line 77
    "LLMValidationConfig",                             # line 95  ← anchor for the __all__ insert
]                                                      # line 153
```

### Does NOT Exist
- ~~`parrot_formdesigner.core.audit_trail`~~ — this task creates it.
- ~~`FormSchema.audit_trail`~~ — this task adds it.
- ~~`LLMValidationConfig.audit_trail`~~ / ~~`LLMValidationConfig.detail`~~ — the audit
  config is deliberately **not** a field of `LLMValidationConfig` (spec §2 D): turning
  the LLM check off must never turn deterministic auditing off.
- ~~`AuditTrailConfig.enabled`~~ — there is no boolean switch; `detail: "off"` is the off
  switch.
- ~~`CheckId.from_function(...)`~~ / ~~`CheckId.from_message(...)`~~ — check identity is
  never derived from a helper name or an error string (spec §2 B).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/audit_trail.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_audit_trail_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `str`-valued `Enum`s (`class X(str, Enum)`) so the JSONB round trip is readable and
  `model_dump(mode="json")` emits plain strings.
- `CheckId` values are a **published contract** — they land in submission rows. Use the
  exact values below; never rename one later.
- `audit_trail.py` must not import `schema.py` (schema imports audit_trail — a cycle).

---

## Implementation Blueprint

### Steps (in order)
1. Create `core/audit_trail.py` from the block below — *why*: every later FEAT-732 task
   imports these names, so they must exist first and exactly as the spec fixed them.
2. Import `AuditTrailConfig` in `core/schema.py` and add the field — *why*: the pipeline
   (TASK-4650) reads `form.audit_trail` to decide the detail level.
3. Export the names from `core/__init__.py` — *why*: matches how `llm_validation` names
   are exported today.
4. Write the tests and run the Validation Commands.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/audit_trail.py` (CREATE)
```python
"""Deterministic validation audit-trail models (FEAT-732).

Declares the per-form ``FormSchema.audit_trail`` block, the stable check
vocabulary, and the sealed ``ValidationTrace`` persisted into
``FormSubmission.context["validation"]``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AuditDetail(str, Enum):
    """How much deterministic validation evidence to retain."""

    OFF = "off"
    SUMMARY = "summary"
    FULL = "full"


class CheckId(str, Enum):
    """Stable identifier for one deterministic validation check.

    Values are a published contract: they are persisted into submission rows
    and read back by auditors, so they are NEVER derived from a helper name or
    a localised error message, and an existing value is never renamed.
    """

    FORM_CIRCULAR_DEPENDENCIES = "form.circular_dependencies"
    FORM_RULE_INTEGRITY = "form.rule_integrity"
    RESOLUTION_VISIBLE = "resolution.visible"
    RESOLUTION_REQUIRED = "resolution.required"
    FIELD_VOICE_ENVELOPE = "field.voice_envelope"
    FIELD_REQUIRED = "field.required"
    FIELD_RELATION_SHAPE = "field.relation_shape"
    FIELD_COERCE = "field.coerce"
    FIELD_TYPE = "field.type"
    FIELD_OPTION_SET = "field.option_set"
    FIELD_CROSS_FIELD = "field.cross_field"
    FIELD_ASYNC_VALIDATOR = "field.async_validator"
    FIELD_REMOTE_RESPONSE = "field.remote_response"
    FIELD_REST = "field.rest"
    CONSTRAINT_MIN_LENGTH = "constraint.min_length"
    CONSTRAINT_MAX_LENGTH = "constraint.max_length"
    CONSTRAINT_MIN_VALUE = "constraint.min_value"
    CONSTRAINT_MAX_VALUE = "constraint.max_value"
    CONSTRAINT_PATTERN = "constraint.pattern"
    CONSTRAINT_MIN_ITEMS = "constraint.min_items"
    CONSTRAINT_MAX_ITEMS = "constraint.max_items"
    CONSTRAINT_ALLOWED_MIME_TYPES = "constraint.allowed_mime_types"


class CheckOutcome(str, Enum):
    """Result of one recorded check."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class SkipReason(str, Enum):
    """Why a declared check did not run. A skip is evidence, not an absence of evidence.

    Undeclared checks are never recorded at all — their absence is provable
    from ``ValidationTrace.schema_fingerprint``.
    """

    NOT_APPLICABLE = "not_applicable"  # declared, but does not apply to this field (e.g. not required)
    EMPTY_OPTIONAL = "empty_optional"  # optional field arrived empty — validation short-circuits
    EARLY_RETURN = "early_return"  # an earlier check returned before this one
    NOT_DISPLAYED = "not_displayed"  # rule resolution hid the field, so required was relaxed
    NO_MIME_SIDECHANNEL = "no_mime_sidechannel"  # allowed_mime_types with no resolvable MIME
    WRONG_VALUE_SHAPE = "wrong_value_shape"  # bound declared but the coerced value cannot carry it


class CheckRecord(BaseModel):
    """One check, as retained under ``full`` detail (and every failure, at any detail)."""

    check: CheckId
    outcome: CheckOutcome
    bound: str | None = None
    skip_reason: SkipReason | None = None
    message: str | None = None


class FieldTrace(BaseModel):
    """Per-field evidence."""

    field_id: str
    required_effective: bool
    visible_effective: bool
    checks_ran: list[CheckId] = Field(default_factory=list)
    records: list[CheckRecord] = Field(default_factory=list)
    failures: list[CheckRecord] = Field(default_factory=list)
```
**Why this shape**: the enum values and model fields are fixed verbatim by spec §2 Data
Models — do not rename, reorder or add members. The one deliberate refinement is the
`SkipReason.NOT_APPLICABLE` comment: it now means "declared but does not apply", because
TASK-4649 never records undeclared checks (the fingerprint already proves them absent),
which keeps the trace from carrying eight empty skips per field.

### `core/audit_trail.py` (CREATE, continued — append after `FieldTrace`)
```python
# Per-detail cap defaults (spec §2 E, §7 R6). `full` gets four times the room
# because it is the opt-in level that exists for disputes.
DEFAULT_MAX_BYTES: dict[AuditDetail, int] = {
    AuditDetail.OFF: 0,
    AuditDetail.SUMMARY: 65_536,
    AuditDetail.FULL: 262_144,
}


class AuditTrailConfig(BaseModel):
    """Per-form deterministic-audit settings (``FormSchema.audit_trail``)."""

    detail: AuditDetail = AuditDetail.SUMMARY
    max_bytes: int | None = Field(default=None, ge=1024, le=1_048_576)
    """Hard cap on the serialized trace. ``None`` resolves per `detail` via
    ``DEFAULT_MAX_BYTES``; an explicit value always wins, in either direction."""

    @property
    def effective_max_bytes(self) -> int:
        """Return `max_bytes`, or the `DEFAULT_MAX_BYTES` entry for `detail`."""
        return self.max_bytes if self.max_bytes is not None else DEFAULT_MAX_BYTES[self.detail]


class ValidationTrace(BaseModel):
    """Deterministic validation evidence for one submission."""

    trace_schema: int = 1
    detail: AuditDetail
    form_uid: uuid.UUID
    form_id: str
    form_version: str
    schema_fingerprint: str
    ruleset_version: str
    locale: str
    validated_at: datetime
    duration_ms: int
    checks_run: int
    checks_failed: int
    is_valid: bool
    form_checks: list[CheckRecord] = Field(default_factory=list)
    fields: list[FieldTrace] = Field(default_factory=list)
    truncated: bool = False
    omitted_fields: int = 0
    omitted_checks: int = 0
```
**Why**: `effective_max_bytes` is the only accessor callers use (spec AC8/AC8b);
`max_bytes` stays `None`-able so "unset" is distinguishable from "set to the default".

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .llm_validation import LLMValidationConfig' core/schema.py)
# AFTER — insert below `from .llm_validation import LLMValidationConfig` (verified: core/schema.py:26)
from .audit_trail import AuditTrailConfig
```
```python
# occurrences: 1 (verified: grep -c '    llm_validation: LLMValidationConfig | None = None' core/schema.py)
# AFTER — insert below `    llm_validation: LLMValidationConfig | None = None` (verified: core/schema.py:491)
    # FEAT-732 — deterministic audit trail. SEPARATE from llm_validation on
    # purpose: turning the LLM check off must never turn auditing off.
    audit_trail: AuditTrailConfig | None = None
```
**Why**: placing it beside `llm_validation` keeps the two related-but-independent blocks
together for readers. Also add one line to the `FormSchema` docstring `Attributes:`
section (line ~441, next to `llm_validation:`): `audit_trail: Optional deterministic
validation audit-trail block (FEAT-732); ``None`` means the ``summary`` default.`

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .llm_validation import (' core/__init__.py)
# BEFORE — insert above `from .llm_validation import (` (verified: core/__init__.py:60)
from .audit_trail import (
    DEFAULT_MAX_BYTES,
    AuditDetail,
    AuditTrailConfig,
    CheckId,
    CheckOutcome,
    CheckRecord,
    FieldTrace,
    SkipReason,
    ValidationTrace,
)
```
```python
# occurrences: 1 (verified: grep -c '    "LLMValidationConfig",' core/__init__.py)
# BEFORE — insert above `    "LLMValidationConfig",` (verified: core/__init__.py:95)
    "AuditDetail",
    "AuditTrailConfig",
    "CheckId",
    "CheckOutcome",
    "CheckRecord",
    "DEFAULT_MAX_BYTES",
    "FieldTrace",
    "SkipReason",
    "ValidationTrace",
```

### FILL IN checklist
- [ ] `test_audit_trail_models.py` — the four test bodies below; bounded by spec AC1, AC8b.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.core import AuditTrailConfig, CheckId, ValidationTrace` works.
- [ ] `AuditTrailConfig().detail is AuditDetail.SUMMARY` and `FormSchema(...).audit_trail is None`.
- [ ] `effective_max_bytes` is 65 536 under `summary`, 262 144 under `full`, and an explicit
      `max_bytes` overrides both, up or down (spec AC8b).
- [ ] Every `CheckId` value equals the frozen literal list in the test.
- [ ] A form with `llm_validation.enabled=False` and no `audit_trail` still resolves to a
      `summary` config (spec §2 D).
- [ ] `ruff check` is clean on the four files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_audit_trail_models.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_audit_trail_models.py
import pytest

from parrot_formdesigner.core import AuditDetail, AuditTrailConfig, CheckId, DEFAULT_MAX_BYTES

FROZEN_CHECK_IDS = {
    "form.circular_dependencies", "form.rule_integrity",
    "resolution.visible", "resolution.required",
    "field.voice_envelope", "field.required", "field.relation_shape", "field.coerce",
    "field.type", "field.option_set", "field.cross_field", "field.async_validator",
    "field.remote_response", "field.rest",
    "constraint.min_length", "constraint.max_length", "constraint.min_value",
    "constraint.max_value", "constraint.pattern", "constraint.min_items",
    "constraint.max_items", "constraint.allowed_mime_types",
}


def test_audit_detail_default_is_summary():
    """Absent config resolves to summary."""
    # FILL IN: AuditTrailConfig() and a FormSchema with no audit_trail block


def test_cap_default_per_detail():
    """max_bytes=None → 64 KiB summary / 256 KiB full; explicit value wins both ways."""
    # FILL IN: assert effective_max_bytes for SUMMARY, FULL, and max_bytes=4096 / 500_000


def test_check_id_values_are_stable():
    """Guards the published contract against a rename."""
    assert {c.value for c in CheckId} == FROZEN_CHECK_IDS


def test_audit_trail_independent_of_llm_validation():
    """Disabling the LLM check leaves deterministic auditing at its default."""
    # FILL IN: FormSchema with llm_validation=LLMValidationConfig(enabled=False), no audit_trail
```

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug formdesigner-validation-audit-trail --feature-id FEAT-732`
2. **Read the spec** — §2 Data Models, §3 Module 1.
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-run every `grep -c` in the blueprint.
5. **Update status** → `"in-progress"` in `sdd/tasks/index/formdesigner-validation-audit-trail.json`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the four listed files.
9. **Close** — `scripts/sdd/close_task.sh TASK-4644 formdesigner-validation-audit-trail verified`.
10. **Completion Note** — record that YAML forms do not yet load `audit_trail` (follow-up).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
