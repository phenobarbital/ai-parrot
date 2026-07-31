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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
