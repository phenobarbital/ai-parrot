---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [wikitoolkit, symbols, ast-grep, svelte, typescript]
---

# Feature Specification: Honest structural tier, Svelte component symbols, and module-local JS functions in wikitoolkit

**Feature ID**: FEAT-609
**Date**: 2026-09-28
**Author**: Juan (jfrruffato@trocglobal.com), FieldSync team
**Status**: draft
**Target version**: next ai-parrot minor after 1.0.6

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-498 put a structural symbol plane (`sym:` pages plus `defines`/`contains`/`calls`/`extends`/
`implements` edges, served by `wikitoolkit symbols lookup|outline|blast`) behind an optional
ast-grep seam. For every language except Python, **symbols come only from that seam**. The
tree-sitter and heuristic tiers still write the `## API outline`, but they return empty `symbols`
and `refs` (`languages/javascript.py:510-551`; the same pattern holds in `php.py`, `rust.py` and
`perl.py`).

We measured this on `navigator-svelte`, the FieldSync SvelteKit front end (1,376 `.svelte` and
1,929 `.ts` files under `src/`), with ai-parrot 1.0.6. Every wiki module this spec touches is
byte-identical to `origin/dev` 8bf475842 except `project.py`, which this spec does not touch.

| Environment | `wikitoolkit build` result |
|---|---|
| venv with `wiki-languages` but without `wiki-structural` | `6032 pages, 7367 import edges, 0 symbols, 0 symbol edges` |
| same venv plus `ast-grep-py==0.45.3`, `build --force` | `13590 symbols, 24226 symbol edges` scanned → 13,574 `sym:` pages stored |

The investigation found three defects.

**1. The structural tier degrades silently and reports its state wrongly.**
- Nothing tells the user that symbols are off. The build logs `0 symbols` at INFO level
  (`repo_scan.py:1141`), and `symbols lookup` returns `(no results)`, which looks the same as
  "no such symbol".
- `wikitoolkit status` prints `Structural: {'javascript': 'tree-sitter', ...}` in both
  environments (`cli.py:2129`, `cli.py:2180`). This is because `mode` reports the tier that
  served the *last* file (`_last_mode`, `javascript.py:506`, `javascript.py:755`), and a
  `status` process has scanned nothing. So `status` claims `tree-sitter` even when ast-grep is
  installed, and never shows that the symbol plane is missing.
- **Installing the extra has no effect on an existing plane.** Staleness is decided per file
  from mtime and content (`cli.py:765`, `sources.entry_is_stale`). A build that newly *can*
  extract symbols reports `0 ingested, 6032 unchanged` and stores nothing: the scan found
  13,590 symbols and persisted none. Only `--force` recovers them, and nothing points the user
  to it.

**2. A Svelte component is not a symbol.** `_extract_script_blocks` (`javascript.py:173`) hands
only
the `<script>` body to `rules/typescript.yaml`. The component itself never becomes a `sym:` page,
even though it is the unit that other files import and render. For example, `symbols lookup
AdminBulkBar` and `symbols blast AdminBulkBar` return nothing, although the file-level
`references` edges to `AdminBulkBar.svelte` exist. Markup usage (`<Child ... />`) produces no ref.
Top-level script calls produce refs with an empty `src_qualname`, which `SymbolResolver`
(`repo_scan.py:903`) drops because no symbol owns them. 1,052 of the 1,376 components declare
their inputs with `$props()`, and none of that is captured as a signature.

**3. Module-local arrow functions are invisible.** The only rule that sees a
`lexical_declaration` requires `inside: export_statement` (`rules/typescript.yaml:67`). The only
ref scopes are
`function_declaration`/`method_definition`/`class_declaration` (`rules/typescript.yaml:77`). In a
`<script>` block almost nothing is exported, and handlers are written as `const onSave = () => …`:
643 such declarations exist in `src/**/*.svelte`. Minimal probe:

```svelte
<script lang="ts">
  import Child from './Child.svelte'
  let { rows }: { rows: string[] } = $props()
  const onSave = async () => { persist(rows) }
  function onReset() { clear() }
  export const helper = (x: number) => x * 2
</script>
<Child items={rows} on:save={onSave} />
```

What is extracted today:
- **Symbols:** `function onReset`, `const helper`. `onSave` is missing.
- **Refs:** `calls "" -> $props`, `calls "" -> persist` (both dropped for having no source
  symbol) and `calls onReset -> clear`.
- **`<Child>`:** nothing.

A related minor issue appears on every build: `typescript.yaml` is aliased to `javascript`
(`rules/typescript.yaml:14`), so the TypeScript-only kinds (`interface`, `type`, `extends`,
`implements`) are evaluated against the JavaScript grammar. That logs four
`could not be evaluated` warnings (`astgrep.py:863`), which bury any real warning.

### Goals

- G1: A build that could emit symbols but cannot do so because `ast-grep-py` is missing says so
  once, loudly, with the install hint. `status` reports the tier that *would* serve each
  language, and whether the symbol plane is enabled.
- G2: A change in a scanner's effective tier or rule file re-ingests that language's files on
  the next plain `build`, with no `--force`.
- G3: Every `.svelte` file yields one `component` symbol. Markup usage of an imported component
  becomes a `uses` edge. Top-level script refs are attributed to the component. `blast` on a
  component returns its users.
- G4: Module-local arrow and function-expression declarations become `function` symbols, and
  calls inside them resolve.
- G5: The `## API outline` text stays byte-identical to today for every existing fixture: the
  parity contract in `tests/knowledge/wiki/languages/test_outline_parity.py` holds.
- G6: No warnings from TS-only rules evaluated under the `javascript` alias.

### Non-Goals (explicitly out of scope)

- Making ast-grep a hard dependency, or moving `ast-grep-py` into `wiki-languages`. The seam
  stays optional, and this feature only makes its absence visible. See Open Question Q1.
- Symbol extraction on the tree-sitter tier. That would be a second extractor to keep in parity
  with the rules files.
- Svelte markup semantics beyond component usage: `{#if}`/`{#each}` blocks, slots, snippets,
  event directives as edges, `bind:`.
- `.vue` and `.astro` single-file components.
- Federating the `symbols` commands across namespaces. `symbols lookup` from a repo that
  federates `navigator-svelte` still reads only the local plane. This is a separate gap, noted
  for a follow-up.
- Changing Python symbol extraction (stdlib `ast`, unaffected).

---

## 2. Architectural Design

### Overview

Three independent modules plus one small rules-schema extension:

1. **Tier honesty (M1).**
   - `mode` becomes *predictive*: it reports what the next file would be served by, instead of
     what served the last one.
   - `build` emits a single WARNING when structural-capable files were scanned but the seam is
     unavailable.
   - `status` gains a `Symbols:` line.
2. **Fingerprint invalidation (M2).**
   - Each build persists a per-language *extractor fingerprint*: the effective tier plus a hash
     of the language's rule file.
   - When a language's fingerprint changes, that language's files go into the existing
     `force_rel_paths` mechanism (`cli.py:699`, already used by FEAT-532), so only those files
     re-ingest.
3. **Svelte component symbol (M3).** For `.svelte` files, after the seam succeeds,
   `JavaScriptScanner.outline` adds:
   - one `SymbolKind.COMPONENT` record spanning the file;
   - `uses` refs for PascalCase tags bound to `.svelte` imports;
   - re-attribution of `src_qualname == ""` refs to the component.

   `uses` joins the default blast relations.
4. **Module-local functions (M4).**
   - New `typescript.yaml` rules capture `const|let NAME = (arrow_function | function_expression)`
     at any export status, emitted as `function` symbols.
   - The arrow and function-expression declarators join the ref `scope` ancestors.
   - An optional `languages:` filter on `SymbolSpec`/`RefSpec` keeps TS-only rules off the
     `javascript` alias (G6).

The outline stays unchanged (G5) because `render.py` never renders the new records:
- `COMPONENT` is not in `_JS_RENDERED_KINDS` (`render.py:112`).
- The new function records carry `node_kind == "variable_declarator"`, which
  `_render_javascript` skips.

### Component Diagram

```
wikitoolkit build
   │
   ├─ scan_repo ─→ build_file_slice ─→ JavaScriptScanner.outline(.svelte)
   │                                      ├─ astgrep.extract(script)        (M4 rules)
   │                                      └─ _svelte_component_augment()    (M3)
   │                                            ├─ + COMPONENT symbol
   │                                            ├─ + uses refs (markup tags)
   │                                            └─ "" refs → component qualname
   ├─ _structural_gap_warning(scan)                                        (M1)
   ├─ extractor_fingerprint() vs stored ─→ force_rel_paths                (M2)
   └─ _ingest_files(..., force_rel_paths)                                 (existing)

wikitoolkit status ─→ scanner.mode (predictive, M1) + "Symbols:" line
symbols blast ─→ _DEFAULT_BLAST_RELATIONS + "uses"                        (M3)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `JavaScriptScanner.mode` / `PhpScanner.mode` / `RustScanner.mode` / `PerlScanner.mode` | modify | predictive; `_last_mode` kept only for logging |
| `astgrep.is_available()` / `astgrep.supported_language()` | uses | `astgrep.py:74`, `astgrep.py:151` |
| `render.structural_enabled()` | uses | `render.py:45` (config kill switch honoured) |
| `cli._ingest_files(force_rel_paths=…)` | uses | `cli.py:693-699`, `cli.py:765` |
| `cli` build call sites | modify | `cli.py:1548-1552`, `cli.py:1813-1817`: union fingerprint force set |
| `cli` status payload | modify | `cli.py:2129`, `cli.py:2180` |
| `SymbolKind` | extend | add `COMPONENT = "component"` after `MOD` (`symbols.py:53`) |
| `SymbolRef.rel` | uses | `uses` already allowed (`symbols.py:118`), emitted by nobody today |
| `SymbolResolver` | uses (unchanged) | step 2 (reachable file, unique name) resolves `uses` to the target component |
| `structural/service.py` `_DEFAULT_BLAST_RELATIONS` | modify | add `"uses"` (`service.py:44`) |
| `structural/tools.py` `BlastRadiusInput.relations` | modify | add `"uses"` to the `Literal` (`tools.py:74`) |
| `astgrep.SymbolSpec` / `RefSpec` | extend | optional `languages: list[str] \| None` |
| `rules/typescript.yaml` | modify | new `function` rules, extended ref scope, `languages:` on TS-only rules |

### Data Models

```python
# symbols.py — enum extension
class SymbolKind(str, Enum):
    ...
    MOD = "mod"
    COMPONENT = "component"   # new: a single-file UI component (.svelte)

# languages/astgrep.py — rule schema extension (both models)
class SymbolSpec(BaseModel):
    ...
    languages: list[str] | None = None   # None = every language the RuleSet serves

class RefSpec(BaseModel):
    ...
    languages: list[str] | None = None

# languages/fingerprint.py (new)
class ExtractorFingerprint(BaseModel):
    """Per-language identity of what produced a plane's symbols."""
    schema_version: int = 1
    languages: dict[str, str]   # scanner name -> "<mode>:<sha1(rule file)|none>"
```

The fingerprint is stored as `<storage_dir>/extractor_fingerprint.json`, next to
`wiki_stats.json`. It does not live in the store, because there is no backend-agnostic meta API:
the sqlite `meta` table (`store.py:1340`) has no counterpart on arango or postgres. See Open
Question Q2.

### New Public Interfaces

No new CLI commands and no new flags. The user-visible changes are:
- `status` gains a `Symbols:` line, e.g.
  `Symbols   : disabled for javascript, php, rust, perl — pip install 'ai-parrot[wiki-structural]'`.
- `build` may print one WARNING line with the same install hint.
- `symbols blast` follows `uses` by default.
- `sym:` pages of kind `component` appear.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: tier honesty | yes | predictive `mode` rule, warning text, status line fixed below | — |
| M2: fingerprint invalidation | no | — | Q2 (storage location) must be answered first |
| M3: Svelte component symbol | yes, after Q3 | record shape, tag regex, re-attribution rule fixed below | Q3 (name collisions on `+page`) confirms the decision |
| M4: module-local functions + rule languages | yes | exact YAML rules and render exclusion fixed below | — |

### Module 1: Structural tier honesty
- **Path**: `languages/javascript.py`, `languages/php.py`, `languages/rust.py`,
  `languages/perl.py`, `cli.py`
- **Responsibility**:
  - `mode` returns `"ast-grep"` when `structural_enabled()` and
    `astgrep.supported_language(<the scanner's primary ast-grep language>)` are both true
    (`typescript` for JS, `php`, `rust`, `perl`). Otherwise it applies today's
    tree-sitter/heuristic rule. `_last_mode` stays, used only for debug logging.
  - After `scan_repo`, `build` counts the scanned files whose scanner reports a non-`ast-grep`
    mode while being structural-capable (every scanner except `python` and `luau`). If that
    count is above 0 and `astgrep.is_available()` is false, it logs one WARNING:
    `"%d %s file(s) scanned without the structural tier: no sym: pages for them. Install
    'ai-parrot[wiki-structural]'"`.
  - When `structural_enabled()` is false (the kill switch), no warning is emitted: the user
    asked for that.
  - `status` prints a `Symbols:` line derived from the same predicate.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # languages/javascript.py  (modifies javascript.py:755)
  @property
  def mode(self) -> str:
      """Tier the NEXT file would be served by: "ast-grep" | "tree-sitter" | "heuristic"."""

  # cli.py  (new helper, called from the build path before _ingest_files)
  def _structural_gap_warning(scan: Any) -> str | None:
      """Return the one-line warning when structural-capable files were scanned
      without the ast-grep seam available, else None. Pure: no logging, no I/O."""
  ```

### Module 2: Extractor-fingerprint invalidation
- **Path**: `languages/fingerprint.py` (new), `cli.py`
- **Responsibility**:
  - Compute `ExtractorFingerprint` from every registered scanner: `mode` (M1) plus the SHA-1
    of its rule file under `languages/rules/<lang>.yaml`, or `none`.
  - Load the stored fingerprint and diff the two per language. The rel_paths of every scanned
    file whose scanner's entry changed are unioned into `force_rel_paths` at both
    `_ingest_files` call sites.
  - Write the new fingerprint only after a *successful* ingest.
  - A missing or corrupt stored file means "unknown". On an existing plane that holds pages,
    "unknown" forces every structural-capable language once: this is what heals every plane
    built before this feature.
- **Depends on**: Module 1 (predictive `mode`)
- **Interface Skeleton**:
  ```python
  # languages/fingerprint.py  (new)
  def current_fingerprint() -> ExtractorFingerprint:
      """Fingerprint of the scanners as installed in this process."""

  def load_fingerprint(storage_dir: Path) -> ExtractorFingerprint | None:
      """Stored fingerprint, or None when absent/unreadable. Never raises."""

  def save_fingerprint(storage_dir: Path, fp: ExtractorFingerprint) -> None:
      """Atomically write <storage_dir>/extractor_fingerprint.json."""

  def changed_languages(old: ExtractorFingerprint | None, new: ExtractorFingerprint) -> set[str]:
      """Scanner names whose entry differs; every structural-capable name when old is None."""
  ```

### Module 3: Svelte component symbol and `uses` edges
- **Path**: `symbols.py`, `languages/javascript.py`, `structural/service.py`,
  `structural/tools.py`
- **Responsibility**: in `JavaScriptScanner.outline`, only when the suffix is `.svelte` and the
  seam returned a `StructuralOutline`, `_svelte_component_augment` does three things:
  1. **Add the component symbol.** It prepends one `SymbolRecord` with:
     - `kind=COMPONENT`, `name=qualname=<file stem>`, `exported=True`, `depth=1`, `parent=None`;
     - `node_kind="svelte_component"`, `start_line=1`, `end_line=<last line>`,
       `start_byte=0`, `end_byte=len(source bytes)`;
     - `content_hash` = SHA-1 of the whole file;
     - `signature` = the type annotation text of the `let {…}: <T> = $props()` destructuring when
       present, else the destructured names, else `""`.

     Existing script symbols keep `parent=None` and their qualnames, so no existing `sym:` id
     changes.
  2. **Emit `uses` refs.** For every PascalCase opening tag in the markup (outside `<script>` and
     `<style>`) whose tag name is the default binding of an import whose specifier ends in
     `.svelte`, it emits `SymbolRef(src_qualname=<stem>, rel="uses",
     target_text=<stem of the imported file>, line=<tag line>)`. The ref is deduplicated per
     (target, line). The tag name alone is not the target, because the binding may differ from
     the imported file's stem.
  3. **Re-attribute orphan refs.** Every seam ref with `src_qualname == ""` gets the component
     stem as `src_qualname`.

  `"uses"` is added to `_DEFAULT_BLAST_RELATIONS` and to `BlastRadiusInput.relations`. No
  language emits `uses` today, so nothing else changes.
- **Depends on**: nothing (M4 improves its recall but is not required)
- **Interface Skeleton**:
  ```python
  # languages/javascript.py  (new, module-level)
  def _svelte_component_augment(
      source: str, rel_path: str, structural: StructuralOutline
  ) -> StructuralOutline:
      """Return `structural` with the component symbol prepended, markup `uses`
      refs appended, and empty-src refs re-attributed. Pure; never raises
      (on any parse failure returns `structural` unchanged)."""
  ```

### Module 4: Module-local functions and per-rule language filter
- **Path**: `languages/rules/typescript.yaml`, `languages/astgrep.py`, `languages/render.py`
- **Responsibility**:
  - Add `SymbolSpec.languages` and `RefSpec.languages`. When a spec's list is set and does not
    contain the language being extracted (the alias actually in use), the spec is skipped
    before `_find_all_isolated`.
  - Tag the `interface`, `type`, `extends` and `implements` entries of `typescript.yaml` with
    `languages: [typescript, tsx]`.
  - Add a `function` symbol rule matching a `variable_declarator` whose `value` is an
    `arrow_function` or a `function_expression`, inside a `lexical_declaration` at program or
    `<script>` top level:
    - `exported` is true when the rule matches inside an `export_statement`;
    - `node_kind` is `variable_declarator`;
    - `is_async` is read from the function node.
  - Existing `export const NAME = () => …` declarations keep their `const` record, so the
    outline is unchanged. The new rule excludes that case (`not: { inside: export_statement }`),
    which avoids two records for one name.
  - Extend the `calls` ref `scope.ancestor` list with that declarator, so a call inside an
    arrow body gets the arrow's name as `src_qualname`.
  - `render._render_javascript` skips any record with `node_kind == "variable_declarator"`
    (G5).
- **Depends on**: nothing
- **Interface Skeleton**: YAML only, plus one field on each of the two pydantic models (§2 Data
  Models) and one `continue` in `_render_javascript` (`render.py:117-125`). The exact YAML is
  written in the task. Kind names (`variable_declarator`, `arrow_function`,
  `function_expression`) must be re-verified against ast-grep-py 0.45.3's built-in typescript
  grammar, as TASK-2742 did.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_mode_predictive_with_astgrep` | M1 | with ast-grep available, a fresh `JavaScriptScanner().mode == "ast-grep"` before any `outline()` call |
| `test_mode_predictive_without_astgrep` | M1 | under `force_no_astgrep` (`tests/knowledge/wiki/languages/conftest.py:22`), `mode` is `tree-sitter`/`heuristic`, for all four scanners |
| `test_mode_honours_kill_switch` | M1 | `set_structural_enabled(False)`: mode is not `ast-grep` even when available |
| `test_structural_gap_warning_text` | M1 | a scan with JS files + `force_no_astgrep` returns the warning; a Python-only scan returns `None`; the kill switch returns `None` |
| `test_status_symbols_line` | M1 | `status` output contains `Symbols` + `wiki-structural` hint under `force_no_astgrep` |
| `test_fingerprint_changed_languages` | M2 | tier flip or rule hash change marks exactly that language; `None` old marks all structural-capable |
| `test_fingerprint_load_corrupt` | M2 | an unreadable file returns `None`, never raises |
| `test_svelte_component_symbol` | M3 | the §1 probe yields a `component` symbol `Parent`, with signature `{ rows: string[] }` |
| `test_svelte_uses_ref_by_import_stem` | M3 | `import Foo from './Child.svelte'` + `<Foo/>` → `uses` ref target `Child` |
| `test_svelte_orphan_refs_attributed` | M3 | `persist`/`$props` refs get `src_qualname == "Parent"` |
| `test_svelte_no_script` | M3 | markup-only `.svelte` yields just the component symbol, never raises |
| `test_svelte_existing_qualnames_stable` | M3 | script symbols keep `parent=None` and today's qualnames |
| `test_arrow_function_symbol` | M4 | `const onSave = async () => {}` → `function onSave`, `is_async`, not exported |
| `test_exported_arrow_stays_const` | M4 | `export const helper = () => 1` keeps exactly one `const` record |
| `test_call_inside_arrow_scoped` | M4 | `persist(...)` in `onSave` → ref `src_qualname == "onSave"` |
| `test_ts_only_rules_skip_javascript` | M4 | extracting a `.js` file logs no `could not be evaluated` warning |
| `test_outline_parity` (existing) | M3, M4 | still passes unmodified: the parity contract (G5) |

### Integration Tests
| Test | Description |
|---|---|
| `test_build_heals_after_extra_installed` | build a fixture repo under `force_no_astgrep` (0 symbols), then a plain `build` with ast-grep available → the JS files re-ingest and `sym:` pages exist, **without** `--force` |
| `test_build_fingerprint_no_churn` | two consecutive plain builds with nothing changed → the second reports 0 ingested |
| `test_blast_component_users` | fixture: `Child.svelte` used by `Parent.svelte` and `Other.svelte` → `blast Child` returns both components' symbols via `uses` |
| `test_lookup_component` | `symbols lookup Child` returns the `component` hit |

### Test Data / Fixtures
```python
# tests/knowledge/wiki/languages/fixtures/svelte_components/
#   Child.svelte   — $props() with a typed destructuring, one arrow handler
#   Parent.svelte  — the §1 probe (imports Child, renders <Child/>)
#   Other.svelte   — imports Child under a different binding (`import Kid from './Child.svelte'`)
#   +page.svelte   — markup only, no <script>
#   plain.js       — a JS file, to prove the TS-only rules stay silent
```

---

## 5. Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/ -q` passes, including the unmodified
      `test_outline_parity.py`.
- [ ] On a venv without `ast-grep-py`: `wikitoolkit build` on a repo with `.ts` files prints the
      `wiki-structural` WARNING exactly once, and `status` shows `Symbols: disabled for …`.
- [ ] Installing `ai-parrot[wiki-structural]` and running a plain `wikitoolkit build` (no
      `--force`) on that same plane stores `sym:` pages.
- [ ] `status` reports `javascript: ast-grep` in a fresh process when ast-grep is installed.
- [ ] Re-measured on `navigator-svelte`, the counts are recorded in the PR description:
      - at least one `component` symbol per `.svelte` file;
      - at least 600 new `function` symbols with `node_kind == "variable_declarator"`;
      - `symbols blast AdminBulkBar` is non-empty.
- [ ] No `could not be evaluated` warning when building `navigator-svelte`.
- [ ] No `sym:` id that exists today changes (compare the id sets of a before and an after
      build of the fixture repo: after is a superset).
- [ ] `docs/` wikitoolkit page documents the `Symbols:` status line, the `component` kind, and
      `uses` in blast.

---

## 6. Codebase Contract

> Verified against `origin/dev` **8bf475842** on 2026-09-28. Paths are relative to
> `packages/ai-parrot/src/parrot/knowledge/wiki/`.

### Verified Imports
```python
from parrot.knowledge.wiki.languages import astgrep, treesitter          # javascript.py:40
from parrot.knowledge.wiki.languages.render import render_outline, structural_enabled  # javascript.py:42
from parrot.knowledge.wiki.symbols import SymbolRecord, SymbolRef, SymbolKind, StructuralOutline
```

### Existing Class Signatures
```python
# symbols.py
class SymbolKind(str, Enum): ...            # :31, last member MOD = "mod" at :53
class SymbolRecord(BaseModel): ...          # :56  (rel_path, language, kind, name, qualname,
                                            #       parent, signature, doc, exported, is_async,
                                            #       start/end_line, start/end_byte, node_kind,
                                            #       decorators, content_hash, depth)
class SymbolRef(BaseModel):                 # :105
    rel: str = Field(pattern=r"^(calls|extends|implements|uses)$")   # :118
class StructuralOutline(BaseModel): ...     # :123 (summary, symbols, refs, imports)

# languages/astgrep.py
def is_available() -> bool:                                   # :74
def supported_language(lang: str) -> bool:                    # :151
class SymbolSpec(BaseModel): ...                              # :562
class RefSpec(BaseModel): ...                                 # :620
class RuleSet(BaseModel): language; aliases; symbols; refs    # :649-668
def extract(src: str, lang: str, rel_path: str, *, max_depth: int = 2) -> StructuralOutline | None:  # :867

# languages/javascript.py
def _extract_script_blocks(source: str, suffix: str) -> tuple[str, str | None]:  # :173
class JavaScriptScanner:
    _last_mode: str | None = None                             # :506
    def outline(self, source: str, rel_path: str) -> LanguageOutline:  # :510
    @property
    def mode(self) -> str:                                    # :755

# languages/base.py
    @property
    @abstractmethod
    def mode(self) -> str:                                    # :118 — docstring lists "ast" | "tree-sitter" | "heuristic"

# languages/render.py
def structural_enabled() -> bool:                             # :45
_JS_RENDERED_KINDS = frozenset({CLASS, FUNCTION, INTERFACE, TYPE, CONST})   # :112

# repo_scan.py
class SymbolResolver:                                         # :903 (3-step deterministic resolution)

# cli.py
async def _ingest_files(..., force: bool = False, force_rel_paths: set[str] | None = None)  # :693-699
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| predictive `mode` | `astgrep.supported_language` | call | `astgrep.py:151` |
| `_structural_gap_warning` | build path, before `_ingest_files` | call | `cli.py:1551`, `cli.py:1816` |
| fingerprint force set | `force_rel_paths` param | union | `cli.py:1552`, `cli.py:1817` |
| `Symbols:` line | status payload | dict key | `cli.py:2129`, `cli.py:2180` |
| `_svelte_component_augment` | seam success branch of `outline` | call | `javascript.py:532-541` |
| `uses` in blast | default relations | tuple | `structural/service.py:44` |
| `uses` in MCP/tool input | `BlastRadiusInput.relations` | Literal | `structural/tools.py:74` |

### Does NOT Exist (Anti-Hallucination)
- ~~`SymbolKind.COMPONENT`~~: added by this spec.
- ~~`SymbolSpec.languages` / `RefSpec.languages`~~: added by this spec.
- ~~A backend-agnostic store meta get/set API~~: only sqlite's private `meta` table exists
  (`store.py:1340`).
- ~~A Svelte ast-grep grammar~~: Svelte is pre-extracted to its `<script>` body.
- ~~Any language emitting `uses` refs today~~: the only mention is the `RefSpec` docstring
  (`astgrep.py:624`).
- ~~Namespace federation in `wikitoolkit symbols`~~: out of scope.

### Edit Sites (Blueprint Anchors)

Verified against: 8bf475842

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `symbols.py` | MODIFY | `    MOD = "mod"` | `symbols.py:53` | 1 |
| `languages/astgrep.py` | MODIFY | `class SymbolSpec(BaseModel):` | `astgrep.py:562` | 1 |
| `languages/astgrep.py` | MODIFY | `class RefSpec(BaseModel):` | `astgrep.py:620` | 1 |
| `languages/javascript.py` | MODIFY | `                structural = astgrep.extract(script_source, ast_grep_lang, rel_path)` | `javascript.py:532` | 1 |
| `languages/javascript.py` | MODIFY | `    def mode(self) -> str:` | `javascript.py:755` | 1 |
| `languages/php.py` | MODIFY | `    def mode(self) -> str:` | `php.py:413` | 1 |
| `languages/rust.py` | MODIFY | `    def mode(self) -> str:` | `rust.py:420` | 1 |
| `languages/perl.py` | MODIFY | `    def mode(self) -> str:` | `perl.py:536` | 1 |
| `languages/render.py` | MODIFY | `_JS_RENDERED_KINDS = frozenset(` | `render.py:112` | 1 |
| `languages/rules/typescript.yaml` | MODIFY | `    rule: { kind: lexical_declaration, inside: { kind: export_statement } }` | `typescript.yaml:67` | 1 |
| `languages/rules/typescript.yaml` | MODIFY | `    scope: { ancestor: [function_declaration, method_definition, class_declaration] }` | `typescript.yaml:77` | 1 |
| `languages/fingerprint.py` | CREATE | — | — | — |
| `structural/service.py` | MODIFY | `_DEFAULT_BLAST_RELATIONS = ("calls", "extends", "implements")` | `service.py:44` | 1 |
| `structural/tools.py` | MODIFY | `    relations: list[Literal["calls", "extends", "implements", "references", "contains"]] \| None = Field(` | `tools.py:74` | 1 |
| `cli.py` | MODIFY | `        if entry is not None and not must_force and not sources.entry_is_stale(entry):` | `cli.py:765` | 1 |
| `cli.py` | MODIFY | `        "structural": {name: s.mode for name, s in all_scanners().items()},` | `cli.py:2129` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Never raise from a scanner: every new path degrades to today's output (the existing
  `except Exception` contract in `outline`).
- Parity first: run `test_outline_parity.py` after each module. Symbol-plane additions must
  never leak into `## API outline`.
- Reuse `force_rel_paths` (the FEAT-532 mechanism); do not add a second invalidation path.
- Log the gap warning once per build, not once per file.

### Known Risks / Gotchas
- **SvelteKit route files share stems** (`+page`, `+layout`, `+error`): hundreds of `component`
  symbols will be named `+page`. Ids stay unique, because concept ids embed `rel_path`. Global
  step-3 resolution is ambiguous for them and correctly yields no edge. Nobody imports route
  files, so no edge is lost. See Q3.
- **One-time re-ingest cost.** The first build after upgrade forces every structural-capable
  file once, because no fingerprint exists yet. On `navigator-svelte` a full `build --force`
  takes under a minute.
- **`mode` is displayed elsewhere.** Grep all consumers of `.mode` before changing its
  semantics. The FEAT-396 docstring on `JavaScriptScanner.mode` says "honest reporting" was the
  goal; predictive reporting keeps that intent.
- **PascalCase tag detection is a regex over markup**, not a parse. It is bounded to tags whose
  name is a known `.svelte` default-import binding, which keeps false positives to zero by
  construction.
- **ast-grep kind names drift between grammar versions.** A kind the wheel does not have is
  already isolated per rule (`astgrep.py:845-864`), so a drift costs recall, not the build.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `ast-grep-py` | `>=0.45` (already the `wiki-structural` extra) | no change; tests needing it are skipped when absent, as today |

---

## 8. Open Questions

- [ ] Q1: Should `wiki-languages` pull `ast-grep-py`? Today a user who installs "the language
  plugins" gets outlines without symbols. This spec keeps them separate, per FEAT-498's "zero new
  core dependencies", and makes the gap loud. *Owner: Jesús*
- [ ] Q2: Where should the extractor fingerprint live: `<storage_dir>/extractor_fingerprint.json`
  (proposed; backend-agnostic, but a database-kind namespace may have no meaningful local
  storage_dir), or a new `get_meta`/`set_meta` pair on `BaseWikiStore` implemented by all three
  backends? *Owner: Jesús*
- [ ] Q3: Component symbol naming for route files. Should it be the bare stem (`+page`,
  proposed), or should the stem be qualified with the parent directory for names starting with
  `+`, so that `lookup` is useful for routes? *Owner: Juan*
- [ ] Q4: Should `symbols lookup|blast` federate across namespaces (the gap found while
  verifying this spec)? Out of scope here; decide whether it becomes its own feature.
  *Owner: Jesús*

---

## 9. Design Research Cross-Check

Status: skipped (spec drafted from a measured investigation; no exploration doc). Run the codex
design seat before approval if the reviewer wants one.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-28 | Juan (via Claude Code) | Initial draft from the navigator-svelte 0-symbols investigation |
