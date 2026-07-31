---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Pluggable Language Scanners for `wikitoolkit build`

**Feature ID**: FEAT-394
**Date**: 2026-07-31
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 0.26.x
**Brainstorm**: `sdd/proposals/wikitoolkit-language-plugins.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit build` scans a repository into the LLM-wiki knowledge graph via
the deterministic scanner in `parrot/knowledge/wiki/repo_scan.py`. Every file
whose suffix is in `DEFAULT_SUFFIXES` gets a shallow `file:` page (content head
+ first-line summary), but only **Python/Cython** files get the deep treatment:
an API outline (classes/functions/docstrings via `ast`) and `references` edges
derived from imports — `_python_outline()`, `build_import_edges()`, and
`_module_index()` are hardwired to Python semantics.

Consequences: TypeScript, Rust, JS, Go, etc. appear in the graph with no
outline and no cross-file edges; **PHP and HTML are not scanned at all**
(absent from the suffix sets) despite a concrete user request to index a PHP
codebase; and adding a language means editing `repo_scan.py` internals — there
is no extension seam.

### Goals

- A **pluggable per-language scanner interface** (`LanguageScanner` ABC +
  suffix registry) in a new package `parrot/knowledge/wiki/languages/`.
- Python/Cython extraction becomes the first plugin — **byte-identical
  output**, existing tests pass unchanged.
- New deep extractors: **PHP**, **JS/TS** (one plugin for `.js/.jsx/.mjs/.ts/
  .tsx`), and **Rust** — each with an API outline and language-correct
  `references`-edge resolution.
- `.php` joins `CODE_SUFFIXES`; `.html`/`.htm` join `DOC_SUFFIXES` (shallow
  scan only).
- tree-sitter grammars are an **optional extra** (`ai-parrot[wiki-languages]`);
  every plugin has a stdlib-only deterministic heuristic fallback.
- `repo_scan.py` public API frozen: `scan_repository()`, `FileSlice`,
  `RepoScan`, `build_file_slice()`, `build_import_edges()` keep their
  signatures; `cli.py`, `ingest.py`, and the post-commit hook need no changes
  (the CLI gains only an additive `languages` stats block).
- The scanner stays deterministic and offline — no LLM, no embeddings, no
  network; parse failures degrade to the shallow page, never raise.

### Non-Goals (explicitly out of scope)

- tsconfig `paths` alias resolution in the JS/TS resolver (v1 resolves only
  relative specifiers) — resolved in brainstorm.
- A deep HTML plugin (outline/edges from `<script src>`/`<link href>`) —
  rejected in brainstorm; HTML is shallow-scan only.
- Third-party plugin discovery via entry points (the ABC is designed so this
  can be added later without interface changes) — rejected for v1 in
  brainstorm ("External plugin packages" option).
- A generic tree-sitter query engine (`.scm` files) — rejected in brainstorm
  (Option B): import resolution still needs per-language Python logic.
- Go/Java/Kotlin/C/C++ deep extractors (keep today's shallow scan).
- GraphIndex (`parrot/knowledge/graphindex/`) changes — its `CodeExtractor`
  is a separate subsystem and stays untouched.

---

## 2. Architectural Design

### Overview

A new package `parrot/knowledge/wiki/languages/` hosts one `LanguageScanner`
class per language, registered by file suffix. Each scanner implements three
hooks: (1) the suffixes it claims, (2) `outline(source, rel_path)` returning a
summary, rendered outline lines, and *raw* language-native import specifiers,
and (3) `build_reference_index(rel_paths)` + `resolve_import(spec, from_file,
index)` so `references`-edge resolution is per-language. A module-level
registry maps suffix → scanner; suffixes with no scanner keep today's shallow
path exactly.

`repo_scan.py` keeps its public API: `build_file_slice()` consults the
registry instead of the hardcoded `if suffix in {".py", ".pyi"}` branch, and
`build_import_edges()` groups scanned files by language, builds each
language's reference index **once** over the full repository file list, and
resolves each file's raw specifiers to target rel-paths (unresolvable
specifiers are dropped — no dangling edges).

tree-sitter is optional: a shared `treesitter.py` helper exposes a cached
`get_parser(language) -> Parser | None` that never raises. Each non-Python
plugin implements both a tree-sitter outline and a regex-heuristic fallback
and reports which mode is active. Python stays on stdlib `ast` (no tree-sitter
path at all). With `pip install ai-parrot[wiki-languages]` outlines come from
grammars; without it, heuristics are used silently. `wiki_stats.json` and
`wikitoolkit status` gain a `languages` block, e.g.
`{"php": "tree-sitter", "rust": "heuristic", "python": "ast"}`.

The incremental fast-path in `scan_repository()` (docs-only commits skip
repo-wide discovery) generalizes: full discovery runs when any changed file's
suffix belongs to a registered scanner, not just `.py/.pyi`.

### Component Diagram

```
wikitoolkit build / upsert (cli.py — unchanged call sites)
        │
        ▼
scan_repository()  ──────────────┐ (repo_scan.py — public API frozen)
        │                        │
        ▼                        ▼
build_file_slice()        build_import_edges()
        │                        │
        ▼                        ▼
languages.registry.scanner_for(suffix)
        │
        ├── python.py  (ast — moved, byte-identical)
        ├── php.py     ──┐
        ├── javascript.py├── treesitter.get_parser() ── tree-sitter | None
        └── rust.py    ──┘         │
                                   └── (None) → per-plugin regex heuristics
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/repo_scan.py` | modifies internals | `_python_outline`/`_module_index` move out; registry consulted in `build_file_slice()`/`build_import_edges()`; suffix sets extended |
| `parrot/knowledge/wiki/cli.py` | extends (additive) | `languages` block added to the `wiki_stats.json` report (`_write_reports`, cli.py:515-529) and `status` output |
| `parrot/knowledge/wiki/store.py` | uses | `WikiPageRecord`, `estimate_tokens` — unchanged |
| `parrot/knowledge/wiki/project.py` | uses | existing `include_suffixes`/`exclude_dirs` config covers opt-out; **no new config surface** |
| git post-commit hook | none | benefits automatically via `scan_repository(rel_paths=...)` |
| `packages/ai-parrot/pyproject.toml` | extends | new optional extra `wiki-languages` |

### Data Models

```python
# parrot/knowledge/wiki/languages/base.py
class LanguageOutline(BaseModel):
    """Result of deep-scanning one source file."""
    summary: str = ""
    outline: list[str] = Field(default_factory=list)   # rendered "## API outline" lines
    imports: list[str] = Field(default_factory=list)   # raw language-native specifiers

# repo_scan.FileSlice gains ONE optional field (additive, default None):
class FileSlice(BaseModel):
    rel_path: str
    record: WikiPageRecord
    imports: list[str] = Field(default_factory=list)
    language: Optional[str] = None    # NEW — scanner name ("python", "php", ...)
```

### New Public Interfaces

```python
# parrot/knowledge/wiki/languages/base.py
class LanguageScanner(ABC):
    """One language's deep extractor for the wiki repo scanner."""
    name: ClassVar[str]                      # "python", "php", "javascript", "rust"
    suffixes: ClassVar[frozenset[str]]       # e.g. frozenset({".php"})

    @abstractmethod
    def outline(self, source: str, rel_path: str) -> LanguageOutline: ...

    @abstractmethod
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...
        # Opaque per-language index over the FULL repo file list.

    @abstractmethod
    def resolve_import(
        self, spec: str, from_file: str, index: Any
    ) -> Optional[str]: ...
        # → target rel_path within the repo, or None (edge dropped).

    @property
    def mode(self) -> str: ...
        # "ast" | "tree-sitter" | "heuristic" — for the stats block.

def scanner_for(suffix: str) -> Optional[LanguageScanner]: ...
def all_scanners() -> dict[str, LanguageScanner]: ...      # name → scanner
def scanned_suffixes() -> frozenset[str]: ...              # union of all suffixes

# parrot/knowledge/wiki/languages/treesitter.py
def get_parser(language: str) -> Optional["tree_sitter.Parser"]: ...
    # Cached per process; returns None (never raises) when the optional
    # dependency or grammar is missing.
```

Per-language semantics (resolved in brainstorm):

| Language | Outline | Imports → `references` edges |
|---|---|---|
| Python | unchanged (`ast`) | unchanged — byte-identical |
| PHP | classes, interfaces, traits, enums, functions, methods + docblock first line | `use A\B\C;` (incl. group use), `require/include 'path'`; namespace→file via composer.json PSR-4 maps when present, else heuristic namespace-tail ↔ path matching; require paths resolved relative to the importing file |
| JS/TS | exported classes/functions/consts, interfaces, type aliases | `import … from`, `export … from`, `require()`; only **relative** specifiers, extension guessing (`.ts/.tsx/.js/.jsx/.mjs`, `/index.*`); bare package names ignored |
| Rust | `pub` structs/enums/traits/fns/mods, impl blocks, `///` doc first line | `use crate::a::b`, `mod foo;` via crate conventions (`src/lib.rs`, `src/main.rs`, `foo.rs` vs `foo/mod.rs`) |
| HTML | *not a plugin* — shallow: summary from `<title>` or first heading | none |

---

## 3. Module Breakdown

### Module 1: Plugin framework (`base.py` + `treesitter.py`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py`,
  `.../languages/treesitter.py`, `.../languages/__init__.py`
- **Responsibility**: `LanguageScanner` ABC, `LanguageOutline` model, suffix
  registry (`scanner_for`/`all_scanners`/`scanned_suffixes`), cached
  never-raising optional-grammar loader.
- **Depends on**: `parrot.knowledge.wiki.store` (nothing else).

### Module 2: Python plugin (move, no behavior change)
- **Path**: `.../languages/python.py`
- **Responsibility**: relocate `_python_outline()` and `_module_index()` logic
  behind the ABC; `mode == "ast"`. Output byte-identical to today.
- **Depends on**: Module 1.

### Module 3: `repo_scan.py` integration
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py`
- **Responsibility**: registry-driven `build_file_slice()` (drop the
  hardcoded `.py/.pyi` branch; set `FileSlice.language`); per-language
  grouping in `build_import_edges()`; generalized incremental fast-path in
  `scan_repository()`; add `.php` to `CODE_SUFFIXES`, `.html`/`.htm` to
  `DOC_SUFFIXES`; HTML `<title>`-aware summary helper. Public API frozen.
- **Depends on**: Modules 1-2.

### Module 4: PHP plugin
- **Path**: `.../languages/php.py`
- **Responsibility**: tree-sitter + heuristic outline; `use`/`require`
  extraction; PSR-4 (composer.json) + relative-path resolution.
- **Depends on**: Modules 1, 3.

### Module 5: JS/TS plugin
- **Path**: `.../languages/javascript.py`
- **Responsibility**: one scanner claiming `.js/.jsx/.mjs/.ts/.tsx`;
  exported-symbol outline; relative-specifier resolution with extension
  guessing.
- **Depends on**: Modules 1, 3.

### Module 6: Rust plugin
- **Path**: `.../languages/rust.py`
- **Responsibility**: `pub`-item outline; `use crate::`/`mod` resolution via
  crate layout conventions.
- **Depends on**: Modules 1, 3.

### Module 7: Stats surface, extra, and docs
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`,
  `packages/ai-parrot/pyproject.toml`, `documentation/parrot-wiki-cli.md`
- **Responsibility**: `languages` block in `wiki_stats.json` + `status`;
  `wiki-languages` optional extra; docs update; soften the "no external
  parsers" claim in the `repo_scan.py` module docstring to "no *required*
  external parsers".
- **Depends on**: Modules 1-6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_registry_maps_suffix_to_scanner` | 1 | `.php` → php scanner, `.ts` → javascript scanner, `.cfg` → None |
| `test_get_parser_missing_dep_returns_none` | 1 | grammar import failure → `None`, no raise, cached |
| `test_python_plugin_byte_identical` | 2 | plugin outline/imports equal legacy `_python_outline` output on fixture corpus |
| `test_php_outline_heuristic` / `_treesitter` | 4 | classes/traits/functions extracted in both modes |
| `test_php_psr4_resolution` | 4 | composer.json PSR-4 map resolves `use App\X\Y` to file |
| `test_php_require_relative` | 4 | `require __DIR__ . '/x.php'` / `include 'x.php'` resolves relative |
| `test_jsts_outline_exports` | 5 | exported classes/functions/interfaces/type aliases in both modes |
| `test_jsts_relative_resolution` | 5 | `./x` → `x.ts`/`x/index.ts`; bare `react` dropped |
| `test_rust_outline_pub_items` | 6 | pub structs/enums/traits/fns + `///` docs in both modes |
| `test_rust_mod_resolution` | 6 | `mod foo;` → `foo.rs` or `foo/mod.rs`; `use crate::a::b` via `src/lib.rs` |
| `test_parse_failure_degrades_shallow` | 3 | garbage source → shallow page, no exception |
| `test_html_shallow_title_summary` | 3 | `.html` page from `<title>`, no outline, no edges |
| `test_mixed_language_indexes_isolated` | 3 | a PHP `require` never resolves to a `.ts` file |
| `test_incremental_fastpath_generalized` | 3 | changed `.php` file triggers repo-wide discovery; docs-only set does not |
| `test_stats_languages_block` | 7 | `wiki_stats.json` carries per-language mode |

### Integration Tests

| Test | Description |
|---|---|
| `test_scan_repository_polyglot_fixture` | fixture repo with py+php+ts+rs+html: pages, outlines, and cross-file `references` edges per language |
| `test_existing_python_regression` | **entire existing `tests/knowledge/wiki/test_repo_scan.py` passes unchanged** |

### Test Data / Fixtures

```python
# tests/knowledge/wiki/languages/conftest.py
@pytest.fixture
def polyglot_repo(tmp_path):
    """Tiny repo: src/app.py, src/Service.php, composer.json,
    web/index.ts, web/util/index.ts, native/src/lib.rs,
    native/src/parser.rs, public/index.html."""
    ...

@pytest.fixture
def force_heuristic(monkeypatch):
    """monkeypatch languages.treesitter.get_parser to return None."""
    ...
```

Both modes are exercised in CI: dev dependencies include the
`wiki-languages` extra (tree-sitter path), and `force_heuristic` covers the
fallback path deterministically.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `pytest tests/knowledge/wiki/ -v` passes, **including the pre-existing
  `test_repo_scan.py` without any modification to that file** (Python
  byte-identical guarantee).
- [ ] A repository containing `.php` files scanned with `wikitoolkit build`
  produces `file:` pages with an API outline and `references` edges between
  PHP files (both with and without tree-sitter installed).
- [ ] Same for `.ts/.tsx/.js` and `.rs` fixtures.
- [ ] `.html` files produce shallow pages (summary + content head, no
  outline/edges).
- [ ] `scan_repository()`, `FileSlice` (modulo the additive optional
  `language` field), `RepoScan`, `build_file_slice()`, and
  `build_import_edges()` signatures are unchanged; `cli.py` call sites at
  the `scan_repository(...)` invocations require no edits.
- [ ] With tree-sitter absent, `wikitoolkit build` completes with heuristic
  outlines and no warnings-as-errors; nothing raises on any parse failure.
- [ ] `wiki_stats.json` and `wikitoolkit status` report the per-language mode
  block.
- [ ] `pip install ai-parrot[wiki-languages]` installs the grammar
  dependencies; core install gains zero new required dependencies.
- [ ] `documentation/parrot-wiki-cli.md` documents language support, the
  extra, and the fallback behavior; `repo_scan.py` docstring updated.
- [ ] `ruff check` and `mypy` clean on all new/modified files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Line numbers verified 2026-07-31 at dev commit `398dacc95`.

### Verified Imports

```python
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens
# verified: used by repo_scan.py (packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:32)
from parrot.knowledge.wiki.repo_scan import scan_repository
# verified: cli.py imports at lines 47-50
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py
CODE_SUFFIXES: frozenset[str]     # line 43 — includes .py .pyx .pxd .pyi .rs .go .java .kt .c .h .cpp .hpp .js .jsx .ts .tsx .mjs .sql .sh .bash — NO .php
DOC_SUFFIXES: frozenset[str]      # line 51 — {".md", ".rst", ".txt"} — NO .html/.htm
CONFIG_SUFFIXES: frozenset[str]   # line 54
DEFAULT_SUFFIXES: frozenset[str]  # line 58 — union of the three

class FileSlice(BaseModel):       # line 132
    rel_path: str
    record: WikiPageRecord
    imports: list[str]            # Python dotted modules today

class RepoScan(BaseModel):        # line 148
    root: Path
    files: list[FileSlice]
    dir_records: list[WikiPageRecord]
    dir_edges: list[tuple[str, str, str]]
    import_edges: list[tuple[str, str, str]]
    skipped: list[str]

def _category_for(rel_path: str) -> str: ...                       # line 415
def _python_outline(source) -> tuple[str, list[str], list[str]]: ...  # line 425 — moves to languages/python.py
def _markdown_summary(content: str) -> str: ...                    # line 469 — frontmatter-aware (PR #1081); HTML needs its own <title> helper, do NOT overload this
def build_file_slice(root, rel_path, body_max_chars=16_000, max_file_bytes=524_288) -> Optional[FileSlice]: ...  # line 517 — contains the hardcoded `if suffix in {".py", ".pyi"}` branch to replace
def _module_index(rel_paths) -> dict[str, str]: ...                # line 644 — moves to languages/python.py (src-layout stripping included)
def build_import_edges(files, index_paths=None) -> list[tuple[str, str, str]]: ...  # line 669
def scan_repository(root, suffixes=None, exclude_dirs=None, body_max_chars=..., max_file_bytes=..., use_git=True, rel_paths=None) -> RepoScan: ...  # line 711 — incremental fast-path checks `{".py", ".pyi"}`
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def estimate_tokens(text: str) -> int: ...   # line 153
class WikiPageRecord(BaseModel):             # line 205
    concept_id: str; node_id: Optional[str]; title: str; category: str
    summary: str; body: str; source_id: Optional[str]; token_count: int
    origin: str = "ingest"; asserted_by: Optional[str]
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
# scan_repository() call sites: line 678 (full build), line 871 (incremental upsert)
# _write_reports() writes wiki_stats.json: lines 515-529
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
include_suffixes: list[str]   # line 142 — per-repo suffix override exists
exclude_dirs: list[str]       # line 143
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py:202
# tree-sitter precedent (do NOT import from graphindex; pattern reference only):
@staticmethod
def _build_parser():
    from tree_sitter import Language, Parser
    import tree_sitter_python
    lang = Language(tree_sitter_python.language())
    return Parser(lang)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `languages.scanner_for()` | `build_file_slice()` | replaces suffix branch | repo_scan.py:517 |
| `LanguageScanner.build_reference_index/resolve_import` | `build_import_edges()` | per-language grouping | repo_scan.py:669 |
| `languages.scanned_suffixes()` | `scan_repository()` fast-path | membership check | repo_scan.py:711 |
| per-language `mode` | `_write_reports()` stats block | additive dict entry | cli.py:515-529 |
| `wiki-languages` extra | `[project.optional-dependencies]` | new group | packages/ai-parrot/pyproject.toml:128 |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/knowledge/wiki/languages/`~~ — package does not exist yet
  (verified 2026-07-31); every file in it is new.
- ~~`.php`, `.html`, `.htm` in any suffix set~~ — not scanned today.
- ~~`FileSlice.language`~~ — field does not exist yet.
- ~~a `wiki-languages` extra~~ — pyproject has `graphindex` (with
  `tree-sitter>=0.23`, `tree-sitter-languages>=1.10` at
  packages/ai-parrot/pyproject.toml:184-192) but NO wiki-languages group.
- ~~`tree_sitter_php` / `tree_sitter_rust` / `tree_sitter_typescript`
  imports anywhere in the repo~~ — only `tree_sitter_python` is used
  (graphindex/extractors/code.py:209).
- ~~any non-Python outline/import extraction in `repo_scan.py`~~ — Python
  `ast` only.
- ~~`wikitoolkit build --languages` CLI flag~~ — not planned; language
  reporting rides on stats output.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic models for structured data (`LanguageOutline`); Google-style
  docstrings + strict type hints everywhere.
- `logging.getLogger(__name__)` module loggers, as `repo_scan.py` does.
- The scanner is intentionally **synchronous** (pure CPU, called from the
  CLI and hook) — match `repo_scan.py`'s existing style; do not introduce
  async here.
- Registry population at import time in `languages/__init__.py` (explicit
  instantiation of the four scanners — no magic discovery).
- Outline rendering format must match today's Python outline style
  (`class X: doc` / four-space-indented `def y(args): doc`) so page bodies
  stay uniform across languages.

### Known Risks / Gotchas

- **Python byte-identical requirement**: keep the moved code verbatim
  (including the `rstrip(": ")` quirks); the regression suite is the gate.
- `_markdown_summary()` is now frontmatter-aware (PR #1081) — write a
  separate `<title>`-aware helper for HTML instead of extending it.
- `tree-sitter-languages` (already in the `graphindex` extra) is
  effectively unmaintained and incompatible with `tree-sitter>=0.23` on
  newer Pythons — do NOT reuse it for this feature; pick per the open
  question below and verify wheels for py3.10-3.12.
- Heuristic extractors must not catastrophically backtrack — keep regexes
  line-anchored and bounded (the hook runs on every commit).
- PHP heuristic must tolerate files that open with HTML before `<?php`.
- Windows paths: registry and resolvers operate on POSIX rel-paths
  (`PurePosixPath`) like the rest of `repo_scan.py`.
- Parse-failure policy is *degrade, never raise*: wrap each plugin call in
  `build_file_slice()` defensively.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `tree-sitter` | `>=0.23` | optional — accurate parsing (`wiki-languages` extra only) |
| grammar wheels (see §8 open question) | py3.10-3.12 wheels required | optional — PHP/TS/JS/Rust grammars (`wiki-languages` extra only) |

Core install: **zero** new required dependencies.

---

## 8. Open Questions

- [x] Where should plugins live / can they bring dependencies? — *Resolved in
  brainstorm*: In-tree registry + optional tree-sitter; plugins may declare an
  optional grammar and MUST degrade to stdlib heuristics when it is missing.
- [x] Language coverage for the first delivery? — *Resolved in brainstorm*:
  Framework + PHP + JS/TS + Rust deep extractors (Python stays on `ast`,
  moved unchanged).
- [x] How should HTML be handled? — *Resolved in brainstorm*: Shallow scan
  only — `.html`/`.htm` in default suffixes, `<title>`/first-heading summary,
  no outline, no edges, no plugin.
- [x] Plugin interface architecture? — *Resolved in brainstorm*:
  `LanguageScanner` ABC + suffix registry (Option A), with per-language
  `build_reference_index`/`resolve_import` for edge resolution.
- [x] tsconfig `paths` aliases in the JS/TS resolver? — *Resolved in
  brainstorm*: Out of scope for v1; only relative specifiers are resolved.
- [ ] Grammar packaging for the `wiki-languages` extra: one bundled wheel
  (`tree-sitter-language-pack`) vs individual grammar wheels
  (`tree-sitter-php`, `tree-sitter-typescript`, `tree-sitter-rust`,
  `tree-sitter-javascript`) following the graphindex `tree_sitter_python`
  precedent — decide at implementation time after verifying py3.10-3.12
  wheel availability. — *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: per-spec — one worktree
  (`.claude/worktrees/feat-394-wikitoolkit-language-plugins`, branched from
  `dev`), all tasks sequential.
- **Rationale**: Modules 4-6 (PHP/JS-TS/Rust plugins) are independent files
  and parallelizable in principle, but they share `base.py`, `treesitter.py`,
  the registry `__init__.py`, and the fixture conftest — coordination cost of
  parallel worktrees exceeds the benefit for plugins this small.
- **Cross-feature dependencies**: none — touches only
  `parrot/knowledge/wiki/` + pyproject extras; no in-flight spec conflicts
  known.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-31 | Jesus Lara (with Claude) | Initial draft from brainstorm |
