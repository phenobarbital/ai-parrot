# TASK-1868: Recipe stores — AbstractRecipeStore + File + DB backends

**Feature**: FEAT-324 — Infographic Builder — Recipe-Driven, Replayable A2UI Infographics
**Spec**: `sdd/specs/infographic-builder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1865
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-324. Recipes persist in BOTH a file directory (hand-authoring) and a DB
table (SkillRegistry pattern) — both in core ai-parrot (resolved brainstorm decision).
Versioning is simple overwrite + `updated_at` bump (spec G5); history is a non-goal.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py`:
  - `AbstractRecipeStore(ABC)` with async `save`, `get`, `list`, `delete` (spec §2 New Public
    Interfaces) — `save` overwrites and sets `updated_at`; all ops accept optional `owner`
    scoping; `get` of a missing recipe raises a typed `RecipeNotFoundError` naming available
    recipes.
  - `FileRecipeStore(directory)` — one YAML file per recipe (`<name>.yaml`; owner-scoped
    subdirectories when `owner` given). Uses the TASK-1865 YAML round-trip. Path traversal in
    `name` rejected.
  - `DBRecipeStore` — CORRECTED (see Codebase Contract): persists via the SAME Redis pattern
    `SkillRegistry` actually uses (lazy `redis.asyncio` import, `REDIS_AVAILABLE` flag,
    in-memory dict fallback when Redis is absent/unconfigured), keyed by
    `(namespace, owner, name)`; NOT a relational table (no asyncdb table pattern exists in
    this codebase to copy). `configure()`-style idempotent async init, mirroring SkillRegistry.
- Contract test suite run against BOTH backends (file: tmp_path; DB: test double/fake
  connection per existing SkillRegistry test approach).
- `schema_version` mismatch on load → explicit error with guidance (spec edge case).

**NOT in scope**: runner (TASK-1869), REST exposure (TASK-1872), version history.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py` | CREATE | ABC + File + DB stores |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py` | MODIFY | export stores |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_store.py` | CREATE | shared contract suite, both backends |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.recipes.models import InfographicRecipe  # TASK-1865
import yaml                                                        # PyYAML, existing dep
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/store.py — PATTERN REFERENCE (read before implementing)
# CORRECTED 2026-07-22 (re-verified against the actual file — the original
# contract's "asyncdb-based pattern" / "a2ui_recipes table (JSONB)" claim is
# STALE: grep confirms zero `asyncdb` references anywhere in skills/store.py.
# The real persistence is Redis (redis.asyncio, lazy try/except import,
# REDIS_AVAILABLE flag) with an in-memory dict fallback, keyed by namespace.
class SkillRegistry:                       # line 120
    def __init__(self, ..., redis_url: Optional[str] = None, ...):  # line 132
    async def configure(self, ...):        # line 186 — idempotent async init:
                                            #   connects Redis (await self._redis.ping()),
                                            #   falls back to in-memory on failure, sets self._configured
    async def _persist_skill(self, skill) -> None:   # line 820 —
        # if self._use_redis: await self._redis.hset(f"skill:{namespace}:{id}", "data", json.dumps(...))
        # else: in-memory dict + optional _save_to_disk() JSON file
    async def list_skills(self, ...) -> List[Dict[str, Any]]:  # line 774 — lightweight summary dicts
# Copy its connection/config handling shape (lazy Redis import + in-memory
# fallback + idempotent configure()); do NOT import SkillRegistry into
# store.py. DBRecipeStore therefore persists via Redis (JSON payload per
# key) with an in-memory fallback when Redis is unavailable/unconfigured —
# NOT a relational "a2ui_recipes" SQL table (no such pattern exists to copy).
```

### Does NOT Exist
- ~~`AbstractRecipeStore` / `FileRecipeStore` / `DBRecipeStore`~~ — created by THIS task
- ~~An `a2ui_recipes` SQL table or migration~~ — does NOT exist and is NOT created; grep-verified
  `skills/store.py` has zero `asyncdb`/SQL-table code to copy. `DBRecipeStore` persists via
  Redis (+ in-memory fallback), matching the ACTUAL SkillRegistry mechanism.
- ~~`AbstractStore` from `parrot.stores`~~ — that ABC is for VECTOR stores
  (`parrot/stores/`, Document/SearchResult vocabulary); do NOT subclass it for recipes
- ~~SkillsDirectoryLoader reuse~~ — `parrot/skills/loader.py` loads markdown skills; the file
  store here is plain YAML-per-recipe, implemented fresh

---

## Implementation Notes

### Key Constraints
- G8 import rule still applies (this module lives inside `parrot.outputs.a2ui`): no
  DatasetManager/agents/LLM-client imports. DB access via the same driver stack SkillRegistry
  uses is acceptable — keep the import lazy/optional so `FileRecipeStore` works without DB
  extras installed.
- `save()` sets `updated_at = datetime.now(timezone.utc)` on the stored copy (single source
  of truth for overwrite semantics — TASK-1865 models do not auto-set it).
- `list()` returns lightweight dicts (name, title, description, owner, updated_at), NOT full
  recipes — the REST handler and chat tool paginate on this.
- File store must be safe for concurrent same-name saves (write-to-temp + atomic rename).
- Async throughout (`aiofiles` not required — `asyncio.to_thread` for file I/O is acceptable
  and dependency-free; be consistent).

### References in Codebase
- `packages/ai-parrot/src/parrot/skills/store.py` — DB persistence + configure pattern
- `sdd/specs/infographic-builder.spec.md` §2 New Public Interfaces — normative store API

---

## Acceptance Criteria

- [ ] One shared contract test suite passes against BOTH backends
      (`test_file_store_crud_and_owner_scope`, `test_db_store_crud`)
- [ ] Overwrite bumps `updated_at`; no version rows/files accumulate
- [ ] Owner scoping isolates recipes; missing recipe → `RecipeNotFoundError` with available names
- [ ] Path traversal in recipe name rejected (file backend)
- [ ] `schema_version` mismatch produces explicit guidance error
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/test_store.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/recipes/test_store.py
import pytest

@pytest.fixture(params=["file", "db"])
def store(request, tmp_path): ...   # parametrized: FileRecipeStore(tmp_path) | DBRecipeStore(fake)

class TestRecipeStoreContract:
    async def test_save_get_roundtrip(self, store, sample_recipe): ...
    async def test_overwrite_bumps_updated_at(self, store, sample_recipe): ...
    async def test_owner_scope_isolation(self, store, sample_recipe): ...
    async def test_missing_recipe_lists_available(self, store): ...
    async def test_delete(self, store, sample_recipe): ...

async def test_file_store_rejects_path_traversal(tmp_path): ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/infographic-builder.spec.md`
2. **Check dependencies** — TASK-1865 completed; read its real models
3. **Verify the Codebase Contract** — especially read `parrot/skills/store.py` before the DB backend
4. **Update status** in `sdd/tasks/index/infographic-builder.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
