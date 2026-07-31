# TASK-2013: PHP scanner plugin — outline + PSR-4/require resolution

**Feature**: FEAT-394 — Pluggable Language Scanners for wikitoolkit build
**Spec**: `sdd/specs/wikitoolkit-language-plugins.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2010, TASK-2012
**Assigned-to**: unassigned

---

## Context

> Spec Module 4. Implements the PHP language scanner with tree-sitter +
> heuristic fallback outline and two import resolution modes: PSR-4 via
> composer.json and relative require/include paths.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/languages/php.py`
  implementing `PhpScanner(LanguageScanner)`.
- `suffixes = frozenset({".php"})`, `name = "php"`.
- **Outline** (both modes):
  - Extract: classes, interfaces, traits, enums, functions, methods.
  - Include docblock (`/** ... */`) first line as the description.
  - tree-sitter mode: use `tree_sitter_php` grammar via `get_parser("php")`.
  - Heuristic mode: line-anchored regex extraction (no catastrophic backtrack).
- **Import extraction**:
  - `use A\B\C;` (including group `use A\{B, C};`).
  - `require`/`include`/`require_once`/`include_once` with string literal paths.
- **Reference resolution** (`build_reference_index` + `resolve_import`):
  - Parse `composer.json` PSR-4 autoload maps when present in the repo root.
  - Map namespaced `use` statements to file paths via PSR-4.
  - Resolve `require`/`include` paths relative to the importing file.
  - Heuristic fallback: namespace-tail ↔ path matching when no composer.json.
- Register `PhpScanner` in `languages/__init__.py`.
- Write unit tests for both modes.

**NOT in scope**: JS/TS plugin (TASK-2014), Rust plugin (TASK-2015).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/php.py` | CREATE | `PhpScanner` implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py` | MODIFY | Register PhpScanner |
| `tests/knowledge/wiki/languages/test_php_plugin.py` | CREATE | Unit tests |
| `tests/knowledge/wiki/languages/conftest.py` | CREATE or MODIFY | Shared fixtures (`force_heuristic`, `polyglot_repo` start) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.languages.base import LanguageScanner, LanguageOutline
# verified: created in TASK-2010

from parrot.knowledge.wiki.languages.treesitter import get_parser
# verified: created in TASK-2010
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py (TASK-2010)
class LanguageScanner(ABC):
    name: ClassVar[str]
    suffixes: ClassVar[frozenset[str]]
    def outline(self, source: str, rel_path: str) -> LanguageOutline: ...
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...
    def resolve_import(self, spec: str, from_file: str, index: Any) -> Optional[str]: ...
    @property
    def mode(self) -> str: ...
```

### Does NOT Exist

- ~~`PhpScanner`~~ — does not exist yet; this task creates it.
- ~~`tree_sitter_php` anywhere in the repo~~ — only `tree_sitter_python` exists.
- ~~`.php` in any suffix set~~ — not scanned today; TASK-2012 adds it to `CODE_SUFFIXES`.

---

## Implementation Notes

### Outline Format

Match the existing Python outline style for uniformity:
```
class ClassName: First line of docblock
    def methodName(params): First line of docblock
trait TraitName: First line of docblock
interface InterfaceName: First line of docblock
enum EnumName: First line of docblock
function functionName(params): First line of docblock
```

### PHP Heuristic Patterns (line-anchored)

```python
RE_PHP_CLASS = re.compile(r"^\s*(?:abstract\s+|final\s+)?class\s+(\w+)", re.MULTILINE)
RE_PHP_INTERFACE = re.compile(r"^\s*interface\s+(\w+)", re.MULTILINE)
RE_PHP_TRAIT = re.compile(r"^\s*trait\s+(\w+)", re.MULTILINE)
RE_PHP_ENUM = re.compile(r"^\s*enum\s+(\w+)", re.MULTILINE)
RE_PHP_FUNCTION = re.compile(r"^\s*(?:public|protected|private|static|\s)*function\s+(\w+)\s*\(([^)]*)\)", re.MULTILINE)
RE_PHP_USE = re.compile(r"^\s*use\s+([\w\\]+)(?:\s*\{([^}]+)\})?\s*;", re.MULTILINE)
RE_PHP_REQUIRE = re.compile(r"^\s*(?:require|include|require_once|include_once)\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
RE_PHP_NAMESPACE = re.compile(r"^\s*namespace\s+([\w\\]+)\s*;", re.MULTILINE)
```

### PSR-4 Resolution

```python
def _load_psr4_map(self, rel_paths):
    # Find composer.json in the file list
    # Parse autoload.psr-4 map: {"App\\": "src/"}
    # Return dict mapping namespace prefix → directory prefix
    ...

def resolve_import(self, spec, from_file, index):
    psr4_map, file_set = index
    if "\\" in spec:
        # Try PSR-4 resolution
        for ns_prefix, dir_prefix in psr4_map.items():
            if spec.startswith(ns_prefix):
                relative = spec[len(ns_prefix):].replace("\\", "/") + ".php"
                candidate = dir_prefix + relative
                if candidate in file_set:
                    return candidate
        # Fallback: namespace-tail matching
        tail = spec.rsplit("\\", 1)[-1]
        # Search for files ending in tail.php
        ...
    else:
        # require/include: resolve relative to from_file
        ...
```

### Key Constraints

- Heuristic regexes must be line-anchored and bounded — no catastrophic backtrack
  (the hook runs on every commit).
- PHP files may open with HTML before `<?php` — heuristic must tolerate this.
- POSIX rel-paths throughout.
- Parse failure → `LanguageOutline()` (empty), never raise.
- Google-style docstrings + strict type hints.

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.languages.php import PhpScanner` works
- [ ] `scanner_for(".php")` returns a `PhpScanner` instance
- [ ] `PhpScanner().mode` returns `"tree-sitter"` or `"heuristic"` depending on availability
- [ ] Outline extracts classes, interfaces, traits, enums, functions, methods with docblock
- [ ] `use App\Models\User;` and group `use App\{A, B};` extracted as imports
- [ ] `require 'path/to/file.php';` extracted as import
- [ ] PSR-4 composer.json map resolves namespace to file path
- [ ] Relative require resolves to correct file
- [ ] Heuristic fallback produces valid (if less precise) outlines
- [ ] All tests pass: `pytest tests/knowledge/wiki/languages/test_php_plugin.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/languages/php.py`

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_php_plugin.py
SAMPLE_PHP = '''<?php
namespace App\\Models;

use App\\Base\\Model;
use App\\Traits\\{HasTimestamps, SoftDeletes};

/**
 * User model for authentication.
 */
class User extends Model {
    /**
     * Get the full name.
     */
    public function getFullName(): string { ... }
}

function helper_function(string $x): void { ... }
'''

def test_php_outline_heuristic(force_heuristic):
    scanner = PhpScanner()
    result = scanner.outline(SAMPLE_PHP, "src/Models/User.php")
    assert any("class User" in line for line in result.outline)
    assert any("getFullName" in line for line in result.outline)
    assert "App\\Base\\Model" in result.imports

def test_php_psr4_resolution():
    scanner = PhpScanner()
    rel_paths = ["src/Models/User.php", "src/Base/Model.php", "composer.json"]
    index = scanner.build_reference_index(rel_paths)
    target = scanner.resolve_import("App\\Base\\Model", "src/Models/User.php", index)
    assert target == "src/Base/Model.php"

def test_php_require_relative():
    scanner = PhpScanner()
    rel_paths = ["lib/a.php", "lib/helpers/b.php"]
    index = scanner.build_reference_index(rel_paths)
    target = scanner.resolve_import("helpers/b.php", "lib/a.php", index)
    assert target == "lib/helpers/b.php"

def test_php_tolerates_html_prefix(force_heuristic):
    source = '<html><body><?php class Foo {} ?>'
    scanner = PhpScanner()
    result = scanner.outline(source, "mixed.php")
    assert any("Foo" in line for line in result.outline)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2010 and TASK-2012 must be done
3. **Verify the Codebase Contract** — confirm ABC signatures from TASK-2010
4. **Update status** in `sdd/tasks/index/wikitoolkit-language-plugins.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2013-php-scanner-plugin.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-31
**Notes**: Implemented `PhpScanner` (heuristic mode fully tested; a
best-effort tree-sitter path is implemented but untestable in this dev
environment since `tree_sitter_php` is not installed — no `wiki-languages`
extra yet, that lands in TASK-2016 — so it is exercised only via defensive
`try/except` degrade-to-empty, never invoked by the test suite).
Heuristic outline extracts classes/interfaces/traits/enums/functions/
methods with PHPDoc first-line association (whitespace + modifier-keyword
gap check) and brace-depth method-vs-function classification. Group
`use A\{B, C};` expands to full dotted paths. `require`/`include`
(including `__DIR__ .` concatenation) extracted as raw specifiers.
`resolve_import` handles PSR-4 (via `composer.json` autoload map, parsed
from disk relative to CWD — `build_reference_index`'s `Iterable[str]`
signature per the frozen TASK-2010 ABC has no repo-root parameter, so
this only resolves when the process CWD is the scanned repo root, the
common case for the `wikitoolkit build` CLI; falls back to namespace-tail
matching otherwise, never raises) and relative require paths. Created
`tests/knowledge/wiki/languages/conftest.py` with the `force_heuristic`
fixture (monkeypatches `treesitter.get_parser`, which required switching
`php.py`'s import to `from parrot.knowledge.wiki.languages import
treesitter` + `treesitter.get_parser(...)` module-attribute calls instead
of a bound name, so the monkeypatch is visible to the scanner — this
same pattern should be reused by TASK-2014/2015). 13/13 new tests pass;
full `tests/knowledge/wiki/` suite (474 tests) passes; `ruff check` clean.

**Deviations from spec**: Heuristic regexes use a `(?<![\w$])` lookbehind
instead of the contract's literal `^...` + `re.MULTILINE` line anchoring.
Verified both cannot be satisfied simultaneously: the task's own
`test_php_tolerates_html_prefix` fixture (`'<html><body><?php class Foo
{} ?>'`) has no newline before `class`, so a strict line-start anchor
would never match it. The lookbehind keeps the same "no nested
quantifiers, bounded character classes" property that actually prevents
catastrophic backtracking, so the safety goal is preserved.
