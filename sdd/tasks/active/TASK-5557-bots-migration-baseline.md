# TASK-5557: Non-destructive bots baseline and schema checks

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5554, TASK-5556
**Assigned-to**: unassigned


---

## Context

Implement M3 file 001 from BotModel and historical additive DDL. Create complete fresh schema and catch up supported existing schemas without data loss.

---

## Scope

Implement M3 file 001 from BotModel and historical additive DDL. Create complete fresh schema and catch up supported existing schemas without data loss.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes catalog.render_sql from TASK-5554 and runner.upgrade from TASK-5556 for disposable database tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/migrations/sql/bots/001_baseline.sql` | CREATE | Complete 49-field bots table, additive catch-up, scoped indexes/constraints and qualified timestamp trigger Use complete statements/DO blocks; never split SQL on semicolons. |
| `packages/ai-parrot/src/parrot/migrations/sql/bots/001_baseline.check.sql` | CREATE | All required columns/types/nullability, compatible defaults, keys/indexes/trigger; do not require a language default or NOT NULL removed by 005 Missing relations are screened by checks.verify_postconditions; remain valid after every successor. |
| `packages/ai-parrot/tests/migrations/test_bots_baseline.py` | CREATE | Fresh full shape/no seeds/no uuid-ossp; legacy 44 fields and missing tooling/suggestions; preserve rows; reject incompatible type/constraint or missing required identity on nonempty table; custom targets and distinct index/constraint names; usable existing UUID default retained; replay idempotence; 001 check valid after 005 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from parrot.migrations.runner import upgrade
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/models/bots.py` — BotModel line 100; 49 model fields; Meta.strict=True and configured targets line 461. Embedded DDL and hydration shim are frozen.
- `packages/ai-parrot-server/src/parrot/handlers/creation.sql` — Fresh-install SQL at line 1; includes destructive bootstrap and seeds that must not enter the packaged baseline.
- `sdd/migrations/ai-bots-homologate-botmodel.sql` — Verified additive statements; strip transaction wrappers when converting, retain source until conversion task.
- `sdd/migrations/FEAT-add-prompt-config-ai-bots.sql` — Verified additive statements; strip transaction wrappers when converting, retain source until conversion task.
- `sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql` — Verified additive statements; strip transaction wrappers when converting, retain source until conversion task.
- `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` — Verified additive statements; strip transaction wrappers when converting, retain source until conversion task.

### Dependency interfaces

- `TASK-5554` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5556` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.

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
      "path": "packages/ai-parrot/src/parrot/migrations/sql/bots/001_baseline.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/sql/bots/001_baseline.check.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/migrations/test_bots_baseline.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/bots.py#BotModel"
  ]
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

### `packages/ai-parrot/src/parrot/migrations/sql/bots/001_baseline.sql` (CREATE)

```sql
-- Provenance: BotModel documented DDL and fields; historical additive scripts.
CREATE TABLE IF NOT EXISTS "{schema}"."{bots_table}" (
    chatbot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR NOT NULL,
    description TEXT,
    avatar TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    timezone VARCHAR(75) DEFAULT 'UTC',
    role VARCHAR DEFAULT 'AI Assistant',
    goal TEXT NOT NULL DEFAULT 'Help users accomplish their tasks effectively.',
    backstory TEXT NOT NULL DEFAULT 'I am an AI assistant created to help users with various tasks.',
    rationale TEXT NOT NULL DEFAULT 'I maintain a professional tone and provide accurate, helpful information.',
    capabilities TEXT DEFAULT 'I can engage in conversation, answer questions, and use tools when needed.',
    system_prompt_template TEXT,
    human_prompt_template TEXT,
    pre_instructions JSONB DEFAULT '[]'::JSONB,
    prompt_config JSONB NOT NULL DEFAULT '{}'::JSONB,
    llm VARCHAR DEFAULT 'google',
    model_config JSONB DEFAULT '{}'::JSONB,
    tools_enabled BOOLEAN DEFAULT TRUE,
    auto_tool_detection BOOLEAN DEFAULT TRUE,
    tool_threshold DOUBLE PRECISION DEFAULT 0.7,
    tools JSONB DEFAULT '[]'::JSONB,
    toolkit_config JSONB DEFAULT '{}'::JSONB,
    mcp_servers JSONB DEFAULT '[]'::JSONB,
    operation_mode VARCHAR DEFAULT 'adaptive',
    use_vector BOOLEAN DEFAULT FALSE,
    vector_store_config JSONB DEFAULT '{}'::JSONB,
    reranker_config JSONB DEFAULT '{}'::JSONB,
    parent_searcher_config JSONB DEFAULT '{}'::JSONB,
    context_search_limit INTEGER DEFAULT 10,
    context_score_threshold DOUBLE PRECISION DEFAULT 0.7,
    memory_type VARCHAR DEFAULT 'memory',
    memory_config JSONB DEFAULT '{}'::JSONB,
    max_context_turns INTEGER DEFAULT 5,
    use_conversation_history BOOLEAN DEFAULT TRUE,
    enable_suggestions BOOLEAN DEFAULT FALSE,
    suggest_followups BOOLEAN DEFAULT FALSE,
    suggestion_timeout_s REAL DEFAULT 4.0,
    max_suggestions INTEGER DEFAULT 6,
    suggestion_model VARCHAR,
    permissions JSONB DEFAULT '{}'::JSONB,
    use_kb BOOLEAN DEFAULT FALSE,
    kb JSONB,
    custom_kbs JSONB,
    bot_class VARCHAR,
    language VARCHAR(10),
    disclaimer TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by INTEGER,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
-- FILL IN: guarded additive catch-up before indexes; fail incompatible schemas.
-- FILL IN: table-scoped indexes/constraints and schema-qualified updated_at function/trigger.
-- No DROP TABLE, seeds, transaction wrappers, or user-data normalization in this file.
```

**Why**: Complete 49-field bots table, additive catch-up, scoped indexes/constraints and qualified timestamp trigger Use complete statements/DO blocks; never split SQL on semicolons.

---

### `packages/ai-parrot/src/parrot/migrations/sql/bots/001_baseline.check.sql` (CREATE)

```sql
-- FEAT-884 postcondition: All required columns/types/nullability, compatible defaults, keys/indexes/trigger; do not require a language default or NOT NULL removed by 005
-- FILL IN: replace FALSE with a SELECT-only, single-row, single-boolean predicate.
SELECT FALSE;
```

**Why**: All required columns/types/nullability, compatible defaults, keys/indexes/trigger; do not require a language default or NOT NULL removed by 005 Missing relations are screened by checks.verify_postconditions; remain valid after every successor.

---

### `packages/ai-parrot/tests/migrations/test_bots_baseline.py` (CREATE)

```python
"""Fresh full shape/no seeds/no uuid-ossp."""
from __future__ import annotations

import pytest
from parrot.migrations.runner import upgrade


async def test_bots_baseline_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Fresh full shape/no seeds/no uuid-ossp; legacy 44 fields and missing tooling/suggestions; preserve rows; reject incompatible type/constraint or missing required identity on nonempty table; custom targets and distinct index/constraint names; usable existing UUID default retained; replay idempotence; 001 check valid after 005

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/migrations/sql/bots/001_baseline.sql` — Complete 49-field bots table, additive catch-up, scoped indexes/constraints and qualified timestamp trigger Use complete statements/DO blocks; never split SQL on semicolons.
- [ ] `packages/ai-parrot/src/parrot/migrations/sql/bots/001_baseline.check.sql` — All required columns/types/nullability, compatible defaults, keys/indexes/trigger; do not require a language default or NOT NULL removed by 005 Missing relations are screened by checks.verify_postconditions; remain valid after every successor.
- [ ] `packages/ai-parrot/tests/migrations/test_bots_baseline.py` — Fresh full shape/no seeds/no uuid-ossp; legacy 44 fields and missing tooling/suggestions; preserve rows; reject incompatible type/constraint or missing required identity on nonempty table; custom targets and distinct index/constraint names; usable existing UUID default retained; replay idempotence; 001 check valid after 005
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

- `pytest packages/ai-parrot/tests/migrations/test_bots_baseline.py -q`

---

## Test Specification

- Fresh full shape/no seeds/no uuid-ossp; legacy 44 fields and missing tooling/suggestions; preserve rows; reject incompatible type/constraint or missing required identity on nonempty table; custom targets and distinct index/constraint names; usable existing UUID default retained; replay idempotence; 001 check valid after 005

---

## Agent Instructions

1. Use `$sdd-start TASK-5557` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note

Populated by the task finalizer after verified implementation.
