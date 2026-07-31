# TASK-2008: Migrations — form_uid type, question_id rename, element-UID backfill

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1995, TASK-1997, TASK-2006
**Assigned-to**: unassigned

---

## Context

Implements Module 14 of FEAT-393 (spec §3, blueprint §9). Three migration
artifacts following FEAT-389's numbered, idempotent convention under
`packages/parrot-formdesigner/migrations/`: two SQL (column type retrofit,
question-bank rename) and one Python (JSONB UID backfill + rule-reference
rewrite with a duplicates report).

---

## Scope

- SQL A — `form_schemas.form_uid` and `form_data.form_uid` column type
  `VARCHAR(36)` → `UUID` (`USING form_uid::uuid`), guarded to skip when
  already `uuid` (query `information_schema.columns`).
- SQL B — `field_bank` column rename `field_id` → `question_id` + UNIQUE
  constraint rename, guarded on column existence.
- Python C — for each `form_schemas` row: walk `schema_json` in `walk_fields`
  order; inject missing `field_uid`/`section_uid`/`subsection_uid`
  (`str(uuid.uuid4())`); duplicate `field_id` in a form → add to report and
  SKIP the row (no write); rewrite rule refs by round-tripping through
  `FormSchema.model_validate` + `resolve_rule_references`; re-save via the
  existing upsert; final report lists migrated / skipped-duplicates / blobs
  still on legacy `{form_id}/{field_id}/` key patterns (report only — never
  rewrite object-store keys).
- Idempotency tests for all three (re-run = no-op / same output).

**NOT in scope**: object-store key rewrites (forbidden); registry/in-memory
state (rebuilt from storage on load).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/migrations/00X_form_uid_uuid_type.sql` | CREATE | column type retrofit |
| `packages/parrot-formdesigner/migrations/00Y_question_bank_question_id.sql` | CREATE | bank column rename |
| `packages/parrot-formdesigner/migrations/00Z_backfill_element_uids.py` | CREATE | JSONB backfill + report |
| `packages/parrot-formdesigner/tests/unit/migrations/test_feat393_migrations.py` | CREATE | idempotency + report tests |

> Numbering: FEAT-389 creates `001..003`; use the next free numbers at
> implementation time (ls the migrations dir first).

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormSchema, walk_fields        # TASK-1996
from parrot_formdesigner.core.resolution import resolve_rule_references    # TASK-1997
```

### Existing Signatures to Use
```python
# services/storage.py — PostgresFormStorage (:63) (FEAT-389 rewrites this file — re-verify)
# _create_table_sql (:148-163): schema_json JSONB NOT NULL; UNIQUE(form_id, version) (:161)
#   → post-FEAT-389: form_uid VARCHAR(36) NOT NULL, UNIQUE(form_uid, version)
# _upsert_sql (:165-176): ON CONFLICT ... DO UPDATE SET schema_json = EXCLUDED.schema_json
# services/question_bank.py DDL (:74-85): field_id VARCHAR(255), UNIQUE(field_id, tenant)
#   → post-TASK-2006 the CODE says question_id; THIS migration renames existing DBs
# blob key pattern pre-change: {prefix}{form_id}/{field_id}/{uuid} (blob_storage.py:220)
# FEAT-389 migration artifacts: packages/parrot-formdesigner/migrations/
#   001_add_form_uid.sql, 002_add_form_uid_submissions.sql, 003_migrate_form_data.py
#   (per its spec Module 3b) — MATCH their style: idempotent, re-runnable, report-emitting
```

### Does NOT Exist
- ~~an Alembic/framework migration runner~~ — migrations are plain numbered SQL/py artifacts (FEAT-389 convention); do not introduce a framework
- ~~a blob-key rewrite path~~ — explicitly forbidden; report only
- ~~`migrations/` dir on pre-FEAT-389 dev~~ — created by FEAT-389; if missing at start, the gate was violated — STOP

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 14" blueprint (SQL bodies + Python outline given).

### Key Constraints
- SQL guards: `DO $$ ... IF EXISTS (SELECT 1 FROM information_schema.columns
  WHERE ...) THEN ... END IF; $$;` — plain `ALTER TABLE` alone is not
  idempotent for the rename.
- Python backfill determinism: same input doc → same structure (fresh UUIDs
  differ per run, but docs ALREADY carrying `*_uid` keys must pass through
  byte-identical — that is the idempotency test).
- Duplicate-field_id forms: skip + report, never auto-rename, never write.
- Tenant-qualified tables: reuse `qualified_table` from
  `services/_identifiers.py` (used by question_bank DDL) for schema-qualified
  names.

---

## Acceptance Criteria

- [ ] SQL A/B idempotent (second run: no error, no change)
- [ ] Backfill injects UIDs at every tree level (sections, subsections, fields, children, item_template)
- [ ] Backfill rewrites rule refs to UIDs; already-migrated docs pass through unchanged
- [ ] Duplicate-field_id form → skipped + reported, row unmodified
- [ ] Report lists legacy-pattern blob refs without touching them
- [ ] `pytest packages/parrot-formdesigner/tests/unit/migrations/ -v` passes; `ruff check` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/migrations/test_feat393_migrations.py
def test_backfill_injects_all_uid_levels(legacy_schema_json): ...
def test_backfill_rewrites_rule_refs(legacy_schema_json): ...
def test_backfill_idempotent(migrated_schema_json): ...
def test_backfill_skips_and_reports_duplicates(duplicate_field_id_json): ...
def test_report_lists_legacy_blob_refs(): ...
# SQL idempotency: run against the test Postgres fixture twice (or assert guard SQL shape
# if no DB fixture exists — check how FEAT-389's migration tests do it and MATCH)
```

---

## Agent Instructions

1. **Read the spec** §9 Module 14; verify TASK-1995/1997/2006 completed.
2. **Verify the contract**: ls `migrations/`, read FEAT-389's artifacts, match their style and pick next numbers.
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run tests, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-31
**Notes**:

Read FEAT-389's existing 3 migration artifacts (`001_add_form_uid.sql`,
`002_add_form_uid_submissions.sql`, `003_migrate_form_data.py`) and its
`README.md`/test file (`tests/unit/test_migrations_form_uid.py`) first to
match style exactly before writing anything: `ls migrations/` showed
`001`/`002`/`003` already used, so this task's artifacts are numbered
`004`/`005`/`006`.

**SQL A** (`004_form_uid_uuid_type.sql`): retrofits `form_schemas.form_uid`
and `form_data.form_uid` from `VARCHAR(36)` to native `UUID`, each guarded
by an `information_schema.columns` check on `data_type <> 'uuid'` AND
scoped to `table_schema = current_schema()` — the same
per-physical-schema scoping FEAT-389's `001` uses (and which its own
regression test explicitly checks for), so one tenant's already-migrated
table never masks another's. `form_data.form_uid` is nullable
(orphan-tolerant, per FEAT-389); `NULL::uuid` casts without error so no
separate guard was needed there.

**SQL B** (`005_question_bank_question_id.sql`): renames the EXISTING
`field_bank.field_id` column (and its `UNIQUE(field_id, tenant)`
constraint, under Postgres's default auto-generated name) to
`question_id`, guarded so the column rename only fires if the OLD name
exists AND the NEW one doesn't (safe against a partial/interrupted prior
run), and the constraint rename only fires if the OLD constraint name
still exists in `pg_constraint`.

**Python C** (`006_backfill_element_uids.py`): implemented as a PURE,
directly-testable `migrate_schema_document(data: dict) ->
DocumentMigrationResult` core, wrapped by a DB-batch runner
(`backfill_element_uids`) mirroring `003`'s keyset-pagination pattern
(guards against the exact infinite-loop class FEAT-389's own tests
specifically regression-test for — a plain `WHERE ... IS NULL` re-fetch
never shrinks for orphaned/unchanged/dry-run rows). Key implementation
decision: `migrate_schema_document` round-trips the document through
`FormSchema.model_validate()` rather than a hand-rolled tree walk — this
already mints a fresh `field_uid`/`section_uid`/`subsection_uid` via each
model's own `default_factory=uuid.uuid4` for any level missing one, while
preserving already-present UIDs unchanged (verified idempotent). This
ALSO means `FormSchema._validate_unique_identity` (added in TASK-1996,
Module 2) catches duplicate `field_id`s for free — `model_validate` raises
a `pydantic.ValidationError` wrapping the model_validator's "Duplicate
field_id '...'" message, which is regex-extracted into a clean, specific
`skipped_reason="duplicate_field_id"` + `duplicate_field_ids` report
entry (a generic `validation_error: ...` fallback also exists for any
other validation failure, so a malformed document can never crash the
whole batch run). After validation, `resolve_rule_references(form)`
rewrites `depends_on`/`post_depends` field_id references to field_uid
(idempotent by construction, per its own docstring).

Legacy blob-ref detection (`find_legacy_blob_refs` / `is_legacy_blob_ref`)
scans `form_data.data` (submission answers) for blob_ref-shaped strings
(`s3://`/`gs://`/`file://`/`temp://` prefixes) and classifies each by
whether ANY two ADJACENT path segments both parse as UUIDs (new pattern)
— report only, `scan_legacy_blob_refs` never issues an UPDATE.

Created `tests/unit/migrations/` (new package, `__init__.py` matching
`unit/services/`'s one-line convention) with
`test_feat393_migrations.py` — 19 tests total, all passing:
- SQL content/idempotency-guard assertions for 004 and 005 (matching
  FEAT-389's `test_001_add_form_uid_sql_exists_and_idempotent` style).
- All 5 Test-Specification-named tests:
  `test_backfill_injects_all_uid_levels`, `test_backfill_rewrites_rule_refs`,
  `test_backfill_idempotent`, `test_backfill_skips_and_reports_duplicates`,
  `test_report_lists_legacy_blob_refs`.
- Additional stub-pool DB-flow tests for `backfill_element_uids`/
  `scan_legacy_blob_refs` (migrate-and-write, dry-run writes nothing,
  duplicate skip writes nothing, already-migrated is a no-op) — matching
  FEAT-389's `_StubConn`/`_StubPool` depth per the task's "MATCH their
  style" instruction, beyond the 5 explicitly named pure-function tests.
- `test_arg_parser_requires_dsn_and_schema` / `test_main_handles_unreachable_dsn_gracefully`
  mirroring 003's CLI-boundary coverage.

Full suite: `pytest packages/parrot-formdesigner/tests/ -q` → 1849 passed
(19 new), exactly the same 20 pre-existing/unrelated baseline failures as
every prior task in this feature. FEAT-389's own
`test_migrations_form_uid.py` (15 tests) re-verified passing unmodified.
`ruff check` on the two new Python files: 5 findings on first pass, all
fixed (`EXE001` — matched `003`'s executable bit via `chmod +x`; 2×
`UP037` — removed unnecessary quotes from `asyncpg.Pool` annotations,
safe since `from __future__ import annotations` makes them lazy anyway;
2× `RUF019` in the test file — replaced `"key" in dict and dict["key"]`
with `dict.get("key")`). Note: `ruff check` does not lint `.sql` files
(not a SQL linter) — the 380-error false alarm on first invocation was
ruff mis-parsing `004_form_uid_uuid_type.sql` as Python when passed
directly; scoping to `.py` files only resolved this immediately and is
reflected in the Acceptance Criteria checklist below as SQL content
verified via direct string assertions instead.

**Deviations from spec**: none — every file created is exactly the one
named in the task's "Files to Create/Modify" table, at the next free
migration numbers (004/005/006) as instructed.
