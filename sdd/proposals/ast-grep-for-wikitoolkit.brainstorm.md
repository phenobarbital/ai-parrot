---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: ast-grep Structural Plane for wikitoolkit — symbols as first-class wiki nodes

**Date**: 2026-09-02
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

> Input documents: `artifacts/ast/astgrepstructuralplanedesign.md` (full design,
> §1–§9) and `artifacts/ast/astgrep_rules_prototype.py` (rule-set probe). This
> brainstorm scopes the **first feature** carved out of that design — the
> design's Sprint 1 + Sprint 2 — and records what was re-verified against the
> codebase and against `ast-grep-py 0.45.3` in this session. The edit tools
> (`ast_grep` / `ast_edit`, Sprint 3) and the dev_loop integration (Sprint 4)
> are explicitly **follow-up features** that build on the contracts fixed here.

---

## Problem Statement

The LLM wiki (`wikitoolkit build`) knows *files*, not *symbols*. Every source
file becomes one `file:<rel>` page whose body carries a rendered
`## API outline` (plain text lines) plus a content head. Consequences:

- **Agents cannot ask "where is `UserService.get_user`?"** — `wiki_query` is
  FTS over page title/summary/body, so a symbol name competes with every
  mention of it in prose and in unrelated files. There is no ranked
  symbol-exact lookup, no byte range, no signature/doc per symbol.
- **No blast radius.** The graph has `contains` (dir → file) and `references`
  (file → file via imports). "Who calls `helper()`?" or "what implements
  `Visitor`?" is unanswerable without grepping the repository, which is what
  the wiki was built to avoid.
- **Five hand-written walkers drift.** `languages/{python,javascript,php,rust,
  perl}.py` each walk `node.children` manually (never `tree_sitter.Query`),
  duplicate the same "find name field, find doc comment, indent under parent"
  logic, and encode the extraction rules in Python control flow that cannot
  be reviewed as data or validated with `sg test`.
- **Freshness is per source and hook-driven.** `sources.file_hash` exists, but
  `file:` pages themselves carry no hash; if the `post-commit` hook is missed
  (checkout, merge, rebase, dirty tree) a query silently returns stale
  outlines and nobody notices.

**Who is affected**: every agent consuming the wiki — Claude Code via the
`wikitoolkit` MCP server, ai-parrot agents via `LLMWikiToolkit`, and the
`dev_loop` research/QA nodes — plus the developers maintaining five scanners.

**Why now**: the follow-up design (structural `ast_edit` with plan/token/apply,
scoped by blast radius) is only sound if the symbol layer, the `calls`/`extends`
edges, and a per-file freshness invariant exist first. This feature is that
foundation.

## Constraints & Requirements

- **Zero regression for users without the extra.** `ast-grep-py` is an
  optional extra (`wiki-structural`). Without it the current chain
  (tree-sitter walker → stdlib heuristic) must produce byte-identical
  outlines. Without `wiki-languages` either, the heuristic path still works.
- **Strict outline parity (Round 2 decision).** The rendered `## API outline`
  of `file:` pages does **not** change. Extra symbols the new backend sees
  (TS class methods, PHP namespaces) live only in the symbols table and
  `sym:` pages. Parity tests per language: `outline()` with and without
  `ast-grep-py` must be identical.
- **Python source of truth stays `ast` (Round 1 decision).** `PythonScanner`
  emits `SymbolRecord`s from stdlib `ast` (so Python `sym:` pages exist even
  without any extra); ast-grep only enriches with byte offsets and call refs
  when available.
- **Perl in scope with fallback (Round 1 decision).** Dynamic registration of
  the `tree-sitter-perl` wheel's `.so`; `kind` rules only (patterns verified
  to return nothing); any failure degrades to today's walker silently.
- **Never persist the AST.** Persist derived facts only (`SymbolRecord`,
  edges). The source file is the AST's source of truth; re-parse is cheaper
  than deserialising.
- **A pyo3 panic must never kill the MCP process.** `SgRoot(src, lang)` on an
  unregistered language raises `PanicException`, a `BaseException` subclass
  (re-verified this session). Language whitelist before construction, and
  `except BaseException` only around that call.
- **Store backends (Round 2 decision).** SQLite gets the full `symbols` table
  + FTS + `content_hash` column (schema v2, idempotent ALTER migration as
  `_MIGRATION_COLUMNS` already does). ArangoDB and InMemory/OKF receive `sym:`
  pages and edges through the existing `upsert_pages`/`add_edges`/
  `replace_source_slice`; symbol lookups there fall back to a default
  implementation over pages with `category="symbol"`.
- **Two surfaces, one implementation.** `symbol_lookup`, `code_outline`,
  `blast_radius` are `AbstractTool`s registered in `wikitoolkit mcp` **and**
  re-exposed by a `CodeStructuralToolkit(AbstractToolkit)` with
  `tool_prefix="code"` — both delegating to one `StructuralService`.
- **Default symbol depth ≤ 2 (Round 2 decision).** Top-level declarations and
  their direct members. Configurable; not "exported only" (blast radius needs
  private helpers) and not unlimited (monorepo table size).
- **Deterministic, offline, no LLM** anywhere in extraction or resolution.
  Unresolvable references produce no edge rather than a guessed one.
- **Read-only feature.** No tool in this feature writes to the working tree.
  `ast_edit` is out of scope; the `EditPlan`/token protocol is designed later.
- Async-first, Pydantic models, Google docstrings, `self.logger` — project
  standards. `uv` for the new extra.

---

## Options Explored

### Option A: Declarative ast-grep rule backend + symbols table + read-only lookup tools

Add an optional structural backend (`languages/astgrep.py`) that loads one
YAML rule file per language (`languages/rules/<lang>.yaml`) and evaluates
ast-grep `kind`/`inside`/`has`/`not`/`any` rules through `SgRoot.find_all(
{"rule": ...})`. Rules are pure data; anything needing logic (first
docstring, leading doc-comment skipping `#[derive]`, POD `=head2` lookup,
"preceding package" for Perl) is a named *extractor* implemented once in
Python. The backend returns a `StructuralOutline` (`symbols`, `refs`,
`imports`, `summary`); each existing scanner tries it first and falls back to
its current tree-sitter walker / heuristic. `render_outline(symbols)` projects
symbols back to today's outline lines (parity-tested), so the outline becomes a
projection rather than the source of truth.

Symbols are persisted as `sym:<rel>#<qualname>` pages (same
`replace_source_slice()` as their `file:` page — atomic per source) plus a
SQLite `symbols` table with FTS; `file:` pages gain `content_hash`. New edges
`defines` (file → sym), `contains` (sym → member sym), and — via a
deterministic three-step `SymbolResolver` inside `build_import_edges()` —
`calls` / `extends` / `implements` between `sym:` pages, tagged
`provenance=extracted|inferred`.

`StructuralService` performs *read-repair*: before answering, it hashes the
candidate files of the hits, compares with `page_hashes()`, and re-scans the
stale ones through the same `scan_repository(rel_paths=…)` +
`replace_source_slice` path that `wikitoolkit upsert --changed` uses. Three
tools consume it: `symbol_lookup` (exact qualname → exact name → FTS),
`code_outline` (file or symbol, exact ranges), `blast_radius` (iterative
`neighbors(direction="in")` over the requested relations, returns the impacted
symbols **and the file set**, which is the `scope` the future `ast_grep`/
`ast_edit` expect).

✅ **Pros:**
- Rules are reviewable data, validatable with `sg test`, shared vocabulary
  with the future `ast_grep`/`ast_edit` tools (same `Rule` schema, same
  engine, same `SgNode` byte ranges). Building the symbol layer on ast-grep
  now means Sprint 3 adds tools, not a second parser stack.
- One extractor implementation for five languages instead of five walkers;
  parity evidence already reproduced for TS/PHP/Rust in the prototype
  (re-run this session — see Code Context).
- Full degradation chain preserved: extra absent → walker → heuristic.
- `sym:` pages reuse *all* existing plumbing (pages, edges, FTS, namespaces,
  `broken_edges()` lint, federation) — no parallel store.
- Read-repair turns the git hook into a backstop; correctness stops depending
  on hook installation.

❌ **Cons:**
- New native dependency (`ast-grep-py`, pyo3) with a `BaseException`-class
  failure mode that must be fenced carefully.
- Two extraction paths per language coexist until the walkers can be retired
  (design says: two stable releases) → parity tests are mandatory, not
  optional.
- Perl support depends on locating a wheel-private `.so`
  (`tree_sitter_perl/_binding.abi3.so`) — works today, but it is an
  undocumented contract of that wheel.
- Schema v2 touches three backends and the `_ID_KINDS` id grammar; more
  surface than a pure-Python change.

📊 **Effort:** Medium-High (two sprints in the design's roadmap)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ast-grep-py` | Structural matching (`SgRoot`, `find_all`, `Rule`), byte ranges, dynamic language registration | 0.45.3 latest on PyPI (verified 2026-09-02), `requires_python>=3.8`, abi3 wheels. New optional extra `wiki-structural`. Not in the venv today. |
| `tree-sitter-perl` | Provides the `.so` exporting `tree_sitter_perl` for `register_dynamic_language` | 1.2.1 installed; already part of `wiki-languages`. |
| `pyyaml` | Load `rules/<lang>.yaml` | Already a transitive dep (used by OKF frontmatter writer). |
| `aiosqlite` | `symbols` table + `symbols_fts` | Already core (FEAT-471). |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/languages/base.py` — `LanguageOutline` gains
  `symbols`/`refs` with empty defaults; `LanguageScanner` ABC unchanged.
- `parrot/knowledge/wiki/languages/treesitter.py` — `get_parser()` stays the
  second tier of the chain; `_GRAMMAR_MODULES` mapping is the model for the
  ast-grep whitelist/dynamic table.
- `parrot/knowledge/wiki/languages/perl.py::_head2_docs()` → the `pod_head2`
  extractor; `javascript.py::_extract_script_blocks()` for Svelte.
- `parrot/knowledge/wiki/repo_scan.py` — `build_file_slice()` attaches
  symbols to `FileSlice`; `build_import_edges()` hosts `SymbolResolver`;
  `file_concept_id()` pattern for `sym_concept_id()`.
- `parrot/knowledge/wiki/store.py` — `_MIGRATION_COLUMNS` for the
  `content_hash` ALTER; `replace_source_slice()` for atomic per-source
  replacement; `neighbors()` for blast radius; `broken_edges()` for lint.
- `parrot/knowledge/wiki/sources.py::SourceCollectionManager._compute_hash()`
  — the SHA-1 used for `content_hash` (same digest as `sources.file_hash`).
- `parrot/knowledge/wiki/cli.py::_ingest_files()` + `scan_repository(
  rel_paths=…)` — the exact code path read-repair re-uses.
- `parrot/knowledge/wiki/tools.py` (`WikiQueryTool` pattern,
  `create_wiki_tools()`), `mcp_server.py::create_wiki_mcp_server()`
  (`server.register_tools`), `toolkit.py::LLMWikiToolkit` (`tool_prefix`).
- `parrot/knowledge/wiki/context.py` — `_ID_KINDS` (add `sym`),
  `pack_results`, `truncate_to_tokens` for token-budgeted outputs.
- `tests/knowledge/wiki/languages/conftest.py::force_heuristic` — the
  monkeypatch style for the parity fixture (`astgrep.is_available → False`).

---

### Option B: Extend the existing tree-sitter walkers by hand to emit `SymbolRecord`

Keep the five hand-written walkers and teach each one to build
`SymbolRecord`s (kind, qualname, parent, byte range, doc) alongside the
outline lines it already renders. Add the same `symbols` table, `sym:` pages,
edges, `content_hash`, read-repair and the three tools — but with no new
dependency and no rule files.

✅ **Pros:**
- No native dependency, no pyo3 panic class, no wheel `.so` contract.
- Byte ranges are already available on tree-sitter nodes (`start_byte`/
  `end_byte`); the walkers already know each language's node kinds.
- Smallest conceptual delta: the store/tools half is identical to Option A.

❌ **Cons:**
- Five more walkers' worth of Python control flow; the extraction logic
  stays un-reviewable as data and un-testable with `sg test`.
- Dead end for the follow-up: `ast_grep`/`ast_edit` need pattern matching
  with metavariables and `commit_edits` — tree-sitter alone offers neither,
  so Sprint 3 would introduce ast-grep *anyway*, with a second, unrelated
  node-kind vocabulary.
- Heuristic tier (no `wiki-languages`) cannot produce byte ranges at all;
  symbol pages would be inconsistent across tiers.
- Call-site extraction (`calls` refs) must be hand-coded per language on top
  of the declaration walk.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tree-sitter` + grammar wheels | Already used by the walkers | 0.26.0 installed; `wiki-languages` extra unchanged |

🔗 **Existing Code to Reuse:**
- All five `languages/*.py` walkers (extended in place).
- Same store / repo_scan / tools reuse list as Option A.

---

### Option C: tree-sitter `Query` (`.scm` S-expression queries) as the declarative layer

Use tree-sitter's native query language — the same mechanism editors use for
highlights/tags — with one `tags.scm`-style file per language capturing
`@definition.class`, `@definition.function`, `@name`, `@doc`. Evaluate with
`tree_sitter.Query`/`QueryCursor` on the parsers `get_parser()` already
returns. Rest of the feature (symbols table, `sym:` pages, edges, read-repair,
tools) as in Option A.

✅ **Pros:**
- Declarative and reviewable like Option A, but on the dependency stack that is
  **already installed** — no new native package, no `PanicException` class.
- Upstream grammars ship reference `tags.scm` files (the `tree_sitter_perl`
  wheel even bundles a `queries/` directory) to crib from.
- `Query` is faster than Python child-walks for large files.

❌ **Cons:**
- No rewrite engine and no metavariable *patterns*: the follow-up
  `ast_grep`/`ast_edit` would still need ast-grep, leaving two declarative
  vocabularies (`.scm` captures vs. ast-grep `Rule`) for the same node kinds.
- `tree_sitter.Query` API churned across 0.22 → 0.25 (`Query(lang, src)` vs
  `lang.query()`, `QueryCursor` introduction); the repo pins `>=0.23` and has
  0.26 installed, so compatibility shims are needed.
- Predicates (`#match?`, `#eq?`) are weaker than ast-grep's relational rules
  (`inside`/`has` with `stopBy`); "not inside class" is awkward in `.scm`.
- Perl: works via the already-loaded grammar (no dynamic registration
  needed) — the one place this option is *simpler*.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tree-sitter>=0.23` | `Query`/`QueryCursor` | Installed 0.26.0; API differences across minors |
| grammar wheels | Node kinds + bundled `queries/*.scm` | Already in `wiki-languages` |

🔗 **Existing Code to Reuse:**
- `languages/treesitter.py::get_parser()` (unchanged), all five scanners as
  fallback, same store/tools reuse as Option A.

---

### Option D (unconventional, rejected): LSP-backed symbol plane

Drive language servers (pyright, tsserver, intelephense, rust-analyzer,
PerlNavigator) through a multi-LSP client, use `documentSymbol` for the
symbol table and `references`/`callHierarchy` for type-accurate `calls`
edges.

✅ **Pros:** type-accurate call graph (no name-collision guesses); exact
rename semantics for the future edit tool.

❌ **Cons:** one long-lived server per language per worktree; minutes-long
warm-up on large repos, so `wikitoolkit build` stops being a cheap offline
step; servers require the project's dependencies installed to resolve types;
five independent server behaviours to babysit; and it does not remove the
walkers (still needed for the offline tier). The design explicitly scopes type
resolution out ("that is LSP's job, not this plane's") — this option confirms
the boundary rather than crossing it.

📊 **Effort:** High

---

## Recommendation

**Option A** is recommended because:

- It is the only option where the symbol layer built now and the edit tools
  built next share **one engine, one rule vocabulary, and one notion of byte
  range**. Options B and C would each force a second stack in Sprint 3, and
  the `SymbolRecord.start_byte/end_byte` produced today would have to be
  re-derived by ast-grep tomorrow to be safe to edit against.
- Its main risks were **re-verified this session**, not assumed: the
  `PanicException` fence, dynamic Perl registration from the installed wheel,
  `RuntimeError: cannot get matcher` for bad kinds being a normal exception,
  and the anonymous-comma artefact in `$$$ARGS` (fixed by `is_named()`).
- Its regression surface is bounded by a mechanical test: the strict
  outline-parity suite. If parity holds, nothing an existing consumer sees
  changes; if it does not, the test fails before merge.
- What we trade away: a new native dependency and a bounded period of
  duplicated extraction paths. The extra stays opt-in, so the cost lands only
  on installs that want symbols — and Python `sym:` pages (the repository's
  main language) come from stdlib `ast` regardless.

Option C is the credible runner-up and is worth keeping in the back pocket:
if `ast-grep-py` ever becomes unmaintainable, its rule files map onto `.scm`
captures with a mechanical translation, and the store/tools half is
identical.

---

## Feature Description

### User-Facing Behavior

**Install.** `uv pip install "ai-parrot[wiki-structural]"` (new extra;
also folded into the `wiki` meta-extra). Without it, `wikitoolkit build`
behaves exactly as today except that **Python** files still gain `sym:` pages
(from `ast`).

**Build / upsert.** `wikitoolkit build` and `wikitoolkit upsert --changed`
additionally produce, per scanned source file:
- one `sym:<rel>#<qualname>` page per symbol down to depth 2
  (`category="symbol"`, title = qualname, summary = first doc line, body =
  signature + doc + line range + a capped excerpt of the node text);
- `defines` (file → sym) and `contains` (sym → member) edges;
- `calls` / `extends` / `implements` edges between symbols when the
  resolver finds a unique target, marked `extracted` (same file or
  import-reachable) or `inferred` (globally unique name);
- a `content_hash` on the `file:` page.
`wikitoolkit status`/`stats` report symbol counts and the structural mode per
language (`ast-grep | tree-sitter | heuristic`). `wikitoolkit lint` keeps
reporting dangling edges (now including `sym:` targets after a rename).

**Query.** `sym:` ids are first-class everywhere ids are accepted:
`wikitoolkit page sym:parrot/utils.py#helper`, `wikitoolkit related <sym>`,
`wiki_page`/`wiki_related` over MCP, federated `ns::sym:...`. `wiki_query`
results may include symbol stubs (ranked by FTS like any page; see Open
Question on default filtering).

**New tools** (in `wikitoolkit mcp` as `symbol_lookup`, `code_outline`,
`blast_radius`; in `CodeStructuralToolkit` as `code_symbol_lookup`, …; and
as `wikitoolkit symbols lookup|outline|blast` CLI subcommands for humans and
scripts):

- `symbol_lookup(query, kind?, language?, path_prefix?, limit=20,
  namespace?)` → ranked hits `{symbol_id, rel_path, qualname, kind,
  signature, doc, start_line, end_line, exported, score, stale}` plus
  `repaired_files` listing anything read-repair re-scanned on the way.
- `code_outline(target, depth=2, include_source=False)` where `target` is a
  `file:` id, a `sym:` id, or a relative path → the symbol tree with exact
  line/byte ranges; `include_source` returns the node text (capped) for a
  `sym:` target only.
- `blast_radius(symbol, relations=[calls,extends,implements], depth=2,
  include_inferred=True, include_tests=True)` → `{root, impacted:[{symbol,
  via, distance, provenance}], files:[…], truncated}`. `files` is the
  scope handed to future edit tools; `provenance` lets the caller discount
  inferred links.

Outputs are token-budgeted (`pack_results`/`truncate_to_tokens`); no tool
ever dumps a whole file.

### Internal Behavior

1. **Extraction (per file, in `build_file_slice`)** — `scanner.outline()`
   first calls `astgrep.extract(source, lang, rel_path)`. That function
   checks `is_available()` (import succeeded) and `supported_language(lang)`
   (built-in whitelist, or a cached dynamic registration attempt for Perl
   that locates `tree_sitter_perl/_binding*.so` and calls
   `register_dynamic_language`). It parses with `SgRoot` inside a
   `BaseException` fence, loads the cached `RuleSet` for the language, runs
   each symbol rule with `find_all({"rule": …})`, applies the declared name/
   signature/doc/parent/exported/async extractors, then runs ref and import
   rules. It returns `StructuralOutline` or `None`; on `None` the scanner
   continues with its existing tree-sitter walker or heuristic.
   `PythonScanner` differs: it always builds symbols from `ast` and, when
   ast-grep is present, merges byte offsets and `calls` refs by line match.
2. **Rendering** — when `symbols` is non-empty, `LanguageOutline.outline`
   is `render_outline(symbols)`, a projection that reproduces today's line
   format per language (indent under parent, `: <doc>` suffix, `export`/
   `pub` prefixes, `impl X:` headers). Symbols the current outline never
   showed (TS methods, PHP namespaces) are skipped by the renderer.
3. **Persistence (in `scan_repository` → `_ingest_files`)** — `FileSlice`
   carries `symbols` and `refs`; the `file:` record gets `content_hash`;
   `sym:` records and `defines`/`contains` edges are emitted into the same
   per-source slice so `replace_source_slice()` deletes and re-inserts them
   atomically with the file page (SQLite also replaces the `symbols` rows for
   that `source_id` in the same transaction).
4. **Resolution (in `build_import_edges`)** — `SymbolResolver` gets every
   file's symbols and refs plus the freshly computed `references` edges.
   For each `SymbolRef.target_text` it tries (1) same-file qualname/name,
   (2) name in files reachable via the source file's `references` edges,
   (3) globally unique name. Steps 1–2 → `extracted`, 3 → `inferred`, no
   unique candidate → no edge.
5. **Lookup** — `StructuralService(store, root, config)` wraps the store's
   new `find_symbols`/`search_symbols_fts`/`symbols_for`/`page_hashes`
   methods (SQLite-native; default implementations on `BaseWikiStore` fall
   back to `list_pages(category="symbol")` + `search_fts` for Arango/OKF).
   Before returning hits it runs `_ensure_fresh(rel_paths)`: SHA-1 the hit
   files on disk, compare with `page_hashes()`, and for mismatches call
   `scan_repository(root, rel_paths=stale)` + `_ingest_files(force=True)`
   under `wiki_write_lock`, then re-query. Repaired files are reported.
6. **Surfaces** — `create_structural_tools(store, root, config)` returns the
   three `AbstractTool`s; `create_wiki_mcp_server()` registers them next to
   the six wiki tools; `CodeStructuralToolkit` exposes the same service with
   `tool_prefix="code"`; `wikitoolkit symbols …` CLI wraps the service too.
   `claude_code/assets.permission_rules()` gains the new read-only
   `mcp__wikitoolkit__*` names.

### Edge Cases & Error Handling

- **Extra missing / import error** → `is_available()` False, cached; every
  scanner uses its current path; Python symbols still come from `ast`.
- **Unsupported or unregistered language** → whitelist check fails →
  `None` before `SgRoot` is ever built. A test forces an invalid language to
  prove the process survives; a second test monkeypatches the whitelist to
  let `SgRoot` panic and asserts the `BaseException` fence catches it.
- **Perl `.so` not found / symbol not exported** → dynamic registration
  returns False, cached for the process, logged at DEBUG (not per file);
  Perl falls back to the existing walker.
- **Rule references a `kind` the grammar lacks** → `RuntimeError: cannot
  get matcher` is caught per rule, logged once per (language, rule id), and
  the remaining rules still run. Rule files are validated at load (required
  keys, known extractor names).
- **Syntax errors in source** → tree-sitter error recovery still yields
  nodes; symbols inside `ERROR` subtrees are dropped; outline degrades to
  whatever is well-formed (same as today's walkers).
- **Duplicate qualnames in one file** (overloads, re-opened Perl packages,
  Rust `impl` blocks for the same type) → deterministic `#<n>` suffix on the
  concept id for the 2nd+ occurrence, so ids stay stable across re-scans in
  source order.
- **Renamed symbol** → old `sym:` page disappears with its file's slice;
  incoming `calls` edges from other files dangle until those files re-scan
  (their own upsert or read-repair); `broken_edges()` surfaces them
  meanwhile; `blast_radius` never follows a dangling target.
- **Read-repair races a running build** → `wiki_write_lock` not acquired →
  serve the stale hits with `stale=True` and skip the repair rather than
  block a tool call.
- **File deleted on disk but page present** → read-repair treats it like
  `upsert --changed` does for deleted paths: drop the source slice.
- **Very large files** (> `max_file_bytes`) are skipped by the scanner today
  and keep being skipped — no symbols, no repair loop.
- **Depth cap** → symbols nested deeper than `symbol_depth` are not
  persisted; `code_outline(depth>2)` therefore cannot show them and says so
  (`truncated=True`) instead of re-parsing on demand in v1.
- **Namespaces** → `symbol_lookup(namespace=…)` scopes to one federated
  store like `wiki_query`; read-repair only runs against the local root (a
  foreign namespace's files are not on this disk).
- **ArangoDB / OKF** → no `symbols` table; `find_symbols` default impl is
  slower but functionally equivalent; `content_hash` is stored as a page
  field there (Arango documents are schemaless; OKF frontmatter key).

---

## Capabilities

### New Capabilities
- `wiki-structural-backend`: optional ast-grep rule engine
  (`languages/astgrep.py` + `languages/rules/<lang>.yaml` + fixed
  extractors + `render_outline`) slotted in front of every scanner with
  strict outline parity and full degradation.
- `wiki-symbol-pages`: `SymbolRecord`/`SymbolRef` models, `sym:` concept
  ids, `symbols` table (SQLite) with FTS, `defines`/`contains`/`calls`/
  `extends`/`implements` edges, `SymbolResolver`.
- `wiki-freshness-read-repair`: `content_hash` on `file:` pages,
  `page_hashes()` store method, `StructuralService._ensure_fresh` reusing
  the `upsert --changed` path.
- `wiki-symbol-tools`: `symbol_lookup`, `code_outline`, `blast_radius` as
  `AbstractTool`s (MCP) + `CodeStructuralToolkit` (agents) + `wikitoolkit
  symbols` CLI, all over one `StructuralService`.

### Modified Capabilities
- `wikitoolkit-language-plugins` (FEAT-394): `LanguageOutline` gains
  `symbols`/`refs`; scanners gain the ast-grep first tier; parity tests.
- `wikitoolkit-perl-scanner` (FEAT-432): dynamic ast-grep registration in
  front of the existing walker; `_head2_docs` reused as extractor.
- `wikitoolkit-svelte-typescript-support` (FEAT-396): `<script>` extraction
  feeds the `typescript`/`javascript` ast-grep grammar.
- `mcp-local-server-wikitoolkit` (FEAT-403): three more tools registered;
  permission rules extended.
- `wiki-namespaces` (FEAT-450): `namespace` argument and `ns::sym:` ids on
  the new tools; `_ID_KINDS` gains `sym`.
- `llmwiki-pageindex-graphindex` (FEAT-260) store schema: `SCHEMA_VERSION`
  → `"2"`, `pages.content_hash`, `symbols`, `symbols_fts`.
- `graphindex` (`EdgeKind`): add `CALLS` and `IMPLEMENTS` so the
  `sync_graph` mirror stays 1:1 (see Open Questions).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/languages/base.py` | extends | `LanguageOutline.symbols: list[SymbolRecord] = []`, `.refs: list[SymbolRef] = []` — additive, defaults keep every scanner valid |
| `parrot/knowledge/wiki/languages/{python,javascript,php,rust,perl}.py` | modifies | Try `astgrep.extract()` first; unchanged fallback chain; Python merges `ast` symbols with ast-grep offsets |
| `parrot/knowledge/wiki/languages/astgrep.py`, `render.py`, `rules/*.yaml` | new | Optional seam, projection renderer, per-language rule data (package data in `pyproject`) |
| `parrot/knowledge/wiki/symbols.py` | new | `SymbolKind`, `SymbolRecord`, `SymbolRef`, `StructuralOutline`, `sym_concept_id()` |
| `parrot/knowledge/wiki/repo_scan.py` | modifies | `FileSlice.symbols/refs`, `RepoScan.symbol_records/symbol_edges`, `content_hash`, `SymbolResolver` in `build_import_edges()` |
| `parrot/knowledge/wiki/store.py` | modifies | `SCHEMA_VERSION="2"`, `_MIGRATION_COLUMNS["pages"] += content_hash`, `symbols`/`symbols_fts` DDL, new abstract+default methods, `replace_source_slice` clears symbol rows |
| `parrot/knowledge/wiki/arango_store.py`, `file_store.py` | modifies (light) | Persist `content_hash`; rely on `BaseWikiStore` default symbol methods over `sym:` pages |
| `parrot/knowledge/wiki/structural/{service,tools,toolkit}.py` | new | `StructuralService`, three tools, `CodeStructuralToolkit` |
| `parrot/knowledge/wiki/tools.py`, `mcp_server.py` | extends | `create_structural_tools()` registered by `create_wiki_mcp_server()` |
| `parrot/knowledge/wiki/cli.py` | extends | `wikitoolkit symbols lookup|outline|blast`; `stats` shows symbol counts; `_ingest_files` unchanged signature |
| `parrot/knowledge/wiki/context.py` | modifies | `_ID_KINDS` += `sym` so `split_namespaced_id`/`stub_line` accept symbol ids |
| `parrot/knowledge/wiki/project.py::WikiProjectConfig` | extends | `symbol_depth: int = 2`, `structural_backend: bool = True` (kill switch) |
| `parrot/knowledge/wiki/claude_code/assets.py` | extends | `permission_rules()` adds the three read-only MCP tool names (shared file with FEAT-495 — coordinate) |
| `parrot/knowledge/graphindex/schema.py::EdgeKind` | extends | `CALLS`, `IMPLEMENTS` |
| `packages/ai-parrot/pyproject.toml` | extends | `wiki-structural = ["ast-grep-py>=0.45"]`; `wiki` meta-extra includes it; rules YAML as package data |
| `tests/knowledge/wiki/languages/*` | extends | Parity suite (with/without ast-grep), panic fence, Perl dynamic registration, rule-load validation |
| `tests/knowledge/wiki/test_store.py` | extends | Runs against every backend: symbol methods, `page_hashes`, migration v1→v2 |
| Existing wiki planes (`.parrot/wiki/wiki.db`) | data migration | Idempotent ALTER + CREATE IF NOT EXISTS; first `build` after upgrade populates symbols; no rebuild required for old pages |

No breaking changes to public APIs; every new field has a default.

---

## Code Context

### User-Provided Code

The full design and the prototype live in the repository and are the
authoritative inputs; only the fragments the spec must carry forward are
reproduced here.

```python
# Source: artifacts/ast/astgrep_rules_prototype.py:228 (rule evaluation shape — a positional dict MUST carry the "rule" key)
for m in root.find_all({"rule": spec["rule"]}):
    r = m.range()   # r.start.line / r.start.column / r.start.index (byte)
```

```python
# Source: artifacts/ast/astgrepstructuralplanedesign.md §4.2 (seam skeleton)
def parse(src: str, lang: str) -> "SgRoot | None":
    if not is_available() or not supported_language(lang): return None
    try:
        return SgRoot(src, lang)
    except BaseException:               # pyo3 PanicException inherits BaseException
        logger.warning("ast-grep panicked parsing %s", lang); return None
```

```yaml
# Source: artifacts/ast/astgrepstructuralplanedesign.md §4.1 (rule-file schema, one file per language)
language: python
aliases: []
summary: module_docstring
symbols:
  - id: class
    rule: { kind: class_definition }
    name: { field: name }
    signature: { field: parameters }
    doc: first_docstring
    parent: { ancestor: class_definition, name: { field: name } }
    exported: { inside: export_statement }
refs:
  - rel: calls
    rule: { kind: call, not: { inside: { kind: decorator } } }
    target: { field: function }
    scope: { ancestor: [function_definition, class_definition] }
imports:
  - { rule: { kind: import_statement } }
```

**Re-verified this session against `ast-grep-py 0.45.3`** (installed into
the session scratchpad, not the project venv; prototype re-run):

- Prototype output for TS/PHP/Rust matches the design's §4.4 table (class/
  method/function/interface/const/type, PHP class+method+interface+trait+enum,
  Rust struct/impl/fn/trait/mod/enum with `#[derive]` skipped).
- `SgRoot("x", "perl")` without registration → `PanicException`, **caught
  only by `except BaseException`**, not by `except Exception`.
- `register_dynamic_language({"perl": {"library_path": <tree_sitter_perl/_binding.abi3.so>,
  "language_symbol": "tree_sitter_perl", "extensions": ["pl","pm","t"]}})`
  then `find_all(kind="package_statement" | "use_statement" |
  "subroutine_declaration_statement")` all match; `find_all(pattern="sub
  $NAME { $$$ }")` returns `[]` → **Perl: `kind` rules only**.
- `nm -D` on the installed wheel: `_binding.abi3.so` exports `T tree_sitter_perl`.
- `find_all(kind="no_such_kind")` → `RuntimeError: cannot get matcher`
  (ordinary exception).
- Naïve join of `get_multiple_matches("ARGS")` yields `utility_helper(1, ,,
  b=2)`; filtering `is_named()` yields `1, b=2`.

### Verified Codebase References

All paths relative to `packages/ai-parrot/src/parrot/` unless noted.
Verified on `dev` @ `d46d2d57e`, 2026-09-02.

#### Classes & Signatures
```python
# From knowledge/wiki/languages/base.py:21
class LanguageOutline(BaseModel):
    summary: str = ""                                   # line 36
    outline: list[str] = Field(default_factory=list)    # line 37
    imports: list[str] = Field(default_factory=list)    # line 38

# From knowledge/wiki/languages/base.py:40
class LanguageScanner(ABC):
    name: ClassVar[str]; suffixes: ClassVar[frozenset[str]]
    def outline(self, source: str, rel_path: str) -> LanguageOutline: ...            # line 58 (must never raise)
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...            # line 76
    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None:   # line 94
    @property
    def mode(self) -> str: ...   # "ast" | "tree-sitter" | "heuristic"             # line 113

# From knowledge/wiki/languages/__init__.py:33
_SCANNERS: dict[str, LanguageScanner] = {"python": PythonScanner(), "php": PhpScanner(),
    "javascript": JavaScriptScanner(), "rust": RustScanner(), "perl": PerlScanner()}
def scanner_for(suffix: str) -> LanguageScanner | None: ...   # line 47
def all_scanners() -> dict[str, LanguageScanner]: ...
def scanned_suffixes() -> frozenset[str]: ...
def set_scan_root(root: Path) -> None / def get_scan_root() -> Path | None

# From knowledge/wiki/languages/treesitter.py:64
def get_parser(language: str) -> Parser | None: ...   # cached, never raises; _build_parser at line 86

# Scanner classes: python.py:30 PythonScanner (outline :36, mode :138); php.py:128 PhpScanner (outline :136);
# javascript.py:492 JavaScriptScanner (outline :505); rust.py:127 RustScanner (outline :135);
# perl.py:196 PerlScanner (outline :204, mode :515)
def _head2_docs(source: str) -> dict[str, str]: ...                       # perl.py:118  → `pod_head2` extractor
def _extract_script_blocks(source: str, suffix: str) -> tuple[str, str | None]: ...   # javascript.py:187

# From knowledge/wiki/repo_scan.py
class FileSlice(BaseModel):            # line 159
    rel_path: str; record: WikiPageRecord
    imports: list[str] = Field(default_factory=list); language: str | None = None
class RepoScan(BaseModel):             # line 182
    root: Path; files: list[FileSlice]; dir_records: list[WikiPageRecord]
    dir_edges: list[tuple[str, str, str]]; import_edges: list[tuple[str, str, str]]; skipped: list[str]
def file_concept_id(rel_path: str) -> str: ...      # line 249  ("file:<rel>")
def dir_concept_id(rel_path: str) -> str: ...       # line 254
def is_wiki_relevant(...)                           # line 202
def is_inside_wiki_bundle(root: Path, rel_path: str) -> bool   # line 327
def build_file_slice(root: Path, rel_path: str, body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
                     max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> FileSlice | None   # line 556
    # calls scanner_for(suffix).outline(content, rel_path) inside try/except Exception; renders
    # "## API outline\n" + "\n".join(lang_outline.outline) into the body (lines ~586-608)
def build_import_edges(files: list[FileSlice], index_paths: Iterable[str] | None = None) -> list[tuple[str, str, str]]   # line 718
def scan_repository(root: Path, suffixes=None, exclude_dirs=None, body_max_chars=..., max_file_bytes=...,
                    use_git: bool = True, rel_paths: Iterable[str] | None = None) -> RepoScan   # line 776
DEFAULT_EXCLUDE_DIRS: frozenset[str]   # line 85

# From knowledge/wiki/store.py
SCHEMA_VERSION = "1"                                   # line 46
WIKI_SCHEMA_SQL = """..."""                            # line 50; pages(concept_id, node_id, title, category, summary,
                                                       #   body, source_id, token_count, created_at, updated_at, origin, asserted_by)
                                                       #   edges(src, dst, rel, provenance) PK(src,dst,rel); pages_fts(fts5); embeddings
_MIGRATION_COLUMNS = {"pages": [("origin", ...), ("asserted_by", "TEXT")]}   # line 131 — idempotent ALTER model
class WikiPageRecord(BaseModel):                       # line 224
    concept_id: str; node_id: Optional[str]; title: str; category: str = "concept"; summary: str; body: str
    source_id: Optional[str]; token_count: int; origin: str = "ingest"; asserted_by: Optional[str]; updated_at: Optional[str]
class BaseWikiStore(ABC):                              # line 332
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int                 # line 351
    async def add_edges(self, edges: list[tuple]) -> int                             # line 354  (3- or 4-tuples w/ provenance)
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord],
                                   edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]   # line 357
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict]   # line 372
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict]   # line 383
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict]   # line 389
    async def stats(self) -> dict[str, Any]           # line 403
    async def broken_edges(self) -> list[dict[str, Any]]   # line 410
class SQLiteWikiStore(BaseWikiStore):                  # line 488;  async def _migrate(self, conn) at line 818
# arango_store.py:128 ArangoDBWikiStore ; file_store.py:71 InMemoryWikiStore (_write_page_file :208 serialises YAML frontmatter)

# From knowledge/wiki/sources.py
class SourceCollectionManager:                         # line 107
    def is_stale(self, source_id: str) -> bool         # line 528
    def _compute_hash(self, path: Path) -> str         # line 1115 — SHA-1 hex, 8 KiB chunks

# From knowledge/wiki/tools.py
class WikiQueryTool(AbstractTool):                     # line 155 — name/description/args_schema class attrs,
    def __init__(self, store: BaseWikiStore)           #   super().__init__(name=..., description=...); async def _execute(...)
def create_wiki_tools(store: BaseWikiStore, root: Path | None = None,
                      config: WikiProjectConfig | None = None) -> list[AbstractTool]   # line 541

# From knowledge/wiki/mcp_server.py:90
def create_wiki_mcp_server(root: Path) -> StdioMCPServer   # load_effective_config(root).config → store → FederatedWikiStore
                                                           # → create_wiki_tools(...) → server.register_tools(tools)
# From knowledge/wiki/toolkit.py:54
class LLMWikiToolkit(AbstractToolkit):  tool_prefix: str = "wiki"   # line 81

# From tools/toolkit.py:206
class AbstractToolkit(ABC):
    tool_prefix: str | None = None                     # line 257
    confirming_tools: frozenset = frozenset()          # line 275 → sets tool.routing_meta["requires_confirmation"] = True (line 686-689)
# From tools/abstract.py
class ToolResult(BaseModel)                            # line 250
class AbstractTool(EventEmitterMixin, ABC)             # line 281; self.routing_meta: Dict (line 373)
# From mcp/adapter.py:8
class MCPToolAdapter  — _requires_confirmation() reads routing_meta["requires_confirmation"] (line 23)

# From knowledge/wiki/context.py
_ID_KINDS = "file|dir|mod|pkg|doc|func|class|concept|page"   # line 38 — no `sym` yet
def split_namespaced_id(page_id: str) -> tuple[str | None, str]   # line 54
def pack_results(...)                                  # line 203
def truncate_to_tokens(text: str, max_tokens: int | None) -> tuple[str, bool]   # line 272
DEFAULT_BUDGET_TOKENS = 1200                           # line 108

# From knowledge/graphindex/schema.py:64
class EdgeKind(str, Enum): CONTAINS, REFERENCES, DEFINES, MENTIONS, EXPLAINS, EXTENDS, PRODUCED, ABOUT, SUPPORTED_BY, CONTRADICTS

# From knowledge/wiki/cli.py
async def _ingest_files(store: BaseWikiStore, sources: SourceCollectionManager, root: Path,
                        scan: Any, force: bool = False) -> dict[str, int]   # line 622
def _changed_files_from_git(root: Path) -> list[str]   # line 1335; `upsert --changed` flag at 1384, used at 1421;
                                                       # upsert path: wiki_write_lock → is_wiki_relevant filter → scan_repository(rel_paths=existing)

# From knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):   # fields at lines 401-422: wiki_name, storage_dir, backend, include_suffixes,
                                      # exclude_dirs, body_max_chars, max_file_kb, claude, sync_graph, arango_*, vault_dir
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig   # line 813
def find_project_root(start: Path | None = None) -> Path | None                        # line 625
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]           # line 65

# From knowledge/wiki/claude_code/assets.py
def mcp_json_entry(root: Path) -> dict          # line 99
def git_hook_block(root: Path) -> str           # line 151
def permission_rules(root: Path) -> tuple[str, ...]   # line 169
```

#### Verified Imports
```python
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner   # languages/__init__.py:14
from parrot.knowledge.wiki.languages import scanner_for, all_scanners, scanned_suffixes  # languages/__init__.py:21-29 (__all__)
from parrot.knowledge.wiki.languages import treesitter                              # tests/.../conftest.py (monkeypatch target)
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, SQLiteWikiStore
from parrot.knowledge.wiki.repo_scan import FileSlice, RepoScan, scan_repository, build_import_edges, file_concept_id
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.tools import create_wiki_tools
from parrot.knowledge.wiki.project import load_effective_config, WikiProjectConfig, wiki_write_lock
from parrot.knowledge.graphindex.schema import EdgeKind
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.toolkit import AbstractToolkit
from parrot.mcp.local_server import StdioMCPServer           # mcp_server.py (imported lazily under redirect_stdout)
import tree_sitter_perl  # installed 1.2.1; package dir contains _binding.abi3.so exporting `tree_sitter_perl`
```

#### Key Attributes & Constants
- `WikiPageRecord.category` is an open string → `"symbol"` needs no enum change (store.py:227).
- `edges.provenance` column already exists with default `'extracted'` (store.py DDL) → `inferred` needs no schema change.
- `pyproject` extras: `wiki-languages` at `packages/ai-parrot/pyproject.toml:248-255`; meta-extra `wiki` at 269-272 — `wiki-structural` slots beside them.
- Installed: `tree-sitter 0.26.0`, `tree-sitter-perl 1.2.1`, `tree-sitter-php 0.24.1`, `tree-sitter-typescript 0.23.2`, `tree-sitter-javascript 0.25.0`, `tree-sitter-rust 0.24.2`, `tree-sitter-python 0.25.0`. **`ast-grep-py` is NOT installed** in the project venv.
- `tests/knowledge/wiki/languages/conftest.py:11` `force_heuristic` fixture monkeypatches `treesitter.get_parser` → model for a `force_no_astgrep` fixture.
- In-flight features touching shared files: **FEAT-495** (`portable-wikitoolkit-config-paths`, 2 open tasks) edits `claude_code/assets.py` / `.mcp.json.example`; **FEAT-481** (fireflies, 16 open) is ingestion-side, no overlap with scanners/store schema expected.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.knowledge.wiki.symbols`~~, ~~`parrot.knowledge.wiki.structural`~~ (package), ~~`languages/astgrep.py`~~, ~~`languages/render.py`~~, ~~`languages/rules/`~~ — all new in this feature.
- ~~`SymbolRecord`~~, ~~`SymbolRef`~~, ~~`SymbolKind`~~, ~~`StructuralOutline`~~, ~~`sym_concept_id()`~~, ~~`render_outline()`~~ — do not exist anywhere in `parrot/` (grep verified).
- ~~`LanguageOutline.symbols`~~, ~~`LanguageOutline.refs`~~, ~~`FileSlice.symbols`~~, ~~`RepoScan.symbol_records`~~ — not present.
- ~~`pages.content_hash`~~ column, ~~`symbols`~~ / ~~`symbols_fts`~~ tables, ~~`BaseWikiStore.page_hashes / find_symbols / upsert_symbols / symbols_for / search_symbols_fts`~~ — not present; `SCHEMA_VERSION` is `"1"`.
- ~~`EdgeKind.CALLS`~~, ~~`EdgeKind.IMPLEMENTS`~~ — enum has `EXTENDS` and `DEFINES` but neither of these.
- ~~`sym` in `context._ID_KINDS`~~ — currently `file|dir|mod|pkg|doc|func|class|concept|page` (`func`/`class` exist as id kinds but no page producer emits them today).
- ~~`WikiProjectConfig.symbol_depth`~~, ~~`.structural_backend`~~ — not present.
- ~~`wiki-structural`~~ extra — not in `pyproject.toml`; `ast-grep-py` is not a dependency anywhere.
- ~~`tree_sitter.Query` usage in any scanner~~ — all five walk `node.children` manually.
- ~~`StructuralService`~~, ~~`create_structural_tools()`~~, ~~`CodeStructuralToolkit`~~, ~~`wikitoolkit symbols`~~ CLI group — new.
- ~~`ast_grep` / `ast_edit` / `EditPlan` / `plan_token`~~ — **deliberately out of scope** (follow-up feature); nothing in this feature may write to the working tree.
- ~~`ClaudeCodeDispatcher` passing `mcp_servers`~~ — dev_loop integration is out of scope (design Sprint 4); do not touch `flows/dev_loop/`.
- ~~`code_ast`~~ package — rejected in the design; do not add.

---

## Parallelism Assessment

- **Internal parallelism**: moderate. Three clusters are independent after
  the models land: (1) `symbols.py` + `LanguageOutline` extension +
  `astgrep.py` seam + `render.py`; (2) per-language rule files
  (`typescript`, `php`, `rust`, `perl`, `python` refs) — each is a separate
  YAML + parity test with no shared code beyond the loader; (3) store schema
  v2 + `repo_scan` sym pages/edges + `SymbolResolver` + read-repair; then
  (4) `StructuralService` + tools + toolkit + MCP/CLI registration depends
  on (3). Cluster (2) tasks could run in parallel worktrees, but they all
  edit `languages/<lang>.py` to wire the seam, and the parity fixtures share
  `conftest.py`.
- **Cross-feature independence**: shared file with **FEAT-495**
  (`claude_code/assets.py::permission_rules`, `.mcp.json.example`) — small
  additive change here; land FEAT-495 first or rebase the one hunk. No
  overlap with FEAT-481. `store.py` schema bump is the highest-contention
  file in the wiki subsystem; no other open spec touches it today.
- **Recommended isolation**: `per-spec`.
- **Rationale**: the feature's value is the *contract* between layers
  (`SymbolRecord` shape → rules → store → tools). Splitting across worktrees
  risks three agents defining that contract three ways; sequential tasks in
  one worktree with the models task first keep it single-sourced. Rule
  files are the one place a task author may mark tasks as parallel-safe
  within the worktree if the sdd-worker pool is used.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus*: `type: feature`, `base_branch: dev`.
- [x] Scope of this feature vs. the design's roadmap — *Owner: Jesus*: Sprint 1 + Sprint 2 (backend, symbols, hash + read-repair, `SymbolResolver`, read-only tools). `ast_grep`/`ast_edit` (Sprint 3) and dev_loop wiring (Sprint 4) are follow-up features.
- [x] Python source of truth — *Owner: Jesus*: stdlib `ast` remains authoritative; ast-grep only adds byte offsets and `calls` refs. Python `sym:` pages therefore exist without any extra.
- [x] Perl via dynamic registration — *Owner: Jesus*: yes, `kind` rules only, silent fallback to the current walker (re-verified: patterns return nothing, `.so` exports `tree_sitter_perl`).
- [x] Outline parity policy — *Owner: Jesus*: strict byte-parity; extra symbols live only in `symbols`/`sym:` pages.
- [x] Tool surfaces — *Owner: Jesus*: MCP (`wikitoolkit mcp`) **and** `CodeStructuralToolkit`; one `StructuralService`.
- [x] Backend coverage — *Owner: Jesus*: SQLite gets `symbols` table + FTS + `content_hash`; Arango/OKF persist `sym:` pages via existing `upsert_pages`/`add_edges` and use default `BaseWikiStore` symbol methods over pages.
- [x] Default symbol depth — *Owner: Jesus*: top-level + direct members (≤ 2), `symbol_depth` config.
- [ ] Should `content_hash` be a new `pages` column, or should read-repair compare against the existing `sources.file_hash` (same SHA-1, already maintained by `SourceCollectionManager`) joined through `pages.source_id`? A column avoids a join and covers `sym:` pages; reusing `sources` avoids a schema change. — *Owner: spec author*
- [ ] Should `wiki_query` include `category="symbol"` stubs by default, or exclude them unless asked (`include_symbols=True`), to keep file/doc results from being flooded by one symbol per method? — *Owner: Jesus*
- [ ] Are `EdgeKind.CALLS` / `IMPLEMENTS` required now (GraphIndex mirror via `sync_graph`) or is the wiki-side `rel` string enough until the mirror is exercised? — *Owner: spec author*
- [ ] MCP tool naming: bare `symbol_lookup` / `code_outline` / `blast_radius` (as in the design) vs. `wiki_`-prefixed for consistency with the existing six tools and `permission_rules()` globs. — *Owner: Jesus*
- [ ] Duplicate-qualname id policy (`#2` suffix in source order) — accept, or prefer including the start line in the id (`sym:<rel>#<qualname>@L12`), which is unstable across edits? — *Owner: spec author*
- [ ] Read-repair when `wiki_write_lock` is held by a build: serve stale with `stale=True` (proposed) vs. wait up to N seconds. — *Owner: spec author*
- [ ] Where do the rule YAML files ship: package data under `languages/rules/` (proposed) vs. a user-overridable `.parrot/wiki/rules/` overlay for project-specific symbols? v1 proposes package data only. — *Owner: Jesus*
