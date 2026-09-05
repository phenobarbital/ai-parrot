# TASK-2873: Integration — publish/replay through `PgRecipeStore`, REST lane, foreign-host replay

**Feature**: FEAT-528 — Postgres recipe store + agent-package importability
**Spec**: `sdd/specs/pg-recipe-store-and-agent-package-importability.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2870, TASK-2872
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests and §5. The two modules are independent at file level; this task proves they meet: a recipe row is the ONLY state between publish and replay, the REST recipe lane accepts the new store unchanged, and a "foreign host" (the FieldSync shape: no `agents` package, no agent instance, no LLM) can register flex's transformers, register the datasets, read the recipe from Postgres and produce an envelope.

---

## Scope

- `test_recipe_publish_and_replay_through_pg_store`: save a minimal recipe with `PgRecipeStore(pg_dsn)` A, replay with `RecipeRunner(PgRecipeStore(pg_dsn) B, dataset_manager)`; assert the envelope; A and B share nothing but the database.
- `test_register_recipe_routes_with_pg_store`: `register_recipe_routes(app, recipe_store=PgRecipeStore(pg_dsn))` on a bare `aiohttp.web.Application()` with the three `RecipeHandler` views added the way `manager.py:2217-2219` does; `GET /api/v1/infographic_recipes` lists the saved recipe; `POST …/{name}/run` answers with the runner's shape. Auth: the handler is `@is_authenticated()`-wrapped — use the same test session installation the existing handler tests use (find one under `tests/handlers/` and copy its fixture; do not hand-set attributes on a Mock — build the real `aiohttp` app and client).
- `test_replay_flex_recipe_from_foreign_host`: in a subprocess whose cwd has NO `agents` package, `load_transformer_module(<repo>/agents/flex_dashboard/transformers.py)`, register the six flex aliases on a `DatasetManager` with `add_query` **over an in-memory substitute** (six small `add_dataframe` frames with the columns the transformers need — this test must not hit querysource), read the flex recipe from `PgRecipeStore` (published once in the test via the classmethod-built descriptor, NOT by instantiating `FlexDashboard`), run `RecipeRunner`, assert an `Infographic` envelope with the five tab sections and assert no `FlexDashboard` instance exists in the process.

**NOT in scope**: any production code change. If a test cannot pass without one, stop and report — that is a finding for the spec, not a licence to widen production (ARCHITECTURE.md R6 in FieldSync; the same discipline here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/test_pg_recipe_store_replay.py` | CREATE | publish/replay + REST lane |
| `tests/integration/test_foreign_host_flex_replay.py` | CREATE | foreign-host replay |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.models.recipes import PgRecipeStore                       # TASK-2870
from parrot.tools.infographic_recipes import RecipeRunner, load_transformer_module   # runner (existing) + TASK-2871
from parrot.handlers.infographic_recipes import RecipeHandler, register_recipe_routes   # :155 / :78
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, DataSourceSpec  # models.py:235 / :69
from parrot.tools.dataset_manager.tool import DatasetManager                    # add_query :1406 (lazy) · add_dataframe :1092
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py
def register_recipe_routes(app, *, recipe_store, recipe_runner=None, dataset_manager=None, artifact_store=None) -> RecipeRunner   # :78
#   sets app["recipe_runner"] (and the store) — routes are NOT registered here (:86-90); add them yourself:
#   app.router.add_view("/api/v1/infographic_recipes", RecipeHandler)              (manager.py:2217)
#   app.router.add_view("/api/v1/infographic_recipes/{name}", RecipeHandler)       (:2218)
#   app.router.add_view("/api/v1/infographic_recipes/{name}/run", RecipeHandler)   (:2219)

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:   # ctor: RecipeRunner(recipe_store, dataset_manager)  — agents/flex_dashboard.py:697 usage
#   run(name, params=..., pctx=..., recipe_owner=..., include_envelope=True) → artifact with metadata["source_envelope"]  (ui_surfaces.py:534-550 usage)
#   _fetch_frames: passes ONLY DataSourceSpec.conditions/sql to the fetch (:467-469) — flex declares none → unfiltered fetch

# agents/flex_dashboard.py — recipe readable with NO instance (all @classmethod)
FlexDashboard._transform_sections()   # :296     FlexDashboard._narrative_spec()   # :370
FlexDashboard.recipe_params()         # :389     FlexDashboard.dashboard_descriptor()  # :423
FlexDashboard.DASHBOARD_RECIPE_NAME   # :150 = "flex-program-dashboard"
DATASET_SLUGS                          # :95-102  aliases msl/finance/hours/employees/region_utilization/rep_utilization
# publish_dashboard_recipe (:645) is an INSTANCE method → NOT used here; build the InfographicRecipe from the
# classmethods the way InfographicAuthoringMixin.publish_recipe does (bots/mixins/infographic_authoring.py:281-420),
# so the test never instantiates the agent (instantiation needs ai-parrot-visualizations, infographic_toolkit.py:253).

# tests/conftest.py:21  pg_dsn fixture (NAVIGATOR_PG_DSN) ; mark @pytest.mark.integration
```

### Does NOT Exist
- ~~`FlexDashboard()` in these tests~~ — forbidden by design; it needs the visualizations package and an LLM config.
- ~~A querysource connection in these tests~~ — datasets are in-memory frames; if a transformer needs a column, add it to the frame.
- ~~`load_transformer_module` on the installed wheel~~ — comes from TASK-2871 in this checkout; run tests from the repo with `src/` importable (editable install).

---

## Implementation Notes

### Key Constraints
- Every test `@pytest.mark.integration`, skipped when `NAVIGATOR_PG_DSN` is empty.
- The foreign-host test's whole point is the ABSENCE of an `agents` package: run it in a subprocess with `cwd=tmp_path` and assert `"agents" not in sys.modules` inside it after the replay.
- Truncate `navigator.infographic_recipes` rows the tests create; never touch `navigator.ui_surfaces`.
- Copy the flex frames' column names from the transformers (`agents/flex_dashboard/transformers.py`), not from memory.

### References in Codebase
- `bots/mixins/infographic_authoring.py:281-420` — how a recipe is assembled from a descriptor
- `agents/flex_dashboard.py:645-700` — what `publish_dashboard_recipe` adds (params) that a bare `publish_recipe` misses

---

## Acceptance Criteria

- [ ] `pytest tests/integration/test_pg_recipe_store_replay.py tests/integration/test_foreign_host_flex_replay.py -v` passes with `NAVIGATOR_PG_DSN`
- [ ] `PgRecipeStore` is a drop-in at `register_recipe_routes`, `RecipeRunner` and the REST lane — demonstrated, not asserted in prose (spec §5)
- [ ] The foreign-host test proves: transformers registered via `load_transformer_module`, six aliases registered, recipe read from Postgres, envelope with five tabs, no `FlexDashboard` instance, no `agents` in `sys.modules`
- [ ] No production file changed by this task (`git diff --stat -- packages agents` empty)

---

## Test Specification

```python
# tests/integration/test_foreign_host_flex_replay.py (skeleton)
import pytest, subprocess, sys, textwrap
pytestmark = pytest.mark.integration

def test_replay_flex_recipe_from_foreign_host(tmp_path, pg_dsn):
    if not pg_dsn: pytest.skip("NAVIGATOR_PG_DSN not set")
    code = textwrap.dedent(f'''
        import asyncio, sys
        from parrot.tools.infographic_recipes import load_transformer_module, RecipeRunner
        from parrot.handlers.models.recipes import PgRecipeStore
        load_transformer_module(r"{REPO}/agents/flex_dashboard/transformers.py")
        # ... build DatasetManager with six add_dataframe frames, publish the classmethod-built recipe, run ...
        assert "agents" not in sys.modules
        assert not any(type(o).__name__ == "FlexDashboard" for o in gc.get_objects())
        print("TABS", len(envelope_tabs))
    ''')
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, env={..., "NAVIGATOR_PG_DSN": pg_dsn})
    assert r.returncode == 0 and "TABS 5" in r.stdout, r.stderr
```

---

## Agent Instructions

1. Confirm TASK-2870 and TASK-2872 are in `sdd/tasks/completed/`.
2. Read `infographic_authoring.py:281-420` to build the recipe without the agent.
3. Implement, run with `NAVIGATOR_PG_DSN`, record the run in the Completion Note.
4. Move this file to `sdd/tasks/completed/`, set the index entry to `done`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
