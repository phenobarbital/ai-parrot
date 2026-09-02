# TASK-2741: Python `SymbolRecord`s from stdlib `ast` (+ optional ast-grep enrichment)

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2739
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (Python half), resolved decision "Python source of truth
stays `ast`". `PythonScanner` must always emit `SymbolRecord`s (so Python
`sym:` pages exist with no optional extra installed) and keep its outline
strings unchanged. ast-grep, when present, only contributes `calls` refs
(rule file lands in TASK-2746) and never replaces the `ast` symbol list.

---

## Scope

- In `languages/python.py::PythonScanner.outline()`: while walking `tree.body`
  (and class bodies) build `SymbolRecord`s for `ClassDef` (kind `CLASS`,
  depth 1), top-level `FunctionDef`/`AsyncFunctionDef` (kind `FUNCTION`, depth 1)
  and class-body functions (kind `METHOD`, depth 2, `parent=<ClassName>`,
  `qualname="Class.method"`); populate `signature` via `ast.unparse(node.args)`
  (+ `" -> " + ast.unparse(node.returns)` when present), `decorators` via
  `ast.unparse`, `is_async`, `doc` (first docstring line — reuse `_first_line`),
  `exported = not name.startswith("_")`, `start_line/end_line`
  (`lineno`/`end_lineno`), `start_byte/end_byte` from a precomputed
  line-offset table + `col_offset`/`end_col_offset` (UTF-8 byte columns),
  `content_hash = sha1_of_text(ast.get_source_segment(source, node) or "")`,
  `node_kind = type(node).__name__`.
- Honour `symbol_depth` via the same module-level helper TASK-2740 introduced
  (default 2; depth 3+ = nested defs, only when configured).
- Optional enrichment: if `astgrep.extract(source, "python", rel_path)` returns
  a result, merge **only** its `refs` into `LanguageOutline.refs` (symbols
  stay `ast`-derived). Outline strings unchanged (:69, :74, :78).
- `mode` stays `"ast"`.
- Tests in `test_python_plugin.py`: symbols without the extra, byte offsets
  against `source.encode()[start:end]`, async/decorators/depth, unchanged
  outline lines, syntax-error path returns empty `LanguageOutline()`.

**NOT in scope**: `python.yaml` (TASK-2746), rendering via `render_outline`
(Python keeps its own outline emission), persistence.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/python.py` | MODIFY | Emit `SymbolRecord`s; merge ast-grep refs |
| `tests/knowledge/wiki/languages/test_python_plugin.py` | MODIFY | Symbol tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import ast
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord, SymbolRef, sha1_of_text   # TASK-2738
from parrot.knowledge.wiki.languages import astgrep                                          # TASK-2739
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner            # languages/__init__.py:14
from parrot.knowledge.wiki.languages.python import PythonScanner                              # python.py:30
```

### Existing Signatures to Use
```python
# languages/python.py
class PythonScanner(LanguageScanner):                           # :30
    def outline(self, source: str, rel_path: str) -> LanguageOutline:   # :36
        tree = ast.parse(source, filename=rel_path or "<unknown>")      # :49 ; except (SyntaxError, ValueError): return LanguageOutline()
        summary = _first_line(ast.get_docstring(tree) or "")            # :53
        def _sig(node) -> str: ... f"({', '.join(names)})"              # :57-60  (arg NAMES only — keep for the outline line)
        for node in tree.body:                                          # :62
            ... outline.append(f"class {node.name}: {doc}".rstrip(": "))            # :69
            ... outline.append(f"    def {item.name}{_sig(item)}: {idoc}".rstrip(": "))   # :74
            ... outline.append(f"def {node.name}{_sig(node)}: {doc}".rstrip(": "))       # :78
        return LanguageOutline(summary=summary, outline=outline, imports=imports)        # :79
    def build_reference_index(self, rel_paths) -> Any       # :81
    def resolve_import(self, spec, from_file, index) -> str | None   # :111
    @property def mode(self) -> str  → "ast"                # :138
```

### Does NOT Exist
- ~~`SymbolRecord.signature` built from `_sig()`~~ — `_sig` yields arg names only (outline parity); the record's `signature` uses `ast.unparse(node.args)` (full params) — two different strings on purpose.
- ~~`ast.AST.start_byte`~~ — `ast` has line/col only; byte offsets must be computed from a line-offset table over `source.encode("utf-8")`.
- ~~`languages/rules/python.yaml`~~ — TASK-2746; until then `astgrep.extract(…, "python", …)` is `None` and refs are `[]`.
- ~~`render_outline` for Python~~ — not used; Python emits its own outline lines (unchanged).

---

## Implementation Notes

### Pattern to Follow
```python
def _byte_offsets(source: str) -> list[int]:
    """Cumulative UTF-8 byte offset of each line start (index 0 = line 1)."""
    offs, total = [0], 0
    for line in source.splitlines(keepends=True):
        total += len(line.encode("utf-8")); offs.append(total)
    return offs
# start_byte = offs[node.lineno - 1] + len(source_line[:node.col_offset].encode()) — note col_offset is ALREADY a UTF-8 byte offset in CPython ≥3.8, so start_byte = offs[lineno-1] + col_offset
```

### Key Constraints
- `col_offset`/`end_col_offset` are UTF-8 byte offsets in CPython; do not re-encode.
- Decorated defs: `lineno` points at the `def`, not the decorator — record
  `decorators` separately; `start_byte` from the def line (matches ast-grep's
  `function_definition` node, which excludes decorators).
- Keep the `except (SyntaxError, ValueError)` degrade path.
- Google docstrings, type hints, no prints.

### References in Codebase
- `languages/python.py:36-79` — current walker (extend in place).
- `tests/knowledge/wiki/languages/test_python_plugin.py` — existing expectations that must not change.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/languages/test_python_plugin.py tests/knowledge/wiki/languages/test_repo_scan_integration.py -v` passes with `force_no_astgrep` and with the seam available.
- [ ] Outline lines identical to before (`class X: doc`, `    def m(self, x): doc`, `def f(a, b): doc`).
- [ ] For every symbol: `source.encode()[start_byte:end_byte].decode() == ast.get_source_segment(source, node)`.
- [ ] `async def` → `is_async=True`; `@decorator` captured; methods have `parent`, `depth=2`, `qualname="Cls.m"`.
- [ ] `symbol_depth=1` yields classes/functions only.
- [ ] `mode == "ast"` always.
- [ ] `ruff` / `mypy` clean.

---

## Test Specification

```python
def test_python_symbols_without_extra(force_no_astgrep):
    src = 'class A:\n    """Doc."""\n    async def m(self, x: int) -> int:\n        return x\n\n@dec\ndef f(a, b=1): ...\n'
    out = PythonScanner().outline(src, "a.py")
    kinds = [(s.kind.value, s.qualname, s.depth) for s in out.symbols]
    assert kinds == [("class", "A", 1), ("method", "A.m", 2), ("function", "f", 1)]
    m = out.symbols[1]; assert m.is_async and m.signature.startswith("(self, x: int)") and m.parent == "A"
    f = out.symbols[2]; assert f.decorators == ["dec"]
    for s in out.symbols:
        assert src.encode()[s.start_byte:s.end_byte].decode().startswith(("class", "async def", "def"))
```

---

## Agent Instructions

1. Read spec §2 Overview ("Python exception") and §7 ("Python symbols from `ast`").
2. Confirm TASK-2739 completed. 3. Verify contract lines. 4. Index → `in-progress`.
5. Implement. 6. Tests in both modes. 7. Move to `completed/`. 8. Index → `done`.
9. Completion Note.

---

## Completion Note

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
