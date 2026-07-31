"""Byte-identical output tests for the Python language plugin.

Pins that :class:`PythonScanner` produces exactly the same summary,
outline lines, and imports as the legacy ``_python_outline``/
``_module_index`` functions still living in ``repo_scan.py`` (removed in
TASK-2012, once the registry is wired in).
"""

from parrot.knowledge.wiki.languages import scanner_for
from parrot.knowledge.wiki.languages.python import PythonScanner
from parrot.knowledge.wiki.repo_scan import _module_index, _python_outline

SAMPLE_PYTHON = '''
"""Module docstring."""

import os
from pathlib import Path

class Foo:
    """Foo class."""
    def bar(self, x: int) -> str:
        """Bar method."""
        ...

async def baz(name: str) -> None:
    """Top-level async function."""
    ...
'''


def test_python_plugin_byte_identical():
    scanner = PythonScanner()
    result = scanner.outline(SAMPLE_PYTHON, "pkg/mod.py")
    legacy_summary, legacy_outline, legacy_imports = _python_outline(SAMPLE_PYTHON)
    assert result.summary == legacy_summary
    assert result.outline == legacy_outline
    assert result.imports == legacy_imports


def test_python_plugin_syntax_error_degrades_empty():
    scanner = PythonScanner()
    result = scanner.outline("def broken(:\n", "pkg/broken.py")
    legacy_summary, legacy_outline, legacy_imports = _python_outline("def broken(:\n")
    assert result.summary == legacy_summary == ""
    assert result.outline == legacy_outline == []
    assert result.imports == legacy_imports == []


def test_python_module_index_equivalence():
    scanner = PythonScanner()
    paths = ["src/pkg/mod.py", "src/pkg/__init__.py", "lib/util.py", "README.md"]
    plugin_index = scanner.build_reference_index(paths)
    legacy_index = _module_index(paths)
    assert plugin_index == legacy_index


def test_python_resolve_import():
    scanner = PythonScanner()
    index = {"pkg.mod": "src/pkg/mod.py", "pkg": "src/pkg/__init__.py"}
    assert scanner.resolve_import("pkg.mod", "other.py", index) == "src/pkg/mod.py"
    assert scanner.resolve_import("pkg.mod", "src/pkg/mod.py", index) is None  # self
    assert scanner.resolve_import("nonexistent.module", "x.py", index) is None


def test_scanner_for_py_returns_python_scanner():
    scanner = scanner_for(".py")
    assert isinstance(scanner, PythonScanner)


def test_scanner_for_pyi_returns_same_scanner():
    assert scanner_for(".pyi") is scanner_for(".py")


def test_python_scanner_mode_is_ast():
    assert PythonScanner().mode == "ast"
