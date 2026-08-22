# TASK-2319: Add batch-list endpoint — GET /api/v1/comm_center/sender

**Feature**: commcenter-post-launch-fixes
**Feature ID**: FEAT-445
**Spec**: (follow-up to sdd/specs/commcenter-notify.spec.md — FEAT-417)
**Status**: [x] done
**Priority**: medium
**Depends-on**: TASK-2317
**Assigned-to**: unassigned

## Context

CommCenter has `GET /sender/{batch_id}` to inspect a single batch, but no
endpoint to **list** batches.  Without it, batch history is only available
client-side (per-browser IndexedDB / Dexie), so two operators on different
machines see different histories over the same shared library.

The tracking table (`notification_batch_recipients`) is flat — one row per
recipient, `batch_id` repeated. Batch-level metadata (totals, timestamps,
status breakdown) must be derived by aggregation.

## Scope

1. **Add `GET /api/v1/comm_center/sender`** to `CommCenterHandler`.
2. The endpoint returns a paginated list of batches with aggregated stats:
   ```json
   {
     "batches": [
       {
         "batch_id": "uuid",
         "created_at": "ISO-8601",
         "created_by": 42,
         "total": 150,
         "queued": 140,
         "skipped": 8,
         "publish_failed": 2,
         "pending": 0,
         "template_ref": "monthly-report",
         "provider": "email"
       }
     ],
     "total": 47,
     "limit": 25,
     "offset": 0
   }
   ```
3. **Query parameters**:
   - `limit` (default 25, max 100)
   - `offset` (default 0)
   - `status` — filter batches that have at least one row with this status
   - `provider` — filter by provider
   - `created_after` / `created_before` — ISO-8601 date range
4. The SQL query should `GROUP BY batch_id` over
   `notification_batch_recipients` with conditional counts per status.
5. **Requires `@is_authenticated`** (same as all CommCenter endpoints).

## Files to Create/Modify

- `packages/ai-parrot-server/src/parrot/handlers/comm_center.py` — add
  `get_batches()` method + route registration
- `packages/ai-parrot-server/tests/handlers/test_comm_center_*.py` — tests
  for the new endpoint
- `docs/comm_center.md` — add endpoint to the table

## Implementation Notes

- Follow the existing `get_batch_status()` method pattern for DB access
  and response shape.
- The flat table design means the aggregation query is the only way to
  derive batch-level info — there is no header table to SELECT from.
- Consider adding an index on `(created_at, batch_id)` if query
  performance is a concern with large volumes; add it to the
  `notification_batches_creation.sql` DDL file.
- The endpoint disambiguates from `GET /sender/{batch_id}` by the absence
  of a path parameter — aiohttp routing handles this naturally.

## Acceptance Criteria

- [x] `GET /api/v1/comm_center/sender` returns paginated batch list with
      aggregated status counts
- [x] `limit`, `offset`, `status`, `provider`, `created_after`,
      `created_before` filters work correctly
- [x] Response matches the documented JSON shape
- [x] Endpoint requires authentication
- [x] `docs/comm_center.md` endpoint table is updated
- [x] Tests cover: empty result, pagination, status filter, date range filter

### Completion Note

Added `get_batches()` to `CommCenterHandler`, registered as
`GET /api/v1/comm_center/sender` (disambiguated from the existing
`GET /sender/{batch_id}` by aiohttp's normal static-vs-dynamic route
resolution — verified live, both routes coexist without conflict). The
query aggregates `navigator.notification_batch_recipients` `GROUP BY
batch_id` with `COUNT(*) FILTER (WHERE status = ...)` per status, matching
the documented JSON shape (`batch_id`, `created_at`, `created_by`, `total`,
`queued`, `skipped`, `publish_failed`, `pending`, `template_ref`,
`provider`). `status`/`provider` filters are applied as an `IN (SELECT
batch_id FROM ... WHERE ...)` subquery so a batch's *other* rows are still
counted (a batch with 140 queued + 1 skipped row still reports `total=141`
when filtered by `status=skipped`, not just the matching row). `limit`
defaults to 25 and is clamped to 100; a second `COUNT(*)` query over the
same filters returns the overall `total` batch count for pagination.

Implemented the DB access directly in `comm_center.py` (raw
`conn.fetchall()`, mirroring `aggregate_batch_status`'s pattern in
`dispatch.py`) rather than adding a new function to `dispatch.py`, since
this task's file list named only `comm_center.py` for code changes — kept
`dispatch.py` untouched per file fidelity.

Tests (`test_comm_center_handler.py`, `TestGetBatches` +
`TestGetBatchesAuthentication`): empty result, pagination
params/clamping, status-filter subquery predicate, created_after/before
filters, aggregated-shape/batch_id-stringification, and a real
`@is_authenticated()` rejection test (via `aiohttp.test_utils.
make_mocked_request`, unlike the other `TestGetBatches` tests which call
`CommCenterHandler.get_batches.__wrapped__` directly to bypass the
decorator the same way this file's other handler-method tests bypass it
by not exercising decorated methods at all). Route-registration test
updated: 11 → 12 routes, plus a new assertion that `/sender` now answers
both `GET` and `POST`.

**Deliberately not done** (out of this task's file scope): the
`(created_at, batch_id)` index the task's Implementation Notes
"consider" adding to `notification_batches_creation.sql` — that file is
not in this task's Files to Create/Modify list, and TASK-2317 already
established the existing DDL as final/idempotent. Flagging as a possible
follow-up if list-batches query performance becomes a concern at scale.
