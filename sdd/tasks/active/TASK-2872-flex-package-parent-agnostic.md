# TASK-2872: Make `agents/flex_dashboard` parent-agnostic — relative imports + path-anchored sibling load

**Feature**: FEAT-528 — Postgres recipe store + agent-package importability
**Spec**: `sdd/specs/pg-recipe-store-and-agent-package-importability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2871
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, items 1 and 2 — the minimal fix Juan chose (§8: relative imports plus a path-anchored sibling load, no rename). Two absolute imports root the flex sibling package at a top-level package literally named `agents`:

- `agents/flex_dashboard.py:83` — `import agents.flex_dashboard.transformers  # noqa: F401`
- `agents/flex_dashboard/transformers.py:53` — `from agents.flex_dashboard.normalize import (…)`

They resolve only when THIS repo's `agents/` directory is the `agents` package on `sys.path`. FieldSync has its own `agents/` package, so replaying flex's recipe there raised `ModuleNotFoundError: No module named 'agents.flex_dashboard'` (reproduced twice, spec §6). The same regular-package layout is why `from agents.flex_dashboard import FlexDashboard` resolves to the package, never to the module — the footgun the file's own docstring (`:19-47`) defers "to the PR reviewer". This task is that decision.

---

## Scope

- `agents/flex_dashboard/transformers.py:53`: `from agents.flex_dashboard.normalize import (` → `from .normalize import (`. Nothing else in that file changes.
- `agents/flex_dashboard.py`: delete line 83's `import agents.flex_dashboard.transformers`; AFTER `_PACKAGE_DIR` is defined (`:88`), add
  `load_transformer_module(_PACKAGE_DIR / "transformers.py")` using TASK-2871's helper, with the same "import side effect ONLY" comment (`:80-82`) kept above it.
- Rewrite the module docstring's `.. warning::` block (`:19-47`): the shadowing footgun is now moot because the module no longer imports its sibling through the `agents` package; keep the one true sentence — a plain `from agents.flex_dashboard import FlexDashboard` still resolves to the package (regular-package layout unchanged), so production keeps loading by file location (`parrot.registry`).
- Tests: `test_transformers_import_under_foreign_parent`, `test_flex_module_loads_without_agents_package`.

**NOT in scope**: renaming the sibling package; touching `finance_reporter.py` (spec §8: rejected — the agents move to `navigator-plugins`, Jesús's item); moving either agent; `normalize.py` (already stdlib + numpy + pandas, `:25-32`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/flex_dashboard/transformers.py` | MODIFY | `:53` relative import |
| `agents/flex_dashboard.py` | MODIFY | `:83` removed; loader call after `:88`; docstring warning rewritten |
| `tests/unit/agents/test_flex_dashboard_importability.py` | CREATE | the two regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_recipes import load_transformer_module   # TASK-2871
from parrot.outputs.a2ui.recipes.transformers import transformer_registry   # transformers.py:161
```

### Existing Signatures to Use
```python
# agents/flex_dashboard.py (dev @ 0027b07a6)
# :80-83
# Import side effect ONLY: registers the Flex transformers (payroll_hero,
# worked_hours_by_month, ..., flex_narrative_facts) on the shared
# `transformer_registry` — see agents/flex_dashboard/transformers.py.
import agents.flex_dashboard.transformers  # noqa: F401          ← REMOVE
# :87-91
_AGENT_DIR = Path(__file__).resolve().parent
_PACKAGE_DIR = _AGENT_DIR / "flex_dashboard"
SKILLS_DIR = _PACKAGE_DIR / "skills"
KB_DIR = _PACKAGE_DIR / "kb"
# :95-102  DATASET_SLUGS (frozen aliases)    :127 class FlexDashboard(NarrativeMixin, InfographicAuthoringMixin, PandasAgent)
# :150 DASHBOARD_RECIPE_NAME = "flex-program-dashboard"

# agents/flex_dashboard/transformers.py
# :45-53
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer
from agents.flex_dashboard.normalize import (        ← becomes: from .normalize import (
    canonicalize_columns, month_period, normalize_currency_columns,
)
__all__: list[str] = []   # :59 registration is by import side effect, not re-export

# agents/flex_dashboard/normalize.py:25-32 — stdlib (re, collections.abc, typing) + numpy + pandas. Unchanged.
# agents/flex_dashboard/__init__.py exists (regular package, 1.3K).
```

### Does NOT Exist
- ~~`agents/flex_dashboard_kit/`~~ — no rename (spec Non-Goals).
- ~~A shipped `parrot/agents/flex_dashboard`~~ — the repo-root `agents/` is not distributed; `parrot/agents/` holds framework agents only.
- ~~A change to `finance_reporter.py`~~ — out of scope by decision.

---

## Implementation Notes

### Key Constraints
- The loader call must come AFTER `_PACKAGE_DIR` is defined and BEFORE `class FlexDashboard` (the class's recipe sections reference transformer names resolved at replay, not at import, but keep the registration early for parity with today).
- `transformers.py` MUST be loadable as a package submodule for the relative import to work — TASK-2871's package-aware branch handles that; do not add `sys.path` hacks.
- Do not change the `# noqa`-free import ordering more than necessary; `ruff check agents/` must stay clean.
- Mutation check (spec §5): revert `:53` to the absolute import and `test_transformers_import_under_foreign_parent` must go RED.

### Test design
- `test_transformers_import_under_foreign_parent`: copy `agents/flex_dashboard/` to `tmp_path/hostpkg/flex_dashboard/` (with a `hostpkg/__init__.py`), make sure no `agents` package is importable in the subprocess (`python -I -c …` with `cwd=tmp_path`), import `hostpkg.flex_dashboard.transformers`, print `sorted(transformer_registry._names())` or the equivalent public accessor, assert `payroll_hero` is present.
- `test_flex_module_loads_without_agents_package`: in a subprocess with `cwd=tmp_path` (so the repo-root `agents/` is NOT on the path), `spec_from_file_location("flex_mod", <repo>/agents/flex_dashboard.py)` + exec; assert `hasattr(mod, "FlexDashboard")` and the transformer names are registered. This imports parrot heavily (tiktoken cache etc.); mark `integration` if it exceeds a few seconds.

### References in Codebase
- `agents/flex_dashboard.py:19-47` — the warning to rewrite
- `parrot/registry/` — how production loads agents by file location (cite the exact function in the rewritten docstring)

---

## Acceptance Criteria

- [ ] `agents/flex_dashboard/transformers.py` contains no `agents.` import; `agents/flex_dashboard.py` contains no `import agents.` line
- [ ] `test_transformers_import_under_foreign_parent` passes; reverting `:53` makes it RED (evidence in the Completion Note)
- [ ] `test_flex_module_loads_without_agents_package` passes
- [ ] Running the agent the way production does (`parrot.registry` file-location load with the repo root on the path) still registers all flex transformers — no behaviour change
- [ ] The docstring warning no longer says the problem is "out of scope … flagged for the PR reviewer"
- [ ] `ruff check agents/flex_dashboard.py agents/flex_dashboard/` clean

---

## Test Specification

```python
# tests/unit/agents/test_flex_dashboard_importability.py
import shutil, subprocess, sys, textwrap
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]

def test_transformers_import_under_foreign_parent(tmp_path):
    host = tmp_path / "hostpkg"; host.mkdir(); (host / "__init__.py").write_text("")
    shutil.copytree(REPO / "agents" / "flex_dashboard", host / "flex_dashboard")
    code = textwrap.dedent('''
        import hostpkg.flex_dashboard.transformers
        from parrot.outputs.a2ui.recipes.transformers import transformer_registry
        transformer_registry.get("payroll_hero")   # raises if absent
        print("OK")
    ''')
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr

def test_flex_module_loads_without_agents_package(tmp_path):
    code = textwrap.dedent(f'''
        import importlib.util
        spec = importlib.util.spec_from_file_location("flex_mod", r"{REPO / 'agents' / 'flex_dashboard.py'}")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        assert hasattr(mod, "FlexDashboard")
        from parrot.outputs.a2ui.recipes.transformers import transformer_registry
        transformer_registry.get("payroll_hero")
        print("OK")
    ''')
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
```

---

## Agent Instructions

1. Read `agents/flex_dashboard.py:1-130` and `agents/flex_dashboard/transformers.py:40-60` before editing.
2. Confirm TASK-2871 is in `sdd/tasks/completed/`.
3. Implement, run both tests, do the mutation check, record it.
4. Move this file to `sdd/tasks/completed/`, set the index entry to `done`, fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Mutation-check evidence**:

**Deviations from spec**: none | describe if any
