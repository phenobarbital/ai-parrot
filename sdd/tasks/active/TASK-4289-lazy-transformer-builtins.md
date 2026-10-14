# TASK-4289: Lazy built-in transformer registration

**Feature**: FEAT-668 — A2UI Lazy Imports
**Spec**: `sdd/specs/a2ui-lazy-imports.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. `parrot/outputs/a2ui/recipes/__init__.py:15` imports `library`
purely for its side effect, so any import of the `recipes` package (e.g.
`handlers/models/recipes.py:24` → `recipes.models`) registers the 8 built-in
transformers and imports pandas. This task makes the process-wide
`transformer_registry` load its built-ins on first use instead.

---

## Scope

- Add a keyword-only `builtins_module: str | None = None` argument to `TransformerRegistry.__init__`.
- Add a private, thread-safe, re-entrancy-safe `_ensure_builtins()` and call it first in `register()`, `get()` and `list()` (`manifest()` already goes through `get()`).
- Build the singleton as `TransformerRegistry(builtins_module="parrot.outputs.a2ui.recipes.library")`.
- Delete the `library` side-effect import (and its comment block) from `recipes/__init__.py`.
- Add unit tests to `test_transformers.py`.

**NOT in scope**: the catalog registries, `artifacts.py`, `parrot.tools.infographic_recipes`, server handlers, and the import-isolation subprocess tests (TASK-4290–4293).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py` | MODIFY | ctor kwarg + `_ensure_builtins()` + singleton |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py` | MODIFY | drop the `library` side-effect import |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_transformers.py` | MODIFY | lazy-built-ins unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.recipes.transformers import TransformerRegistry, transformer_registry, infographic_transformer  # verified: transformers.py:61,161,164
import importlib   # stdlib — new import in transformers.py
import threading   # stdlib — new import in transformers.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
logger = ...                                                  # module logger used at line 114
class TransformerRegistry:                                    # line 61
    def __init__(self) -> None:                               # line 71
        self._transformers: dict[str, RegisteredTransformer] = {}   # line 72
    def register(self, name: str, func: TransformerFunc, *, requires_columns=None, description: str = "",
                 params_schema=None) -> RegisteredTransformer:      # line 74; first body line 100: `existing = self._transformers.get(name)`
    def get(self, name: str) -> RegisteredTransformer:       # line 117; `try:` then line 130 `return self._transformers[name]`
    def manifest(self, name: str) -> TransformerManifest:    # line 137 — returns self.get(name).manifest
    def list(self) -> list[TransformerManifest]:             # line 151; body line 157
transformer_registry = TransformerRegistry()                  # line 161
def infographic_transformer(name, *, requires_columns=None, description="", params_schema=None)  # line 164 → calls transformer_registry.register

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer  # line 35
# registers: day_totals, division_breakdown, variance_analysis, top_movers,
#            narrative_facts, groupby_aggregate, pivot, latest_vs_baseline
```

### Does NOT Exist
- ~~`TransformerRegistry.load_builtins()` / `ensure_loaded()`~~ — do not add a public method; only the private `_ensure_builtins()`.
- ~~`parrot.outputs.a2ui.recipes.builtins`~~ — the built-ins module is `recipes.library`.
- ~~direct `transformer_registry._transformers` reads outside `transformers.py`~~ — none exist (grep verified), so the four public methods are the only entry points to guard.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/recipes/test_transformers.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py#TransformerRegistry",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py#TransformerRegistry.register",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py#TransformerRegistry.get",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py#TransformerRegistry.list",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py#infographic_transformer"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Set `_builtins_loaded = True` **before** `importlib.import_module(...)`: the built-ins module calls `register()` through `@infographic_transformer`, and `register()` calls `_ensure_builtins()` — without the early flag it recurses.
- Use a `threading.RLock`, not a `Lock`: the re-entrant `register()` calls happen on the same thread while the lock is held.
- On import failure, reset `_builtins_loaded = False` and re-raise — no silent half-loaded state.
- Call `_ensure_builtins()` at the top of `register()` too, so built-ins always register before any external transformer. That keeps today's collision behaviour (spec AC3).
- Bare `TransformerRegistry()` (used by the existing tests at `test_transformers.py:13,39,50,64`) must never import anything.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import importlib` and `import threading` to the stdlib imports in `transformers.py` — *why*: they are needed by `_ensure_builtins()`.
2. Replace `__init__` and add `_ensure_builtins()` — *why*: spec §3 M1 skeleton.
3. Insert `self._ensure_builtins()` as the first statement of `register`, `get` and `list` — *why*: these are the only paths that read or write `_transformers`.
4. Change the singleton constructor call — *why*: only the process-wide registry has built-ins.
5. Remove the `library` import and its comment block from `recipes/__init__.py` — *why*: that eager import is the bug.
6. Add the tests and run the Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self._transformers: dict\[str, RegisteredTransformer\] = {}' transformers.py)
# REPLACE `def __init__(self) -> None:` (line 71) + its body line 72 with:
    def __init__(self, *, builtins_module: str | None = None) -> None:
        """Create a registry.

        Args:
            builtins_module: Dotted module whose import registers the built-in
                transformers (side effect). Imported once, lazily, on the first
                register/get/manifest/list call. ``None`` = no built-ins.
        """
        self._transformers: dict[str, RegisteredTransformer] = {}
        self._builtins_module = builtins_module
        self._builtins_loaded = builtins_module is None
        self._builtins_lock = threading.RLock()

    def _ensure_builtins(self) -> None:
        """Import ``builtins_module`` exactly once (thread-safe, re-entrant safe).

        The loaded flag is set before the import so the decorator calls made by
        the built-ins module (which call ``register``) do not recurse.
        """
        if self._builtins_loaded:
            return
        with self._builtins_lock:
            if self._builtins_loaded:
                return
            self._builtins_loaded = True
            try:
                importlib.import_module(self._builtins_module)
            except Exception:
                self._builtins_loaded = False
                raise
```
```python
# occurrences: 1 each — insert `        self._ensure_builtins()` as the FIRST body statement of:
#   register()  → directly above `        existing = self._transformers.get(name)`              (line 100)
#   get()       → directly above the `        try:` whose body is `return self._transformers[name]` (line 129-130)
#   list()      → directly above `        return [entry.manifest for entry in self._transformers.values()]` (line 157)
```
```python
# occurrences: 1 (verified: grep -c '^transformer_registry = TransformerRegistry()' transformers.py) — line 161
#: Process-wide transformer registry; built-ins load lazily on first use (FEAT-668).
transformer_registry = TransformerRegistry(builtins_module="parrot.outputs.a2ui.recipes.library")
```
**Why this shape**: it implements the spec §3 M1 skeleton exactly. The double-checked flag keeps the hot path lock-free once loaded.

### `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.outputs.a2ui.recipes import library as _library  # noqa: F401' __init__.py) — line 15
# DELETE lines 10-15 (the "# Import side effect ONLY ..." comment block + the import) and put in their place:
# Built-in transformers (recipes.library) register lazily on the first
# transformer_registry access — not at package import (FEAT-668).
```
**Why**: importing `recipes.models` / `recipes.store` must not import pandas-heavy `library`.

### `packages/ai-parrot/tests/outputs/a2ui/recipes/test_transformers.py` (MODIFY — append)
```python
_BUILTINS = {
    "day_totals", "division_breakdown", "variance_analysis", "top_movers",
    "narrative_facts", "groupby_aggregate", "pivot", "latest_vs_baseline",
}


def test_bare_registry_has_no_builtins():
    """A registry built without builtins_module never imports anything."""
    assert TransformerRegistry().list() == []


def test_singleton_list_contains_all_builtins():
    from parrot.outputs.a2ui.recipes.transformers import transformer_registry

    assert _BUILTINS <= {m.name for m in transformer_registry.list()}


def test_package_import_does_not_load_library_until_first_access():
    # FILL IN: subprocess probe (pattern: test_import_rule.py:47-65 — sys.path.insert(0, src_dir)):
    #   import parrot.outputs.a2ui.recipes → assert "parrot.outputs.a2ui.recipes.library" not in sys.modules;
    #   transformer_registry.get("day_totals") → assert it IS in sys.modules now. Bounded by spec AC2.


def test_register_collision_with_builtin_raises():
    # FILL IN: on a registry built with builtins_module="parrot.outputs.a2ui.recipes.library"
    #   (a NEW instance, so the singleton stays untouched), register a different func under
    #   "day_totals" as the FIRST call → pytest.raises(ValueError). Bounded by spec AC3.
```

### FILL IN checklist
- [ ] `test_package_import_does_not_load_library_until_first_access` — subprocess probe; bounded by AC2.
- [ ] `test_register_collision_with_builtin_raises` — needs a fresh registry instance; bounded by AC3. Note: re-importing `library` for a second registry instance is a no-op (module cache), so that registry would stay EMPTY. Build it by pointing `builtins_module` at a tiny test-local module, or assert the collision on the singleton with a unique throwaway func and no cleanup needed (the raise leaves the registry unchanged). Pick one and say which in the Completion Note.

---

## Acceptance Criteria

- [ ] `import parrot.outputs.a2ui.recipes` does not load `parrot.outputs.a2ui.recipes.library`.
- [ ] `transformer_registry.get/manifest/list` return all 8 built-ins with no explicit `library` import (spec AC2).
- [ ] Collision with a built-in name still raises `ValueError` (spec AC3).
- [ ] Existing `test_transformers.py`, `test_library.py`, `test_import_rule.py` pass unchanged.
- [ ] `ruff check` clean on the touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/test_transformers.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/test_library.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/test_import_rule.py -q`

---

## Test Specification

See the `test_transformers.py` block in the Implementation Blueprint.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug a2ui-lazy-imports --feature-id FEAT-668`).
2. Read the spec. 3. No dependencies. 4. Verify the Codebase Contract.
5. Mark `in-progress` in `sdd/tasks/index/a2ui-lazy-imports.json`. 6. Implement from the blueprint.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`. 8. Commit only the listed files.
9. `scripts/sdd/close_task.sh TASK-4289 a2ui-lazy-imports verified`. 10. Fill in the Completion Note and commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
