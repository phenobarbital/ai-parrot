"""Regression tests: `agents/flex_dashboard` is parent-agnostic (FEAT-528 TASK-2872).

Both tests run in a subprocess so the absence of a top-level ``agents``
package is genuine, not just "not imported yet in this interpreter".
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_transformers_import_under_foreign_parent(tmp_path):
    """The regression test for the reported defect (spec §4)."""
    host = tmp_path / "hostpkg"
    host.mkdir()
    (host / "__init__.py").write_text("")
    shutil.copytree(REPO / "agents" / "flex_dashboard", host / "flex_dashboard")
    code = textwrap.dedent(
        """
        import hostpkg.flex_dashboard.transformers
        from parrot.outputs.a2ui.recipes.transformers import transformer_registry
        transformer_registry.get("payroll_hero")   # raises if absent
        print("OK")
        """
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


def test_flex_module_loads_without_agents_package(tmp_path):
    code = textwrap.dedent(
        f"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("flex_mod", r"{REPO / 'agents' / 'flex_dashboard.py'}")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        assert hasattr(mod, "FlexDashboard")
        from parrot.outputs.a2ui.recipes.transformers import transformer_registry
        transformer_registry.get("payroll_hero")
        print("OK")
        """
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
