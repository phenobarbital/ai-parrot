# TASK-2420: Submission mapper - tabular flattening and document nesting

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2417
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 5

---

## Context

Turns a `FormSubmission` into what a sink actually stores. Two modes, because
the destinations genuinely differ (spec section 8, resolved):

- **tabular** (Postgres table, CSV, Google Sheets, BigQuery): one flat row.
- **document** (Mongo, Arango): one document with `data` left **nested** - flattening a
  document store loses structure for no benefit.

Also owns `RESERVED_COLUMNS`, which TASK-2421 needs for collision validation and
TASK-2422/2424/2425 need to compute the additive column set.

Implements spec section 3 Module 5.

---

## Scope

- Create `services/sinks/mapper.py`.
- Define `RESERVED_COLUMNS: frozenset[str]` - `submission_id`, `form_uid`, `form_id`, `form_version`, `created_at`, `tenant`, `user_id`, `username`, `org_id`, `submitted_at`, `ip`, `user_agent`, `locale`, `root_submission_id`, `revision`, `context`.
- Implement `flatten_submission(form, submission) -> dict[str, Any]`: scalar field -> column named after `field_id`; `GROUP` -> recursive path flattening joined with `__`; `ARRAY` -> ONE column holding `json.dumps(...)`; declared `FormMetadataField.key` values -> their own columns; every reserved column always emitted.
- Implement `nest_submission(form, submission) -> dict[str, Any]`: the reserved fields plus `data` nested exactly as submitted.
- Implement `column_names_for(form) -> list[str]` returning the ordered tabular column set (reserved first, then form columns) - used by `ensure_target()` for additive extension.
- Handle `item_template` on ARRAY fields and `children` on GROUP fields when walking the schema.
- Write unit tests in `tests/unit/test_submission_mapper.py`.

**NOT in scope**: Any sink. Column DDL or type inference (TASK-2422). Validation of collisions against `RESERVED_COLUMNS` - that is TASK-2421's validator, which imports this constant.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py` | CREATE | flatten / nest / column_names_for |
| `packages/parrot-formdesigner/tests/unit/test_submission_mapper.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.
>
> Verified against `dev` on 2026-08-24. All paths are relative to the repo root.
> Line numbers shift as soon as anything above them changes — **re-`grep` before editing**.

### Verified Imports

```python
# Verified to resolve today:
from parrot_formdesigner.core.schema import (
    FormSchema, FormField, FormSection, FormSubsection, FormMetadataField,
)                                             # core/schema.py:313 / 44 / 155 / 102 / 257
from parrot_formdesigner.core.types import FieldType   # referenced by FormField.field_type
from parrot_formdesigner.services.submissions import FormSubmission  # services/submissions.py:50
import json
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:313
class FormSchema(BaseModel):
    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)   # line 356
    form_id: str                                              # line 357
    version: str = "1.0"                                      # line 358
    title: LocalizedString                                    # line 359
    sections: list[FormSection]                               # line 361
    submit: SubmitAction | None = None                        # line 362
    meta: dict[str, Any] | None = None                        # line 364
    created_at: datetime | None = None                        # line 365
    tenant: str | None = None                                 # line 366
    metadata: list[FormMetadataField] | None = None           # line 367
    events: FormEventsConfig | None = None                    # line 368
    form_type: FormType = FormType.SIMPLE                     # line 370
    published_version: str | None = None                      # line 372
    is_public: bool = False                                   # line 374
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:44 - self-referential; GROUP uses `children`, ARRAY uses `item_template`
class FormField(BaseModel):
    field_uid: uuid.UUID = Field(default_factory=uuid.uuid4)  # line 81
    field_id: str                                             # line 82
    field_type: FieldType                                     # line 83
    label: LocalizedString                                    # line 84
    children: list[FormField] | None = None                   # line 95  <- GROUP
    item_template: FormField | None = None                    # line 96  <- ARRAY
    meta: dict[str, Any] | None = None                        # line 97

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:257 - `key` is ALREADY validated as a safe Postgres identifier
# precisely so it can be promoted to a column (docstring lines 267-271). Rely on that.
class FormMetadataField(BaseModel):
    key: str                                  # line 292
    source: MetadataSource                    # line 293
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:50
class FormSubmission(BaseModel):
    submission_id: str          # default_factory=lambda: str(uuid.uuid4())
    form_uid: uuid.UUID         # REQUIRED (FEAT-389 / TASK-1979)
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime        # default_factory -> datetime.now(timezone.utc)
    tenant: str | None = None
    user_id: str | None = None
    username: str | None = None
    org_id: int | None = None
    submitted_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    root_submission_id: str | None = None
    revision: int | None = None
    context: dict[str, Any] | None = None
```

### Does NOT Exist

- ~~`FormSchema.persistence`~~ - does NOT exist on `dev`. It is added by TASK-2421. Until that task lands, do not read it off a `FormSchema` instance.
- ~~`FormField.name`~~ - the identifier attribute is `field_id` (`core/schema.py:82`).
- ~~an existing flattening helper~~ - there is no submission-flattening utility anywhere in the package. `FormSubmissionStorage` stores `data` as a single JSONB blob (`services/submissions.py:254` `_insert_sql`), which is exactly what this feature replaces for autonomous forms.
- ~~`FormSection.fields` containing only `FormField`~~ - it may ALSO contain `FormSubsection` (`core/schema.py:102`), which groups fields without being a field. The walker MUST handle both.

---

## Implementation Notes

### Pattern to Follow

Walk sections -> (fields | subsections) -> fields, recursively:

```python
SEP = "__"

def _walk(field: FormField, prefix: str = "") -> Iterator[tuple[str, FormField]]:
    name = f"{prefix}{SEP}{field.field_id}" if prefix else field.field_id
    if field.field_type == FieldType.GROUP and field.children:
        for child in field.children:
            yield from _walk(child, name)
    else:
        yield name, field          # ARRAY yields ONE column; value is json.dumps(...)
```

Reserved columns come from the `FormSubmission` attributes, not from the form.

### Key Constraints

- One row per submission, always - an ARRAY never fans out into extra rows.
- `GROUP` separator is exactly `__` (double underscore), so the result stays a valid Postgres identifier under `_IDENTIFIER_RE`.
- A flattened name longer than 63 chars must raise - Postgres identifiers are capped, and `validate_identifier` enforces 63.
- `nest_submission` must NOT mutate `submission.data`.
- Deterministic column ordering (reserved first, then schema order) so CSV headers are stable.
- Pure functions, no I/O, no logging side effects. Async not required here.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:44` - `FormField` self-reference (children / item_template)
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:102` - `FormSubsection`, the second thing in `FormSection.fields`
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:50` - the reserved attribute set
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/_identifiers.py:21` - the 63-char identifier cap

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.services.sinks.mapper import flatten_submission, nest_submission, column_names_for, RESERVED_COLUMNS` works
- [ ] A nested GROUP produces `parent__child` keys
- [ ] An ARRAY produces exactly ONE key whose value is a JSON string
- [ ] A declared `FormMetadataField.key` appears as its own key
- [ ] Every member of `RESERVED_COLUMNS` is present in `flatten_submission` output
- [ ] `nest_submission` output contains `data` nested and unmodified
- [ ] `column_names_for` is deterministic across calls and puts reserved columns first
- [ ] A GROUP path exceeding 63 characters raises
- [ ] A section containing a `FormSubsection` is walked correctly
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_submission_mapper.py -v` passes
- [ ] `ruff` and `mypy` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_submission_mapper.py
import json
import pytest

from parrot_formdesigner.services.sinks.mapper import (
    RESERVED_COLUMNS, column_names_for, flatten_submission, nest_submission,
)


class TestFlatten:
    def test_group_flattens_by_path(self, form_with_group, submission):
        row = flatten_submission(form_with_group, submission)
        assert "address__city" in row

    def test_array_is_single_json_column(self, form_with_array, submission_with_array):
        row = flatten_submission(form_with_array, submission_with_array)
        assert isinstance(row["answers"], str)
        assert json.loads(row["answers"]) == [{"q": 1}, {"q": 2}]

    def test_metadata_promoted(self, form_with_metadata, submission):
        assert "campaign_id" in flatten_submission(form_with_metadata, submission)

    def test_reserved_always_present(self, form_with_group, submission):
        row = flatten_submission(form_with_group, submission)
        assert RESERVED_COLUMNS <= set(row)

    def test_long_path_raises(self, form_with_deep_group, submission):
        with pytest.raises(ValueError):
            flatten_submission(form_with_deep_group, submission)

    def test_subsection_is_walked(self, form_with_subsection, submission):
        assert "notes" in flatten_submission(form_with_subsection, submission)


class TestNest:
    def test_data_stays_nested(self, form_with_group, submission):
        doc = nest_submission(form_with_group, submission)
        assert doc["data"] == submission.data
        assert "address__city" not in doc

    def test_does_not_mutate(self, form_with_group, submission):
        before = dict(submission.data)
        nest_submission(form_with_group, submission)
        assert submission.data == before


class TestColumnNames:
    def test_deterministic(self, form_with_group):
        assert column_names_for(form_with_group) == column_names_for(form_with_group)

    def test_reserved_come_first(self, form_with_group):
        names = column_names_for(form_with_group)
        assert set(names[: len(RESERVED_COLUMNS)]) == RESERVED_COLUMNS
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** - verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** - before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
4. **Update status** in `sdd/tasks/index/formbuilder-formschema-persistency.json` ->
   `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** -> `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
