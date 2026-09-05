---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Postgres recipe store + agent-package importability

**Feature ID**: FEAT-528
**Date**: 2026-09-04
**Author**: Juan Ruffato (jfrruffato@trocglobal.com) + Claude
**Status**: draft
**Target version**: next minor after 0.29.0
**Reserved via**: `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label pg-recipe-store-and-agent-package-importability` → `FEAT-528` (commit `0a27686cd`). The allocator returned 528, not the ledger's cached 527, because `infographic-a2ui-migration` had already claimed 527 on `origin/dev`.
**Downstream consumer**: FieldSync `FEAT-559` — `fieldsync/sdd/proposals/fieldsync-a2ui-surfaces-plane.brainstorm.md`. That feature mounts parrot's `ui_surfaces` REST lane in `fieldsync-api` and is blocked on both modules below.

---

## 1. Motivation & Business Requirements

### Problem Statement

Two gaps surfaced while wiring parrot's A2UI surfaces plane into a host application (FieldSync). Both are generic parrot concerns, neither has anything host-specific in it, and the host cannot work around either one without copying parrot code.

**Gap 1 — there is no relational recipe store.** `AbstractRecipeStore` has exactly two implementations:

- `FileRecipeStore` writes `<dir>/<name>.yaml`, so a recipe travels baked into a deployment artifact. Changing a dashboard means a deploy.
- `DBRecipeStore` is **Redis**, despite the name. Its own docstring says *"There is no relational table here — SkillRegistry itself has none to copy."* It degrades to in-memory when Redis is unavailable, evaporates on a flush, and is invisible to SQL.

Meanwhile the surfaces those recipes produce are already relational: `PgUISurfaceStore` persists them to `navigator.ui_surfaces` with a lazy `ensure_schema()`. A recipe and the surface it produces therefore live in two different worlds, backed up differently, queryable differently, and created by two different DDL stories.

**Gap 2 — an agent's sibling package is not importable by a host whose root already has an `agents/` package.** `agents/flex_dashboard.py:83` does `import agents.flex_dashboard.transformers`, and `agents/flex_dashboard/transformers.py:53` does `from agents.flex_dashboard.normalize import ...`. Both are absolute imports rooted at a top-level package literally named `agents`. They resolve only when the process has *this repo's* `agents/` directory as that package.

A host that wants to replay a flex recipe needs those transformers registered in-process — and nothing else from the agent, no LLM, no toolkit. FieldSync cannot get them: it has its own `agents/` package at its repo root, so `agents.flex_dashboard` resolves to FieldSync's package and raises `ModuleNotFoundError`. This was reproduced twice while investigating, once with FieldSync's `agents/` shadowing this repo's.

`flex_dashboard.py`'s own module docstring already documents a *different* face of the same problem: because the sibling is a regular package, a plain `from agents.flex_dashboard import FlexDashboard` resolves to the package and never to the module. It flags the fix as "out of scope for this feature to do unilaterally… flagged here for the PR reviewer to decide." This spec is that decision.

### Goals

- Ship `PgRecipeStore`, a relational `AbstractRecipeStore` that stores one row per recipe, so a recipe becomes editable, backed-up, queryable data alongside the surfaces it produces.
- Make an agent's sibling package importable under **any** parent package name, so a host can register a recipe's transformers without owning a package named `agents`.
- Give a host a documented, supported way to register transformers without importing the agent class or its dependencies.

### Non-Goals (explicitly out of scope)

- Migrating existing `FileRecipeStore` or `DBRecipeStore` users. Both stay, both keep working; `PgRecipeStore` is a third choice.
- Renaming `DBRecipeStore`, however misleading the name is. That is a breaking change for its users and belongs in its own feature.
- Any change to `AbstractRecipeStore`'s method contract. The new store implements the existing five methods.
- Adding a `program_slug` or any tenancy column to `ui_surfaces`. FieldSync stamps the program in `recipe_params` for now; a first-class column is a separate request.
- Moving the flex agent out of `agents/`, or renaming the sibling package. Module 2 fixes importability without relocating anything.
- Anything in FEAT-527 (infographic → A2UI dual-emit). Verified non-overlapping: that feature's five modules touch emit defaults, presentation parity, the bundled-UI renderer, `HtmlDocument` and docs. No shared file with this spec.

---

## 2. Architectural Design

### Overview

Two independent modules. Module 1 adds a persistence class beside its existing twin. Module 2 changes import statements inside one agent package and adds one small public helper.

### Component Diagram

```
Module 1
  AbstractRecipeStore (unchanged contract)
        ├── FileRecipeStore   (existing, YAML on disk)
        ├── DBRecipeStore     (existing, Redis)
        └── PgRecipeStore     (NEW) ──→ navigator.infographic_recipes (one row per recipe)
                                             ▲
                          PgUISurfaceStore ──┘ same schema, same lazy ensure_schema() idiom
                                └──→ navigator.ui_surfaces / ui_surface_shares

Module 2
  host process ──→ load_transformer_module(path) ──→ registers @infographic_transformer fns
                                                       (no agent, no LLM, no toolkit)
  agents/flex_dashboard/transformers.py ──(relative)──→ .normalize
  agents/flex_dashboard.py             ──(path-anchored)──→ its own sibling package
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractRecipeStore` | implements | `PgRecipeStore` satisfies the existing five-method contract; no ABC change |
| `PgUISurfaceStore` (`parrot/handlers/models/ui_surfaces.py:309`) | mirrors | same constructor shape (`dsn: str \| None`), same lazy `_ensure_ready()` / `ensure_schema()`, same `navigator` schema |
| `register_recipe_routes(app, *, recipe_store, …)` (`parrot/handlers/infographic_recipes.py:78`) | uses | a host passes `PgRecipeStore()` where it passes `FileRecipeStore(...)` today; no signature change |
| `RecipeRunner` (`parrot/tools/infographic_recipes/runner.py`) | uses | reads recipes through the store contract, unchanged |
| `InfographicAuthoringMixin.publish_recipe` (`parrot/bots/mixins/infographic_authoring.py:281`) | uses | writes through the store contract, unchanged |
| `agents/flex_dashboard.py`, `agents/flex_dashboard/{transformers,normalize}.py` | modifies | import statements only; no behavior change |
| `parrot.tools.infographic_recipes` | extends | gains one public helper, `load_transformer_module` |

### Data Models

```python
# The row shape. One recipe per row, keyed by (name, owner-or-empty).
# `recipe` holds InfographicRecipe.model_dump(mode="json") verbatim, so the
# store never has to know the recipe schema — only its version, which is
# lifted into a column so _raw_schema_version() is a cheap scalar read.
CREATE TABLE IF NOT EXISTS navigator.infographic_recipes (
    name            VARCHAR      NOT NULL,
    owner           VARCHAR      NOT NULL DEFAULT '',   -- '' = unscoped/shared
    schema_version  INTEGER      NOT NULL,
    title           TEXT,                               -- denormalised for list()
    description     TEXT,                               -- denormalised for list()
    recipe          JSONB        NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (name, owner)
);
CREATE INDEX IF NOT EXISTS ix_infographic_recipes_owner
    ON navigator.infographic_recipes (owner);
```

`title` and `description` are denormalised so `list()` returns its lightweight summaries without deserialising every recipe. They are written from the model on every save and are never read back into it.

### New Public Interfaces

```python
# parrot/outputs/a2ui/recipes/store.py  (or a new pg_store.py re-exported there)
class PgRecipeStore(AbstractRecipeStore):
    def __init__(self, dsn: str | None = None, *, schema: str = "navigator") -> None: ...
    async def ensure_schema(self) -> None: ...
    async def save(self, recipe: InfographicRecipe) -> None: ...
    async def get(self, name: str, owner: Optional[str] = None) -> InfographicRecipe: ...
    async def list(self, owner: Optional[str] = None) -> list[dict[str, Any]]: ...
    async def delete(self, name: str, owner: Optional[str] = None) -> None: ...
    async def _raw_schema_version(self, name: str, owner: Optional[str] = None) -> int: ...

# parrot/tools/infographic_recipes/__init__.py
def load_transformer_module(path: str | Path, *, name: str | None = None) -> ModuleType:
    """Import a transformer module by file path so its @infographic_transformer
    functions register, without importing the agent that ships them."""
```

---

## 3. Module Breakdown

### Module 1: `PgRecipeStore`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/pg_store.py`, re-exported from `recipes/store.py` and `recipes/__init__.py`
- **Responsibility**: A relational `AbstractRecipeStore`. Lazy `ensure_schema()` creating `navigator.infographic_recipes`, mirroring `PgUISurfaceStore`'s `_ensure_ready()` idiom so the first store use creates the table. `save` upserts on `(name, owner)` and bumps `updated_at`. `get` raises `RecipeNotFoundError` when absent and runs the same `_check_schema_version` gate the other stores run. `list` returns the lightweight summaries from the denormalised columns. `delete` raises `RecipeNotFoundError` when absent, matching the sibling implementations. `_raw_schema_version` reads the column, not the JSON.
- **Depends on**: nothing new. `asyncdb` and `RecipeNotFoundError` / `RecipeSchemaVersionError` already exist in this module.

### Module 2: Agent-package importability
- **Path**: `agents/flex_dashboard/transformers.py`, `agents/flex_dashboard/normalize.py`, `agents/flex_dashboard.py`, `packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py`
- **Responsibility**: Three changes.
  1. **Relative imports inside the sibling package.** `transformers.py:53` becomes `from .normalize import (...)`. A relative import resolves against whatever the package's real parent turns out to be, so the package works as `agents.flex_dashboard`, `docs.flex_dashboard` or a top-level `flex_dashboard` without edits.
  2. **Path-anchored sibling load in the agent module.** `flex_dashboard.py:83`'s `import agents.flex_dashboard.transformers` is replaced by a load anchored on `_PACKAGE_DIR`, which the module already computes at `:88` for `skills/` and `kb/`. The agent then no longer assumes a package named `agents`, which also removes the "regular package shadows the module" footgun its own docstring documents at `:19-47`.
  3. **A public host-side loader.** `load_transformer_module(path)` imports a module by file location under a synthetic name and returns it, so a host that only wants the transformers registered never touches the agent class, its LLM, or its toolkit. This is the supported answer to "how do I replay this recipe in my own service".
- **Depends on**: none. Independent of Module 1 at file level; the two can be implemented in parallel.

### Module 3: Documentation
- **Path**: `docs/outputs/infographic-recipes.md`, and the `agents/flex_dashboard.py` docstring
- **Responsibility**: Document `PgRecipeStore` as the third store and when to choose it over the other two. Document `load_transformer_module` as the host contract for replaying a recipe outside the process that authored it. Update the flex agent's docstring warning, which currently says the import problem is unresolved and out of scope.
- **Depends on**: Modules 1 and 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_pg_recipe_store_roundtrip` | 1 | `save` then `get` returns an equal `InfographicRecipe`, params and transforms intact |
| `test_pg_recipe_store_upsert_bumps_updated_at` | 1 | Saving the same `(name, owner)` twice replaces the row and moves `updated_at` forward, and does not create a second row |
| `test_pg_recipe_store_owner_scoping` | 1 | The same `name` under two owners is two rows; `get` and `list` respect the scope; `owner=None` maps to `''` consistently |
| `test_pg_recipe_store_get_missing_raises` | 1 | `RecipeNotFoundError`, matching `FileRecipeStore` and `DBRecipeStore` |
| `test_pg_recipe_store_delete_missing_raises` | 1 | Same error parity on delete |
| `test_pg_recipe_store_list_summaries` | 1 | `list` returns name/title/description/owner/updated_at without deserialising the recipe body |
| `test_pg_recipe_store_schema_version_gate` | 1 | A row written with an out-of-range `schema_version` raises `RecipeSchemaVersionError`; `schema_version=1` still loads (auto-migrated in memory) |
| `test_pg_recipe_store_ensure_schema_idempotent` | 1 | Calling `ensure_schema()` twice is a no-op the second time; first store use creates the table |
| `test_transformers_import_under_foreign_parent` | 2 | Load `agents/flex_dashboard/` under a synthetic parent named something other than `agents` and confirm `transformers` imports and registers. **This is the regression test for the reported defect** |
| `test_flex_module_loads_without_agents_package` | 2 | Load `flex_dashboard.py` by file location in an interpreter where no top-level `agents` package is importable, and confirm the class is defined and its transformers registered |
| `test_load_transformer_module_registers` | 2 | `load_transformer_module(path)` makes the decorated functions resolvable in the transformer registry, with no agent instantiated |

### Integration Tests

| Test | Description |
|---|---|
| `test_recipe_publish_and_replay_through_pg_store` | Publish a recipe into `PgRecipeStore`, then replay it with `RecipeRunner` in a **separate** store instance, proving the row is the only state carried between them |
| `test_register_recipe_routes_with_pg_store` | `register_recipe_routes(app, recipe_store=PgRecipeStore(...))` wires the runner and the recipe REST lane answers, exactly as it does with `FileRecipeStore` |
| `test_replay_flex_recipe_from_foreign_host` | End-to-end shape of the FieldSync case: register the transformers through `load_transformer_module`, register the datasets, read the recipe from `PgRecipeStore`, and produce an envelope — with no agent instantiated anywhere in the process |

### Test Data / Fixtures

```python
@pytest.fixture
def recipe() -> InfographicRecipe:
    """A minimal schema_version=2 recipe with one param, one data source and
    one stock transform, so store tests never depend on the flex agent."""

@pytest.fixture
async def pg_store(scratch_dsn) -> PgRecipeStore:
    """PgRecipeStore against the scratch database, ensure_schema() applied,
    table truncated between tests."""
```

Store tests run against the existing scratch-Postgres fixture used by the other relational tests; they must not require a Redis instance and must not touch `navigator.ui_surfaces`.

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/ -v`)
- [ ] `PgRecipeStore` is a drop-in for `FileRecipeStore` at every `AbstractRecipeStore` call site: `register_recipe_routes`, `RecipeRunner`, `publish_recipe`, and `UISurfacesHandler`'s refresh path. Demonstrated by the integration tests, not asserted in prose.
- [ ] `navigator.infographic_recipes` is created by a lazy `ensure_schema()` that is safe to call on every boot and requires only `CREATE` on the target schema.
- [ ] `agents/flex_dashboard/transformers.py` imports and registers when the package's parent is **not** named `agents`. Mutation-checked: revert the relative import, and `test_transformers_import_under_foreign_parent` goes RED.
- [ ] A host can register a recipe's transformers via `load_transformer_module` with no agent instantiated, therefore without needing `ai-parrot-visualizations` or an LLM credential in that process.
- [ ] `FileRecipeStore` and `DBRecipeStore` behavior is unchanged; their existing tests pass untouched.
- [ ] No breaking change to `AbstractRecipeStore`, to `register_recipe_routes`'s signature, or to any published import path.
- [ ] `docs/outputs/infographic-recipes.md` documents the third store and the host loader; the flex agent docstring's "out of scope, flagged for the PR reviewer" warning is replaced by what was actually done.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Everything below was verified on `dev` and, where noted, in the installed wheel `ai_parrot_server 0.27.1` / `ai_parrot 0.28.1`.

### Verified Imports

```python
from parrot.outputs.a2ui.recipes.store import (
    AbstractRecipeStore, FileRecipeStore, DBRecipeStore,
    RecipeNotFoundError, RecipeSchemaVersionError,
)                                                    # store.py:175, :230, :304, :67, :81
from parrot.outputs.a2ui.recipes.models import InfographicRecipe   # models.py:235
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore    # ui_surfaces.py:309
from parrot.handlers.infographic_recipes import register_recipe_routes  # :78
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py
class RecipeNotFoundError(LookupError): ...                       # :67
class RecipeSchemaVersionError(ValueError): ...                   # :81
SUPPORTED_SCHEMA_VERSION = 2   # accepts 1 too, auto-migrated in memory on read   # :56-58
class AbstractRecipeStore(ABC):                                   # :175
    @abstractmethod
    async def save(self, recipe: InfographicRecipe) -> None: ...  # :184  "overwriting any existing
                                                                  #  (name, owner) and bumping updated_at"
    @abstractmethod
    async def get(self, name: str, owner: Optional[str] = None) -> InfographicRecipe: ...   # :190
    @abstractmethod
    async def list(self, owner: Optional[str] = None) -> list[dict[str, Any]]: ...          # :200
                                                                  # "lightweight summaries
                                                                  #  (name/title/description/owner/updated_at)"
    @abstractmethod
    async def delete(self, name: str, owner: Optional[str] = None) -> None: ...             # :206
    @abstractmethod
    async def _raw_schema_version(self, name: str, owner: Optional[str] = None) -> int: ... # :215
class FileRecipeStore(AbstractRecipeStore):                       # :230
    def __init__(self, directory: Path | str) -> None: ...        # :239
    # layout: <directory>/<name>.yaml, or <directory>/<owner>/<name>.yaml when owner is set
class DBRecipeStore(AbstractRecipeStore):                         # :304
    """Redis-backed ... There is no relational table here."""     # :305-312
    def __init__(self, redis_url: Optional[str] = None, namespace: str = "default") -> None: ...  # :314

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class InfographicRecipe(BaseModel):        # :235
    schema_version: int = 2                # :276
    def to_yaml(self) -> str:              # :291 → yaml.safe_dump(self.model_dump(mode="json"), ...)  :297
    @classmethod
    def from_yaml(cls, text: str) -> "InfographicRecipe": ...   # :300

# packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py — THE TEMPLATE FOR MODULE 1
_DDL_STATEMENTS: list[str]                                        # :88
class PgUISurfaceStore:                                           # :309
    def __init__(self, dsn: str | None = None) -> None: ...       # :321
    def _get_db(self) -> AsyncDB: ...                             # :326
    async def _ensure_ready(self) -> None:                        # :330  "Lazily run ensure_schema on first store use"
    async def ensure_schema(self) -> None: ...                    # :335  iterates _DDL_STATEMENTS
    async def save(self, record, *, overwrite: bool = False) -> str: ...   # :355
    async def get(self, surface_id) -> UISurfaceRecord | None: ...         # :396
    async def list(self, user_id, *, kind=None) -> list[UISurfaceRecord]: ...  # :404
    async def delete(self, surface_id, user_id) -> bool: ...               # :430

# packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py
def register_recipe_routes(                                       # :78
    app: web.Application, *, recipe_store: AbstractRecipeStore,
    recipe_runner: Optional[RecipeRunner] = None,
    dataset_manager: Any = None, artifact_store: Any = None,
) -> RecipeRunner: ...
    # ":86-90 — Routes themselves are registered unconditionally in manager.py ...
    #  this function ONLY wires the store/runner onto app"

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py — stock transformers already registered
#   day_totals :120 · division_breakdown :146 · variance_analysis :209 · top_movers :270
#   narrative_facts :359 · groupby_aggregate :460 · pivot :489 · latest_vs_baseline :516
```

### The defect Module 2 fixes, verbatim

```python
# agents/flex_dashboard.py:83
import agents.flex_dashboard.transformers  # noqa: F401
#   ^ absolute, rooted at a top-level package named `agents`

# agents/flex_dashboard/transformers.py:47-53
from typing import Any
import numpy as np
import pandas as pd
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer
from agents.flex_dashboard.normalize import (      # ← same absolute rooting
    ...
)
# NOTE: apart from that one line, this module's dependency surface is numpy, pandas
# and parrot's decorator. Registering these transformers costs no agent, no LLM and
# no ai-parrot-visualizations — which is exactly why a host wants to import it alone.

# agents/flex_dashboard/normalize.py:25-32 — stdlib + numpy + pandas only. Nothing else.

# agents/flex_dashboard.py:87-90 — the anchoring Module 2 reuses, already present
_AGENT_DIR = Path(__file__).resolve().parent
_PACKAGE_DIR = _AGENT_DIR / "flex_dashboard"
SKILLS_DIR = _PACKAGE_DIR / "skills"
KB_DIR = _PACKAGE_DIR / "kb"
```

Reproduction of the failure, run this session from the FieldSync virtualenv:

```
ModuleNotFoundError: No module named 'agents.flex_dashboard'
  File ".../ai-parrot/agents/flex_dashboard.py", line 83, in <module>
    import agents.flex_dashboard.transformers
```

…triggered because the interpreter's working repo contributed its own `agents/` package. The same import succeeds when this repo's root is the only `agents` on the path, which is precisely the fragility being fixed.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PgRecipeStore` | `register_recipe_routes` | passed as `recipe_store=` | `infographic_recipes.py:78-85` |
| `PgRecipeStore` | `RecipeRunner` | constructor's first positional argument | `agents/flex_dashboard.py:697` (`RecipeRunner(self._require_recipe_store(), self._dataset_manager)`) |
| `PgRecipeStore` | `UISurfacesHandler` refresh | `app["recipe_runner"]` wired by `register_recipe_routes` | `ui_surfaces.py:303-306` |
| `PgRecipeStore.ensure_schema` | `navigator` schema | `CREATE TABLE IF NOT EXISTS` | mirrors `ui_surfaces.py:88-112` |
| `load_transformer_module` | transformer registry | import side effect of `@infographic_transformer` | `recipes/transformers.py`, `library.py` |

### Does NOT Exist (Anti-Hallucination)

- ~~A relational recipe store~~ — `DBRecipeStore` is Redis; its docstring says so explicitly.
- ~~`navigator.infographic_recipes`~~ — the table does not exist in any database. `navigator.ui_surfaces` and `navigator.ui_surface_shares` do not either, as of 2026-09-04; whichever store runs `ensure_schema()` first creates its own.
- ~~A host-callable transformer loader~~ — no `load_transformer_module`, no plugin/entry-point mechanism for transformers. Registration is purely an import side effect today.
- ~~A `setup_a2ui(app, ...)` or `setup_ui_surfaces(app, ...)`~~ — `handlers/a2ui.py` and `handlers/ui_surfaces.py` expose no module-level mount function. Out of scope here, noted because the downstream consumer works around it with five `add_view` calls.
- ~~Any tenancy column on `ui_surfaces`~~ — the plane is `user_id`-scoped only.
- ~~A schema/table-name override on `PgUISurfaceStore`~~ — it hardcodes `navigator`. `PgRecipeStore` takes a `schema` keyword so a host is not forced into the same assumption; this is a deliberate, small divergence from the template.

---

## 7. External Dependencies

None new. `asyncdb` is already a dependency and is what `PgUISurfaceStore` uses.

---

## 8. Open Questions

- [ ] **Module placement**: `PgRecipeStore` in `ai-parrot` (`parrot/outputs/a2ui/recipes/`) beside the other two stores, or in `ai-parrot-server` beside `PgUISurfaceStore`? The contract it implements lives in core; its twin lives in server. Recommended: core, next to the ABC and the two siblings, because nothing about it is HTTP. — *Owner: Jesús*
- [ ] **Table name and schema**: `navigator.infographic_recipes` proposed, with a `schema=` constructor keyword so a host can place it elsewhere. Does the `navigator` default belong in a library, or should the schema be required? — *Owner: Jesús*
- [ ] **Module 2 shape**: relative imports plus a path-anchored sibling load is the minimal fix. The alternative Jesús's own docstring floats is renaming the sibling package (`agents/flex_dashboard_kit/`), which the flex spec's Module 3 architecture mandated against. Confirm the minimal fix is acceptable. — *Owner: Jesús*
- [ ] **Whether `finance_reporter` needs the same treatment.** It has no sibling package, but `SKILLS_DIR = Path(__file__).resolve().parents[1] / ".agent" / "skills"` (`:73`) is anchored to the repo layout, so it silently finds nothing when the file is relocated. Same class of defect, different symptom. Fold in or file separately? — *Owner: Jesús*
- [ ] **Target version**, given 0.29.0 just released and FEAT-527 targets it. — *Owner: Jesús*
