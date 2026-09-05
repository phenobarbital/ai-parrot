# TASK-2870: `PgRecipeStore` — relational `AbstractRecipeStore` beside `PgUISurfaceStore`

**Feature**: FEAT-528 — Postgres recipe store + agent-package importability
**Spec**: `sdd/specs/pg-recipe-store-and-agent-package-importability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. `AbstractRecipeStore` has two implementations: `FileRecipeStore` (YAML on disk) and `DBRecipeStore` (Redis, despite the name — its docstring says "There is no relational table here"). A recipe therefore cannot live next to the `navigator.ui_surfaces` rows it produces. This task adds the third store, mirroring `PgUISurfaceStore` line for line: same constructor shape, same lazy `_ensure_ready()` / `ensure_schema()`, same `navigator` schema, same `AsyncDB("pg", dsn=...)` per-call idiom.

Placement decided by Juan (spec §8): **ai-parrot-server, beside its twin** — `packages/ai-parrot-server/src/parrot/handlers/models/recipes.py`. The downstream consumer (FieldSync FEAT-559) imports `from parrot.handlers.models.recipes import PgRecipeStore`; do not put it anywhere else.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/handlers/models/recipes.py` with `class PgRecipeStore(AbstractRecipeStore)`.
- `__init__(self, dsn: str | None = None, *, schema: str = "navigator")`; `self.dsn = dsn or default_dsn`; `self._schema_ensured = False`.
- DDL (spec §2 Data Models) as `_ddl_statements(schema)` → `CREATE TABLE IF NOT EXISTS {schema}.infographic_recipes (...)` + `CREATE INDEX IF NOT EXISTS ix_infographic_recipes_owner ...`. Identifier-quote nothing dynamic except `schema`, which must match `^[A-Za-z_][A-Za-z0-9_]*$` or raise `ValueError`.
- `ensure_schema()` idempotent and race-tolerant (copy the "already exists" tolerance from `PgUISurfaceStore.ensure_schema`, `models/ui_surfaces.py:335-353`).
- `save(recipe)`: upsert on `(name, owner)` with `owner = recipe.owner or ""`; write `schema_version`, `title`, `description`, `recipe = recipe.model_dump(mode="json")`, `updated_at = NOW()`.
- `get(name, owner=None)`: `RecipeNotFoundError(name, available)` when absent; otherwise `_load_and_migrate(row["recipe"], name_for_error=name)` then `_check_schema_version(...)` — the same gate the other stores run.
- `list(owner=None)`: summaries `{name, title, description, owner, updated_at}` from the denormalised columns only, no JSON deserialisation.
- `delete(name, owner=None)`: `RecipeNotFoundError` when absent (parity with the siblings).
- `_raw_schema_version(name, owner=None)`: read the column, not the JSON.
- Export from `parrot/handlers/models/__init__.py` (add to the existing re-export list).
- Unit tests against the scratch Postgres fixture.

**NOT in scope**: any change to `AbstractRecipeStore`, `FileRecipeStore`, `DBRecipeStore`; the transformer loader (TASK-2871); flex imports (TASK-2872); integration tests through `RecipeRunner`/`register_recipe_routes` (TASK-2873); docs (TASK-2874).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/models/recipes.py` | CREATE | `PgRecipeStore` |
| `packages/ai-parrot-server/src/parrot/handlers/models/__init__.py` | MODIFY | re-export `PgRecipeStore` |
| `tests/unit/handlers/test_pg_recipe_store.py` | CREATE | store unit tests (Postgres-backed, `integration`-marked, skipped without `NAVIGATOR_PG_DSN`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from asyncdb import AsyncDB                                   # models/ui_surfaces.py:28
from parrot.conf import default_dsn                           # models/ui_surfaces.py:29
from parrot.outputs.a2ui.recipes.store import (
    AbstractRecipeStore,          # packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py:175
    RecipeNotFoundError,          # :67   __init__(self, name: str, available: list[str])  :75
    RecipeSchemaVersionError,     # :81   __init__(self, name: str, found_version: int)   :89
    _check_schema_version,        # :116  bounds-check 1..SUPPORTED_SCHEMA_VERSION (=2, :62)
    _load_and_migrate,            # :123  (raw: dict, *, name_for_error: str) -> InfographicRecipe ; v1 layout auto-migrated
)
from parrot.outputs.a2ui.recipes.models import InfographicRecipe   # models.py:235
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py
class AbstractRecipeStore(ABC):                                   # :175
    async def save(self, recipe: InfographicRecipe) -> None                                  # :184
    async def get(self, name: str, owner: Optional[str] = None) -> InfographicRecipe         # :190
    async def list(self, owner: Optional[str] = None) -> list[dict[str, Any]]               # :200  "name/title/description/owner/updated_at"
    async def delete(self, name: str, owner: Optional[str] = None) -> None                  # :206
    async def _raw_schema_version(self, name: str, owner: Optional[str] = None) -> int      # :215
class FileRecipeStore(AbstractRecipeStore):  # :230  — reference for error parity (get :264, delete :291, _available_names :297)
class DBRecipeStore(AbstractRecipeStore):    # :304  — Redis; reference for owner-or-"" keying (:351-426)

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py:235
class InfographicRecipe(BaseModel):
    schema_version: int = 2 ; name: str ; title: str ; description: Optional[str] = None
    owner: Optional[str] = None ; params ; data_sources ; transforms ; layout ; render ; schedule
    updated_at: datetime ; section_descriptor ; narrative

# THE TEMPLATE — packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py
_DDL_STATEMENTS: list[str]                                        # :88
class PgUISurfaceStore:                                           # :309
    def __init__(self, dsn: str | None = None) -> None            # :321  self.dsn = dsn or default_dsn ; self._schema_ensured = False
    def _get_db(self) -> AsyncDB                                  # :326  return AsyncDB("pg", dsn=self.dsn)
    async def _ensure_ready(self) -> None                         # :330
    async def ensure_schema(self) -> None                         # :335-353  race-tolerant ("already exists" → debug + continue)
    async def save(...)                                           # :355  async with await db.connection() as conn: await conn.execute(...)
    # rows: conn.fetchall(sql, *args) / conn.fetchrow(sql, *args) — see :404-421

# tests/conftest.py
@pytest.fixture
def pg_dsn() -> str        # :21  os.getenv("NAVIGATOR_PG_DSN", ""); mark tests @pytest.mark.integration, skip when empty
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.recipes.store.PgRecipeStore`~~ — the class lives in ai-parrot-server (`parrot.handlers.models.recipes`), by decision.
- ~~A relational table for recipes~~ — `navigator.infographic_recipes` exists in no database; `ensure_schema()` creates it.
- ~~A `schema` override on `PgUISurfaceStore`~~ — it hardcodes `navigator`; this store deliberately takes `schema=` (spec §6, last bullet).
- ~~A `title`/`description` read-back into the model~~ — the columns are denormalised for `list()` only; `get()` deserialises the `recipe` JSONB.
- ~~A `pg_store` fixture~~ — write it in the test module (spec §4 Test Data): `PgRecipeStore(pg_dsn)`, `ensure_schema()`, truncate between tests.

---

## Implementation Notes

### Pattern to Follow
Copy `PgUISurfaceStore` (`models/ui_surfaces.py:309-436`) structurally: module docstring, DDL list, `__init__`, `_get_db`, `_ensure_ready`, `ensure_schema`, then one method per ABC method, each opening `async with await db.connection() as conn:`. Keep the `(name, owner)` key with `owner or ""` exactly as `DBRecipeStore` does.

### Key Constraints
- Async throughout; `self.logger = logging.getLogger(__name__)`; never log a DSN.
- `save` is an UPSERT (`INSERT ... ON CONFLICT (name, owner) DO UPDATE SET ... updated_at = NOW()`), never two rows.
- `get` on a v1 row still loads (auto-migrated in memory); an out-of-range `schema_version` raises `RecipeSchemaVersionError` — the same gate `FileRecipeStore.get` runs.
- `schema` is interpolated into SQL: validate it with the regex above and refuse anything else.
- Tests must not require Redis and must not touch `navigator.ui_surfaces`.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` — the template
- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py:230-430` — error parity with the siblings

---

## Acceptance Criteria

- [ ] `from parrot.handlers.models.recipes import PgRecipeStore` works; `PgRecipeStore` is an `AbstractRecipeStore`
- [ ] `test_pg_recipe_store_roundtrip`, `_upsert_bumps_updated_at`, `_owner_scoping`, `_get_missing_raises`, `_delete_missing_raises`, `_list_summaries`, `_schema_version_gate`, `_ensure_schema_idempotent` pass against `NAVIGATOR_PG_DSN`
- [ ] `ensure_schema()` twice is a no-op the second time; the first store use creates the table
- [ ] A bad `schema=` value raises `ValueError` before any SQL runs
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/models/recipes.py` clean
- [ ] `FileRecipeStore`/`DBRecipeStore` untouched (`git diff --stat` shows neither)

---

## Test Specification

```python
# tests/unit/handlers/test_pg_recipe_store.py
import pytest
from datetime import UTC, datetime
from parrot.handlers.models.recipes import PgRecipeStore
from parrot.outputs.a2ui.recipes.models import InfographicRecipe
from parrot.outputs.a2ui.recipes.store import RecipeNotFoundError, RecipeSchemaVersionError

pytestmark = pytest.mark.integration

@pytest.fixture
def recipe() -> InfographicRecipe:
    """Minimal schema_version=2 recipe: one param, one data source, one stock transform — never the flex agent."""

@pytest.fixture
async def pg_store(pg_dsn):
    if not pg_dsn:
        pytest.skip("NAVIGATOR_PG_DSN not set")
    store = PgRecipeStore(pg_dsn)
    await store.ensure_schema()
    # TRUNCATE navigator.infographic_recipes between tests
    yield store

async def test_pg_recipe_store_roundtrip(pg_store, recipe): ...
async def test_pg_recipe_store_upsert_bumps_updated_at(pg_store, recipe): ...
async def test_pg_recipe_store_owner_scoping(pg_store, recipe): ...
async def test_pg_recipe_store_get_missing_raises(pg_store):
    with pytest.raises(RecipeNotFoundError): await pg_store.get("nope")
async def test_pg_recipe_store_delete_missing_raises(pg_store): ...
async def test_pg_recipe_store_list_summaries(pg_store, recipe): ...
async def test_pg_recipe_store_schema_version_gate(pg_store, recipe):
    """UPDATE the row's schema_version to 99 → get raises RecipeSchemaVersionError; set 1 → still loads."""
async def test_pg_recipe_store_ensure_schema_idempotent(pg_store): ...
def test_bad_schema_name_rejected():
    with pytest.raises(ValueError): PgRecipeStore("postgres://x", schema="navigator; DROP TABLE")
```

---

## Agent Instructions

1. Read the spec §2 Data Models, §3 Module 1, §6. Read `models/ui_surfaces.py:309-436` and `recipes/store.py:175-430` in full.
2. Verify every import in the contract still resolves before writing.
3. Implement, run `pytest tests/unit/handlers/test_pg_recipe_store.py -v` with `NAVIGATOR_PG_DSN` set.
4. Move this file to `sdd/tasks/completed/`, set the index entry to `done`, fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
