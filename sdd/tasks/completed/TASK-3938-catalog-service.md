# TASK-3938: StudioSkillCatalogService, catalogue model tenancy fields and derived index location

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Draft + catalogue services (M6, part 2: StudioSkillCatalogService + model fields)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3936
**Assigned-to**: unassigned

---

## Context

Spec §2.5 (`StudioSkillCatalogService`: publish / update / update_visibility / delete / list / import_to_agent),
§2.8 row `skills_catalog.py` (the shared `SkillRegistry` becomes a derived per-pod search index: namespace
`<tenant or org_id>/_shared`, persistence path `STUDIO_RUNTIME_DIR/_shared/<partition>/skills`, never `AGENTS_DIR`),
Q3, X1 (column `body`).

---

## Scope

- `services/catalog.py` `StudioSkillCatalogService(repos, *, assets)`: `publish`, `update`, `update_visibility`,
  `delete`, `list(category=, owner=)`, `get`, `import_to_agent(part, skill_id, agent_name, *, actor, guard)`
  (asset row under the agent lock via `StudioAssetService.put`), `mark_stale`/`list_stale`, and
  `shared_index_location(part, org_id) -> tuple[str, Path]` (namespace + persistence dir).
- `handlers/models/skills_catalog.py`: add `tenant`, `visibility`, `allowed_groups` fields and update the docstring
  DDL to match 0004.

**NOT in scope**: Handler switch and the registry rebuild/resync wiring (TASK-3948).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/catalog.py` | CREATE | StudioSkillCatalogService + shared_index_location |
| `packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py` | MODIFY | three tenancy fields + docstring DDL |
| `packages/ai-parrot-server/tests/studio/storage/test_catalog_service.py` | CREATE | catalogue service tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.services.assets import StudioAssetService   # TASK-3936
from parrot.handlers.models.skills_catalog import SkillCatalogEntry             # skills_catalog.py:29
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py
    search_index_stale: bool = Field(required=False, default=False)   # line 69 (occurrences: 1) ← anchor
# packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py
def _shared_namespace(org_id: str) -> str                             # :46
def _get_shared_skill_registry(app: Any, org_id: str)                 # :51 (handler-side; changed in TASK-3948)
```

### Does NOT Exist
- ~~`STUDIO_RUNTIME_DIR`~~ config key — new; resolve it only through `studio_runtime_dir()` from
  `services/_common.py` (TASK-3933), the same helper the runtime uses.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/catalog.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_catalog_service.py",
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

- Parallelism: import_to_agent writes the asset through StudioAssetService from TASK-3936 (services/assets.py); creates services/catalog.py; sole FEAT-621 writer of handlers/models/skills_catalog.py
- Cross-feature ordering: X16 "Cross-spec waits" — STORAGE W2 needs TOOLKITS Wave 1 merged (asset writes go through
  the gate). FEAT-605 W4.1 (`PATCH /skills/{id}/visibility`) persists through `update_visibility` (X13).
- Name uniqueness per partition comes from the DB (`StudioNameConflict`); the 409 code mapping is the handler's
  (`duplicate` only as pre-merge state, final `name_taken`, X14).

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
1. Model fields; 2. service; 3. tests.

### `packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    search_index_stale: bool = Field(required=False, default=False)' skills_catalog.py)
# AFTER — insert below `    search_index_stale: bool = Field(required=False, default=False)` (verified: :69)
    tenant: Optional[str] = Field(required=False, default=None)
    visibility: str = Field(required=False, default="private")
    allowed_groups: list = Field(required=False, default_factory=list)
# FILL IN: update the class docstring DDL to the 0004 columns/constraints; check `Optional` is imported.
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/catalog.py` (CREATE)
```python
"""StudioSkillCatalogService (spec §2.5): partitioned catalogue + derived per-pod search index location."""
class StudioSkillCatalogService:
    def __init__(self, repos: StudioRepositories, *, assets: StudioAssetService) -> None:
        self._repos, self._assets = repos, assets

    async def import_to_agent(self, part: StudioPartition, skill_id: UUID, agent_name: str, *, actor: str | None,
                              guard: StudioWriteGuard) -> tuple[StudioAssetRecord, int]:
        # FILL IN: get skill in partition (None → StudioNotFound); compose the SKILL.md text the same way
        #   skills_catalog._compose_skill_markdown does (:99 — import it lazily, do not duplicate); assets.put(...).
        raise NotImplementedError
    # FILL IN: publish, update, update_visibility, delete, list, get, mark_stale, list_stale, shared_index_location.
```

### `packages/ai-parrot-server/tests/studio/storage/test_catalog_service.py` (CREATE)
```python
"""FEAT-621 M6 — catalogue (AC4, AC6, AC7)."""
# FILL IN: test_publish_unique_per_partition; test_import_to_agent_writes_asset_row_under_lock;
#   test_shared_index_location_not_in_agents_dir; test_update_visibility_tenant_null_private_only.
```

### FILL IN checklist
- [ ] model fields + docstring; service methods; four tests.

---

## Acceptance Criteria

- [ ] Skill names unique per partition, incl. tenant NULL (AC6).
- [ ] Import-to-agent writes an `ai_agent_assets` row under the agent lock, nothing under `AGENTS_DIR` (AC4).
- [ ] Derived index location is under `STUDIO_RUNTIME_DIR/_shared/<partition>/skills`, never `AGENTS_DIR`.
- [ ] `SkillCatalogEntry` carries `tenant`, `visibility`, `allowed_groups`.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_catalog_service.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_publish_unique_per_partition` | AC6 |
| `test_import_to_agent_writes_asset_row_under_lock` | AC4 |
| `test_shared_index_location_not_in_agents_dir` | §2.8 |
| `test_update_visibility_tenant_null_private_only` | X1 CHECK |

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
   `feat(agentstudio-db-storage): TASK-3938 — StudioSkillCatalogService, catalogue model tenancy fields and derived index location`.
8. Close with `scripts/sdd/close_task.sh TASK-3938 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sonnet)
**Date**: 2026-10-01
**Notes**: services/catalog.py StudioSkillCatalogService (publish/update/update_visibility/delete/get/list/mark_stale/list_stale/import_to_agent via StudioAssetService.put as skills/<name>.md under the agent lock) + shared_index_location (namespace <tenant or org_id>/_shared, dir STUDIO_RUNTIME_DIR/_shared/<tenant or ->/skills via studio_runtime_dir, refuses AGENTS_DIR). models/skills_catalog.py: tenant/visibility/allowed_groups fields + 0004 DDL docstring. 14 tests (memory+postgres) pass; mutations RED: visibility validation, tenant-namespace, asset name. Existing studio test_scaffold/test_integration/test_skills_catalog: no new failures vs baseline.

**Deviations from spec**: none
