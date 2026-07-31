# TASK-2011: Python scanner plugin — move existing logic behind LanguageScanner ABC

**Feature**: FEAT-394 — Pluggable Language Scanners for wikitoolkit build
**Spec**: `sdd/specs/wikitoolkit-language-plugins.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2010
**Assigned-to**: unassigned

---

## Context

> Spec Module 2. Relocates the existing `_python_outline()` and
> `_module_index()` logic from `repo_scan.py` into a `PythonScanner`
> class in `languages/python.py`. The output must be **byte-identical**
> to today's — the existing test suite (`test_repo_scan.py`) is the gate
> and must pass unchanged.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/languages/python.py`
  implementing `PythonScanner(LanguageScanner)`.
- Move `_python_outline()` body into `PythonScanner.outline()` — keep logic
  verbatim (including `rstrip(": ")` quirks).
- Move `_module_index()` body into `PythonScanner.build_reference_index()`.
- Implement `PythonScanner.resolve_import()` — extracted from the inner loop
  of `build_import_edges()` (dotted-prefix matching against the module index).
- `mode` property returns `"ast"`.
- `suffixes = frozenset({".py", ".pyi"})`, `name = "python"`.
- Register `PythonScanner` in `languages/__init__.py`.
- Write a byte-identical comparison test: run the plugin on a fixture corpus
  and compare output to the legacy `_python_outline()` function.

**NOT in scope**: modifying `repo_scan.py` to use the plugin (that is TASK-2012).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/python.py` | CREATE | `PythonScanner` implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py` | MODIFY | Register PythonScanner |
| `tests/knowledge/wiki/languages/test_python_plugin.py` | CREATE | Byte-identical output tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.languages.base import LanguageScanner, LanguageOutline
# verified: created in TASK-2010

import ast  # stdlib — used by _python_outline
from pathlib import PurePosixPath  # used by _module_index
```

### Existing Signatures to Move

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:425
def _python_outline(source: str) -> tuple[str, list[str], list[str]]:
    # Returns (summary, outline_lines, imports)
    # Uses ast.parse, walks ast.ClassDef/ast.FunctionDef/ast.AsyncFunctionDef
    # Summary = module docstring (first Expr(Constant(str)))
    # Imports = dotted module names from Import/ImportFrom

# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:644
def _module_index(rel_paths: Iterable[str]) -> dict[str, str]:
    # Maps dotted module names to relative file paths
    # Handles src-layout stripping: parts after "src" component
    # Only processes .py/.pyi files

# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:669-703
# build_import_edges inner loop — the resolve logic:
#   for module in fs.imports:
#       parts = module.split(".")
#       for depth in range(len(parts), 0, -1):
#           target = index.get(".".join(parts[:depth]))
#           if target: break
#       if target and target != fs.rel_path:
#           edges.add(...)
```

### Does NOT Exist

- ~~`PythonScanner`~~ — does not exist yet; this task creates it.
- ~~`LanguageScanner.outline()` returning a tuple~~ — it returns `LanguageOutline` (Pydantic model); convert the tuple internally.

---

## Implementation Notes

### Pattern to Follow

```python
class PythonScanner(LanguageScanner):
    name: ClassVar[str] = "python"
    suffixes: ClassVar[frozenset[str]] = frozenset({".py", ".pyi"})

    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        # Copy _python_outline body verbatim, return LanguageOutline
        summary, outline_lines, imports = self._python_outline(source)
        return LanguageOutline(summary=summary, outline=outline_lines, imports=imports)

    def build_reference_index(self, rel_paths):
        # Copy _module_index body verbatim
        ...

    def resolve_import(self, spec, from_file, index):
        parts = spec.split(".")
        for depth in range(len(parts), 0, -1):
            target = index.get(".".join(parts[:depth]))
            if target:
                return target if target != from_file else None
        return None

    @property
    def mode(self) -> str:
        return "ast"
```

### Key Constraints

- **Byte-identical output**: the moved code must produce the same summary,
  outline lines, and import lists as the original functions. Do not refactor,
  simplify, or "improve" the logic — including the `rstrip(": ")` quirk.
- The existing `tests/knowledge/wiki/test_repo_scan.py` test suite MUST pass
  unchanged after TASK-2012 wires this up.
- `_python_outline` and `_module_index` remain in `repo_scan.py` for now —
  they are NOT deleted in this task (TASK-2012 handles that transition).

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.languages.python import PythonScanner` works
- [ ] `scanner_for(".py")` returns a `PythonScanner` instance
- [ ] `scanner_for(".pyi")` returns the same scanner
- [ ] `PythonScanner().mode == "ast"`
- [ ] Plugin outline output matches `_python_outline()` exactly on fixture input
- [ ] Plugin `build_reference_index` + `resolve_import` produce the same edges as `_module_index` + the inner loop of `build_import_edges`
- [ ] All tests pass: `pytest tests/knowledge/wiki/languages/test_python_plugin.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/languages/python.py`

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_python_plugin.py
from parrot.knowledge.wiki.languages.python import PythonScanner
from parrot.knowledge.wiki.repo_scan import _python_outline, _module_index

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
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2010 must be done
3. **Verify the Codebase Contract** — read `_python_outline` and `_module_index` in repo_scan.py
4. **Update status** in `sdd/tasks/index/wikitoolkit-language-plugins.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2011-python-scanner-plugin.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
