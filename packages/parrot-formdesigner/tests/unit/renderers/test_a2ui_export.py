"""Lazy-export test for ``A2UIFormRenderer`` (FEAT-544, TASK-3073)."""

from __future__ import annotations

import ast
import inspect

import pytest


def test_lazy_export():
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot_formdesigner import renderers

    assert "A2UIFormRenderer" in renderers.__all__
    assert renderers.A2UIFormRenderer.__name__ == "A2UIFormRenderer"


def test_package_import_does_not_import_ai_parrot_eagerly():
    """No top-level ``import``/``from`` in ``renderers/__init__.py`` names ``parrot``."""
    import parrot_formdesigner.renderers as renderers_pkg

    tree = ast.parse(inspect.getsource(renderers_pkg))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("parrot."), f"unexpected top-level import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            assert not module_name.startswith("parrot."), f"unexpected top-level import: {module_name}"
