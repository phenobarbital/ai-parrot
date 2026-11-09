# TASK-5452: Documentation — crew-definition-storage and crew_handler

**Feature**: FEAT-860 — Postgres CrewDefinition Storage
**Spec**: `sdd/specs/postgres-crew-storage.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1–2h)
**Depends-on**: TASK-5443, TASK-5444, TASK-5445, TASK-5446, TASK-5448, TASK-5449, TASK-5450
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.2 contracts for documentation — crew-definition-storage and crew_handler.
Spec §§2–5 are authoritative; §6 records baseline source, not old error-policy requirements.
This task is part of the four review resolutions recorded in spec §9.

## Scope

- Inspect completed prerequisite APIs before writing examples — documentation must describe final contracts.
- Create the storage page from the techwiki template and update the handler page — exactly one task owns required wiki documentation.
- Correct both persistence READMEs — stale keys and best-effort claims would mislead operators.
- Run techwiki check and verify API references — declared pages and symbols must be traceable.
- Add a scoped pytest adapter executing parrot sdd techwiki check --spec sdd/specs/postgres-crew-storage.spec.md --root . and verifying pages/output — the graph cannot dispatch the advisory CLI directly.

**NOT in scope**: files outside the table; changing CrewDefinition model fields, execution-result storage,
creation.sql, _load_database_bots, dependency manifests or introducing new services.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/bots/orchestration/crew-definition-storage.md` | CREATE | Use sdd/templates/techwiki-page.md structure with actual implemented API links. |
| `wiki/bots/crew_handler.md` | MODIFY | Handler consumers must understand the changed failure contract. |
| `packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md` | MODIFY | The current README incorrectly describes pre-tenant keys and unconditional best-effort semantics. |
| `packages/ai-parrot-server/src/parrot/handlers/crew/README_REDIS_PERSISTENCE.md` | MODIFY | Operators must understand why failed/conflicting sources remain in Redis. |
| `packages/ai-parrot-server/tests/unit/test_crew_definition_docs.py` | CREATE | Run the exact required techwiki command in the repository root; verify both declared pages have title/summary and no missing-page output. Exit zero alone is insufficient for this advisory CLI. |

## Codebase Contract (Anti-Hallucination)

Verified at `0cfa595cb2` on `dev`; re-check after dependencies land.

### Verified Imports

```python
import pytest
import subprocess
from pathlib import Path
```

Standard-library imports resolve under the project Python runtime; pytest/Pydantic/asyncdb are already declared in workspace pyproject.toml files. Crew model re-exports are verified in handlers/crew/models.py:17–23. Relative imports of new modules in blueprints are dependency contracts below, not claims of pre-existing code.

### Existing Signatures to Use

- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis` — `class CrewRedis:` (packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:17).
- `sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager` — `class BotManager:` (packages/ai-parrot-server/src/parrot/manager/manager.py:217).
- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler` — `class CrewHandler(BaseView):` (packages/ai-parrot-server/src/parrot/handlers/crew/handler.py:27).

### Dependency Imports and New Symbols

Documents codec from TASK-5443, config from TASK-5444, Redis snapshots from TASK-5445, PG APIs from TASK-5446, migration/composition from TASK-5448, manager API from TASK-5449 and HTTP behavior from TASK-5450.

Exact blueprint imports (stdlib/existing references above; new symbols require the named prerequisite):

```python
from __future__ import annotations
from pathlib import Path
import pytest
import subprocess
```
Blueprint imports from `definition_codec`, `postgres_persistence`, `definition_storage`, and new Redis types are permitted only after their producer task completes; inspect those exact declarations before implementation. New symbols defined by this task are declared in its blueprint.

### Does NOT Exist

- wiki/bots/orchestration/crew-definition-storage.md is absent before this task.
- No new storage configuration should be invented in documentation.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/bots/orchestration/crew-definition-storage.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/bots/crew_handler.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/crew/README_REDIS_PERSISTENCE.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_crew_definition_docs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler"
  ]
}
```

## Implementation Notes

Use async I/O, Pydantic v2 models, strict type hints and Google-style docstrings. Format with black (120 columns); lint with ruff. No new dependencies. Logs belong under artifacts/logs/.

## Implementation Blueprint

### Steps (in order)

1. Inspect completed prerequisite APIs before writing examples — documentation must describe final contracts.
2. Create the storage page from the techwiki template and update the handler page — exactly one task owns required wiki documentation.
3. Correct both persistence READMEs — stale keys and best-effort claims would mislead operators.
4. Run techwiki check and verify API references — declared pages and symbols must be traceable.
5. Add a scoped pytest adapter executing parrot sdd techwiki check --spec sdd/specs/postgres-crew-storage.spec.md --root . and verifying pages/output — the graph cannot dispatch the advisory CLI directly.

### `wiki/bots/orchestration/crew-definition-storage.md` (CREATE)

```markdown
---
title: Crew Definition Storage
summary: Postgres authority, Redis fallback, tombstones and safe crew migration.
---
# Crew Definition Storage
## Purpose
<!-- FILL IN: definitions versus execution results; opt-in default. -->
## Public API
- [`CrewPostgres`](ref:parrot.handlers.crew.postgres_persistence.CrewPostgres)
- [`CrewDefinitionStorage`](ref:parrot.handlers.crew.definition_storage.CrewDefinitionStorage)
- [`crew_definition_from_dict`](ref:parrot.handlers.crew.definition_codec.crew_definition_from_dict)
## Configuration & Parameters
<!-- FILL IN: three configuration keys and manager overrides from implementation. -->
## Usage Examples
<!-- FILL IN: env-based setup, verified dry-run/migration APIs, report interpretation. -->
## Gotchas
<!-- FILL IN: fail closed, both identity keys, tombstones, retained conflicts,
rename rejection, upgraded workers, single-instance Redis and live safety gate. -->
## Related
- [Crew handler](../crew_handler.md)
```

**Why**: Use sdd/templates/techwiki-page.md structure with actual implemented API links.

### `wiki/bots/crew_handler.md` (MODIFY)

```markdown
# Anchor: The key is never stored in a `CrewDefinition`, so it never reaches Redis and never appears in `GET /api/v1/crew`, and it is never logged.
# occurrences: 1; verified wiki/bots/crew_handler.md:602 at 0cfa595cb2
# Replace the persistence note to say crew definition storage (Redis or Postgres).
# FILL IN: add template title/summary frontmatter; retain the no-secret-persistence
# guarantee; document 503/409, tombstone
# retries and PG update/rename behavior; link the new storage page.
```

**Why**: Handler consumers must understand the changed failure contract.

### `packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md` (MODIFY)

```markdown
# Anchor: ## Key Format
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md:32 at 0cfa595cb2
# Anchor: ## Migration
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md:256 at 0cfa595cb2
# Replace Key Format and revise Migration plus add/get/remove descriptions.
# FILL IN: tenant:name keys, Postgres authority, persistence-before-cache, retry
# semantics, retained conflicts and environment configuration. Keep Redis-only defaults clear.
```

**Why**: The current README incorrectly describes pre-tenant keys and unconditional best-effort semantics.

### `packages/ai-parrot-server/src/parrot/handlers/crew/README_REDIS_PERSISTENCE.md` (MODIFY)

```markdown
# Anchor: ## Key Format
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/handlers/crew/README_REDIS_PERSISTENCE.md:161 at 0cfa595cb2
# Replace Key Format and document legacy-global fallback, strict helpers,
# captured snapshots and conditional cleanup; distinguish Redis-only best effort
# from Postgres-mode read-only source semantics. Never recommend unconditional cleanup.
```

**Why**: Operators must understand why failed/conflicting sources remain in Redis.

### `packages/ai-parrot-server/tests/unit/test_crew_definition_docs.py` (CREATE)

```python
"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""
from __future__ import annotations
import pytest
import subprocess
from pathlib import Path

def test_required_crew_documentation() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError
```

**Why**: Run the exact required techwiki command in the repository root; verify both declared pages have title/summary and no missing-page output. Exit zero alone is insufficient for this advisory CLI.

### FILL IN checklist

- [ ] `wiki/bots/orchestration/crew-definition-storage.md` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `wiki/bots/crew_handler.md` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/src/parrot/handlers/crew/README_BOTMANAGER_PERSISTENCE.md` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/src/parrot/handlers/crew/README_REDIS_PERSISTENCE.md` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/tests/unit/test_crew_definition_docs.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] Replace all blueprint gaps with complete working code/tests; no placeholders in implementation files.

## Acceptance Criteria

- [ ] AC1: Both required wiki pages exist and reference actual implemented APIs with the techwiki template structure.
- [ ] AC2: Both READMEs show tenant-scoped keys and legacy global behavior.
- [ ] AC3: Explain fail-closed outages, 503/409, tombstones, no auto-purge, same-name-only updates and operator reconciliation.
- [ ] AC4: Examples use environment configuration, disclose service prerequisites and never claim skipped live tests proved safety.
- [ ] AC5: Run the required spec documentation check and resolve missing pages; no implementation edits.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_crew_definition_docs.py -q`

## Test Specification

Each test block above is an executor starting point, not an implementation. Build fixtures locally in the declared test files; do not modify shared conftest.py. Assert observable state and error behavior from every acceptance criterion. Avoid network/LLM calls except the explicitly gated live tests in TASK-5451.

### Required Documentation Validation

- `parrot sdd techwiki check --spec sdd/specs/postgres-crew-storage.spec.md --root .`

Run directly and through the scoped pytest adapter; assert no missing pages, not just exit zero.

## Agent Instructions

Implement in the feature worktree provisioned by sdd-start, never on dev. Check the dependency states
in `sdd/tasks/index/postgres-crew-storage.json` first. Verify source anchors and dependency-created APIs before editing.
Complete only declared files, run narrow validation commands, and commit scoped code. Finalize with
`parrot sdd task finalize` and real TaskCompletionEvidence for the implementation HEAD; do not manually
move the task, stamp completion, or run legacy task-close helpers.

## Completion Note


- Task: TASK-5452
- Feature: postgres-crew-storage
- Implementation SHA: 46a0487b8f65c86cde3ecdfc0790d9c888c5a312
- Closed at (UTC): 2026-11-09T22:21:10+00:00
- Fix commits: 46a0487b8f65c86cde3ecdfc0790d9c888c5a312

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 315.202s · Tokens: n/a |
| validation_note | The attached validation log is the pre-fix merge-tier run (3 passed). The docs fix touched one Markdown bullet and the selector then reported the target as cached, so the docs test was re-run directly against the fixed page: 3 passed. |
