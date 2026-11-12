# TASK-5559: Retire converted scripts and preserve manual operations

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5557, TASK-5558
**Assigned-to**: unassigned


---

## Context

Finish M3 conversion: remove the eight superseded scripts only after their packaged equivalents exist; split manual users_bots embedding and lossy language reset; update bootstrap guidance and exact sanctioned freeze rewrites.

---

## Scope

Finish M3 conversion: remove the eight superseded scripts only after their packaged equivalents exist; split manual users_bots embedding and lossy language reset; update bootstrap guidance and exact sanctioned freeze rewrites.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes packaged 001 baseline from TASK-5557 and 002–005 successors from TASK-5558 before retiring historical sources.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/migrations/ai-bots-homologate-botmodel.sql` | MODIFY | REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement. |
| `sdd/migrations/FEAT-add-prompt-config-ai-bots.sql` | MODIFY | REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement. |
| `sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql` | MODIFY | REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement. |
| `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` | MODIFY | REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement. |
| `sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql` | MODIFY | REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement. |
| `sdd/migrations/FEAT-fold-legacy-llm-columns.sql` | MODIFY | REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement. |
| `sdd/migrations/FEAT-fix-stale-bot-tool-names.sql` | MODIFY | REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement. |
| `sdd/migrations/FEAT-638-bot-language-nullable.sql` | MODIFY | REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement. |
| `sdd/migrations/users-bots-fold-embedding.sql` | CREATE | Preserve separate operator-run embedding migration; missing table/source column is safe, explicit destination keys win. |
| `sdd/migrations/manual-bot-language-reset.sql` | CREATE | Keep original users_bots schema/data operation and both explicit resets available; explain backups and intentional English values lost. |
| `sdd/migrations/botmodel-recreate-table.sql` | MODIFY | Retain destructive SQL unchanged, add explicit manual/destructive warning and parrot self migration upgrade pointer. |
| `packages/ai-parrot-server/src/parrot/handlers/creation.sql` | MODIFY | Retain fresh-install-only warning; replace obsolete pointers with parrot self migration upgrade; add five FEAT-752 suggestion fields with exact defaults, update 44-field count to 49. Preserve unrelated bootstrap content. |
| `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` | MODIFY | Append exact old/new text tuples for the creation.sql changes; do not weaken any gate, accepted scope, or frozen BotModel/loader checks. |
| `packages/ai-parrot/tests/migrations/test_legacy_conversion.py` | CREATE | All eight superseded files removed only after equivalents exist; manual scripts guarded and excluded from wheel sets; automatic SQL contains no users_bots or lossy reset; bootstrap five suggestion fields and command pointer; recreate file warning retained |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `sdd/migrations/ai-bots-homologate-botmodel.sql` — anchor at line 2, one exact occurrence: `-- Homologate navigator.ai_bots with parrot.models.bots.BotModel`
- `sdd/migrations/FEAT-add-prompt-config-ai-bots.sql` — anchor at line 2, one exact occurrence: `-- Add prompt_config to navigator.ai_bots`
- `sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql` — anchor at line 1, one exact occurrence: `-- FEAT-593 (TASK-3652): Agent Studio tooling columns on navigator.ai_bots.`
- `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` — anchor at line 1, one exact occurrence: `-- FEAT-752 (TASK-4811): follow-up suggestion chip settings on navigator.ai_bots (Agent Studio).`
- `sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql` — anchor at line 2, one exact occurrence: `-- Fold embedding_model into vector_store_config / vector_config`
- `sdd/migrations/FEAT-fold-legacy-llm-columns.sql` — anchor at line 2, one exact occurrence: `-- Fold legacy LLM-tuning columns into model_config`
- `sdd/migrations/FEAT-fix-stale-bot-tool-names.sql` — anchor at line 2, one exact occurrence: `-- Remap stale bot tool names to canonical TOOL_REGISTRY keys`
- `sdd/migrations/FEAT-638-bot-language-nullable.sql` — anchor at line 1, one exact occurrence: `-- FEAT-638: bot-level output language — `language` becomes nullable with no default.`
- `sdd/migrations/botmodel-recreate-table.sql` — anchor at line 1, one exact occurrence: `-- Recreate navigator.ai_bots (BotModel) from scratch.`
- `packages/ai-parrot-server/src/parrot/handlers/creation.sql` — anchor at line 1, one exact occurrence: `-- WARNING: Initial setup DDL only. DO NOT run against production.`
- `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` — anchor at line 148, one exact occurrence: `_SANCTIONED_REWRITES: tuple[tuple[str, str], ...] = (`

### Dependency interfaces

- `TASK-5557` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5558` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.

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
      "path": "sdd/migrations/ai-bots-homologate-botmodel.sql",
      "action": "MODIFY"
    },
    {
      "path": "sdd/migrations/FEAT-add-prompt-config-ai-bots.sql",
      "action": "MODIFY"
    },
    {
      "path": "sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql",
      "action": "MODIFY"
    },
    {
      "path": "sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql",
      "action": "MODIFY"
    },
    {
      "path": "sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql",
      "action": "MODIFY"
    },
    {
      "path": "sdd/migrations/FEAT-fold-legacy-llm-columns.sql",
      "action": "MODIFY"
    },
    {
      "path": "sdd/migrations/FEAT-fix-stale-bot-tool-names.sql",
      "action": "MODIFY"
    },
    {
      "path": "sdd/migrations/FEAT-638-bot-language-nullable.sql",
      "action": "MODIFY"
    },
    {
      "path": "sdd/migrations/users-bots-fold-embedding.sql",
      "action": "CREATE"
    },
    {
      "path": "sdd/migrations/manual-bot-language-reset.sql",
      "action": "CREATE"
    },
    {
      "path": "sdd/migrations/botmodel-recreate-table.sql",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/creation.sql",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/migrations/test_legacy_conversion.py",
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

### `sdd/migrations/ai-bots-homologate-botmodel.sql` (MODIFY)

```sql
# Anchor (exact full line): -- Homologate navigator.ai_bots with parrot.models.bots.BotModel
# occurrences: 1; verified at sdd/migrations/ai-bots-homologate-botmodel.sql:2
# FILL IN: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
```

**Why**: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.

---

### `sdd/migrations/FEAT-add-prompt-config-ai-bots.sql` (MODIFY)

```sql
# Anchor (exact full line): -- Add prompt_config to navigator.ai_bots
# occurrences: 1; verified at sdd/migrations/FEAT-add-prompt-config-ai-bots.sql:2
# FILL IN: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
```

**Why**: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.

---

### `sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql` (MODIFY)

```sql
# Anchor (exact full line): -- FEAT-593 (TASK-3652): Agent Studio tooling columns on navigator.ai_bots.
# occurrences: 1; verified at sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql:1
# FILL IN: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
```

**Why**: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.

---

### `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` (MODIFY)

```sql
# Anchor (exact full line): -- FEAT-752 (TASK-4811): follow-up suggestion chip settings on navigator.ai_bots (Agent Studio).
# occurrences: 1; verified at sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql:1
# FILL IN: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
```

**Why**: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.

---

### `sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql` (MODIFY)

```sql
# Anchor (exact full line): -- Fold embedding_model into vector_store_config / vector_config
# occurrences: 1; verified at sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql:2
# FILL IN: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
```

**Why**: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.

---

### `sdd/migrations/FEAT-fold-legacy-llm-columns.sql` (MODIFY)

```sql
# Anchor (exact full line): -- Fold legacy LLM-tuning columns into model_config
# occurrences: 1; verified at sdd/migrations/FEAT-fold-legacy-llm-columns.sql:2
# FILL IN: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
```

**Why**: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.

---

### `sdd/migrations/FEAT-fix-stale-bot-tool-names.sql` (MODIFY)

```sql
# Anchor (exact full line): -- Remap stale bot tool names to canonical TOOL_REGISTRY keys
# occurrences: 1; verified at sdd/migrations/FEAT-fix-stale-bot-tool-names.sql:2
# FILL IN: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
```

**Why**: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.

---

### `sdd/migrations/FEAT-638-bot-language-nullable.sql` (MODIFY)

```sql
# Anchor (exact full line): -- FEAT-638: bot-level output language — `language` becomes nullable with no default.
# occurrences: 1; verified at sdd/migrations/FEAT-638-bot-language-nullable.sql:1
# FILL IN: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
```

**Why**: REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.

---

### `sdd/migrations/users-bots-fold-embedding.sql` (CREATE)

```sql
-- Manual users_bots embedding fold; not part of any packaged set.
-- FILL IN: preserve legacy vector_config backfill/normalization with relation and per-column guards.
```

**Why**: Preserve separate operator-run embedding migration; missing table/source column is safe, explicit destination keys win.

---

### `sdd/migrations/manual-bot-language-reset.sql` (CREATE)

```sql
-- MANUAL, LOSSY: intentionally clears language=en on ai_bots and users_bots.
-- Never run automatically through parrot self migration.
-- FILL IN: preserve historical FEAT-638 operations with relation/column guards.
```

**Why**: Keep original users_bots schema/data operation and both explicit resets available; explain backups and intentional English values lost.

---

### `sdd/migrations/botmodel-recreate-table.sql` (MODIFY)

```sql
# Anchor (exact full line): -- Recreate navigator.ai_bots (BotModel) from scratch.
# occurrences: 1; verified at sdd/migrations/botmodel-recreate-table.sql:1
# FILL IN: Retain destructive SQL unchanged, add explicit manual/destructive warning and parrot self migration upgrade pointer.
```

**Why**: Retain destructive SQL unchanged, add explicit manual/destructive warning and parrot self migration upgrade pointer.

---

### `packages/ai-parrot-server/src/parrot/handlers/creation.sql` (MODIFY)

```sql
# Anchor (exact full line): -- WARNING: Initial setup DDL only. DO NOT run against production.
# occurrences: 1; verified at packages/ai-parrot-server/src/parrot/handlers/creation.sql:1
# FILL IN: Retain fresh-install-only warning; replace obsolete pointers with parrot self migration upgrade; add five FEAT-752 suggestion fields with exact defaults, update 44-field count to 49. Preserve unrelated bootstrap content.
```

**Why**: Retain fresh-install-only warning; replace obsolete pointers with parrot self migration upgrade; add five FEAT-752 suggestion fields with exact defaults, update 44-field count to 49. Preserve unrelated bootstrap content.

---

### `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` (MODIFY)

```python
# Anchor (exact full line): _SANCTIONED_REWRITES: tuple[tuple[str, str], ...] = (
# occurrences: 1; verified at packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py:148
# FILL IN: Append exact old/new text tuples for the creation.sql changes; do not weaken any gate, accepted scope, or frozen BotModel/loader checks.
```

**Why**: Append exact old/new text tuples for the creation.sql changes; do not weaken any gate, accepted scope, or frozen BotModel/loader checks.

---

### `packages/ai-parrot/tests/migrations/test_legacy_conversion.py` (CREATE)

```python
"""All eight superseded files removed only after equivalents exist."""
from __future__ import annotations

import pytest


def test_legacy_conversion_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: All eight superseded files removed only after equivalents exist; manual scripts guarded and excluded from wheel sets; automatic SQL contains no users_bots or lossy reset; bootstrap five suggestion fields and command pointer; recreate file warning retained

---

### FILL IN checklist

- [ ] `sdd/migrations/ai-bots-homologate-botmodel.sql` — REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
- [ ] `sdd/migrations/FEAT-add-prompt-config-ai-bots.sql` — REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
- [ ] `sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql` — REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
- [ ] `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` — REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
- [ ] `sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql` — REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
- [ ] `sdd/migrations/FEAT-fold-legacy-llm-columns.sql` — REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
- [ ] `sdd/migrations/FEAT-fix-stale-bot-tool-names.sql` — REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
- [ ] `sdd/migrations/FEAT-638-bot-language-nullable.sql` — REMOVE this file after checking its operations are represented in packaged bots SQL or the explicit split manual scripts. MODIFY denotes retirement of an existing tracked file in the complexity schema; do not leave an empty replacement.
- [ ] `sdd/migrations/users-bots-fold-embedding.sql` — Preserve separate operator-run embedding migration; missing table/source column is safe, explicit destination keys win.
- [ ] `sdd/migrations/manual-bot-language-reset.sql` — Keep original users_bots schema/data operation and both explicit resets available; explain backups and intentional English values lost.
- [ ] `sdd/migrations/botmodel-recreate-table.sql` — Retain destructive SQL unchanged, add explicit manual/destructive warning and parrot self migration upgrade pointer.
- [ ] `packages/ai-parrot-server/src/parrot/handlers/creation.sql` — Retain fresh-install-only warning; replace obsolete pointers with parrot self migration upgrade; add five FEAT-752 suggestion fields with exact defaults, update 44-field count to 49. Preserve unrelated bootstrap content.
- [ ] `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` — Append exact old/new text tuples for the creation.sql changes; do not weaken any gate, accepted scope, or frozen BotModel/loader checks.
- [ ] `packages/ai-parrot/tests/migrations/test_legacy_conversion.py` — All eight superseded files removed only after equivalents exist; manual scripts guarded and excluded from wheel sets; automatic SQL contains no users_bots or lossy reset; bootstrap five suggestion fields and command pointer; recreate file warning retained
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

- `pytest packages/ai-parrot/tests/migrations/test_legacy_conversion.py -q`
- `pytest packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py -q`

---

## Test Specification

- Append exact old/new text tuples for the creation.sql changes; do not weaken any gate, accepted scope, or frozen BotModel/loader checks.
- All eight superseded files removed only after equivalents exist; manual scripts guarded and excluded from wheel sets; automatic SQL contains no users_bots or lossy reset; bootstrap five suggestion fields and command pointer; recreate file warning retained

---

## Agent Instructions

1. Use `$sdd-start TASK-5559` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note

Populated by the task finalizer after verified implementation.
