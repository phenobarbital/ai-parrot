---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: ast-grep Structural Plane for wikitoolkit — symbols as first-class wiki nodes

**Feature ID**: FEAT-498
**Date**: 2026-09-02
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

> Input: `sdd/proposals/ast-grep-for-wikitoolkit.brainstorm.md` (Option A,
> accepted) and the underlying design `artifacts/ast/astgrepstructuralplanedesign.md`
> (§1–§6, §9 Sprints 1–2) + probe `artifacts/ast/astgrep_rules_prototype.py`.
> This spec covers **the design's Sprint 1 + Sprint 2 only**. The structural
> search/edit tools (`ast_grep` / `ast_edit`, Sprint 3) and the dev_loop
> wiring (Sprint 4) are follow-up features that consume the contracts fixed
> here (`SymbolRecord`, `sym:` ids, `blast_radius.files`, `content_hash`).

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The LLM wiki (`wikitoolkit build`) knows *files*, not *symbols*. Every source
file becomes one `file:<rel>` page whose body carries a rendered
`## API outline` (plain text lines) and a content head. Consequences:

- **Agents cannot ask "where is `UserService.get_user`?"** — `wiki_query` is
  FTS over title/summary/body, so a symbol name competes with every mention
  of it in prose and unrelated files. There is no exact symbol lookup, no
  byte range, no signature/doc per symbol.
- **No blast radius.** The graph has `contains` (dir → file) and `references`
  (file → file via imports). "Who calls `helper()`?" or "what implements
  `Visitor`?" cannot be answered without grepping the repository — the very
  thing the wiki exists to avoid.
- **Five hand-written walkers drift.** `languages/{python,javascript,php,rust,
  perl}.py` each walk `node.children` by hand (never `tree_sitter.Query`),
  duplicate "find name field / find doc comment / indent under parent", and
  encode extraction rules as Python control flow that cannot be reviewed as
  data or validated with `sg test`.
- **Freshness is per source and hook-driven.** `sources.file_hash` exists but
  `file:` pages carry no hash; if the `post-commit` hook is missed (checkout,
  merge, rebase, dirty tree) a query silently returns stale outlines.

Affected: every wiki consumer — Claude Code via the `wikitoolkit` MCP server,
ai-parrot agents via `LLMWikiToolkit`, `dev_loop` research/QA nodes — and the
developers maintaining five scanners. The follow-up structural edit tool is
only sound if the symbol layer, `calls`/`extends` edges, and a per-file
freshness invariant exist first. This feature is that foundation.

### Goals

- **G1** — Optional declarative structural backend (`ast-grep-py` + one YAML
  rule file per language + fixed extractors) slotted in front of every
  scanner, with **strict byte-parity** of the rendered `## API outline` and
  the full degradation chain (extra absent → tree-sitter walker → stdlib
  heuristic) intact.
- **G2** — Symbols as first-class wiki nodes: `SymbolRecord` model,
  `sym:<rel>#<qualname>` pages (`category="symbol"`), SQLite `symbols` table
  + FTS, edges `defines`, `contains`, `calls`, `extends`, `implements` with
  `provenance` `extracted|inferred`, resolved deterministically (no LLM).
- **G3** — Per-page freshness: `pages.content_hash` (SHA-1, same digest as
  `sources.file_hash`) on `file:` and `sym:` pages; `StructuralService`
  read-repair re-scans stale hit files through the `upsert --changed` path
  before answering.
- **G4** — Three read-only tools over one `StructuralService`:
  `wiki_symbol_lookup`, `wiki_code_outline`, `wiki_blast_radius` — exposed by
  `wikitoolkit mcp`, by `CodeStructuralToolkit` (`tool_prefix="code"`), and
  by the `wikitoolkit symbols` CLI group.
- **G5** — Python `sym:` pages exist **without any extra**: `PythonScanner`
  derives `SymbolRecord`s from stdlib `ast`; ast-grep only enriches them.
- **G6** — Perl via `register_dynamic_language` on the `tree-sitter-perl`
  wheel's `.so`, `kind` rules only, silent fallback to today's walker.

### Non-Goals (explicitly out of scope)

- **No `ast_grep` / `ast_edit` tools, no `EditPlan`/token protocol, no
  writes to the working tree** — Sprint 3 follow-up. Nothing in this feature
  modifies source files.
- **No dev_loop / dev_flow wiring** (`ClaudeCodeDispatcher.mcp_servers`,
  per-node `allowed_tools`, brief enricher) — Sprint 4 follow-up. Do not
  touch `flows/dev_loop/`.
- **No type-based resolution** (LSP). Name-based, deterministic; an ambiguous
  reference produces no edge (brainstorm Option D rejected).
- **No persisted AST.** Only derived facts are stored.
- **No rewrite of the outline format.** Extra symbols the backend sees (TS
  class methods, PHP namespaces) live only in `symbols`/`sym:` pages.
- **No removal of the tree-sitter walkers** in this feature — they remain the
  second tier and the parity oracle (retirement earliest two releases later).
- **No native `symbols` table in ArangoDB / InMemory-OKF** — those backends
  persist `sym:` pages + edges via existing methods and use the
  `BaseWikiStore` default symbol methods over pages (brainstorm resolved).
- **No `tree_sitter.Query` layer and no `code_ast`** (brainstorm Options C
  and design decision 1).
- **No user-overridable rule overlay** in v1 — rules ship as package data
  (see §8).

---

## 2. Architectural Design

### Overview

Two layers are added under `parrot/knowledge/wiki/`: an **extraction**
layer and a **service/tools** layer, joined by the persisted symbol plane.

**Extraction.** `languages/astgrep.py` is an optional seam mirroring
`languages/treesitter.py`: `is_available()` (import of `ast_grep_py`
succeeded), `supported_language(lang)` (built-in whitelist, plus a cached
dynamic-registration attempt for `perl`), `parse(src, lang)` (constructs
`SgRoot` inside a `BaseException` fence — pyo3 panics are `BaseException`),
`RuleSet.load(lang)` (YAML from `languages/rules/<lang>.yaml`, validated at
load), and `extract(src, lang, rel_path) -> StructuralOutline | None`. Each
scanner's `outline()` calls `extract()` first; on `None` it continues with
its current tree-sitter walker or heuristic. Rules are pure data
(`kind`/`inside`/`has`/`not`/`any`/`field`); anything needing logic is one of
a fixed set of named **extractors** implemented once
(`first_docstring`, `leading_comment`, `leading_doc_comment`, `pod_head2`,
`module_docstring`, `first_heading_comment`, `preceding_package`).
`languages/render.py::render_outline(symbols, language)` projects symbols
back to today's outline lines; a per-language parity suite asserts
`outline()` is identical with and without `ast-grep-py`.

**Python exception (resolved in brainstorm).** `PythonScanner` keeps stdlib
`ast` as the source of truth and *always* emits `SymbolRecord`s from it
(line ranges from `lineno`/`end_lineno`, byte offsets computed from the
source). When ast-grep is available it adds `calls` refs and confirms byte
offsets; it never replaces the `ast`-derived symbol list.

**Symbol plane.** `symbols.py` defines `SymbolKind`, `SymbolRecord`,
`SymbolRef`, `StructuralOutline`, `sym_concept_id()`. `repo_scan` turns each
`FileSlice.symbols` into `sym:` pages plus `defines`/`contains` edges and
stamps `content_hash` on the `file:` page; `SymbolResolver` (inside
`build_import_edges()`) resolves `SymbolRef`s to `calls`/`extends`/
`implements` edges in three deterministic steps. `cli._ingest_files` writes
the `sym:` pages **in the same `replace_source_slice()` call as their `file:`
page** (atomic per source) and upserts `symbols` rows. SQLite schema goes to
`"2"`: `pages.content_hash` via `_MIGRATION_COLUMNS`, new `symbols` +
`symbols_fts` tables. `BaseWikiStore` gains `upsert_symbols`, `symbols_for`,
`find_symbols`, `search_symbols_fts`, `page_hashes` — abstract-with-default:
SQLite overrides natively; ArangoDB and InMemory inherit defaults built on
`list_pages(category="symbol")`, `search_fts(category="symbol")` and
`get_page`.

**Service & tools.** `structural/service.py::StructuralService(store, root,
config)` is the only component that touches disk: `lookup()`, `outline()`,
`blast_radius()`, and `_ensure_fresh(rel_paths)` (read-repair: SHA-1 the hit
files, compare with `page_hashes()`, re-scan mismatches via
`scan_repository(rel_paths=…)` + `_ingest_files(force=True)` under
`wiki_write_lock`; if the lock is held, serve stale hits flagged
`stale=True`). `structural/tools.py` wraps it in three `AbstractTool`s named
`wiki_symbol_lookup`, `wiki_code_outline`, `wiki_blast_radius` (resolved:
`wiki_` prefix, consistent with the six existing tools and
`permission_rules()`), created by `create_structural_tools()` and registered
by `create_wiki_mcp_server()`. `structural/toolkit.py::CodeStructuralToolkit`
re-exposes them as `code_symbol_lookup` etc. `cli.py` adds `wikitoolkit
symbols lookup|outline|blast`. `wiki_query` excludes `category="symbol"`
stubs unless `include_symbols=True` (resolved); `wiki_page`/`wiki_related`
accept `sym:` ids because `context._ID_KINDS` gains `sym`.

**Identity.** `sym:<rel>#<qualname>`; a repeated qualname in one file gets a
source-order ordinal suffix `~2`, `~3` … (resolved: the first keeps the clean
id; `~` cannot collide with `#` or qualname characters of the five
languages).

### Component Diagram

```
                     ┌──────────────── wiki plane (SQLite v2 / Arango / OKF) ────────────────┐
                     │ pages: file:<rel> · dir:<rel> · sym:<rel>#<q>[~n]   (+content_hash)     │
                     │ symbols (SQLite only) + symbols_fts                                    │
                     │ edges: contains · references · defines · calls · extends · implements  │
                     └──────────────▲──────────────────────────────────────▲──────────────────┘
        build / upsert --changed    │                                      │  lookup / neighbors / page_hashes
   ┌────────────────────────────────┴────────────┐        ┌────────────────┴───────────────────────┐
   │ EXTRACTION  (repo_scan.build_file_slice)     │        │ structural/service.py::StructuralService │
   │  scanner.outline()                           │        │   lookup() outline() blast_radius()      │
   │   ├─ languages/astgrep.extract()  ← rules/*.yaml       │   _ensure_fresh() = read-repair via      │
   │   │    SgRoot (BaseException fence) + extractors        │   scan_repository(rel_paths) + _ingest_files│
   │   ├─ (python) ast → SymbolRecord, astgrep enriches      └──┬───────────────────┬────────────────┘
   │   └─ fallback: tree-sitter walker → heuristic              │                   │
   │  render_outline(symbols) → byte-identical outline   ┌──────▼──────┐   ┌────────▼────────────────┐
   │  build_import_edges() + SymbolResolver → calls/…    │ structural/ │   │ structural/toolkit.py    │
   └────────────────────────────────────────────────────┘ │ tools.py    │   │ CodeStructuralToolkit    │
                                                          │ wiki_symbol_lookup · wiki_code_outline ·  │ prefix "code"  │
                                                          │ wiki_blast_radius   └─→ mcp_server.py     │ any ai-parrot agent │
                                                          └─────────────┘   └─────────────────────────┘
                                                          cli.py: `wikitoolkit symbols lookup|outline|blast`
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `languages/base.py::LanguageOutline` | extends | `symbols: list[SymbolRecord] = []`, `refs: list[SymbolRef] = []` — additive defaults; every existing scanner stays valid |
| `languages/{python,javascript,php,rust,perl}.py` | modifies | `outline()` tries `astgrep.extract()` first; Python merges `ast` symbols + ast-grep refs; `mode` reports `"ast-grep"` when the seam served the file |
| `languages/treesitter.py` | reuses | Unchanged second tier; `_GRAMMAR_MODULES` is the model for the astgrep whitelist |
| `languages/perl.py::_head2_docs()` / `javascript.py::_extract_script_blocks()` | reuses | `pod_head2` extractor; Svelte `<script>` fed to `typescript`/`javascript` grammar |
| `repo_scan.py` | modifies | `FileSlice.symbols/refs`, `RepoScan.symbol_records/symbol_edges`, `content_hash` on file record, `SymbolResolver` in `build_import_edges()` |
| `store.py` (`BaseWikiStore`, `SQLiteWikiStore`) | modifies | `SCHEMA_VERSION="2"`, `_MIGRATION_COLUMNS["pages"] += ("content_hash","TEXT")`, `symbols`/`symbols_fts` DDL, five new methods (abstract-with-default), `replace_source_slice` clears `symbols` rows for the source, `stats()` adds `symbols` |
| `arango_store.py`, `file_store.py` | modifies (light) | Persist/read `content_hash` as a page field / frontmatter key; inherit default symbol methods |
| `sources.py::SourceCollectionManager._compute_hash` | reuses | Same SHA-1 for `content_hash`; exposed as a module-level `sha1_of_text()` helper in `symbols.py` for in-memory hashing |
| `cli.py::_ingest_files` | modifies | Per-slice and bulk paths include `sym:` records + symbol edges; `upsert_symbols()` after pages |
| `cli.py` click group `wiki` | extends | New `wiki.group(name="symbols")` with `lookup`, `outline`, `blast`; `stats` prints symbol counts and structural mode per language |
| `context.py::_ID_KINDS` | modifies | += `sym` so `split_namespaced_id`/`stub_line` treat `sym:` as a page id |
| `tools.py` | extends | `WikiQueryInput.include_symbols: bool = False`; `create_structural_tools(store, root, config)` |
| `mcp_server.py::create_wiki_mcp_server` | extends | `server.register_tools(create_structural_tools(read_store, root, config))` |
| `toolkit.py` pattern (`LLMWikiToolkit`) | model for | `CodeStructuralToolkit(AbstractToolkit)`, `tool_prefix="code"` |
| `claude_code/assets.py::PERMISSION_RULES` | extends | `mcp__wikitoolkit__wiki_symbol_lookup`, `…wiki_code_outline`, `…wiki_blast_radius` (shared file with FEAT-495 — additive hunk) |
| `graphindex/schema.py::EdgeKind` | extends | `CALLS = "calls"`, `IMPLEMENTS = "implements"` so the `sync_graph` mirror stays 1:1 |
| `project.py::WikiProjectConfig` | extends | `symbol_depth: int = 2`, `structural_backend: bool = True` (kill switch) |
| `packages/ai-parrot/pyproject.toml` | extends | `wiki-structural = ["ast-grep-py>=0.45"]`; `wiki` meta-extra includes it; `[tool.setuptools.package-data] "parrot.knowledge.wiki.languages.rules" = ["*.yaml"]` |

### Data Models

```python
# parrot/knowledge/wiki/symbols.py  (new)
class SymbolKind(str, Enum):
    MODULE="module"; CLASS="class"; INTERFACE="interface"; TRAIT="trait"; ENUM="enum"
    STRUCT="struct"; IMPL="impl"; FUNCTION="function"; METHOD="method"; CONST="const"
    TYPE="type"; PACKAGE="package"; ROLE="role"; FIELD="field"; ATTRIBUTE="attribute"; MOD="mod"

class SymbolRecord(BaseModel):
    rel_path: str                 # POSIX, relative to root
    language: str                 # scanner name: python|javascript|php|rust|perl
    kind: SymbolKind
    name: str                     # local identifier
    qualname: str                 # "UserService.get_user" | "App\\Models\\User::getFullName" | "Parser::new"
    parent: str | None = None     # container qualname
    signature: str = ""           # params (+ return) as written
    doc: str = ""                 # first doc line
    exported: bool = False        # export / pub / public
    is_async: bool = False
    start_line: int; end_line: int         # 1-based inclusive
    start_byte: int; end_byte: int         # byte offsets in the file
    node_kind: str = ""           # tree-sitter kind that produced it ("" for ast-derived)
    decorators: list[str] = Field(default_factory=list)
    content_hash: str             # sha1 of the node text
    depth: int = 1                # 1 = top-level, 2 = direct member …

class SymbolRef(BaseModel):
    src_qualname: str
    rel: Literal["calls", "extends", "implements", "uses"]
    target_text: str              # as written: "BaseService", "helper", "self.repo.get"
    line: int

class StructuralOutline(BaseModel):
    summary: str = ""
    symbols: list[SymbolRecord] = Field(default_factory=list)
    refs: list[SymbolRef] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)   # same contract as today → resolve_import()

def sym_concept_id(rel_path: str, qualname: str, ordinal: int = 1) -> str:
    """'sym:<rel>#<qualname>' — ordinal ≥ 2 appends '~<n>' (source order)."""
def sha1_of_text(text: str) -> str
```

```python
# parrot/knowledge/wiki/languages/base.py  (extended)
class LanguageOutline(BaseModel):
    summary: str = ""
    outline: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    symbols: list[SymbolRecord] = Field(default_factory=list)   # NEW
    refs: list[SymbolRef] = Field(default_factory=list)         # NEW
```

```sql
-- store.py: SCHEMA_VERSION = "2"
-- _MIGRATION_COLUMNS["pages"] += ("content_hash", "TEXT")   (idempotent ALTER, like origin/asserted_by)
CREATE TABLE IF NOT EXISTS symbols (
  concept_id TEXT PRIMARY KEY,              -- sym:<rel>#<qualname>[~n]
  rel_path TEXT NOT NULL, language TEXT NOT NULL, kind TEXT NOT NULL,
  name TEXT NOT NULL, qualname TEXT NOT NULL, parent TEXT,
  signature TEXT NOT NULL DEFAULT '', doc TEXT NOT NULL DEFAULT '',
  exported INTEGER NOT NULL DEFAULT 0, is_async INTEGER NOT NULL DEFAULT 0, depth INTEGER NOT NULL DEFAULT 1,
  start_line INTEGER, end_line INTEGER, start_byte INTEGER, end_byte INTEGER,
  node_kind TEXT, content_hash TEXT, source_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbols_name   ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_path   ON symbols(rel_path);
CREATE INDEX IF NOT EXISTS idx_symbols_source ON symbols(source_id);
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
  concept_id UNINDEXED, name, qualname, doc, signature, tokenize = 'unicode61'
);
```

```yaml
# parrot/knowledge/wiki/languages/rules/<lang>.yaml — schema (validated at load)
language: typescript            # ast-grep language name
aliases: [tsx, javascript]      # other ast-grep names served by this file
summary: first_heading_comment  # extractor name
symbols:
  - id: class                   # → SymbolKind
    rule: { kind: class_declaration }             # ast-grep Rule (evaluated as find_all({"rule": …}))
    name: { field: name }                         # field | path: [kind, …] | text
    signature: { field: type_parameters }         # optional
    doc: leading_comment                          # extractor | none
    parent: { ancestor: class_declaration, name: { field: name } }   # optional
    exported: { inside: export_statement }        # inside <kind> | has <kind> | always | never
    async: { has: async }                         # optional
    depth: 1                                      # 1 top-level | 2 member
refs:
  - rel: calls
    rule: { kind: call_expression }
    target: { field: function }
    scope: { ancestor: [function_declaration, method_definition, class_declaration] }
  - rel: extends
    rule: { kind: class_heritage }
    target: { each: identifier }
imports:
  - { rule: { kind: import_statement } }
```

### New Public Interfaces

```python
# parrot/knowledge/wiki/languages/astgrep.py  (new; never raises)
def is_available() -> bool
def supported_language(lang: str) -> bool          # whitelist ∪ cached dynamic registration (perl)
def parse(src: str, lang: str) -> "SgRoot | None"  # BaseException fence around SgRoot only
class RuleSet(BaseModel):  language: str; aliases: list[str]; summary: str; symbols: list[SymbolSpec]; refs: list[RefSpec]; imports: list[ImportSpec]
    @classmethod
    def load(cls, lang: str) -> "RuleSet | None"   # cached; validates extractor names + required keys
def extract(src: str, lang: str, rel_path: str, *, max_depth: int = 2) -> StructuralOutline | None
EXTRACTORS: dict[str, Callable[["SgNode"], str]]

# parrot/knowledge/wiki/languages/render.py  (new)
def render_outline(symbols: list[SymbolRecord], language: str) -> list[str]   # byte-parity projection

# parrot/knowledge/wiki/repo_scan.py  (extended)
class FileSlice(BaseModel):   ... symbols: list[SymbolRecord] = []; refs: list[SymbolRef] = []
class RepoScan(BaseModel):    ... symbol_records: list[WikiPageRecord] = []; symbol_edges: list[tuple[str, str, str, str]] = []
class SymbolResolver:
    def __init__(self, files: list[FileSlice], reference_edges: list[tuple[str, str, str]]) -> None
    def resolve(self) -> list[tuple[str, str, str, str]]   # (src_sym, dst_sym, rel, provenance)

# parrot/knowledge/wiki/store.py  (BaseWikiStore — abstract-with-default)
async def upsert_symbols(self, symbols: list[SymbolRecord], source_id: str | None = None) -> int   # default: no-op (pages already hold them)
async def symbols_for(self, rel_path: str) -> list[SymbolRecord]                    # default: list_pages(category="symbol") filtered by node_id prefix
async def find_symbols(self, name: str | None = None, qualname_prefix: str | None = None, kind: str | None = None,
                       language: str | None = None, path_prefix: str | None = None, limit: int = 50) -> list[SymbolRecord]
async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]  # default: search_fts(category="symbol")
async def page_hashes(self, concept_ids: list[str]) -> dict[str, str | None]          # default: get_page(include_body=False)["content_hash"]

# parrot/knowledge/wiki/structural/service.py  (new)
class StructuralService:
    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> None
    async def lookup(self, query: str, *, kind: SymbolKind | None = None, language: str | None = None,
                     path_prefix: str | None = None, limit: int = 20) -> SymbolLookupOutput
    async def outline(self, target: str, *, depth: int = 2, include_source: bool = False) -> CodeOutlineOutput
    async def blast_radius(self, symbol: str, *, relations: list[str] = ["calls","extends","implements"],
                           depth: int = 2, include_inferred: bool = True, include_tests: bool = True) -> BlastRadiusOutput
    async def _ensure_fresh(self, rel_paths: list[str]) -> list[str]   # returns repaired files; [] when lock busy

# parrot/knowledge/wiki/structural/tools.py  (new; AbstractTool, args_schema Pydantic)
class SymbolLookupInput(BaseModel):  query: str; kind: SymbolKind | None; language: str | None; path_prefix: str | None; limit: int = Field(20, le=100); namespace: str | None
class SymbolHit(BaseModel):          symbol_id: str; rel_path: str; qualname: str; kind: SymbolKind; signature: str; doc: str; start_line: int; end_line: int; exported: bool; score: float; stale: bool = False
class SymbolLookupOutput(BaseModel): hits: list[SymbolHit]; total: int; repaired_files: list[str] = []
class CodeOutlineInput(BaseModel):   target: str; depth: int = Field(2, ge=1, le=4); include_source: bool = False; namespace: str | None
class CodeOutlineOutput(BaseModel):  target: str; language: str; symbols: list[SymbolHit]; source: str | None = None; truncated: bool = False
class BlastRadiusInput(BaseModel):   symbol: str; relations: list[Literal["calls","extends","implements","references","contains"]]; depth: int = Field(2, ge=1, le=5); include_inferred: bool = True; include_tests: bool = True; namespace: str | None
class ImpactedSymbol(BaseModel):     symbol: SymbolHit; via: str; distance: int; provenance: str
class BlastRadiusOutput(BaseModel):  root: SymbolHit; impacted: list[ImpactedSymbol]; files: list[str]; truncated: bool
class WikiSymbolLookupTool(AbstractTool):  name = "wiki_symbol_lookup"
class WikiCodeOutlineTool(AbstractTool):   name = "wiki_code_outline"
class WikiBlastRadiusTool(AbstractTool):   name = "wiki_blast_radius"
def create_structural_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> list[AbstractTool]

# parrot/knowledge/wiki/structural/toolkit.py  (new)
class CodeStructuralToolkit(AbstractToolkit):
    tool_prefix: str = "code"
    async def symbol_lookup(...) / async def code_outline(...) / async def blast_radius(...)   # delegate to StructuralService

# parrot/knowledge/wiki/tools.py  (extended)
class WikiQueryInput(BaseModel): ... include_symbols: bool = Field(default=False, description="Include sym: pages in results")
```

`wikitoolkit` CLI (click group `wiki`, cli.py:1071):
`wikitoolkit symbols lookup <query> [--kind] [--language] [--path] [--limit] [--json]`,
`wikitoolkit symbols outline <file|sym-id> [--depth] [--source]`,
`wikitoolkit symbols blast <sym-id|qualname> [--rel …] [--depth] [--no-inferred]`.
`wikitoolkit stats` adds `symbols: N` and `structural: {python: ast, php: ast-grep, perl: tree-sitter, …}`.

---

## 3. Module Breakdown

> Modules map to Task Artifacts. Order = dependency order.

### Module 1: Symbol models and id grammar
- **Path**: `parrot/knowledge/wiki/symbols.py` (new); `languages/base.py`; `context.py`; `repo_scan.py` (`FileSlice`/`RepoScan` fields only); `project.py` (`symbol_depth`, `structural_backend`); `graphindex/schema.py` (`EdgeKind.CALLS/IMPLEMENTS`)
- **Responsibility**: `SymbolKind`, `SymbolRecord`, `SymbolRef`, `StructuralOutline`, `sym_concept_id()` with `~n` ordinals, `sha1_of_text()`; additive fields on `LanguageOutline`/`FileSlice`/`RepoScan`; `_ID_KINDS` += `sym`; config keys; enum members. Pure models — no behaviour change anywhere.
- **Depends on**: nothing.

### Module 2: ast-grep seam, rule loader, extractors, optional extra
- **Path**: `parrot/knowledge/wiki/languages/astgrep.py` (new); `packages/ai-parrot/pyproject.toml` (extra `wiki-structural`, `wiki` meta-extra, package-data for `languages/rules/*.yaml`)
- **Responsibility**: `is_available`, `supported_language` (whitelist + Perl dynamic registration locating `tree_sitter_perl/_binding*.so`, cached True/False, DEBUG log), `parse` with `BaseException` fence, `RuleSet` Pydantic schema + `load()` with validation, the fixed `EXTRACTORS`, `extract()` honouring `max_depth`, per-(language, rule-id) once-only logging of `RuntimeError: cannot get matcher`. Never raises.
- **Depends on**: Module 1.

### Module 3: Outline renderer and scanner wiring
- **Path**: `parrot/knowledge/wiki/languages/render.py` (new); `languages/{javascript,php,rust,perl,python}.py`
- **Responsibility**: `render_outline(symbols, language)` reproducing each scanner's current outline lines exactly (indent under parent, `: <doc>` suffix, `export`/`pub` prefix, `impl X:` header, Perl `package`/`has`/`field` lines); each scanner's `outline()` tries `astgrep.extract()` first (honouring `config.structural_backend`), falls back unchanged; `mode` reports `"ast-grep"` when served by the seam. **Python**: symbols always from `ast` (`lineno`/`end_lineno`, byte offsets via cumulative line lengths, decorators, `async`, docstring, signature via `ast.unparse` of args/returns); ast-grep adds `calls` refs only. Parity fixture `force_no_astgrep` (monkeypatch `astgrep.is_available → False`) modelled on `force_heuristic`.
- **Depends on**: Module 2.

### Module 4: Rule files per language (one task each; parallel-safe inside the worktree)
- **Path**: `parrot/knowledge/wiki/languages/rules/{typescript,php,rust,perl,python}.yaml`
- **Responsibility**: Encode the design §4.3 mapping tables. `typescript.yaml` (aliases `tsx`, `javascript`; Svelte `<script>` fed by the scanner) — class, function, method (depth 2, not rendered), interface, type alias, exported const, imports, `calls`, `extends`/`implements` via `class_heritage`. `php.yaml` — class/interface/trait/enum, method, function, `namespace_definition` as qualname prefix (not rendered), `namespace_use_declaration`, calls (`function_call_expression`, `member_call_expression`, `scoped_call_expression`), `base_clause`/`class_interface_clause`. `rust.yaml` — pub struct/enum/trait/mod, impl (`field: type`), fn (pub or inside impl), `use_declaration`, `call_expression`, `impl_item.field: trait` → `implements`; `leading_doc_comment` skips `attribute_item`. `perl.yaml` — **`kind` rules only**: package/class/role, sub/method with `preceding_package` parent extractor, `has`/`field` via `expression_statement` + `regex`, `use_statement`/`require_expression`; `pod_head2` doc. `python.yaml` — **refs and imports only** (`call` with `field: function`, `class_definition.superclasses` → `extends`); symbols come from `ast`. Each file ships with its parity test and an `astgrep`-present fixture test asserting the design §4.4 symbol table.
- **Depends on**: Module 3.

### Module 5: Store schema v2 and symbol methods
- **Path**: `parrot/knowledge/wiki/store.py`; `arango_store.py`; `file_store.py`; `federation.py` (delegate new read methods to the local store; foreign namespaces via default page-based path)
- **Responsibility**: `SCHEMA_VERSION="2"`; `content_hash` ALTER via `_MIGRATION_COLUMNS`; `symbols`/`symbols_fts` DDL in `WIKI_SCHEMA_SQL` and `_SCHEMA_TABLES`; `WikiPageRecord.content_hash: str | None = None` read/written by all three backends; `BaseWikiStore` five new methods with page-based defaults; SQLite native implementations; `replace_source_slice()` deletes `symbols` rows by `source_id` in the same transaction; `stats()` adds `symbols`; `search_fts` unchanged (symbol exclusion is done in the tool — see §7).
- **Depends on**: Module 1.

### Module 6: Symbol pages, edges, content_hash, SymbolResolver, ingest
- **Path**: `parrot/knowledge/wiki/repo_scan.py`; `cli.py::_ingest_files` and the `build` bulk path
- **Responsibility**: `build_file_slice()` stamps `content_hash` on the file record and carries `symbols`/`refs`; `build_symbol_pages(slice) -> (records, edges)` producing `sym:` `WikiPageRecord`s (`category="symbol"`, `node_id=rel_path`, `title=qualname`, `summary=doc`, body = signature + doc + `L<start>-<end>` + node excerpt ≤ 2 000 chars, `content_hash`=node hash, `source_id` filled by ingest) and `defines`/`contains` edges; `SymbolResolver` in `build_import_edges()` (same file → import-reachable files via `references` edges → globally unique name; `extracted`/`extracted`/`inferred`; none → no edge); `_ingest_files` passes `[file_record, *sym_records]` and the file's symbol edges into `replace_source_slice()` (and into the bulk `upsert_pages`/`add_edges` path), then `upsert_symbols()`. Depth filter `config.symbol_depth`.
- **Depends on**: Modules 3, 5.

### Module 7: StructuralService with read-repair
- **Path**: `parrot/knowledge/wiki/structural/__init__.py`, `structural/service.py` (new)
- **Responsibility**: `lookup()` (exact qualname → exact name → `search_symbols_fts`; ranks and caps), `outline()` (`file:` / `sym:` / relative path; depth; optional capped source read from disk, root-confined via `Path.resolve()` + `is_relative_to`), `blast_radius()` (iterative `store.neighbors(direction="in")` over the requested `rel`s from `sym:` seeds, depth-bounded, dedup, `files` = sorted set of `rel_path`s, `include_tests` filter by `tests/` path prefix, `provenance` from edge), `_ensure_fresh()` (SHA-1 of hit files vs `page_hashes()`; stale → `scan_repository(root, rel_paths=stale)` + `_ingest_files(force=True)` under `wiki_write_lock(timeout=0)`; lock busy → return `[]` and mark hits `stale=True`; deleted file → drop slice like `upsert --changed`). Only module that reads the working tree.
- **Depends on**: Modules 5, 6.

### Module 8: Tools, toolkit, MCP registration, permissions, `wiki_query` opt-in
- **Path**: `structural/tools.py`, `structural/toolkit.py` (new); `tools.py`; `mcp_server.py`; `claude_code/assets.py`
- **Responsibility**: three `AbstractTool`s with Pydantic `args_schema`, `namespace` argument (`_scoped_store` like the existing tools; read-repair only for the local namespace), token-budgeted output via `pack_results`/`truncate_to_tokens`; `create_structural_tools()`; `CodeStructuralToolkit` delegating to one `StructuralService`; `create_wiki_mcp_server()` registers the new tools; `PERMISSION_RULES` += three `mcp__wikitoolkit__wiki_*` entries; `WikiQueryInput.include_symbols` (default False → `WikiQueryTool` drops `category=="symbol"` results after over-fetching `limit*3`).
- **Depends on**: Module 7.

### Module 9: CLI, stats, docs
- **Path**: `cli.py` (`wiki.group(name="symbols")`, `stats`); `docs/wiki/` (or the existing wikitoolkit docs location); `claude_code/assets.py::CLAUDE_MD_SECTION` (one paragraph on symbol tools)
- **Responsibility**: `wikitoolkit symbols lookup|outline|blast` (human + `--json`), `stats` symbol counts and structural mode per language, install docs for `ai-parrot[wiki-structural]`, migration note (first `build` after upgrade populates symbols; old pages untouched).
- **Depends on**: Module 8.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_sym_concept_id_plain_and_ordinal` | 1 | `sym:a/b.py#X` for ordinal 1, `sym:a/b.py#X~2` for 2; `~` never appears in a clean id |
| `test_language_outline_defaults_backward_compatible` | 1 | `LanguageOutline(summary=…, outline=[…])` still constructs; `symbols == []` |
| `test_split_namespaced_id_accepts_sym` | 1 | `context.split_namespaced_id("ns::sym:a.py#X")` → `("ns", "sym:a.py#X")` |
| `test_edgekind_has_calls_and_implements` | 1 | enum members exist with string values `"calls"`, `"implements"` |
| `test_astgrep_unavailable_returns_none` | 2 | `is_available()` False (monkeypatched import) → `extract()` is `None`, no log noise |
| `test_astgrep_unsupported_language_never_builds_sgroot` | 2 | `supported_language("cobol")` False; `SgRoot` not called (spy) |
| `test_astgrep_panic_fence` | 2 | monkeypatch whitelist to admit an unregistered language → `parse()` returns `None`; process survives (`PanicException` caught) — skipped when `ast_grep_py` absent |
| `test_astgrep_perl_dynamic_registration` | 2 | with wheel present: `supported_language("perl")` True and `find_all(kind="package_statement")` matches; with `.so` path monkeypatched to missing → False, cached, DEBUG log once |
| `test_ruleset_load_validates_schema` | 2 | unknown extractor name / missing `rule` key → `RuleSet.load` returns `None` + one WARNING; valid file loads and caches |
| `test_extract_bad_kind_is_isolated` | 2 | a rule with a nonexistent `kind` logs once and other rules still produce symbols |
| `test_metavar_join_filters_anonymous_nodes` | 2 | helper used by extractors/refs joins only `is_named()` nodes (`"1, b=2"`, never `"1, ,, b=2"`) |
| `test_render_outline_parity_<lang>` | 3 | For each of `typescript, javascript, svelte, php, rust, perl, python` fixtures: `outline()` with ast-grep == `outline()` with `force_no_astgrep` (`outline`, `summary`, `imports` identical) |
| `test_python_symbols_without_extra` | 3 | `force_no_astgrep`: `PythonScanner.outline().symbols` non-empty with correct `start_byte/end_byte`, `is_async`, `decorators`, `depth` |
| `test_scanner_mode_reports_ast_grep` | 3 | `mode` is `"ast-grep"` only when the seam served the last file; `"ast"` for Python always |
| `test_rules_<lang>_symbol_table` | 4 | Symbols extracted from the design §4.4 samples match kind/name/parent/exported/doc/depth (per language file) |
| `test_rules_perl_kind_only` | 4 | `perl.yaml` contains no `pattern:` keys (schema-level assertion) |
| `test_rules_python_has_no_symbol_rules` | 4 | `python.yaml` has `refs`/`imports` only |
| `test_schema_v2_migration_from_v1` | 5 | open a v1 `wiki.db` fixture → `content_hash` column, `symbols`, `symbols_fts` exist; existing pages intact; `SCHEMA_VERSION` meta `"2"` |
| `test_symbol_methods_every_backend` | 5 | `upsert_symbols`/`symbols_for`/`find_symbols`/`search_symbols_fts`/`page_hashes` run in `test_store.py` against SQLite, InMemory (and Arango when available) with equivalent results |
| `test_replace_source_slice_clears_symbols` | 5 | re-ingesting a source removes its old `symbols` rows and `sym:` pages atomically |
| `test_stats_includes_symbols` | 5 | `stats()["symbols"]` present in every backend |
| `test_build_file_slice_sets_content_hash` | 6 | `record.content_hash == sha1(file bytes)`; equals `SourceCollectionManager._compute_hash` for the same file |
| `test_symbol_pages_and_defines_edges` | 6 | one `sym:` page per symbol ≤ depth, `defines` file→sym, `contains` parent→member, `source_id` propagated by ingest |
| `test_symbol_resolver_three_steps` | 6 | same-file → `extracted`; import-reachable → `extracted`; globally unique → `inferred`; ambiguous → no edge |
| `test_symbol_depth_config` | 6 | `symbol_depth=1` persists no methods; `=3` persists nested functions |
| `test_duplicate_qualname_ordinals_stable` | 6 | two `impl Parser` blocks → `#Parser` and `#Parser~2`; re-scan yields identical ids |
| `test_lookup_ranking` | 7 | exact qualname beats exact name beats FTS; `limit` respected |
| `test_read_repair_rescans_stale_file` | 7 | modify a file on disk without upsert → `lookup()` returns fresh symbols, `repaired_files == [rel]`, `content_hash` updated |
| `test_read_repair_lock_busy_serves_stale` | 7 | hold `wiki_write_lock` → hits returned with `stale=True`, `repaired_files == []`, no write attempted |
| `test_read_repair_deleted_file_drops_slice` | 7 | delete file → its `file:`/`sym:` pages and `symbols` rows removed |
| `test_outline_confined_to_root` | 7 | `outline("../etc/passwd")` and absolute paths outside root → error result, no read |
| `test_blast_radius_files_and_provenance` | 7 | `files` is the sorted union of impacted `rel_path`s; `include_inferred=False` drops inferred; `include_tests=False` drops `tests/` |
| `test_tool_names_and_schemas` | 8 | tool names exactly `wiki_symbol_lookup`, `wiki_code_outline`, `wiki_blast_radius`; `args_schema` matches §2 models; `namespace` accepted |
| `test_wiki_query_excludes_symbols_by_default` | 8 | FTS hit on a `sym:` page hidden unless `include_symbols=True` |
| `test_code_structural_toolkit_prefix` | 8 | `CodeStructuralToolkit().get_tools()` names are `code_symbol_lookup` etc.; delegate to the same service instance |
| `test_permission_rules_include_structural_tools` | 8 | `PERMISSION_RULES` contains the three `mcp__wikitoolkit__wiki_*` entries |
| `test_cli_symbols_lookup_json` | 9 | `wikitoolkit symbols lookup helper --json` prints `SymbolLookupOutput` JSON |
| `test_stats_reports_structural_mode` | 9 | `wikitoolkit stats` shows per-language mode |

### Integration Tests

| Test | Description |
|---|---|
| `test_polyglot_build_produces_symbols` | Extends `test_polyglot_integration.py`: `wikitoolkit build` on the polyglot fixture repo yields `sym:` pages for every language, `defines`/`contains`/`calls` edges, `content_hash` on every `file:` page; identical `## API outline` bodies with and without ast-grep |
| `test_mcp_server_registers_nine_tools` | `create_wiki_mcp_server(root)` exposes the six wiki tools + three structural tools; `wiki_symbol_lookup` round-trips over the stdio adapter |
| `test_upsert_changed_refreshes_symbols` | `upsert --changed` after a commit renaming a function: old `sym:` gone, new present, dangling `calls` reported by `broken_edges()` until dependents re-scan |
| `test_end_to_end_lookup_blast_repair` | lookup → blast_radius → edit file on disk → lookup again shows `stale`-free fresh result with `repaired_files` |
| `test_no_extra_installed_is_noop` | Full build with `ast_grep_py` import blocked: identical pages/edges to the pre-feature build except Python `sym:` pages and `content_hash` |

### Test Data / Fixtures

```python
# tests/knowledge/wiki/languages/conftest.py — add beside `force_heuristic` (line 11)
@pytest.fixture
def force_no_astgrep(monkeypatch):
    """Pretend ast-grep-py is not installed so the walker/heuristic tiers run."""
    from parrot.knowledge.wiki.languages import astgrep
    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    astgrep.RuleSet.load.cache_clear()
    yield

requires_astgrep = pytest.mark.skipif(not _has_astgrep(), reason="ast-grep-py not installed")

# Design §4.4 samples (typescript/php/rust/python/perl) from artifacts/ast/astgrep_rules_prototype.py:6-65
# become tests/knowledge/wiki/languages/fixtures/structural/<lang>.<ext>

# tests/knowledge/wiki/fixtures/wiki_v1.db — a SCHEMA_VERSION "1" plane with 3 pages, 2 edges (migration test)
```

CI note: the test job that installs `ai-parrot[wiki-languages]` must also
install `ai-parrot[wiki-structural]` so the `requires_astgrep` tests run at
least once; the default job keeps exercising the fallback tiers.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC1 Parity** — for every language fixture, `outline()`, `summary` and `imports` are byte-identical with and without `ast-grep-py` (`pytest tests/knowledge/wiki/languages -v` passes in both CI jobs).
- [ ] **AC2 No-extra no-op** — a full `wikitoolkit build` without `ast-grep-py` produces the same `file:`/`dir:` pages and `references`/`contains` edges as before this feature, plus Python `sym:` pages and `content_hash` only.
- [ ] **AC3 Python from `ast`** — Python `sym:` pages, `defines`/`contains` edges and byte offsets exist with no optional extra installed.
- [ ] **AC4 Panic fence** — an unregistered/unsupported language never constructs `SgRoot`; a forced panic is caught as `BaseException` and returns `None`; the MCP server process survives (test + manual `wikitoolkit mcp` smoke).
- [ ] **AC5 Perl dynamic** — with `tree-sitter-perl` installed, Perl symbols come from ast-grep `kind` rules; with the `.so` missing, `PerlScanner` falls back to today's walker with a single DEBUG line; `perl.yaml` contains no `pattern:` rules.
- [ ] **AC6 Schema v2** — opening a v1 `wiki.db` migrates idempotently (ALTER `content_hash`, CREATE `symbols`, `symbols_fts`); no page data is rewritten; `SCHEMA_VERSION == "2"`.
- [ ] **AC7 Backends** — SQLite implements the five symbol methods natively; ArangoDB and InMemory pass the same `test_store.py` cases via the default page-based implementations; `content_hash` persists in all three.
- [ ] **AC8 Atomic slice** — `sym:` pages and `symbols` rows for a source are replaced in the same `replace_source_slice()` transaction as the `file:` page; no duplicates after repeated builds.
- [ ] **AC9 Resolver** — `calls`/`extends`/`implements` edges carry `provenance` `extracted` (steps 1–2) or `inferred` (step 3); ambiguous targets produce no edge; no LLM call anywhere in extraction or resolution.
- [ ] **AC10 Ids** — `sym:<rel>#<qualname>` for the first occurrence, `~2`, `~3` … for repeats in source order; ids stable across re-scans of unchanged files; `_ID_KINDS` accepts `sym` (namespaced ids work in `wiki_page`/`wiki_related`).
- [ ] **AC11 Depth** — default `symbol_depth=2` persists top-level declarations and direct members only; configurable via `WikiProjectConfig`.
- [ ] **AC12 Read-repair** — a `wiki_symbol_lookup` whose hit file changed on disk re-scans only that file before answering and reports it in `repaired_files`; when `wiki_write_lock` is held it returns `stale=True` without blocking or writing.
- [ ] **AC13 Tools** — `wikitoolkit mcp` registers exactly `wiki_symbol_lookup`, `wiki_code_outline`, `wiki_blast_radius` in addition to the existing six; `CodeStructuralToolkit` exposes `code_symbol_lookup`, `code_outline`, `code_blast_radius` (method names `symbol_lookup`, `outline`, `blast_radius` — see §7 naming note) over the same `StructuralService`; `PERMISSION_RULES` lists the three MCP names.
- [ ] **AC14 Read-only** — no tool, service or CLI command in this feature writes to any file outside `.parrot/` (asserted by a test that snapshots the fixture repo tree before/after every tool call).
- [ ] **AC15 `blast_radius.files`** — output includes the sorted file set of impacted symbols and honours `include_inferred` / `include_tests`; outputs are token-budgeted (no whole-file dumps).
- [ ] **AC16 `wiki_query` opt-in** — `sym:` stubs are excluded by default and included with `include_symbols=True`.
- [ ] **AC17 Extras** — `pip install "ai-parrot[wiki-structural]"` pulls `ast-grep-py>=0.45`; `ai-parrot[wiki]` includes it; rule YAML files are installed as package data (verified in a wheel build).
- [ ] **AC18 Quality gates** — `pytest tests/knowledge/wiki -v` passes; `ruff` and `mypy` clean on new/changed files; Google docstrings + type hints on every new public symbol; `self.logger`/module logger, no `print`.
- [ ] **AC19 Docs** — install/migration notes and the three tools documented; `CLAUDE_MD_SECTION` mentions symbol lookup.
- [ ] **AC20 No breaking changes** — every new model field has a default; existing `create_wiki_tools()`, `create_wiki_mcp_server()`, `scan_repository()` signatures unchanged (new keyword-only parameters allowed).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified on `dev` @ `692cb0fce` (2026-09-02); `git diff d46d2d57e..HEAD` over
> `parrot/knowledge`, `parrot/tools`, `parrot/mcp`, `pyproject.toml`,
> `tests/knowledge/wiki` is empty, so the brainstorm's line numbers hold.
> All paths relative to `packages/ai-parrot/src/parrot/` unless noted.

### Verified Imports
```python
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner   # languages/__init__.py:14
from parrot.knowledge.wiki.languages import scanner_for, all_scanners, scanned_suffixes, set_scan_root, get_scan_root  # languages/__init__.py:21-29
from parrot.knowledge.wiki.languages import treesitter                              # tests/knowledge/wiki/languages/conftest.py (monkeypatch target)
from parrot.knowledge.wiki.languages.treesitter import get_parser                   # treesitter.py:64
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, SQLiteWikiStore, estimate_tokens  # store.py:332/224/488/172
from parrot.knowledge.wiki.repo_scan import FileSlice, RepoScan, scan_repository, build_file_slice, build_import_edges, file_concept_id, dir_concept_id, is_wiki_relevant, is_inside_wiki_bundle, DEFAULT_EXCLUDE_DIRS
from parrot.knowledge.wiki.sources import SourceCollectionManager                    # sources.py:107
from parrot.knowledge.wiki.tools import create_wiki_tools, WikiQueryTool, WikiQueryInput   # tools.py:541/155/96
from parrot.knowledge.wiki.context import split_namespaced_id, pack_results, truncate_to_tokens, DEFAULT_BUDGET_TOKENS  # context.py:54/203/272/108
from parrot.knowledge.wiki.project import load_effective_config, WikiProjectConfig, find_project_root, wiki_write_lock   # project.py:813/~400/625/65
from parrot.knowledge.graphindex.schema import EdgeKind                             # graphindex/schema.py:64
from parrot.tools.abstract import AbstractTool, ToolResult                          # tools/abstract.py:281/250
from parrot.tools.toolkit import AbstractToolkit                                    # tools/toolkit.py:206
from parrot.mcp.local_server import StdioMCPServer                                  # mcp/local_server.py:36 (mcp_server.py imports it lazily under redirect_stdout)
from parrot.mcp.adapter import MCPToolAdapter                                       # mcp/adapter.py:8
import tree_sitter_perl   # 1.2.1 installed; dir contains `_binding.abi3.so` exporting `T tree_sitter_perl` (nm verified)
# NOT importable in the project venv today: `ast_grep_py` (to be added by extra `wiki-structural`)
```

### Existing Class Signatures
```python
# languages/base.py
class LanguageOutline(BaseModel):                       # line 21
    summary: str = ""                                    # line 36
    outline: list[str] = Field(default_factory=list)     # line 37
    imports: list[str] = Field(default_factory=list)     # line 38
class LanguageScanner(ABC):                              # line 40
    name: ClassVar[str]; suffixes: ClassVar[frozenset[str]]
    def outline(self, source: str, rel_path: str) -> LanguageOutline           # line 58 — "must never raise"
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any           # line 76
    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None   # line 94
    @property def mode(self) -> str                                            # line 113 — "ast" | "tree-sitter" | "heuristic"

# languages/__init__.py
_SCANNERS: dict[str, LanguageScanner] = {python, php, javascript, rust, perl}   # line 33
def scanner_for(suffix: str) -> LanguageScanner | None                          # line 47

# languages/treesitter.py
def get_parser(language: str) -> Parser | None        # line 64 — cached, never raises
def _build_parser(language: str) -> Parser | None     # line 86 — uses _GRAMMAR_MODULES / _GRAMMAR_CALLABLES

# languages/*.py
class PythonScanner(LanguageScanner)        # python.py:30   outline :36, build_reference_index :81, resolve_import :111, mode :138
class PhpScanner(LanguageScanner)           # php.py:128     outline :136, mode :417
class JavaScriptScanner(LanguageScanner)    # javascript.py:492  outline :505, mode :747
def _extract_script_blocks(source: str, suffix: str) -> tuple[str, str | None]   # javascript.py:187
class RustScanner(LanguageScanner)          # rust.py:127    outline :135, mode :416
class PerlScanner(LanguageScanner)          # perl.py:196    outline :204, mode :515
def _head2_docs(source: str) -> dict[str, str]                                    # perl.py:118

# repo_scan.py
DEFAULT_EXCLUDE_DIRS: frozenset[str]                  # line 85
class FileSlice(BaseModel):                           # line 159 — rel_path: str; record: WikiPageRecord; imports: list[str]; language: str | None
class RepoScan(BaseModel):                            # line 182 — root; files; dir_records; dir_edges: list[tuple[str,str,str]]; import_edges; skipped
def is_wiki_relevant(...)                             # line 202
def file_concept_id(rel_path: str) -> str             # line 249  → "file:<rel>"
def dir_concept_id(rel_path: str) -> str              # line 254
def is_inside_wiki_bundle(root: Path, rel_path: str) -> bool     # line 327
def build_file_slice(root: Path, rel_path: str, body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
                     max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> FileSlice | None   # line 556
    # scanner_for(suffix).outline(content, rel_path) in try/except Exception (lines ~586-608);
    # body = f"# {rel_path}\n\n" + "## API outline\n" + "\n".join(lang_outline.outline) + "## Content…"
def build_import_edges(files: list[FileSlice], index_paths: Iterable[str] | None = None) -> list[tuple[str, str, str]]   # line 718
def scan_repository(root: Path, suffixes=None, exclude_dirs=None, body_max_chars=..., max_file_bytes=...,
                    use_git: bool = True, rel_paths: Iterable[str] | None = None) -> RepoScan   # line 776

# store.py
SCHEMA_VERSION = "1"                                  # line 46
WIKI_SCHEMA_SQL                                       # line 50 — pages(concept_id PK, node_id, title, category, summary, body,
                                                      #   source_id, token_count, created_at, updated_at, origin, asserted_by);
                                                      #   edges(src, dst, rel DEFAULT 'references', provenance DEFAULT 'extracted') PK(src,dst,rel);
                                                      #   pages_fts fts5(concept_id UNINDEXED, title, summary, body); embeddings
_MIGRATION_COLUMNS = {"pages": [("origin", "TEXT NOT NULL DEFAULT 'ingest'"), ("asserted_by", "TEXT")]}   # line 131
_SCHEMA_TABLES = frozenset({"meta","sources","pages","edges","pages_fts",...})   # line 141 — presence probe; add "symbols"
class WikiPageRecord(BaseModel):                      # line 224 — concept_id, node_id, title, category="concept", summary, body,
                                                      #   source_id, token_count, origin="ingest", asserted_by, updated_at
class BaseWikiStore(ABC):                             # line 332
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int                 # line 351
    async def add_edges(self, edges: list[tuple]) -> int                             # line 354 — 3- or 4-tuples (provenance)
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord],
                                   edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]   # line 357
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict]   # line 372
    async def list_pages(...)                                                        # line 375
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict]   # line 383
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict]   # line 389
        # SQLite impl line 1239: dicts with concept_id, rel, direction, + title/summary stub when target is a known page
    async def stats(self) -> dict[str, Any]           # line 403 — SQLite :1300 counts pages/edges/sources/embeddings/total_tokens
    async def broken_edges(self) -> list[dict[str, Any]]   # line 410 — SQLite :1337
class SQLiteWikiStore(BaseWikiStore)                  # line 488 — async def _migrate(self, conn) line 818 iterates _MIGRATION_COLUMNS
# arango_store.py: class ArangoDBWikiStore(BaseWikiStore) line 128; upsert_pages :510 writes origin/asserted_by/updated_at doc fields (:535-550)
# file_store.py:  class InMemoryWikiStore(BaseWikiStore) line 71; _write_page_file :208 dumps extra frontmatter keys via yaml (:218-222)

# sources.py
class SourceCollectionManager                         # line 107
    def is_stale(self, source_id: str) -> bool        # line 528
    def _compute_hash(self, path: Path) -> str        # line 1115 — SHA-1 hex, 8 KiB chunks

# cli.py
@click.group(name="wiki")                             # line 1071 — the `wikitoolkit` entry group; sub-groups `ns` :1918, `sync` :3001
async def _ingest_files(store, sources, root, scan, force: bool = False) -> dict[str, int]   # line 622
    # per-slice: store.replace_source_slice(source_id, [file_slice.record], slice_edges) (~line 689)
    # fresh plane: bulk store.upsert_pages(bulk_records) / store.add_edges(bulk_edges) (~lines 694-696)
def _changed_files_from_git(root: Path) -> list[str]  # line 1335; `upsert --changed` option :1384, used :1421; path filter via is_wiki_relevant + is_inside_wiki_bundle; scan_repository(rel_paths=existing) ~:1461

# tools.py
class WikiQueryInput(BaseModel):                      # line 96 — question: str; budget_tokens: int = DEFAULT_BUDGET_TOKENS; namespace: str | None
class WikiQueryTool(AbstractTool):                    # line 155 — name/description/args_schema class attrs; __init__(self, store) :171; async def _execute(...) -> str :175
def _scoped_store(store: BaseWikiStore, namespace: str | None) -> BaseWikiStore   # line 23
def create_wiki_tools(store: BaseWikiStore, root: Path | None = None, config: WikiProjectConfig | None = None) -> list[AbstractTool]   # line 541

# mcp_server.py
def create_wiki_mcp_server(root: Path) -> StdioMCPServer   # line 90 — load_effective_config → create_wiki_store → FederatedWikiStore →
                                                           #   tools = create_wiki_tools(read_store, root=root, config=config) → server.register_tools(tools)
# toolkit.py
class LLMWikiToolkit(AbstractToolkit)                 # line 54;  tool_prefix: str = "wiki"  line 81

# tools/toolkit.py
class AbstractToolkit(ABC)                            # line 206; tool_prefix: str | None = None :257; confirming_tools: frozenset :275 → routing_meta["requires_confirmation"] (:686-689)
# tools/abstract.py
class ToolResult(BaseModel)                           # line 250
class AbstractTool(EventEmitterMixin, ABC)            # line 281; self.routing_meta: Dict :373
# mcp/adapter.py
class MCPToolAdapter                                  # line 8; _requires_confirmation() :23 (not needed here — all tools read-only)

# context.py
_ID_KINDS = "file|dir|mod|pkg|doc|func|class|concept|page"   # line 38 (feeds _ID_PREFIX_RE :45 and _BARE_ID_PREFIX_RE :51)
def split_namespaced_id(page_id: str) -> tuple[str | None, str]   # line 54
def pack_results(...)                                 # line 203
def truncate_to_tokens(text: str, max_tokens: int | None) -> tuple[str, bool]   # line 272
DEFAULT_BUDGET_TOKENS = 1200                          # line 108

# graphindex/schema.py
class EdgeKind(str, Enum): CONTAINS REFERENCES DEFINES MENTIONS EXPLAINS EXTENDS PRODUCED ABOUT SUPPORTED_BY CONTRADICTS   # line 64-91

# project.py
class WikiProjectConfig(BaseModel)   # fields :401-422 — wiki_name, storage_dir, backend: Literal["sqlite","memory","arangodb"], include_suffixes,
                                     #   exclude_dirs, body_max_chars, max_file_kb, claude, sync_graph, arango_database, arango_credentials_env, arango_text_analyzer, vault_dir
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]   # line 65
def find_project_root(start: Path | None = None) -> Path | None                # line 625
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig   # line 813  (.config → WikiProjectConfig; .config.storage_path(root))

# claude_code/assets.py
PERMISSION_RULES (static tuple) + def permission_rules(root: Path) -> tuple[str, ...]   # line 169 — appends Bash(<resolved-bin>:*)
def mcp_json_entry(root: Path) -> dict               # line 99
def git_hook_block(root: Path) -> str                # line 151
CLAUDE_MD_SECTION                                    # line 186

# packages/ai-parrot/pyproject.toml
wiki-languages = [tree-sitter>=0.23, tree-sitter-php/typescript/javascript/rust/perl>=0.23]   # lines 248-255
wiki = ["ai-parrot[graphindex,wiki-languages,leiden]", "pymupdf>=1.27"]                       # lines 269-272
[tool.setuptools.package-data]                        # line 759 — e.g. "parrot.openapi" = ["*.yaml"] :765, "parrot.flows.dev_loop" = ["_subagent_data/*.md"] :768

# tests
tests/knowledge/wiki/languages/conftest.py: force_heuristic fixture (line 11) monkeypatches treesitter.get_parser → None; polyglot_repo fixture :69
tests/knowledge/wiki/test_store.py — runs the BaseWikiStore contract against every backend
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `astgrep.extract()` | `<Lang>Scanner.outline()` | first call inside `outline()`, before `get_parser()` | `languages/php.py:136`, `rust.py:135`, `javascript.py:505`, `perl.py:204`, `python.py:36` |
| `render_outline()` | `LanguageOutline.outline` | assignment when `symbols` non-empty | `languages/base.py:37` |
| `FileSlice.symbols` | `build_file_slice()` | copied from `lang_outline.symbols`; `content_hash` set on `record` | `repo_scan.py:556` (record built ~:618) |
| `SymbolResolver` | `build_import_edges()` | called after per-language import resolution; consumes returned `references` edges | `repo_scan.py:718` |
| `sym:` records + symbol edges | `_ingest_files()` | appended to `pages`/`edges` args of `replace_source_slice()` and to bulk lists | `cli.py:622`, ~:689, ~:694-696 |
| `upsert_symbols()` | `_ingest_files()` | after `replace_source_slice()` per source (SQLite native; default no-op elsewhere) | `cli.py:622` |
| `content_hash` column | `SQLiteWikiStore._migrate()` | `_MIGRATION_COLUMNS["pages"]` entry | `store.py:131`, `:818` |
| `symbols` table presence | `_SCHEMA_TABLES` probe | add `"symbols"`, `"symbols_fts"` | `store.py:141` |
| `StructuralService._ensure_fresh()` | `scan_repository(rel_paths=…)` + `_ingest_files(force=True)` | same path as `upsert --changed`, under `wiki_write_lock(timeout=0)` | `repo_scan.py:776`, `cli.py:622`, `project.py:65` |
| `StructuralService.blast_radius()` | `BaseWikiStore.neighbors(direction="in")` | iterative BFS over `rel in relations` | `store.py:389` (SQLite :1239) |
| `create_structural_tools()` | `create_wiki_mcp_server()` | `server.register_tools(...)` after the six wiki tools | `mcp_server.py:90` |
| `WikiQueryInput.include_symbols` | `WikiQueryTool._execute()` | filter `category == "symbol"` unless set | `tools.py:96`, `:175` |
| `CodeStructuralToolkit` | `AbstractToolkit.tool_prefix` machinery | public async methods → `code_*` tools | `tools/toolkit.py:257`, `:521-577` |
| `sym` id kind | `context._ID_KINDS` | string extension | `context.py:38` |
| `EdgeKind.CALLS/IMPLEMENTS` | `graphindex/schema.py::EdgeKind` | new enum members | `schema.py:64-91` |
| `PERMISSION_RULES` | `claude_code/assets.py` | three new `mcp__wikitoolkit__wiki_*` strings | `assets.py:169` |
| `wiki-structural` extra | `pyproject.toml` | new extras entry + `wiki` meta-extra + package-data | `pyproject.toml:248-272`, `:759` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.knowledge.wiki.symbols`~~, ~~`parrot.knowledge.wiki.structural`~~ (package), ~~`languages/astgrep.py`~~, ~~`languages/render.py`~~, ~~`languages/rules/`~~ — created by this feature.
- ~~`SymbolRecord` / `SymbolRef` / `SymbolKind` / `StructuralOutline` / `sym_concept_id()` / `sha1_of_text()` / `render_outline()` / `SymbolResolver`~~ — no such names anywhere in `parrot/` today (grep verified).
- ~~`LanguageOutline.symbols` / `.refs`~~, ~~`FileSlice.symbols` / `.refs`~~, ~~`RepoScan.symbol_records` / `.symbol_edges`~~ — not present.
- ~~`pages.content_hash`~~, ~~`symbols` / `symbols_fts` tables~~, ~~`WikiPageRecord.content_hash`~~, ~~`BaseWikiStore.upsert_symbols / symbols_for / find_symbols / search_symbols_fts / page_hashes`~~ — not present; `SCHEMA_VERSION` is `"1"`.
- ~~`EdgeKind.CALLS`~~, ~~`EdgeKind.IMPLEMENTS`~~ — enum has `EXTENDS`/`DEFINES` only.
- ~~`sym` in `context._ID_KINDS`~~ — `func`/`class` are listed but no producer emits them today; `sym` is new.
- ~~`WikiProjectConfig.symbol_depth` / `.structural_backend`~~, ~~`WikiQueryInput.include_symbols`~~ — not present.
- ~~`wiki-structural` extra~~, ~~`ast_grep_py` in the venv~~ — not present; `ast-grep-py` is not a dependency anywhere.
- ~~`tree_sitter.Query` usage in any scanner~~ — all five walk `node.children` manually.
- ~~`StructuralService`, `create_structural_tools()`, `CodeStructuralToolkit`, `wikitoolkit symbols` group~~ — new.
- ~~`ast_grep` / `ast_edit` / `EditPlan` / `plan_token` / `AstEditInput`~~ — **out of scope (Sprint 3)**; nothing here writes to the working tree.
- ~~`ClaudeCodeDispatcher` passing `mcp_servers`~~, ~~per-node `allowed_tools` changes~~ — out of scope (Sprint 4); do not touch `flows/dev_loop/`.
- ~~`code_ast`~~ package — rejected; do not add.
- ~~`ast-grep` patterns for Perl~~ — verified to return nothing; `perl.yaml` must use `kind` rules only.
- ~~`BaseWikiStore.search_fts(exclude_category=…)`~~ — no such parameter; symbol exclusion lives in `WikiQueryTool`.
- ~~`SourceCollectionManager.sha1_of_text()`~~ — only the file-path based `_compute_hash(path)` exists; the text helper is new in `symbols.py`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Seam pattern** from `languages/treesitter.py`: module-level cache, never raise, `None` means "use the next tier". `astgrep.py` copies it and adds the `BaseException` fence **only** around `SgRoot(...)`; everything else uses normal `except Exception`.
- **Rule evaluation shape** (verified): `node.find_all({"rule": spec.rule})` — a positional dict **must** carry the `rule` key; `find_all(kind=…)`/`find_all(pattern=…)` are the keyword forms. `SgNode` API: `kind() text() range() field(name) parent() ancestors() prev() next() child(i) find() find_all() get_match(v) get_multiple_matches(v) is_named()`; `range().start.line` is 0-based, `.index` is a byte offset.
- **Metavariable joins** filter `is_named()` (anonymous comma nodes are included in `$$$` captures — verified artefact `f(1, ,, b=2)`).
- **Dynamic Perl**: `register_dynamic_language({"perl": {"library_path": <site-packages>/tree_sitter_perl/_binding*.so, "language_symbol": "tree_sitter_perl", "extensions": ["pl","pm","t"]}})`; locate the `.so` via `importlib.util.find_spec("tree_sitter_perl")` + `glob("_binding*.so")`, register once per process, cache the boolean.
- **Parent for Perl** is the *last preceding* `package_statement`, not an ancestor → `preceding_package` extractor (matches today's `perl.py` behaviour).
- **Python symbols from `ast`**: `ast.parse` → walk `ClassDef`/`FunctionDef`/`AsyncFunctionDef` to depth `symbol_depth`; `start_byte` = sum of encoded line lengths before `lineno` + `col_offset`; `end_byte` analogously from `end_lineno`/`end_col_offset`; `signature` via `ast.unparse(node.args)` (+ `-> unparse(returns)`); `decorators` via `ast.unparse(d)`; `is_async` for `AsyncFunctionDef`; `content_hash = sha1_of_text(ast.get_source_segment(src, node))`.
- **Parity oracle**: the existing walkers are the oracle. `render_outline` must reproduce their exact strings, including the `: <doc>` suffix only when doc is non-empty, four-space indent for members, Rust `impl X:` header lines, PHP `def name(params)` for methods vs `function name(params)` for functions, JS/TS `export ` prefix only for exported. Read each walker's emit sites before writing the renderer; do not "improve" formatting.
- **Slice atomicity**: `sym:` pages travel in the same `replace_source_slice()` call as the file page; on SQLite the `symbols` rows for the `source_id` are deleted inside the same transaction (`replace_source_slice` override), then `upsert_symbols()` inserts the new ones.
- **`sym:` page body** (kept small; token_count via `estimate_tokens`): `# <qualname>\n\n**kind** <kind> · **file** <rel>:L<start>-<end> · **exported** <bool>\n\n<signature>\n\n<doc>\n\n## Source (excerpt)\n<node text ≤ 2000 chars>`.
- **Store defaults**: implement the five symbol methods on `BaseWikiStore` as concrete defaults (not `@abstractmethod`) so `ArangoDBWikiStore`, `InMemoryWikiStore` and `FederatedWikiStore` compile unchanged; `SQLiteWikiStore` overrides. `page_hashes()` default: `get_page(cid, include_body=False).get("content_hash")`.
- **Namespaces**: tools take `namespace` and use `_scoped_store()`; read-repair runs only when the scoped store is the local one (foreign namespaces' files are not on this disk).
- **Token budgets**: every tool output goes through `truncate_to_tokens`; `SymbolHit.doc` capped at 240 chars, `signature` at 200; `code_outline(include_source=True)` caps at 4 000 chars.
- **Toolkit naming**: `AbstractToolkit` derives tool names from method names as `f"{tool_prefix}_{method}"`. Method names in `CodeStructuralToolkit` are `symbol_lookup`, `outline`, `blast_radius` → tools `code_symbol_lookup`, `code_outline`, `code_blast_radius` (avoids the `code_code_outline` stutter).
- **Logging**: module loggers (`logging.getLogger(__name__)`); once-per-key warnings via a module-level `set`.
- **Commit discipline**: one task = one commit; run `pytest tests/knowledge/wiki -v` after every logic change (CLAUDE.md).

### Known Risks / Gotchas
| Risk | Mitigation |
|---|---|
| pyo3 `PanicException` (BaseException) kills `wikitoolkit mcp` | whitelist before `SgRoot`; `except BaseException` only there; `test_astgrep_panic_fence` |
| Parity drift between YAML rules and walkers | walkers are the oracle; parity tests per language run in both CI jobs; walkers not removed in this feature |
| `RuntimeError: cannot get matcher` for a `kind` the grammar lacks (grammar wheel version skew) | catch per rule, log once per (language, rule id), continue; `RuleSet.load` validates structure |
| Perl `.so` missing / symbol renamed by a future wheel | `supported_language` caches False, DEBUG once; walker fallback; pin `tree-sitter-perl>=0.23` unchanged |
| `symbols` table size on monorepos | `symbol_depth=2` default; FTS on `symbols` SQLite-only; `find_symbols(limit=)` capped |
| Renamed symbol leaves dangling `calls` edges | `broken_edges()` + `wikitoolkit lint` report them; dependents' next upsert/read-repair closes them; `blast_radius` never follows a dangling target |
| Read-repair vs. concurrent `build` | `wiki_write_lock(timeout=0)`; busy → serve `stale=True`, never block a tool call |
| Read-repair on a deleted file | treat as `upsert --changed` does: drop the slice |
| Duplicate qualnames | `~n` ordinal in source order; documented instability if declaration order changes (acceptable — ids follow the code) |
| `wiki_query` flooded by method pages | excluded by default (`include_symbols=False`), over-fetch ×3 then filter so `limit` is still honoured |
| Shared file with FEAT-495 (`claude_code/assets.py`) | keep the `PERMISSION_RULES` change to one additive hunk; merge FEAT-495 first if it lands before this feature's worktree opens |
| Tree-sitter error recovery hides syntax errors | symbols under `ERROR` subtrees dropped; no `syntax_ok` promise in this feature (that belongs to `ast_edit`) |
| Package data not shipped in wheels | `[tool.setuptools.package-data]` entry + `test`/`AC17` wheel check |

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `ast-grep-py` | `>=0.45` (0.45.3 latest on PyPI 2026-09-02; `requires_python>=3.8`; abi3 wheels) | Structural matching, byte ranges, dynamic language registration — new optional extra `wiki-structural` |
| `tree-sitter-perl` | `>=0.23` (1.2.1 installed) | Already in `wiki-languages`; its `.so` is what Perl dynamic registration loads |
| `pyyaml` | present (transitive) | Rule files |
| `aiosqlite` | present (core since FEAT-471) | `symbols` / `symbols_fts` |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one worktree
  `.claude/worktrees/feat-498-ast-grep-for-wikitoolkit` branched from `dev`.
- **Why**: the feature's value is the contract between layers (`SymbolRecord` → rules →
  store → tools). `store.py`, `repo_scan.py`, `base.py` and `cli.py` are touched by several
  modules; splitting across worktrees would let three agents define the contract three ways.
- **Parallel-safe within the worktree** (if an sdd-worker pool is used): the five Module 4
  rule-file tasks (`typescript`, `php`, `rust`, `perl`, `python`) are independent of each
  other once Module 3 has landed — each owns one YAML file, one fixture and one test module,
  and touches only its own `languages/<lang>.py` wiring line.
- **Cross-feature dependencies**: none blocking. **FEAT-495** (`portable-wikitoolkit-config-paths`,
  2 open tasks) also edits `claude_code/assets.py` — additive hunk here; rebase if it lands
  first. FEAT-481 (fireflies) is ingestion-side; no overlap.
- **Worktree test setup**: per the repo's worktree notes, set `PYTHONPATH` to the worktree's
  `packages/*/src` and install `ai-parrot[wiki-languages,wiki-structural]` extras into the
  shared venv once (`uv pip install ast-grep-py>=0.45`) so both CI modes can be exercised locally
  (`force_no_astgrep` covers the absent case).

---

## 8. Open Questions

> Resolved items were decided in the brainstorm (two Q&A rounds) or in the
> `/sdd-spec` clarifying batch; the decision is already reflected in the body.

- [x] Flow type / base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Scope vs. the design's roadmap — *Resolved in brainstorm*: Sprint 1 + Sprint 2 (backend, symbols, hash + read-repair, `SymbolResolver`, read-only tools). `ast_grep`/`ast_edit` (Sprint 3) and dev_loop wiring (Sprint 4) are follow-up features.
- [x] Python source of truth — *Resolved in brainstorm*: stdlib `ast` remains authoritative; ast-grep only adds byte offsets and `calls` refs. Python `sym:` pages therefore exist without any extra.
- [x] Perl via dynamic registration — *Resolved in brainstorm*: yes, `kind` rules only, silent fallback to the current walker (re-verified: patterns return nothing, `.so` exports `tree_sitter_perl`).
- [x] Outline parity policy — *Resolved in brainstorm*: strict byte-parity; extra symbols live only in `symbols`/`sym:` pages.
- [x] Tool surfaces — *Resolved in brainstorm*: MCP (`wikitoolkit mcp`) **and** `CodeStructuralToolkit`; one `StructuralService`.
- [x] Backend coverage — *Resolved in brainstorm*: SQLite gets `symbols` table + FTS + `content_hash`; Arango/OKF persist `sym:` pages via existing `upsert_pages`/`add_edges` and use default `BaseWikiStore` symbol methods over pages.
- [x] Default symbol depth — *Resolved in brainstorm*: top-level + direct members (≤ 2), `symbol_depth` config.
- [x] Where does the freshness hash live — *Resolved in /sdd-spec*: new `pages.content_hash` column (SHA-1 per page, `file:` and `sym:`), via `_MIGRATION_COLUMNS`; not a join on `sources.file_hash`.
- [x] MCP tool naming — *Resolved in /sdd-spec*: `wiki_symbol_lookup`, `wiki_code_outline`, `wiki_blast_radius` (consistent with the six existing `wiki_*` tools and `permission_rules()`); toolkit exposes `code_symbol_lookup`, `code_outline`, `code_blast_radius`.
- [x] `wiki_query` and symbol pages — *Resolved in /sdd-spec*: excluded by default; opt-in `include_symbols=True`. `wiki_page`/`wiki_related` accept `sym:` ids unconditionally.
- [x] Duplicate-qualname ids — *Resolved in /sdd-spec*: source-order ordinal suffix `~2`, `~3` … (`sym:<rel>#<q>`, `sym:<rel>#<q>~2`); the first occurrence keeps the clean id.
- [ ] `EdgeKind.CALLS` / `IMPLEMENTS` — the spec **adds both** (additive enum members, needed for a 1:1 `sync_graph` mirror). Veto here if GraphIndex maintainers prefer wiki-only `rel` strings until the mirror is exercised. — *Owner: Jesus*: both
- [ ] Read-repair when `wiki_write_lock` is held — the spec **serves stale with `stale=True`, no wait**. Alternative: wait up to N seconds. Decide before Module 7. — *Owner: spec author*
- [x] Rule files: package data only (spec) vs. a `.parrot/wiki/rules/` overlay for project-specific symbols — deferred to a later feature unless a concrete project needs it during implementation. — *Owner: Jesus*: follow-up later feature

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-02 | Jesus Lara | Initial draft from `ast-grep-for-wikitoolkit.brainstorm.md` (Option A) + four /sdd-spec clarifications |
