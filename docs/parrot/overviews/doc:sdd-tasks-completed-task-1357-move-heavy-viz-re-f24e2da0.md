---
type: Wiki Overview
title: 'TASK-1357: Move heavy visualization renderers to satellite'
id: doc:sdd-tasks-completed-task-1357-move-heavy-viz-renderers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.outputs.formats.base import BaseRenderer, RenderResult, RenderError
  # base.py stays in core'
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.base
  rel: mentions
- concept: mod:parrot.outputs.formats.matplotlib
  rel: mentions
- concept: mod:parrot.outputs.formats.plotly
  rel: mentions
---

# TASK-1357: Move heavy visualization renderers to satellite

**Feature**: FEAT-200 — Extract outputs/formats to ai-parrot-visualizations
**Spec**: `sdd/proposals/ai-parrot-visualizations.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1355, TASK-1356
**Assigned-to**: unassigned

---

## Context

> Moves the heavy visualization renderer modules from the core package
> to the satellite. These are the renderers with external library
> dependencies (matplotlib, seaborn, plotly, altair, bokeh, holoviews)
> plus JS-based renderers (d3, echarts) and the chart base class.
> After this move, `import_module('.matplotlib', 'parrot.outputs.formats')`
> resolves via PEP 420 namespace merging (extend_path from TASK-1356).

---

## Scope

- Move these files from `packages/ai-parrot/src/parrot/outputs/formats/` to `packages/ai-parrot-visualizations/src/parrot/outputs/formats/`:
  - `matplotlib.py`
  - `seaborn.py`
  - `plotly.py`
  - `altair.py`
  - `bokeh.py`
  - `holoviews.py`
  - `d3.py`
  - `echarts.py`
  - `map.py`
  - `chart.py`
- Move `assets/echarts.min.js` (and `assets/__init__.py`) to satellite
- Verify each moved renderer still auto-registers via `@register_renderer` when imported through `get_renderer()`
- Verify import paths unchanged (e.g. `from parrot.outputs.formats.plotly import PlotlyRenderer`)

**NOT in scope**: Infographic renderers (TASK-1358), messaging/utility renderers (TASK-1358), direct import migration (TASK-1359), pyproject.toml dependency changes (TASK-1360).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/formats/matplotlib.py` | DELETE (move) | Move to satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/seaborn.py` | DELETE (move) | Move to satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/plotly.py` | DELETE (move) | Move to satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/altair.py` | DELETE (move) | Move to satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/bokeh.py` | DELETE (move) | Move to satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/holoviews.py` | DELETE (move) | Move to satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/d3.py` | DELETE (move) | Move to satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/echarts.py` | DELETE (move) | Move to satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/map.py` | DELETE (move) | Move to satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/chart.py` | DELETE (move) | Move to satellite |
| `packages/ai-parrot/src/parrot/outputs/formats/assets/` | DELETE (move) | Move entire directory to satellite |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/*.py` | CREATE | Destination for moved files |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/` | CREATE | Destination for echarts.min.js |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All renderers import from the same namespace — these MUST still work after move:
from parrot.outputs.formats.base import BaseRenderer, RenderResult, RenderError  # base.py stays in core
from parrot.outputs.formats import register_renderer  # __init__.py stays in core
from parrot.models.outputs import OutputMode  # stays in core

# Example from matplotlib.py:
from .base import BaseRenderer  # relative import — MUST be updated to absolute
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py:17
def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None):
    # Decorator — each renderer uses @register_renderer(OutputMode.X)

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py:33
def get_renderer(mode: OutputMode) -> Type[Renderer]:
    # Lazy-loads via import_module('.matplotlib', 'parrot.outputs.formats')

# packages/ai-parrot/src/parrot/outputs/formats/base.py:54
class BaseRenderer(ABC):
    # Lines 54-466 — abstract base with render(), _get_content(), execute_code(), etc.

# packages/ai-parrot/src/parrot/outputs/formats/base.py:20
@dataclass
class RenderError:

# packages/ai-parrot/src/parrot/outputs/formats/base.py:36
@dataclass
class RenderResult:
```

### Does NOT Exist
- ~~`parrot.outputs.formats.base` in the satellite~~ — `base.py` stays in core; satellite imports from it via namespace merging
- ~~`__init__.py` at satellite namespace levels~~ — must NOT exist (PEP 420)

---

## Implementation Notes

### Pattern to Follow
```bash
# Use git mv to preserve history:
git mv packages/ai-parrot/src/parrot/outputs/formats/matplotlib.py \
       packages/ai-parrot-visualizations/src/parrot/outputs/formats/matplotlib.py
# Repeat for each file
```

### Key Constraints
- **Relative imports in moved files**: Each renderer likely uses `from .base import BaseRenderer`. Since `base.py` stays in core and the satellite contributes to the same namespace, the relative import `from .base import BaseRenderer` will STILL WORK because `extend_path` merges both directories. The `.` resolves to `parrot.outputs.formats`, which includes both core and satellite paths.
- **Do NOT copy `base.py` to satellite** — it stays in core. The namespace merge makes it visible.
- **Preserve `@register_renderer` decorators** on each renderer class — they auto-register when imported.
- **`assets/__init__.py`**: If the core has one, move it too. The satellite's `pyproject.toml` already declares `package-data` for `*.js`.

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/formats/matplotlib.py` — representative renderer
- `packages/ai-parrot-embeddings/src/parrot/stores/pgvector.py` — reference: satellite module importing core abstractions

---

## Acceptance Criteria

- [ ] All 10 renderer files moved to satellite directory
- [ ] `assets/echarts.min.js` moved to satellite
- [ ] Files removed from core's `formats/` directory
- [ ] `from parrot.outputs.formats.matplotlib import MatplotlibRenderer` works (with satellite installed)
- [ ] `get_renderer(OutputMode.MATPLOTLIB)` returns the renderer class
- [ ] `get_renderer(OutputMode.PLOTLY)` returns the renderer class
- [ ] `get_renderer(OutputMode.ECHARTS)` returns the renderer class
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/`
- [ ] Existing tests in `packages/ai-parrot/tests/outputs/formats/` still pass

---

## Test Specification

```python
import pytest
from parrot.models.outputs import OutputMode
from parrot.outputs.formats import get_renderer

@pytest.mark.parametrize("mode", [
    OutputMode.MATPLOTLIB,
    OutputMode.SEABORN,
    OutputMode.PLOTLY,
    OutputMode.ALTAIR,
    OutputMode.BOKEH,
    OutputMode.HOLOVIEWS,
    OutputMode.D3,
    OutputMode.ECHARTS,
    OutputMode.MAP,
    OutputMode.CHART,
])
def test_heavy_renderer_resolves(mode):
    """Each moved renderer is still discoverable via get_renderer."""
    renderer_cls = get_renderer(mode)
    assert renderer_cls is not None
    assert hasattr(renderer_cls, 'render')
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-1355 and TASK-1356 are complete** (satellite scaffold exists, extend_path added)
2. **Read a sample renderer** (e.g. `matplotlib.py`) to understand import patterns
3. **Move each file** using `git mv` for history preservation
4. **Check relative imports** — they should work as-is via namespace merging
5. **Test** that `get_renderer()` resolves each moved renderer
6. **Commit** with message: `sdd: move heavy viz renderers to satellite (TASK-1357)`

---

## Completion Note

Implemented by sdd-worker on 2026-05-28.

Moved 10 renderer files + assets directory to satellite via `git mv`:
- matplotlib.py, seaborn.py, plotly.py, altair.py, bokeh.py, holoviews.py
- d3.py, echarts.py, map.py, chart.py
- assets/echarts.min.js, assets/__init__.py

Bug fixes during move:
- `d3.py`: Fixed pre-existing bug `from .base import BaseChart` → `from .chart import BaseChart` (BaseChart is in chart.py not base.py)
- `formats/__init__.py`: Fixed dispatch `import_module('.charts', ...)` → `import_module('.chart', ...)` (file is chart.py not charts.py)

All 9 renderers (matplotlib, seaborn, plotly, altair, bokeh, holoviews, d3, echarts, map) resolve via `get_renderer()` ✅
Note: `OutputMode.CHART` has no renderer class (chart.py is only a base class) — pre-existing issue.
Pre-existing lint errors (bare except, undefined forward refs) noted but not fixed — same issues exist in core package.
