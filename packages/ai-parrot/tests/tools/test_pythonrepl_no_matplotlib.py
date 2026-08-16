"""Regression tests for FEAT-423 (TASK-2218): PythonREPLTool matplotlib/seaborn purge.

Verifies:
- matplotlib/seaborn/bokeh are gone from the REPL namespace.
- The removed plot-helper functions no longer exist.
- ``plt_style``/``palette``/``auto_save_plots``/``return_plot_as_base64``
  are no longer named constructor parameters.
- ``matplotlib``/``matplotlib.pyplot`` are blocked imports.
- altair/plotly/core libs are unaffected.

Deviation from the task's literal Test Specification (documented in the
Completion Note): ``PythonREPLTool.__init__`` forwards unrecognized
``**kwargs`` to ``AbstractTool.__init__``, which also accepts ``**kwargs``
and stores them in ``_init_kwargs`` without raising. So passing
``plt_style=...``/``palette=...``/etc. is silently absorbed rather than
raising ``TypeError`` — the removed params are verified via
``inspect.signature`` and by asserting the resulting instance never gets a
``plt_style``/``palette``/... attribute, instead of ``pytest.raises(TypeError)``.
"""

from __future__ import annotations

import inspect

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
        """plt_style/palette are not named constructor params.

        See module docstring: unlike a strict ``TypeError``, unknown kwargs
        are silently absorbed by ``AbstractTool.__init__``'s own
        ``**kwargs`` — verify removal via the signature and via the absence
        of the resulting instance attribute instead.
        """
        sig = inspect.signature(PythonREPLTool.__init__)
        assert "plt_style" not in sig.parameters
        assert "palette" not in sig.parameters

        tool = PythonREPLTool(plt_style="dark_background", palette="Set1")
        assert not hasattr(tool, "plt_style")
        assert not hasattr(tool, "palette")

    def test_no_auto_save_plots_param(self):
        """auto_save_plots/return_plot_as_base64 are not named constructor params."""
        sig = inspect.signature(PythonREPLTool.__init__)
        assert "auto_save_plots" not in sig.parameters
        assert "return_plot_as_base64" not in sig.parameters

        tool = PythonREPLTool(auto_save_plots=True, return_plot_as_base64=True)
        assert not hasattr(tool, "auto_save_plots")
        assert not hasattr(tool, "return_plot_as_base64")

    def test_matplotlib_in_blocked_imports(self):
        """matplotlib must be in BLOCKED_IMPORTS."""
        assert "matplotlib" in PythonREPLTool.BLOCKED_IMPORTS
        assert "matplotlib.pyplot" in PythonREPLTool.BLOCKED_IMPORTS

    def test_matplotlib_import_blocked_at_runtime(self):
        """User code ``import matplotlib`` is blocked by the sandbox gate."""
        tool = PythonREPLTool()
        error = tool._host_gate_check("import matplotlib")
        assert error is not None
        assert "blocked" in error.lower()

    def test_altair_still_available(self):
        """altair should still be lazy-loaded when installed."""
        # altair is optional — may or may not be in locals depending on
        # install, but the key invariant is that it's NOT blocked.
        assert "altair" not in PythonREPLTool.BLOCKED_IMPORTS

    def test_core_libs_still_present(self):
        """pd, np, numexpr must still be available."""
        tool = PythonREPLTool()
        assert "pd" in tool.locals
        assert "np" in tool.locals
        assert "numexpr" in tool.locals

    def test_no_matplotlib_module_imports(self):
        """No module-level or lazy imports of matplotlib remain in pythonrepl.py."""
        import parrot.tools.pythonrepl as pythonrepl_module

        source = inspect.getsource(pythonrepl_module)
        assert "import matplotlib" not in source
        assert "import seaborn" not in source
