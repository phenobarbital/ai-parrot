# TASK-2260: PerlScanner — heuristic mode, imports & resolution

**Feature**: FEAT-432 — Wikitoolkit Perl Scanner
**Spec**: `sdd/specs/wikitoolkit-perl-scanner.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2259
**Assigned-to**: unassigned

---

## Context

This is the core implementation task. It creates `perl.py` with the
`PerlScanner` class implementing the `LanguageScanner` ABC. This task
covers the heuristic (regex) extraction mode, POD summary extraction,
import extraction, and reference resolution. The tree-sitter mode is
added in TASK-2261 on top of this foundation.

Implements spec Module 2 (heuristic path, imports, resolution).

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/languages/perl.py`
- Implement `PerlScanner(LanguageScanner)` with:
  - `name = "perl"`, `suffixes = frozenset({".pl", ".pm", ".t"})`
  - `outline()` — dual-mode dispatcher (tree-sitter path is a stub that
    falls through to heuristic until TASK-2261)
  - `_outline_heuristic()` — line-anchored regex extraction for:
    - `package Foo::Bar;` statements
    - `sub name { }` declarations (with params from signature or `my ($self, ...) = @_;`)
    - `has 'attr' => (...)` (Moose/Moo attributes)
    - `method name { }`, `class Name { }`, `role Name { }` (Corinna)
    - `field $x :param;` (Corinna)
  - POD summary extraction (`=head1 NAME` or first `=head1` paragraph)
  - Doc-comment association (POD `=head2` blocks near declarations)
  - `_extract_perl_imports()` — regex for `use Module::Name`,
    `require Module::Name`, `use parent/base 'Module::Name'`
  - `build_reference_index()` — build `(file_set, lib_dirs)` from repo paths
  - `resolve_import()` — `Module::Name` → `lib/Module/Name.pm`
  - `mode` property — returns `"heuristic"` (updated to check tree-sitter in TASK-2261)

**NOT in scope**: tree-sitter outline extraction (TASK-2261), tests (TASK-2262).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/perl.py` | CREATE | Full PerlScanner class |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner  # base.py:21,40
from parrot.knowledge.wiki.languages import treesitter  # treesitter.py (module)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py
class LanguageOutline(BaseModel):                  # line 21
    summary: str = ""                              # line 35
    outline: list[str] = Field(default_factory=list)   # line 36
    imports: list[str] = Field(default_factory=list)    # line 37

class LanguageScanner(ABC):                        # line 40
    name: ClassVar[str]                            # line 53
    suffixes: ClassVar[frozenset[str]]             # line 55
    def outline(self, source: str, rel_path: str) -> LanguageOutline: ...   # line 58
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...   # line 75
    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None: ...  # line 92
    @property
    def mode(self) -> str: ...                     # line 112

# packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py
def get_parser(language: str) -> Parser | None: ...  # line 62
```

### Reference Implementation

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py — follow this exactly
class RustScanner(LanguageScanner):     # line 127
    name: ClassVar[str] = "rust"        # line 130
    suffixes = frozenset({".rs"})       # line 131

    def outline(self, source, rel_path):     # line 135 — dual-mode pattern:
        try:
            imports = _extract_rust_imports(source)
            parser = treesitter.get_parser("rust")
            if parser is not None:
                summary, lines = self._outline_treesitter(parser, source)
            else:
                summary, lines = self._outline_heuristic(source)
        except Exception as exc:
            logger.debug("...", rel_path, exc)
            return LanguageOutline()
        return LanguageOutline(summary=summary, outline=lines, imports=imports)

    def _outline_heuristic(self, source):    # line 159
    def build_reference_index(self, rel_paths):  # line 325
    def resolve_import(self, spec, from_file, index):  # line 360
    @property
    def mode(self):                          # line 416
```

### Does NOT Exist

- ~~`LanguageOutline.functions`~~ — no such field; outlines are `list[str]`
- ~~`PerlScanner.parse()`~~ — the method is called `outline()`, not `parse()`
- ~~`LanguageScanner.extract_imports()`~~ — imports are returned inside `LanguageOutline.imports`
- ~~`treesitter.register_grammar()`~~ — no such function
- ~~`get_scan_root()`~~ returning a mandatory value — it returns `None` in tests

---

## Implementation Notes

### Pattern to Follow — Outline Rendering Style

Match the existing Python scanner style for outline lines:

```
package Foo::Bar
    sub new($class, %args): Constructor
    sub validate($self): Validate user data
    has name: Str
    has email: Str
    method coordinates(): Return x,y pair
    field $x
```

- Top-level `package` / `class` / `role` at column 0
- `sub` / `has` / `method` / `field` inside a package: 4-space indent
- Standalone `sub` (no enclosing package): column 0
- Doc from POD `=head2` or inline `#` comment on the preceding line
- Params from Perl signatures `sub foo($self, $x, $y)` or from the
  `my (...) = @_;` pattern on the first line of the sub body (heuristic only)

### Regex Safety Rules

ALL patterns MUST be:
- Line-anchored (`^` or `re.MULTILINE`)
- No nested quantifiers (`(a+)+` is forbidden)
- Bounded: no `.*` without line anchoring

The scanner runs on every git commit via post-commit hook — catastrophic
backtracking would freeze the hook.

### Import Specifier Format

```
use Foo::Bar;           → "Foo::Bar"
use Foo::Bar qw(baz);   → "Foo::Bar"
require Foo::Bar;       → "Foo::Bar"
use parent 'Foo::Bar';  → "Foo::Bar"
use base qw(Foo::Bar);  → "Foo::Bar"
require "./lib.pl";     → "require:./lib.pl"
```

### Reference Resolution Strategy

`build_reference_index(rel_paths)` returns `(file_set, lib_dirs)`:
- `file_set`: `frozenset` of all `.pm`/`.pl`/`.t` paths for O(1) lookup
- `lib_dirs`: `list[str]` of directories named `lib` containing `.pm` files

`resolve_import(spec, from_file, index)`:
1. If `spec` starts with `require:` — resolve relative to `from_file`'s dir
2. Otherwise convert `Module::Name` → `Module/Name.pm`
3. Try `{lib_dir}/Module/Name.pm` for each `lib_dir`
4. Try `Module/Name.pm` directly in `file_set`
5. Return `None` if not found (CPAN-only module)

### Key Constraints

- Synchronous only — no async
- Must never raise from `outline()` — outer `except Exception` is mandatory
- Use `PurePosixPath`, never `os.path`
- Google-style docstrings + strict type hints
- `logging.getLogger(__name__)` for module logger
- `_SUMMARY_MAX_CHARS = 240` (same as rust.py)

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py` — primary reference
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/php.py` — PSR-4 resolution pattern
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py` — ABC

---

## Acceptance Criteria

- [ ] `perl.py` created with `PerlScanner` implementing all 4 abstract members
- [ ] Heuristic mode extracts `sub`, `package`, `use`/`require`, `has`, `class`/`role`/`method`/`field`
- [ ] POD summary extraction works (`=head1 NAME` paragraph)
- [ ] `_extract_perl_imports()` captures `use`, `require`, `use parent/base`
- [ ] `build_reference_index()` identifies `lib/` directories
- [ ] `resolve_import()` resolves `Foo::Bar` → `lib/Foo/Bar.pm`
- [ ] `outline()` never raises — garbage input returns empty `LanguageOutline`
- [ ] All regex patterns are line-anchored with no nested quantifiers
- [ ] `mode` property returns `"heuristic"` (tree-sitter check added in TASK-2261)

---

## Test Specification

```python
# Basic smoke test — full suite in TASK-2262
from parrot.knowledge.wiki.languages.perl import PerlScanner
from parrot.knowledge.wiki.languages.base import LanguageOutline

scanner = PerlScanner()

def test_never_raises():
    result = scanner.outline("{{{{garbage not perl at all", "test.pl")
    assert isinstance(result, LanguageOutline)
    # No exception raised

def test_basic_sub():
    source = 'package Foo;\nsub bar { }\n1;\n'
    result = scanner.outline(source, "lib/Foo.pm")
    assert any("sub bar" in line for line in result.outline)

def test_basic_import():
    source = 'use Foo::Bar;\nrequire Baz::Qux;\n'
    result = scanner.outline(source, "lib/App.pm")
    assert "Foo::Bar" in result.imports
    assert "Baz::Qux" in result.imports
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context, especially §7 Implementation Notes
2. **Read `rust.py` in full** — it is the reference implementation; follow
   its structure exactly for the dual-mode `outline()` dispatcher, the
   `_outline_heuristic()` method, and the reference resolution pair
3. **Verify the Codebase Contract** — confirm signatures in `base.py`
4. **Implement** — start with `_extract_perl_imports()` and `_outline_heuristic()`,
   then `build_reference_index()` / `resolve_import()`, then the `outline()`
   dispatcher
5. **Stub the tree-sitter path**: `_outline_treesitter()` should exist as a
   method but is implemented in TASK-2261. For now it can just call
   `_outline_heuristic()` or raise `NotImplementedError` (the `outline()`
   dispatcher's `except Exception` will catch it)

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
