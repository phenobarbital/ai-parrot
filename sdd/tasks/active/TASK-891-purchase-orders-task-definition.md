# TASK-891: Create purchase_orders flowtask task definition

**Feature**: wm-assembly-purchase-orders-date-sanitization
**Feature ID**: FEAT-130
**Spec**: sdd/specs/wm-assembly-purchase-orders-date-sanitization.spec.md
**Jira**: NAV-8241
**Status**: [ ] pending
**Priority**: high
**Depends-on**: none
**Assigned-to**: unassigned

## Context

The `wm_assembly` `purchase_orders` flowtask does not yet have a task
definition file. When rows in the source Excel/SAP export contain
`########` as a date value (an Excel column-overflow artifact), the
raw string reaches PostgreSQL and triggers:

```
psycopg2.errors.InvalidDatetimeFormat: invalid input syntax for type date: "########"
```

This task creates the `purchase_orders.json` flowtask definition with a
date-sanitization step that coerces `########` (and any other
non-parseable date string) to `NULL` before the database write.

## Scope

Create the file:
`/home/jesuslara/proyectos/navigator/navigator-dataintegrator-tasks/programs/wm_assembly/tasks/purchase_orders.json`

The task definition must include:

1. A source data ingestion step (e.g. `DownloadFromSharepoint` or
   `OpenWithPandas`) that reads the Excel/SAP export containing
   `po_number`, `po_line`, `store_id`, `order_date`, `delivery_date`
   and related purchase order columns.
2. A `TransformRows` step that sanitizes `order_date` and `delivery_date`:
   - Any value matching the regex `^#+$` (the `########` overflow pattern)
     must be replaced with `null` / `None`.
   - Any value that cannot be parsed as a valid date must also be set to `null`.
3. A `FilterRows` step with `clean_dates: true` to handle any residual
   `NaT` values after the transformation.
4. A `CopyToPg` or `TableOutput` step that writes to
   `wm_assembly.purchase_orders`.

Reference existing task files for the pattern:
- `programs/wm_assembly/tasks/stores.json` (TransformRows + FilterRows + CopyToPg)
- `programs/wm_assembly/tasks/volt_transactions.json` (TableOutput)

## Files to Create/Modify

- `/home/jesuslara/proyectos/navigator/navigator-dataintegrator-tasks/programs/wm_assembly/tasks/purchase_orders.json` — CREATE

## Implementation Notes

- Use `TransformRows` with a `replace_regex` or equivalent verb to
  sanitize date fields before any SQL write step.
- The `clean_dates: true` option on `FilterRows` only handles
  `datetime64[ns]` NaT values — it does NOT catch string `########`.
  Both steps are needed.
- Primary key for the table: `(po_number, po_line)` or
  `(po_number, po_line, store_id)` — confirm against the source schema.
- Use `if_exists: "append"` with `upsert` or `replace` semantics as
  appropriate for idempotent re-runs.

## Acceptance Criteria

- [ ] File `purchase_orders.json` exists and is valid JSON.
- [ ] The JSON contains a step that maps to a date-sanitization
      transformation on `order_date` and `delivery_date`.
- [ ] `flowtask --program=wm_assembly --task=purchase_orders` exits 0
      when run against a test dataset containing `########` values.
