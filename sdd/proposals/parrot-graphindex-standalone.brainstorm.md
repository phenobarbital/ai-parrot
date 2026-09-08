---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: `parrot-graphindex` — standalone GraphIndex + LLM Wiki distribution

**Date**: 2026-09-03
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

`wikitoolkit` (LLM wiki) and GraphIndex are the parts of AI-Parrot that a
developer can use *without* an agent: point them at a repository, run
`wikitoolkit build`, and get a queryable knowledge graph plus a local MCP
server for Claude Code / Codex. Tools in the same space — `graphify`,
`zvec-grep` — install in one `pip install` and work in seconds.

Today that use case is impossible without installing the whole framework:

- `wikitoolkit` ships from the `ai-parrot` core distribution, which declares
  **55 runtime dependencies** (navigator-api, navigator-auth, pandas, pyarrow,
  faiss-cpu, sqlglot, …) and a `parrot.conf` settings module with import-time
  side effects (Navigator startup banner, settings dir, Google model import).
- A cold `import parrot.knowledge.wiki.cli` loads **1930 modules** including
  navconfig, `parrot.conf`, navigator_eventbus, aiohttp, asyncdb, pandas,
  pyarrow, faiss, redis and asyncpg — none of which `wikitoolkit build` uses.

The measured cause (branch `exp-lazy-ontology`, commit `c4555d7d1`,
`artifacts/logs/lazy-ontology-import-measurement.md`, wiki memory
`mem-37597ac72bbd`) is **not** the wiki/graphindex code itself. It is two eager
package roots that the graph code crosses to fetch a Pydantic model or a
dataclass:

| Gateway | Trigger | Drags in |
|---|---|---|
| `parrot/knowledge/ontology/__init__.py` | `from ontology.schema import TenantContext` (7 top-level imports in graphindex) | `mixin` → bots → clients → `parrot.conf` → navconfig, navigator_eventbus, aiohttp, pandas, faiss |
| `parrot/stores/__init__.py` | `from parrot.stores.models import Document` (`graphindex/extractors/loader.py`) | `stores.abstract` → `parrot.conf` |
| `wiki/documents.py` | top-level `import aiohttp` with a single use | aiohttp |

With PEP 562 lazy roots for the two packages plus a lazy aiohttp import, the
same CLI import drops to **813 modules** and none of the framework surfaces
above are loaded:

| Import | dev (before) | lazy ontology | + lazy stores + lazy aiohttp |
|---|---:|---:|---:|
| `parrot.knowledge.ontology.schema` | 1535 | 220 | 220 |
| `parrot.knowledge.graphindex` | 1894 | 1224 | 776 |
| `parrot.knowledge.graphindex.builder` | 2864 | 1230 | 1173 (still loads `parrot.conf`) |
| `parrot.knowledge.wiki.cli` | 1930 | 1351 | 813 |

The remaining third-party floor for the SQLite plane is: pydantic, PyYAML,
rustworkx, networkx, numpy, pathspec, aiosqlite, orjson, click. (`hyperscan`
and `re2` also appear: they are *optional pathspec backends* auto-detected by
pathspec ≥1.1, not parrot dependencies.)

What laziness cannot fix is the set of **true seams** — places where the graph
code inherits from or calls framework classes:

- `graphindex/builder.py:55` → `PageIndexToolkit` → `AbstractToolkit` → `parrot.conf`
- `graphindex/embed.py:15,17` → `EmbeddingRegistry`, `quiet_faiss_loader`
- `wiki/triage.py:41-42` → `GroundingEvaluator`, `PageIndexLLMAdapter` → `AbstractClient`
- `wiki/tools.py`, `wiki/toolkit.py`, `wiki/structural/*` → `AbstractTool`/`AbstractToolkit`
- `wiki/mcp_server.py:90` → `StdioMCPServer` (`parrot.mcp.local_server`) → `MCPToolAdapter` → `AbstractTool`
- `wiki/vault_scan.py`, `obsidian_sync.py` → `parrot.interfaces.obsidian`
- `wiki/jira_sync.py`, `jira_render.py` → `parrot.interfaces.jira`
- `graphindex/loader.py:31-35` → `AbstractLoader`, `Document`, `OntologyGraphStore`

**Who is affected**: external developers who want "a knowledge graph of my
repo" without adopting an agent framework; the repo's own Claude Code hook,
which imports `wiki/project.py` on every PreToolUse and is already written to
be dependency-light for exactly this reason; and the maintainers, because the
`ai-parrot` core keeps absorbing graph-only dependencies (FEAT-471 moved
rustworkx/networkx/pathspec/aiosqlite/orjson *into* core because the CLI
imports them unconditionally).

## Constraints & Requirements

Decisions taken during discovery (this session) — treat as fixed:

- **Distribution** `parrot-graphindex`, **import name** `parrot_graphindex`,
  living at `packages/parrot-graphindex/` in the uv workspace, released in
  lockstep by `/release` (added to `scripts/release.py` `PACKAGES`, line 109 —
  a package missing there strands at its initial version, as `parrot-codec` did).
- **One distribution**, not two: `wiki/` has 18 hard imports of `graphindex/`;
  they are not separable.
- **Dependency direction is inverted**: `parrot-graphindex` must have **zero**
  dependency on `ai-parrot`; `ai-parrot` core depends on `parrot-graphindex`.
  Note this is *new* for the workspace: `ai-parrot-tools` and
  `ai-parrot-loaders` are top-level packages but both declare
  `dependencies = ["ai-parrot", …]` (`packages/ai-parrot-tools/pyproject.toml`).
  `parrot-graphindex` would be the first leaf that core depends on.
- **Not** a PEP 420 satellite under `parrot.*`: every satellite depends on core,
  and any `from parrot.tools.abstract import …` inside a `parrot.*` module
  brings the framework back.
- **Backward compatibility** via a `sys.meta_path` finder redirecting
  `parrot.knowledge.graphindex.*` / `parrot.knowledge.wiki.*` (and the moved
  `okf`, `ontology.schema`, pageindex core) to `parrot_graphindex.*`, following
  `_ParrotToolsRedirector` in `parrot/tools/__init__.py:50`. No stub modules.
- **navconfig stays**, as an *optional, lazily imported* credential provider —
  the pattern `wiki/project.py:499 _navconfig()` already implements (`os.environ`
  first, navconfig second, tolerant to a broken env). It becomes an explicit
  dependency of the `[postgres]` and `[arangodb]` extras (asyncdb 2.15.10 does
  **not** pull it), never of the base install. `parrot.conf` and
  `navconfig.logging` never enter the standalone.
- **asyncdb stays** as the driver behind the Arango and Postgres planes
  (`wiki/arango_store.py:34 AsyncDB("arangodb", …)`); it is a dependency of the
  backend extras only.
- **pageindex is split**: pure core (tree builder, `md_builder`, `store`,
  `content_store`, `tree_ops`, `schemas`, `retriever`, `vector_walk`,
  `embedding_store`, `utils`) moves to the standalone; `toolkit.py`
  (`AbstractToolkit`), `llm_adapter.py` (`AbstractClient`), `loader.py`
  (`AbstractLoader`) and `pdf_to_markdown.py` (pymupdf) stay in core or become
  extras.
- **LLM-dependent CLI commands** (`ingest` with `LLMGraphExtractor`, triage,
  `ingest-jira`) are exposed through a `LLMCaller` Protocol. Without a
  registered caller the standalone hides/declines them with a clear message;
  with `ai-parrot` installed, core registers its client via an entry point.
  The standalone never imports an LLM SDK.
- **Two features, not one**: FEAT-A reshapes the seams *inside* core (Protocols,
  toolkits → `parrot_tools`, `resolve_setting()`, lazy roots); FEAT-B performs
  the physical move once the tree is `git mv`-shaped.
- **The `exp-lazy-ontology` worktree is discarded**; FEAT-A re-does the lazy
  roots inside its own worktree (the evidence log is what carries forward).
- **FEAT-520 `graphindex-postgres-backend`** is in flight and will land on core
  first (`persist_postgres.py`, `pg_schema.py`, `wiki/postgres_store.py`, …).
  It moves with FEAT-B; FEAT-B must not start before FEAT-520 merges.
- Existing planes under `~/.parrot/wikis/*/wiki.db` built by today's core must
  remain readable by the standalone (same SQLite schema, same
  `pages.content_hash` migration rules) — no plane rebuild forced by the move.
- The CLI entry points `wikitoolkit` and `parrot-graphindex` move with the
  package. The Claude Code and Codex managed assets reference only the command
  name (`claude_code/assets.py` 66 occurrences, `codex/assets.py` 13) and need
  no change.

---

## Options Explored

### Option A: PEP 420 satellite `ai-parrot-graphindex` (same `parrot.knowledge.*` paths)

Mirror `ai-parrot-embeddings`: a satellite distribution whose `src/parrot/`
has no `__init__.py` and contributes `parrot.knowledge.graphindex`,
`parrot.knowledge.wiki`, `parrot.knowledge.okf`. Import paths stay identical,
no shim needed.

✅ **Pros:**
- Zero import-path churn; every caller and doc stays valid.
- Precedent already exists (FEAT-201) with `[tool.setuptools.packages.find] namespaces = true`.

❌ **Cons:**
- Does not achieve the goal. Satellites declare `dependencies = ["ai-parrot"]`
  and rely on core's `parrot/__init__.py` (`extend_path`). The framework is
  still installed; only ownership of files changes.
- Keeping the code under `parrot.*` invites the exact regressions measured
  here: one `from parrot.tools.abstract import …` re-imports the world.
- `parrot.knowledge` has no `__init__` in core today, but `parrot.stores` and
  `parrot.knowledge.ontology` do; the same eager-root problem persists.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| setuptools namespaces | PEP 420 merge | already used by `ai-parrot-embeddings` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-embeddings/pyproject.toml:108-111` — namespace package config.

---

### Option B: Top-level leaf `parrot_graphindex`, core depends on it, two-phase delivery ✅

A new workspace member `packages/parrot-graphindex/` providing the top-level
package `parrot_graphindex` with subpackages `graph/` (today's graphindex),
`wiki/`, `okf/`, `pageindex/` (pure core only), and `ontology/schema.py`.
Base dependencies are the measured floor (pydantic, PyYAML, rustworkx,
networkx, numpy, pathspec, aiosqlite, orjson, click). Everything that touches a
framework class is replaced by a Protocol the framework implements, or moved
to where the framework code already lives (`parrot_tools`).

Delivered as two FEATs:

**FEAT-A — "graph seams in core"** (no new package yet):
1. PEP 562 lazy roots for `parrot/knowledge/ontology/__init__.py` and
   `parrot/stores/__init__.py`; lazy aiohttp in `wiki/documents.py`.
   Acceptance: `import parrot.knowledge.wiki.cli` ≤ 850 modules and does not
   load navconfig / `parrot.conf` / navigator_eventbus / asyncdb / pandas / faiss.
2. Protocols in `parrot/knowledge/graphindex/protocols.py`: `Embedder`
   (`embed_nodes`), `LLMCaller` (`ask`, `ask_structured`, `ask_json` — the
   subset of `PageIndexLLMAdapter` that wiki/graphindex call), `PageIndexer`
   (what `GraphIndexBuilder` needs from `PageIndexToolkit`). `GraphIndexBuilder`,
   `NoveltyScorer`, `IngestTriageRouter` accept the Protocols; concrete
   framework classes are injected by `factory.py` / the CLI when available.
3. Move `LLMWikiToolkit`, `WikiQueryTool`…`WikiNoteTool`,
   `CodeStructuralToolkit` and the structural tools to
   `parrot_tools/wiki/` (precedent: `GraphIndexToolkit` at
   `parrot_tools/graphindex/toolkit.py:72`). They call plain wiki service
   functions; nothing in `knowledge/wiki` imports `parrot.tools` afterwards.
4. Single `resolve_setting(key, *, default, explicit=None)` in
   `wiki/project.py` replacing `_env_setting` (`cli.py:464`), the local
   navconfig import in `graphindex/loader.py:337`, and `_env_credential`
   (`project.py:529`). Order: explicit argument → `os.environ` → navconfig if
   importable → `wiki.json` defaults.
5. MCP: `wiki/mcp_server.py` gains a `mcp`-SDK stdio path (`mcp` 1.29.0 is
   already installed) selected when `parrot.mcp` is not importable; the
   `StdioMCPServer`/`MCPToolAdapter` path stays for in-framework use.
6. Minimal `Document`, `Loader` shapes for `graphindex/extractors/loader.py`
   and `graphindex/loader.py` so they no longer import `parrot.stores.models`
   / `parrot.loaders.abstract`; core adapters convert.
7. `ontology/schema.py` becomes import-clean (it already is: only pydantic +
   re); `OntologyGraphStore` use in `graphindex/persist.py` / `loader.py`
   moves behind the `[arangodb]` seam.

**FEAT-B — "physical move"** (after FEAT-520 merges):
1. `git mv` into `packages/parrot-graphindex/src/parrot_graphindex/`;
   `pyproject.toml` with extras `[postgres]` (asyncpg, pgvector via asyncdb,
   navconfig), `[arangodb]` (asyncdb, navconfig), `[obsidian]` (marko,
   python-frontmatter, `interfaces/obsidian` moved), `[mcp]` (mcp),
   `[languages]`, `[structural]`, `[leiden]`, `[pdf]` (pymupdf); scripts
   `wikitoolkit`, `parrot-graphindex`.
2. `_ParrotGraphindexRedirector` meta_path finder in core mapping the old
   dotted paths; core `pyproject.toml` gains `parrot-graphindex` as a runtime
   dependency and drops rustworkx/networkx/pathspec/aiosqlite/orjson from its
   own list (they arrive transitively).
3. Entry point group `parrot_graphindex.providers` through which core
   registers `LLMCaller`, `Embedder`, `PageIndexer` implementations and the
   Arango/Postgres wiki backends (`register_wiki_backend`, `store.py:401`).
4. Tests move with the code; `scripts/release.py` `PACKAGES` gains the new
   package; docs (`docs/graphindex.md`, `docs/wiki-claude-code.md`,
   `docs/guides/llm-wiki-guide.md`) updated to `uv pip install parrot-graphindex`.

✅ **Pros:**
- Achieves the goal outright: `uv pip install parrot-graphindex` → ~10
  third-party packages → `wikitoolkit build` works.
- FEAT-A alone already pays back in the monorepo (Claude Code hook, faster
  `wikitoolkit`, smaller core dependency list) and is mergeable on its own.
- Each seam has a measured owner; the acceptance criteria are module counts,
  which CI can assert.
- The meta_path shim is a known, tested pattern in this repo.

❌ **Cons:**
- Inverts a dependency arrow for the first time in the workspace; CI and
  `uv sync` must build `parrot-graphindex` before `ai-parrot`.
- ~60k lines move in FEAT-B; any long-lived branch touching
  `knowledge/wiki` or `knowledge/graphindex` (FEAT-481, FEAT-520) must merge
  first or rebase across a rename.
- Protocol injection adds indirection to `factory.py` / the CLI.

📊 **Effort:** High (FEAT-A Medium, FEAT-B High)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `rustworkx` 0.18.1 | graph core | base |
| `networkx` 3.4.2 | Louvain fallback, export | base |
| `pydantic` 2.13.5 | schemas | base |
| `aiosqlite` 0.22.1 | SQLite plane | base |
| `orjson` 3.12.0, `PyYAML`, `pathspec` 1.1.1, `click` 8.4.2, `numpy` 2.5.2 | serialization, ignore rules, CLI, hashing embedder | base |
| `mcp` 1.29.0 | stdio MCP server without `parrot.mcp` | `[mcp]` |
| `asyncdb` 2.15.10 | Arango / Postgres drivers | `[arangodb]`, `[postgres]` |
| `navconfig` 2.4.1 | `.env` / Vault credential provider | `[arangodb]`, `[postgres]`; 541 modules on its own, acceptable for DB planes |
| `marko` 2.2.4, `python-frontmatter` 1.3.0 | Obsidian vault parsing | `[obsidian]` |
| `tree-sitter` 0.26.0 + grammars, `ast-grep-py` 0.45.3 | language scanners | `[languages]`, `[structural]` |
| `leidenalg` 0.12.0, `igraph` 1.0.0 | Leiden communities | `[leiden]` |
| `pymupdf` 1.27.1 | PDF → markdown for pageindex | `[pdf]` |

🔗 **Existing Code to Reuse:**
- `parrot/tools/__init__.py:31-136` — `_AliasLoader` + `_ParrotToolsRedirector` meta_path finder, the compat mechanism to clone.
- `parrot/knowledge/wiki/project.py:499-558` — `_navconfig()`, `_env_credential()`, `resolve_arango_params()` — the tolerant credential resolution to generalise.
- `parrot/knowledge/wiki/store.py:401` — `register_wiki_backend(name, factory)` — the backend registry the extras plug into.
- `parrot_tools/graphindex/toolkit.py:72` — `GraphIndexToolkit(AbstractToolkit)` — precedent for agent-facing toolkits living in `parrot_tools`.
- `parrot/knowledge/pageindex/llm_adapter.py:42-201` — `PageIndexLLMAdapter.ask/ask_structured/ask_with_finish_info/ask_json` — the surface the `LLMCaller` Protocol mirrors.
- `parrot/knowledge/graphindex/embed.py:25-58` — `GraphIndexEmbedder.embed_nodes` — the surface the `Embedder` Protocol mirrors.
- `packages/ai-parrot-tools/pyproject.toml` — workspace member layout (`[tool.uv.sources] ai-parrot = { workspace = true }`), to mirror in reverse.

---

### Option C: Slim the `ai-parrot` core itself (dependency demotion, no new package)

Keep the code where it is; shrink core's `dependencies` to the measured floor
and demote everything else (navigator-*, pandas, pyarrow, faiss, sqlglot, …) to
extras such as `ai-parrot[agents]`. `pip install ai-parrot` would then be the
"graph-only" install.

✅ **Pros:**
- No move, no shim, no dependency inversion.
- Forces a healthy audit of core's 55 dependencies.

❌ **Cons:**
- `parrot.conf`, `parrot.tools.abstract`, `parrot.clients` are imported at
  module level across core; a bare install would break on first agent import
  with `ModuleNotFoundError` deep in the stack. Every satellite's `ai-parrot`
  dependency would need to become `ai-parrot[agents]`.
- Product identity stays wrong: users still install "an agent framework" to
  get a graph tool; discoverability (`pip install parrot-graphindex`) is lost.
- The eager-root and seam work of FEAT-A is required anyway.

📊 **Effort:** Medium

📦 **Libraries / Tools:** same base floor as Option B; no new packages.

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/pyproject.toml:170-300` — existing extras ladder (`graphindex`, `wiki-languages`, `wiki-structural`, `leiden`, `wiki`).

---

### Option D: Separate repository built by vendoring (graphify-style)

Publish `parrot-graphindex` from its own repository, with a sync script that
copies `knowledge/wiki`, `knowledge/graphindex`, `okf` out of the monorepo at
release time and rewrites imports.

✅ **Pros:**
- Cleanest external story: a small repo, its own issues, its own README.
- No workspace dependency inversion.

❌ **Cons:**
- Two sources of truth; import-rewriting scripts are fragile and the seams
  (Protocols, toolkits) still have to be cut in the monorepo first.
- Contradicts the lockstep `/release` decision and the `release.py` PACKAGES
  model.
- Test duplication.

📊 **Effort:** High (ongoing)

📦 **Libraries / Tools:** same as Option B plus a sync tool.

🔗 **Existing Code to Reuse:** none beyond Option B.

---

## Recommendation

**Option B** is recommended because it is the only option that both meets the
user-facing goal (`uv pip install parrot-graphindex` with ~10 packages) and
keeps one source of truth inside the workspace. Option A changes file
ownership without changing what gets installed, which the measurements show is
the actual problem. Option C does most of Option B's seam work but leaves the
product under the wrong name and makes every satellite's dependency line more
complex. Option D solves packaging by duplication.

The trade-off accepted is the dependency inversion (core → `parrot-graphindex`),
a first for the workspace. It is contained: the leaf package is import-clean by
construction, the shim is a known pattern, and the two-FEAT split means the
risky move happens only after core already compiles against Protocols and
after FEAT-520 has landed.

---

## Feature Description

### User-Facing Behavior

- `uv pip install parrot-graphindex` installs ~10 third-party packages. Then:
  `wikitoolkit build`, `query`, `page`, `related`, `remember`, `note`, `link`,
  `memories`, `audit`, `status`, `export`, the `symbols` group
  (`lookup`/`outline`/`blast`), the `ns` group (`list`/`add`/`remove`) and
  `mcp` work against the SQLite plane with no `.env`, no framework, no LLM.
- `uv pip install "parrot-graphindex[postgres]"` or `[arangodb]` enables the
  DB planes and `wikitoolkit sync push/pull`. Credentials resolve as today:
  explicit flag → `os.environ` → navconfig (`env/{ENV}/.env`) → `wiki.json`.
  Missing credentials produce one actionable message naming the key and the
  resolution order that was tried, never a loopback default.
- `[obsidian]` enables `wikitoolkit sync obsidian` and vault ingest; `[mcp]`
  serves the same tool set over stdio using the `mcp` SDK, so
  `.claude/settings.local.json` / `.mcp.json` entries keep their shape
  (`"command": "wikitoolkit", "args": ["mcp"]`).
- Commands that need an LLM (`ingest` with extraction, triage, `ingest-jira`)
  are listed with a `(requires an LLM provider — install ai-parrot)` note and
  exit with code 2 and that message when invoked without one.
- With `ai-parrot` installed nothing changes for agents: `from
  parrot.knowledge.wiki import …` still resolves (via the finder),
  `LLMWikiToolkit` / `CodeStructuralToolkit` come from `parrot_tools.wiki`,
  and the `wikitoolkit` command is the same binary.

### Internal Behavior

- `parrot_graphindex` is a leaf: no `parrot.*` import anywhere in its tree
  (enforced by a test that greps the package and by an import-count test
  asserting the module ceiling).
- Providers are Protocols declared in `parrot_graphindex.protocols`:
  `Embedder`, `LLMCaller`, `PageIndexer`, plus the existing wiki backend
  registry (`register_wiki_backend`). Discovery: explicit constructor
  arguments first, then the `parrot_graphindex.providers` entry-point group.
  `ai-parrot` registers `EmbeddingRegistry`-backed embedders,
  `PageIndexLLMAdapter`, `PageIndexToolkit`, and the Arango/Postgres stores.
  `HashingGraphEmbedder` is the built-in default.
- `resolve_setting()` is the single configuration reader. navconfig is
  imported inside it, once, and only if `os.environ` did not already have the
  key; import failures degrade to `os.environ` with a debug log, as
  `_navconfig()` does today.
- Core keeps: `OntologyRAGMixin`, `OntologyGraphStore`, `TenantOntologyManager`,
  `OntologyCache`, `OntologyIntentResolver` (they import `TenantContext` from
  the standalone), `PageIndexToolkit`, `PageIndexLLMAdapter`, pageindex
  `loader.py`, `GraphIndexToolkit`, the `parrot.mcp` adapter path, and the
  Jira interface.
- Compat: `_ParrotGraphindexRedirector` maps `parrot.knowledge.graphindex` →
  `parrot_graphindex.graph`, `parrot.knowledge.wiki` → `parrot_graphindex.wiki`,
  `parrot.knowledge.okf` → `parrot_graphindex.okf`,
  `parrot.knowledge.ontology.schema` → `parrot_graphindex.ontology.schema`,
  `parrot.knowledge.pageindex.<pure>` → `parrot_graphindex.pageindex.<pure>`.
  Aliased modules are registered under both names in `sys.modules` so
  `isinstance` and pickling stay stable.

### Edge Cases & Error Handling

- **Both old and new installed** (upgrade path): the finder must yield to a
  real `parrot.knowledge.wiki` directory if one still exists in an old
  editable checkout; log a warning naming the stale path.
- **Plane schema drift**: the standalone carries the same `wiki.db`
  migrations; `wikitoolkit status` reports "plane predates the current schema"
  exactly as `federation.py:494` does today.
- **navconfig present but env file broken**: `resolve_setting()` swallows
  the import error, logs at debug, and continues with `os.environ` (current
  `_navconfig()` behaviour, kept deliberately because `project.py` sits on the
  PreToolUse hook path).
- **Provider missing at call time** (e.g. `wikitoolkit ingest --llm` without a
  registered `LLMCaller`): raise `ProviderNotAvailable` with the entry-point
  group name and the pip extra that supplies it; the CLI maps it to exit code 2.
- **Cython modules**: none of the moved code is Cython; `parrot.utils.types`
  is reached only via `faiss_logging`, which stays in core behind the
  `Embedder` seam.
- **Entry-point cycles**: core's provider registration must import lazily
  (module path strings, not objects) so that `import parrot_graphindex` never
  triggers `import parrot`.

---

## Capabilities

### New Capabilities
- `graphindex-core-seams`: FEAT-A — lazy roots, Protocols, toolkits to
  `parrot_tools.wiki`, `resolve_setting()`, mcp-SDK stdio path, minimal
  `Document`/`Loader` shapes. Acceptance by module-count ceilings.
- `parrot-graphindex-package`: FEAT-B — the workspace member, extras, finder,
  entry-point providers, release wiring, docs.

### Modified Capabilities
- `graphindex-postgres-backend` (FEAT-520): its files move in FEAT-B; no
  behaviour change.
- `sdd-flow-types-and-per-spec-index` — none; listed only because `/sdd-task`
  will need `depends_on` across the two new specs.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | modifies | adds `parrot-graphindex` runtime dep; drops rustworkx/networkx/pathspec/aiosqlite/orjson (transitive now); `[project.scripts]` loses `wikitoolkit` / `parrot-graphindex`; extras `graphindex`, `wiki-*`, `leiden`, `wiki` become forwards to the new package's extras |
| `packages/parrot-graphindex/` | new | workspace member, `src/parrot_graphindex/` |
| `parrot/knowledge/ontology/__init__.py`, `parrot/stores/__init__.py` | modifies | PEP 562 lazy roots (FEAT-A) |
| `parrot/knowledge/graphindex/*` (30 files) | moves | FEAT-B; `builder.py`, `embed.py`, `factory.py`, `loader.py`, `persist.py`, `extractors/loader.py` change in FEAT-A first |
| `parrot/knowledge/wiki/*` (54 files) | moves | FEAT-B; `tools.py`, `toolkit.py`, `structural/tools.py`, `structural/toolkit.py` leave for `parrot_tools/wiki/` in FEAT-A; `mcp_server.py`, `triage.py`, `documents.py`, `project.py`, `cli.py` change in FEAT-A |
| `parrot/knowledge/pageindex/*` | splits | pure core moves; `toolkit.py`, `llm_adapter.py`, `loader.py`, `pdf_to_markdown.py` stay |
| `parrot/knowledge/okf/*` | moves | 579 lines, import-clean already |
| `parrot/knowledge/ontology/schema.py` | moves | rest of ontology stays and imports it back |
| `parrot/interfaces/obsidian/*` | moves | into `[obsidian]` extra |
| `parrot/interfaces/jira/*` | unchanged | Jira commands remain core-only via `LLMCaller`/provider gating |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/` | new | agent-facing wiki toolkits |
| `parrot/tools/__init__.py` | extends | second redirector for graph paths, or generalise `_ParrotToolsRedirector` |
| `scripts/release.py` | modifies | `PACKAGES` gains `parrot-graphindex` (must be ordered before `ai-parrot` for build) |
| `.github/workflows/*` | modifies | build order; import-ceiling test job |
| `docs/graphindex.md`, `docs/wiki-claude-code.md`, `docs/guides/llm-wiki-guide.md`, `CLAUDE.md` § Knowledge Graph | modifies | install instructions |
| `.claude/settings.local.json` (wikitoolkit MCP entry) | unchanged | command name is stable |
| Claude Code / Codex managed assets (`claude_code/assets.py`, `codex/assets.py`) | unchanged | reference the command name only |

Breaking changes: none for `import parrot.knowledge.*` callers (finder). The
only observable change for framework users is that `pip install ai-parrot`
now also installs `parrot-graphindex`.

---

## Code Context

### User-Provided Code

None — discovery was measurement-driven; the evidence log is
`artifacts/logs/lazy-ontology-import-measurement.md` on branch
`exp-lazy-ontology` (commit `c4555d7d1`, to be discarded; keep the log).

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/tools/__init__.py
class _AliasLoader(importlib.abc.Loader): ...            # line 31
_CORE_TOOLS_DIR = _Path(__file__).parent                  # line 43
class _ParrotToolsRedirector(importlib.abc.MetaPathFinder): ...  # line 50
# installed at sys.meta_path front, guarded by isinstance check   # lines 132-136

# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def _navconfig() -> Any | None: ...                       # line 499
def _env_credential(key: str, default: Any) -> Any: ...   # line 529
def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]: ...  # line 558
def resolve_wiki_env(env: str | None = None) -> str: ...  # line 792

# From packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _env_setting(name: str) -> str | None: ...            # line 464 (lazy `from navconfig import config` at 472)

# From packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py
#   lazy `from navconfig import config` + config.get(key)   # lines 337-342

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None: ...  # line 401

# From packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
from asyncdb import AsyncDB                               # line 34
#   AsyncDB("arangodb", params={**self._params, "database": ...})  # lines 285, 313

# From packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
def create_wiki_mcp_server(root: Path) -> StdioMCPServer: ...  # line 90
def main() -> None: ...                                   # line 202

# From packages/ai-parrot/src/parrot/mcp/local_server.py
class StdioMCPServer(LocalMCPServerBase): ...             # line 36
# From packages/ai-parrot/src/parrot/mcp/server_base.py
class LocalServerConfig: ...                              # line 48
class MCPServerBase(ABC): ...                             # line 57
    def register_tool(self, tool: AbstractTool): ...      # line 68
    def register_tools(self, tools: list[AbstractTool]): ...  # line 75
    async def start(self): ...                            # line 127

# From packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py
class GraphIndexEmbedder: ...                             # line 25
    def __init__(...): ...                                # line 40
    async def embed_nodes(...): ...                       # line 58
# top-level imports to sever: EmbeddingRegistry (line 15), quiet_faiss_loader (line 17)

# From packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit   # line 55
class GraphIndexBuilder: ...                              # line 60
    def __init__(self, ..., embedder: GraphIndexEmbedder, ..., pageindex_toolkit: PageIndexToolkit | None = None, ...)  # lines 116-123

# From packages/ai-parrot/src/parrot/knowledge/graphindex/grounding.py
class GroundingEvaluator: ...                             # line 96

# From packages/ai-parrot/src/parrot/knowledge/wiki/triage.py
from parrot.knowledge.graphindex.grounding import GroundingEvaluator      # line 41
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter    # line 42
class NoveltyScorer: ...                                  # line 67 (grounding_evaluator kwarg line 90)
class IngestTriageRouter: ...                             # line 252

# From packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter: ...                            # line 42
    def __init__(...): ...                                # line 49
    async def ask(...): ...                               # line 61
    async def ask_structured(...): ...                    # line 99
    async def ask_with_finish_info(...): ...              # line 151
    async def ask_json(...): ...                          # line 201

# From packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit): ...              # line 50; __init__ line 88

# From packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry: ...                              # line 55
    def get_or_create_sync(...): ...                      # line 355
# From packages/ai-parrot/src/parrot/utils/faiss_logging.py
def quiet_faiss_loader() -> None: ...                     # line 34

# From packages/ai-parrot/src/parrot/knowledge/ontology/schema.py  (imports: re, pydantic only)
class MergedOntology(BaseModel): ...                      # line 452
class TenantContext(BaseModel): ...                       # line 529
class ResolvedIntent(BaseModel): ...                      # line 547
class EnrichedContext(BaseModel): ...                     # line 582

# From packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py (eager today)
from .cache import OntologyCache; from .graph_store import OntologyGraphStore
from .intent import OntologyIntentResolver; from .mixin import OntologyRAGMixin
from .schema import EnrichedContext, MergedOntology, ResolvedIntent, TenantContext
from .tenant import TenantOntologyManager                 # lines 2-7

# From packages/ai-parrot/src/parrot/stores/__init__.py (eager today)
__path__ = extend_path(__path__, __name__)                # line 2
from .abstract import AbstractStore                        # line 4
supported_stores = {...}                                  # lines 6-13

# From packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):                                # line 19
    page_content: str                                     # line 24
    metadata: Dict[str, Any] = Field(default_factory=dict)  # line 25

# Agent-facing toolkits to relocate to parrot_tools/wiki/
class LLMWikiToolkit(AbstractToolkit): ...                # wiki/toolkit.py:54
class WikiQueryTool / WikiPageTool / WikiRelatedTool / WikiRememberTool / WikiNoteTool(AbstractTool)  # wiki/tools.py:161,203,240,272,354
class CodeStructuralToolkit(AbstractToolkit): ...         # wiki/structural/toolkit.py:25
class WikiSymbolLookupTool / WikiCodeOutlineTool / WikiBlastRadiusTool(AbstractTool)  # wiki/structural/tools.py:105,145,180
class GraphIndexToolkit(AbstractToolkit): ...             # packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py:72
```

#### Verified Imports
```python
from parrot.knowledge.ontology.schema import TenantContext, MergedOntology   # schema.py:452,529
from parrot.knowledge.wiki.project import _navconfig, resolve_arango_params # project.py:499,558
from parrot.knowledge.wiki.store import register_wiki_backend               # store.py:401
from parrot.mcp.local_server import StdioMCPServer                          # local_server.py:36
from parrot_tools.graphindex.toolkit import GraphIndexToolkit               # toolkit.py:72 (lazy in graphindex/factory.py:38,236)
from parrot.knowledge.okf import ConceptType, RelationType                  # okf/__init__.py:16-17
from parrot.knowledge.pageindex.okf.projection import ...                   # pageindex/okf/projection.py exists
```

#### Key Attributes & Constants
- `packages/ai-parrot/pyproject.toml:162-167` — `[project.scripts]`: `parrot-graphindex = "parrot.knowledge.graphindex.cli:main"`, `wikitoolkit = "parrot.knowledge.wiki.cli:main"`.
- `packages/ai-parrot/pyproject.toml:151-160` — FEAT-471 comment: rustworkx, networkx, pathspec, aiosqlite, orjson are core deps *because* wikitoolkit imports them unconditionally.
- `packages/ai-parrot/pyproject.toml:234-280` — extras `graphindex`, `wiki-languages`, `wiki-structural`, `leiden`, `wiki`.
- `packages/ai-parrot-tools/pyproject.toml` — `dependencies = ["ai-parrot", "PyGithub", "ddgs", "rustworkx"]`, setuptools backend, `[tool.uv.sources] ai-parrot = { workspace = true }`.
- `pyproject.toml:57-58` (root) — `[tool.uv.workspace] members = ["packages/*"]`.
- `scripts/release.py:109` — `PACKAGES: list[Package]` (ai-parrot, ai-parrot-tools, -loaders, -embeddings, -pipelines, -visualizations, -integrations, -server, -advisors, parrot-formdesigner, navrules, parrot-codec); `CORE = PACKAGES[0]` line 164.
- Sizes (lines): wiki 30 882 (54 files), graphindex 13 704 (30 files), ontology 9 962, pageindex 8 959, okf 579.
- pageindex modules and their non-stdlib imports: `builder.py` (none), `md_builder.py`, `store.py`, `content_store.py`, `tree_ops.py`, `retriever.py`, `schemas.py` (pydantic), `ingest.py` (pydantic), `vector_walk.py`/`embedding_store.py` (numpy), `utils.py` (tiktoken, yaml), `hybrid_search.py` (numpy, `parrot._imports`), `prompts.py`; framework-bound: `toolkit.py` (`parrot.tools.toolkit`), `llm_adapter.py` (`parrot.clients.base`, `parrot.models.outputs`), `loader.py` (`parrot.loaders.abstract`, `parrot.stores.models`), `pdf_to_markdown.py` (pymupdf, lazy).
- `pageindex/okf/tools.py` imports `parrot.tools.tool` → stays in core or moves to `parrot_tools`.
- Installed versions (2026-09-03): rustworkx 0.18.1, networkx 3.4.2, pydantic 2.13.5, aiosqlite 0.22.1, orjson 3.12.0, pathspec 1.1.1, click 8.4.2, numpy 2.5.2, mcp 1.29.0, marko 2.2.4, python-frontmatter 1.3.0, tree-sitter 0.26.0, ast-grep-py 0.45.3, leidenalg 0.12.0, igraph 1.0.0, asyncdb 2.15.10, navconfig 2.4.1, pymupdf 1.27.1, faiss-cpu 1.15.0.
- `asyncdb` 2.15.10 requires: aiofiles, aiohttp, aiosqlite, asyncpg, pgvector, pandas, python-datamodel, google-cloud-* … (no navconfig).
- `navconfig` 2.4.1 alone: 541 modules / ~155 ms; pulls requests, redis, hvac, cryptography, uvloop, python-dotenv.
- In-flight features sharing files: **FEAT-520** `graphindex-postgres-backend` (10 pending) touches `graphindex/embed.py`, `factory.py`, `persist.py`, `persist_sqlite.py`, `publish.py`, new `persist_postgres.py`, `pg_schema.py`, `wiki/postgres_store.py`, `wiki/store.py`, `pageindex/hybrid_search.py`, `parrot_tools/graphindex/toolkit.py`. **FEAT-481** `fireflies-wiki-knowledgebase-agent` (16 pending) — consumer of the wiki, no shared files found in its task text.

### Does NOT Exist (Anti-Hallucination)
- ~~`packages/parrot-graphindex/`~~, ~~`parrot_graphindex`~~ — to be created.
- ~~`parrot.knowledge.graphindex.protocols`~~ / ~~`Embedder`, `LLMCaller`, `PageIndexer` Protocols~~ — do not exist yet.
- ~~`resolve_setting()`~~ — does not exist; today's readers are `_env_setting` (cli.py:464), `_env_credential` (project.py:529), inline navconfig in `graphindex/loader.py:337`.
- ~~`parrot_tools.wiki`~~ — does not exist; wiki toolkits live in `parrot/knowledge/wiki/tools.py`, `toolkit.py`, `structural/`.
- ~~`.mcp.json` at repo root~~ — CLAUDE.md mentions it, but the file is absent; the `wikitoolkit` MCP entry is in `.claude/settings.local.json`.
- ~~`parrot/knowledge/__init__.py` imports~~ — the file exists but has no imports (PEP 420-like root, import-clean).
- ~~`HashingGraphEmbedder` in `embed.py`~~ — it is defined in `graphindex/factory.py:118`, not in `embed.py` (which only has `GraphIndexEmbedder`).
- ~~`hyperscan` / `google-re2` as parrot dependencies~~ — they are optional `pathspec` backends auto-detected at import; do not declare them.
- ~~A `parrot.stores.models` dependency-free path~~ — importing `parrot.stores.models` executes `parrot/stores/__init__.py` (eager `AbstractStore`) today.
- ~~`ai-parrot-tools` as a leaf package~~ — it depends on `ai-parrot`; the "top-level package" precedent covers naming and the finder, **not** dependency direction.

---

## Parallelism Assessment

- **Internal parallelism**: FEAT-A splits into four independent lanes that
  touch disjoint files: (1) lazy roots + module-ceiling test
  (`ontology/__init__.py`, `stores/__init__.py`, `wiki/documents.py`);
  (2) Protocols + `builder.py`/`embed.py`/`triage.py`/`factory.py`;
  (3) toolkits → `parrot_tools/wiki/` (`wiki/tools.py`, `toolkit.py`,
  `structural/*`); (4) `resolve_setting()` + mcp-SDK stdio path
  (`project.py`, `cli.py`, `graphindex/loader.py`, `mcp_server.py`). FEAT-B
  is one sequential lane (a rename cannot be parallelised).
- **Cross-feature independence**: FEAT-A lane (2) overlaps FEAT-520 on
  `graphindex/embed.py` and `factory.py`; lane (4) does not. FEAT-B overlaps
  everything FEAT-520 adds and must wait for it. FEAT-481 is a consumer only.
- **Recommended isolation**: `mixed` for FEAT-A (lanes 1, 3, 4 in their own
  worktrees; lane 2 after FEAT-520 or rebased onto it); `per-spec` for FEAT-B.
- **Rationale**: the seams are file-disjoint by construction, and the
  module-count acceptance test gives each lane an objective merge gate. The
  physical move is a single atomic rename and gains nothing from parallelism.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus Lara*: feature on `dev`.
- [x] Import name — *Owner: Jesus Lara*: `parrot_graphindex` (distribution `parrot-graphindex`).
- [x] Where does pageindex go — *Owner: Jesus Lara*: split; pure core (tree, md_builder, store, …) moves, `toolkit.py` / `llm_adapter.py` / `loader.py` stay in core.
- [x] LLM-dependent CLI commands — *Owner: Jesus Lara*: `LLMCaller` Protocol; without a provider the commands warn and are unavailable; core registers its client.
- [x] Backward-compat mechanism — *Owner: Jesus Lara*: `sys.meta_path` finder, as `parrot.tools` → `parrot_tools`.
- [x] Fate of `exp-lazy-ontology` — *Owner: Jesus Lara*: discard; FEAT-A re-does it in its own worktree.
- [x] Versioning — *Owner: Jesus Lara*: workspace member, lockstep with `/release`.
- [x] Phasing — *Owner: Jesus Lara*: two FEATs (seams in core, then physical move).
- [x] navconfig — *Owner: Jesus Lara*: kept as optional lazy credential provider, dependency of `[postgres]`/`[arangodb]` only; `parrot.conf` never enters the standalone.
- [x] Where is `HashingGraphEmbedder` defined today? — *Owner: FEAT-A planner*: `parrot/knowledge/graphindex/factory.py:118`; it moves to the standalone as the default `Embedder`.
- [x] `pageindex/hybrid_search.py` uses `parrot._imports.lazy_import` (`hybrid_search.py:28`, defined at `parrot/_imports.py:110`) — *Owner: FEAT-A planner*: it moves; the standalone carries its own small `lazy_import` helper (no `parrot.*` import allowed).
- [ ] Should core's extras `graphindex` / `wiki-languages` / `wiki-structural` / `leiden` / `wiki` be kept as forwards (`ai-parrot[wiki]` → `parrot-graphindex[all]`) or removed with a deprecation note? — *Owner: Jesus Lara*
- [ ] Entry-point group name for providers (`parrot_graphindex.providers`) and whether backends also register through it or keep `register_wiki_backend()` import-time registration (FEAT-449 M7). — *Owner: FEAT-B planner*
- [ ] CI: does the GitHub build matrix need an explicit order (build `parrot-graphindex` wheel before `ai-parrot`) or does `uv build --all-packages` resolve it from `[tool.uv.sources]`? — *Owner: FEAT-B planner*
- [x] Obsidian: does `parrot.interfaces.obsidian` have consumers outside wiki? — *Owner: FEAT-B planner*: yes — `parrot/agents/obsidian.py`, `parrot/loaders/obsidian/{__init__,loader,graph_bridge}.py`, `parrot/tools/obsidian.py`, `parrot/interfaces/jira/{__init__,errors}.py`, `parrot_tools/audio_note_capture.py`, plus `tests/loaders/obsidian/*`. Recommendation: move the parser/models/index (`interfaces/obsidian`) into the standalone **base** (marko + python-frontmatter are small, no extra gating) so every consumer gets it transitively via the finder; keep `[obsidian]` for vault sync / MCP-only bits. Final call: Jesus Lara.
- [ ] Jira v2: once `LLMCaller` exists, should `interfaces.jira` (aiohttp + pydantic) also move behind a `[jira]` extra so `ingest-jira` works standalone with a registered caller? — *Owner: Jesus Lara*
