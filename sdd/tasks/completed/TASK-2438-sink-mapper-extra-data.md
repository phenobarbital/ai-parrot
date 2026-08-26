# TASK-2438: Carry `extra_data` through FEAT-457's submission sinks

**Feature**: FEAT-458 — Unknown-Field Capture Policy for Form Submissions
**Spec**: `sdd/specs/formdesigner-unknown-fields-capture.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2435
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 8

---

## Context

Without this task the feature is **half-working**, in exactly the way FEAT-458
exists to eliminate. FEAT-457's central acceptance criterion is *exclusivity*: a
form declaring `persistence:` writes ONLY to its own sink and skips
`FormSubmissionStorage` entirely. So an `extra_data` column on `navigator.form_data`
captures extras for generic-storage forms and silently loses them again for
autonomous ones.

> ⚠️ **BLOCKED ON FEAT-457** (`formbuilder-formschema-persistency`, 15 tasks, all
> `in-progress` as of 2026-08-24). This task edits `services/sinks/mapper.py`, a
> file **FEAT-457/TASK-2420 creates**. It cannot begin before that task lands —
> this is a semantic dependency, not merely a merge conflict.

Implements spec section 3 Module 8.

---

## Scope

- Add `"extra_data"` to `RESERVED_COLUMNS` in `services/sinks/mapper.py` so no
  `field_id` or `FormMetadataField.key` can collide with the reserved column in a
  tabular target. TASK-2421's `FormSchema` validator imports this constant, so the
  authoring-time collision check comes along for free — verify that it does.
- Emit `extra_data` from `flatten_submission(form, submission)` as ONE column
  holding `json.dumps(submission.extra_data)`, mirroring the treatment ARRAY fields
  already get. `None` must serialize to SQL `NULL`, not the string `"null"`.
- Include `extra_data` in `nest_submission(form, submission)`'s reserved fields,
  left as a nested object (document targets keep structure).
- Add `extra_data` to `column_names_for(form)` so `ensure_target()` provisions the
  column on tabular sinks.
- Confirm the type inference used by the Postgres/BigQuery `ensure_target()`
  implementations maps it to a JSON/JSONB-ish column, not `TEXT`; if the inference
  is driven by a name→type map, register `extra_data` there.
- Extend `packages/parrot-formdesigner/tests/unit/test_submission_mapper.py` (created
  by TASK-2420) rather than creating a parallel test file.

**NOT in scope**: Creating `mapper.py`, the sink ABC, or any sink implementation —
all FEAT-457. Any change to `FormSubmissionStorage` (TASK-2435 owns it). The
handler branch (TASK-2436).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py` | MODIFY | `RESERVED_COLUMNS`, `flatten_submission`, `nest_submission`, `column_names_for` |
| `packages/parrot-formdesigner/tests/unit/test_submission_mapper.py` | MODIFY | Add `extra_data` cases |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Most of this contract is **PLANNED, NOT LANDED**. Every name below
> comes from FEAT-457's spec and task files, not from a file you can read today.
> `grep` each one and reconcile against reality BEFORE writing code. If a signature
> differs from what is listed, update this contract first, then implement.

### Verified Imports

```python
# VERIFIED — landed (TASK-2435):
from ..submissions import FormSubmission     # services/submissions.py:50
from ...core.schema import FormSchema        # core/schema.py:313

# PLANNED — created by FEAT-457/TASK-2420; verify the module path and names:
from .mapper import RESERVED_COLUMNS, column_names_for, flatten_submission, nest_submission
```

### Existing Signatures to Use

```python
# ── VERIFIED (landed via TASK-2435) ────────────────────────────────────────────
# services/submissions.py:50
class FormSubmission(BaseModel):
    submission_id: str
    form_uid: uuid.UUID
    form_id: str
    form_version: str
    data: dict[str, Any]                    # line 97
    is_valid: bool                          # line 98
    ...
    context: dict[str, Any] | None = None   # line 115
    extra_data: dict[str, Any] | None = None  # NEW — TASK-2435

# services/submissions.py:39-47 — the OTHER reserved-ish list. Do NOT add
# extra_data here: it is not a metadata column, and this tuple's order is coupled
# to FormSubmissionStorage._insert_sql.
CORE_METADATA_COLUMNS: tuple[str, ...] = (
    "user_id", "username", "org_id", "submitted_at", "ip", "user_agent", "locale",
)

# ── PLANNED (FEAT-457/TASK-2420 — spec sections 394-403, Module 5) ─────────────
# services/sinks/mapper.py
RESERVED_COLUMNS: frozenset[str]
#   Declared contents per TASK-2420 scope: submission_id, form_uid, form_id,
#   form_version, created_at, tenant, user_id, username, org_id, submitted_at,
#   ip, user_agent, locale, root_submission_id, revision, context
#   → THIS TASK ADDS: extra_data
def flatten_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]: ...
#   Per TASK-2420: scalar field -> column named after field_id; GROUP -> recursive
#   path flattening joined with `__`; ARRAY -> ONE column holding json.dumps(...);
#   declared FormMetadataField.key values -> their own columns; every reserved
#   column always emitted.
def nest_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]: ...
#   Per TASK-2420: the reserved fields plus `data` nested exactly as submitted.
def column_names_for(form: FormSchema) -> list[str]: ...
#   Per TASK-2420: ordered tabular column set (reserved first, then form columns);
#   used by ensure_target() for additive extension.

# ── PLANNED (FEAT-457/TASK-2421) ──────────────────────────────────────────────
# core/schema.py — FormSchema's @model_validator is extended to reject, when
# `persistence` is set AND the target is tabular: any field_id or
# FormMetadataField.key colliding with RESERVED_COLUMNS. Adding "extra_data" to
# that frozenset is what makes spec AC15 hold — verify the validator picks it up
# rather than hard-coding a second list.
```

### Does NOT Exist

- ~~`services/sinks/`~~ — the whole package is created by FEAT-457. If it is not
  there, this task is not yet startable; stop and report.
- ~~`RESERVED_COLUMNS`~~, ~~`flatten_submission`~~, ~~`nest_submission`~~,
  ~~`column_names_for`~~ — none exist on `dev` as of 2026-08-24.
- ~~`FormSchema.persistence`~~ — planned by TASK-2421.
- ~~An `extra_data` entry anywhere in FEAT-457's specified `RESERVED_COLUMNS`~~ —
  it is absent from TASK-2420's declared list; adding it is precisely this task.
- ~~A second collision-validation list to update~~ — TASK-2421's validator imports
  `RESERVED_COLUMNS`. Do not create a parallel constant.

---

## Implementation Notes

### Pattern to Follow

```python
# services/sinks/mapper.py — flatten_submission, tabular target.
# Mirror the ARRAY treatment: one column, json.dumps'd. None -> None (SQL NULL),
# NOT json.dumps(None) which would store the literal string "null".
row["extra_data"] = (
    json.dumps(submission.extra_data)
    if submission.extra_data is not None
    else None
)

# services/sinks/mapper.py — nest_submission, document target.
# Document stores keep structure; do not flatten and do not stringify.
doc["extra_data"] = submission.extra_data     # may be None
```

### Key Constraints

- **`None` → SQL `NULL`**, never the string `"null"` and never `{}` (spec AC23).
  This is the same trap as TASK-2435's `_row_to_submission`.
- **Do not stringify for document sinks.** Flattening or `json.dumps`-ing into a
  Mongo/Arango document loses structure for no benefit — the reasoning TASK-2420
  records for `data` applies identically to `extra_data`.
- `extra_data` belongs in the **reserved** block of `column_names_for`'s ordering
  (reserved first, then form columns), next to `context`.
- Adding to a `frozenset` means also checking nothing iterates it expecting a
  fixed length or a specific order.
- The extras are unvalidated caller-controlled JSON. A sink must never interpolate
  their keys into DDL or SQL — they go in as a single opaque value. Verify the
  sink's `ensure_target()` derives columns from `column_names_for(form)` only, never
  from a submission's runtime keys.

### References in Codebase

- `sdd/tasks/active/TASK-2420-submission-mapper.md` — the authoritative scope for
  `mapper.py`; read it before editing.
- `sdd/tasks/active/TASK-2421-formschema-persistence-field.md` — the
  `RESERVED_COLUMNS` collision validator this task feeds.
- `services/submissions.py:254-282` — the `::text::jsonb` lesson; a Postgres sink
  writing JSONB is subject to the same double-encoding hazard.

---

## Acceptance Criteria

- [ ] `"extra_data" in RESERVED_COLUMNS`.
- [ ] A form declaring a `field_id` named `extra_data` against a tabular target is
      rejected at authoring time by TASK-2421's validator, with no second
      hard-coded list involved (spec AC15).
- [ ] `flatten_submission` emits an `extra_data` column holding
      `json.dumps(extra_data)` when set, and `None` when `extra_data is None`
      (never the string `"null"`).
- [ ] `nest_submission` includes `extra_data` as a nested object (not stringified),
      `None` when unset.
- [ ] `column_names_for(form)` includes `extra_data` in the reserved block.
- [ ] A tabular sink's `ensure_target()` provisions the column with a JSON-ish
      type, not `TEXT`.
- [ ] A form with `persistence:` and `unknown_fields: keep` writes extras to its
      sink and nothing to `navigator.form_data` (spec AC14 — asserted end-to-end
      by TASK-2440).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_submission_mapper.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_submission_mapper.py  (extend, do not replace)
import json
import pytest
from parrot_formdesigner.services.sinks.mapper import (
    RESERVED_COLUMNS, column_names_for, flatten_submission, nest_submission,
)


def test_reserved_columns_includes_extra_data():
    assert "extra_data" in RESERVED_COLUMNS


class TestFlattenExtraData:
    def test_emits_json_column(self, simple_form, submission_factory):
        row = flatten_submission(simple_form, submission_factory(extra_data={"legacy_id": 42}))
        assert row["extra_data"] == json.dumps({"legacy_id": 42})

    def test_none_stays_none(self, simple_form, submission_factory):
        row = flatten_submission(simple_form, submission_factory(extra_data=None))
        assert row["extra_data"] is None

    def test_none_is_not_the_string_null(self, simple_form, submission_factory):
        row = flatten_submission(simple_form, submission_factory(extra_data=None))
        assert row["extra_data"] != "null"


class TestNestExtraData:
    def test_included_as_object(self, simple_form, submission_factory):
        doc = nest_submission(simple_form, submission_factory(extra_data={"legacy_id": 42}))
        assert doc["extra_data"] == {"legacy_id": 42}

    def test_not_stringified(self, simple_form, submission_factory):
        doc = nest_submission(simple_form, submission_factory(extra_data={"a": 1}))
        assert not isinstance(doc["extra_data"], str)


def test_column_names_for_includes_extra_data(simple_form):
    assert "extra_data" in column_names_for(simple_form)


def test_field_id_named_extra_data_rejected(tabular_persistence_config):
    """Spec AC15 — authoring-time collision with the reserved column."""
    from parrot_formdesigner.core.schema import FormSchema
    with pytest.raises(ValueError, match="extra_data"):
        FormSchema(..., persistence=tabular_persistence_config)  # field_id="extra_data"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-unknown-fields-capture.spec.md` for full context.
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code: confirm each import
   still resolves and each listed signature still has the listed attributes. Line
   numbers were verified on `dev` at `72490fa14` (2026-08-24) and WILL drift once
   FEAT-456/FEAT-457 land — re-`grep` rather than trusting a number.
4. **Update status** in `sdd/tasks/index/formdesigner-unknown-fields-capture.json` → `"in-progress"`.
5. **Implement** following the scope and contract above. Nothing outside scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-26
**Notes**: FEAT-457 had merged; `services/sinks/mapper.py` existed exactly
as the contract's PLANNED section described (263 lines, `RESERVED_COLUMNS`
frozenset + `_RESERVED_COLUMN_ORDER` tuple driving a shared
`_reserved_values()` getattr helper used by both `flatten_submission` and
`nest_submission`). Added `"extra_data"` to both `RESERVED_COLUMNS` and
`_RESERVED_COLUMN_ORDER` (the latter automatically threads it through
`column_names_for()` too, since that function is just
`list(_RESERVED_COLUMN_ORDER) + ...`). Because `_reserved_values()` is
shared, its raw `getattr(submission, "extra_data")` value is exactly right
for `nest_submission` (nested object, unstringified) but wrong for
`flatten_submission` (needs `json.dumps`, mirroring ARRAY) — so
`flatten_submission` overrides `row["extra_data"]` post-hoc with the
serialize-or-None logic, rather than special-casing the shared helper.
`core/schema.py`'s `_validate_persistence` model_validator already imports
`RESERVED_COLUMNS` directly (verified, no second hard-coded list), so
AC15's authoring-time collision check came for free. 8 new tests + 1
updated fixture in `tests/unit/test_submission_mapper.py`.

**Deviations from spec**: Two files NOT in this task's Files table were
touched, both justified by explicit text elsewhere in the task itself
(Scope: "Confirm the type inference ... if the inference is driven by a
name→type map, register extra_data there"; References: "a Postgres sink
writing JSONB is subject to the same double-encoding hazard" as
`services/submissions.py:254-282`). Verified `postgres_table.py` DOES
drive `ensure_target()`'s DDL from exactly such a map
(`_RESERVED_COLUMN_DDL: dict[str, str]`) — without an entry, `extra_data`
would silently fall through to the `TEXT` default (violating the AC
"provisions the column with a JSON-ish type, not TEXT") AND its INSERT
would use a bare `$n` placeholder instead of `$n::text::jsonb` (the exact
double-encoding hazard the references warn about, since `flatten_submission`
already hands `write()` a pre-`json.dumps`'d string). Added
`"extra_data": "JSONB"` to `_RESERVED_COLUMN_DDL` and `"extra_data"` to
`write()`'s `jsonb_columns` base set (alongside `"context"`). Verified
BigQuery's `asyncdb_store.py` needs NO change — `ensure_target()` types
every `column_names_for()` entry uniformly as `STRING` (no per-column map
to register against, confirmed by inspection), and Mongo/Arango document
writes never stringify or cast. Added matching tests to
`tests/unit/test_postgres_table_sink.py` (2 new: DDL type + write-cast).
**NOT fixed** (flagged, not silently expanded): neither
`postgres_table.py`'s `_row_to_submission` nor `asyncdb_store.py`'s
`_doc_to_submission` reconstruct `FormSubmission.extra_data` from a stored
row/document — both were already missing this before this task (same gap
pre-existed for zero other reserved JSONB columns being read back through
"has an entry but the read path doesn't propagate it" — actually `context`
IS reconstructed in both). This means `PostgresTableSink.read()` /
`AsyncDBSink.read()` will return `extra_data=None` even when a row/doc
genuinely has extras stored — a real but narrow gap, out of this task's
explicit Files list (`FormSubmissionStorage` read-path is TASK-2435's,
and these two sink read-paths were never named anywhere in this task).
Full-suite regression diff (`git stash` before/after): zero new failures.
`ruff check` on all 4 changed files: clean, zero findings.
