"""Byte-identical output tests for the Python language plugin.

Pins that :class:`PythonScanner` produces exactly the same summary,
outline lines, and imports as the legacy ``_python_outline``/
``_module_index`` functions still living in ``repo_scan.py`` (removed in
TASK-2012, once the registry is wired in).
"""

from parrot.knowledge.wiki.languages import scanner_for
from parrot.knowledge.wiki.languages.python import (
    PythonScanner,
    get_symbol_depth,
    set_symbol_depth,
)
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


# ---------------------------------------------------------------------
# FEAT-498 — SymbolRecords from stdlib ast (TASK-2741)
# ---------------------------------------------------------------------


SAMPLE_SYMBOLS_SRC = (
    'class A:\n    """Doc."""\n    async def m(self, x: int) -> int:\n' "        return x\n\n@dec\ndef f(a, b=1): ...\n"
)


def test_python_symbols_without_extra(force_no_astgrep):
    out = PythonScanner().outline(SAMPLE_SYMBOLS_SRC, "a.py")
    kinds = [(s.kind.value, s.qualname, s.depth) for s in out.symbols]
    assert kinds == [("class", "A", 1), ("method", "A.m", 2), ("function", "f", 1)]
    method = out.symbols[1]
    assert method.is_async
    assert method.signature.startswith("(self, x: int)")
    assert method.parent == "A"
    func = out.symbols[2]
    assert func.decorators == ["dec"]
    for sym in out.symbols:
        segment = SAMPLE_SYMBOLS_SRC.encode()[sym.start_byte : sym.end_byte].decode()
        assert segment.startswith(("class", "async def", "def"))


def test_python_symbols_byte_offsets_match_get_source_segment(force_no_astgrep):
    import ast

    out = PythonScanner().outline(SAMPLE_SYMBOLS_SRC, "a.py")
    tree = ast.parse(SAMPLE_SYMBOLS_SRC)
    nodes = {"A": tree.body[0], "f": tree.body[1]}
    for sym in out.symbols:
        if sym.qualname == "A.m":
            node = tree.body[0].body[1]
        else:
            node = nodes[sym.qualname]
        expected = ast.get_source_segment(SAMPLE_SYMBOLS_SRC, node)
        actual = SAMPLE_SYMBOLS_SRC.encode()[sym.start_byte : sym.end_byte].decode()
        assert actual == expected


def test_python_symbol_outline_lines_unchanged(force_no_astgrep):
    """Adding SymbolRecords must not change the rendered outline strings."""
    result = PythonScanner().outline(SAMPLE_PYTHON, "pkg/mod.py")
    legacy_summary, legacy_outline, legacy_imports = _python_outline(SAMPLE_PYTHON)
    assert result.summary == legacy_summary
    assert result.outline == legacy_outline
    assert result.imports == legacy_imports
    assert [s.qualname for s in result.symbols] == ["Foo", "Foo.bar", "baz"]


def test_python_symbol_depth_1_yields_top_level_only(force_no_astgrep):
    set_symbol_depth(1)
    try:
        out = PythonScanner().outline(SAMPLE_SYMBOLS_SRC, "a.py")
        assert [s.qualname for s in out.symbols] == ["A", "f"]
    finally:
        set_symbol_depth(2)


def test_get_symbol_depth_default_is_two():
    assert get_symbol_depth() == 2


def test_python_syntax_error_yields_no_symbols(force_no_astgrep):
    out = PythonScanner().outline("def broken(:\n", "broken.py")
    assert out.symbols == []
    assert out.refs == []


def test_python_mode_is_always_ast(force_no_astgrep):
    PythonScanner().outline(SAMPLE_SYMBOLS_SRC, "a.py")
    assert PythonScanner().mode == "ast"
