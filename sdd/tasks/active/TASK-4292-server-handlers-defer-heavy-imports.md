# TASK-4292: Server handler modules defer heavy A2UI imports

**Feature**: FEAT-668 — A2UI Lazy Imports
**Spec**: `sdd/specs/a2ui-lazy-imports.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. `parrot.manager.manager` imports every handler module at
module level (`manager.py:37-46`). Several of those modules import heavy runtime
classes that they only use inside method bodies, `except` clauses or
annotations:

- `RecipeRunner` / `RecipeRunException` in `handlers/infographic_recipes.py:43` and `handlers/ui_surfaces.py:49`
- `InfographicToolkit` / `InfographicValidationError` in `handlers/infographic.py:47`
- `catalog.basic` / `catalog.export` in `handlers/a2ui.py:59-60` and `a2a/server.py:59`

Each of these drags in `builders` and the catalog registrations when
`python run.py` starts. Measured on dev (a85ec8d48): importing
`parrot.handlers.infographic`, `.infographic_recipes` or `.ui_surfaces` loads
`runner`, `builders`, `catalog.basic` and `catalog.parrot`.

---

## Scope

- Move annotation-only uses of `RecipeRunner` / `InfographicToolkit` under `if TYPE_CHECKING:`. Every target file already has `from __future__ import annotations`.
- Add a function-local import right before each runtime use (listed in the blueprint).
- `DEFAULT_CATALOG_ID` (from `catalog.base`, which registers nothing) stays at module level.

**NOT in scope**: `parrot/manager/manager.py` (route registration stays as is; spec Non-Goal), `handlers/infographic_render.py`, `handlers/studio/toolkits.py`, `handlers/ui_surfaces.py:45` (`CatalogValidationError`, excluded by the resolved spec §8 question), and the regression tests (TASK-4293).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` | MODIFY | `RecipeRunner` under TYPE_CHECKING; local imports at :116, :291 |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | `RecipeRunner` under TYPE_CHECKING; local import at :685 |
| `packages/ai-parrot-server/src/parrot/handlers/infographic.py` | MODIFY | `InfographicToolkit` under TYPE_CHECKING; local imports at :403, :535, :647 |
| `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` | MODIFY | local import of `BASIC_CATALOG_ID` + `agent_capabilities` at :242 |
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | local import of `BASIC_CATALOG_ID` at :179 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner   # verified: handlers/infographic_recipes.py:43, handlers/ui_surfaces.py:49
from ..tools.infographic_toolkit import InfographicToolkit, InfographicValidationError  # verified: handlers/infographic.py:47 (relative; absolute = parrot.tools.infographic_toolkit, class at infographic_toolkit.py:146)
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID      # verified: handlers/a2ui.py:58, a2a/server.py:58 — KEEP at module level
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID       # verified: handlers/a2ui.py:59, a2a/server.py:59
from parrot.outputs.a2ui.catalog.export import agent_capabilities    # verified: handlers/a2ui.py:60
from typing import TYPE_CHECKING
```

### Existing Signatures to Use
```python
# handlers/infographic_recipes.py — `from __future__ import annotations` line 27; `from typing import Any, Dict, Optional` line 31
_default_recipe_runner: Optional[RecipeRunner] = None          # line 60 — annotation only (lazy under __future__)
def configure_recipe_runner(runner: RecipeRunner) -> None       # line 63 — annotation only
def get_recipe_runner() -> Optional[RecipeRunner]               # line 73 — annotation only
def register_recipe_routes(..., recipe_runner: Optional[RecipeRunner] = None, ...) -> RecipeRunner   # ~line 79-85
        recipe_runner = RecipeRunner(recipe_store, dataset_manager, artifact_store=artifact_store)   # line 116 — RUNTIME
    def runner(self) -> RecipeRunner                            # line 169 — annotation only
    async def post(self) -> web.Response                        # line 258
        except RecipeRunException as exc:                       # line 291 — RUNTIME

# handlers/ui_surfaces.py — `from __future__ import annotations` line 17; `from typing import Any` line 23
    def _recipe_runner(self) -> RecipeRunner | None             # line 369 — annotation only
    async def _refresh(self) -> web.Response                    # line 630
        except RecipeRunException as exc:                       # line 685 — RUNTIME

# handlers/infographic.py — `from __future__ import annotations` line 13; `from typing import Any, Dict, Optional` line 17
    async def _render_infographic_deterministic(self) -> web.Response   # line 331
        except InfographicValidationError as exc:               # line 403 — RUNTIME
    def _get_render_toolkit(self) -> InfographicToolkit         # line 497 — annotation + RUNTIME below
            toolkit = InfographicToolkit(                       # line 535 — RUNTIME
    async def _run_render_job(...)                              # line 602
            code = exc.code if isinstance(exc, InfographicValidationError) else type(exc).__name__   # line 647 — RUNTIME
            detail = exc.detail if isinstance(exc, InfographicValidationError) else str(exc)         # line 648 — RUNTIME

# handlers/a2ui.py — `from __future__ import annotations` line 39
    async def _get_capabilities(self) -> web.Response           # line 240
        return self.json_response(agent_capabilities([DEFAULT_CATALOG_ID, BASIC_CATALOG_ID]), status=200)   # line 242

# a2a/server.py — `from __future__ import annotations` line 26; `TYPE_CHECKING` already imported line 27; `if TYPE_CHECKING:` block line 64
class A2AServer:                                                # line 86
    def __init__(...)                                           # line 120
        register_a2ui_extension(self.capabilities, [DEFAULT_CATALOG_ID, BASIC_CATALOG_ID])   # line 179
```

### Does NOT Exist
- ~~tests that patch `parrot.handlers.<mod>.RecipeRunner` / `.InfographicToolkit` / `.BASIC_CATALOG_ID`~~ — grep over `packages/*/tests` found none, so moving the names off the module namespace breaks no patch target.
- ~~`RecipeRunException` in a light module~~ — it lives only in `runner.py:91`; do not move it.
- ~~other uses of `BASIC_CATALOG_ID` / `agent_capabilities` in `handlers/a2ui.py`~~ — only line 242 (line 97 is a docstring).
- ~~other uses of `BASIC_CATALOG_ID` in `a2a/server.py`~~ — only line 179.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/infographic.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/a2ui.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/a2a/server.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py#register_recipe_routes",
    "sym:packages/ai-parrot-server/src/parrot/handlers/infographic.py#InfographicTalk._get_render_toolkit",
    "sym:packages/ai-parrot-server/src/parrot/a2a/server.py#A2AServer.__init__"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **An `except X` clause evaluates `X` only when an exception actually reaches it**, so a local import placed *inside the `try` body* would be skipped if the `try` raised first. Put the local import **before the `try:`** of each guarded block — *because* `except RecipeRunException` with the name unbound raises `NameError`, which masks the real error.
- Always import from the defining module (`runner`, `infographic_toolkit`) so `isinstance`/`except` match the exact class object.
- Tag every local import `# noqa: PLC0415 — lazy on purpose (FEAT-668)`.
- `handlers/infographic.py` uses a relative import (`..tools.infographic_toolkit`). Keep that form in the TYPE_CHECKING block and in the local imports.

---

## Implementation Blueprint

### Steps (in order)
1. For each file, replace the module-level import with the TYPE_CHECKING form — *why*: annotation uses stay type-checkable without a runtime import.
2. Add each local import right before the `try:` / statement that needs the name at runtime — *why*: see the `except` constraint above.
3. Run the Validation Commands, then
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src python -c "import sys, parrot.handlers.a2ui, parrot.handlers.infographic_recipes, parrot.handlers.ui_surfaces, parrot.handlers.infographic, parrot.a2a.server; print(sorted(m for m in sys.modules if m.endswith(('a2ui.builders','catalog.basic','catalog.parrot','infographic_recipes.runner','infographic_toolkit'))))"`.
   The list may still be non-empty until TASK-4289/4290 land (`handlers/models` → `recipes` → `library`; `artifacts` → `builders`); paste it into the Completion Note.

### `handlers/infographic_recipes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner' infographic_recipes.py) — line 43
# REPLACE line 43 with (and add TYPE_CHECKING to the `from typing import ...` at line 31):
if TYPE_CHECKING:
    from parrot.tools.infographic_recipes.runner import RecipeRunner

# occurrences: 1 — line 116 `        recipe_runner = RecipeRunner(recipe_store, dataset_manager, artifact_store=artifact_store)`
# INSERT directly above it:
        from parrot.tools.infographic_recipes.runner import RecipeRunner  # noqa: PLC0415 — lazy on purpose (FEAT-668)

# occurrences: 1 — line 291 `        except RecipeRunException as exc:` in post() (line 258)
# FILL IN: insert `from parrot.tools.infographic_recipes.runner import RecipeRunException  # noqa: PLC0415 — lazy on purpose (FEAT-668)`
#   directly above the `        try:` that line 291 belongs to (line ~289) — bounded by the except constraint.
```

### `handlers/ui_surfaces.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner' ui_surfaces.py) — line 49
# REPLACE line 49 with (and add TYPE_CHECKING to `from typing import Any` at line 23):
if TYPE_CHECKING:
    from parrot.tools.infographic_recipes.runner import RecipeRunner
# NOTE: line 49 sits in the middle of the import block (pydantic/navigator imports follow at line 50+). Move the
#   `if TYPE_CHECKING:` block BELOW the last module-level import, so ruff E402 does not fire on the imports after it.

# occurrences: 1 — line 685 `        except RecipeRunException as exc:` in _refresh() (line 630)
# FILL IN: insert the local `RecipeRunException` import directly above the `        try:` at line ~677 — bounded by the except constraint.
```

### `handlers/infographic.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..tools.infographic_toolkit import InfographicToolkit, InfographicValidationError' infographic.py) — line 47
# REPLACE line 47 with (TYPE_CHECKING added to `from typing import ...` line 17; block placed after the last module-level import):
if TYPE_CHECKING:
    from ..tools.infographic_toolkit import InfographicToolkit

# line 403 `        except InfographicValidationError as exc:` inside _render_infographic_deterministic (line 331)
# FILL IN: insert `from ..tools.infographic_toolkit import InfographicValidationError  # noqa: PLC0415 — lazy on purpose (FEAT-668)`
#   directly above the `try:` that line 403 closes.

# line 535 `            toolkit = InfographicToolkit(` inside _get_render_toolkit (line 497)
# INSERT directly above it (same indentation):
            from ..tools.infographic_toolkit import InfographicToolkit  # noqa: PLC0415 — lazy on purpose (FEAT-668)

# lines 647-648 `isinstance(exc, InfographicValidationError)` inside _run_render_job (line 602)
# FILL IN: insert the local InfographicValidationError import directly above that method's outer `try:` — bounded by the except constraint
#   (the isinstance runs inside `except Exception`, so the name must already be bound).
```

### `handlers/a2ui.py` (MODIFY)
```python
# occurrences: 1 each (verified) — lines 59, 60
# DELETE:
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID
from parrot.outputs.a2ui.catalog.export import agent_capabilities

# occurrences: 1 — line 242 inside _get_capabilities (line 240)
# INSERT directly above `        return self.json_response(agent_capabilities([DEFAULT_CATALOG_ID, BASIC_CATALOG_ID]), status=200)`:
        from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID  # noqa: PLC0415 — lazy on purpose (FEAT-668)
        from parrot.outputs.a2ui.catalog.export import agent_capabilities  # noqa: PLC0415 — lazy on purpose (FEAT-668)
```

### `a2a/server.py` (MODIFY)
```python
# occurrences: 1 — line 59: DELETE `from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID`
# occurrences: 1 — line 179, inside A2AServer.__init__ (line 120)
# INSERT directly above `        register_a2ui_extension(self.capabilities, [DEFAULT_CATALOG_ID, BASIC_CATALOG_ID])`:
        from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID  # noqa: PLC0415 — lazy on purpose (FEAT-668)
```

### FILL IN checklist
- [ ] `infographic_recipes.py::RecipeHandler.post` — local import above the `try` for line 291.
- [ ] `ui_surfaces.py::_refresh` — local import above the `try` for line 685.
- [ ] `infographic.py::_render_infographic_deterministic` — local import above the `try` for line 403.
- [ ] `infographic.py::_run_render_job` — local import above the outer `try` for lines 647-648.

---

## Acceptance Criteria

- [ ] None of the five modules imports `runner`, `infographic_toolkit`, `catalog.basic` or `catalog.export` at module level.
- [ ] Existing handler and A2A tests pass unchanged (spec AC5).
- [ ] `ruff check` clean on all five files (no E402, no F401; PLC0415 suppressed inline).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_infographic_recipes.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_a2ui_handler.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_infographic_render_route.py -q`
- `pytest packages/ai-parrot-server/tests/test_namespace_imports.py -q`

---

## Test Specification

Behaviour is covered by the existing handler tests; import isolation is covered by TASK-4293.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug a2ui-lazy-imports --feature-id FEAT-668`).
2. Read the spec. 3. No dependencies. 4. Verify the Codebase Contract (re-run `grep -c` for each anchor).
5. Mark `in-progress`. 6. Implement. 7. Validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
8. Commit only the five listed files. 9. `scripts/sdd/close_task.sh TASK-4292 a2ui-lazy-imports verified`. 10. Fill in the Completion Note and commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
