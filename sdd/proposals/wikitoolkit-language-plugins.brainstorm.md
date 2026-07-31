---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Pluggable Language Scanners for `wikitoolkit build`

**Date**: 2026-07-31
**Author**: Jesus Lara (with Claude)
**Status**: accepted
**Recommended Option**: A

---

## Problem Statement

`wikitoolkit build` scans a repository into the LLM-wiki knowledge graph via
the deterministic scanner in `parrot/knowledge/wiki/repo_scan.py`. Today every
file whose suffix is in `DEFAULT_SUFFIXES` gets a shallow `file:` page (content
head + first-line summary), but only **Python/Cython** files get the deep
treatment: an API outline (classes/functions/docstrings via `ast`) and
`references` edges derived from imports (`_python_outline()`,
`build_import_edges()`, `_module_index()` are hardwired to Python semantics).

Consequences:

- TypeScript, Rust, JS, Go, etc. appear in the graph but with no API outline
  and no cross-file edges — the graph is structurally blind to them.
- **PHP and HTML are not scanned at all** — `.php`/`.html` are absent from
  `CODE_SUFFIXES`/`DOC_SUFFIXES`. There is a concrete user request to index a
  PHP codebase with `wikitoolkit build`.
- Adding a language today means editing `repo_scan.py` internals; there is no
  extension seam.

We want a **pluggable per-language scanner interface** so new languages (PHP
first, then others) can be added as self-contained plugins, with Python
becoming the first plugin (behavior-identical).

## Constraints & Requirements

- The scanner must stay **deterministic and offline** — no LLM, no embeddings,
  no network. It runs in the git post-commit hook; parse failures must degrade
  to the shallow page, never raise, never block a commit.
- **Zero required new dependencies**: tree-sitter grammars are an *optional*
  extra; every plugin must have a stdlib-only heuristic fallback that produces
  useful (if coarser) outlines.
- `repo_scan.py`'s public API (`scan_repository()`, `FileSlice`, `RepoScan`,
  `build_file_slice()`, `build_import_edges()`) must not change signature —
  `cli.py`, `ingest.py`, and the post-commit hook must need no changes.
- Python output must remain **byte-identical**: the existing
  `tests/knowledge/wiki/test_repo_scan.py` suite passes unchanged.
- The incremental fast-path in `scan_repository()` (docs-only commits skip
  repo-wide discovery) must generalize to all languages that produce
  reference edges, not just `.py/.pyi`.

---

## Options Explored

### Option A: `LanguageScanner` ABC + suffix registry (in-tree)

New package `parrot/knowledge/wiki/languages/`. Each language is one class
implementing three hooks: (1) suffixes it claims, (2)
`outline(source, rel_path)` → summary + outline lines + raw import specifiers,
(3) `build_reference_index(rel_paths)` + `resolve_import(spec, from_file,
index)` so `references`-edge resolution is per-language. A module-level
registry maps suffix → scanner; unknown suffixes keep today's shallow path
exactly. A shared `treesitter.py` helper loads optional grammars (cached,
never raises); each plugin implements a tree-sitter outline and a
regex-heuristic fallback.

✅ **Pros:**
- Reference resolution (the genuinely per-language part) has a first-class
  home; Python's dotted-module logic moves in without behavior change.
- Fallback state (tree-sitter vs heuristic) lives naturally on the class.
- Third-party pluggability later (entry points) without changing the
  interface.

❌ **Cons:**
- More ceremony than function hooks (an ABC, a registry, one module per
  language).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tree-sitter>=0.23` | optional accurate parsing | already used by GraphIndex (`graphindex` extra) |
| `tree-sitter-language-pack` | PHP/TS/Rust grammars in one wheel | optional extra; alternative: individual grammar wheels per graphindex precedent |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/repo_scan.py` — `_python_outline()`, `_module_index()`, `build_import_edges()` move into `languages/python.py`.
- `parrot/knowledge/graphindex/extractors/code.py` — tree-sitter parser construction precedent (`_build_parser()`).

### Option B: Generic tree-sitter engine + per-language `.scm` queries

One extractor driven by declarative tree-sitter queries (a `queries/<lang>.scm`
per language); a single generic regex fallback.

✅ **Pros:**
- Less Python code per language for the *outline* half.

❌ **Cons:**
- Import **resolution** still needs per-language Python logic (PSR-4, relative
  specifiers, crate paths) — you end up writing the ABC anyway, plus a query
  DSL on top.
- Makes tree-sitter effectively load-bearing; the "generic fallback" produces
  much worse outlines than per-language heuristics.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tree-sitter` + grammars | required in practice | conflicts with the optional-dependency constraint |

🔗 **Existing Code to Reuse:**
- Same as Option A.

### Option C: Minimal function hooks

A dict `suffix -> (outline_fn, imports_fn)` inside `repo_scan.py` itself; no
classes, no new package.

✅ **Pros:**
- Least ceremony; smallest diff.

❌ **Cons:**
- Reference-edge resolution and tree-sitter fallback state have nowhere clean
  to live; `repo_scan.py` grows per-language code inline.
- Third-party pluggability later gets harder.

📊 **Effort:** Low

📦 **Libraries / Tools:** same optional tree-sitter question as A.

🔗 **Existing Code to Reuse:** same as A.

---

## Recommendation

**Option A** is recommended (and was approved by the user). The hard part of
the feature is not the outline — it is the `references` edges, whose
resolution semantics differ per language (PHP PSR-4 namespaces + `require`
paths; JS/TS relative specifiers with extension guessing; Rust crate/mod
conventions). Only a per-language class gives that logic a first-class home
while keeping `repo_scan.py`'s public API frozen. Options B and C were
rejected: B makes tree-sitter load-bearing and still needs per-language
resolvers; C leaves resolution half-hardwired.

---

## Feature Description

### User-Facing Behavior

- `wikitoolkit build` on a PHP / TypeScript / Rust codebase produces `file:`
  pages with real **API outlines** and **`references` edges** between files,
  exactly as Python enjoys today.
- `.php` joins `CODE_SUFFIXES`; `.html`/`.htm` join `DOC_SUFFIXES` (shallow
  scan only: summary from `<title>` or first heading, content head, no
  outline/edges).
- With `pip install ai-parrot[wiki-languages]`, outlines come from tree-sitter
  grammars; without it, deterministic regex heuristics are used silently.
- `wiki_stats.json` and `wikitoolkit status` gain a `languages` block, e.g.
  `{"php": "tree-sitter", "rust": "heuristic"}`, so users can see which mode
  built the graph.

### Internal Behavior

- New package `parrot/knowledge/wiki/languages/`:
  - `base.py` — `LanguageScanner` ABC, `LanguageOutline` Pydantic model,
    suffix registry + `scanner_for(suffix)`.
  - `treesitter.py` — `get_parser(lang) -> Parser | None`, cached per
    process, never raises.
  - `python.py` — existing `ast` logic moved (`_python_outline`,
    `_module_index`); byte-identical output.
  - `php.py`, `javascript.py` (covers `.js/.jsx/.mjs/.ts/.tsx`), `rust.py` —
    tree-sitter outline + heuristic fallback each.
- `build_file_slice()` consults the registry instead of the hardcoded
  `if suffix in {".py", ".pyi"}` branch; `FileSlice` gains
  `language: Optional[str]`.
- `build_import_edges()` groups `FileSlice`s by language, builds each
  language's reference index once over the full repo file list, and resolves
  each file's raw specifiers to target rel-paths (unresolvable specifiers are
  dropped).
- The incremental fast-path checks "any changed suffix belongs to a registered
  scanner" instead of `.py/.pyi`.

Per-language semantics:

| Language | Outline | Imports → `references` edges |
|---|---|---|
| Python | unchanged (`ast`) | unchanged — byte-identical |
| PHP | classes, interfaces, traits, enums, functions, methods + docblock first line | `use A\B\C;` (incl. group use), `require/include 'path'`; namespace→file via composer.json PSR-4 maps when present, else heuristic namespace-tail ↔ path matching; require paths resolved relative to the file |
| JS/TS | exported classes/functions/consts, interfaces, type aliases | `import … from`, `export … from`, `require()`; only **relative** specifiers resolved, with extension guessing (`.ts/.tsx/.js/.jsx/.mjs`, `/index.*`); bare package names ignored |
| Rust | `pub` structs/enums/traits/fns/mods, impl blocks, `///` doc first line | `use crate::a::b`, `mod foo;` via crate conventions (`src/lib.rs`, `src/main.rs`, `foo.rs` vs `foo/mod.rs`) |
| HTML | *not a plugin* — shallow scan, `<title>`/first-heading summary | none |

### Edge Cases & Error Handling

- Any parse failure (tree-sitter or heuristic) degrades to the shallow page —
  never raises, never blocks the post-commit hook.
- Missing tree-sitter grammar → heuristic mode, reported in stats, silent
  otherwise.
- Oversized/binary file handling unchanged (`build_file_slice` early returns).
- Import specifiers that resolve outside the repo (vendor/, node_modules/,
  crates.io packages) are dropped — no dangling edges.
- Mixed-language repos: each language's index is independent; a PHP `require`
  can never resolve to a `.ts` file.

---

## Capabilities

### New Capabilities
- `wikitoolkit-language-plugins`: pluggable per-language scanner interface for
  the wiki repo scanner, with Python (moved), PHP, JS/TS, and Rust plugins.

### Modified Capabilities
- LLM Wiki build (FEAT-260 `repo_scan`): default suffixes extended
  (`.php`, `.html`, `.htm`); outline/edge extraction becomes registry-driven.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/repo_scan.py` | modifies (internals only) | public API frozen; `_python_outline`/`_module_index` move out |
| `parrot/knowledge/wiki/languages/` | new package | ABC + registry + 4 plugins + treesitter helper |
| `parrot/knowledge/wiki/cli.py` | extends | `languages` block in `wiki_stats.json` / `status` output |
| `packages/ai-parrot/pyproject.toml` | extends | new optional extra `wiki-languages` |
| git post-commit hook | none | unchanged; benefits automatically |
| `documentation/parrot-wiki-cli.md` | docs update | language support + extras |

No breaking changes. Existing wikis re-index new languages on next full build.

---

## Code Context

### User-Provided Code

(none — user provided the feature request in prose)

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py
CODE_SUFFIXES: frozenset[str]   # line 42 — .py .pyx .pxd .pyi .rs .go .java .kt .c .h .cpp .hpp .js .jsx .ts .tsx .mjs .sql .sh .bash — NO .php
DOC_SUFFIXES: frozenset[str]    # line 50 — {".md", ".rst", ".txt"} — NO .html
CONFIG_SUFFIXES: frozenset[str] # line 53
DEFAULT_SUFFIXES: frozenset[str]  # line 57 — union of the three

class FileSlice(BaseModel):     # line 91
    rel_path: str
    record: WikiPageRecord
    imports: list[str] = Field(default_factory=list)  # dotted modules, Python-only today

class RepoScan(BaseModel):      # line 107
    root: Path
    files: list[FileSlice]
    dir_records: list[WikiPageRecord]
    dir_edges: list[tuple[str, str, str]]
    import_edges: list[tuple[str, str, str]]
    skipped: list[str]

def _category_for(rel_path: str) -> str: ...          # line 374
def _python_outline(source: str) -> tuple[str, list[str], list[str]]: ...  # line 384 — (summary, outline, imports) via ast
def _markdown_summary(content: str) -> str: ...       # line 428
def build_file_slice(root, rel_path, body_max_chars=16_000, max_file_bytes=524_288) -> Optional[FileSlice]: ...  # line 437 — hardcodes `if suffix in {".py", ".pyi"}`
def _module_index(rel_paths: Iterable[str]) -> dict[str, str]: ...  # line 564 — Python dotted names, strips src/ layout
def build_import_edges(files, index_paths=None) -> list[tuple[str, str, str]]: ...  # line 589
def scan_repository(root, suffixes=None, exclude_dirs=None, body_max_chars=..., max_file_bytes=..., use_git=True, rel_paths=None) -> RepoScan: ...  # line 631 — fast-path checks `suffix in {".py", ".pyi"}` before repo-wide discovery
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def estimate_tokens(text: str) -> int: ...  # line 142
class WikiPageRecord(BaseModel):            # line 194
    concept_id: str; node_id: Optional[str]; title: str; category: str
    summary: str; body: str; source_id: Optional[str]; token_count: int
    origin: str = "ingest"; asserted_by: Optional[str]
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
# build command calls scan_repository(...) at line 678 (full) and line 871 (incremental);
# _write_reports writes wiki_stats.json at lines 515-529.
from parrot.knowledge.wiki.repo_scan import (  # line 47
    scan_repository,  # line 50
)
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py
include_suffixes: list[str] = Field(default_factory=list)  # line 142 — per-repo suffix override already exists
exclude_dirs: list[str] = Field(default_factory=list)      # line 143
```

```python
# From packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py:202
@staticmethod
def _build_parser():
    from tree_sitter import Language, Parser
    import tree_sitter_python
    lang = Language(tree_sitter_python.language())
    return Parser(lang)
# Precedent: tree-sitter already used in-repo, via individual grammar wheels.
```

#### Verified Imports
```python
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens  # used by repo_scan.py:31
```

#### Key Attributes & Constants
- `packages/ai-parrot/pyproject.toml:184-192` — `graphindex` extra already declares `tree-sitter>=0.23`, `tree-sitter-languages>=1.10`.
- `tests/knowledge/wiki/test_repo_scan.py` — existing scanner regression suite (must pass unchanged).

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/knowledge/wiki/languages/`~~ — package does not exist yet (verified 2026-07-31).
- ~~`.php`, `.html`, `.htm` in any suffix set~~ — not scanned today.
- ~~a `wiki-languages` extra in pyproject.toml~~ — does not exist yet.
- ~~`FileSlice.language`~~ — field does not exist yet.
- ~~any non-Python outline/import extraction in `repo_scan.py`~~ — Python/`ast` only.

---

## Parallelism Assessment

- **Internal parallelism**: after the framework task (base.py + registry +
  Python plugin move + repo_scan integration), the PHP, JS/TS, and Rust
  plugins are independent files with independent tests — parallelizable in
  principle, but they share `treesitter.py` and the registry module.
- **Cross-feature independence**: touches only `parrot/knowledge/wiki/` +
  pyproject extras; no known in-flight spec conflicts.
- **Recommended isolation**: per-spec (single worktree, sequential tasks).
- **Rationale**: the language plugins are small once the framework exists;
  coordination cost of parallel worktrees exceeds the benefit.

---

## Open Questions

- [x] Where should plugins live, and can they bring external dependencies? — *Owner: Jesus*: In-tree registry + optional tree-sitter; plugins may declare an optional grammar and MUST degrade to stdlib heuristics when it is missing.
- [x] Language coverage for the first delivery? — *Owner: Jesus*: Framework + PHP + JS/TS + Rust deep extractors (Python stays on `ast`, moved unchanged).
- [x] How should HTML be handled? — *Owner: Jesus*: Shallow scan only — add `.html`/`.htm` to default suffixes (title/first-heading summary + content head), no outline, no edges, no plugin.
- [x] Plugin interface architecture? — *Owner: Jesus*: `LanguageScanner` ABC + suffix registry in `parrot/knowledge/wiki/languages/` (Option A), with per-language `build_reference_index`/`resolve_import` for edge resolution.
- [x] tsconfig `paths` aliases in the JS/TS resolver? — *Owner: Jesus*: Out of scope for v1; only relative specifiers are resolved.
- [ ] Grammar packaging for the `wiki-languages` extra: one bundled wheel (`tree-sitter-language-pack`) vs individual grammar wheels (`tree-sitter-php`, `tree-sitter-typescript`, `tree-sitter-rust`, `tree-sitter-javascript`) following the graphindex precedent — decidable at implementation time; verify py3.10–3.12 wheel availability. — *Owner: implementer*
