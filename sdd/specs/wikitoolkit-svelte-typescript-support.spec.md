---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Svelte / hardened-TypeScript support in the wiki repo scanner

**Feature ID**: FEAT-396
**Date**: 2026-07-31
**Author**: Emmanuel Arroyo (emman6321@gmail.com)
**Status**: implemented
**Target version**: 0.26.0

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-394 introduced the pluggable language-scanner system (`wiki/languages/`) with scanners for
Python, PHP, JS/TS and Rust. `.svelte` files are claimed by **no** scanner, so in a SvelteKit
repository every component is invisible to the wiki graph: no outline, no `references` edges,
and a `summary` that degrades to the shallow content head.

Measured on `navigator-svelte` (2026-07-31):

| Metric | Value | How measured |
|---|---|---|
| `.svelte` files under `src/` | **920** | `find src -name "*.svelte" \| wc -l` |
| …declaring `<script lang="ts">` | **883 (96.0%)** | `grep -rl '<script lang="ts"' --include=*.svelte src` |
| Internal imports via `$lib` alias | **2976** | `grep -rhoE "from ['\"]\$lib[^'\"]*"` over `*.svelte`/`*.ts` |
| Internal imports via `$app` alias | **271** | idem |
| Internal imports, relative (`./`, `../`) | **1625** | idem |

**65% of internal imports are alias-based**, so even a perfect `.svelte` outline would still lose
roughly two thirds of the cross-file edges.

Baseline for comparison, from the 2026-07-30 measurements: a Laravel repo scanned before its
language plugin existed produced **647 nodes and 0 `references` edges** (the graph collapses to
a directory tree), against **2056 nodes / 173 edges** for a Python repo with an extractor. The
extractor is what makes the difference, not the tool.

Three defects compound here, and only the first is about Svelte:

1. `.svelte` is in neither `CODE_SUFFIXES` (`repo_scan.py:58-66`) nor `JavaScriptScanner.suffixes`
   (`javascript.py:143-145`).
2. `outline()` hands the **whole file** to `parser.parse()` (`javascript.py:229`). A `.svelte` file
   is not valid TS/JS — the markup breaks the tree and the `except Exception` at
   `javascript.py:171-173` silently returns an empty outline.
3. **The TypeScript grammar never loads**, because the grammar wheels do not share a single
   loading convention — see §7. This affects every `.ts`/`.tsx`/`.php` file today, not only
   Svelte, and it must be addressed here because piece 2 depends on a working TS grammar.

### Goals

- `.svelte` files produce a real outline, summary, and resolved import edges.
- The TypeScript and PHP tree-sitter grammars actually load when
  `ai-parrot[wiki-languages]` is installed.
- Alias-based specifiers (`$lib/...`, `tsconfig.json` `paths`) resolve to repository files.
- Every change lands inside `javascript.py` / `treesitter.py` / the existing registry — no new
  scanner class, no new abstraction layer, no change to the `LanguageScanner` ABC.

### Non-Goals (explicitly out of scope)

- A per-framework scanner (`SvelteScanner`, `VueScanner`). Rejected up front: the extension
  belongs inside the JS/TS scanner.
- Parsing Svelte **markup** semantics (component usage as graph edges, `{#if}`/`{#each}` blocks,
  slots). Only the `<script>` block is analysed.
- `.vue` / `.astro` single-file components. The `<script>`-extraction seam introduced here makes
  them cheap to add later, but they are not claimed by this spec.
- Resolving `$app/*`, `$env/*` and other SvelteKit **virtual** modules — they have no file in the
  repository, so the edge is correctly dropped (271 imports affected, by design).
- Runtime type-checking or diagnostics. This is a documentation graph, not a compiler.

---

## 2. Architectural Design

### Overview

`JavaScriptScanner` grows a **pre-extraction seam** and an **alias-aware resolver**; the loader
in `treesitter.py` learns the real grammar-module API.

1. **Claim the suffix.** `.svelte` is added to `CODE_SUFFIXES` and to
   `JavaScriptScanner.suffixes`. `_SUFFIX_INDEX` (`languages/__init__.py:39-43`) then routes
   `.svelte` to the JS scanner automatically, and `scanned_suffixes()` picks it up with no
   registry edit.
2. **Extract the script block.** Before parsing, `outline()` calls a new
   `_extract_script_blocks(source)`. For a `.svelte` file it returns the concatenated bodies of
   the `<script>` / `<script module>` blocks plus the `lang` attribute; for every other suffix it
   returns the source unchanged and `lang=None`. Imports are still extracted from the **raw**
   source (the regexes already work, and this keeps behaviour identical for non-Svelte files).
3. **Select the grammar by `lang`, not by suffix.** The current ternary
   (`javascript.py:163-165`) keys off the file suffix; a `.svelte` with `lang="ts"` would fall to
   the JavaScript grammar. Selection becomes: `lang="ts"`/`"typescript"` → `typescript`, absent
   → `javascript`, and non-Svelte files keep the existing suffix rule.
4. **Fix the grammar loader.** `_build_parser` tries `language()` and then the
   `language_<name>()` variants the wheels actually expose.
5. **Resolve aliases.** `build_reference_index` returns a richer index — the existing
   `frozenset[str]` plus an alias map read from the scan root — and `resolve_import` tries the
   alias map before giving up on a non-relative specifier. `_extract_imports` stops discarding
   non-relative specifiers unconditionally.

### Component Diagram

```
repo_scan.build_file_slice()          repo_scan.build_import_edges()
        │ scanner_for(".svelte")               │
        ▼                                      ▼
  JavaScriptScanner.outline()          build_reference_index(rel_paths)
        │                                      │  reads $lib / tsconfig paths
        ├─ _extract_imports(raw source)        │  via languages.get_scan_root()
        ├─ _extract_script_blocks(source) ─┐   ▼
        │      → (script_src, lang)        │  JsIndex{files, aliases}
        ▼                                  │        │
  treesitter.get_parser(lang)  ◄───────────┘        ▼
        │  language() → language_typescript()  resolve_import(spec, from_file, index)
        ▼                                            ├─ relative  → extension guessing (existing)
   tree_sitter.Parser                                └─ alias     → expand prefix, then guessing
```

### Integration Points

| Existing component | Integration type | Notes |
|---|---|---|
| `repo_scan.CODE_SUFFIXES` (`repo_scan.py:58-66`) | extend | add `".svelte"`; `DEFAULT_SUFFIXES` (line 78) picks it up automatically |
| `JavaScriptScanner.suffixes` (`javascript.py:143-145`) | extend | add `".svelte"`; `_SUFFIX_INDEX` derives routing with no registry edit |
| `JavaScriptScanner.outline` (`javascript.py:149-174`) | modify | insert script pre-extraction + `lang`-based grammar selection |
| `JavaScriptScanner.build_reference_index` (`javascript.py:298-307`) | modify | return `JsIndex` instead of a bare `frozenset` |
| `JavaScriptScanner.resolve_import` (`javascript.py:309-341`) | modify | alias branch before the existing relative branch |
| `JavaScriptScanner.mode` (`javascript.py:343-352`) | modify | stop reporting `"tree-sitter"` when only the JS grammar loaded |
| `treesitter._build_parser` (`treesitter.py:60-76`) | modify | try `language_<name>()` variants |
| `languages.get_scan_root()` (`languages/__init__.py:99-106`) | reuse | same precedent PHP uses to read `composer.json` (`php.py:349-359`) |
| `LanguageScanner` ABC (`base.py:40-114`) | **unchanged** | the index is declared `Any` (`base.py:75-89`), so a richer object needs no ABC change |

### Data Models

```python
# javascript.py — replaces the bare frozenset returned today
@dataclass(frozen=True)
class JsIndex:
    files: frozenset[str]          # every scanned repo file, POSIX rel paths
    aliases: tuple[tuple[str, str], ...]  # ("$lib/", "src/lib/"), longest prefix first
```

`aliases` is a sorted tuple rather than a dict so the longest-prefix match is a plain ordered
scan and the object stays hashable/immutable like the frozenset it replaces.

### New Public Interfaces

None. Every change is internal to the scanner; the `LanguageScanner` contract, the registry
functions, and the CLI surface are untouched.

### Alias discovery order

Read once per scan, in `build_reference_index`, against `get_scan_root()`:

1. `svelte.config.js` → `kit.alias` block, when present (regex-scraped, not JS-evaluated).
2. `tsconfig.json` / `jsconfig.json` → `compilerOptions.paths`, resolved relative to `baseUrl`.
3. **SvelteKit convention fallback**: if the repo has a `svelte.config.js` at the root, map
   `$lib/` → `src/lib/` even when nothing declares it.

Step 3 is not a convenience — it is the common case. In `navigator-svelte` the only declaration
of `$lib` lives in `.svelte-kit/tsconfig.json`, which is **generated and gitignored**
(`.gitignore:4`); the committed `tsconfig.json` merely `extends` it and `svelte.config.js`
declares no `alias` block at all. A scanner that only reads committed files would resolve zero
aliases on a fresh clone.

---

## 3. Module Breakdown

### Module 1: grammar-callable resolution in the loader
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py`
- **Responsibility**: teach `_build_parser` that the wheels expose two conventions. Resolve the
  grammar callable by trying `language()` first (single-grammar wheels — unchanged behaviour for
  javascript, rust, python), then the named variant for multi-grammar wheels
  (`language_typescript()` for `typescript`, `language_php()` for `php`). Log at debug which
  callable was used so the mode is auditable.
- **Depends on**: nothing (self-contained, independently mergeable and revertable)

### Module 2: claim `.svelte`
- **Path**: `repo_scan.py` (`CODE_SUFFIXES`), `languages/javascript.py` (`suffixes`)
- **Responsibility**: two frozenset entries. After this module `.svelte` files get shallow pages
  plus **imports** (the regex extractor already works on the raw source); the outline is still
  degraded until Module 3.
- **Depends on**: nothing

### Module 3: `<script>` pre-extraction + `lang`-aware grammar selection
- **Path**: `languages/javascript.py`
- **Responsibility**: `_extract_script_blocks(source, suffix) -> tuple[str, str | None]`; wire it
  into `outline()`; replace the suffix-based grammar ternary with `lang`-based selection. Must
  handle: multiple `<script>` blocks (instance + `module`/`context="module"`), attributes in any
  order, `lang='ts'` single-quoted, self-closing/empty blocks, and a file with no `<script>` at
  all (returns empty outline, never raises).
- **Depends on**: Modules 1 and 2

### Module 4: alias resolution
- **Path**: `languages/javascript.py`
- **Responsibility**: `JsIndex`; alias discovery in `build_reference_index` (via
  `get_scan_root()`, following the `php.py:349-359` precedent); the alias branch in
  `resolve_import`; relax `_extract_imports` so non-relative specifiers survive extraction and
  are filtered at resolution time instead.
- **Depends on**: Module 2

### Module 5: mode reporting, tests, docs
- **Path**: `languages/javascript.py` (`mode`), `tests/knowledge/wiki/languages/`,
  `packages/ai-parrot/pyproject.toml`, `documentation/parrot-wiki-cli.md`
- **Responsibility**: honest `mode`; the test matrix in §4; document `.svelte` in the CLI docs
  and the `wiki-languages` extra.
- **Depends on**: Modules 1-4

---

## 4. Test Specification

Existing suite to extend: `tests/knowledge/wiki/languages/` — `test_javascript_plugin.py`,
`test_treesitter.py`, `test_registry.py`, `test_polyglot_integration.py`,
`test_repo_scan_integration.py`, with shared fixtures in `conftest.py`.

### Unit tests

| Test | Module | Description |
|---|---|---|
| `test_build_parser_uses_language_variant` | 1 | `typescript` and `php` return a real `Parser` when the wheels are installed (`skipif` otherwise) |
| `test_build_parser_unknown_language_none` | 1 | unchanged `None` for an unmapped name |
| `test_registry_claims_svelte` | 2 | `scanner_for(".svelte")` is the `JavaScriptScanner`; `".svelte" in scanned_suffixes()` |
| `test_code_suffixes_contains_svelte` | 2 | `".svelte" in CODE_SUFFIXES` and in `DEFAULT_SUFFIXES` |
| `test_extract_script_blocks_instance_and_module` | 3 | both blocks concatenated, markup excluded |
| `test_extract_script_blocks_lang_variants` | 3 | `lang="ts"`, `lang='ts'`, `lang="typescript"`, absent → correct grammar name |
| `test_extract_script_blocks_no_script` | 3 | markup-only component → empty outline, no exception |
| `test_svelte_outline_exports` | 3 | `export function` / `export const` / `interface` inside `<script lang="ts">` appear in the outline |
| `test_svelte_summary_is_not_script_tag` | 3 | summary is the leading JSDoc or `""` — **never** the literal `<script lang="ts">` line |
| `test_alias_from_tsconfig_paths` | 4 | `paths` entry `"$lib/*": ["src/lib/*"]` resolves `$lib/x` → `src/lib/x.ts` |
| `test_alias_sveltekit_convention_fallback` | 4 | repo with `svelte.config.js` and **no** declared paths still resolves `$lib/` |
| `test_alias_longest_prefix_wins` | 4 | `$lib/components/` beats `$lib/` when both are declared |
| `test_alias_unresolved_returns_none` | 4 | `$app/environment` → `None` (dropped, not dangling) |
| `test_bare_package_still_unresolved` | 4 | `react`, `lodash` → `None` |
| `test_mode_requires_both_grammars` | 5 | `mode` is `"heuristic"` when only the JS grammar loads |

### Integration tests

| Test | Description |
|---|---|
| `test_scan_svelte_fixture_repo` | Fixture repo with `svelte.config.js`, `src/lib/util.ts`, and a component importing `$lib/util` → the `references` edge exists |
| `test_svelte_heuristic_parity` | Same fixture with grammars monkeypatched to unavailable → imports and edges identical, outline degrades but is non-empty |
| `test_polyglot_svelte_alongside_python` | `.svelte` and `.py` in one scan → both outlines present, no scanner cross-talk |

### Test data / fixtures

```python
# tests/knowledge/wiki/languages/conftest.py — new fixture
@pytest.fixture
def svelte_repo(tmp_path):
    """Minimal SvelteKit-shaped repo: alias declared only by convention."""
    (tmp_path / "svelte.config.js").write_text("export default { kit: {} }\n")
    (tmp_path / "src/lib").mkdir(parents=True)
    (tmp_path / "src/lib/util.ts").write_text("export function helper(a: string) {}\n")
    (tmp_path / "src/lib/Widget.svelte").write_text(
        '<script lang="ts">\n'
        "  import { helper } from '$lib/util'\n"
        "  export const label = 'x'\n"
        "</script>\n"
        "<div>{label}</div>\n"
    )
    return tmp_path
```

---

## 5. Acceptance Criteria

- [x] `scanner_for(".svelte")` returns the `JavaScriptScanner`; `".svelte"` is in
      `CODE_SUFFIXES` and in `scanned_suffixes()`.
- [x] `treesitter.get_parser("typescript")` returns a `Parser` (not `None`) with
      `ai-parrot[wiki-languages]` installed — it returns `None` today, see §7.
- [x] `treesitter.get_parser("php")` likewise returns a `Parser`.
- [x] `treesitter.get_parser("javascript")` and `get_parser("rust")` keep working unchanged —
      Module 1 must not regress the single-grammar wheels.
- [x] A `.svelte` file with `<script lang="ts">` yields a non-empty `outline`, and its `summary`
      is never the literal `<script lang="ts">` line.
- [x] `$lib/...` specifiers resolve to real files in a repo whose alias is declared **only** by
      SvelteKit convention (no committed `paths`, `.svelte-kit/` absent).
- [x] Unresolvable specifiers (`$app/environment`, bare packages) return `None` — no dangling
      edges in the graph.
- [x] Scanning `navigator-svelte` produces > 0 `references` edges out of `.svelte` files, where
      the current build produces 0.
- [x] Behaviour on `.js`/`.jsx`/`.mjs`/`.ts`/`.tsx` files is unchanged except for the grammar fix:
      the existing `test_javascript_plugin.py` suite passes untouched.
- [x] The full existing suite passes: `pytest tests/knowledge/wiki/ -v`.
- [x] Every new code path degrades without the optional extra — the whole suite passes with
      tree-sitter uninstalled.
- [x] `mode` reports `"heuristic"` unless **both** grammars this scanner can select actually load.
- [x] `documentation/parrot-wiki-cli.md` lists `.svelte` among supported suffixes.

---

## 6. Codebase Contract

> Every reference below was read and verified on 2026-07-31 at commit `df5cb1540` (branch `dev`,
> after the FEAT-394 merge `af63af047`, PR #1082).

### Verified imports

```python
# verified: languages/javascript.py:24-25
from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner

# verified: languages/__init__.py:19-27 (__all__)
from parrot.knowledge.wiki.languages import (
    all_scanners, get_scan_root, scanned_suffixes, scanner_for, set_scan_root,
)

# verified: repo_scan.py:40-44
from parrot.knowledge.wiki.languages import scanned_suffixes, scanner_for, set_scan_root
from parrot.knowledge.wiki.languages.python import PythonScanner
```

### Existing class signatures

```python
# languages/base.py
class LanguageOutline(BaseModel):          # line 21
    summary: str = ""                      # line 35
    outline: list[str] = Field(...)        # line 36
    imports: list[str] = Field(...)        # line 37

class LanguageScanner(ABC):                # line 40
    name: ClassVar[str]                    # line 53
    suffixes: ClassVar[frozenset[str]]     # line 55
    def outline(self, source: str, rel_path: str) -> LanguageOutline: ...        # line 58
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...        # line 75
    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None: ...  # line 92
    @property
    def mode(self) -> str: ...             # line 112

# languages/javascript.py
class JavaScriptScanner(LanguageScanner):  # line 139
    name = "javascript"                    # line 142
    suffixes = frozenset({".js", ".jsx", ".mjs", ".ts", ".tsx"})   # lines 143-145
    def outline(self, source, rel_path) -> LanguageOutline:        # line 149
    def _outline_heuristic(self, source) -> tuple[str, list[str]]: # line 176
    def _outline_treesitter(self, parser, source) -> tuple[str, list[str]]:  # line 222
    def build_reference_index(self, rel_paths) -> Any:             # line 298
    def resolve_import(self, spec, from_file, index) -> str | None:# line 309

# module-level helpers to reuse, not reimplement
_extract_imports(source) -> list[str]      # line 111  (filters non-relative at line 119)
_normalize_posix(path) -> str              # line 125
_EXTENSION_CANDIDATES                      # line 77
_INDEX_CANDIDATES                          # lines 78-80

# languages/treesitter.py
_GRAMMAR_MODULES: dict[str, str]           # lines 30-35
def get_parser(language: str) -> Parser | None:   # line 38  (caches, incl. None — line 52-57)
def _build_parser(language: str) -> Parser | None:# line 60  (calls grammar_module.language() — line 69)
```

### Integration points

| New component | Connects to | Via | Verified at |
|---|---|---|---|
| `.svelte` in `suffixes` | `_SUFFIX_INDEX` | derived comprehension | `languages/__init__.py:39-43` |
| `.svelte` in `CODE_SUFFIXES` | `DEFAULT_SUFFIXES` | set union | `repo_scan.py:78` |
| `outline()` | `build_file_slice()` | `scanner_for(suffix)` then `scanner.outline(...)` | `repo_scan.py:584-598` |
| alias discovery | scan root | `get_scan_root()` — same precedent as PHP's `composer.json` read | `languages/__init__.py:99-106`, `php.py:349-359` |
| `set_scan_root(root)` | `scan_repository()` | called once per scan | `repo_scan.py:795` |
| suffix gating for edges | `scanned_suffixes()` | `PurePosixPath(t).suffix in scanned_suffixes()` | `repo_scan.py:809` |
| `wiki-languages` extra | `pyproject.toml` | optional-dependencies | `packages/ai-parrot/pyproject.toml:202-208` |

### Does NOT exist (anti-hallucination)

- ~~`parrot.knowledge.wiki.languages.svelte`~~ — no Svelte module. Do **not** create one; the
  extension lives in `javascript.py` (§1 Non-Goals).
- ~~`SvelteScanner`~~ — not a class anywhere in the tree.
- ~~`tree_sitter_svelte`~~ — not in `_GRAMMAR_MODULES` (`treesitter.py:30-35`) and not in the
  `wiki-languages` extra (`pyproject.toml:202-208`). Svelte is parsed with the **typescript** and
  **javascript** grammars against the extracted `<script>` body.
- ~~`tree_sitter_typescript.language()`~~ — **does not exist in any released version.** Verified
  against 0.23.0 and 0.23.2 (the only versions satisfying `>=0.23`): both expose
  `language_typescript()` and `language_tsx()` only. Not resolvable via the module's dynamic
  `__getattr__` either.
- ~~`tree_sitter_php.language()`~~ — **does not exist.** 0.24.1 exposes `language_php()` and
  `language_php_only()`.
- Conversely, `tree_sitter_javascript.language()` and `tree_sitter_rust.language()` **do** exist
  — do not "fix" those call sites.
- ~~`LanguageScanner.aliases`~~ / ~~`LanguageScanner.script_block()`~~ — no such ABC members; the
  ABC is frozen (`base.py:40-114`, and the TASK-2010 note at `languages/__init__.py:78-86`).
- ~~an entry-point plugin registry~~ — registration is the explicit `_SCANNERS` dict
  (`languages/__init__.py:31-36`).
- `.svelte-kit/tsconfig.json` — **exists only after a build and is gitignored**
  (`navigator-svelte/.gitignore:4`). Never treat it as a required input.

### Verified runtime behaviour (measured, not inferred)

```
$ python -c "from parrot.knowledge.wiki.languages import treesitter, scanner_for, scanned_suffixes; ..."
suffixes claimed: ['.js', '.jsx', '.mjs', '.php', '.py', '.pyi', '.rs', '.ts', '.tsx']
parser typescript: None          ← with tree-sitter-typescript INSTALLED
parser javascript: <tree_sitter.Parser object at 0x...>
scanner_for('.svelte'): None
mode: tree-sitter                ← misreported; TS files are on the regex path

# a real .svelte forced through the JS scanner (FormRenderer.svelte):
summary: ''
outline lines: 2  ['const def', 'const msg']    ← garbage from the markup, 0 real symbols
imports: 8        ['./types', './schema-utils', './validation', ...]   ← all 8 found
```

This is the empirical basis for the whole spec: imports already work, the outline does not, and
the TypeScript grammar is dead on arrival.

---

## 7. Implementation Notes & Constraints

### Patterns to follow

- Follow `php.py` as the reference plugin: it is the only existing scanner that reads an
  auxiliary config file from the scan root (`composer.json`, `php.py:349-377`) and builds a
  prefix map — structurally identical to what alias resolution needs.
- Keep `outline()` non-raising. The `except Exception` at `javascript.py:171-173` is the contract
  (`base.py:59-61`): degrade to an empty outline, never propagate.
- Keep the regexes line-anchored and bounded — no nested quantifiers (`javascript.py:31-34`).
  `<script[^>]*>` with a non-greedy body is safe; a catch-all `.*` across the file is not.
- Everything must work with the optional extra **absent**. `get_parser` returning `None` is a
  supported state, not an error (`treesitter.py:38-57`).
- Alias config is read **once per scan** inside `build_reference_index`, never per file — that
  method is called once per scanner per scan (`base.py:75-89`).

### Known risks / gotchas

- **The tree-sitter wheels do not share one loading convention.** `_build_parser` calls
  `grammar_module.language()` (`treesitter.py:69`). That is correct for every **single-grammar**
  wheel, but the **multi-grammar** ones expose named variants instead — and two of the four
  languages registered in `_GRAMMAR_MODULES` are multi-grammar:

  | Wheel | Exposes | `language()` |
  |---|---|---|
  | `tree_sitter_python` (the graphindex precedent, `graphindex/extractors/code.py:211`) | `language` | ✅ |
  | `tree_sitter_javascript` | `language` | ✅ |
  | `tree_sitter_rust` 0.24.2 | `language` | ✅ |
  | `tree_sitter_typescript` 0.23.0 **and** 0.23.2 | `language_typescript`, `language_tsx` | ❌ |
  | `tree_sitter_php` 0.24.1 | `language_php`, `language_php_only` | ❌ |

  Verified by direct `getattr` against the installed wheels — the failure is a real
  `AttributeError: module 'tree_sitter_typescript' has no attribute 'language'`, and the module's
  dynamic `__getattr__` does not resolve it either. Every version satisfying the extra's
  `tree-sitter-typescript>=0.23` pin (`pyproject.toml:205`) behaves this way; there is no version
  to upgrade to.

  Consequence: the `except Exception` at `treesitter.py:71` — correct behaviour for an optional
  dependency — swallows the `AttributeError` and returns `None`, so **`.ts`, `.tsx` and `.php`
  files take the regex heuristic path whether or not the extra is installed.**

  Three properties made this invisible rather than obvious, which is why it survived FEAT-394's
  review: the only tree-sitter precedent in the repo was the single-grammar
  `tree_sitter_python.language()` (carried into the FEAT-394 spec at lines 410-415); that spec's
  own "Does NOT Exist" section records that `tree_sitter_php`/`tree_sitter_rust`/
  `tree_sitter_typescript` were imported nowhere in the repo, so the convention had nothing to be
  checked against; and `test_treesitter.py` asserts only failure paths (unknown language, missing
  module, caching) — never a successful load — so the suite passes identically either way.
  Module 1 fixes the loader; Module 5 adds the missing positive assertion.

  *Owner note: this predates this feature and affects existing PHP/TypeScript users. Worth
  raising with Jesús Lara as a FEAT-394 follow-up independently of when this spec merges — lead
  with the reproduction, not the diagnosis.*
- **`mode` lies.** `JavaScriptScanner.mode` (`javascript.py:343-352`) returns `"tree-sitter"` if
  **either** grammar loads. Since the JS grammar does load, stats have been reporting
  `tree-sitter` for TypeScript files that were parsed by regex. Module 5 tightens this; expect
  the reported mode of existing repos to change after the fix — that is the correction, not a
  regression.
- **`_PARSER_CACHE` caches `None`** (`treesitter.py:52-57`). Tests that monkeypatch grammar
  availability must clear the cache, or ordering will make them pass/fail non-deterministically.
- **Svelte 5 runes are not import statements.** `$state`, `$derived`, `$effect` are compiler
  intrinsics. They must not be mistaken for aliases — the alias matcher keys on a declared
  prefix ending in `/`, so `$state(` never matches `$lib/`. Worth an explicit test.
- **`export let` is a Svelte 4 prop declaration**, not a module export in the JS sense, and
  `export const` inside a `<script module>` block *is* a real export. The outline should render
  both without pretending to know the difference — do not add Svelte-semantic special-casing.
- **Relaxing `_extract_imports`** (line 119) changes what reaches `resolve_import` for **all**
  JS/TS files, not only Svelte. Bare specifiers (`react`, `lodash`) will now arrive and must be
  rejected there. Guard with `test_bare_package_still_unresolved`.
- **`build_reference_index` receives every scanned path**, not just this scanner's
  (`base.py:78-81`), so `svelte.config.js` and `tsconfig.json` are visible in the index even
  though `.js`/`.json` are scanned by other categories.

### External dependencies

| Package | Version | Reason |
|---|---|---|
| `tree-sitter-typescript` | `>=0.23` | already in the `wiki-languages` extra (`pyproject.toml:205`) — no new dependency, it just needs to actually load |
| `tree-sitter-javascript` | `>=0.23` | already present (`pyproject.toml:206`) |

**No new dependency is introduced by this feature.**

---

## 8. Open Questions

- [x] One plugin per framework, or extend the JS/TS scanner? — *Resolved (Jesús Lara,
      31/07/2026)*: extend `javascript.py`. No `SvelteScanner`. Reflected in §1 Non-Goals and the
      Module Breakdown.
- [x] Is alias resolution in scope, or a separate "hardened-typescript" effort? — *Resolved
      (Emmanuel, 31/07/2026)*: in scope here. Without it, 2976 of 4601 internal imports (65%) are
      dropped and the `.svelte` work delivers little measurable graph value.
- [x] Does the grammar-callable fix belong in this spec, or is it a separate FEAT-394
      follow-up? — *Resolved (Emmanuel, 31/07/2026)*: in this spec, as Module 1. Piece 3
      (`lang`-based grammar selection) is inert while `get_parser("typescript")` returns `None`,
      so splitting it out would leave this feature depending on unowned external work. Module 1
      is kept self-contained so it can be reviewed, merged, or reverted on its own.
- [ ] Should `.vue` / `.astro` reuse the `_extract_script_blocks` seam in a follow-up? —
      *Owner: Jesús Lara*. Out of scope here; the seam is designed to make it a suffix list plus
      a block-delimiter tweak, but no commitment is made.
- [ ] Should unresolved SvelteKit virtual modules (`$app/*`, `$env/*`, 271 imports) be recorded
      as a distinct "external" edge kind rather than dropped? — *Owner: Jesús Lara*. Dropping
      matches current behaviour for bare packages; changing it is a graph-schema decision beyond
      this scanner.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`. All five modules touch `javascript.py` (three of them
  the same two methods), so parallel worktrees would collide on every merge.
- **Sequential order**: Module 1 → 2 → 3 → 4 → 5. Modules 1 and 2 are independent of each other
  and could be committed in either order, but both must precede 3.
- **Cross-feature dependencies**: none. FEAT-394 is already merged to `dev` (`af63af047`,
  PR #1082).
- Module 1 is independently valuable and independently revertable — if the rest of the feature
  stalls, it should still land, since it fixes TypeScript and PHP outlines for every existing
  user.

```bash
git worktree add -b feat-396-wikitoolkit-svelte-typescript-support \
  .claude/worktrees/feat-396-wikitoolkit-svelte-typescript-support HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-31 | Emmanuel Arroyo | Initial draft. Grounded in `~/Documentos/llm-wiki-soporte-svelte.md` (analysis of 31/07/2026) plus direct verification against commit `df5cb1540`; adds Module 1 after reproducing the grammar-callable mismatch against the installed wheels (0.23.0/0.23.2 typescript, 0.24.1 php) and confirming the single-grammar wheels are unaffected. |
