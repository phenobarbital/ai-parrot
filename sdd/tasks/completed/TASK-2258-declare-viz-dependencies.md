# TASK-2258: Declare markdown-it-py, markupsafe & orjson in ai-parrot-visualizations

**Feature**: FEAT-301 — Themed Component Catalog — HTML Renderer v2
**Spec**: `sdd/specs/infographic-theme-catalog-a2ui.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of the spec (§3). `infographic_html.py` imports
`markdown_it`, `orjson`, and `markupsafe` unconditionally at module scope
(lines 15-17), and `infographic.py` imports `orjson`. But
`packages/ai-parrot-visualizations/pyproject.toml` declares exactly one
dependency — `ai-parrot>=0.25.36` — and **none of the three is a hard dependency
of core `ai-parrot` either**:

- `orjson>=3.9` appears in core's pyproject only inside the **optional**
  `graphindex` extra (line 206).
- `markdown-it-py` and `markupsafe` appear nowhere in core's dependency lists.

So they are being satisfied by accident in this dev environment. A clean
`pip install ai-parrot-visualizations` produces an `ImportError` the moment
anything touches the infographic renderer. This task closes that hole.

Fully independent of every other task in FEAT-301 — it touches one file that no
other task touches, so it is the one task here marked `parallel: true`.

---

## Scope

- Add `markdown-it-py>=3.0`, `markupsafe>=2.1`, `orjson>=3.9` to the
  `[project] dependencies` list in
  `packages/ai-parrot-visualizations/pyproject.toml`.
- Verify by import that the declared distribution names match the imported
  module names (`markdown-it-py` → `markdown_it`, `markupsafe` → `markupsafe`).
- Add a guard test asserting each import resolves.

**NOT in scope**:
- Adding these to core `ai-parrot`'s dependencies. They are used by the
  visualizations package; declare them where they are used.
- Making the imports lazy/optional or wrapping them in `try/except ImportError`.
  They are unconditional module-scope imports of the primary renderer — a hard
  dependency is the correct declaration.
- Auditing the rest of the visualizations package for other undeclared imports.
  The spec names these three; a broader audit is a separate concern.
- Touching the `[project.optional-dependencies]` extras
  (`infographic`, `charts`, `matplotlib`, …) — these three go in the **hard**
  `dependencies` list, not an extra.
- Version pinning beyond the floors given. Do not pin `==`; this repo uses `>=`
  floors for these kinds of libraries.
- Any change to `uv.lock` / lockfiles beyond what `uv` regenerates.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/pyproject.toml` | MODIFY | Add the 3 dependencies to the `[project] dependencies` list (lines 28-30) |
| `packages/ai-parrot-visualizations/tests/outputs/test_declared_dependencies.py` | CREATE | Import-guard test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-19.

### Verified Imports

```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
import markdown_it                        # line 15  <- distribution: markdown-it-py
import orjson                             # line 16  <- distribution: orjson
from markupsafe import escape             # line 17  <- distribution: MarkupSafe

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic.py
import orjson                             # line 9
```

These two files are the only consumers of the three libraries under
`packages/ai-parrot-visualizations/src/` (verified with
`grep -rln "markdown_it\|markupsafe\|orjson" packages/ai-parrot-visualizations/src/`).

### Existing Signatures to Use

```toml
# packages/ai-parrot-visualizations/pyproject.toml — VERBATIM current state

[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-visualizations"
dynamic = ["version"]
description = "Visualization renderers for AI-Parrot outputs"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
# ... authors / keywords / classifiers ...
dependencies = [                    # line 28
    "ai-parrot>=0.25.36",           # line 29
]                                   # line 30

[project.optional-dependencies]
matplotlib = ["matplotlib>=3.7"]
seaborn = ["seaborn>=0.13", "matplotlib>=3.7"]
plotly = ["plotly>=5.0"]
altair = ["altair>=5.0"]
echarts = []  # JS-based — ECharts bundled as static asset; no Python deps
map = ["folium>=0.14"]
infographic = ["cairosvg", "svglib", "reportlab"]
jinja2 = ["jinja2>=3.0"]
streamlit = ["streamlit>=1.30"]
panel = ["panel>=1.0"]
messaging = []
charts = ["ai-parrot-visualizations[matplotlib,seaborn,plotly,altair,echarts]"]
```

Note that the existing `infographic` extra holds the **PDF/SVG export** stack
(`cairosvg`, `svglib`, `reportlab`), not the HTML renderer's imports — that is
why these three belong in the hard `dependencies` list instead.

### Does NOT Exist

- ~~`markdown-it-py` in any pyproject.toml in this repo~~ — grep confirms zero
  occurrences before this task
- ~~`markupsafe` / `MarkupSafe` in any pyproject.toml~~ — zero occurrences
- ~~`orjson` as a hard dependency of core `ai-parrot`~~ — it appears only inside
  the optional `graphindex` extra (`packages/ai-parrot/pyproject.toml:206`), so
  it is NOT transitively guaranteed
- ~~a `markdown_it` distribution named `markdown_it`~~ — the PyPI distribution is
  `markdown-it-py`; the importable module is `markdown_it`
- ~~a `dependencies` entry beyond `ai-parrot>=0.25.36`~~ — the list has exactly
  one entry today
- ~~`packages/ai-parrot-visualizations/tests/outputs/test_declared_dependencies.py`~~ —
  create it; `packages/ai-parrot-visualizations/tests/outputs/` exists and holds
  `__init__.py` + `a2ui_renderers/`

---

## Implementation Notes

### The edit

```toml
dependencies = [
    "ai-parrot>=0.25.36",
    # Imported unconditionally by outputs/formats/infographic_html.py (markdown
    # rendering, HTML escaping) and infographic.py (JSON serialization).
    "markdown-it-py>=3.0",
    "markupsafe>=2.1",
    "orjson>=3.9",
]
```

Keep the explanatory comment — this repo's pyprojects annotate non-obvious
dependencies (see the `tenacity` comment in core's `dependencies`, and the
`echarts = []` note here).

### Verification

Since this repo is a `uv` workspace, verify inside the venv:

```bash
source .venv/bin/activate
python -c "import markdown_it, markupsafe, orjson; print('ok')"
python -c "from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer; print('ok')"
uv pip install -e packages/ai-parrot-visualizations   # resolves cleanly
```

A truly clean-room check (fresh venv, install only the built wheel) is the real
proof but is heavier than this task warrants; the import-guard test plus a clean
`uv pip install -e` is sufficient evidence.

### Key Constraints

- `>=` floors, not `==` pins.
- Hard `dependencies`, not an extra.
- Do not make the imports optional or lazy.
- Do not add these to core `ai-parrot`.
- Follow the project rule: `uv` only, and always `source .venv/bin/activate`
  first.

### References in Codebase

- `packages/ai-parrot/pyproject.toml` `[project] dependencies` — the `tenacity`
  entry shows the house style for a commented "must be core because it is
  imported unconditionally" dependency
- `packages/ai-parrot-visualizations/pyproject.toml:28-30` — the list to extend

---

## Acceptance Criteria

- [ ] `markdown-it-py>=3.0`, `markupsafe>=2.1`, `orjson>=3.9` present in
      `[project] dependencies` of `packages/ai-parrot-visualizations/pyproject.toml`
- [ ] They are in the hard `dependencies` list, not in any
      `[project.optional-dependencies]` extra
- [ ] `ai-parrot>=0.25.36` still present and unchanged
- [ ] The file is valid TOML: `python -c "import tomllib; tomllib.load(open('packages/ai-parrot-visualizations/pyproject.toml','rb'))"`
- [ ] `uv pip install -e packages/ai-parrot-visualizations` resolves without error
- [ ] `python -c "from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer"` succeeds
- [ ] Import-guard test passes:
      `pytest packages/ai-parrot-visualizations/tests/outputs/test_declared_dependencies.py -v`
- [ ] No other pyproject.toml in the repo is modified

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/test_declared_dependencies.py
"""Guard tests: the infographic renderer's third-party imports are declared.

``infographic_html.py`` imports ``markdown_it``, ``orjson`` and ``markupsafe``
at module scope, so they must be hard dependencies of this distribution rather
than accidental transitive installs (FEAT-301, TASK-2258).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
REQUIRED = ("markdown-it-py", "markupsafe", "orjson")


def _declared() -> list[str]:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["project"]["dependencies"]


@pytest.mark.parametrize("name", REQUIRED)
def test_dependency_declared(name: str) -> None:
    """Each import-time dependency is declared in [project] dependencies."""
    declared = " ".join(_declared()).lower()
    assert name in declared


def test_ai_parrot_dependency_preserved() -> None:
    assert any(dep.startswith("ai-parrot>=") for dep in _declared())


def test_imports_resolve() -> None:
    """The declared distributions provide the modules the renderer imports."""
    import markdown_it  # noqa: F401
    import markupsafe  # noqa: F401
    import orjson  # noqa: F401


def test_renderer_imports_cleanly() -> None:
    from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer

    assert InfographicHTMLRenderer is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none. This task is `parallel: true` and can run in
   its own worktree at any time; it shares no file with any other FEAT-301 task.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm the `dependencies` list still has exactly the one `ai-parrot` entry
   - Confirm the three imports are still at `infographic_html.py:15-17`
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists
4. **Activate the venv first**: `source .venv/bin/activate` — mandatory per
   project rules; use `uv`, never bare `pip`
5. **Update status** in `sdd/tasks/index/infographic-theme-catalog-a2ui.json` →
   `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2258-declare-viz-dependencies.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-19
**Notes**: Added `markdown-it-py>=3.0`, `markupsafe>=2.1`, `orjson>=3.9`
(with the explanatory comment) to `[project] dependencies` in
`packages/ai-parrot-visualizations/pyproject.toml`, preserving
`ai-parrot>=0.25.36` unchanged. Created
`packages/ai-parrot-visualizations/tests/outputs/test_declared_dependencies.py`
with the 6-test guard suite (declared-dependency checks, import-resolves
check, renderer-imports-cleanly check) — all 6 passing. Verified the
file is valid TOML via `tomllib.load`. No other `pyproject.toml` in the
repo was touched.

**Deviations from spec**: none.
