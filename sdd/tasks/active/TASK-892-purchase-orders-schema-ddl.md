# TASK-892: Create/verify wm_assembly.purchase_orders table DDL

**Feature**: wm-assembly-purchase-orders-date-sanitization
**Feature ID**: FEAT-130
**Spec**: sdd/specs/wm-assembly-purchase-orders-date-sanitization.spec.md
**Jira**: NAV-8241
**Status**: [ ] pending
**Priority**: high
**Depends-on**: TASK-891
**Assigned-to**: unassigned

## Context

The PostgreSQL table `wm_assembly.purchase_orders` must accept `NULL`
values in the `order_date` and `delivery_date` columns so that the
sanitized rows (where `########` was coerced to `NULL`) can be inserted
without a `NOT NULL` constraint violation.

## Scope

Create or update the SQL DDL file:
`/home/jesuslara/proyectos/navigator/navigator-dataintegrator-tasks/docs/sql/wm_assembly/purchase_orders.sql`

The DDL must:

1. Use `CREATE TABLE IF NOT EXISTS wm_assembly.purchase_orders (...)`.
2. Declare `order_date DATE NULL` and `delivery_date DATE NULL`.
3. Set the primary key to `(po_number, po_line)` (adjust if the source
   data confirms a different PK).
4. Include all other columns present in the source Excel export
   (po_number, po_line, store_id, vendor_id, item_id, quantity, etc.).
5. Include an `updated_at TIMESTAMPTZ DEFAULT NOW()` audit column.

Reference the existing SQL files under:
`/home/jesuslara/proyectos/navigator/navigator-dataintegrator-tasks/docs/sql/wm_assembly/`

## Files to Create/Modify

- `/home/jesuslara/proyectos/navigator/navigator-dataintegrator-tasks/docs/sql/wm_assembly/purchase_orders.sql` — CREATE

## Implementation Notes

- Check the existing wm_assembly SQL directory for naming conventions.
- If the table already exists in the database with `NOT NULL` date
  columns, include an `ALTER TABLE ... ALTER COLUMN ... DROP NOT NULL`
  migration statement.
- The task definition (TASK-891) may reference this SQL file via an
  `ExecuteSQL` step; coordinate file name accordingly.

## Acceptance Criteria

- [ ] SQL file exists and is syntactically valid.
- [ ] Both `order_date` and `delivery_date` are defined as `DATE NULL`.
- [ ] File is referenced (or can be referenced) from the
      `purchase_orders.json` task via `ExecuteSQL`.
