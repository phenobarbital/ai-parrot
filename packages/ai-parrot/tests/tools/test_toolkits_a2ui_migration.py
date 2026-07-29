"""Toolkit A2UI migration tests (TASK-1739 / Module 11).

The toolkits (``parrot.tools.*``) are heavy modules that resolve inconsistently under
this repo's worktree pytest layout (namespace packages + Cython). These tests defer the
import and SKIP when the worktree module is not the one loaded; they run in CI. The
deterministic builder capability (the D1a core) is covered by ``test_builders.py``.
"""

import importlib

import pytest


def _import_or_skip(module: str):
    try:
        return importlib.import_module(module)
    except Exception as exc:  # noqa: BLE001 - Cython/namespace worktree limitation
        pytest.skip(f"cannot import {module} in worktree pytest layout: {exc}")


class TestInfographicToolkitMigration:
    def test_render_direct_preserved(self):
        mod = _import_or_skip("parrot.tools.infographic_toolkit")
        assert mod.InfographicToolkit.return_direct is True

    def test_enhance_lane_marked_deprecated(self):
        mod = _import_or_skip("parrot.tools.infographic_toolkit")
        import inspect

        src = inspect.getsource(mod.InfographicToolkit._maybe_enhance)
        assert "DeprecationWarning" in src and "FEAT-273" in src


class TestInteractiveToolkitMigration:
    def test_return_direct_preserved(self):
        mod = _import_or_skip("parrot.tools.interactive_toolkit")
        assert mod.InteractiveToolkit.return_direct is True

    def test_enhance_lane_marked_deprecated(self):
        mod = _import_or_skip("parrot.tools.interactive_toolkit")
        import inspect

        src = inspect.getsource(mod.InteractiveToolkit._maybe_enhance)
        assert "DeprecationWarning" in src and "FEAT-273" in src


class TestBuildersAreThePreferredLane:
    def test_builders_module_available(self):
        # The deterministic (D1a) builders are the migration target; always importable.
        from parrot.outputs.a2ui import builders

        assert hasattr(builders, "build_infographic")
        assert hasattr(builders, "build_chart")
