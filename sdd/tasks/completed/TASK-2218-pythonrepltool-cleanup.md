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
| `packages/ai-parrot/tests/tools/test_pythonrepl_no_matplotlib.py` | CREATE | New tests for matplotlib removal (per Test Specification below) — `tests/tools/test_pythonrepl.py` named in the original contract does not exist |
| `packages/ai-parrot/src/parrot/tools/pythonpandas.py` | MODIFY | **(Scope expansion, resolved 2026-08-16)** `PythonPandasTool(PythonREPLTool)`'s `create_session_clone()` copies `self.plt_style`/`self.palette`/`self.auto_save_plots`/`self.return_plot_as_base64` onto the clone (lines ~267-271) — these attributes no longer exist once this task removes them from `PythonREPLTool.__init__`. Drop those 4 lines. Also fix two now-stale LLM-facing guidance references: a `matplotlib` entry in a library-guide dict (~line 46-55) and a `"...with matplotlib"` hint referencing the deleted `save_current_plot` (~line 469) — replace with altair/structured-chart guidance consistent with TASK-2219's policy. Not in the original spec's Module 1 breakdown; discovered during Codebase Contract verification. |
| `packages/ai-parrot/tests/repl_worker/test_integration.py` | MODIFY | **(Scope expansion, resolved 2026-08-16)** `TestPlots` class (`test_plot_via_shared_dir`, `test_plot_base64_when_enabled`) directly exercises `plt.plot()`, `save_current_plot()`, `return_plot_as_base64=True` — all removed by this task. Remove this test class. |

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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-16
**Notes**: Implemented as scoped, plus a user-approved scope expansion
discovered during Codebase Contract verification (see "Files to Create /
Modify" table above, entries marked "Scope expansion, resolved 2026-08-16"):
`PythonPandasTool.create_session_clone()` (packages/ai-parrot/src/parrot/tools/pythonpandas.py)
copied `plt_style`/`palette`/`auto_save_plots`/`return_plot_as_base64` onto
the clone — those lines were removed, and two stale matplotlib references in
its LLM-facing plotting guide (`PLOTTING_LIBRARIES` dict, `_generate_plotting_guide()`)
were updated to point at structured-chart/A2UI/altair. `test_integration.py`'s
`TestPlots` class (exercised `plt.plot()`/`save_current_plot()`/`return_plot_as_base64`)
was removed since it tested the now-deleted API.

The original contract's `packages/ai-parrot/tests/tools/test_pythonrepl.py`
did not exist; created `test_pythonrepl_no_matplotlib.py` instead, matching
the task's own Test Specification section.

All 9 new tests pass; full affected suite (test_pythonrepl_executor,
test_pythonrepl_security, repl_worker/*, test_pythonpandas_integration,
test_pythonpandas_preview, test_tool_clone, test_pythonrepl_no_matplotlib)
— 159 passed. `ruff check` on the two modified source files: 99 errors, all
pre-existing on `dev` (verified via `git show dev:<file>` — none introduced
by this task; count went DOWN from 117 due to dead-code removal).

`grep -rn "import matplotlib" packages/ai-parrot/src/` → zero matches (AC10).

**Deviations from spec**:
1. Two of the task's own literal Test Specification assertions
   (`test_no_plt_style_param`, `test_no_auto_save_plots_param`) expected
   `pytest.raises(TypeError)` when passing `plt_style=`/`palette=`/
   `auto_save_plots=`/`return_plot_as_base64=` to the constructor. In
   practice `PythonREPLTool.__init__`'s `**kwargs` forwards to
   `AbstractTool.__init__`, which also accepts arbitrary `**kwargs` and
   stores them in `_init_kwargs` without raising — so no `TypeError` is
   ever raised. Rewrote those two tests to assert via
   `inspect.signature()` (param absent) and `hasattr()` (no resulting
   instance attribute) instead. Documented at the top of
   `test_pythonrepl_no_matplotlib.py`.
2. Scope expansion into `pythonpandas.py` and `test_integration.py`
   (user-approved) — see Files table above and Notes.
