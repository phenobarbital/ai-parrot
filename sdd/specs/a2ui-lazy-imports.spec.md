---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [a2ui, lazy-import, startup, infographic-recipes]
---

# Feature Specification: A2UI Lazy Imports

**Feature ID**: FEAT-668
**Date**: 2026-10-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

`python run.py`, the `parrot` agent CLI and several local MCP servers eagerly
import the heavy A2UI/outputs infrastructure at startup, even when the process
never renders a surface or runs a recipe. The visible symptom is DEBUG noise
from registry side effects:

```
parrot.outputs.a2ui.recipes.transformers :: Registered infographic transformer 'latest_vs_baseline'
parrot.outputs.a2ui.catalog :: Registered A2UI catalog component 'Chart' under catalog 'https://parrot.dev/catalogs/v1' (ChartComponent)
```

The real cost is startup time (`import parrot.outputs.a2ui.artifacts` ≈ 314 ms
on its own, measured with `python -X importtime`) and a wider import graph for
every bot that merely *can* attach an artifact.

A `sys.meta_path` trace (2026-10-14) found three independent eager chains:

1. **Transformer registration via the `recipes` package `__init__`**
   `handlers/models/recipes.py:24` imports `parrot.outputs.a2ui.recipes.models`
   → Python runs `recipes/__init__.py`, whose line 15 imports `library`
   *purely for its side effect* → the 8 built-in transformers register (and
   `library.py` imports pandas).
2. **Catalog registration via `artifacts.py` → `builders.py`**
   `outputs/a2ui/artifacts.py:29` imports `adapters.structured` at module level
   → `structured.py:45` imports `builders` → `builders.py:32,36` import
   `catalog.parrot` / `catalog.viz_core` for registration side effects (which in
   turn pull `catalog.basic`). Every importer of `artifacts` pays for this:
   `bots/data.py:33` and `bots/database/agent.py:18` (data agents in the CLI/MCP
   lanes) and `tools/infographic_recipes/runner.py:67`.
3. **Server handlers importing heavy runtime classes at module level**
   `parrot.manager.manager` imports the handler modules at module level
   (`manager.py:37-46`); those handlers import `RecipeRunner`
   (`handlers/infographic_recipes.py:43`, `handlers/ui_surfaces.py:49`),
   `InfographicToolkit` (`handlers/infographic.py:47`) and `catalog.basic`
   (`handlers/a2ui.py:59-60`, `a2a/server.py:59`) — names used only inside
   method bodies, `except` clauses or annotations.
   Separately, `tools/infographic_recipes/__init__.py:12-18` eagerly imports
   `freeze` and `runner`, so even the tiny `figure_guard` import in
   `bots/mixins/narrative.py:24` drags in the runner and builders.

`import parrot.bots` on its own is already clean (loads only `a2ui.models`,
`emission`, `serialization`); the leaks come from the chains above.

### Goals
- G1: Importing `parrot.manager`, `parrot.bots.data`, `parrot.bots.database.agent`,
  `parrot.bots.mixins.narrative`, `parrot.handlers.models` and `parrot.a2a.server`
  MUST NOT import `parrot.outputs.a2ui.builders`, `parrot.outputs.a2ui.catalog.basic`,
  `parrot.outputs.a2ui.catalog.parrot`, `parrot.outputs.a2ui.catalog.viz_core` or
  `parrot.outputs.a2ui.recipes.library`.
- G2: The process-wide `transformer_registry` still returns all built-in
  transformers on first `get()` / `manifest()` / `list()` / `register()` — no
  caller has to import `library` explicitly.
- G3: Behaviour is unchanged once a code path actually renders/runs: the catalog
  is populated by the time `builders` is used, recipe runs and A2UI endpoints
  return the same results.
- G4: A subprocess-based regression test locks G1 and G2 in so the leak cannot
  silently return.

### Non-Goals (explicitly out of scope)
- Making `parrot.outputs.a2ui.catalog` itself registry-lazy (the catalog package
  `__init__` already defers `basic`/`viz_core` to call time; its registrations are
  triggered by `builders.py`, which genuinely needs them).
- Removing pandas from `recipes/transformers.py` or from querysource/asyncdb
  (`app.py` imports pandas through `asyncdb` regardless).
- Deferring handler-class imports in `parrot.manager.manager` — the server
  registers those routes in `setup()` anyway; G1 is met by making the handler
  *modules* cheap instead.
- Lazy-loading `parrot.tools.infographic_toolkit` for bots that use it at class
  level (`bots/info.py`, `bots/flows/result_agent.py`) — they genuinely need it.
- Silencing the DEBUG log lines themselves.

---

## 2. Architectural Design

### Overview

Four mechanical changes, each at the narrowest point of its chain:

1. **Lazy built-ins on the transformer registry.** `TransformerRegistry` gains
   an optional `builtins_module: str | None` constructor argument. The module-level
   singleton is built with `builtins_module="parrot.outputs.a2ui.recipes.library"`;
   a private `_ensure_builtins()` imports it once (thread-safe, re-entrancy-guarded)
   at the top of `register()`, `get()`, `manifest()` and `list()`.
   `recipes/__init__.py` drops the `library` side-effect import.
   Loading built-ins *before* any `register()` preserves today's ordering, so an
   external transformer that collides with a built-in name still raises at its own
   registration, exactly as now. Bare `TransformerRegistry()` instances (unit tests)
   keep `builtins_module=None` and never load the library.
2. **Light `artifacts.py`.** Move `from parrot.outputs.a2ui.adapters.structured
   import SCHEMA_VERSION, root_component` from module level (line 29) into the one
   function that uses them (line ~148). `bots/data.py` and
   `bots/database/agent.py` then stay untouched and stop pulling `builders`.
3. **PEP 562 lazy `tools/infographic_recipes/__init__.py`.** Replace the eager
   imports with a `__getattr__` that resolves the six public names from
   `freeze` / `loader` / `runner` on first access (`__all__` unchanged,
   `TYPE_CHECKING` imports for type checkers).
4. **Server handler modules defer heavy runtime names.**
   - `handlers/infographic_recipes.py`, `handlers/ui_surfaces.py`: `RecipeRunner`
     under `TYPE_CHECKING` (both files already use
     `from __future__ import annotations`); `RecipeRunner(...)` construction and
     `except RecipeRunException` get a function-local import.
   - `handlers/infographic.py`: `InfographicToolkit` under `TYPE_CHECKING`,
     function-local import in `_get_render_toolkit()` and in the two methods that
     catch/inspect `InfographicValidationError`.
   - `handlers/a2ui.py` and `a2a/server.py`: function-local import of
     `BASIC_CATALOG_ID` (and `agent_capabilities` in `a2ui.py`) at the call site.
     `DEFAULT_CATALOG_ID` from `catalog.base` stays at module level (it does not
     register anything).

### Component Diagram
```
before:  manager ─→ handlers.* ─→ runner / toolkit / catalog.basic ─→ builders ─→ catalog.parrot+viz_core (register)
         handlers.models ─→ recipes/__init__ ─→ library (register 8 transformers)
         bots.data ─→ artifacts ─→ adapters.structured ─→ builders ─→ (register)

after:   manager ─→ handlers.*            (runner/toolkit/catalog.basic imported on first request)
         handlers.models ─→ recipes/__init__   (library imported on first registry access)
         bots.data ─→ artifacts            (structured/builders imported on first artifact build)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TransformerRegistry` (`recipes/transformers.py:61`) | modifies | new ctor arg + `_ensure_builtins()` |
| `transformer_registry` singleton (`transformers.py:161`) | modifies | built with `builtins_module=` |
| `recipes/__init__.py:15` | modifies | side-effect import removed |
| `artifacts.py:29` | modifies | import moved into function |
| `tools/infographic_recipes/__init__.py` | modifies | PEP 562 `__getattr__` |
| server handlers + `a2a/server.py` | modifies | function-local / `TYPE_CHECKING` imports |

### Data Models
None.

### New Public Interfaces
None. `TransformerRegistry.__init__` gains a keyword-only optional argument;
all existing call sites keep working.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: lazy transformer built-ins | yes | ctor kwarg `builtins_module`, `_ensure_builtins()` called first in `register/get/manifest/list`, `threading.Lock` + `_builtins_loaded` flag set *before* import (re-entrancy) | — |
| M2: light artifacts | yes | one import moved into the function at `artifacts.py:~148` | — |
| M3: lazy infographic_recipes package | yes | PEP 562 `__getattr__` over a name→module map; `__all__` unchanged | — |
| M4: server handler deferral | yes | `TYPE_CHECKING` + function-local imports at the listed edit sites | — |
| M5: import-isolation regression tests | yes | subprocess `python -c` per entry module, assert forbidden set ∩ `sys.modules` is empty | — |

### Module 1: Lazy transformer built-ins
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py`, `.../recipes/__init__.py`
- **Responsibility**: populate the singleton registry with built-ins on first use instead of at package import.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py:61
  class TransformerRegistry:  # verified: transformers.py:61
      def __init__(self, *, builtins_module: str | None = None) -> None:  # was: def __init__(self) -> None  (transformers.py:71)
          """Create a registry.

          Args:
              builtins_module: Dotted module whose import registers the built-in
                  transformers (side effect). Imported once, lazily, on the first
                  register/get/manifest/list call. ``None`` = no built-ins.
          """
      def _ensure_builtins(self) -> None:
          """Import ``builtins_module`` exactly once (thread-safe, re-entrant safe).

          The loaded flag is set before the import so the decorator calls made by
          the built-ins module (which call ``register``) do not recurse.
          """
      def register(...) -> RegisteredTransformer: ...   # transformers.py:74 — calls _ensure_builtins() first
      def get(self, name: str) -> RegisteredTransformer: ...  # :117 — calls _ensure_builtins() first
      def manifest(self, name: str) -> TransformerManifest: ...  # :137 — via get()
      def list(self) -> list[TransformerManifest]: ...  # :151 — calls _ensure_builtins() first

  transformer_registry = TransformerRegistry(builtins_module="parrot.outputs.a2ui.recipes.library")  # :161
  ```
  `recipes/__init__.py:15` (`from parrot.outputs.a2ui.recipes import library as _library  # noqa: F401`)
  is deleted, along with the comment block above it (lines 10-14), replaced by a
  one-line note that built-ins load on first registry access.

### Module 2: Light artifacts
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py`
- **Responsibility**: stop `artifacts` from importing `adapters.structured` (→ `builders` → catalog registrations) at module import.
- **Depends on**: —
- **Interface Skeleton**: no signature changes. The import at `artifacts.py:29` moves
  into the body of the function that builds the `"schemaVersion"` / `"definition"`
  dict (`artifacts.py:148-149`), with `# noqa: PLC0415 — lazy on purpose (FEAT-668)`.

### Module 3: Lazy `parrot.tools.infographic_recipes` package
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py`
- **Responsibility**: importing a leaf submodule (`figure_guard`, `loader`) must not import `runner`/`freeze`.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py:12-18
  from typing import TYPE_CHECKING, Any
  if TYPE_CHECKING:
      from parrot.tools.infographic_recipes.freeze import (FreezeProvenanceError, FreezeValidationError,
                                                            freeze_session_envelope)
      from parrot.tools.infographic_recipes.loader import load_transformer_module
      from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner

  _LAZY: dict[str, str]  # public name -> submodule ("freeze" | "loader" | "runner")
  __all__ = [...]        # unchanged (verified: __init__.py:20-27)

  def __getattr__(name: str) -> Any:
      """Resolve a public name from its submodule on first access (PEP 562).

      Raises:
          AttributeError: for names not in ``_LAZY``.
      """
  ```

### Module 4: Server handler deferral
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/{infographic_recipes,ui_surfaces,infographic,a2ui}.py`, `packages/ai-parrot-server/src/parrot/a2a/server.py`
- **Responsibility**: importing these modules must not import `runner`, `infographic_toolkit`, `catalog.basic` or `catalog.export`.
- **Depends on**: M2 + M3 for the full effect (M4's own edits are independent; the G1 test for `parrot.manager` passes only once M1–M4 are all in).
- **Interface Skeleton**: no signature changes. Annotation-only names
  (`RecipeRunner`, `InfographicToolkit`) move under `if TYPE_CHECKING:`; runtime uses
  (`RecipeRunner(...)` at `infographic_recipes.py:116`, `except RecipeRunException`
  at `infographic_recipes.py:291` / `ui_surfaces.py:685`, `InfographicToolkit(` at
  `infographic.py:535`, `InfographicValidationError` at `infographic.py:403,647`,
  `BASIC_CATALOG_ID` / `agent_capabilities` at `a2ui.py:242`, `BASIC_CATALOG_ID` at
  `a2a/server.py:179`) get a function-local import immediately before use.

### Module 5: Import-isolation regression tests
- **Path**: `packages/ai-parrot/tests/outputs/a2ui/test_lazy_imports.py` (new),
  `packages/ai-parrot-server/tests/test_a2ui_lazy_imports.py` (new)
- **Responsibility**: lock G1/G2.
- **Depends on**: M1–M4
- **Interface Skeleton**:
  ```python
  FORBIDDEN: frozenset[str] = frozenset({
      "parrot.outputs.a2ui.builders",
      "parrot.outputs.a2ui.catalog.basic",
      "parrot.outputs.a2ui.catalog.parrot",
      "parrot.outputs.a2ui.catalog.viz_core",
      "parrot.outputs.a2ui.recipes.library",
  })

  def _loaded_after_import(module: str) -> set[str]:
      """Run ``python -c 'import <module>'`` in a fresh subprocess and return the
      subset of FORBIDDEN present in ``sys.modules`` afterwards."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_registry_singleton_loads_builtins_on_first_get` | M1 | fresh subprocess: `import parrot.outputs.a2ui.recipes` → `library` not in `sys.modules`; `transformer_registry.get("day_totals")` succeeds and `library` is now loaded |
| `test_registry_list_returns_all_builtins` | M1 | `list()` names ⊇ the 8 built-ins (`day_totals`, `division_breakdown`, `variance_analysis`, `top_movers`, `narrative_facts`, `groupby_aggregate`, `pivot`, `latest_vs_baseline`) |
| `test_bare_registry_has_no_builtins` | M1 | `TransformerRegistry().list() == []` (existing `test_transformers.py` keeps passing) |
| `test_register_collision_with_builtin_still_raises` | M1 | registering a different func under `day_totals` on the singleton raises `ValueError` even when it is the first registry call |
| `test_artifacts_import_is_light` | M2 | `import parrot.outputs.a2ui.artifacts` loads nothing in FORBIDDEN |
| `test_core_entrypoints_do_not_load_a2ui_heavy` | M2, M3 | parametrized over `parrot.bots`, `parrot.bots.data`, `parrot.bots.database.agent`, `parrot.bots.mixins.narrative`, `parrot.tools.infographic_recipes.figure_guard` |
| `test_infographic_recipes_lazy_attrs_resolve` | M3 | `from parrot.tools.infographic_recipes import RecipeRunner, load_transformer_module` still works; unknown name raises `AttributeError` |

### Integration Tests
| Test | Description |
|---|---|
| `test_server_entrypoints_do_not_load_a2ui_heavy` | parametrized over `parrot.manager`, `parrot.handlers.models`, `parrot.handlers.a2ui`, `parrot.handlers.infographic_recipes`, `parrot.handlers.ui_surfaces`, `parrot.handlers.infographic`, `parrot.a2a.server` |
| existing suites | `packages/ai-parrot/tests/outputs/a2ui/recipes/`, `packages/ai-parrot/tests/outputs/a2ui/`, `packages/ai-parrot-server/tests/handlers/` stay green |

### Test Data / Fixtures
None — subprocess `python -c` with the current interpreter (`sys.executable`) and an
inherited `PYTHONPATH` (worktree rule: tests run with `PYTHONPATH=packages/<dist>/src`).

---

## 5. Acceptance Criteria

- [ ] AC1: in a fresh interpreter, importing each module listed under G1 leaves
      `FORBIDDEN ∩ sys.modules` empty (M5 tests green).
- [ ] AC2: `transformer_registry.get/manifest/list/register` see all 8 built-ins with
      no explicit `library` import; `TransformerRegistry()` instances stay empty.
- [ ] AC3: a name collision between an external transformer and a built-in raises
      `ValueError` at the external registration, as before.
- [ ] AC4: `from parrot.tools.infographic_recipes import <name>` works for every name
      in its `__all__`.
- [ ] AC5: existing tests under `packages/ai-parrot/tests/outputs/a2ui/` and
      `packages/ai-parrot-server/tests/handlers/` pass unchanged.
- [ ] AC6: `python -X importtime -c "import parrot.bots.data"` no longer lists
      `parrot.outputs.a2ui.builders` (evidence saved to `artifacts/logs/`).
- [ ] AC7: `ruff check` clean on every touched file (function-local imports carry
      `# noqa: PLC0415` where ruff flags them).
- [ ] No breaking change to any public import path.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.outputs.a2ui.recipes.transformers import TransformerRegistry, transformer_registry, infographic_transformer  # verified: recipes/transformers.py:61,161,164
from parrot.outputs.a2ui.adapters.structured import SCHEMA_VERSION, root_component  # verified: artifacts.py:29
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner  # verified: runner.py:91; tools/infographic_recipes/__init__.py:18
from parrot.tools.infographic_recipes.freeze import FreezeProvenanceError, FreezeValidationError, freeze_session_envelope  # verified: tools/infographic_recipes/__init__.py:12-16
from parrot.tools.infographic_recipes.loader import load_transformer_module  # verified: tools/infographic_recipes/__init__.py:17
from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicValidationError  # verified: infographic_toolkit.py:146; handlers/infographic.py:47 (relative ..tools)
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID  # verified: handlers/a2ui.py:58 — no registration side effect
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID  # verified: catalog/basic/__init__.py:44 — module registers basic components at import (line 202)
from parrot.outputs.a2ui.catalog.export import agent_capabilities  # verified: handlers/a2ui.py:60 — imports catalog.basic (export.py:32)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
class TransformerRegistry:                                   # line 61
    def __init__(self) -> None:                              # line 71
        self._transformers: dict[str, RegisteredTransformer] = {}   # line 72
    def register(self, name: str, func: TransformerFunc, *, requires_columns: dict[str, list[str]] | None = None,
                 description: str = "", params_schema: dict[str, Any] | None = None) -> RegisteredTransformer:  # line 74
    def get(self, name: str) -> RegisteredTransformer:      # line 117
    def manifest(self, name: str) -> TransformerManifest:   # line 137
    def list(self) -> list[TransformerManifest]:            # line 151
transformer_registry = TransformerRegistry()                 # line 161
def infographic_transformer(...)                             # line 164 — decorator calling transformer_registry.register

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunException(Exception):                         # line 91
    def __init__(self, error: RecipeRunError) -> None:       # line 94

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicValidationError(Exception):                 # line 146
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_ensure_builtins()` | `parrot.outputs.a2ui.recipes.library` | `importlib.import_module` | `recipes/library.py:35` (registers via `infographic_transformer`) |
| lazy `__getattr__` | `freeze` / `loader` / `runner` submodules | `importlib.import_module` | `tools/infographic_recipes/__init__.py:12-18` |

### Does NOT Exist (Anti-Hallucination)
- ~~`TransformerRegistry.load_builtins()` / `ensure_loaded()`~~ — no public loader exists; M1 adds the *private* `_ensure_builtins()` only.
- ~~`parrot.outputs.a2ui.recipes.builtins`~~ — the built-ins module is `recipes.library`.
- ~~a lazy/`__getattr__` mechanism in `parrot/outputs/a2ui/adapters/__init__.py` or `graph/__init__.py`~~ — both are eager; out of scope (the chains go through `artifacts.py` / `builders.py`, not those inits).
- ~~`RecipeRunException` in a light module~~ — it lives only in `runner.py`; do not move it (would change a public import path).
- ~~direct `transformer_registry._transformers` access outside `transformers.py`~~ — grep found none in `src/` or `tests/`.

### Edit Sites (Blueprint Anchors)

Verified against: `06a201b63` (origin/dev)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py` | MODIFY | `        self._transformers: dict[str, RegisteredTransformer] = {}` | `transformers.py:72` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py` | MODIFY | `        existing = self._transformers.get(name)` | `transformers.py:100` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py` | MODIFY | `            return self._transformers[name]` | `transformers.py:130` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py` | MODIFY | `        return [entry.manifest for entry in self._transformers.values()]` | `transformers.py:157` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py` | MODIFY | `transformer_registry = TransformerRegistry()` | `transformers.py:161` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py` | MODIFY | `from parrot.outputs.a2ui.recipes import library as _library  # noqa: F401` | `__init__.py:15` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` | MODIFY | `from parrot.outputs.a2ui.adapters.structured import SCHEMA_VERSION, root_component` | `artifacts.py:29` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` | MODIFY | `                "schemaVersion": SCHEMA_VERSION,` | `artifacts.py:148` | 1 |
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py` | MODIFY | `from parrot.tools.infographic_recipes.freeze import (` | `__init__.py:12` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` | MODIFY | `from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner` | `infographic_recipes.py:43` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` | MODIFY | `        recipe_runner = RecipeRunner(recipe_store, dataset_manager, artifact_store=artifact_store)` | `infographic_recipes.py:116` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` | MODIFY | `        except RecipeRunException as exc:` | `infographic_recipes.py:291` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | `from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner` | `ui_surfaces.py:49` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | `        except RecipeRunException as exc:` | `ui_surfaces.py:685` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/infographic.py` | MODIFY | `from ..tools.infographic_toolkit import InfographicToolkit, InfographicValidationError` | `infographic.py:47` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/infographic.py` | MODIFY | `        except InfographicValidationError as exc:` | `infographic.py:403` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/infographic.py` | MODIFY | `            toolkit = InfographicToolkit(` | `infographic.py:535` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/infographic.py` | MODIFY | `            code = exc.code if isinstance(exc, InfographicValidationError) else type(exc).__name__` | `infographic.py:647` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` | MODIFY | `from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID` | `a2ui.py:59` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` | MODIFY | `from parrot.outputs.a2ui.catalog.export import agent_capabilities` | `a2ui.py:60` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` | MODIFY | `        return self.json_response(agent_capabilities([DEFAULT_CATALOG_ID, BASIC_CATALOG_ID]), status=200)` | `a2ui.py:242` | 1 |
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | `from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID` | `server.py:59` | 1 |
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | `        register_a2ui_extension(self.capabilities, [DEFAULT_CATALOG_ID, BASIC_CATALOG_ID])` | `server.py:179` | 1 |
| `packages/ai-parrot/tests/outputs/a2ui/test_lazy_imports.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/test_a2ui_lazy_imports.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Function-local imports carry `# noqa: PLC0415 — lazy on purpose (FEAT-668)`,
  matching the existing convention in `parrot/cli/agent_repl.py:257-259`.
- Annotation-only names go under `if TYPE_CHECKING:`; every touched module already
  has `from __future__ import annotations` (verified: `artifacts.py:18`,
  `handlers/infographic_recipes.py:27`, `handlers/ui_surfaces.py:17`,
  `handlers/infographic.py:13`, `handlers/a2ui.py:39`, `a2a/server.py:26`) — check
  `tools/infographic_recipes/__init__.py` and add it if needed.
- `_ensure_builtins()` uses `threading.Lock` (the registry may be touched from
  executor threads) and sets the loaded flag *before* `importlib.import_module` so
  the built-ins module's own `@infographic_transformer` → `register()` calls do not
  recurse. On import failure, reset the flag and re-raise (no half-loaded silent state).

### Known Risks / Gotchas
- **Hidden reliance on side-effect registration.** Code that reads the registry via a
  path other than `register/get/manifest/list` would see an empty registry. Grep found
  no `._transformers` access outside `transformers.py`; the M1 tests cover the four
  public entry points.
- **Ordering of external transformers.** Loading built-ins at the top of `register()`
  keeps today's "built-ins first" order, so collisions still fail at the external
  registration (AC3).
- **`isinstance`/`except` on a lazily imported class** must import the *same* class
  object — always import from the defining module (`runner`, `infographic_toolkit`),
  never re-define.
- **Residual chains.** If an M5 test still fails after M1–M4, the remaining importer
  must be named in the task's Completion Note and fixed with the same pattern only if
  it is one of the files in §6 Edit Sites; anything else is a follow-up, not scope creep.
- **Worktree imports.** The shared `.venv` is editable-installed against the main
  checkout — run the subprocess tests with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
  and pass `env=os.environ` to the subprocess so it inherits it.

### External Dependencies
None.

---

## 8. Open Questions

- [x] Should `catalog.base`'s import of `jsonschema` (pulled by `handlers/ui_surfaces.py:45`
      via `CatalogValidationError`) also be deferred? It registers nothing; left out of
      scope unless importtime shows it matters. — *Owner: Jesus Lara*: left out of scope

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-668-a2ui-lazy-imports`); each task in its own sub-worktree.
- **Module dependency graph**: M1, M2, M3, M4 are independent (no shared files, no
  symbol imported from each other's changes). M5 → M1, M2, M3, M4 (its assertions only
  pass once all four land).
- **Shared files**: none.
- **Exclusive resources**: none (no lockfile, migration or extension rebuild).
- **Cross-feature dependencies**: none.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec written from a direct import-trace investigation)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-14 | Jesus Lara | Initial draft (from sys.meta_path import trace) |
