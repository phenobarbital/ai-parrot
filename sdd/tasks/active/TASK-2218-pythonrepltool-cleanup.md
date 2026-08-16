# TASK-2218: PythonREPLTool — Remove matplotlib/seaborn integration

**Feature**: FEAT-423 — Purge Matplotlib & Heavy Renderer Libraries
**Spec**: `sdd/specs/purge-matplotlib-renderer-libs.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the core task of FEAT-423. PythonREPLTool currently pre-loads matplotlib,
seaborn, and related helper functions into the REPL namespace, steers LLMs toward
generating matplotlib code, and carries ~60 lines of defensive cleanup code for
matplotlib's non-GUI backend quirks. All of this must be removed — the REPL becomes
a pure compute engine; visualization flows through A2UI / structured-chart / altair.

Implements spec §Module 1.

---

## Scope

- **Remove** module-level matplotlib lazy init: `matplotlib = None`, `plt = None`,
  `_pylab_helpers = None` globals and the `_ensure_matplotlib()` function.
- **Remove** `_setup_charts()`, `_safe_close_all_plots()`, `_safe_matplotlib_cleanup()`
  methods.
- **Remove** `plt_style`, `palette`, `auto_save_plots`, `return_plot_as_base64`
  constructor params and their `self.*` assignments.
- **Remove** `import seaborn as sns` hard import from `_setup_environment()`.
- **Remove** `plt`, `matplotlib`, `sns` from `self.locals.update({...})`.
- **Remove** `save_current_plot()`, `get_plot_as_base64()`, `clear_plots()` closures
  and their entries in the locals dict.
- **Rewrite** `_get_default_setup_code()` — remove all matplotlib/seaborn init code.
- **Remove** `_setup_charts()` call from `__init__`.
- **Remove** `plt.style.use()` / `sns.set_palette()` from `_bootstrap()`.
- **Update** `_worker_repl_kwargs` to drop `plt_style` and `palette`.
- **Update** class docstring and `description` field.
- **Remove** `logging.getLogger("matplotlib")` silencer at module top.
- **Add** `"matplotlib"` and `"matplotlib.pyplot"` to `BLOCKED_IMPORTS` set.

**NOT in scope**:
- System prompt changes (TASK-2219)
- `python_sanitizer.py` allowlist changes (TASK-2220)
- ChartTool migration (TASK-2221)
- Documentation updates (TASK-2223)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/pythonrepl.py` | MODIFY | Remove all matplotlib/seaborn integration |
| `packages/ai-parrot/tests/tools/test_pythonrepl.py` | MODIFY | Update/add tests for matplotlib removal |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/tools/pythonrepl.py:54
from parrot.tools.abstract import AbstractTool

# packages/ai-parrot/src/parrot/tools/pythonrepl.py:53
from parrot._imports import lazy_import

# packages/ai-parrot/src/parrot/tools/pythonrepl.py:50
from pydantic import BaseModel, Field

# packages/ai-parrot/src/parrot/tools/pythonrepl.py:51
from datamodel.parsers.json import json_decoder, json_encoder

# packages/ai-parrot/src/parrot/tools/pythonrepl.py:52
from navconfig import BASE_DIR
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/pythonrepl.py

# Module-level globals to DELETE (lines 30-31, 33):
matplotlib = None   # type: ignore[assignment]
plt = None          # type: ignore[assignment]
_pylab_helpers = None  # type: ignore[assignment]

# Function to DELETE (lines 35-46):
def _ensure_matplotlib(): ...

# Class (line 105):
class PythonREPLTool(AbstractTool):
    name = "python_repl"  # line 117
    description = "Execute Python code with pre-loaded data science libraries (pandas, numpy, matplotlib, seaborn)"  # line 118
    _bootstrapped = False  # line 122
    BLOCKED_IMPORTS: set = {...}  # line 125 — ADD matplotlib, matplotlib.pyplot here

    def __init__(self,
        locals_dict, globals_dict, report_dir,
        plt_style: str = "seaborn-v0_8-whitegrid",  # line 209 — REMOVE
        palette: str = "Set2",                       # line 210 — REMOVE
        setup_code, sanitize_input_enabled,
        auto_save_plots: bool = True,                # line 213 — REMOVE
        return_plot_as_base64: bool = False,          # line 214 — REMOVE
        debug, policy, executor_max_workers,
        worker_config, **kwargs): ...                 # line 204

    def _setup_charts(self): ...           # line 324 — DELETE entirely
    def _safe_close_all_plots(self): ...   # line 351 — DELETE entirely
    def _safe_matplotlib_cleanup(self): ... # line 368 — DELETE entirely
    def _setup_environment(self): ...      # line 402 — MODIFY (remove sns import, plt/matplotlib/sns from locals)
    def _get_default_setup_code(self): ... # line 570 — REWRITE (remove matplotlib/seaborn init)
    def _bootstrap(self): ...              # line 606 — MODIFY (remove plt.style.use, sns.set_palette)

# _worker_repl_kwargs dict (lines 302-308):
self._worker_repl_kwargs = {
    "plt_style": plt_style,       # REMOVE
    "palette": palette,           # REMOVE
    "setup_code": self.setup_code,
    "auto_save_plots": auto_save_plots,          # REMOVE
    "return_plot_as_base64": return_plot_as_base64,  # REMOVE
}

# self.locals.update dict (lines 533-559):
# REMOVE: "plt": plt, "matplotlib": matplotlib, "sns": sns
# REMOVE: "save_current_plot": save_current_plot,
#         "get_plot_as_base64": get_plot_as_base64,
#         "clear_plots": clear_plots,

# _get_default_setup_code return value (lines 572-604):
# REMOVE all matplotlib/seaborn references in the f-string
```

### Does NOT Exist

- ~~`PythonREPLTool.set_visualization_backend()`~~ — not a real method
- ~~`PythonREPLTool.rendering_mode`~~ — not a real attribute
- ~~`parrot.tools.pythonrepl.AltairREPLTool`~~ — does not exist

---

## Implementation Notes

### Pattern to Follow

The existing lazy-import pattern for optional libs (lines 417-433) stays as-is
for altair/plotly/folium. The key change is that matplotlib and seaborn go from
"always loaded" to "blocked":

```python
# BEFORE: matplotlib was lazily imported and injected
# AFTER: matplotlib is in BLOCKED_IMPORTS — user code gets a clear error

BLOCKED_IMPORTS: set = {
    ...existing entries...,
    "matplotlib",
    "matplotlib.pyplot",
}
```

### Key Constraints

- `numexpr` stays — it's a core dependency for pandas acceleration.
- `altair`, `plotly`, `folium` stay as optional lazy-loaded libs.
- The `_repl_executor` ThreadPoolExecutor stays — it's used for general code
  execution isolation (FEAT-380), not just matplotlib.
- `_worker_repl_kwargs` must still be a dict, just with fewer keys — the worker
  process reads these to construct its own PythonREPLTool instance.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/pythonrepl.py` — the file being modified
- `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py` — consumes `_worker_repl_kwargs`

---

## Acceptance Criteria

- [ ] `PythonREPLTool().locals` does NOT contain `plt`, `matplotlib`, `sns`, or `bokeh`
- [ ] `PythonREPLTool.__init__` does NOT accept `plt_style`, `palette`,
  `auto_save_plots`, or `return_plot_as_base64` params
- [ ] No module-level or lazy imports of matplotlib anywhere in `pythonrepl.py`
- [ ] `"matplotlib"` and `"matplotlib.pyplot"` are in `BLOCKED_IMPORTS`
- [ ] `save_current_plot`, `get_plot_as_base64`, `clear_plots` functions no longer exist
- [ ] `_setup_charts`, `_safe_close_all_plots`, `_safe_matplotlib_cleanup` methods deleted
- [ ] `_get_default_setup_code()` produces no matplotlib/seaborn references
- [ ] `_bootstrap()` does not call `plt.style.use()` or `sns.set_palette()`
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/tools/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/pythonrepl.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_pythonrepl_no_matplotlib.py
import pytest
from parrot.tools.pythonrepl import PythonREPLTool


class TestPythonREPLNoMatplotlib:
    def test_no_matplotlib_in_namespace(self):
        """matplotlib, plt, sns must not be in REPL locals."""
        tool = PythonREPLTool()
        assert "plt" not in tool.locals
        assert "matplotlib" not in tool.locals
        assert "sns" not in tool.locals
        assert "bokeh" not in tool.locals

    def test_no_plot_helpers(self):
        """Plot helper functions must not exist."""
        tool = PythonREPLTool()
        assert "save_current_plot" not in tool.locals
        assert "get_plot_as_base64" not in tool.locals
        assert "clear_plots" not in tool.locals

    def test_no_plt_style_param(self):
        """Constructor must not accept plt_style or palette."""
        with pytest.raises(TypeError):
            PythonREPLTool(plt_style="dark_background")
        with pytest.raises(TypeError):
            PythonREPLTool(palette="Set1")

    def test_no_auto_save_plots_param(self):
        """Constructor must not accept auto_save_plots or return_plot_as_base64."""
        with pytest.raises(TypeError):
            PythonREPLTool(auto_save_plots=True)
        with pytest.raises(TypeError):
            PythonREPLTool(return_plot_as_base64=True)

    def test_matplotlib_in_blocked_imports(self):
        """matplotlib must be in BLOCKED_IMPORTS."""
        assert "matplotlib" in PythonREPLTool.BLOCKED_IMPORTS
        assert "matplotlib.pyplot" in PythonREPLTool.BLOCKED_IMPORTS

    def test_altair_still_available(self):
        """altair should still be lazy-loaded when installed."""
        tool = PythonREPLTool()
        # altair is optional — may or may not be in locals depending on install
        # but the key is it's NOT blocked
        assert "altair" not in PythonREPLTool.BLOCKED_IMPORTS

    def test_core_libs_still_present(self):
        """pd, np, numexpr must still be available."""
        tool = PythonREPLTool()
        assert "pd" in tool.locals
        assert "np" in tool.locals
        assert "numexpr" in tool.locals
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/purge-matplotlib-renderer-libs.spec.md`
2. **Check dependencies** — this task has none, start immediately
3. **Verify the Codebase Contract** — confirm all line numbers in `pythonrepl.py`
4. **Update status** in `sdd/tasks/index/purge-matplotlib-renderer-libs.json` → `"in-progress"`
5. **Implement** — work top-down: delete globals/functions first, then modify __init__, then _setup_environment, then _get_default_setup_code, then _bootstrap
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
