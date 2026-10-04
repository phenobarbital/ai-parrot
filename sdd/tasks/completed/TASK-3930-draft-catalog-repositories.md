# TASK-3930: StudioDraftRepository, StudioSkillCatalogRepository and the StudioRepositories container

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W1 — Repositories (M3, part 4: drafts, catalogue, StudioRepositories container)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3929
**Assigned-to**: unassigned

---

## Context

Spec §2.5 (`StudioDraftRepository`, `StudioSkillCatalogRepository`), §2.3 (0003 drafts with own `version` +
trigger; 0004 catalogue extended in place: content column `body`), §2.5a (drafts use the same lock/guard protocol).
`StudioRepositories` is named as the type of `StudioStorage.repos` and of the services' first argument (§2.5, §3 M4)
but never defined in the spec; it is defined here as a frozen dataclass bundling the five repositories.

---

## Scope

- `StudioDraftRepository`: `get`, `list(part, *, owner=None)`, `lock(conn, part, name, guard)`, `insert`,
  `update_bundle`, `set_status` (incl. `activated_agent_id`), `update_visibility`, `delete` — partitioned, guarded.
- `StudioSkillCatalogRepository`: `get(part, skill_id)`, `get_by_name`, `list(part, *, category=None, owner=None)`,
  `insert`, `update`, `update_visibility`, `delete`, `mark_stale`, `list_stale` (no `expected_version`).
- `@dataclass(frozen=True) class StudioRepositories(pool, agents, assets, tooling, drafts, skills)` +
  `build_studio_repositories(pool) -> StudioRepositories`.

**NOT in scope**: Draft activation transaction (service, TASK-3937); Python drafts table `studio_drafts` (unchanged legacy path).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py` | MODIFY | draft + catalogue repositories, StudioRepositories, build_studio_repositories |
| `packages/ai-parrot-server/tests/studio/storage/test_draft_catalog_repositories.py` | CREATE | real-PG draft/catalogue repository tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.models import (StudioDraftRecord, StudioSkillRecord, StudioAgentBundle,
    StudioWriteGuard, StudioNameConflict, StudioVersionConflict, StudioStaleAuthorization, StudioNotFound)  # TASK-3922
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py — existing columns of navigator.ai_skills_catalog
class SkillCatalogEntry(Model):   # :29 — skill_id :60, name :61, description :62, category :63, owner :64,
                                  #   triggers :65, body :66, version :67, status :68, search_index_stale :69
```
0004 adds `tenant`, `visibility`, `allowed_groups`; the content column is **`body`** (X1).

### Does NOT Exist
- ~~A `content` column on `ai_skills_catalog`~~ — it is `body`.
- ~~`StudioRepositories`~~ — defined here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_draft_catalog_repositories.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py#SkillCatalogEntry"
  ]
}
```

---

## Implementation Notes

- Parallelism: extends storage/repositories.py after TASK-3929 (same file); defines StudioRepositories that TASK-3931/11/12 import
- Cross-feature ordering: none (X16 early subset). FEAT-605 W2.1 uses `StudioDraftRepository.update_visibility` and
  the catalogue `update_visibility` through services (X13).
- Draft `lock` uses the same NotFound → VersionConflict → StaleAuthorization order on `ai_agent_drafts`.
- Catalogue writes never take a client `expected_version` (§2.9: 400 `expected_version_unsupported` is the handler's).
- After this task `repositories.py` holds five classes; if it exceeds 500 lines, move the catalogue repository to
  `storage/catalog_repository.py` re-exported from `repositories.py` and note it in the Completion Note.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### Steps (in order)
1. Draft repository (mirror the agent `lock`), catalogue repository, then the container.
2. Tests.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py` (MODIFY — append)
```python
class StudioDraftRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool
    # FILL IN: get / list / lock / insert / update_bundle / set_status / update_visibility / delete — partitioned
    #   on navigator.ai_agent_drafts; definition jsonb holds StudioAgentBundle.model_dump(mode="json").


class StudioSkillCatalogRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool
    # FILL IN: get / get_by_name / list / insert / update / update_visibility / delete / mark_stale / list_stale.


@dataclass(frozen=True)
class StudioRepositories:
    pool: Any
    agents: StudioAgentRepository
    assets: StudioAssetRepository
    tooling: StudioToolingRepository
    drafts: StudioDraftRepository
    skills: StudioSkillCatalogRepository


def build_studio_repositories(pool: Any) -> StudioRepositories:
    return StudioRepositories(pool, StudioAgentRepository(pool), StudioAssetRepository(pool),
                              StudioToolingRepository(pool), StudioDraftRepository(pool),
                              StudioSkillCatalogRepository(pool))
```
Add `from dataclasses import dataclass` to the imports.

### `packages/ai-parrot-server/tests/studio/storage/test_draft_catalog_repositories.py` (CREATE)
```python
"""FEAT-621 M3 — drafts and catalogue (AC6, AC7)."""
# FILL IN: test_unique_per_tenant_drafts_and_skills (incl. tenant NULL); test_partition_isolation_drafts_catalog;
#   test_draft_lock_guard_and_version_bump; test_catalog_mark_and_list_stale.
```

### FILL IN checklist
- [ ] two repositories; container; four tests.

---

## Acceptance Criteria

- [ ] `UNIQUE(tenant, name)` holds for drafts and skills, incl. tenant NULL (AC6).
- [ ] Draft and catalogue methods are partition-isolated (AC7).
- [ ] Draft writes use lock + guard and bump the draft `version`.
- [ ] `build_studio_repositories(pool)` returns the five repositories sharing one pool.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_draft_catalog_repositories.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_unique_per_tenant_drafts_and_skills` | AC6 |
| `test_partition_isolation_drafts_catalog` | AC7 |
| `test_draft_lock_guard_and_version_bump` | §2.5a drafts |
| `test_catalog_mark_and_list_stale` | §2.5 catalogue |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3930 — StudioDraftRepository, StudioSkillCatalogRepository and the StudioRepositories container`.
8. Close with `scripts/sdd/close_task.sh TASK-3930 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5)
**Date**: 2026-09-30
**Notes**: All methods implemented; 10 new real-PG tests pass (59 in storage/). Rule-4 module size: repositories.py would reach ~620 lines, so StudioDraftRepository went to storage/draft_repository.py and StudioSkillCatalogRepository to storage/catalog_repository.py (the task note allowed the latter; the draft split is the same mechanism, files not in the task's table). Both are lazily re-exported from repositories.py via module __getattr__ (they import its helpers, so an eager import would be circular) and build_studio_repositories imports them locally. Draft lock() returns StudioAgentHead with agent_id carrying the draft id (no draft head type specified). Catalogue has no version trigger, so its writes bump version/updated_at explicitly; mark_stale does not bump version. Catalogue update/update_visibility/mark_stale return None/False when the row is absent.

**Deviations from spec**: none
