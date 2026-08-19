# TASK-2259: Perl tree-sitter registration & dependency wiring

**Feature**: FEAT-432 — Wikitoolkit Perl Scanner
**Spec**: `sdd/specs/wikitoolkit-perl-scanner.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Before the `PerlScanner` class can use tree-sitter, the grammar must be
registered in the tree-sitter loader module and the wheel added to the
`wiki-languages` optional dependency extra. This task also adds the
scanner registration entry in `__init__.py` — it will import
`PerlScanner` which does not yet exist, so TASK-2260 must land before
this task's registration line becomes importable. However, the
tree-sitter and pyproject.toml changes are independent and should land
first so the grammar is available when the scanner is implemented.

Implements spec Modules 1, 3, and 4.

---

## Scope

- Add `"perl": "tree_sitter_perl"` to `_GRAMMAR_MODULES` in `treesitter.py`.
- Add `"perl": ("language",)` to `_GRAMMAR_CALLABLES` in `treesitter.py`.
- Add `"tree-sitter-perl>=0.23"` to the `wiki-languages` extra in
  `packages/ai-parrot/pyproject.toml`.
- Add `from parrot.knowledge.wiki.languages.perl import PerlScanner` and
  `"perl": PerlScanner()` to `_SCANNERS` in `__init__.py`.

**NOT in scope**: The `PerlScanner` class itself (TASK-2260), tests
(TASK-2262), or the `wiki` meta-extra (already added separately).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py` | MODIFY | Add perl grammar entries to `_GRAMMAR_MODULES` and `_GRAMMAR_CALLABLES` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py` | MODIFY | Import `PerlScanner` and add to `_SCANNERS` |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `tree-sitter-perl>=0.23` to `wiki-languages` extra |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# No new imports needed — this task only edits existing module-level dicts
# and adds one import line in __init__.py:
from parrot.knowledge.wiki.languages.perl import PerlScanner  # will exist after TASK-2260
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py
_GRAMMAR_MODULES: dict[str, str] = {       # line 30
    "php": "tree_sitter_php",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "rust": "tree_sitter_rust",
}

_GRAMMAR_CALLABLES: dict[str, tuple[str, ...]] = {  # line 51
    "php": ("language", "language_php"),
    "javascript": ("language",),
    "typescript": ("language", "language_typescript"),
    "rust": ("language",),
}

# packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py
_SCANNERS: dict[str, LanguageScanner] = {   # line 31
    "python": PythonScanner(),
    "php": PhpScanner(),
    "javascript": JavaScriptScanner(),
    "rust": RustScanner(),
}
```

### Does NOT Exist

- ~~`treesitter.register_grammar()`~~ — no such function; edit dicts directly
- ~~`tree_sitter_perl.language_perl()`~~ — the wheel uses `language()`, not `language_perl()`
- ~~`LanguageScanner.register()`~~ — no auto-registration mechanism

---

## Implementation Notes

### Pattern to Follow

Each existing language has exactly one entry in `_GRAMMAR_MODULES` and one
in `_GRAMMAR_CALLABLES`. Perl's grammar wheel (`tree_sitter_perl`) is a
single-grammar wheel exposing `language()` — the same convention as
`tree_sitter_rust` and `tree_sitter_javascript`.

### Key Constraints

- `_GRAMMAR_CALLABLES["perl"]` must be `("language",)` — the wheel exposes
  `tree_sitter_perl.language()`, verified against PyPI 1.2.1.
- The `__init__.py` import will fail until TASK-2260 creates `perl.py`.
  If implementing these sequentially, commit treesitter.py + pyproject.toml
  first, then `__init__.py` after `perl.py` exists.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py` — grammar loader
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py` — scanner registry
- `packages/ai-parrot/pyproject.toml` — `wiki-languages` extra (line ~218)

---

## Acceptance Criteria

- [ ] `treesitter.get_parser("perl")` returns a `Parser` when `tree-sitter-perl` is installed
- [ ] `treesitter.get_parser("perl")` returns `None` when `tree-sitter-perl` is NOT installed
- [ ] `scanner_for(".pm")` returns a `PerlScanner` instance (after TASK-2260)
- [ ] `scanner_for(".pl")` returns a `PerlScanner` instance (after TASK-2260)
- [ ] `tree-sitter-perl>=0.23` is in the `wiki-languages` extra
- [ ] No changes to existing scanner registrations

---

## Test Specification

```python
# Verification (after TASK-2260 lands):
from parrot.knowledge.wiki.languages import treesitter

def test_perl_grammar_loads():
    parser = treesitter.get_parser("perl")
    assert parser is not None  # when tree-sitter-perl installed
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `_GRAMMAR_MODULES` and
   `_GRAMMAR_CALLABLES` still have the same structure
4. **Implement** the three one-line additions
5. **Note**: The `__init__.py` import will fail until TASK-2260 creates
   `perl.py`. Either commit `__init__.py` last, or implement TASK-2259
   and TASK-2260 together.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
