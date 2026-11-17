"""parrot-formdesigner must import without the ai-parrot extra — FEAT-650 TASK-4205 (AC12)."""

from __future__ import annotations

import ast
import importlib
import inspect

import pytest

MODULES = [
    "parrot_formdesigner.api.dialect",
    "parrot_formdesigner.services.a2ui_export",
    "parrot_formdesigner.services.a2ui_translate",
    "parrot_formdesigner.extractors.a2ui",
    "parrot_formdesigner.extractors",
    "parrot_formdesigner.cli",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_no_top_level_parrot_import(module_name):
    """No module-level ``parrot.`` import (the optional extra) in the FEAT-650 modules."""
    mod = importlib.import_module(module_name)
    tree = ast.parse(inspect.getsource(mod))
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith("parrot.") for a in node.names), f"{module_name}: {ast.dump(node)}"
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("parrot."), f"{module_name}: {node.module}"
