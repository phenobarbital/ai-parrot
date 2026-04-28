# TASK-904: Add reranker_config + parent_searcher_config columns to navigator.ai_bots

**Feature**: FEAT-133 — DB-Persisted Reranker & Parent-Searcher Config for AI Bots
**Spec**: `sdd/specs/bot-reranker-and-parent-searcher-config.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`navigator.ai_bots` already persists `vector_store_config JSONB` (creation.sql:46)
but has no equivalent column for FEAT-126 (reranker) or FEAT-128 (parent
searcher). This task adds the two new JSONB columns so DB-driven bots can opt
into both features without code changes. Implements spec section 3 / Module 3.

---

## Scope

- Add `reranker_config JSONB DEFAULT '{}'::JSONB` and
  `parent_searcher_config JSONB DEFAULT '{}'::JSONB` to the
  `CREATE TABLE navigator.ai_bots` block (placed alongside `vector_store_config`).
- Append idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for both
  columns at the bottom of the file (so existing deployments pick them up).
- Add `COMMENT ON COLUMN` entries for both columns referencing FEAT-133.

**NOT in scope**:
- Bulk migration of existing rows (out of scope per spec §1).
- Any Python code changes (handled by TASK-905..912).
- Provisioning of additional indexes (the configs are read-only at bot load
  time; no GIN index needed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/creation.sql` | MODIFY | Add columns to CREATE + idempotent ALTERs + COMMENTs |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
N/A (SQL-only task).

### Existing Signatures to Use
```sql
-- packages/ai-parrot/src/parrot/handlers/creation.sql:5
CREATE TABLE IF NOT EXISTS navigator.ai_bots (
    ...
    -- Vector store and retrieval configuration       (line 44)
    use_vector BOOLEAN DEFAULT FALSE,
    vector_store_config JSONB DEFAULT '{}'::JSONB,    -- line 46 — pattern to mirror
    embedding_model JSONB DEFAULT ...,                -- line 47
    ...
);
-- existing ALTER TABLE block at line 83 adds the unique constraint.
```

### Does NOT Exist
- ❌ `navigator.ai_bots.reranker_config` — to be added by this task.
- ❌ `navigator.ai_bots.parent_searcher_config` — to be added by this task.
- ❌ Any GIN index on the new columns — out of scope.

---

## Implementation Notes

### Pattern to Follow
Place the new columns inside the existing "Vector store and retrieval
configuration" block at line 44–49, immediately after `vector_store_config`.
Use the same `JSONB DEFAULT '{}'::JSONB` shape.

Append the idempotent ALTERs after the existing `ALTER TABLE` at line 83 and
the COMMENT block at lines 87+.

### Key Constraints
- Both columns MUST default to `'{}'::JSONB` so existing rows + new rows
  without explicit configuration retain pre-FEAT-133 behavior.
- ALTERs MUST use `IF NOT EXISTS` to remain idempotent (re-running the file
  on a deployed DB must not fail).

### Required SQL Snippets
```sql
-- Inside CREATE TABLE, alongside vector_store_config:
reranker_config        JSONB DEFAULT '{}'::JSONB,
parent_searcher_config JSONB DEFAULT '{}'::JSONB,

-- At end of file (after existing ALTER + COMMENT blocks):
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS reranker_config        JSONB DEFAULT '{}'::JSONB;
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS parent_searcher_config JSONB DEFAULT '{}'::JSONB;

COMMENT ON COLUMN navigator.ai_bots.reranker_config        IS 'FEAT-133 — reranker factory config (FEAT-126)';
COMMENT ON COLUMN navigator.ai_bots.parent_searcher_config IS 'FEAT-133 — parent searcher factory config (FEAT-128)';
```

---

## Acceptance Criteria

- [ ] `reranker_config JSONB DEFAULT '{}'::JSONB` exists inside
  `CREATE TABLE navigator.ai_bots`.
- [ ] `parent_searcher_config JSONB DEFAULT '{}'::JSONB` exists inside
  `CREATE TABLE navigator.ai_bots`.
- [ ] Idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` exists for both
  columns at the end of the file.
- [ ] `COMMENT ON COLUMN` entries are present for both columns.
- [ ] Re-running `creation.sql` on an existing DB succeeds without errors
  (idempotency).
- [ ] Maps to spec AC1.

---

## Test Specification

> SQL-only — test by applying the migration to a clean and to an
> existing-schema database, then verifying column presence + defaults.

```sql
-- Verify:
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_schema = 'navigator'
  AND table_name = 'ai_bots'
  AND column_name IN ('reranker_config', 'parent_searcher_config');
-- Expected: two rows with data_type=jsonb and column_default = '''{}''::jsonb'
```

---

## Agent Instructions

1. Read the spec section 3 (Module 3) for full context.
2. Verify the Codebase Contract: confirm `creation.sql` lines 5–66 and the
   ALTER/COMMENT blocks at 83+ still match the contract above.
3. Update `tasks/.index.json` → `"in-progress"` with your session ID.
4. Edit `creation.sql` per the snippets in Implementation Notes.
5. Confirm acceptance criteria locally if a test DB is available
   (otherwise leave verification to TASK-911 integration tests).
6. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
