# Feature Specification: wm_assembly purchase_orders Date Sanitization

**Feature ID**: FEAT-130
**Jira**: NAV-8241
**Date**: 2026-04-28
**Author**: flow-bot (research phase)
**Reporter**: jesuslarag@gmail.com
**Assignee**: flow-bot
**Status**: approved
**Target version**: next patch release

---

## 1. Motivation & Business Requirements

### Problem Statement

The `wm_assembly` `purchase_orders` flowtask fails on every run that
contains rows where `delivery_date` or `order_date` carries the
Excel/SAP overflow sentinel value `########`.

This sentinel is produced by SAP-generated Excel exports when a date
value does not fit the display column width, or the underlying serial
value is out of the valid date range. The raw string `########` is
passed verbatim to the PostgreSQL `INSERT` / `COPY` path, which raises:

```
psycopg2.errors.InvalidDatetimeFormat:
    invalid input syntax for type date: "########"
```

A single bad row causes the entire task batch to fail, silently dropping
all valid rows that would have been processed in the same run.

**Affected record (first observed)**:
- `po_number=41131767`, `po_line=70`, `store_id=754`
- `delivery_date='########'`
- Observed at `2026-04-27T19:09:57.260378Z`

### Business Impact

- All `purchase_orders` data for the affected run date is lost (no
  partial insert).
- Downstream dashboards and reports that depend on `wm_assembly.purchase_orders`
  go stale silently.
- Operations team must manually re-trigger the task once the root cause
  is identified, adding operational overhead.

---

## 2. Scope

### In-scope

1. Create the flowtask task definition file
   `programs/wm_assembly/tasks/purchase_orders.json` in the
   `navigator-dataintegrator-tasks` repository (or in the local
   `ai-parrot` workspace if that is where the task is managed).
2. Add a `TransformRows` / `FilterRows` step (or equivalent inline
   transformation) that sanitizes date fields before the SQL write step:
   - Field list to sanitize: `order_date`, `delivery_date` (and any
     other column typed as `date`/`datetime` in the schema).
   - Sanitization rule: if the raw string value matches `########`, or
     cannot be parsed as a valid date, set the field to `None` / `NULL`.
3. Add or update the PostgreSQL table definition `wm_assembly.purchase_orders`
   to accept `NULL` for `order_date` and `delivery_date`.
4. Write a unit test that feeds a DataFrame with `########` in a date
   column through the sanitization step and asserts the output value
   is `None`/`NaT`.

### Out-of-scope

- Changes to the `flowtask` framework itself (FilterRows, TransformRows
  source code) — we use existing capabilities.
- Backfilling historical bad data.
- Changing the Excel/SAP export format.

---

## 3. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|-------------|
| AC-1 | `flowtask --program=wm_assembly --task=purchase_orders` exits with code 0 | Shell: `flowtask --program=wm_assembly --task=purchase_orders` |
| AC-2 | Rows with `delivery_date='########'` are inserted with `delivery_date=NULL` | SQL query on `wm_assembly.purchase_orders` |
| AC-3 | All valid rows in the same batch are inserted (no silent drop) | Row count check pre/post run |
| AC-4 | Unit test `test_purchase_orders_date_sanitization` passes with `pytest -x` | `pytest tests/wm_assembly/test_purchase_orders.py` |
| AC-5 | No regression on other wm_assembly tasks | Full wm_assembly task suite passes |

---

## 4. Technical Design

### 4.1 Root Cause

The `OpenWithPandas` component reads the Excel export and produces a
`pandas.DataFrame`. When Excel contains `########`, pandas reads it as
the string `"########"` (object dtype) rather than a `NaT` or
`datetime` value, because the cell content is literally the overflow
string, not a numeric date serial.

The existing `FilterRows.clean_dates` option only cleans `NaT` values
on columns already typed as `datetime64[ns]`. It does not handle string
columns that contain non-parseable date strings like `########`.

### 4.2 Fix Location

In the `purchase_orders.json` task definition, add a `TransformRows`
step before the `CopyToPg` / `TableOutput` step:

```json
{
  "TransformRows": {
    "fields": {
      "order_date": {
        "value": ["safe_date_or_null"]
      },
      "delivery_date": {
        "value": ["safe_date_or_null"]
      }
    }
  }
}
```

If `safe_date_or_null` is not a built-in TransformRows verb, use the
`replace_value` verb with a regex match:

```json
{
  "TransformRows": {
    "fields": {
      "order_date": {
        "value": ["replace_regex", {"pattern": "^#+$", "replacement": null}]
      },
      "delivery_date": {
        "value": ["replace_regex", {"pattern": "^#+$", "replacement": null}]
      }
    }
  }
}
```

Alternatively, a `FilterRows` step with `clean_dates: true` after
forcing a `pd.to_datetime(..., errors='coerce')` pass on the date
columns will also convert any unparseable string to `NaT`, which
downstream maps to `NULL`.

### 4.3 Schema Consideration

Ensure the target table columns `order_date` and `delivery_date` are
defined as `DATE NULL` (not `NOT NULL`) so `NULL` values are accepted.

---

## 5. Files to Create / Modify

| File | Action | Notes |
|------|--------|-------|
| `programs/wm_assembly/tasks/purchase_orders.json` | CREATE | Full task definition with date sanitization step |
| `docs/sql/wm_assembly/purchase_orders.sql` | CREATE or VERIFY | `CREATE TABLE` DDL with nullable date columns |
| `tests/wm_assembly/test_purchase_orders.py` | CREATE | Unit test for date sanitization |

---

## 6. Dependencies

- flowtask >= 5.11.2 (already installed in the worker environment)
- pandas >= 1.5 (already available via flowtask)
- Access to `wm_assembly` PostgreSQL schema (existing, used by other tasks)

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Other date columns have same overflow issue | Medium | Low | Sanitize all date-typed columns generically |
| SAP export format changes, `########` disappears | Low | None | Fix is additive; no harm if pattern never matches |
| NULL dates break downstream SQL JOINs | Low | Medium | Review downstream SQL; use `COALESCE` where needed |
