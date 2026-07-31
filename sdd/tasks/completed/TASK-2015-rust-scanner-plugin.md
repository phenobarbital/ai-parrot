# TASK-2015: Rust scanner plugin — pub-item outline + crate-layout resolution

**Feature**: FEAT-394 — Pluggable Language Scanners for wikitoolkit build
**Spec**: `sdd/specs/wikitoolkit-language-plugins.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2010, TASK-2012
**Assigned-to**: unassigned

---

## Context

> Spec Module 6. Implements the Rust language scanner with tree-sitter +
> heuristic fallback. Extracts `pub` items and `///` doc comments for the
> outline, and resolves `use crate::` and `mod` declarations via crate
> layout conventions.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py`
  implementing `RustScanner(LanguageScanner)`.
- `suffixes = frozenset({".rs"})`, `name = "rust"`.
- **Outline** (both modes):
  - Extract: `pub struct`, `pub enum`, `pub trait`, `pub fn`, `pub mod`,
    `impl` blocks (with associated methods).
  - Include `///` doc comment first line as description.
  - tree-sitter mode: use `tree_sitter_rust` grammar via `get_parser("rust")`.
  - Heuristic mode: line-anchored regex extraction.
- **Import extraction**:
  - `use crate::a::b;` and `use crate::a::{b, c};`
  - `mod foo;` declarations (external module declarations).
  - `use super::`, `use self::` (relative crate paths).
- **Reference resolution** (`build_reference_index` + `resolve_import`):
  - Crate layout conventions: `src/lib.rs`, `src/main.rs` as roots.
  - `mod foo;` → `foo.rs` or `foo/mod.rs`.
  - `use crate::a::b` → resolve `a/b.rs` or `a/b/mod.rs` relative to crate root.
- Register `RustScanner` in `languages/__init__.py`.
- Write unit tests for both modes.

**NOT in scope**: PHP plugin (TASK-2013), JS/TS plugin (TASK-2014).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py` | CREATE | `RustScanner` implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py` | MODIFY | Register RustScanner |
| `tests/knowledge/wiki/languages/test_rust_plugin.py` | CREATE | Unit tests |

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

- ~~`RustScanner`~~ — does not exist yet; this task creates it.
- ~~`tree_sitter_rust` anywhere in the repo~~ — only `tree_sitter_python`.
- ~~any Rust outline/import extraction in `repo_scan.py`~~ — `.rs` files get shallow pages only.

---

## Implementation Notes

### Outline Format

```
pub struct StructName: First line of /// doc
    pub field_name: Type
pub enum EnumName: First line of /// doc
pub trait TraitName: First line of /// doc
    fn method(&self, params) -> ReturnType: First line of /// doc
impl StructName:
    pub fn method(&self, params) -> ReturnType: First line of /// doc
pub fn function_name(params) -> ReturnType: First line of /// doc
pub mod module_name
```

### Rust Heuristic Patterns (line-anchored)

```python
RE_PUB_STRUCT = re.compile(r"^\s*pub(?:\(crate\))?\s+struct\s+(\w+)", re.MULTILINE)
RE_PUB_ENUM = re.compile(r"^\s*pub(?:\(crate\))?\s+enum\s+(\w+)", re.MULTILINE)
RE_PUB_TRAIT = re.compile(r"^\s*pub(?:\(crate\))?\s+trait\s+(\w+)", re.MULTILINE)
RE_PUB_FN = re.compile(r"^\s*pub(?:\(crate\))?\s+(?:async\s+)?fn\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*(\S+))?", re.MULTILINE)
RE_PUB_MOD = re.compile(r"^\s*pub(?:\(crate\))?\s+mod\s+(\w+)\s*;", re.MULTILINE)
RE_IMPL = re.compile(r"^\s*impl(?:<[^>]*>)?\s+(\w+)", re.MULTILINE)
RE_MOD_DECL = re.compile(r"^\s*(?:pub(?:\(crate\))?\s+)?mod\s+(\w+)\s*;", re.MULTILINE)
RE_USE_CRATE = re.compile(r"^\s*use\s+(crate|super|self)(::[\w:]+)(?:\s*\{([^}]+)\})?\s*;", re.MULTILINE)
RE_DOC_COMMENT = re.compile(r"^\s*///\s?(.*)", re.MULTILINE)
```

### Crate Layout Resolution

```python
def build_reference_index(self, rel_paths):
    file_set = set()
    crate_roots = {}  # directory → crate root file
    for rp in rel_paths:
        p = PurePosixPath(rp)
        if p.suffix == ".rs":
            file_set.add(rp)
            # Detect crate roots
            if p.name in ("lib.rs", "main.rs"):
                crate_roots[str(p.parent)] = rp
    return (file_set, crate_roots)

def resolve_import(self, spec, from_file, index):
    file_set, crate_roots = index
    from_dir = str(PurePosixPath(from_file).parent)
    if spec.startswith("mod:"):
        # mod foo; → look for foo.rs or foo/mod.rs relative to from_file dir
        mod_name = spec[4:]
        for candidate in [f"{from_dir}/{mod_name}.rs", f"{from_dir}/{mod_name}/mod.rs"]:
            if candidate in file_set:
                return candidate
    elif spec.startswith("crate::"):
        # use crate::a::b → resolve from crate root
        parts = spec[7:].split("::")
        crate_root_dir = self._find_crate_root(from_file, crate_roots)
        if crate_root_dir:
            path = "/".join(parts)
            for candidate in [f"{crate_root_dir}/{path}.rs", f"{crate_root_dir}/{path}/mod.rs"]:
                if candidate in file_set:
                    return candidate
    return None
```

### Key Constraints

- Heuristic regexes: line-anchored, bounded, no catastrophic backtrack.
- Handle `pub(crate)` visibility qualifier.
- POSIX rel-paths throughout.
- Parse failure → `LanguageOutline()` (empty), never raise.

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.languages.rust import RustScanner` works
- [ ] `scanner_for(".rs")` returns a `RustScanner` instance
- [ ] `RustScanner().mode` returns `"tree-sitter"` or `"heuristic"`
- [ ] `pub struct`, `pub enum`, `pub trait`, `pub fn` extracted with `///` docs
- [ ] `impl` blocks with their methods extracted
- [ ] `use crate::a::b` and `mod foo;` extracted as imports
- [ ] `mod foo;` resolves to `foo.rs` or `foo/mod.rs`
- [ ] `use crate::a::b` resolves via crate root (`src/lib.rs`)
- [ ] Both tree-sitter and heuristic modes produce valid outlines
- [ ] All tests pass: `pytest tests/knowledge/wiki/languages/test_rust_plugin.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py`

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_rust_plugin.py
SAMPLE_RUST = '''
/// A document parser.
pub struct Parser {
    pub name: String,
    buffer: Vec<u8>,
}

/// Parser implementation.
impl Parser {
    /// Create a new parser.
    pub fn new(name: &str) -> Self { ... }

    /// Parse the input.
    pub async fn parse(&self, input: &str) -> Result<Doc, Error> { ... }
}

pub enum Format {
    Json,
    Yaml,
}

/// Utility trait.
pub trait Serializable {
    /// Serialize to bytes.
    fn to_bytes(&self) -> Vec<u8>;
}

mod tests;
use crate::utils::helpers;
'''

def test_rust_outline_pub_items(force_heuristic):
    scanner = RustScanner()
    result = scanner.outline(SAMPLE_RUST, "src/parser.rs")
    names = " ".join(result.outline)
    assert "Parser" in names
    assert "Format" in names
    assert "Serializable" in names
    assert "new" in names
    assert "parse" in names

def test_rust_mod_resolution():
    scanner = RustScanner()
    rel_paths = ["src/lib.rs", "src/parser.rs", "src/utils/mod.rs", "src/utils/helpers.rs"]
    index = scanner.build_reference_index(rel_paths)
    assert scanner.resolve_import("mod:parser", "src/lib.rs", index) == "src/parser.rs"
    assert scanner.resolve_import("mod:utils", "src/lib.rs", index) == "src/utils/mod.rs"

def test_rust_use_crate_resolution():
    scanner = RustScanner()
    rel_paths = ["src/lib.rs", "src/utils/helpers.rs"]
    index = scanner.build_reference_index(rel_paths)
    assert scanner.resolve_import("crate::utils::helpers", "src/parser.rs", index) == "src/utils/helpers.rs"

def test_rust_doc_comments(force_heuristic):
    scanner = RustScanner()
    result = scanner.outline(SAMPLE_RUST, "src/parser.rs")
    assert any("document parser" in line.lower() for line in result.outline)
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
7. **Move this file** to `sdd/tasks/completed/TASK-2015-rust-scanner-plugin.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-31
**Notes**: Implemented `RustScanner`. Heuristic mode uses the exact regex
patterns from the Codebase Contract (`pub struct/enum/trait/fn`, `impl`,
`mod`/`pub mod`, `use crate|super|self::...`) plus a `///`-run finder for
doc-comment association (whitespace-only gap check, mirroring the PHP
plugin's approach). `impl` blocks render as `"impl Name:"` verbatim (no
doc suffix — matches the literal Outline Format example) with their
`pub fn` methods indented via the same brace-depth ownership heuristic
used by the PHP plugin. `mod foo;` imports as `"mod:{name}"` (prefix
needed so `resolve_import` can distinguish it from `crate::`/`super::`/
`self::` specifiers); group `use crate::a::{b, c};` expands to full
paths. `resolve_import` follows crate-layout conventions: `mod:` resolves
relative to the declaring file's own directory; `crate::` resolves via
the nearest ancestor directory holding a `lib.rs`/`main.rs` (returns
`None`, never raises, when no crate root is found); best-effort `super::`/
`self::` handling added beyond the given pseudocode (not required by the
task's own Acceptance Criteria/Test Specification, which only exercise
`mod:`/`crate::`, but matches the Scope bullet listing `super::`/`self::`
as extractable imports). A best-effort tree-sitter path is implemented
but untestable here (no grammar installed until TASK-2016's extra).
Registered as `"rust"` for `.rs`. 13/13 new tests pass (all against
literally the given `SAMPLE_RUST`/`test_rust_mod_resolution`/
`test_rust_use_crate_resolution` fixtures — no fixture inconsistency this
time, unlike TASK-2014); full `tests/knowledge/wiki/` suite (499 tests)
passes; `ruff check` clean.

**Deviations from spec**: Struct field listing (`    pub field_name:
Type`) and bare (non-`pub`) trait-interior method signatures shown in the
Outline Format example are not extracted — no regex for either is given
in the Codebase Contract, and the task's own Acceptance Criteria/Test
Specification don't require them (`test_rust_outline_pub_items` only
checks for `Parser`/`Format`/`Serializable`/`new`/`parse`, all satisfied
without field/trait-method extraction).
