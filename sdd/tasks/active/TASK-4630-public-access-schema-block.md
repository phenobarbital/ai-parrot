# TASK-4630: Public-access schema block (`PublicAccessConfig` on `FormSchema`)

**Feature**: FEAT-730 — FormDesigner public response controls
**Spec**: `sdd/specs/formdesigner-public-form-controls.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Public forms (FieldSync FEAT-796 / navigator-svelte FEAT-797)
need per-form response controls: open/closed, close date, response cap,
one-response-per-key-question and a completion action. They live in a TYPED
block on `FormSchema` (FEAT-649 precedent: `voice`, `llm_validation`), never in
`meta`. `public_access = None` means "no policy" — today's behaviour exactly.
This task only adds the models, the pure helpers and the schema validation;
enforcement is TASK-4632.

---

## Scope

- Create `core/public_access.py` with `CompletionAction`, `PublicAccessConfig`,
  `RejectionReason`, `AvailabilityState`, `evaluate_open()`, `normalize_key_value()`.
- Add `public_access: PublicAccessConfig | None = None` to `FormSchema` after
  `llm_validation`, plus a `_validate_public_access` model validator.
- Export the new names from `core/__init__.py`.
- Write unit tests.

**NOT in scope**: storage counting (TASK-4631), pipeline enforcement
(TASK-4632), HTTP (TASK-4634), docs (TASK-4637).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/public_access.py` | CREATE | models + pure helpers |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | `public_access` field + validator |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | exports |
| `packages/parrot-formdesigner/tests/unit/test_public_access_schema.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Paths below are relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`.
> Verified at ai-parrot `dev` @ `685e6176c`.

### Verified Imports
```python
from .types import FieldType, LocalizedString            # core/schema.py:25
from .llm_validation import LLMValidationConfig           # core/schema.py:26 (typed-block precedent)
from .voice import VoiceFormConfig                        # core/schema.py:27
from parrot_formdesigner.core.schema import FormSchema    # core/schema.py:411
```

### Existing Signatures to Use
```python
# core/schema.py
class FormSchema(BaseModel):                                        # line 411
    is_public: bool = False                                         # line 483
    persistence: FormPersistenceConfig | None = None                # line 485
    voice: VoiceFormConfig | None = None                            # line 489
    llm_validation: LLMValidationConfig | None = None               # line 491
    def iter_all_fields(self) -> Iterator[FormField]                # line 493 (top-level layout fields)
    @model_validator(mode="after")
    def _validate_persistence(self) -> FormSchema                   # line 587
# FormField.field_id: str ; FormField.field_type: FieldType
# FieldType members used: GROUP, ARRAY, FILE, IMAGE, IMAGE_DROPZONE, MULTI_UPLOAD, SIGNATURE (core/types.py)

# core/__init__.py
from .llm_validation import (                                       # line 60
__all__ = [ ... "LLMValidationConfig", ... ]                        # "LLMValidationConfig", at line 95
```

### Does NOT Exist
- ~~`FormSchema.public_access` / `closes_at` / `max_responses`~~ — added by this task.
- ~~`core.public_access`~~ — new module.
- ~~Any https-URL validator helper in core~~ — write the check inline with `urllib.parse.urlparse`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/public_access.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_public_access_schema.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema.iter_all_fields",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema._validate_persistence"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Copy the module shape of `core/llm_validation.py` (typed config block in its own
module, exported from `core/__init__.py`).

### Key Constraints
- Wire keys are the snake_case field names (cross-repo contract with FEAT-796/797).
- `closes_at` must be tz-aware; normalize to UTC. Naive → `ValueError`.
- `redirect_url`: absolute `https://` with a host only (reject `http:`, `javascript:`, `data:`, relative).
- `public_access` with `max_responses` or `unique_key_field` + `persistence` set → `ValueError`
  (counting is only atomic over `FormSubmissionStorage`).
- `unique_key_field` must be a `field_id` from `iter_all_fields()` whose type is not
  GROUP/ARRAY/FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD/SIGNATURE.

---

## Implementation Blueprint

### Steps (in order)
1. Create `core/public_access.py` — *why*: one typed module, like `llm_validation.py`.
2. Add the import and the field to `FormSchema` after `llm_validation` — *why*: spec §3 M1 fixes the position.
3. Add `_validate_public_access` after `_validate_persistence` — *why*: it reads `persistence` and the field tree, so it must be an `after` validator.
4. Export from `core/__init__.py` — *why*: hosts import from `parrot_formdesigner.core`.
5. Write the tests listed below and run them.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/public_access.py` (CREATE)
```python
"""Per-form public response controls (FEAT-730).

Typed ``FormSchema.public_access`` block: open/closed, close date, response cap,
one-response-per-key-question and the completion action. ``None`` on the form
means no policy (today's behaviour).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from .types import LocalizedString

RejectionReason = Literal["form_closed", "response_limit_reached", "duplicate_response"]


class CompletionAction(BaseModel):
    """What the respondent sees after a successful submit."""

    mode: Literal["message", "redirect"] = "message"
    message: LocalizedString | None = None
    redirect_url: str | None = None

    @model_validator(mode="after")
    def _validate_redirect(self) -> CompletionAction:
        """mode == "redirect" requires an absolute https:// redirect_url with a host."""
        # FILL IN: when redirect_url is set (any mode) validate scheme == "https" and netloc;
        # when mode == "redirect" and redirect_url is None raise — bounded by AC10.
        return self


class PublicAccessConfig(BaseModel):
    """Per-form response policy (``FormSchema.public_access``)."""

    accepting_responses: bool = True
    closes_at: datetime | None = None
    max_responses: int | None = Field(default=None, ge=1)
    unique_key_field: str | None = None
    completion: CompletionAction | None = None

    @field_validator("closes_at")
    @classmethod
    def _require_tz(cls, v: datetime | None) -> datetime | None:
        """Reject naive datetimes; normalize aware ones to UTC."""
        if v is None:
            return None
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("closes_at must be timezone-aware")
        return v.astimezone(timezone.utc)


class AvailabilityState(BaseModel):
    """Body of ``GET …/forms/{form_uid}/availability``."""

    accepting: bool
    reason: Literal["form_closed", "response_limit_reached"] | None = None
    completion: CompletionAction | None = None


def evaluate_open(config: PublicAccessConfig | None, *, now: datetime) -> Literal["form_closed"] | None:
    """Return ``"form_closed"`` when the form is closed at ``now``, else ``None``."""
    if config is None:
        return None
    # FILL IN: closed when accepting_responses is False or (closes_at and now >= closes_at) — AC2.
    return None


def normalize_key_value(value: Any) -> Any | None:
    """``None`` for blank/missing (None, "", whitespace, [], {}); strings returned stripped."""
    # FILL IN: implement per docstring — AC4 ("a blank value is never checked").
    return value
```
**Why this shape**: names, fields and wire keys are fixed by the cross-repo contract
(FEAT-796/797 read them). Do not add fields; do not rename.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .voice import VoiceFormConfig' core/schema.py)
# AFTER — insert below `from .voice import VoiceFormConfig` (verified: core/schema.py:27)
from .public_access import PublicAccessConfig
```
```python
# occurrences: 1 (verified: grep -c '    llm_validation: LLMValidationConfig | None = None' core/schema.py)
# AFTER — insert below `    llm_validation: LLMValidationConfig | None = None` (verified: core/schema.py:491)
    # FEAT-730 — public response controls (typed block, not meta).
    public_access: PublicAccessConfig | None = None
```
```python
# occurrences: 1 (verified: grep -c '    def _validate_persistence(self) -> FormSchema:' core/schema.py)
# BEFORE — insert above the `@model_validator(mode="after")` decorating
# `    def _validate_persistence(self) -> FormSchema:` (verified: core/schema.py:587)
    @model_validator(mode="after")
    def _validate_public_access(self) -> FormSchema:
        """Validate ``public_access`` against the form (FEAT-730)."""
        cfg = self.public_access
        if cfg is None:
            return self
        # FILL IN: (a) unique_key_field must name a field_id from iter_all_fields() whose
        # field_type is not GROUP/ARRAY/FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD/SIGNATURE;
        # (b) (max_responses or unique_key_field) and persistence is not None -> ValueError.
        # Error messages name the offending field — bounded by spec §3 M1.
        return self
```
**Why**: the validator needs the whole form (field tree + persistence), so it is a
schema-level `after` validator, next to the existing `_validate_persistence`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .llm_validation import (' core/__init__.py)
# BEFORE — insert above `from .llm_validation import (` (verified: core/__init__.py:60)
from .public_access import (
    AvailabilityState,
    CompletionAction,
    PublicAccessConfig,
    RejectionReason,
    evaluate_open,
    normalize_key_value,
)
```
```python
# occurrences: 1 (verified: grep -c '    "LLMValidationConfig",' core/__init__.py)
# AFTER — insert below `    "LLMValidationConfig",` (verified: core/__init__.py:95)
    # Public response controls (FEAT-730)
    "PublicAccessConfig",
    "CompletionAction",
    "AvailabilityState",
    "RejectionReason",
    "evaluate_open",
    "normalize_key_value",
```
**Why**: hosts import these from `parrot_formdesigner.core`.

### `packages/parrot-formdesigner/tests/unit/test_public_access_schema.py` (CREATE)
```python
"""FEAT-730 — public_access schema block."""
from datetime import datetime, timedelta, timezone

import pytest

from parrot_formdesigner.core import PublicAccessConfig, CompletionAction, evaluate_open, normalize_key_value
from parrot_formdesigner.core.schema import FormSchema


def test_public_access_defaults_none():
    """A form without the block round-trips with public_access None."""
    # FILL IN: build a minimal FormSchema (copy a builder from tests/unit/test_core_models.py), dump/load.


def test_redirect_requires_https():
    # FILL IN: http:, javascript:, relative, missing URL on redirect mode -> ValueError; https ok.
    ...


def test_closes_at_naive_rejected():
    # FILL IN: naive -> ValueError; +02:00 aware -> stored as UTC.
    ...


def test_unique_key_must_exist_and_be_scalar():
    # FILL IN: unknown field_id / GROUP field / FILE field -> ValueError; TEXT field ok.
    ...


def test_cap_with_persistence_rejected():
    # FILL IN: max_responses + persistence -> ValueError.
    ...


def test_evaluate_open():
    # FILL IN: None config, manual close, past/future closes_at.
    ...


def test_normalize_key_value():
    # FILL IN: None/""/"  "/[]/{} -> None; " a@x.com " -> "a@x.com"; 5 -> 5.
    ...
```
**Why**: the test names are the spec §4 rows for Module 1.

### FILL IN checklist
- [ ] `CompletionAction._validate_redirect` — https + host only; bounded by AC10
- [ ] `evaluate_open` — closed rules; bounded by AC2
- [ ] `normalize_key_value` — blank detection; bounded by AC4
- [ ] `FormSchema._validate_public_access` — key-field and persistence rules; bounded by spec §3 M1
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `FormSchema` without `public_access` serializes exactly as before (AC1).
- [ ] Redirect validation accepts only absolute `https://` (AC10).
- [ ] Unknown / non-scalar `unique_key_field` and cap+persistence combinations raise.
- [ ] `ruff check` clean on the touched files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_public_access_schema.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -q`

---

## Test Specification

See the CREATE block above (spec §4 Module 1 rows).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug formdesigner-public-form-controls --feature-id FEAT-730`).
2. Read the spec; verify the Codebase Contract (re-run every `grep -c`).
3. Set `in-progress` in `sdd/tasks/index/formdesigner-public-form-controls.json`.
4. Implement from the blueprint; complete every `FILL IN`.
5. Run the Validation Commands; commit only the listed files.
6. `scripts/sdd/close_task.sh TASK-4630 formdesigner-public-form-controls verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
