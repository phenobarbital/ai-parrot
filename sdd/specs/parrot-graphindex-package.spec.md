---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: parrot-graphindex — Standalone Distribution

**Feature ID**: FEAT-541
**Date**: 2026-09-09
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 1.1.0

> **Phase 2 of 2. Blocked on FEAT-540 `graphindex-core-seams`.**
> FEAT-540 makes the graph tree framework-free in place; this spec performs
> the physical move into a new workspace member and inverts the dependency
> arrow. Do not create the worktree for this feature until FEAT-540 is merged
> to `dev` — every `git mv` here would otherwise conflict with FEAT-540's
> in-place edits.
>
> Source brainstorm: `sdd/proposals/parrot-graphindex-standalone.brainstorm.md`
> (Recommended Option B, two-FEAT phasing).

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit` and GraphIndex are usable without an agent: point them at a
repository, run `wikitoolkit build`, get a queryable knowledge graph plus a
local MCP server for Claude Code / Codex. Competing tools in that space —
`graphify`, `zvec-grep` — install in one `pip install` and work in seconds.

Getting there requires installing `ai-parrot`, an agent framework with 55
runtime dependencies (navigator-api, navigator-auth, pandas, pyarrow,
faiss-cpu, sqlglot, …). FEAT-540 removes the *import-time* cost of that
coupling, but not the *install-time* cost: the code still ships inside the
framework distribution, so `pip install ai-parrot` is still the only way to
get `wikitoolkit`, and the product still presents as "an agent framework you
install to get a graph tool".

The measured third-party floor for the SQLite plane is nine packages:
pydantic, PyYAML, rustworkx, networkx, numpy, pathspec, aiosqlite, orjson,
click.

### Goals

- G1 — `uv pip install parrot-graphindex` installs **≤ 12** third-party
  distributions, and `wikitoolkit build` then works with no `.env`, no
  framework, no LLM.
- G2 — `parrot_graphindex` contains **zero** `parrot.*` imports anywhere in
  its tree, enforced by test.
- G3 — Every existing `from parrot.knowledge.{graphindex,wiki,okf}…` import
  keeps working, via a `sys.meta_path` redirector — no stub modules, no
  deprecation break.
- G4 — Existing planes under `~/.parrot/wikis/*/wiki.db` remain readable with
  no rebuild and no schema migration.
- G5 — With `ai-parrot` installed nothing changes for agents: real embedders,
  a real LLM adapter, a real PageIndex toolkit and the Arango/Postgres wiki
  planes are all registered automatically through an entry-point group.
- G6 — `/release` versions the new package in lockstep with the rest of the
  workspace.

### Non-Goals (explicitly out of scope)

- Re-cutting seams. Protocols, `resolve_setting()`, the toolkit relocation and
  the MCP dual transport are FEAT-540's work and are assumed present.
- Any behavioural change to graph or wiki logic. This is a move plus packaging.
- Renaming the CLI commands. `wikitoolkit` and `parrot-graphindex` keep their
  names and move with the package.
- Publishing from a separate repository (brainstorm Option D, rejected) or
  shipping as a PEP 420 satellite under `parrot.*` (Option A, rejected —
  satellites depend on core, so the framework would still be installed).
- Splitting graph and wiki into two distributions — `wiki/` has 18 hard
  imports of `graphindex/`; they are not separable.

---

## 2. Architectural Design

### Overview

A new uv workspace member `packages/parrot-graphindex/` provides the
top-level package `parrot_graphindex`. `ai-parrot` core declares it as a
runtime dependency.

**This is less novel than the brainstorm assumed.** The workspace now holds
**27** packages, and core already depends on its own satellites: the 15
`ai-parrot-client-*` distributions are named in core's extras (e.g.
`packages/ai-parrot/pyproject.toml:522, 546, 550`) with `[tool.uv.sources]
… = { workspace = true }` entries at lines 868-882 — and each declares
`dependencies = ["ai-parrot>=1.0.0", …]` back, so core↔satellite cycles
already exist and uv already resolves them. `ai-parrot-openlit-bridge` is
already a true leaf (`dependencies = ["aiohttp>=3.9"]`).

What is genuinely new here is narrower: a **runtime** (non-extra) dependency
from core onto a package that does **not** depend back on core. The build
ordering and workspace-source machinery this needs is already exercised
15 times over.

Layout:

```
packages/parrot-graphindex/
  pyproject.toml                      # extras: postgres, arangodb, obsidian,
                                      #   mcp, languages, structural, leiden, pdf
  src/parrot_graphindex/
    graph/          ← parrot/knowledge/graphindex/   (32 files, 16 106 lines)
    wiki/           ← parrot/knowledge/wiki/         (77 files, 37 624 lines)
    okf/            ← parrot/knowledge/okf/          (5 files, 579 lines)
    pageindex/      ← the pure-core subset of parrot/knowledge/pageindex/
    ontology/schema.py  ← parrot/knowledge/ontology/schema.py
    obsidian/       ← parrot/interfaces/obsidian/    (8 files, 1 589 lines)
    protocols.py    ← parrot/knowledge/graphindex/protocols.py  (from FEAT-540)
    _imports.py     # the standalone's own small lazy_import helper
```

Backward compatibility is a `sys.meta_path` finder in core —
`_ParrotGraphindexRedirector`, cloned from `_ParrotToolsRedirector`
(`parrot/tools/__init__.py:50`) — mapping the old dotted paths onto the new
ones and registering each aliased module under **both** names in `sys.modules`
so `isinstance` checks and pickling stay stable.

Provider registration flips from import to entry point: core publishes its
`LLMCaller`, `Embedder`, `PageIndexer` implementations and the Arango/Postgres
wiki backends through the `parrot_graphindex.providers` group. Registration
values are **module path strings, not objects**, so that
`import parrot_graphindex` never triggers `import parrot`.

### Component Diagram

```
   pip install parrot-graphindex                pip install ai-parrot
            │                                            │
            ▼                                            ▼
   ┌─────────────────────────┐          ┌────────────────────────────────┐
   │  parrot_graphindex      │◄─────────│  ai-parrot  (depends on it)    │
   │  (leaf — no parrot.*)   │  runtime │                                │
   │                         │   dep    │  parrot/tools/__init__.py      │
   │  graph/  wiki/  okf/    │          │   _ParrotToolsRedirector       │
   │  pageindex/ (pure)      │          │   _ParrotGraphindexRedirector ─┼──┐
   │  ontology/schema.py     │          │                                │  │
   │  obsidian/  protocols.py│          │  entry points:                 │  │
   │                         │          │   parrot_graphindex.providers  │  │
   │  scripts:               │◄─────────┼─── LLMCaller (PageIndexLLMAdapter)│
   │    wikitoolkit          │ registers│    Embedder  (EmbeddingRegistry)  │
   │    parrot-graphindex    │          │    PageIndexer (PageIndexToolkit) │
   └─────────────────────────┘          │    wiki backends (arango, pg)  │  │
            ▲                           └────────────────────────────────┘  │
            │  parrot.knowledge.graphindex.* ─────────────────────────────────┘
            │  parrot.knowledge.wiki.*        (old import paths, redirected)
            │  parrot.knowledge.okf.*
            └─ parrot.knowledge.ontology.schema
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `packages/parrot-graphindex/` | new | workspace member #28; `members = ["packages/*"]` already matches it (`pyproject.toml:58`) |
| `packages/ai-parrot/pyproject.toml` | modifies | adds `parrot-graphindex` runtime dep + `[tool.uv.sources]` workspace entry; drops rustworkx/networkx/pathspec/aiosqlite/orjson (lines 169-173, now transitive); `[project.scripts]` loses `parrot-graphindex` and `wikitoolkit` (lines 179, 181) |
| `parrot/tools/__init__.py` | extends | second redirector, or generalise `_ParrotToolsRedirector` (line 50) |
| `parrot/knowledge/{graphindex,wiki,okf}/` | moves | to `parrot_graphindex/{graph,wiki,okf}/` |
| `parrot/knowledge/ontology/schema.py` | moves | the rest of `ontology/` stays and imports it back |
| `parrot/knowledge/pageindex/` | splits | pure core moves; `toolkit.py`, `llm_adapter.py`, `loader.py`, `pdf_to_markdown.py`, `okf/tools.py` stay |
| `parrot/interfaces/obsidian/` | moves | into the standalone **base** (see §8 — 12 consumers get it back through the finder) |
| `parrot/interfaces/jira/` | unchanged | stays core-only; gated by `LLMCaller` |
| `wiki/store.py:401` `register_wiki_backend` | extends | entry-point discovery in addition to direct calls |
| `scripts/release.py:116` `PACKAGES` | modifies | gains `parrot-graphindex`, ordered **before** `ai-parrot` for build; `CORE = PACKAGES[0]` (line 189) must keep pointing at `ai-parrot` |
| `.github/workflows/*` | modifies | build order + the FEAT-540 import-ceiling job |
| `docs/graphindex.md`, `docs/wiki-claude-code.md`, `docs/guides/llm-wiki-guide.md`, `CLAUDE.md` § Codebase Knowledge Graph | modifies | install instructions |
| `.claude/settings.local.json` wikitoolkit MCP entry | unchanged | command name is stable |
| Claude Code / Codex managed assets (`claude_code/assets.py` 66 occurrences, `codex/assets.py` 13) | unchanged | they reference the command name only |

### Data Models

No new data models. `ontology/schema.py` (`MergedOntology:452`,
`TenantContext:529`, `ResolvedIntent:547`, `EnrichedContext:582`) moves
verbatim; it imports only `re` and `pydantic`.

### New Public Interfaces

```python
# parrot/tools/__init__.py  (or a sibling module in core)
class _ParrotGraphindexRedirector(importlib.abc.MetaPathFinder):
    """Redirect legacy dotted paths onto ``parrot_graphindex``.

    Mapping:
        parrot.knowledge.graphindex        → parrot_graphindex.graph
        parrot.knowledge.wiki              → parrot_graphindex.wiki
        parrot.knowledge.okf               → parrot_graphindex.okf
        parrot.knowledge.ontology.schema   → parrot_graphindex.ontology.schema
        parrot.knowledge.pageindex.<pure>  → parrot_graphindex.pageindex.<pure>
        parrot.interfaces.obsidian         → parrot_graphindex.obsidian

    Yields to a real on-disk ``parrot/knowledge/wiki`` directory if one still
    exists (stale editable checkout) and logs a warning naming that path.
    Aliased modules are registered under both names in ``sys.modules``.
    """


# packages/parrot-graphindex/src/parrot_graphindex/providers.py
def load_providers() -> None:
    """Import and register everything advertised on the
    ``parrot_graphindex.providers`` entry-point group.

    Entry-point values are module path strings; nothing is imported until a
    provider is actually requested, so ``import parrot_graphindex`` never
    pulls ``parrot``.
    """
```

```toml
# packages/ai-parrot/pyproject.toml — core registers its implementations
[project.entry-points."parrot_graphindex.providers"]
llm_caller  = "parrot.knowledge.pageindex.llm_adapter:PageIndexLLMAdapter"
embedder    = "parrot.knowledge.graphindex_adapters:registry_embedder"
pageindexer = "parrot.knowledge.pageindex.toolkit:PageIndexToolkit"
wiki_arango = "parrot.knowledge.wiki_backends:arango_factory"
wiki_pg     = "parrot.knowledge.wiki_backends:postgres_factory"
```

---

## 3. Module Breakdown

### Module 1: Package skeleton + pyproject
- **Path**: `packages/parrot-graphindex/pyproject.toml`,
  `packages/parrot-graphindex/src/parrot_graphindex/{__init__,version,_imports}.py`
- **Responsibility**: create the workspace member with the nine base
  dependencies (pydantic, PyYAML, rustworkx, networkx, numpy, pathspec,
  aiosqlite, orjson, click) and the extras `[postgres]` (asyncdb, asyncpg,
  pgvector, navconfig), `[arangodb]` (asyncdb, navconfig), `[obsidian]`
  (marko, python-frontmatter), `[mcp]` (mcp), `[languages]` (tree-sitter +
  grammars), `[structural]` (ast-grep-py), `[leiden]` (leidenalg, igraph),
  `[pdf]` (pymupdf), plus an `[all]`. Carry the standalone's own small
  `lazy_import` helper (no `parrot._imports` dependency).
- **Depends on**: FEAT-540 merged

### Module 2: `git mv` the graph tree
- **Path**: `parrot/knowledge/graphindex/` → `parrot_graphindex/graph/`;
  `parrot/knowledge/okf/` → `parrot_graphindex/okf/`;
  `parrot/knowledge/ontology/schema.py` → `parrot_graphindex/ontology/schema.py`
- **Responsibility**: move with `git mv` (preserve history), rewrite intra-tree
  imports to `parrot_graphindex.*`, leave `parrot/knowledge/ontology/` importing
  `schema` back from the standalone.
- **Depends on**: Module 1

### Module 3: `git mv` the wiki tree
- **Path**: `parrot/knowledge/wiki/` → `parrot_graphindex/wiki/` (77 files)
- **Responsibility**: same treatment; keep the `wikitoolkit` CLI intact and
  re-point `[project.scripts]` at `parrot_graphindex.wiki.cli:main`.
- **Depends on**: Module 2 (wiki has 18 hard imports of graphindex)

### Module 4: pageindex split + obsidian move
- **Path**: `parrot_graphindex/pageindex/`, `parrot_graphindex/obsidian/`
- **Responsibility**: move the pure-core pageindex modules (`builder`,
  `md_builder`, `store`, `content_store`, `tree_ops`, `schemas`, `ingest`,
  `retriever`, `vector_walk`, `embedding_store`, `utils`, `hybrid_search`,
  `prompts`) and leave the framework-bound ones in core (`toolkit.py`,
  `llm_adapter.py`, `loader.py`, `pdf_to_markdown.py`, `okf/tools.py` — the
  latter imports `parrot.tools.tool`). Move `parrot/interfaces/obsidian/`
  (8 files, 1 589 lines) into the standalone base; its 12 consumers keep
  working through the finder.
- **Depends on**: Module 2

### Module 5: `_ParrotGraphindexRedirector`
- **Path**: `parrot/tools/__init__.py` (or a sibling), plus tests
- **Responsibility**: the meta_path finder and its `sys.modules` dual
  registration; the stale-checkout yield-and-warn path; installation at the
  front of `sys.meta_path` guarded by an `isinstance` check, exactly as
  `_ParrotToolsRedirector` is (`parrot/tools/__init__.py:132-136`).
- **Depends on**: Modules 2, 3, 4

### Module 6: Entry-point providers
- **Path**: `parrot_graphindex/providers.py`, `packages/ai-parrot/pyproject.toml`,
  core adapter modules
- **Responsibility**: define the `parrot_graphindex.providers` group and the
  loader; register core's `LLMCaller` / `Embedder` / `PageIndexer` and the
  Arango + Postgres wiki backends (today registered by direct
  `register_wiki_backend` calls, `wiki/store.py:401`). Values must be module
  path strings resolved on demand.
- **Depends on**: Module 5

### Module 7: Core pyproject inversion
- **Path**: `packages/ai-parrot/pyproject.toml`
- **Responsibility**: add `parrot-graphindex` as a runtime dependency and a
  `[tool.uv.sources]` workspace entry; drop rustworkx / networkx / pathspec /
  aiosqlite / orjson (lines 169-173) now that they arrive transitively; remove
  `parrot-graphindex` and `wikitoolkit` from `[project.scripts]` (lines 179,
  181); resolve the extras question in §8 for `graphindex`, `wiki-languages`,
  `wiki-structural`, `leiden`, `wiki` (lines 250, 275, 290, 299, 307).
- **Depends on**: Module 6

### Module 8: Tests, release wiring, CI, docs
- **Path**: `packages/parrot-graphindex/tests/`, `scripts/release.py`,
  `.github/workflows/*`, `docs/graphindex.md`, `docs/wiki-claude-code.md`,
  `docs/guides/llm-wiki-guide.md`, `CLAUDE.md`
- **Responsibility**: move the graph/wiki tests with the code; add
  `Package("parrot-graphindex", …)` to `PACKAGES` (`scripts/release.py:116`)
  **before** `ai-parrot`, keeping `CORE = PACKAGES[0]` (line 189) pointing at
  `ai-parrot`, and mirror the `*_VERSION_FILE` variable in the `Makefile`.
  `PACKAGES` currently lists **13** of the workspace's **27** packages (the
  15 `ai-parrot-client-*` are absent; `parrot-codec` is listed with no
  directory) — verify the new entry with `scripts/release.py status`, which
  the file's own comment says fails loudly on a missing path.
  add a clean-venv install job that asserts G1; update install instructions.
- **Depends on**: Module 7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_no_parrot_imports_in_standalone` | 2-4 | AST scan of the whole `parrot_graphindex` tree: no `parrot.*` import at any level (G2) |
| `test_redirector_maps_all_prefixes` | 5 | each of the six mapped prefixes resolves to the new module |
| `test_redirector_dual_sys_modules` | 5 | an aliased module is present under both names and is the *same object* |
| `test_redirector_yields_to_real_dir` | 5 | with a real `parrot/knowledge/wiki` on disk, the finder declines and warns naming the path |
| `test_isinstance_stable_across_alias` | 5 | a class imported by the old path `isinstance`-matches one imported by the new path |
| `test_providers_lazy` | 6 | `import parrot_graphindex` leaves `parrot` out of `sys.modules` even with `ai-parrot` installed |
| `test_provider_registration_roundtrip` | 6 | with `ai-parrot` installed, `LLMCaller`/`Embedder`/`PageIndexer` and both wiki backends resolve |
| `test_release_packages_ordering` | 8 | `parrot-graphindex` precedes `ai-parrot` in `PACKAGES`; `CORE` is still `ai-parrot` |

### Integration Tests

| Test | Description |
|---|---|
| `test_clean_venv_install` | Fresh venv, `uv pip install parrot-graphindex`, assert ≤ 12 third-party distributions, then `wikitoolkit build` on a fixture repo (G1) |
| `test_legacy_import_paths` | Every documented `from parrot.knowledge.{graphindex,wiki,okf}…` import in `docs/` and `CLAUDE.md` still resolves |
| `test_plane_backward_readable` | A `wiki.db` built before the move opens, queries, and reports schema state unchanged (G4) |
| `test_agent_path_unchanged` | Framework agent with `LLMWikiToolkit` + `GraphIndexToolkit` answers a query end to end (G5) |
| `test_mcp_entry_shape_unchanged` | `.claude/settings.local.json`'s `{"command": "wikitoolkit", "args": ["mcp"]}` still starts a server |
| `test_workspace_builds` | `uv build --all-packages` succeeds and resolves the inverted arrow |

### Test Data / Fixtures

```python
@pytest.fixture(scope="session")
def clean_venv(tmp_path_factory):
    """Build both wheels, install ONLY parrot-graphindex into a fresh venv.

    Must not inherit the developer venv — the whole point is proving the
    framework is absent. Returns the venv's python + the installed
    distribution list.
    """

@pytest.fixture
def legacy_plane(tmp_path):
    """A wiki.db copied from a pre-move build, for the G4 assertion."""
```

---

## 5. Acceptance Criteria

- [ ] `uv pip install parrot-graphindex` into a clean venv installs **≤ 12**
      third-party distributions
- [ ] In that venv, `wikitoolkit build`, `query`, `page`, `related`,
      `remember`, `note`, `link`, `memories`, `audit`, `status`, `export`,
      `symbols {lookup,outline,blast}`, `ns {list,add,remove}` and `mcp` all
      work against the SQLite plane with no `.env` and no LLM
- [ ] `parrot`, `navconfig`, `parrot.conf`, `asyncdb`, `pandas`, `faiss` are
      **not** importable in that venv
- [ ] No file under `packages/parrot-graphindex/src/` contains a `parrot.*`
      import (AST scan)
- [ ] `parrot-graphindex[postgres]` and `[arangodb]` enable the DB planes and
      `wikitoolkit sync push/pull`; a missing credential produces one
      actionable message naming the key and the resolution order tried
- [ ] LLM-dependent commands (`ingest` with extraction, triage, `ingest-jira`)
      list a `(requires an LLM provider — install ai-parrot)` note and exit
      with code **2** and that message when invoked without a provider
- [ ] With `ai-parrot` installed, every legacy import path resolves through
      the finder, and an aliased module is the same object under both names
- [ ] A `wiki.db` plane built before the move opens and queries unchanged;
      no rebuild is forced
- [ ] `uv build --all-packages` succeeds; `parrot-graphindex` builds before
      `ai-parrot`
- [ ] `scripts/release.py status` lists `parrot-graphindex` at the workspace
      version, and the `Makefile` `*_VERSION_FILE` variable matches
- [ ] `pytest packages/parrot-graphindex/tests/ -v` passes
- [ ] `pytest packages/ai-parrot/tests/ -v` and
      `pytest packages/ai-parrot-tools/tests/ -v` pass
- [ ] The FEAT-540 import ceilings still hold after the move
- [ ] `docs/graphindex.md`, `docs/wiki-claude-code.md`,
      `docs/guides/llm-wiki-guide.md` and `CLAUDE.md` § Codebase Knowledge
      Graph give `uv pip install parrot-graphindex` as the install line
- [ ] `ruff check .` clean on changed files

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Re-verified against `dev` @ `81e087bd8` on **2026-09-09**. Line numbers and
> tree sizes supersede the 2026-09-03 brainstorm (FEAT-520 and FEAT-539 landed
> in between; the wiki tree grew from 54 to 77 files).

### Verified Imports

```python
from parrot.knowledge.ontology.schema import TenantContext, MergedOntology  # schema.py:529, 452
from parrot.knowledge.wiki.store import register_wiki_backend               # store.py:401
from parrot.knowledge.wiki.project import resolve_arango_params             # project.py:558
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter      # llm_adapter.py:42
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit             # toolkit.py:50
from parrot.embeddings.registry import EmbeddingRegistry                    # registry.py:55
from parrot_tools.graphindex.toolkit import GraphIndexToolkit               # toolkit.py:110
from parrot.knowledge.okf import ConceptType, RelationType                  # okf/__init__.py:15
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/__init__.py — THE PATTERN TO CLONE
class _AliasLoader(importlib.abc.Loader): ...                    # line 31
_CORE_TOOLS_DIR = _Path(__file__).parent                         # line 43
class _ParrotToolsRedirector(importlib.abc.MetaPathFinder): ...  # line 50
#   installed at sys.meta_path front, guarded by isinstance      # lines 132-136

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None: ...  # line 401

# packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
from asyncdb import AsyncDB                                      # line 34
    AsyncDB("arangodb", params={**self._params, "database": ...})  # line 292

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py  (re + pydantic ONLY)
class MergedOntology(BaseModel): ...                             # line 452
class TenantContext(BaseModel): ...                              # line 529
class ResolvedIntent(BaseModel): ...                             # line 547
class EnrichedContext(BaseModel): ...                            # line 582

# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter: ...                                   # line 42 — stays in core
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit): ...                     # line 50 — stays in core
```

### Key Attributes & Constants (re-verified 2026-09-09)

| Fact | Location | Note |
|---|---|---|
| `[project.scripts] parrot-graphindex = "parrot.knowledge.graphindex.cli:main"` | `packages/ai-parrot/pyproject.toml:179` | brainstorm said 162-167 — **drifted** |
| `wikitoolkit = "parrot.knowledge.wiki.cli:main"` | `packages/ai-parrot/pyproject.toml:181` | moves with the package |
| FEAT-471 deps (rustworkx, networkx, pathspec, aiosqlite, orjson) | `packages/ai-parrot/pyproject.toml:168-173` | brainstorm said 151-160 — **drifted** |
| extras `graphindex` / `wiki-languages` / `wiki-structural` / `leiden` / `wiki` | `packages/ai-parrot/pyproject.toml:250 / 275 / 290 / 299 / 307` | brainstorm said 234-280 — **drifted** |
| `PACKAGES: list[Package]` | `scripts/release.py:116` | brainstorm said 109 — **drifted** |
| `CORE = PACKAGES[0]` | `scripts/release.py:189` | brainstorm said 164 — **drifted**; must keep resolving to `ai-parrot` |
| `[tool.uv.workspace] members = ["packages/*"]` | root `pyproject.toml:57-58` | `packages/parrot-graphindex/` matches automatically |
| Tree sizes | — | wiki 77 files / 37 624 lines; graphindex 32 / 16 106; ontology 31 / 9 962; pageindex 29 / 9 029; okf 5 / 579; interfaces/obsidian 8 / 1 589 |
| FEAT-520 files present on `dev` | `graphindex/persist_postgres.py`, `graphindex/pg_schema.py`, `wiki/postgres_store.py` | merged — they move with Modules 2/3 |
| pageindex framework-bound modules | `toolkit.py`, `llm_adapter.py`, `loader.py`, `okf/tools.py` (imports `parrot.tools.tool`), `pdf_to_markdown.py` (pymupdf, lazy) | stay in core |
| `interfaces/obsidian` consumers | `parrot/agents/obsidian.py`, `parrot/tools/obsidian.py`, `parrot/loaders/obsidian/{__init__,loader,graph_bridge}.py`, `parrot/interfaces/jira/{__init__,errors}.py`, `parrot/knowledge/wiki/{obsidian_sync,vault_scan,ingest}.py`, `parrot_tools/audio_note_capture.py`, plus tests | 12 modules — all keep working via the finder |
| Installed versions (2026-09-09) | mcp 1.29.0 (verified in this venv) | others per brainstorm's 2026-09-03 survey |
| `asyncdb` 2.15.10 | requires aiofiles, aiohttp, aiosqlite, asyncpg, pgvector, pandas, python-datamodel, google-cloud-* | **does not** pull navconfig |
| `navconfig` 2.4.1 | 541 modules / ~155 ms; pulls requests, redis, hvac, cryptography, uvloop, python-dotenv | extras only, never base |

### Does NOT Exist (Anti-Hallucination)

- ~~`packages/parrot-graphindex/`~~ / ~~`parrot_graphindex`~~ — created by this spec.
- ~~`_ParrotGraphindexRedirector`~~ — created here; clone `_ParrotToolsRedirector`
  (`parrot/tools/__init__.py:50`).
- ~~`parrot_graphindex.providers` entry-point group~~ — does not exist.
- ~~`parrot_tools.wiki`~~ — created by **FEAT-540**, not this spec; assume present.
- ~~`parrot.knowledge.graphindex.protocols`~~ — created by **FEAT-540**; assume present.
- ~~`resolve_setting()`~~ — created by **FEAT-540**; assume present.
- ~~`.mcp.json` at the repo root~~ — CLAUDE.md mentions it, but the file is
  absent; the `wikitoolkit` MCP entry lives in `.claude/settings.local.json`.
- ~~`hyperscan` / `google-re2` as declared dependencies~~ — optional `pathspec`
  backends auto-detected at import.
- ~~`ai-parrot-tools` as a leaf package~~ — it declares
  `dependencies = ["ai-parrot", …]`. It is the precedent for the *finder* and
  for top-level naming, **not** for dependency direction. `parrot-graphindex`
  is the first true leaf.
- ~~A `Package(...)` entry for `parrot-graphindex` in `scripts/release.py`~~ —
  absent; a package missing from `PACKAGES` strands at its initial version,
  as `parrot-codec` did.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`git mv`, never copy-delete** — history on 54 000+ moved lines is the only
  way this stays reviewable.
- **Clone `_ParrotToolsRedirector`** (`parrot/tools/__init__.py:31-136`)
  rather than inventing a finder; keep the `isinstance` install guard.
- **Entry-point values are module path strings.** An object value would import
  `parrot` at group-load time and undo the whole feature.
- **One atomic rename per module.** Modules 2-4 are a sequential lane; a
  rename gains nothing from parallelism and loses conflict-freedom.
- Google-style docstrings, strict type hints, Pydantic, `self.logger`,
  async-first, `aiohttp` never `requests` — per `CLAUDE.md`.

### Known Risks / Gotchas

- **The dependency-arrow inversion is a smaller risk than the brainstorm
  thought.** 15 `ai-parrot-client-*` satellites already sit in core's extras
  with workspace sources and depend back on core; uv resolves that today.
  Confirm `uv build --all-packages` handles the leaf case too (§8), but treat
  it as verification, not as an unknown.
- **`scripts/release.py` `PACKAGES` is already out of sync with the
  workspace, and that is the real release risk.** It lists **13** packages
  while the workspace has **27**: all 15 `ai-parrot-client-*` distributions
  are missing from it, and `parrot-codec` is listed but has no workspace
  directory. A package missing from `PACKAGES` strands at its initial
  version — the documented `parrot-codec` failure. The precedent Module 8
  would copy is therefore currently *broken*: add `parrot-graphindex`
  correctly rather than inheriting the gap, and flag the 15 missing clients
  to the maintainer (fixing them is out of scope here, but same mechanism).
- **~54 000 lines move.** Any long-lived branch touching `knowledge/wiki` or
  `knowledge/graphindex` must merge before this feature starts or rebase
  across a rename. FEAT-481 `fireflies-wiki-knowledgebase-agent` (16 tasks
  pending) is a wiki consumer — check its state before the worktree is cut.
- **Stale editable checkouts** are the nastiest upgrade case: an old
  `parrot/knowledge/wiki/` directory left on disk shadows the redirect. The
  finder must yield to it *and warn with the path*, never silently win.
- **`isinstance` and pickling across the alias.** Registering the module under
  one name only produces two distinct class objects and breaks both. The dual
  `sys.modules` registration is not optional.
- **`CORE = PACKAGES[0]`** (`scripts/release.py:189`) is positional. Inserting
  `parrot-graphindex` at index 0 to get build ordering would silently
  re-point `CORE`. Order the *build*, not necessarily the list — or move
  `CORE` to a name lookup.
- **The `Makefile` mirrors `PACKAGES`** (`release.py:114` comment says so
  explicitly, and `status` fails loudly if a path disappears). Update both.
- **`okf/tools.py` under pageindex imports `parrot.tools.tool`** — it must
  stay in core or move to `parrot_tools`, not into the standalone.
- **Extras become a user-visible break** if `ai-parrot[wiki]` stops existing.
  That is the first open question in §8 and belongs to you, not the
  implementer.

### External Dependencies

Base (the measured floor — 9 packages):

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.13` | schemas |
| `PyYAML` | `>=6` | wiki config / frontmatter |
| `rustworkx` | `>=0.18` | graph core |
| `networkx` | `>=3.4` | Louvain fallback, export |
| `numpy` | `>=2` | hashing embedder |
| `pathspec` | `>=1.1` | ignore rules |
| `aiosqlite` | `>=0.22` | SQLite plane |
| `orjson` | `>=3.12` | serialization |
| `click` | `>=8.4` | CLI |

Extras: `[postgres]` asyncdb + asyncpg + pgvector + navconfig · `[arangodb]`
asyncdb + navconfig · `[obsidian]` marko + python-frontmatter · `[mcp]` mcp
`>=1.29` · `[languages]` tree-sitter + grammars · `[structural]` ast-grep-py ·
`[leiden]` leidenalg + igraph · `[pdf]` pymupdf.

---

## Worktree Strategy

**Default isolation unit: `per-spec` (sequential).**

All eight modules run in one worktree, in order. A ~54 000-line rename cannot
be parallelised without guaranteeing conflicts, and each module's output is
the next one's input (skeleton → graph → wiki → pageindex/obsidian → finder →
providers → core inversion → release/CI/docs).

**Cross-feature dependencies:**

- **FEAT-540 `graphindex-core-seams` MUST be merged to `dev` first.** Cut this
  worktree from `dev` only after that merge.
- Re-check FEAT-481 `fireflies-wiki-knowledgebase-agent` (16 tasks pending)
  before starting — it consumes the wiki and would rebase across the rename.
- FEAT-520 `graphindex-postgres-backend` has merged; its three files move here
  with Modules 2 and 3.

---

## 8. Open Questions

**Resolved in the brainstorm — carried forward, not reopened:**

- [x] Flow type / base branch — *Resolved in brainstorm*: feature on `dev`.
- [x] Import name — *Resolved in brainstorm*: `parrot_graphindex`, distribution
      `parrot-graphindex`, at `packages/parrot-graphindex/`.
- [x] One distribution or two — *Resolved in brainstorm*: one. `wiki/` has 18
      hard imports of `graphindex/`; they are not separable.
- [x] Where does pageindex go — *Resolved in brainstorm*: split. Pure core
      (tree builder, `md_builder`, `store`, `content_store`, `tree_ops`,
      `schemas`, `retriever`, `vector_walk`, `embedding_store`, `utils`,
      `hybrid_search`, `prompts`, `ingest`) moves; `toolkit.py`,
      `llm_adapter.py`, `loader.py`, `pdf_to_markdown.py` stay. §3 Module 4.
- [x] LLM-dependent CLI commands — *Resolved in brainstorm*: `LLMCaller`
      Protocol (built in FEAT-540); without a provider the commands warn and
      are unavailable; core registers its client. §5 pins exit code 2.
- [x] Backward-compat mechanism — *Resolved in brainstorm*: `sys.meta_path`
      finder, as `parrot.tools` → `parrot_tools`; no stub modules. §3 Module 5.
- [x] Versioning — *Resolved in brainstorm*: workspace member, lockstep with
      `/release`. §3 Module 8.
- [x] Phasing — *Resolved in brainstorm*: two FEATs. This is the second.
- [x] navconfig — *Resolved in brainstorm*: optional lazy credential provider,
      a dependency of `[postgres]`/`[arangodb]` only; `parrot.conf` never
      enters the standalone. §7 External Dependencies.
- [x] `pageindex/hybrid_search.py` uses `parrot._imports.lazy_import`
      (`_imports.py:110`) — *Resolved in brainstorm*: it moves; the standalone
      carries its own small `lazy_import` (no `parrot.*` import allowed).
      §3 Module 1.
- [x] Obsidian: does `parrot.interfaces.obsidian` have consumers outside wiki?
      — *Resolved in brainstorm*: yes, 12 modules (re-verified 2026-09-09, §6).
      Recommendation adopted here: move `interfaces/obsidian` into the
      standalone **base** (marko + python-frontmatter are small), keeping
      `[obsidian]` for vault-sync / MCP-only bits. **Final call is yours** —
      confirm or overturn before Module 4 starts.

**Still open:**

- [ ] Should core's extras `graphindex` / `wiki-languages` / `wiki-structural`
      / `leiden` / `wiki` (`packages/ai-parrot/pyproject.toml:250,275,290,299,307`)
      be kept as forwards (`ai-parrot[wiki]` → `parrot-graphindex[all]`) or
      removed with a deprecation note? — *Owner: Jesus Lara* **(blocks Module 7)**
- [ ] Entry-point group name (`parrot_graphindex.providers`), and do the wiki
      backends register through it too, or keep the import-time
      `register_wiki_backend()` call (`wiki/store.py:401`)? —
      *Owner: FEAT-541 implementer* **(blocks Module 6)**
- [ ] CI: does the GitHub build matrix need an explicit order (build
      `parrot-graphindex` before `ai-parrot`) or does `uv build --all-packages`
      resolve it from `[tool.uv.sources]`? — *Owner: FEAT-541 implementer*
      *(Downgraded from "blocks Module 8" after re-checking `dev` on
      2026-09-10: 15 `ai-parrot-client-*` satellites already build in this
      workspace with workspace sources and a core↔satellite cycle, so this is
      verification rather than an unknown.)*
- [ ] Out-of-scope but adjacent: the 15 `ai-parrot-client-*` packages are
      missing from `scripts/release.py` `PACKAGES` and are therefore stranded
      at their initial version (the `parrot-codec` failure mode). Separate
      change, or fold into Module 8? — *Owner: Jesus Lara*
- [ ] Jira v2: once `LLMCaller` exists, should `interfaces/jira` (aiohttp +
      pydantic) also move behind a `[jira]` extra so `ingest-jira` works
      standalone with a registered caller? — *Owner: Jesus Lara*
      *(Not blocking — deferrable to a follow-up feature.)*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-09 | Jesus Lara (with Claude) | Initial draft from `parrot-graphindex-standalone.brainstorm.md` (Option B, phase 2 of 2) |
| 0.2 | 2026-09-10 | Jesus Lara (with Claude) | Re-verified against `dev` @ `24ff50f03`: dropped the "first inverted arrow" claim (15 `ai-parrot-client-*` satellites already cycle with core via extras + workspace sources); downgraded the CI-ordering question to verification; recorded that `release.py` `PACKAGES` covers 13 of 27 workspace packages |
