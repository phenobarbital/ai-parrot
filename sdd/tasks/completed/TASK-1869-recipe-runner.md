# TASK-1869: RecipeRunner — deterministic replay pipeline

**Feature**: FEAT-324 — Infographic Builder — Recipe-Driven, Replayable A2UI Infographics
**Spec**: `sdd/specs/infographic-builder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1866, TASK-1867, TASK-1868
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-324 — the heart of the feature. One runner behind all three triggers
(chat/REST/scheduler, spec G6) executes the seven-step replay: params → data → gate →
transforms → envelope → render → persist/deliver. Lives OUTSIDE `parrot.outputs.a2ui`
(in `parrot/tools/infographic_recipes/`) precisely so it may import DatasetManager (G8).

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/infographic_recipes/{__init__,runner}.py`:
  - `RecipeRunner(store: AbstractRecipeStore, dataset_manager: DatasetManager, *,
    artifact_store=None, owner=None)`.
  - `async run(name, *, params=None, pctx=None) -> RenderedArtifact` implementing, in order:
    1. load recipe from store; resolve params (declared defaults + overrides; date resolvers)
       — undeclared overrides already rejected by TASK-1865 params engine;
    2. per `DataSourceSpec`: substitute params into sql/conditions, call
       `DatasetManager.fetch_dataset(name, sql=..., conditions=..., force_refresh=...)`,
       then take the frame from `get_dataset_entry(name).df`; map to the spec alias.
       Propagate the invoker `pctx` the way DatasetManager expects (see contract note);
    3. run the TASK-1866 gate over every transform step; abort if any `RecipeRunError`;
    4. execute transform chain in declared order; each `output_key` lands in a `data_model`
       dict; steps may consume prior `output_key`s as inputs;
    5. cross-check every layout `$bind` pointer against `data_model` keys (the "$bind drift"
       risk from spec §7), then assemble via `build_infographic`/`build_surface`
       (these call `validate_envelope` internally);
    6. render via `get_a2ui_renderer(recipe.render.profile)` → `RenderedArtifact`;
    7. optionally persist to the artifact store and deliver via `deliver_artifact` when
       `recipe.render.delivery` is set.
  - `async dry_run(recipe) -> list[RecipeRunError]` — steps 1/3/5 only (no data fetch beyond
    metadata, no render): validates params-references, transformer names, gate against
    dataset metadata columns when available, and `$bind` pointers. Used by the freeze path.
  - `RecipeRunException(Exception)` carrying a `RecipeRunError`; every abort path raises it.
- Unit tests with a mocked DatasetManager + fake renderer (registered via
  `register_a2ui_renderer`).

**NOT in scope**: toolkit tools/freeze capture (TASK-1870), REST/scheduler wiring
(TASK-1872), the interactive-html renderer itself (TASK-1871 — tests here use a fake).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py` | CREATE | exports RecipeRunner, RecipeRunException |
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py` | CREATE | seven-step pipeline + dry_run |
| `packages/ai-parrot/tests/tools/infographic_recipes/__init__.py` | CREATE | test package |
| `packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py` | CREATE | pipeline/order/binding/error tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, RecipeRunError   # TASK-1865
from parrot.outputs.a2ui.recipes.params import resolve_params, substitute          # TASK-1865 (verify names)
from parrot.outputs.a2ui.recipes.transformers import TransformerRegistry, validate_inputs  # TASK-1866
from parrot.outputs.a2ui.recipes.store import AbstractRecipeStore                  # TASK-1868
from parrot.outputs.a2ui.builders import build_surface, build_infographic          # builders.py:44,:151
from parrot.outputs.a2ui.renderers import get_a2ui_renderer, register_a2ui_renderer  # renderers/__init__.py __all__:26-31
from parrot.outputs.a2ui.artifacts import RenderedArtifact                         # artifacts.py:41
from parrot.outputs.a2ui.delivery import deliver_artifact                          # delivery.py:86
from parrot.tools.dataset_manager.tool import DatasetManager                       # tool.py:501
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                                  # line 501
    def get_dataset_entry(self, name: str) -> Optional[DatasetEntry]:   # line 2250
    async def fetch_dataset(self, name: str, sql: Optional[str] = None,
                            conditions: Optional[Dict[str, Any]] = None,
                            force_refresh: bool = False) -> Dict[str, Any]:  # line 3266
# DatasetEntry (line 124): `.df` property → materialized pd.DataFrame
# PBAC NOTE: per-call permission context is a module-level ContextVar set by _pre_execute
# (see tool.py __init__ comment near line 600) — the runner does NOT pass pctx as an argument
# to fetch_dataset; it must invoke DatasetManager the way callers set that context. READ the
# _pre_execute / _get_current_pctx implementation in tool.py before wiring pctx and document
# the chosen mechanism in the runner docstring.

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_infographic(*, title, sections, subtitle=None, theme=None,
                      surface_id="infographic", data_model=None) -> CreateSurface:  # line 151
# builders call validate_envelope(origin=ProducerOrigin.LLM) internally (builders.py:68) —
# rejects unknown/action-bearing components; no separate validation call needed.

# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
class AbstractA2UIRenderer(ABC):
    capabilities: RendererCapabilities
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> "Any | str": ...
# get_a2ui_renderer(name): registry-first, importlib fallback to
# "parrot.outputs.a2ui_renderers.<name>", ImportError names the pip extra.

# packages/ai-parrot/src/parrot/outputs/a2ui/delivery.py
async def deliver_artifact(owner, artifact, *, recipients, provider=_EMAIL, message="",
                           subject=None, artifact_store=None, user_id=None,
                           agent_id=None, session_id=None) -> dict[str, Any]:  # line 86
```

### Does NOT Exist
- ~~`RecipeRunner` / `parrot/tools/infographic_recipes/`~~ — created by THIS task
- ~~`DatasetManager.get_dataframe()` returning a DataFrame~~ — returns a Dict (info+sample);
  use `get_dataset_entry(name).df` for the real frame
- ~~`fetch_dataset(pctx=...)` parameter~~ — pctx flows via ContextVar, not an argument
- ~~A retry/repair loop on gate failure~~ — fail fast is the contract (LLM repair is a
  declared non-goal for v1)
- ~~Renderer-side dataModel mutation~~ — transforms fully populate `data_model` BEFORE
  envelope assembly; renderers only read

---

## Implementation Notes

### Key Constraints
- Every abort raises `RecipeRunException` with a `RecipeRunError` whose `stage` matches where
  it died (`params|data|gate|transform|layout|render`) — REST maps this to 422 (TASK-1872),
  the chat tool returns it structured (TASK-1870).
- Dataset-not-registered error must list available datasets
  (`DatasetManager.get_dataset_entry` returns None → build the diagnostic from
  `list(self._datasets)` equivalent public API — use `list_datasets()`).
- The layout `$bind` cross-check happens BEFORE rendering (spec §7 known risk).
- Transform outputs land under their `output_key`; later steps may reference prior keys in
  `inputs` — resolve aliases as: data-source alias first, then prior output_key.
- Concurrency: `run()` must not mutate the recipe or shared runner state (safe concurrent
  replays, spec edge case).
- Logging via `self.logger` at each pipeline stage.

### References in Codebase
- `sdd/specs/infographic-builder.spec.md` §2 Component Diagram — the seven steps are normative
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — READ `_pre_execute`/pctx
  ContextVar mechanics before implementing step 2

---

## Acceptance Criteria

- [ ] Seven-step pipeline implemented; `test_runner_pipeline_order_and_binding` proves
      output_key→$bind resolution and catalog validation
- [ ] `test_runner_unknown_transformer` and `test_runner_dataset_not_registered` produce the
      specified diagnostics; nothing executes after a gate failure
- [ ] `dry_run` returns ALL problems (params refs, transformer names, $bind pointers) without
      fetching data or rendering
- [ ] Invoker pctx honored per DatasetManager's ContextVar mechanism (documented in docstring)
- [ ] Delivery only invoked when `render.delivery` set (mock-asserted)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/infographic_recipes/ -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py
import pytest
from parrot.outputs.a2ui.renderers import register_a2ui_renderer

@pytest.fixture
def fake_renderer():  # registers a capture-renderer returning a minimal RenderedArtifact
    ...

@pytest.fixture
def mock_dataset_manager(budget_variance_frames):  # fetch_dataset + get_dataset_entry stubs
    ...

class TestRecipeRunner:
    async def test_runner_pipeline_order_and_binding(self, ...): ...
    async def test_runner_unknown_transformer(self, ...): ...
    async def test_runner_dataset_not_registered(self, ...): ...
    async def test_gate_failure_aborts_before_transforms(self, ...): ...
    async def test_bind_drift_detected_before_render(self, ...): ...
    async def test_dry_run_collects_all_errors(self, ...): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 diagram + §7 risks are normative for this task)
2. **Check dependencies** — TASK-1866/1867/1868 completed; read their real APIs
3. **Verify the Codebase Contract** — especially the pctx ContextVar note
4. **Update status** in `sdd/tasks/index/infographic-builder.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-22
**Notes**: Verified `_pctx_var` lives in `parrot.auth.context` (not a local
DatasetManager ContextVar) before wiring pctx propagation — the runner sets/
resets it manually around the fetch step since it calls `fetch_dataset`
directly, bypassing `_pre_execute`'s toolkit-dispatch trigger. Implemented
all seven steps: params -> data (dataset-not-registered raises stage="data"
listing available names via `list_datasets()`) -> gate (DataFrame-backed
inputs only; chained dict-output_key inputs are exempt from column-gating,
validated instead at transform time) -> transforms (data_model keyed by
`output_key`, chaining supported) -> `$bind` drift check (custom lightweight
top-level-key scan reusing `BINDING_KEY`/`is_binding_expression` from
`parrot.outputs.a2ui.models` — no `jsonpointer` dependency needed since only
the top-level key is checked, not full resolution) -> envelope assembly
(`build_infographic` for `component == "Infographic"`, `build_surface`
otherwise) -> render (`get_a2ui_renderer` returns a CLASS, instantiated then
`.render()` called; ImportError propagates unchanged for unknown profiles)
-> best-effort delivery (no RecipeRunError stage exists for delivery/persist
in the TASK-1865 model, so failures are logged, never raised). `dry_run()`
checks params/transformer-names/`$bind`-vs-declared-output_keys, plus a
best-effort dataset-metadata column check, WITHOUT ever calling
`fetch_dataset`. 78 tests pass (12 new + 66 pre-existing recipes suite);
`ruff check` clean.

**Deviations from spec**: (1) `run()`'s literal signature per spec/contract
has no `owner`/session-context params, so full `ArtifactStore.save_artifact`
persistence (which needs user_id/agent_id/session_id) is left to the caller
with that context (TASK-1870/1872); `artifact_store` is passed straight
through to `deliver_artifact` for its one verified use (Slack public-URL
lookup). (2) `$bind` drift checking validates only the pointer's top-level
key against `data_model`/declared `output_key`s (not full nested-path
resolution via `jsonpointer`), since spec §7's stated risk is specifically
about `output_key` renames breaking bindings, and this avoids requiring the
`ai-parrot-visualizations[a2ui]` extra just to validate a recipe.
