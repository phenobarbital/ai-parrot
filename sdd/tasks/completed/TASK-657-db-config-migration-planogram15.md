# TASK-657: DB config migration for planogram_id=15 (Epson scanner endcap)

**Feature**: FEAT-096 — Endcap Backlit Multitier Planogram Type
**Spec**: `sdd/specs/endcap-backlit-multitier.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-655
**Assigned-to**: unassigned

---

## Context

This is Module 5 of FEAT-096. The Epson scanner endcap (planogram_id=15 in table
`troc.planograms_configurations`) currently uses `planogram_type = "product_on_shelves"`.
To activate the new type, its config row must be updated to:

1. Set `planogram_type = "endcap_backlit_multitier"`.
2. Add `sections` arrays to the top shelf config (the multi-riser scanner shelf that was
   causing cross-tier hallucinations).
3. Middle and bottom shelves remain flat (no sections needed).

This task produces and documents the migration. It does NOT modify code.

---

## Scope

- Produce a SQL migration script (or documented `UPDATE` statement) for `troc.planograms_configurations`.
- The script must update planogram_id=15's `config_json` (or equivalent column) to add
  the sections schema for the top shelf.
- Document the section layout (left/center/right columns with product assignments).
- Verify the migration is safe to run (no schema change, data-only update).

**NOT in scope**: Modifying the Python code (TASK-655/656). Running the migration (user must
approve and run against their DB). Projector planogram — leave on current type.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/migrations/FEAT-096-planogram15-config.sql` | CREATE | SQL UPDATE for planogram_id=15 config |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

N/A — this task produces SQL, not Python code.

### Existing Signatures to Use

From the brainstorm (verified design decisions):

```
Top shelf (multi-riser): 3 sections (left / center / right)
  left:   x_start=0.00, x_end=0.35 — products: [ES-60W, ES-C320W, ES-50]
  center: x_start=0.35, x_end=0.65 — products: [ES-580W, FF-680W]
  right:  x_start=0.65, x_end=1.00 — products: [RR-70W, RR-600W]
  section_padding: 0.05

Middle shelf (flat): sections=null
Bottom shelf (flat): sections=null
```

DB table: `troc.planograms_configurations`
Column holding planogram type: `planogram_type` (exact column name — verify against DB schema)
Column holding config JSON: `config_json` or `config` (exact name — verify against DB schema)

### Does NOT Exist

- ~~The migration does not add new DB columns~~ — `sections` is stored inside the existing
  JSON config column, not a new column.
- ~~No ORM model change needed~~ — `PlanogramConfig.planogram_config` is a `Dict[str, Any]`.

---

## Implementation Notes

### SQL template

```sql
-- FEAT-096: Update planogram_id=15 to use endcap_backlit_multitier type
-- Run on: troc database
-- Safe: data-only update, no schema change
-- Backup recommended before running

BEGIN;

UPDATE troc.planograms_configurations
SET
    planogram_type = 'endcap_backlit_multitier',
    config_json = jsonb_set(
        jsonb_set(
            config_json,
            '{planogram_type}',
            '"endcap_backlit_multitier"'
        ),
        '{shelves}',
        (
            SELECT jsonb_agg(
                CASE
                    WHEN shelf->>'level' = 'top' THEN
                        shelf
                        || '{"section_padding": 0.05}'::jsonb
                        || jsonb_build_object('sections', '[
                            {"id": "left",   "region": {"x_start": 0.00, "x_end": 0.35, "y_start": 0.0, "y_end": 1.0}, "products": ["ES-60W", "ES-C320W", "ES-50"]},
                            {"id": "center", "region": {"x_start": 0.35, "x_end": 0.65, "y_start": 0.0, "y_end": 1.0}, "products": ["ES-580W", "FF-680W"]},
                            {"id": "right",  "region": {"x_start": 0.65, "x_end": 1.00, "y_start": 0.0, "y_end": 1.0}, "products": ["RR-70W", "RR-600W"]}
                        ]'::jsonb)
                    ELSE shelf
                END
            )
            FROM jsonb_array_elements(config_json->'shelves') AS shelf
        )
    )
WHERE planogram_id = 15;

-- Verify:
SELECT planogram_id, planogram_type, config_json->'shelves'->0->'level', config_json->'shelves'->0->'sections'
FROM troc.planograms_configurations
WHERE planogram_id = 15;

COMMIT;
```

### Caveats for the implementing agent

1. **Verify column names**: before writing the final SQL, check the actual column names
   in `troc.planograms_configurations` (the exact column for the JSON config and the
   planogram type string). The column may be named `config`, `config_json`, or similar.

2. **Verify jsonb vs json**: if the column is `json` (not `jsonb`), the `jsonb_set`
   approach won't work directly. Adjust accordingly.

3. **Product names**: the product names in the sections (ES-60W, ES-C320W, etc.) must
   exactly match the `name` field in the existing `products` array for the top shelf.
   Verify by querying the current config:
   ```sql
   SELECT config_json->'shelves'->0->'products' FROM troc.planograms_configurations WHERE planogram_id = 15;
   ```

4. **Section Y ratios**: all sections span `y_start=0.0, y_end=1.0` (full shelf height)
   because the top shelf is a multi-column riser, not horizontal rows.

5. **Do not touch projector planogram** — only update planogram_id=15.

---

## Acceptance Criteria

- [ ] Migration script created at `sdd/migrations/FEAT-096-planogram15-config.sql`
- [ ] Script is idempotent (safe to run twice)
- [ ] Script includes a verification `SELECT` after the `UPDATE`
- [ ] Product names in sections match exactly what is in the current config
- [ ] Correct column names verified against actual DB schema (document in script comments)
- [ ] Middle and bottom shelves left unchanged (sections=null)

---

## Test Specification

N/A — this is a data migration. Verification is via the `SELECT` in the script and
end-to-end testing with a real image after migration (manual).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/endcap-backlit-multitier.spec.md`.
2. **Check dependencies** — TASK-655 must be in `tasks/completed/`.
3. **Query the DB** (if accessible) to verify column names and current config:
   ```sql
   SELECT planogram_id, planogram_type, config_json FROM troc.planograms_configurations WHERE planogram_id = 15;
   ```
   If DB not accessible: write the SQL template and add a TODO comment for the user
   to verify column names before running.
4. **Create** `sdd/migrations/FEAT-096-planogram15-config.sql` with the final SQL.
5. **Update status** in `tasks/.index.json` → `"in-progress"`, then `"done"`.
6. **Move this file** to `tasks/completed/TASK-657-db-config-migration-planogram15.md`.
7. **Commit** with message: `sdd: TASK-657 add DB migration script for planogram_id=15`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
