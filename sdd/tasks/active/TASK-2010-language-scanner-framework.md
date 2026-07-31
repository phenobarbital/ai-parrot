# TASK-2010: Plugin framework — LanguageScanner ABC, registry, tree-sitter helper

**Feature**: FEAT-394 — Pluggable Language Scanners for wikitoolkit build
**Spec**: `sdd/specs/wikitoolkit-language-plugins.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 1. Creates the foundational plugin framework that all language
> scanners will implement. This is the first task because every subsequent
> task depends on the ABC, the registry functions, and the tree-sitter helper.

---

## Scope

- Create package `packages/ai-parrot/src/parrot/knowledge/wiki/languages/`
  with `__init__.py`, `base.py`, and `treesitter.py`.
- Implement `LanguageOutline` Pydantic model in `base.py`.
- Implement `LanguageScanner` ABC in `base.py` with:
  - `name: ClassVar[str]`, `suffixes: ClassVar[frozenset[str]]`
  - `outline(source, rel_path) -> LanguageOutline`
  - `build_reference_index(rel_paths) -> Any`
  - `resolve_import(spec, from_file, index) -> Optional[str]`
  - `mode` property returning `"ast" | "tree-sitter" | "heuristic"`
- Implement module-level registry functions in `__init__.py`:
  - `scanner_for(suffix) -> Optional[LanguageScanner]`
  - `all_scanners() -> dict[str, LanguageScanner]`
  - `scanned_suffixes() -> frozenset[str]`
- Implement `get_parser(language) -> Optional[Parser]` in `treesitter.py`:
  cached per process, returns `None` (never raises) when the optional
  dependency or grammar is missing.
- Write unit tests for the registry and tree-sitter helper.

**NOT in scope**: any concrete language scanner (Python/PHP/JS/Rust) — those
are separate tasks. The `__init__.py` will register scanners as they are
added in subsequent tasks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py` | CREATE | Registry: `scanner_for`, `all_scanners`, `scanned_suffixes` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py` | CREATE | `LanguageOutline` model + `LanguageScanner` ABC |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py` | CREATE | `get_parser()` with process-level caching |
| `tests/knowledge/wiki/languages/__init__.py` | CREATE | Test package init |
| `tests/knowledge/wiki/languages/test_registry.py` | CREATE | Registry unit tests |
| `tests/knowledge/wiki/languages/test_treesitter.py` | CREATE | tree-sitter helper tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:205, :153
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:205
class WikiPageRecord(BaseModel):
    concept_id: str; node_id: Optional[str]; title: str; category: str
    summary: str; body: str; source_id: Optional[str]; token_count: int
    origin: str = "ingest"; asserted_by: Optional[str]

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:153
def estimate_tokens(text: str) -> int: ...
```

### tree-sitter Pattern Reference (do NOT import from graphindex)

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py:202-212
@staticmethod
def _build_parser():
    from tree_sitter import Language, Parser
    import tree_sitter_python
    lang = Language(tree_sitter_python.language())
    return Parser(lang)
```

### Does NOT Exist

- ~~`parrot/knowledge/wiki/languages/`~~ — package does not exist yet; every file is new.
- ~~`tree_sitter_php` / `tree_sitter_rust` / `tree_sitter_typescript` imports~~ — only `tree_sitter_python` used in graphindex.
- ~~`wiki-languages` extra in pyproject~~ — only `graphindex` extra exists (packages/ai-parrot/pyproject.toml:184).

---

## Implementation Notes

### Pattern to Follow

```python
# base.py — ABC pattern
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Iterable, Optional
from pydantic import BaseModel, Field

class LanguageOutline(BaseModel):
    summary: str = ""
    outline: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)

class LanguageScanner(ABC):
    name: ClassVar[str]
    suffixes: ClassVar[frozenset[str]]

    @abstractmethod
    def outline(self, source: str, rel_path: str) -> LanguageOutline: ...

    @abstractmethod
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...

    @abstractmethod
    def resolve_import(self, spec: str, from_file: str, index: Any) -> Optional[str]: ...

    @property
    def mode(self) -> str: ...
```

### Key Constraints

- Synchronous — no async (matches repo_scan.py style).
- `get_parser()` must be cached (module-level dict or `functools.lru_cache`).
- `get_parser()` must never raise — catch `ImportError`, `OSError`, any grammar load failure → `None`.
- Registry populated explicitly in `__init__.py` (no magic discovery / entry points).
- Google-style docstrings + strict type hints.
- `logging.getLogger(__name__)` for module loggers.

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.languages import scanner_for, all_scanners, scanned_suffixes` works
- [ ] `from parrot.knowledge.wiki.languages.base import LanguageScanner, LanguageOutline` works
- [ ] `scanner_for(".cfg")` returns `None` (no scanner registered for config files)
- [ ] `get_parser("nonexistent")` returns `None` without raising
- [ ] `get_parser()` result is cached (second call returns same object)
- [ ] All tests pass: `pytest tests/knowledge/wiki/languages/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/languages/`

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_registry.py
def test_scanner_for_unknown_suffix_returns_none():
    assert scanner_for(".cfg") is None

def test_scanned_suffixes_is_frozenset():
    assert isinstance(scanned_suffixes(), frozenset)

# tests/knowledge/wiki/languages/test_treesitter.py
def test_get_parser_missing_dep_returns_none(monkeypatch):
    # monkeypatch the import to fail
    ...
    assert get_parser("nonexistent_language") is None

def test_get_parser_caches_result():
    # call twice, assert same object identity
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm imports/signatures still exist
4. **Update status** in `sdd/tasks/index/wikitoolkit-language-plugins.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2010-language-scanner-framework.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
