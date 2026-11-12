# TASK-5558: Bots folds, tool remapping and language preservation

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5554, TASK-5556, TASK-5557
**Assigned-to**: unassigned


---

## Context

Implement M3 successors 002–005 with individually guarded legacy columns and durable postconditions. Prove retained values using before/after snapshots.

---

## Scope

Implement M3 successors 002–005 with individually guarded legacy columns and durable postconditions. Prove retained values using before/after snapshots.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes rendering from TASK-5554, runner.upgrade from TASK-5556, and 001_baseline SQL from TASK-5557; successor tests execute that baseline.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/migrations/sql/bots/002_fold_embedding.sql` | CREATE | Guard embedding_model; backfill absent JSON keys, normalize model to model_name, atomically drop source Use complete statements/DO blocks; never split SQL on semicolons. |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/002_fold_embedding.check.sql` | CREATE | Source absent and normalized destination invariant; explicit JSON null keys win Missing relations are screened by checks.verify_postconditions; remain valid after every successor. |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/003_fold_llm.sql` | CREATE | Guard each legacy tuning column independently; backfill missing JSON keys, mirror model_name to model then drop that source Use complete statements/DO blocks; never split SQL on semicolons. |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/003_fold_llm.check.sql` | CREATE | Legacy columns absent; alias invariant only where destination key was absent Missing relations are screened by checks.verify_postconditions; remain valid after every successor. |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/004_tool_names.sql` | CREATE | Map WebScraperTool/web_scraping, Ibis/ibisworld, Tickertool/yfinance while preserving order and other elements Use complete statements/DO blocks; never split SQL on semicolons. |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/004_tool_names.check.sql` | CREATE | No old tool keys remain in arrays; unrelated elements retained Missing relations are screened by checks.verify_postconditions; remain valid after every successor. |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/005_language_schema.sql` | CREATE | Drop language DEFAULT and NOT NULL, preserving every stored en/es/NULL value Use complete statements/DO blocks; never split SQL on semicolons. |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/005_language_schema.check.sql` | CREATE | Language nullable and has no default, no assertion requiring reset stored values Missing relations are screened by checks.verify_postconditions; remain valid after every successor. |
| `packages/ai-parrot/tests/migrations/test_bots_db.py` | CREATE | Fresh/legacy/partially dropped/current matrix; explicit JSON null and scalar key precedence; SQL NULL config; normalization when source absent; order and arbitrary tools elements preserved; language values preserved; users_bots absent and sentinels untouched; backfill/drop atomic failure; alternate schema/table and replay on completed schema |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from parrot.migrations.runner import upgrade
from parrot.migrations.checks import status
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql` — Verified legacy SQL; unsafe on already-dropped source columns; convert only bots portion and never copy lossy language UPDATE.
- `sdd/migrations/FEAT-fold-legacy-llm-columns.sql` — Verified legacy SQL; unsafe on already-dropped source columns; convert only bots portion and never copy lossy language UPDATE.
- `sdd/migrations/FEAT-fix-stale-bot-tool-names.sql` — Verified legacy SQL; unsafe on already-dropped source columns; convert only bots portion and never copy lossy language UPDATE.
- `sdd/migrations/FEAT-638-bot-language-nullable.sql` — Verified legacy SQL; unsafe on already-dropped source columns; convert only bots portion and never copy lossy language UPDATE.

### Dependency interfaces

- `TASK-5554` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5556` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5557` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.

### Does NOT Exist

- The generic migration packages are absent at planning HEAD; only declared dependency artifacts supply the new APIs.
- No core `PARROT_ADMIN_DSN` setting exists until the CLI task; no existing generic `parrot_schema_migrations` runner may be reused.
- No root-level `parrot/` directory or server `scheduler/store.py` exists. Do not infer executable migration APIs from model docstrings.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/migrations/sql/bots/002_fold_embedding.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/sql/bots/002_fold_embedding.check.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/sql/bots/003_fold_llm.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/sql/bots/003_fold_llm.check.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/sql/bots/004_tool_names.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/sql/bots/004_tool_names.check.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/sql/bots/005_language_schema.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/sql/bots/005_language_schema.check.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/migrations/test_bots_db.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Follow spec §2 for all safety and exit semantics. Use black (120 columns), strict types, Google-style docstrings and module logging. No synchronous database I/O. New SQL is transaction-wrapper-free; checks run read-only. Tests inject fake DSNs or use only `PARROT_MIGRATION_TEST_DSN`. Never contact application configuration DSNs. Local live tests may skip without the test DSN; feature closeout must provide passing live evidence, not skips. Keep logs under artifacts/logs/.

---

## Implementation Blueprint

### Steps (in order)

1. Verify dependencies and the cited source/anchors — because drift must be caught before editing.
2. Apply the per-file starting points below and complete their bounded logic — because file ownership and public signatures are fixed.
3. Exercise the behavioral matrix, including failures and cleanup — because happy-path checks alone cannot establish migration safety.
4. Run Validation Commands and inspect the scoped diff — because unrelated schema/loader changes are forbidden.

---

### `packages/ai-parrot/src/parrot/migrations/sql/bots/002_fold_embedding.sql` (CREATE)

```sql
-- Source: FEAT-fold-embedding-model-into-vector-store-config.sql (bots only).
DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = '{schema}' AND table_name = '{bots_table}'
          AND column_name = 'embedding_model'
    ) THEN
        -- FILL IN: backfill vector_store_config only if embedding_model key is absent.
        -- Explicit JSON null is present, so use JSONB key existence, not ->> IS NULL.
        -- FILL IN: drop source only after successful backfill in this body transaction.
    END IF;
    -- FILL IN: normalize nested model -> model_name even when source was absent.
    -- Preserve explicit destination keys and existing aliases per spec §2.
END
$migration$;
```

**Why**: Guard embedding_model; backfill absent JSON keys, normalize model to model_name, atomically drop source Use complete statements/DO blocks; never split SQL on semicolons.

---

### `packages/ai-parrot/src/parrot/migrations/sql/bots/002_fold_embedding.check.sql` (CREATE)

```sql
-- FEAT-884 postcondition: Source absent and normalized destination invariant; explicit JSON null keys win
-- FILL IN: replace FALSE with a SELECT-only, single-row, single-boolean predicate.
SELECT FALSE;
```

**Why**: Source absent and normalized destination invariant; explicit JSON null keys win Missing relations are screened by checks.verify_postconditions; remain valid after every successor.

---

### `packages/ai-parrot/src/parrot/migrations/sql/bots/003_fold_llm.sql` (CREATE)

```sql
-- Source: FEAT-fold-legacy-llm-columns.sql; independently guard each scalar.
DO $migration$
DECLARE
    source_column text;
BEGIN
    FOREACH source_column IN ARRAY ARRAY['model_name', 'temperature', 'max_tokens', 'top_k', 'top_p']
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = '{schema}' AND table_name = '{bots_table}'
              AND column_name = source_column
        ) THEN
            -- FILL IN: safely quote dynamic identifiers; backfill only absent JSON keys.
            -- Use to_jsonb to retain numeric/string types; explicit JSON null wins.
            -- FILL IN: drop this source only after its backfill succeeds.
        END IF;
    END LOOP;
    -- FILL IN: mirror model_name to model only if model key absent, including on replay.
END
$migration$;
```

**Why**: Guard each legacy tuning column independently; backfill missing JSON keys, mirror model_name to model then drop that source Use complete statements/DO blocks; never split SQL on semicolons.

---

### `packages/ai-parrot/src/parrot/migrations/sql/bots/003_fold_llm.check.sql` (CREATE)

```sql
-- FEAT-884 postcondition: Legacy columns absent; alias invariant only where destination key was absent
-- FILL IN: replace FALSE with a SELECT-only, single-row, single-boolean predicate.
SELECT FALSE;
```

**Why**: Legacy columns absent; alias invariant only where destination key was absent Missing relations are screened by checks.verify_postconditions; remain valid after every successor.

---

### `packages/ai-parrot/src/parrot/migrations/sql/bots/004_tool_names.sql` (CREATE)

```sql
-- Source: FEAT-fix-stale-bot-tool-names.sql; retain order and unrelated JSON elements.
UPDATE "{schema}"."{bots_table}" AS b
SET tools = (
    SELECT jsonb_agg(
        CASE elem #>> '{}'
            WHEN 'WebScraperTool' THEN '"web_scraping"'::jsonb
            WHEN 'Ibis' THEN '"ibisworld"'::jsonb
            WHEN 'Tickertool' THEN '"yfinance"'::jsonb
            ELSE elem
        END ORDER BY ord
    )
    FROM jsonb_array_elements(b.tools) WITH ORDINALITY AS t(elem, ord)
)
WHERE b.tools ?| ARRAY['WebScraperTool', 'Ibis', 'Tickertool'];
-- FILL IN: explicitly reject or safely skip non-array incompatible values; never erase them.
```

**Why**: Map WebScraperTool/web_scraping, Ibis/ibisworld, Tickertool/yfinance while preserving order and other elements Use complete statements/DO blocks; never split SQL on semicolons.

---

### `packages/ai-parrot/src/parrot/migrations/sql/bots/004_tool_names.check.sql` (CREATE)

```sql
-- FEAT-884 postcondition: No old tool keys remain in arrays; unrelated elements retained
-- FILL IN: replace FALSE with a SELECT-only, single-row, single-boolean predicate.
SELECT FALSE;
```

**Why**: No old tool keys remain in arrays; unrelated elements retained Missing relations are screened by checks.verify_postconditions; remain valid after every successor.

---

### `packages/ai-parrot/src/parrot/migrations/sql/bots/005_language_schema.sql` (CREATE)

```sql
-- Only the schema portion of FEAT-638; stored values are intentionally unchanged.
ALTER TABLE "{schema}"."{bots_table}" ALTER COLUMN language DROP DEFAULT;
ALTER TABLE "{schema}"."{bots_table}" ALTER COLUMN language DROP NOT NULL;
```

**Why**: Drop language DEFAULT and NOT NULL, preserving every stored en/es/NULL value Use complete statements/DO blocks; never split SQL on semicolons.

---

### `packages/ai-parrot/src/parrot/migrations/sql/bots/005_language_schema.check.sql` (CREATE)

```sql
-- No stored-language data invariant: en/es/NULL are all preserved.
SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = '{schema}' AND table_name = '{bots_table}'
      AND column_name = 'language' AND is_nullable = 'YES'
      AND column_default IS NULL
);
```

**Why**: Language nullable and has no default, no assertion requiring reset stored values Missing relations are screened by checks.verify_postconditions; remain valid after every successor.

---

### `packages/ai-parrot/tests/migrations/test_bots_db.py` (CREATE)

```python
"""Fresh/legacy/partially dropped/current matrix."""
from __future__ import annotations

import pytest
from parrot.migrations.runner import upgrade
from parrot.migrations.checks import status


async def test_bots_db_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Fresh/legacy/partially dropped/current matrix; explicit JSON null and scalar key precedence; SQL NULL config; normalization when source absent; order and arbitrary tools elements preserved; language values preserved; users_bots absent and sentinels untouched; backfill/drop atomic failure; alternate schema/table and replay on completed schema

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/migrations/sql/bots/002_fold_embedding.sql` — Guard embedding_model; backfill absent JSON keys, normalize model to model_name, atomically drop source Use complete statements/DO blocks; never split SQL on semicolons.
- [ ] `packages/ai-parrot/src/parrot/migrations/sql/bots/002_fold_embedding.check.sql` — Source absent and normalized destination invariant; explicit JSON null keys win Missing relations are screened by checks.verify_postconditions; remain valid after every successor.
- [ ] `packages/ai-parrot/src/parrot/migrations/sql/bots/003_fold_llm.sql` — Guard each legacy tuning column independently; backfill missing JSON keys, mirror model_name to model then drop that source Use complete statements/DO blocks; never split SQL on semicolons.
- [ ] `packages/ai-parrot/src/parrot/migrations/sql/bots/003_fold_llm.check.sql` — Legacy columns absent; alias invariant only where destination key was absent Missing relations are screened by checks.verify_postconditions; remain valid after every successor.
- [ ] `packages/ai-parrot/src/parrot/migrations/sql/bots/004_tool_names.sql` — Map WebScraperTool/web_scraping, Ibis/ibisworld, Tickertool/yfinance while preserving order and other elements Use complete statements/DO blocks; never split SQL on semicolons.
- [ ] `packages/ai-parrot/src/parrot/migrations/sql/bots/004_tool_names.check.sql` — No old tool keys remain in arrays; unrelated elements retained Missing relations are screened by checks.verify_postconditions; remain valid after every successor.
- [ ] `packages/ai-parrot/src/parrot/migrations/sql/bots/005_language_schema.sql` — Drop language DEFAULT and NOT NULL, preserving every stored en/es/NULL value Use complete statements/DO blocks; never split SQL on semicolons.
- [ ] `packages/ai-parrot/src/parrot/migrations/sql/bots/005_language_schema.check.sql` — Language nullable and has no default, no assertion requiring reset stored values Missing relations are screened by checks.verify_postconditions; remain valid after every successor.
- [ ] `packages/ai-parrot/tests/migrations/test_bots_db.py` — Fresh/legacy/partially dropped/current matrix; explicit JSON null and scalar key precedence; SQL NULL config; normalization when source absent; order and arbitrary tools elements preserved; language values preserved; users_bots absent and sentinels untouched; backfill/drop atomic failure; alternate schema/table and replay on completed schema
- [ ] Replace all planning markers with complete working code/tests; no placeholders may remain in implementation files.

---

## Acceptance Criteria

- [ ] All declared files implement the scope and per-file constraints above.
- [ ] Every case in Test Specification asserts observable outcomes, including failure paths.
- [ ] Existing frozen loader, BotModel DDL/shim and unrelated runtime fallback behavior remain unchanged.
- [ ] No credentials, raw driver errors, SQL bodies or parameter values leak into reports/logs.
- [ ] Declared validation succeeds; live-test skips are not release evidence.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/migrations/test_bots_db.py -q`

---

## Test Specification

- Fresh/legacy/partially dropped/current matrix; explicit JSON null and scalar key precedence; SQL NULL config; normalization when source absent; order and arbitrary tools elements preserved; language values preserved; users_bots absent and sentinels untouched; backfill/drop atomic failure; alternate schema/table and replay on completed schema

---

## Agent Instructions

1. Use `$sdd-start TASK-5558` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note

Populated by the task finalizer after verified implementation.
