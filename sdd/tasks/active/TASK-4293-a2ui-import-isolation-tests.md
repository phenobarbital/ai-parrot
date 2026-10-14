# TASK-4293: Import-isolation regression tests for A2UI lazy imports

**Feature**: FEAT-668 — A2UI Lazy Imports
**Spec**: `sdd/specs/a2ui-lazy-imports.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4289, TASK-4290, TASK-4291, TASK-4292
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (goal G4). Lock in the import-isolation guarantees so the leak
cannot silently return: each entry module, imported in a **fresh interpreter**,
must not load any module in `FORBIDDEN`, and the registry must still serve the
built-ins on demand. Every assertion only passes once TASK-4289–4292 have all
landed.

---

## Scope

- Create the core test file: entry points `parrot.bots`, `parrot.bots.data`, `parrot.bots.database.agent`, `parrot.bots.mixins.narrative`, `parrot.tools.infographic_recipes.figure_guard`, `parrot.outputs.a2ui.artifacts`, `parrot.outputs.a2ui.recipes`; plus lazy-registry and lazy-attribute checks.
- Create the server test file: entry points `parrot.manager`, `parrot.handlers.models`, `parrot.handlers.a2ui`, `parrot.handlers.infographic_recipes`, `parrot.handlers.ui_surfaces`, `parrot.handlers.infographic`, `parrot.a2a.server`.

**NOT in scope**: production code changes. If a test still fails after TASK-4289–4292, name the residual importer in the Completion Note. Fix it only if it is one of the spec §6 Edit Sites (spec §7, "Residual chains"); otherwise leave it as a follow-up and mark the task `done-with-issues`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/outputs/a2ui/test_lazy_imports.py` | CREATE | core entry points + registry + lazy attrs |
| `packages/ai-parrot-server/tests/test_a2ui_lazy_imports.py` | CREATE | server entry points |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.recipes.transformers import transformer_registry  # verified: recipes/transformers.py:161
from parrot.tools.infographic_recipes import RecipeRunner, load_transformer_module  # verified: tools/infographic_recipes/__init__.py:17-18 (lazy after TASK-4291)
```

### Existing Signatures to Use
```python
# Subprocess-probe pattern to mirror: packages/ai-parrot/tests/outputs/a2ui/recipes/test_import_rule.py:47-65
#   src_dir prepended via sys.path.insert(0, ...) inside the probe, then
#   subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60)
#   assert result.returncode == 0, result.stderr
```
Path anchors: `Path(__file__).resolve()` → core test at `packages/ai-parrot/tests/outputs/a2ui/` ⇒ `parents[3] / "src"`; server test at `packages/ai-parrot-server/tests/` ⇒ `parents[1] / "src"`, and core src = `parents[2] / "ai-parrot" / "src"`.

Built-in transformer names (verified: `recipes/library.py`): `day_totals`, `division_breakdown`, `variance_analysis`, `top_movers`, `narrative_facts`, `groupby_aggregate`, `pivot`, `latest_vs_baseline`.

### Does NOT Exist
- ~~a shared `assert_not_imported` / import-isolation helper in the test suites~~ — write the small `_loaded_after_import` helper locally in each file (no conftest change; a shared conftest would make the task exclusive).
- ~~`fakeredis` or other test-only deps~~ — not needed; plain subprocess.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/outputs/a2ui/test_lazy_imports.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/test_a2ui_lazy_imports.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py#transformer_registry"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Use a **fresh subprocess per entry module** — *because* the pytest process has usually already imported the heavy modules, so an in-process `sys.modules` check would pass or fail for the wrong reason.
- Prepend the src dirs inside the probe **and** pass `env=os.environ.copy()` — *because* the shared `.venv` is editable-installed against the main checkout, so a worktree run would otherwise import the wrong tree.
- The probe prints a JSON list of the offending modules; the test asserts it equals `[]` and shows the list on failure.
- `parrot.manager` imports navconfig/settings at import time. If the probe exits non-zero for environmental reasons (missing settings or DB), skip with a reason, but only for an `ImportError`/config error, never for a forbidden-module hit.

---

## Implementation Blueprint

### Steps (in order)
1. Write the core file — *why*: covers the CLI/MCP chains (spec G1 core half, G2, AC4).
2. Write the server file — *why*: covers the `run.py` chain (spec G1 server half).
3. Run both with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.

### `packages/ai-parrot/tests/outputs/a2ui/test_lazy_imports.py` (CREATE)
```python
"""FEAT-668: importing core entry points must not load heavy A2UI modules."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3] / "src"

FORBIDDEN: frozenset[str] = frozenset({
    "parrot.outputs.a2ui.builders",
    "parrot.outputs.a2ui.catalog.basic",
    "parrot.outputs.a2ui.catalog.parrot",
    "parrot.outputs.a2ui.catalog.viz_core",
    "parrot.outputs.a2ui.recipes.library",
})


def _run_probe(body: str) -> subprocess.CompletedProcess[str]:
    """Run ``body`` in a fresh interpreter with this tree's src first on sys.path."""
    probe = f"import sys\nsys.path.insert(0, {str(_SRC)!r})\n{body}"
    return subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, env=os.environ.copy()
    )


def _loaded_after_import(module: str) -> list[str]:
    """Return the sorted subset of FORBIDDEN present in sys.modules after ``import module``."""
    body = (
        "import importlib, json\n"
        f"importlib.import_module({module!r})\n"
        f"print(json.dumps(sorted(set(sys.modules) & {sorted(FORBIDDEN)!r})))\n"
    )
    result = _run_probe(body)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("module", [
    "parrot.bots",
    "parrot.bots.data",
    "parrot.bots.database.agent",
    "parrot.bots.mixins.narrative",
    "parrot.tools.infographic_recipes.figure_guard",
    "parrot.outputs.a2ui.artifacts",
    "parrot.outputs.a2ui.recipes",
])
def test_core_entrypoints_do_not_load_a2ui_heavy(module: str) -> None:
    assert _loaded_after_import(module) == []


def test_registry_singleton_loads_builtins_on_first_get() -> None:
    # FILL IN: probe: import parrot.outputs.a2ui.recipes.transformers; assert library NOT in sys.modules;
    #   transformer_registry.get("day_totals"); assert library IS in sys.modules. Bounded by spec AC2.


def test_registry_list_returns_all_builtins() -> None:
    # FILL IN: probe asserting the 8 built-in names ⊆ {m.name for m in transformer_registry.list()}. Bounded by AC2.


def test_infographic_recipes_lazy_attrs_resolve() -> None:
    # FILL IN: in-process is fine here — import every name in parrot.tools.infographic_recipes.__all__ via
    #   getattr; then pytest.raises(AttributeError) on getattr(pkg, "does_not_exist"). Bounded by spec AC4.
```

### `packages/ai-parrot-server/tests/test_a2ui_lazy_imports.py` (CREATE)
```python
"""FEAT-668: importing server entry points must not load heavy A2UI modules."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_SRCS = [_HERE.parents[1] / "src", _HERE.parents[2] / "ai-parrot" / "src"]

FORBIDDEN: frozenset[str] = frozenset({
    "parrot.outputs.a2ui.builders",
    "parrot.outputs.a2ui.catalog.basic",
    "parrot.outputs.a2ui.catalog.parrot",
    "parrot.outputs.a2ui.catalog.viz_core",
    "parrot.outputs.a2ui.recipes.library",
})


def _loaded_after_import(module: str) -> list[str]:
    """Return the sorted subset of FORBIDDEN present in sys.modules after ``import module``."""
    # FILL IN: same probe as the core file, but insert every path in _SRCS; on a non-zero exit caused by an
    #   environment/config error (not an assertion), pytest.skip(reason) — bounded by Key Constraints.


@pytest.mark.parametrize("module", [
    "parrot.manager",
    "parrot.handlers.models",
    "parrot.handlers.a2ui",
    "parrot.handlers.infographic_recipes",
    "parrot.handlers.ui_surfaces",
    "parrot.handlers.infographic",
    "parrot.a2a.server",
])
def test_server_entrypoints_do_not_load_a2ui_heavy(module: str) -> None:
    assert _loaded_after_import(module) == []
```

### FILL IN checklist
- [ ] core `test_registry_singleton_loads_builtins_on_first_get` — AC2
- [ ] core `test_registry_list_returns_all_builtins` — AC2
- [ ] core `test_infographic_recipes_lazy_attrs_resolve` — AC4
- [ ] server `_loaded_after_import` — skip-on-environment rule only

---

## Acceptance Criteria

- [ ] Every parametrized entry point reports `[]` (spec AC1).
- [ ] The registry tests pass (spec AC2); the lazy-attribute test passes (spec AC4).
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/test_lazy_imports.py -q`
- `pytest packages/ai-parrot-server/tests/test_a2ui_lazy_imports.py -q`

---

## Test Specification

The two files above are the test specification.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug a2ui-lazy-imports --feature-id FEAT-668`).
2. Read the spec. 3. TASK-4289, 4290, 4291, 4292 must all be `done` in `sdd/tasks/index/a2ui-lazy-imports.json`.
4. Verify the Codebase Contract. 5. Mark `in-progress`. 6. Implement.
7. Validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`. 8. Commit only the two files.
9. `scripts/sdd/close_task.sh TASK-4293 a2ui-lazy-imports verified` (or `partial` if a residual chain is left as a follow-up). 10. Fill in the Completion Note and commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
