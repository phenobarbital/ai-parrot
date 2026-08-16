---
type: feature
base_branch: dev
---

# Feature Specification: Purge Matplotlib & Heavy Renderer Libraries

**Feature ID**: FEAT-423
**Date**: 2026-08-16
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.0.0 (major release — breaking change)

---

## 1. Motivation & Business Requirements

### Problem Statement

PythonREPLTool and the data-analysis system prompts steer LLMs toward
generating matplotlib/seaborn code for visualizations. This is architecturally
wrong now that AI-Parrot has two superior visualization paths:

1. **A2UI** (FEAT-273) — declarative JSON envelope the frontend renders
   natively with full interactivity (tooltips, zoom, responsive).
2. **`structured-chart` / `structured-table` / `structured-map`** — JSON-based
   output modes the frontend implements directly.

matplotlib generates **static raster images** (PNG/SVG) that must be base64-
encoded and embedded in the chat — no interactivity, no theming, no
responsiveness. Despite this, LLMs overwhelmingly prefer matplotlib because it
dominates their training data. The library being pre-loaded in the REPL
namespace makes this the path of least resistance.

Additionally:
- **~60 MB install footprint** (matplotlib + numpy + pillow + fonttools +
  kiwisolver + cycler + contourpy + pyparsing + packaging + python-dateutil).
- **~400 ms cold-start penalty** for matplotlib style-parsing on first import
  (already partially mitigated by lazy init, but the cost is still paid per
  worker process).
- **seaborn is hard-imported** in PythonREPLTool (`import seaborn as sns` at
  line 411) despite NOT being a core dependency in `pyproject.toml` —
  meaning a bare `pip install ai-parrot` will crash PythonREPLTool on first
  use without the `agents` or `charts` extra.
- **`_setup_charts()`, `_safe_close_all_plots()`, `_safe_matplotlib_cleanup()`**
  — ~60 lines of defensive cleanup code that exist solely to work around
  matplotlib's non-GUI backend quirks.

### Goals

- **G1**: Remove matplotlib, seaborn, and bokeh from PythonREPLTool's
  pre-loaded namespace — the REPL becomes a compute engine, not a renderer.
- **G2**: Rewrite all data-analysis system prompts (`data.py`, `bots/data.py`)
  to direct the LLM toward `structured-chart` / A2UI for visualizations and
  altair-only for complex edge cases (heatmaps, correlation matrices).
- **G3**: Migrate ChartTool's default backend from matplotlib to altair
  (Vega-Lite JSON output).
- **G4**: Update analytics tools (`quickeda.py`, `correlationanalysis.py`,
  `seasonaldetection.py`) to use altair instead of matplotlib.
- **G5**: Remove all matplotlib-specific boilerplate from PythonREPLTool
  (`_ensure_matplotlib`, `_setup_charts`, `save_current_plot`,
  `get_plot_as_base64`, `clear_plots`, `plt_style`, `palette` params).
- **G6**: Update documentation and rules files to reflect the new
  visualization policy.

### Non-Goals (explicitly out of scope)

- **Removing plotly** — it outputs interactive HTML/JSON, not raster images;
  it stays as an optional lazy-loaded backend.
- **Removing folium** — map rendering via Folium is a distinct use case;
  it stays as an optional lazy-loaded backend.
- **Modifying A2UI itself** — A2UI is already complete (FEAT-273); this
  spec only ensures the LLM is directed toward it.
- **Backward compatibility** — this is a hard breaking change for v1.0.0.
  No deprecation shims, no fallback, no migration helpers.
- **Removing matplotlib from `ai-parrot-visualizations`** — the satellite
  package already treats it as an optional extra (`[matplotlib]`); users who
  install it explicitly can still use it in custom renderers. This spec only
  removes it from the default REPL/tool path.

---

## 2. Architectural Design

### Overview

The change enforces a clean separation of concerns:

```
PythonREPLTool (compute)          Frontend (render)
─────────────────────             ──────────────────
Computes data                     Receives structured JSON
  ↓                                 ↓
Returns dict/DataFrame            Renders via Chart.js / Recharts / D3
  ↓                                 ↓
OutputMode.A2UI / structured-*    Interactive, themed, responsive chart
```

For edge cases where the REPL genuinely needs to produce a visual (complex
heatmaps, correlation matrices, graph layouts), **altair** is the sole
fallback — it outputs Vega-Lite JSON specs that the frontend can also render
directly.

```
PythonREPLTool edge case
────────────────────────
import altair as alt
chart = alt.Chart(df).mark_bar().encode(x='category', y='value')
chart.to_dict()  → Vega-Lite JSON spec → frontend renders natively
```

### Component Diagram

```
┌─────────────────────────────────────────────────┐
│           PythonREPLTool (AFTER)                │
│                                                 │
│  Pre-loaded: pd, np, numexpr, json_encoder/dec  │
│  Lazy optional: altair, plotly, folium           │
│  REMOVED: matplotlib, plt, sns, bokeh           │
│  REMOVED: save_current_plot, get_plot_as_base64 │
│  REMOVED: clear_plots, _setup_charts,           │
│           _ensure_matplotlib, plt_style, palette │
│                                                 │
│  NEW: visualization policy in description/      │
│       system prompt directing LLM to A2UI       │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│          System Prompts (data.py)               │
│                                                 │
│  BEFORE: "use matplotlib, seaborn or altair"    │
│  AFTER:  "return data as dict/DataFrame; the    │
│          system renders charts automatically    │
│          via structured-chart/A2UI. Use altair  │
│          ONLY for complex viz not covered by    │
│          the standard chart types."             │
└─────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PythonREPLTool` | **modifies** | Remove matplotlib/seaborn from namespace, constructor params, helpers |
| `data.py` prompts | **rewrites** | All 3 prompt templates (`REACT_PROMPT_PREFIX`, `TOOL_CALLING_PROMPT_PREFIX`, `TOOL_CALLING_PROMPT_SUFFIX`) |
| `DataBot._build_system_prompt()` | **modifies** | Update capabilities text at line 870 |
| `clients/base.py` | **modifies** | Remove `plt_style` param references (lines 106, 1228) |
| `ChartTool` | **modifies** | Replace matplotlib default backend with altair |
| `repl_worker/worker.py` | **modifies** | Remove matplotlib references from docstring, bootstrap |
| `OutputFormatter` docs | **updates** | Remove matplotlib from "Supported Output Types" table |
| `.agent/rules/python-development.md` | **updates** | Replace matplotlib/seaborn recommendation |

### Data Models

No new data models. ChartTool's existing `GenerateChartInput` / `ChartFormat` /
`ChartStyle` models are updated in place (ChartFormat gains `VEGALITE_JSON`;
ChartStyle may be simplified since altair handles its own theming).

### New Public Interfaces

```python
# ChartTool gains an altair backend (replaces matplotlib as default)
class ChartTool(AbstractTool):
    def __init__(
        self,
        backend: Literal["altair", "plotly"] = "altair",  # was "matplotlib"
        ...
    ): ...

    async def _generate_altair(
        self,
        chart_type: ChartType,
        title: str,
        data: Dict[str, Any],
        ...
    ) -> Path:
        """Generate chart as Vega-Lite JSON spec (or PNG via altair-saver)."""
        ...
```

---

## 3. Module Breakdown

### Module 1: PythonREPLTool Cleanup

- **Path**: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
- **Responsibility**: Remove all matplotlib/seaborn integration from the REPL tool.
- **Depends on**: none

**Changes:**
1. Delete module-level `matplotlib = None` / `plt = None` / `_pylab_helpers = None` globals (lines 30–31).
2. Delete `_ensure_matplotlib()` function (lines 35–46).
3. Delete `_setup_charts()` method (lines 324–349).
4. Delete `_safe_close_all_plots()` method (lines 351–366).
5. Delete `_safe_matplotlib_cleanup()` method (lines 368–384).
6. Remove `plt_style` and `palette` constructor params (lines 209, 210).
7. Remove `self.plt_style` and `self.palette` assignments (lines 267–268).
8. Remove `import seaborn as sns` from `_setup_environment()` (line 411).
9. Remove `plt`, `matplotlib`, `sns` from `self.locals.update({...})` (lines 538–541).
10. Remove `save_current_plot`, `get_plot_as_base64`, `clear_plots` closures and their dict entries (lines 437–491, 553–554).
11. Rewrite `_get_default_setup_code()` to remove matplotlib/seaborn init (lines 570–604).
12. Remove `_setup_charts()` call from `__init__` (line 311).
13. Remove `_bootstrap()` matplotlib style calls (lines 620–622).
14. Update class docstring (lines 106–115) and `description` field (line 118).
15. Remove `logging.getLogger("matplotlib")` silencer (line 17).
16. Update `_worker_repl_kwargs` to drop `plt_style` and `palette` (lines 303–304).
17. Remove `auto_save_plots` and `return_plot_as_base64` constructor params — no
    altair replacement; A2UI transports visualization as JSON (OQ1 resolved).
18. Add `"matplotlib"` and `"matplotlib.pyplot"` to `BLOCKED_IMPORTS` set (OQ2 resolved).

### Module 2: System Prompt Rewrite

- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/data.py`
- **Responsibility**: Redirect LLM from matplotlib to structured-chart / A2UI / altair.
- **Depends on**: Module 1

**Changes in `REACT_PROMPT_PREFIX`:**
1. Replace line 25 ("You can create visualizations using matplotlib, seaborn or
   altair") with: "For visualizations, return data as a dict or DataFrame. The
   system renders charts automatically. For complex visualizations (heatmaps,
   correlation matrices), use altair — it outputs Vega-Lite JSON that the
   frontend renders natively."
2. Replace line 28 (library listing) — remove matplotlib, matplotlib-inline,
   seaborn from the available libraries list.
3. Replace line 116 ("use seaborn or altair for charts and matplotlib for plots
   as embedded images") — remove matplotlib/seaborn references.

**Changes in `TOOL_CALLING_PROMPT_PREFIX`:**
1. Replace line 201 (Available Libraries) — remove matplotlib and seaborn.
2. Add a `## Visualization Policy` section:
   ```
   ## Visualization Policy
   - DO NOT use matplotlib or seaborn — they are not available.
   - For standard charts (bar, line, pie, scatter): return the data as a
     Python dict with keys like {"chart_type": "bar", "data": {...}}.
     The system will render it automatically.
   - For complex visualizations only (heatmaps, correlation matrices, network
     graphs): use altair. Return the chart's .to_dict() output.
   - For maps: use folium (if available).
   ```

**Changes in `bots/data.py`:**
1. Update capabilities text at line 870 — replace "Create visualizations
   (matplotlib, seaborn, plotly)" with "Return structured data for
   visualization (the system renders charts automatically via A2UI)."

### Module 3: REPL Worker & Config Cleanup

- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py`,
           `packages/ai-parrot/src/parrot/clients/base.py`
- **Responsibility**: Remove matplotlib references from worker process and config.
- **Depends on**: Module 1

**Changes:**
1. Update `worker.py` docstring (lines 1–21) — remove "matplotlib, connection
   pools" references.
2. Remove `plt_style` param from `clients/base.py` (lines 106, 1228).
3. Remove `"matplotlib"`, `"matplotlib.pyplot"`, and `"seaborn"` from
   `_GENERAL_IMPORTS` in `python_sanitizer.py` (lines 70–72) — resolved
   OQ2 + OQ4.

### Module 4: ChartTool Migration

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/chart.py`
- **Responsibility**: Replace matplotlib default backend with altair.
- **Depends on**: none (independent satellite package)

**Changes:**
1. Change default backend from `"matplotlib"` to `"altair"` in constructor.
2. Remove `_generate_matplotlib()` and `_matplotlib_render()` methods.
3. Add `_generate_altair()` method that produces Vega-Lite JSON specs.
4. Update `ChartFormat` enum — add `VEGALITE_JSON = "vegalite"`.
5. Update `_execute()` dispatch to use altair instead of matplotlib.
6. Keep `_generate_plotly()` as-is (it already outputs HTML/JSON).
7. Remove `ThreadPoolExecutor` (no longer needed — altair is not thread-unsafe).
8. Update `chart.py` module docstring.
9. Update tests in `tests/test_chart_tool.py`.

### Module 5: Analytics Tools Cleanup

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/quickeda.py`,
           `packages/ai-parrot-tools/src/parrot_tools/correlationanalysis.py`,
           `packages/ai-parrot-tools/src/parrot_tools/seasonaldetection.py`,
           `packages/ai-parrot-tools/src/parrot_tools/sandboxtool.py`
- **Responsibility**: Replace matplotlib with altair in analytics tools.
- **Depends on**: Module 4

**Changes:**
1. `quickeda.py`: Replace `import matplotlib` / `import matplotlib.pyplot as plt`
   with altair. Rewrite figure generation to produce Vega-Lite specs or static
   images via altair-saver.
2. `correlationanalysis.py`: Same treatment — replace matplotlib heatmap
   rendering with altair's `mark_rect()`.
3. `seasonaldetection.py`: Replace matplotlib time-series plots with altair
   `mark_line()`.
4. `sandboxtool.py`: Remove `"matplotlib"` from the `DEFAULT_PACKAGES` list
   (line 35) and from the init code templates (lines 250–252, 595, 635, 656).

### Module 6: Documentation & Rules Update

- **Path**: `docs/outputs.md`, `docs/sandbox_tool.md`, `docs/jupyter_mode.md`,
           `docs/repl-worker-sandbox.md`,
           `.agent/rules/python-development.md`,
           `.claude/rules/python-development.md`,
           `.agent/skills/data-storytelling/SKILL.md`
- **Responsibility**: Update all documentation to reflect the new visualization policy.
- **Depends on**: Modules 1–5

**Changes:**
1. `docs/outputs.md`: Remove "Matplotlib" row from Supported Output Types table
   (line 45). Remove matplotlib from install command (line 64). Remove
   matplotlib usage example (line 448–452).
2. `docs/sandbox_tool.md`: Remove matplotlib from pip install lists (lines 173, 255).
3. `docs/jupyter_mode.md`: Replace matplotlib example (line 306–315) with altair.
4. `docs/repl-worker-sandbox.md`: Remove matplotlib from calibration references
   (lines 61, 126, 132, 145).
5. `.agent/rules/python-development.md` and `.claude/rules/python-development.md`:
   Replace line 38 ("Use matplotlib/seaborn for visualization") with "Return
   data for visualization via structured-chart/A2UI; use altair for complex
   viz only."
6. `.agent/skills/data-storytelling/SKILL.md`: Replace matplotlib code example
   (line 243) with altair.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_pythonrepl_no_matplotlib_in_namespace` | 1 | `plt`, `matplotlib`, `sns` are NOT in `tool.locals` |
| `test_pythonrepl_no_plt_style_param` | 1 | Constructor does not accept `plt_style` / `palette` |
| `test_pythonrepl_altair_available` | 1 | `altair` is lazy-loaded and available when installed |
| `test_pythonrepl_plotly_available` | 1 | plotly still lazy-loads correctly |
| `test_pythonrepl_matplotlib_import_blocked` | 1 | User code `import matplotlib` is blocked by sandbox |
| `test_charttool_default_backend_altair` | 4 | `ChartTool()` defaults to `backend="altair"` |
| `test_charttool_altair_bar_chart` | 4 | Altair backend generates valid Vega-Lite JSON for a bar chart |
| `test_charttool_altair_all_types` | 4 | All `ChartType` values produce valid output with altair |
| `test_charttool_plotly_still_works` | 4 | Plotly backend is unaffected |
| `test_quickeda_no_matplotlib_import` | 5 | quickeda module does not import matplotlib |
| `test_sandboxtool_no_matplotlib_default` | 5 | matplotlib not in DEFAULT_PACKAGES |

### Integration Tests

| Test | Description |
|---|---|
| `test_data_agent_uses_structured_output` | DataBot generates structured dict/DataFrame for chart request, not matplotlib code |
| `test_repl_worker_bootstrap_no_matplotlib` | Worker process bootstraps without matplotlib |

### Test Data / Fixtures

```python
@pytest.fixture
def pythonrepl_tool():
    """PythonREPLTool instance without matplotlib in namespace."""
    tool = PythonREPLTool()
    return tool

@pytest.fixture
def chart_data():
    """Sample data for chart generation tests."""
    return {
        "categories": ["Q1", "Q2", "Q3", "Q4"],
        "values": [100, 150, 120, 180],
    }
```

---

## 5. Acceptance Criteria

- [ ] **AC1**: `PythonREPLTool().locals` does NOT contain `plt`, `matplotlib`, `sns`, or `bokeh`.
- [ ] **AC2**: `PythonREPLTool.__init__` does NOT accept `plt_style` or `palette` params.
- [ ] **AC3**: No module-level or lazy imports of matplotlib in `pythonrepl.py`.
- [ ] **AC4**: All system prompts in `data.py` reference structured-chart/A2UI for
  visualization — zero mentions of matplotlib or seaborn as available libraries.
- [ ] **AC5**: `ChartTool()` defaults to `backend="altair"` and produces valid
  Vega-Lite JSON.
- [ ] **AC6**: `quickeda.py`, `correlationanalysis.py`, `seasonaldetection.py`
  produce output without importing matplotlib.
- [ ] **AC7**: `sandboxtool.py` does not list matplotlib in its default package set.
- [ ] **AC8**: All documentation files list altair (not matplotlib) as the
  visualization library.
- [ ] **AC9**: All existing tests pass (`pytest tests/ -v`).
- [ ] **AC10**: `grep -rn "import matplotlib" packages/ai-parrot/src/` returns zero
  matches (core package is matplotlib-free).
- [ ] **AC11**: `"matplotlib"` and `"matplotlib.pyplot"` are present in
  `PythonREPLTool.BLOCKED_IMPORTS` — user REPL code cannot import them.
- [ ] **AC12**: `_GENERAL_IMPORTS` in `python_sanitizer.py` does NOT contain
  `"matplotlib"`, `"matplotlib.pyplot"`, or `"seaborn"`.
- [ ] **AC13**: `PythonREPLTool.__init__` does NOT accept `auto_save_plots`
  or `return_plot_as_base64` params.
- [ ] **AC14**: `ai-parrot-tools/pyproject.toml` has a `charts` extra that
  includes `altair>=5.0` and `vl-convert-python>=1.0`.

---

## 6. Codebase Contract

### Verified Imports

```python
# PythonREPLTool — packages/ai-parrot/src/parrot/tools/pythonrepl.py:54
from parrot.tools.abstract import AbstractTool

# Lazy import helper — packages/ai-parrot/src/parrot/tools/pythonrepl.py:53
from parrot._imports import lazy_import

# OutputMode enum — packages/ai-parrot/src/parrot/models/outputs.py:33
from parrot.models.outputs import OutputMode  # has A2UI, STRUCTURED_CHART, etc.

# AbstractTool (ChartTool base) — packages/ai-parrot-tools/src/parrot_tools/abstract.py
from parrot_tools.abstract import AbstractTool, ToolResult

# A2UI emission — packages/ai-parrot/src/parrot/outputs/a2ui/emission.py:19
from parrot.outputs.a2ui.emission import finalize_a2ui_response

# Redaction — packages/ai-parrot/src/parrot/tools/pythonrepl.py:55
from parrot.security.redaction import redact_text

# Python sanitizer — packages/ai-parrot/src/parrot/tools/pythonrepl.py:261
from parrot.security.python_sanitizer import PythonCodeSanitizer, general_profile
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/pythonrepl.py
class PythonREPLTool(AbstractTool):                    # line 105
    name = "python_repl"                               # line 117
    description = "Execute Python code..."             # line 118
    args_schema = PythonREPLArgs                       # line 119
    _bootstrapped = False                              # line 122
    BLOCKED_IMPORTS: set = {...}                        # line 125
    BLOCKED_NAMES: set = {...}                          # line 145
    BLOCKED_ATTRIBUTES: set = {...}                     # line 169

    def __init__(self,
        locals_dict, globals_dict, report_dir,
        plt_style, palette, setup_code,                # ← REMOVE plt_style, palette
        sanitize_input_enabled, auto_save_plots,
        return_plot_as_base64, debug, policy,
        executor_max_workers, worker_config,
        **kwargs): ...                                 # line 204

    def _setup_charts(self): ...                       # line 324 — DELETE
    def _safe_close_all_plots(self): ...               # line 351 — DELETE
    def _safe_matplotlib_cleanup(self): ...            # line 368 — DELETE
    def _setup_environment(self): ...                  # line 402 — MODIFY
    def _get_default_setup_code(self): ...             # line 570 — MODIFY
    def _bootstrap(self): ...                          # line 606 — MODIFY


# packages/ai-parrot-tools/src/parrot_tools/chart.py
class ChartTool(AbstractTool):                         # line ~160
    name = "generate_chart"
    backend: Literal["matplotlib", "plotly"]            # ← CHANGE to ["altair", "plotly"]

    def __init__(self,
        backend: Literal["matplotlib", "plotly"] = "matplotlib",  # line 184 — CHANGE
        ...): ...

    async def _generate_matplotlib(self, ...): ...     # line 317 — DELETE
    def _matplotlib_render(self, ...): ...             # line 338 — DELETE
    async def _generate_plotly(self, ...): ...         # line ~400 — KEEP


# packages/ai-parrot/src/parrot/bots/data.py
class DataBot:
    def _build_system_prompt(self, **kwargs): ...      # line ~850
    # Uses capabilities text at line 870 referencing matplotlib
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Module 1 (REPL cleanup) | `PythonREPLTool.__init__` | param removal | `pythonrepl.py:204` |
| Module 1 (REPL cleanup) | `_setup_environment` | namespace dict | `pythonrepl.py:533` |
| Module 2 (prompt rewrite) | `REACT_PROMPT_PREFIX` | string constant | `data.py:1` |
| Module 2 (prompt rewrite) | `TOOL_CALLING_PROMPT_PREFIX` | string constant | `data.py:162` |
| Module 3 (worker cleanup) | `repl_worker/worker.py` | docstring only | `worker.py:1` |
| Module 3 (config cleanup) | `clients/base.py` | `plt_style` param | `base.py:106` |
| Module 4 (ChartTool) | `ChartTool.__init__` | backend param | `chart.py:184` |
| Module 5 (analytics tools) | `quickeda.py` imports | matplotlib→altair | `quickeda.py:10-11` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.tools.pythonrepl.AltairREPLTool`~~ — does not exist; there is no
  altair-specific REPL tool class.
- ~~`parrot.outputs.formats.matplotlib`~~ — does not exist as a module; the
  matplotlib renderer is in `ai-parrot-visualizations`, not in core.
- ~~`PythonREPLTool.set_visualization_backend()`~~ — no such method exists.
- ~~`parrot.tools.abstract.AbstractTool.rendering_mode`~~ — not a real attribute.
- ~~`ChartTool._generate_altair()`~~ — does not yet exist; must be created in
  Module 4.
- ~~`altair-saver`~~ — altair-saver is a separate PyPI package for static
  export; it may not be needed if the frontend renders Vega-Lite JSON directly.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Lazy imports** for optional libs — follow the existing pattern at
  `pythonrepl.py:419–433` (`lazy_import("altair", extra="images")`).
- **ToolResult** return type for ChartTool — preserve the existing contract
  (success/error/metadata/images fields).
- **Async-first** — altair chart generation is synchronous but lightweight;
  wrap in `asyncio.to_thread()` only if measured to be blocking.

### Migration Path for ChartTool Output

The altair backend should produce:
1. **Default**: Vega-Lite JSON spec (`.json` file) — the frontend can render
   this natively.
2. **Fallback**: PNG via `altair.save()` (requires `vl-convert-python`) for
   integrations that need raster images (Telegram, MS Teams inline).

### Known Risks / Gotchas

- **LLM behavior drift**: Removing matplotlib from the namespace will cause
  LLMs to generate `import matplotlib` code that hits the sandbox blocklist.
  The system prompt must explicitly state "matplotlib is NOT available" to
  prevent repeated failures.
- **Breaking API change** (resolved): `auto_save_plots`, `return_plot_as_base64`,
  `plt_style`, `palette` are removed from PythonREPLTool's constructor. Any caller
  passing these kwargs will get a TypeError. Acceptable for a major release.
- **`_worker_repl_kwargs`**: The worker config dict passes `plt_style` and
  `palette` to the worker process (line 303–304). Removing these changes the
  worker bootstrap protocol — ensure the worker's PythonREPLTool constructor
  signature matches.
- **EDA tools depend on seaborn**: `quickeda.py` and `correlationanalysis.py`
  use seaborn extensively — the altair migration requires rewriting chart
  generation logic, not just swapping imports.
- **`vl-convert-python`** (resolved): Optional dep in `ai-parrot-tools[charts]`
  (~20 MB). Only needed for raster export to messaging integrations. Lighter
  than matplotlib (~60 MB).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `altair` | `>=5.0` | Vega-Lite chart generation (already an optional dep in ai-parrot-visualizations) |
| `vl-convert-python` | `>=1.0` | **Optional in `ai-parrot-tools[charts]`** — static PNG/SVG export from Vega-Lite specs for messaging integrations (OQ3 resolved) |

---

## 8. Open Questions

- [x] **Should `auto_save_plots` and `return_plot_as_base64` be replaced with
  an altair-equivalent, or simply removed?** — *Resolved*: **Eliminate without
  replacement.** A2UI transports visualization as JSON in the response — no
  file persistence needed. ChartTool handles raster export for messaging
  integrations independently. These params are removed as a breaking change.
- [x] **Should `matplotlib` be added to `BLOCKED_IMPORTS` in the sandbox
  policy?** — *Resolved*: **Yes.** Add `"matplotlib"` and `"matplotlib.pyplot"`
  to `PythonREPLTool.BLOCKED_IMPORTS` AND remove them from
  `python_sanitizer.py`'s `_GENERAL_IMPORTS` allowlist. This produces a clear
  error that the system prompt already explains. Power users needing matplotlib
  can use SandboxTool (Docker) or an external notebook.
- [x] **Does `vl-convert-python` need to be a core or optional dependency?**
  — *Resolved*: **Optional, in `ai-parrot-tools[charts]`** (not in core).
  Only ChartTool needs raster export for Telegram/Teams inline images. The
  extra is: `charts = ["altair>=5.0", "vl-convert-python>=1.0"]`.
- [x] **Should seaborn stay in the `python_sanitizer.py` allowlist?**
  — *Resolved*: **No — remove it.** Remove `"seaborn"` from
  `_GENERAL_IMPORTS` in `python_sanitizer.py` (line 72). Consistent with the
  matplotlib block: the sandbox directs all visualization through
  structured-chart / A2UI / altair.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential).
- All 6 modules modify tightly coupled files and share a single validation
  pass (`grep -rn "import matplotlib" packages/ai-parrot/src/` must return 0).
  Parallel execution would create merge conflicts.
- **Cross-feature dependencies**: None — this spec is self-contained.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-16 | Jesus Lara | Initial draft |
