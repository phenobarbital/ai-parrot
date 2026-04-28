# TASK-895: Verify att_concierge bot record migration and document acceptance criteria

**Feature**: att-concierge-bot-record
**Feature ID**: FEAT-131
**Spec**: sdd/specs/att-concierge-bot-record.spec.md
**Status**: [ ] pending
**Priority**: medium
**Effort**: S
**Depends-on**: TASK-894
**Parallel**: false
**Assigned-to**: unassigned

## Context

After the SQL migration in TASK-894 is created, this task runs it against the
development PostgreSQL instance and confirms all acceptance criteria from the spec
are satisfied.

## Scope

1. Apply the migration `sdd/migrations/FEAT-131-att-concierge-bot-record.sql` against
   the dev/staging PostgreSQL instance using the configured DSN.
2. Execute the verification queries from the spec to confirm each AC is met.
3. Run the migration a second time to confirm idempotency (no error, no duplicate row).
4. Record the `chatbot_id` UUID of the newly created row.

## Verification Queries

```sql
-- AC-1: Row exists
SELECT name FROM navigator.ai_bots WHERE name = 'att_concierge';

-- AC-2: Vector config
SELECT use_vector, vector_store_config
FROM navigator.ai_bots WHERE name = 'att_concierge';

-- AC-3: Enabled and operation mode
SELECT enabled, operation_mode
FROM navigator.ai_bots WHERE name = 'att_concierge';

-- AC-4: Idempotency (run migration twice, then check count)
SELECT COUNT(*) FROM navigator.ai_bots WHERE name = 'att_concierge';
-- Expected: 1
```

## Files to Create/Modify

No new files. This task is purely operational/verification.

## Test Criteria

All four acceptance criteria from the spec (AC-1 through AC-4) must pass:
- 1 row with `name = 'att_concierge'` in `navigator.ai_bots`
- `use_vector = TRUE` and `vector_store_config` references `att.concierge`
- `enabled = TRUE` and `operation_mode = 'adaptive'`
- Count = 1 after running migration twice (idempotency)

## Implementation Notes

- Use the `NAVIGATOR_PG_DSN` or equivalent environment variable for the database connection.
- If the target database is not reachable from local, document the commands and ask a
  DBA/DevOps engineer to run them in the appropriate environment.
- Report results with screenshot or psql output as evidence.
