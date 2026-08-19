---
type: feature
base_branch: dev
---

# Feature Specification: Wikitoolkit Perl Scanner

**Feature ID**: FEAT-432
**Date**: 2026-08-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit build` produces accurate tree-sitter–based outlines for PHP,
JavaScript/TypeScript, and Rust files when the `ai-parrot[wiki-languages]`
extra is installed, and falls back to regex heuristics when it is not.
Perl (`.pl`/`.pm`) files currently receive no deep extraction at all — they
land as shallow `file:` pages with content-head only, meaning no API
outline, no import-based `references` edges, and no cross-file navigation
for Perl codebases.

Perl is actively used in several repositories indexed by wikitoolkit
(infrastructure tooling, legacy services, Catalyst/Mojolicious apps).
Without a scanner, Perl code is invisible to agents querying the wiki
for "where does this Perl module live?" or "what functions does this
`.pm` export?".

### Goals

- Deep extraction of Perl code outlines: `sub`, `package`, `use`/`require`,
  Corinna `class`/`role`/`method`/`field`, and Moose/Moo `has` attributes.
- Cross-file `references` edges via import resolution
  (`Module::Name` → `Module/Name.pm`).
- Dual-mode: tree-sitter when `tree-sitter-perl` is installed, regex
  heuristic fallback when it is not.
- Zero impact on existing scanners — additive-only change.

### Non-Goals (explicitly out of scope)

- Parsing XS/Inline::C code embedded in Perl files.
- Deep analysis of Moose type constraints, method modifiers
  (`before`/`after`/`around`) beyond listing them as outline entries.
- Supporting Perl 6/Raku (`.raku`/`.rakumod`) — that is a different
  language with a different grammar.
- POD-to-markdown rendering — POD is extracted for summary only (first
  `=head1 NAME` or `=head1 DESCRIPTION` paragraph).

---

## 2. Architectural Design

### Overview

Add a `PerlScanner` class to the pluggable wiki language system following
the exact dual-mode architecture established by `RustScanner`, `PhpScanner`,
and `JavaScriptScanner`:

1. **tree-sitter mode** — uses `tree-sitter-perl` (PyPI wheel `>=1.2.1`,
   compatible with `tree-sitter>=0.23`) for accurate AST-based outline
   extraction. The grammar has 144 node types, 283/283 tests passing,
   and covers `sub`, `package`, Corinna OO (`class`/`role`/`method`/`field`),
   heredocs, regex, and modern Perl constructs.

2. **heuristic mode** — bounded, line-anchored regexes with no nested
   quantifiers. Extracts `sub`, `package`, `use`/`require`, `has`
   (Moose/Moo), `method`/`class`/`role` (Corinna). This is the fallback
   when the `wiki-languages` extra is not installed.

Import extraction is regex-based in both modes (same as all existing
scanners). Resolution follows Perl's standard convention:
`Module::Name` → `lib/Module/Name.pm` (scanning for `lib/` directories
in the repo tree).

### Component Diagram

```
pyproject.toml  ──→  wiki-languages extra (adds tree-sitter-perl)
                          │
treesitter.py   ──→  _GRAMMAR_MODULES["perl"] = "tree_sitter_perl"
                     _GRAMMAR_CALLABLES["perl"] = ("language",)
                          │
perl.py         ──→  PerlScanner(LanguageScanner)
  │                    ├── outline()
  │                    │     ├── _outline_treesitter()   [tree-sitter mode]
  │                    │     └── _outline_heuristic()    [regex fallback]
  │                    ├── build_reference_index()
  │                    ├── resolve_import()
  │                    └── mode property
  │
__init__.py     ──→  _SCANNERS["perl"] = PerlScanner()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LanguageScanner` (ABC) | subclass | `PerlScanner` implements all 4 abstract members |
| `treesitter.get_parser()` | consumer | Loads `tree_sitter_perl` grammar via cached loader |
| `__init__._SCANNERS` | registration | One new entry: `"perl": PerlScanner()` |
| `treesitter._GRAMMAR_MODULES` | registration | One new entry: `"perl": "tree_sitter_perl"` |
| `treesitter._GRAMMAR_CALLABLES` | registration | One new entry: `"perl": ("language",)` |
| `pyproject.toml` wiki-languages extra | dependency | Add `tree-sitter-perl>=0.23` |
| `repo_scan.CODE_SUFFIXES` | registration | Add `".pl"`, `".pm"`, `".t"` — **mandatory**: `discover_repo_files()`/`is_wiki_relevant()` filter files against this set *before* the scanner registry is ever consulted, so a scanner registered in `_SCANNERS` without a matching `CODE_SUFFIXES` entry is silently never reached by `wikitoolkit build`. Every prior deep-scan language (`.php`, `.rs`, `.js`/`.ts`, `.svelte`) added its suffixes here; this table omitted it in v0.1 of this spec and the gap shipped undetected until code review caught it empirically (§9 Revision History). |

### Data Models

No new data models. `PerlScanner` produces `LanguageOutline` instances
(the shared data model from `base.py`).

### New Public Interfaces

```python
# parrot/knowledge/wiki/languages/perl.py
class PerlScanner(LanguageScanner):
    name: ClassVar[str] = "perl"
    suffixes: ClassVar[frozenset[str]] = frozenset({".pl", ".pm", ".t"})

    def outline(self, source: str, rel_path: str) -> LanguageOutline: ...
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...
    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None: ...
    @property
    def mode(self) -> str: ...
```

---

## 3. Module Breakdown

### Module 1: tree-sitter-perl registration

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py`
- **Responsibility**: Register the `tree_sitter_perl` grammar module and callable
  so `get_parser("perl")` returns a configured `Parser` when the wheel is
  installed.
- **Depends on**: nothing (additive dict entries)
- **Changes**: Add `"perl": "tree_sitter_perl"` to `_GRAMMAR_MODULES` and
  `"perl": ("language",)` to `_GRAMMAR_CALLABLES`.

### Module 2: PerlScanner implementation

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/languages/perl.py` (new file)
- **Responsibility**: Full `LanguageScanner` subclass with dual-mode outline
  extraction, import extraction, and reference resolution.
- **Depends on**: Module 1 (tree-sitter registration)
- **Key sections**:
  - Heuristic regex patterns (line-anchored, bounded)
  - POD summary extraction
  - `_outline_treesitter()` using node types: `subroutine_declaration_statement`,
    `package_statement`, `use_statement`, `class_statement`, `method_statement`,
    `field_statement`, `role_statement`, `function_call_expression` (for `has`)
  - `_outline_heuristic()` using line-anchored regexes
  - `_extract_perl_imports()` for `use Module::Name`, `require Module::Name`
  - `build_reference_index()` — builds `(file_set, lib_dirs)` pair
  - `resolve_import()` — `Module::Name` → `lib/Module/Name.pm`

### Module 3: Scanner registration

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py`
- **Responsibility**: Import `PerlScanner` and add to `_SCANNERS` dict.
- **Depends on**: Module 2

### Module 4: Dependency declaration

- **Path**: `packages/ai-parrot/pyproject.toml`
- **Responsibility**: Add `tree-sitter-perl>=0.23` to the `wiki-languages` extra.
- **Depends on**: nothing (additive)

### Module 5: Test suite

- **Path**: `tests/knowledge/wiki/languages/test_perl.py` (new file)
- **Responsibility**: Unit tests for `PerlScanner` covering both modes, edge
  cases, import resolution, and the never-raise contract.
- **Depends on**: Module 2

### Module 6: Repo-scan discovery registration

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py`
- **Responsibility**: Add `".pl"`, `".pm"`, `".t"` to `CODE_SUFFIXES` so
  `wikitoolkit build`'s default file discovery (`discover_repo_files()` →
  `is_wiki_relevant()`) actually surfaces Perl files to the scanner
  registry. Without this, `PerlScanner` being registered in `_SCANNERS`
  has no effect — files are filtered out one layer earlier and the
  registered scanner is never reached.
- **Depends on**: nothing (additive; independent of Modules 1-5)
- **Note**: added in v0.2 of this spec. v0.1 omitted this module
  entirely — a real gap, not a documentation-only oversight — caught by
  code review (`code-reviewer` agent) reproducing `wikitoolkit build`
  producing 0 Perl pages on a synthetic fixture, then verifying 5 pages +
  a correct `references` edge after this one-line fix. Also added the
  precedent-mirroring `test_pl_pm_t_are_code_suffixes` regression test
  and extended the shared `polyglot_repo` integration fixture with real
  Perl coverage (the previous 37 Perl-specific unit tests all called
  `PerlScanner` methods directly, bypassing discovery entirely — the
  integration-test gap that let Module 6's omission ship undetected).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_perl_scanner_basics` | M2 | Name, suffixes, mode property |
| `test_outline_sub_declarations` | M2 | Extracts `sub name { }` with params/doc |
| `test_outline_package_statements` | M2 | Extracts `package Foo::Bar;` |
| `test_outline_use_require` | M2 | Extracts `use Module::Name` and `require Module::Name` |
| `test_outline_moose_has` | M2 | Extracts `has 'attr' => (...)` attributes |
| `test_outline_corinna_class` | M2 | Extracts `class Foo { method bar { } }` |
| `test_outline_corinna_role` | M2 | Extracts `role Foo { }` |
| `test_outline_corinna_field` | M2 | Extracts `field $x :param;` |
| `test_outline_pod_summary` | M2 | Extracts summary from `=head1 NAME` |
| `test_outline_never_raises` | M2 | Garbage input → empty `LanguageOutline`, no exception |
| `test_outline_heuristic_fallback` | M2 | When tree-sitter unavailable, heuristic runs |
| `test_outline_treesitter_mode` | M2 | When tree-sitter available, tree-sitter runs |
| `test_build_reference_index` | M2 | Builds `file_set` and `lib_dirs` correctly |
| `test_resolve_module_name` | M2 | `Foo::Bar` → `lib/Foo/Bar.pm` |
| `test_resolve_relative_require` | M2 | `require "./lib.pl"` → relative path |
| `test_resolve_unresolvable` | M2 | CPAN module → `None` |
| `test_nested_sub_indentation` | M2 | Methods inside packages get 4-space indent |
| `test_scanner_registration` | M3 | `scanner_for(".pm")` returns `PerlScanner` |
| `test_treesitter_grammar_loads` | M1 | `get_parser("perl")` returns `Parser` (when installed) |

### Test Data / Fixtures

```python
@pytest.fixture
def perl_module_source():
    return textwrap.dedent("""\
        package MyApp::Model::User;
        use Moose;
        use MyApp::Schema;

        has 'name' => (is => 'ro', isa => 'Str');
        has 'email' => (is => 'rw', isa => 'Str');

        sub validate {
            my ($self) = @_;
            # Validate user data
            return 1;
        }

        sub to_hashref {
            my ($self) = @_;
            return { name => $self->name, email => $self->email };
        }

        __PACKAGE__->meta->make_immutable;
        1;
    """)

@pytest.fixture
def perl_corinna_source():
    return textwrap.dedent("""\
        use v5.38;
        class Point {
            field $x :param;
            field $y :param;

            method coordinates () {
                return ($x, $y);
            }
        }
    """)

@pytest.fixture
def repo_paths():
    return [
        "lib/MyApp/Model/User.pm",
        "lib/MyApp/Schema.pm",
        "lib/MyApp/Controller/Auth.pm",
        "bin/app.pl",
        "t/model_user.t",
    ]
```

---

## 5. Acceptance Criteria

- [ ] `wikitoolkit build` on a repo with `.pl`/`.pm` files produces deep
      outline pages with API outlines (not just content-head).
- [ ] `wikitoolkit status` shows `'perl': 'tree-sitter'` in Languages when
      `ai-parrot[wiki-languages]` is installed.
- [ ] `wikitoolkit status` shows `'perl': 'heuristic'` when tree-sitter-perl
      is NOT installed.
- [ ] Import resolution produces `references` edges between Perl files
      (e.g. `use MyApp::Schema` in `Model/User.pm` links to
      `lib/MyApp/Schema.pm`).
- [ ] `PerlScanner.outline()` never raises — any parse failure returns an
      empty `LanguageOutline`.
- [ ] Heuristic fallback extracts `sub`, `package`, `use`/`require`, `has`
      (Moose/Moo).
- [ ] tree-sitter mode additionally extracts Corinna `class`/`role`/`method`/`field`.
- [ ] All regex patterns are line-anchored with no nested quantifiers
      (no catastrophic backtracking risk).
- [ ] All unit tests pass: `pytest tests/knowledge/wiki/languages/test_perl.py -v`
- [ ] No changes to existing scanner files beyond registration in
      `__init__.py` and `treesitter.py`.
- [ ] `tree-sitter-perl>=0.23` added to the `wiki-languages` extra in
      `pyproject.toml`.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner  # verified: languages/base.py:21,40
from parrot.knowledge.wiki.languages import treesitter  # verified: languages/treesitter.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py

class LanguageOutline(BaseModel):                  # line 21
    summary: str = ""                              # line 35
    outline: list[str] = Field(default_factory=list)   # line 36
    imports: list[str] = Field(default_factory=list)    # line 37

class LanguageScanner(ABC):                        # line 40
    name: ClassVar[str]                            # line 53
    suffixes: ClassVar[frozenset[str]]             # line 55

    @abstractmethod
    def outline(self, source: str, rel_path: str) -> LanguageOutline: ...   # line 58
    @abstractmethod
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...   # line 75
    @abstractmethod
    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None: ...  # line 92
    @property
    @abstractmethod
    def mode(self) -> str: ...                     # line 112
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py

_GRAMMAR_MODULES: dict[str, str]        # line 30 — register "perl" here
_GRAMMAR_CALLABLES: dict[str, tuple[str, ...]]  # line 51 — register "perl" here
def get_parser(language: str) -> Parser | None: ...  # line 62
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py

_SCANNERS: dict[str, LanguageScanner]   # line 31 — register PerlScanner() here
_SUFFIX_INDEX: dict[str, str]           # line 39 — auto-derived, no manual edit
```

### Reference Implementation

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/rust.py

class RustScanner(LanguageScanner):     # line 127
    name: ClassVar[str] = "rust"        # line 130
    suffixes = frozenset({".rs"})       # line 131
    def outline(...):                   # line 135 — dual-mode pattern
    def _outline_heuristic(...):        # line 159
    def _outline_treesitter(...):       # line 236
    def build_reference_index(...):     # line 325
    def resolve_import(...):            # line 360
    @property def mode(...):            # line 416
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PerlScanner` | `LanguageScanner` | subclass | `base.py:40` |
| `PerlScanner.outline()` | `treesitter.get_parser("perl")` | function call | `treesitter.py:62` |
| `__init__._SCANNERS` | `PerlScanner()` | dict entry | `__init__.py:31` |
| `treesitter._GRAMMAR_MODULES` | `"tree_sitter_perl"` | dict entry | `treesitter.py:30` |
| `treesitter._GRAMMAR_CALLABLES` | `("language",)` | dict entry | `treesitter.py:51` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.wiki.languages.perl`~~ — does not exist yet (this spec creates it)
- ~~`tree_sitter_perl.language_perl()`~~ — the wheel uses `language()`, not `language_perl()`
- ~~`LanguageScanner.register()`~~ — no auto-registration; scanners are registered manually in `__init__.py`
- ~~`treesitter.register_grammar()`~~ — no such function; edit the module-level dicts directly
- ~~`LanguageOutline.functions`~~ — no such field; outlines are plain string lists
- ~~`PerlScanner.parse()`~~ — the method is called `outline()`, not `parse()`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Dual-mode template**: Follow `rust.py` exactly:
  `outline()` → `_extract_perl_imports()` (always regex) → check
  `treesitter.get_parser("perl")` → dispatch to `_outline_treesitter()`
  or `_outline_heuristic()` → wrap in `except Exception` → return
  `LanguageOutline()` on failure.
- **Doc-comment extraction**: For heuristic mode, extract POD blocks
  (`=head1`...`=cut`) for summary. For tree-sitter mode, use
  `pod_statement` node type.
- **Outline rendering**: Match existing style — `package Foo::Bar`,
  four-space-indented `sub name(params): doc` for subs inside a package,
  top-level `sub name(params): doc` for standalone subs.
- **Import specifier format**: Use raw `Module::Name` for `use`/`require`;
  for relative requires use `require:./path.pl`.
- **Never raise from `outline()`**: The outer `except Exception` guard
  is mandatory.
- **Regex safety**: All heuristic patterns MUST be line-anchored (`^`)
  with no nested quantifiers. The scanner runs on every git commit via
  a post-commit hook.
- **Synchronous only**: No async (matches `repo_scan.py` style).
- **POSIX paths**: Use `PurePosixPath`, never `os.path`.
- **Google-style docstrings** + strict type hints.
- **`logging.getLogger(__name__)`** for the module logger.

### tree-sitter-perl Node Types (key ones for outline)

From the grammar's 144 node types, the relevant ones for outline
extraction:

| Node Type | Perl Construct | Outline Entry |
|---|---|---|
| `subroutine_declaration_statement` | `sub foo { }` | `sub foo(params): doc` |
| `package_statement` | `package Foo::Bar;` | `package Foo::Bar` |
| `use_statement` | `use Module::Name;` | (import, not outline) |
| `require_statement` | `require Module::Name;` | (import, not outline) |
| `class_statement` | `class Foo { }` | `class Foo: doc` |
| `role_statement` | `role Foo { }` | `role Foo: doc` |
| `method_statement` | `method bar { }` | `    method bar(params): doc` |
| `field_statement` | `field $x :param;` | `    field $x` |
| `function_call_expression` | `has 'attr' => (...)` | `    has attr: type` (Moose) |

Note: node type names must be verified against the actual grammar at
implementation time — the grammar is tagged "unstable" tier by
nvim-treesitter, meaning node types may change between minor releases.
Pin `tree-sitter-perl>=0.23` (not an exact pin) to allow patches but
check node types.

### Perl Import Resolution Strategy

```
use MyApp::Schema;      →  spec = "MyApp::Schema"
                        →  try: lib/MyApp/Schema.pm
                        →  try: MyApp/Schema.pm
                        →  None (CPAN module, not in repo)

require "./lib.pl";     →  spec = "require:./lib.pl"
                        →  resolve relative to importing file

use parent 'Foo::Bar';  →  spec = "Foo::Bar"
                        →  same resolution as `use`
```

`build_reference_index()` should:
1. Collect all `.pm`/`.pl` paths into a `frozenset` for O(1) lookup.
2. Identify `lib/` directories in the repo tree (directories named `lib`
   that contain `.pm` files) as resolution roots.

### Known Risks / Gotchas

- **tree-sitter-perl node type instability**: The grammar is in "unstable"
  tier — node types may change between releases. Mitigated by: (a) the
  outer `except Exception` guard in `outline()` degrades gracefully,
  (b) heuristic fallback always works, (c) pin `>=0.23` not exact.
- **No `tags.scm` in tree-sitter-perl**: Cannot use `tree-sitter tags`
  CLI. Not an issue — we write our own node-walking code, same as all
  existing plugins.
- **Moose `has` is a function call, not syntax**: In tree-sitter mode,
  `has` appears as a `function_call_expression`, not a dedicated node
  type. The tree-sitter extractor needs a special case to recognise
  `has('attr_name', ...)` calls.
- **Multiple packages per file**: Perl allows multiple `package` blocks
  in one `.pm`. The outline should render all of them with their subs
  nested under the correct package.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `tree-sitter-perl` | `>=0.23` | Compiled Perl grammar for tree-sitter (PyPI abi3 wheel) |

Already in existing extras (no new additions beyond the above):
- `tree-sitter>=0.23` (in `wiki-languages` extra)

---

## 8. Open Questions

- [x] Should `.t` (Perl test) files be included in `suffixes`? They are
      valid Perl but mostly test code. Including them means more outline
      coverage but also more noise. — *Owner: Jesus*
      **Decided: yes.** TASK-2260 resolved this in its Scope (`suffixes =
      frozenset({".pl", ".pm", ".t"})`) rather than leaving it open;
      shipped as specified, covered by `TestRegistration.test_scanner_for_t`.
- [x] Should `has` (Moose/Moo) extraction in tree-sitter mode walk into
      `function_call_expression` nodes, or should it remain regex-only
      (like import extraction)? Regex is simpler and more robust against
      node-type changes. — *Owner: implementer*
      **Decided: AST-based, not regex-only.** TASK-2261 resolved this in
      its Scope (walk `function_call_expression`/`ambiguous_function_call_expression`
      nodes where the callee is `has`) rather than leaving it open. In
      practice the real `tree-sitter-perl` grammar splits `has(...)` (explicit
      parens) as `function_call_expression` and `has 'x' => (...)` (bareword
      form) as `ambiguous_function_call_expression` — both are handled.

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Reason**: 5 modules, all tightly coupled (Module 2 is the bulk;
  Modules 1/3/4 are one-line registration changes). No parallelism benefit.
- **Cross-feature dependencies**: None. This is an additive-only change with
  no interface modifications to existing code.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-19 | Jesus Lara | Initial draft from spike research |
| 0.2 | 2026-08-19 | sdd-worker (code review follow-up) | Added Module 6 (`repo_scan.CODE_SUFFIXES` registration) and its Integration Points row — a real gap in v0.1 that made `wikitoolkit build` discover zero `.pl`/`.pm`/`.t` files despite `PerlScanner` being correctly registered; caught by adversarial code review, fixed, and regression-tested. Resolved both §8 Open Questions per the decisions already made in TASK-2260/2261's Scope. |
