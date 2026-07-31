# TASK-2014: JS/TS scanner plugin — exported symbol outline + relative-specifier resolution

**Feature**: FEAT-394 — Pluggable Language Scanners for wikitoolkit build
**Spec**: `sdd/specs/wikitoolkit-language-plugins.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2010, TASK-2012
**Assigned-to**: unassigned

---

## Context

> Spec Module 5. Implements a single JS/TS scanner claiming
> `.js/.jsx/.mjs/.ts/.tsx` with tree-sitter + heuristic fallback. Resolves
> only relative import specifiers with extension guessing; bare package names
> are ignored.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py`
  implementing `JavaScriptScanner(LanguageScanner)`.
- `suffixes = frozenset({".js", ".jsx", ".mjs", ".ts", ".tsx"})`, `name = "javascript"`.
- **Outline** (both modes):
  - Extract: exported classes, functions, consts, interfaces, type aliases.
  - Non-exported top-level symbols included but marked differently.
  - tree-sitter mode: use `tree_sitter_typescript`/`tree_sitter_javascript` grammar.
  - Heuristic mode: line-anchored regex extraction.
- **Import extraction**:
  - `import ... from '...'` / `import '...'`
  - `export ... from '...'`
  - `require('...')`
  - Only relative specifiers (`./`, `../`) kept; bare package names dropped.
- **Reference resolution** (`build_reference_index` + `resolve_import`):
  - Relative specifier resolution with extension guessing:
    `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, then `/index.*` variants.
  - No `tsconfig.json` path alias resolution (out of scope per spec).
- Register `JavaScriptScanner` in `languages/__init__.py`.
- Write unit tests for both modes.

**NOT in scope**: PHP plugin (TASK-2013), Rust plugin (TASK-2015),
tsconfig `paths` alias resolution.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` | CREATE | `JavaScriptScanner` implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py` | MODIFY | Register JavaScriptScanner |
| `tests/knowledge/wiki/languages/test_javascript_plugin.py` | CREATE | Unit tests |

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

- ~~`JavaScriptScanner`~~ — does not exist yet; this task creates it.
- ~~`tree_sitter_typescript` / `tree_sitter_javascript` anywhere in the repo~~ — only `tree_sitter_python`.
- ~~tsconfig `paths` resolution~~ — explicitly out of scope for v1.

---

## Implementation Notes

### Outline Format

```
export class ClassName: First line of JSDoc
    method(params): First line of JSDoc
export function functionName(params): First line of JSDoc
export const CONSTANT_NAME
export interface InterfaceName: First line of JSDoc
export type TypeAlias = ...
class InternalClass: ...
function internalFunction(params): ...
```

### JS/TS Heuristic Patterns (line-anchored)

```python
RE_EXPORT_CLASS = re.compile(r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)
RE_EXPORT_FUNCTION = re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", re.MULTILINE)
RE_EXPORT_CONST = re.compile(r"^\s*export\s+(?:default\s+)?const\s+(\w+)", re.MULTILINE)
RE_EXPORT_INTERFACE = re.compile(r"^\s*export\s+(?:default\s+)?interface\s+(\w+)", re.MULTILINE)
RE_EXPORT_TYPE = re.compile(r"^\s*export\s+(?:default\s+)?type\s+(\w+)\s*=", re.MULTILINE)
RE_CLASS = re.compile(r"^\s*(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)
RE_FUNCTION = re.compile(r"^\s*(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", re.MULTILINE)

# Import extraction
RE_IMPORT_FROM = re.compile(r"""(?:import|export)\s+.*?\s+from\s+['"]([^'"]+)['"]""", re.MULTILINE)
RE_IMPORT_SIDE_EFFECT = re.compile(r"""import\s+['"]([^'"]+)['"]""", re.MULTILINE)
RE_REQUIRE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE)
```

### Extension Guessing Resolution

```python
EXTENSION_CANDIDATES = [".ts", ".tsx", ".js", ".jsx", ".mjs"]
INDEX_CANDIDATES = ["index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"]

def resolve_import(self, spec, from_file, index):
    if not spec.startswith("."):
        return None  # bare package → drop
    file_set = index
    base = PurePosixPath(from_file).parent / spec
    base_str = base.as_posix()
    # Try exact match
    if base_str in file_set:
        return base_str
    # Try with extensions
    for ext in EXTENSION_CANDIDATES:
        candidate = base_str + ext
        if candidate in file_set:
            return candidate
    # Try /index.*
    for idx in INDEX_CANDIDATES:
        candidate = base_str + "/" + idx
        if candidate in file_set:
            return candidate
    return None
```

### Key Constraints

- One scanner for all JS/TS suffixes — tree-sitter may need to pick the
  right grammar (typescript for `.ts/.tsx`, javascript for `.js/.jsx/.mjs`).
- Only **relative** specifiers (`./`, `../`) are resolved; bare names dropped.
- Heuristic regexes: line-anchored, bounded, no catastrophic backtrack.
- Parse failure → `LanguageOutline()` (empty), never raise.

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner` works
- [ ] `scanner_for(".ts")`, `scanner_for(".tsx")`, `scanner_for(".js")`, `scanner_for(".jsx")`, `scanner_for(".mjs")` all return `JavaScriptScanner`
- [ ] `JavaScriptScanner().mode` returns `"tree-sitter"` or `"heuristic"`
- [ ] Exported classes, functions, consts, interfaces, type aliases extracted
- [ ] `import { X } from './util'` extracted; `import React from 'react'` dropped
- [ ] `./util` resolves to `util.ts`, `util/index.ts`, etc. via extension guessing
- [ ] Bare package names (`react`, `lodash`) produce no edges
- [ ] Both tree-sitter and heuristic modes produce valid outlines
- [ ] All tests pass: `pytest tests/knowledge/wiki/languages/test_javascript_plugin.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py`

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_javascript_plugin.py
SAMPLE_TS = '''
import { Model } from './base/model';
import React from 'react';
export { helper } from './utils';

/**
 * Main service class.
 */
export class UserService {
    async getUser(id: string): Promise<User> { ... }
}

export interface UserConfig {
    name: string;
}

export type UserId = string;

export const DEFAULT_LIMIT = 10;

function internalHelper(): void { ... }
'''

def test_jsts_outline_exports(force_heuristic):
    scanner = JavaScriptScanner()
    result = scanner.outline(SAMPLE_TS, "src/services/user.ts")
    names = " ".join(result.outline)
    assert "UserService" in names
    assert "UserConfig" in names
    assert "UserId" in names
    assert "DEFAULT_LIMIT" in names

def test_jsts_relative_resolution():
    scanner = JavaScriptScanner()
    rel_paths = ["src/services/user.ts", "src/base/model.ts", "src/utils/index.ts"]
    index = scanner.build_reference_index(rel_paths)
    assert scanner.resolve_import("./base/model", "src/services/user.ts", index) == "src/base/model.ts"
    assert scanner.resolve_import("./utils", "src/services/user.ts", index) == "src/utils/index.ts"
    assert scanner.resolve_import("react", "src/services/user.ts", index) is None

def test_jsts_imports_only_relative():
    scanner = JavaScriptScanner()
    result = scanner.outline(SAMPLE_TS, "src/services/user.ts")
    assert "./base/model" in result.imports
    assert "./utils" in result.imports
    assert "react" not in result.imports
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
7. **Move this file** to `sdd/tasks/completed/TASK-2014-javascript-typescript-scanner-plugin.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
