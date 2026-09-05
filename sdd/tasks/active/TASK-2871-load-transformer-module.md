# TASK-2871: `load_transformer_module` — host-side loader for a recipe's transformers

**Feature**: FEAT-528 — Postgres recipe store + agent-package importability
**Spec**: `sdd/specs/pg-recipe-store-and-agent-package-importability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, item 3. A host that replays a recipe needs the recipe's `@infographic_transformer` functions registered in-process — and nothing else from the agent: no class, no LLM, no toolkit, no `ai-parrot-visualizations`. Today registration is purely an import side effect, and the only way to trigger it for `flex_dashboard/transformers.py` is `import agents.flex_dashboard.transformers`, which a host with its own `agents/` package cannot do (FieldSync reproduced this twice).

This helper is the supported answer to "how do I replay this recipe in my own service", and it is what TASK-2872 uses inside `flex_dashboard.py` itself.

---

## Scope

- Add `load_transformer_module(path: str | Path, *, name: str | None = None) -> ModuleType` to `packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py` (or a sibling `loader.py` re-exported there) and add it to `__all__`.
- Semantics:
  - `path` is a module file (e.g. `.../flex_dashboard/transformers.py`).
  - If `path.parent / "__init__.py"` exists, the module is loaded **as a submodule of a synthetic package** so that its relative imports (`from .normalize import …`, TASK-2872) resolve: register `sys.modules[pkg]` from `importlib.util.spec_from_file_location(pkg, parent/"__init__.py", submodule_search_locations=[str(parent)])`, then `importlib.import_module(f"{pkg}.{path.stem}")`.
  - Otherwise load the file directly with `spec_from_file_location(name, path)` + `module_from_spec` + `sys.modules[name] = module` + `spec.loader.exec_module(module)`.
  - `name` defaults to a deterministic synthetic name derived from the resolved path (e.g. `parrot_transformers_<sha1(path)[:12]>`), so a second call for the same path returns the module already in `sys.modules` and does not re-execute registration.
  - Raises `FileNotFoundError` for a missing path and re-raises import errors unchanged.
- Unit test with a temporary package written by the test (no flex dependency): one module decorated with `@infographic_transformer`, loaded under a parent NOT named `agents`, resolvable in `transformer_registry`.

**NOT in scope**: editing `agents/flex_dashboard*` (TASK-2872); `PgRecipeStore` (TASK-2870); docs (TASK-2874).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/loader.py` | CREATE | `load_transformer_module` |
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py` | MODIFY | re-export + `__all__` |
| `tests/unit/tools/test_load_transformer_module.py` | CREATE | synthetic-package test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_recipes import RecipeRunner, RecipeRunException   # __init__.py:13 — existing exports
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer, transformer_registry
#   transformers.py:164 (decorator) · :161 (module singleton) · TransformerRegistry :61 · .get(name) :117
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py — current content (:1-21)
from parrot.tools.infographic_recipes.freeze import (FreezeProvenanceError, FreezeValidationError, freeze_session_envelope)
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner
__all__ = ["RecipeRunException", "RecipeRunner", "FreezeProvenanceError", "FreezeValidationError", "freeze_session_envelope"]
# Module docstring (:1-6): this package "lives OUTSIDE parrot.outputs.a2ui so it may import DatasetManager" —
# the loader belongs here for the same one-way-import reason; do NOT put it under parrot.outputs.a2ui.

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
class TransformerRegistry:                                  # :61
    def get(self, name: str) -> RegisteredTransformer       # :117  (raises on unknown name — check the exact exception before asserting)
transformer_registry = TransformerRegistry()                # :161
def infographic_transformer(...)                            # :164  decorator; registers on import
```

### Does NOT Exist
- ~~A plugin / entry-point mechanism for transformers~~ — none; registration is an import side effect (spec §6).
- ~~`load_transformer_module` anywhere in the installed wheel or on `dev`~~ — greenfield.
- ~~`agents.*` as an importable package from a host~~ — the repo-root `agents/` is not distributed (spec §3 Module 2 reframing).

---

## Implementation Notes

### Pattern to Follow
```python
def load_transformer_module(path: str | Path, *, name: str | None = None) -> ModuleType:
    """Import a transformer module by file location so its @infographic_transformer functions register."""
    file = Path(path).resolve()
    if not file.is_file():
        raise FileNotFoundError(file)
    pkg_init = file.parent / "__init__.py"
    if pkg_init.is_file():
        pkg = name or f"parrot_transformers_{_digest(file.parent)}"
        if pkg not in sys.modules:
            spec = importlib.util.spec_from_file_location(pkg, pkg_init, submodule_search_locations=[str(file.parent)])
            module = importlib.util.module_from_spec(spec); sys.modules[pkg] = module; spec.loader.exec_module(module)
        return importlib.import_module(f"{pkg}.{file.stem}")
    mod_name = name or f"parrot_transformers_{_digest(file)}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, file)
    module = importlib.util.module_from_spec(spec); sys.modules[mod_name] = module; spec.loader.exec_module(module)
    return module
```

### Key Constraints
- Deterministic synthetic names → idempotent loads; do not register the same transformer twice.
- Never mutate `sys.path`.
- The package-aware branch is REQUIRED: after TASK-2872, `flex_dashboard/transformers.py` uses `from .normalize import …`, which only resolves inside a package.
- Google-style docstring; type hints; no `print`.

### References in Codebase
- `agents/flex_dashboard.py:83` — the import this helper replaces (TASK-2872 does the replacing)
- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py` — stock transformers registered by import side effect

---

## Acceptance Criteria

- [ ] `from parrot.tools.infographic_recipes import load_transformer_module` works and is in `__all__`
- [ ] `test_load_transformer_module_registers`: a synthetic package (parent named `hostpkg`, not `agents`) with a `from .helpers import …` relative import loads and its transformer resolves via `transformer_registry.get(...)`
- [ ] Loading the same path twice returns the same module object and registers nothing twice
- [ ] Missing path → `FileNotFoundError`
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/infographic_recipes/` clean

---

## Test Specification

```python
# tests/unit/tools/test_load_transformer_module.py
import sys, textwrap
from parrot.tools.infographic_recipes import load_transformer_module
from parrot.outputs.a2ui.recipes.transformers import transformer_registry

def _write_pkg(tmp_path):
    pkg = tmp_path / "hostpkg"; pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "helpers.py").write_text("def double(x):\n    return 2 * x\n")
    (pkg / "transformers.py").write_text(textwrap.dedent('''
        from parrot.outputs.a2ui.recipes.transformers import infographic_transformer
        from .helpers import double
        @infographic_transformer(name="t_2871_probe")   # match the decorator's real signature before writing
        def probe(frames, params): return {"v": double(1)}
    '''))
    return pkg / "transformers.py"

def test_load_transformer_module_registers(tmp_path):
    mod = load_transformer_module(_write_pkg(tmp_path))
    assert transformer_registry.get("t_2871_probe") is not None
    assert load_transformer_module(mod.__file__) is mod          # idempotent

def test_missing_path_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_transformer_module(tmp_path / "nope.py")
```

---

## Agent Instructions

1. Read `transformers.py:61-200` to confirm the decorator's signature and the registry's unknown-name behaviour before writing the test assertions.
2. Implement, run `pytest tests/unit/tools/test_load_transformer_module.py -v`.
3. Move this file to `sdd/tasks/completed/`, set the index entry to `done`, fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
