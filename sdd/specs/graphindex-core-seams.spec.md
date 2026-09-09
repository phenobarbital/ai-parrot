---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: GraphIndex Core Seams

**Feature ID**: FEAT-540
**Date**: 2026-09-09
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 1.1.0

> Phase 1 of 2. This spec cuts the seams *inside* `ai-parrot` core so that
> `parrot.knowledge.graphindex` and `parrot.knowledge.wiki` stop crossing
> into the agent framework. The physical move to a standalone distribution
> is **FEAT-541 `parrot-graphindex-package`** and does not start until this
> spec is merged.
>
> Source brainstorm: `sdd/proposals/parrot-graphindex-standalone.brainstorm.md`
> (Recommended Option B, two-FEAT phasing).

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit` (LLM wiki) and GraphIndex are the parts of AI-Parrot that a
developer can use *without* an agent: point them at a repository, run
`wikitoolkit build`, and get a queryable knowledge graph plus a local MCP
server for Claude Code / Codex. Tools in the same space — `graphify`,
`zvec-grep` — install in one `pip install` and work in seconds.

Today that use case is impossible without installing the whole framework.
`ai-parrot` core declares 55 runtime dependencies (navigator-api,
navigator-auth, pandas, pyarrow, faiss-cpu, sqlglot, …) and a `parrot.conf`
settings module with import-time side effects (Navigator startup banner,
settings directory resolution, Google model import).

The measured cause is **not** the wiki/graphindex code itself. It is a small
number of eager package roots and framework imports that the graph code
crosses to fetch a Pydantic model, a dataclass, or a tool base class:

| Gateway | Trigger | Drags in |
|---|---|---|
| `parrot/knowledge/ontology/__init__.py` | `from parrot.knowledge.ontology.schema import TenantContext` — **9** call sites in `graphindex/` | `.mixin` → bots → clients → `parrot.conf` → navconfig, navigator_eventbus, aiohttp, pandas, faiss |
| `parrot/stores/__init__.py` | `from parrot.stores.models import Document` (`graphindex/extractors/loader.py:38`, `graphindex/loader.py:32`) | `.abstract` → `AbstractStore` → `parrot.conf` |
| `wiki/documents.py:26` | top-level `import aiohttp` for one fetch path | aiohttp |
| `wiki/tools.py:21`, `wiki/toolkit.py:31`, `wiki/structural/*` | `parrot.tools.abstract` / `parrot.tools.toolkit` | the tool machinery and everything it imports |

Measured on `dev` at `81e087bd8` (2026-09-09, this venv):

| Import | modules today | heavy packages loaded |
|---|---:|---|
| `parrot.knowledge.ontology.schema` | 1607 | navconfig, parrot.conf, navigator_eventbus, asyncdb, pandas, faiss, aiohttp, redis, asyncpg, pyarrow |
| `parrot.knowledge.graphindex` | 1959 | same |
| `parrot.knowledge.graphindex.builder` | 2511 | same |
| `parrot.knowledge.wiki.cli` | 1995 | same |

The measurement methodology and the earlier per-seam attribution come from
`artifacts/logs/lazy-ontology-import-measurement.md` on the throwaway branch
`exp-lazy-ontology` (commit `c4555d7d1`). That branch is discarded; the
evidence log is what carries forward. With PEP 562 lazy roots for the two
packages plus a lazy `aiohttp` import, the same measurement dropped
`parrot.knowledge.wiki.cli` from 1930 to **813** modules and loaded none of
the framework surfaces above.

### Goals

- G1 — `import parrot.knowledge.wiki.cli` loads **≤ 850** modules and loads
  none of: `navconfig`, `parrot.conf`, `navigator_eventbus`, `asyncdb`,
  `pandas`, `faiss`, `pyarrow`, `redis`, `asyncpg`.
- G2 — `import parrot.knowledge.ontology.schema` loads **≤ 260** modules
  (it imports only `re` and `pydantic`; the cost today is its package root).
- G3 — Nothing under `parrot/knowledge/wiki/` or
  `parrot/knowledge/graphindex/` imports `parrot.tools.*`,
  `parrot.clients.*`, `parrot.loaders.*`, `parrot.stores.*` or
  `parrot.embeddings.*` at module level.
- G4 — Framework capability is preserved exactly: agents keep getting
  real embedders, a real LLM adapter, a real PageIndex toolkit, and the
  Arango/Postgres wiki planes — injected rather than imported.
- G5 — The wiki MCP server runs without `parrot.mcp` being importable,
  while the in-framework `StdioMCPServer` path stays available.
- G6 — After this spec, the graph tree is `git mv`-shaped: FEAT-541 can move
  it without further behavioural edits.

### Non-Goals (explicitly out of scope)

- Creating `packages/parrot-graphindex/` or the `parrot_graphindex` import
  name. That is FEAT-541.
- The `sys.meta_path` redirector for old dotted paths. FEAT-541.
- Changing `ai-parrot`'s dependency list or extras. FEAT-541.
- Rebuilding or migrating existing planes under `~/.parrot/wikis/*/wiki.db`.
  No schema change is in scope.
- Slimming core's 55 dependencies in place (brainstorm Option C, rejected —
  see `proposals/parrot-graphindex-standalone.brainstorm.md`), and
  publishing from a separate repository by vendoring (Option D, rejected).
- Moving `parrot/interfaces/obsidian/` or `parrot/interfaces/jira/`.
  FEAT-541 and later.

---

## 2. Architectural Design

### Overview

Every place where graph code reaches into the framework is replaced by one
of three seams:

1. **Lazy package roots (PEP 562)** — `parrot/knowledge/ontology/__init__.py`
   and `parrot/stores/__init__.py` keep their public names in `__all__` but
   resolve them through a module-level `__getattr__`, so
   `from parrot.knowledge.ontology.schema import TenantContext` no longer
   executes `.mixin` → bots → clients → `parrot.conf`.
2. **Protocols** — `parrot/knowledge/graphindex/protocols.py` declares
   `Embedder`, `LLMCaller` and `PageIndexer` as `typing.Protocol`s mirroring
   the *subset* of `GraphIndexEmbedder`, `PageIndexLLMAdapter` and
   `PageIndexToolkit` that graph code actually calls. `GraphIndexBuilder`,
   `NoveltyScorer` and `IngestTriageRouter` type their parameters against the
   Protocols; `factory.py` and the CLI inject the concrete framework classes
   when they are importable, and fall back to the built-in
   `HashingGraphEmbedder` or to a `ProviderNotAvailable` error otherwise.
3. **Relocation** — agent-facing toolkits move out of the graph tree into
   `parrot_tools/wiki/`, where framework imports are already the norm
   (precedent: `GraphIndexToolkit`).

Two smaller seams support these: a single `resolve_setting()` configuration
reader that makes navconfig optional and lazy, and minimal `Document` /
`Loader` shapes local to graphindex so the loaders stop importing
`parrot.stores.models` / `parrot.loaders.abstract`.

**Resolved in the brainstorm and binding on this spec**: `navconfig` stays
as an optional, lazily imported credential provider (never a base import);
`asyncdb` stays as the driver behind the Arango and Postgres planes;
`HashingGraphEmbedder` (today at `graphindex/factory.py:116`) is the default
`Embedder`; the pageindex split keeps `toolkit.py`, `llm_adapter.py`,
`loader.py` and `pdf_to_markdown.py` in core.

### Component Diagram

```
      ┌──────────────────────── ai-parrot core (framework) ────────────────────────┐
      │                                                                            │
      │  parrot.embeddings.EmbeddingRegistry ──┐                                   │
      │  parrot.knowledge.pageindex.llm_adapter.PageIndexLLMAdapter ──┐            │
      │  parrot.knowledge.pageindex.toolkit.PageIndexToolkit ──┐      │            │
      │  parrot.knowledge.ontology.graph_store.OntologyGraphStore ─┐  │            │
      │                                                        │  │  │            │
      └────────────────────────────────────────────────────────┼──┼──┼────────────┘
                                                     injects   │  │  │
                                                               ▼  ▼  ▼
   ┌──────────────── graph tree (framework-free after this spec) ─────────────────┐
   │                                                                              │
   │   graphindex/protocols.py                                                    │
   │     Embedder · LLMCaller · PageIndexer      ◄── structural typing only        │
   │            ▲            ▲          ▲                                          │
   │            │            │          │                                          │
   │   graphindex/factory.py (wires providers; HashingGraphEmbedder default)       │
   │            │            │          │                                          │
   │   GraphIndexBuilder   IngestTriageRouter / NoveltyScorer                      │
   │            │                                                                  │
   │   graphindex/models.py  (local Document / Loader shapes)                      │
   │   wiki/project.py       resolve_setting()  ──lazy──►  navconfig (optional)     │
   │   wiki/mcp_server.py    ──┬── parrot.mcp StdioMCPServer  (in-framework)        │
   │                          └── mcp SDK stdio               (standalone)          │
   └──────────────────────────────────────────────────────────────────────────────┘
                                     │ plain service functions
                                     ▼
   ┌──────────────── ai-parrot-tools (parrot_tools.wiki) ─────────────────────────┐
   │   LLMWikiToolkit · Wiki*Tool · VaultIngestTool                                │
   │   CodeStructuralToolkit · WikiSymbolLookup/CodeOutline/BlastRadius Tools       │
   └──────────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/knowledge/ontology/__init__.py` | modifies | PEP 562 lazy root; `TenantContext` et al. still importable from the package |
| `parrot/stores/__init__.py` | modifies | PEP 562 lazy root; `extend_path` and `supported_stores` stay eager (cheap) |
| `GraphIndexBuilder` (`builder.py:60`) | modifies | `embedder` / `pageindex_toolkit` typed as `Embedder` / `PageIndexer` |
| `GraphIndexEmbedder` (`embed.py:25`) | modifies | becomes an *adapter* in core satisfying `Embedder`; `EmbeddingRegistry` + faiss imports leave the graph tree |
| `NoveltyScorer` (`triage.py:67`), `IngestTriageRouter` (`triage.py:252`) | modifies | accept `LLMCaller` instead of importing `PageIndexLLMAdapter` |
| `PageIndexLLMAdapter` (`llm_adapter.py:42`) | unchanged | already satisfies `LLMCaller` structurally (`ask`, `ask_structured`, `ask_json`) |
| `PageIndexToolkit` (`toolkit.py:50`) | unchanged | already satisfies `PageIndexer` |
| `parrot_tools/wiki/` | new | destination for the relocated toolkits |
| `parrot_tools/business_automation/memory.py:31,110` | modifies | already a lazy `LLMWikiToolkit` import; repoint to `parrot_tools.wiki` |
| `wiki/mcp_server.py:90,202` | modifies | dual transport: `parrot.mcp` when importable, `mcp` SDK otherwise |
| `wiki/project.py:499,529,558` | modifies | `_navconfig` / `_env_credential` fold into `resolve_setting()` |
| `wiki/cli.py:464` (`_env_setting`) | modifies | delegates to `resolve_setting()` |
| `graphindex/loader.py:337` | modifies | inline navconfig import replaced by `resolve_setting()` |
| `graphindex/persist.py:36`, `loader.py:34` | modifies | `OntologyGraphStore` moves behind the arango seam (lazy/injected) |
| `parrot.mcp.local_server.StdioMCPServer` (`local_server.py:36`) | unchanged | kept as the in-framework transport |

### Data Models

```python
# parrot/knowledge/graphindex/models.py  (NEW — framework-free shapes)
from pydantic import BaseModel, Field

class GraphDocument(BaseModel):
    """Minimal document shape graphindex loaders need.

    Mirrors the two fields graphindex reads from ``parrot.stores.models
    .Document`` (page_content, metadata) without importing the stores
    package. Core adapters convert between the two.
    """
    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### New Public Interfaces

```python
# parrot/knowledge/graphindex/protocols.py  (NEW)
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class Embedder(Protocol):
    """Vector provider for graph nodes. Mirrors GraphIndexEmbedder.embed_nodes."""
    async def embed_nodes(self, *args: Any, **kwargs: Any) -> Any: ...

@runtime_checkable
class LLMCaller(Protocol):
    """The subset of PageIndexLLMAdapter that wiki/graphindex call."""
    async def ask(self, *args: Any, **kwargs: Any) -> Any: ...
    async def ask_structured(self, *args: Any, **kwargs: Any) -> Any: ...
    async def ask_json(self, *args: Any, **kwargs: Any) -> Any: ...

@runtime_checkable
class PageIndexer(Protocol):
    """What GraphIndexBuilder needs from PageIndexToolkit."""
    ...  # exact surface derived from builder.py call sites during implementation


class ProviderNotAvailable(RuntimeError):
    """Raised when a required provider was never registered.

    Message names the provider role and the pip extra / distribution that
    supplies it; the CLI maps it to exit code 2.
    """


# parrot/knowledge/wiki/project.py  (NEW function)
def resolve_setting(key: str, *, default: Any = None, explicit: Any = None) -> Any:
    """Resolve one configuration value.

    Order: ``explicit`` argument → ``os.environ`` → navconfig (imported
    lazily, only if the key was not already found) → ``wiki.json`` defaults
    → ``default``. A navconfig import failure is swallowed, logged at debug,
    and resolution continues — deliberate, because this path runs inside the
    Claude Code PreToolUse hook.
    """
```

---

## 3. Module Breakdown

### Module 1: Lazy package roots + import-ceiling test
- **Path**: `parrot/knowledge/ontology/__init__.py`, `parrot/stores/__init__.py`,
  `parrot/knowledge/wiki/documents.py`,
  `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` (new)
- **Responsibility**: PEP 562 `__getattr__` roots for the two eager packages;
  move `import aiohttp` (`documents.py:26`) inside the one fetch function that
  uses it (`documents.py:568-595`). Add the parametrized ceiling test that runs
  each import in a **subprocess** (module counts are not resettable in-process)
  and asserts both `len(sys.modules)` and the forbidden-package list.
- **Depends on**: nothing — start here; it is the objective gate every other
  module is measured against.

### Module 2: Provider Protocols + injection
- **Path**: `parrot/knowledge/graphindex/protocols.py` (new),
  `builder.py`, `embed.py`, `factory.py`, `wiki/triage.py`
- **Responsibility**: declare `Embedder` / `LLMCaller` / `PageIndexer` and
  `ProviderNotAvailable`; retype `GraphIndexBuilder.__init__`
  (`builder.py:123`), `NoveltyScorer` (`triage.py:90` `grounding_evaluator`
  kwarg) and `IngestTriageRouter`; sever `EmbeddingRegistry` (`embed.py:15`),
  `quiet_faiss_loader` (`embed.py:17`), the module-level `faiss` import
  (`embed.py:20`) and `PageIndexToolkit` (`builder.py:55`) from the graph tree,
  leaving `HashingGraphEmbedder` (`factory.py:116`) as the default.
- **Depends on**: Module 1 (the ceiling test proves the severing worked)

### Module 3: Wiki toolkits → `parrot_tools/wiki/`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/wiki/` (new package),
  removing `parrot/knowledge/wiki/toolkit.py`,
  `parrot/knowledge/wiki/structural/toolkit.py`, and the `AbstractTool`
  subclasses from `parrot/knowledge/wiki/tools.py` and
  `parrot/knowledge/wiki/structural/tools.py`
- **Responsibility**: relocate `LLMWikiToolkit` (`toolkit.py:41`),
  `WikiQueryTool`/`WikiPageTool`/`WikiRelatedTool`/`WikiRememberTool`/
  `WikiNoteTool`/`WikiStatusTool`/`VaultIngestTool` (`tools.py:161,203,240,272,
  354,419,435`), `CodeStructuralToolkit` (`structural/toolkit.py:25`) and
  `WikiSymbolLookupTool`/`WikiCodeOutlineTool`/`WikiBlastRadiusTool`
  (`structural/tools.py:105,145,180`). The Pydantic input models
  (`tools.py:99-157`) move with them. **The framework-free helpers
  `_scoped_store` (`tools.py:24`) and `_unknown_namespace_error`
  (`tools.py:80`) do NOT move** — `structural/tools.py:29` imports them and
  they call only `BaseWikiStore`; re-home them in a wiki service module that
  both sides import. Repoint `parrot_tools/business_automation/memory.py:31,110`
  and the tests at `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py`,
  `test_vault_ingest_tool.py`, `packages/ai-parrot-tools/tests/business_automation/test_memory.py`.
- **Depends on**: Module 1

### Module 4: `resolve_setting()` — one configuration reader
- **Path**: `parrot/knowledge/wiki/project.py`, `parrot/knowledge/wiki/cli.py`,
  `parrot/knowledge/graphindex/loader.py`
- **Responsibility**: add `resolve_setting()`; fold in `_navconfig`
  (`project.py:499`), `_env_credential` (`project.py:529`), `_env_setting`
  (`cli.py:464`) and the inline navconfig block (`loader.py:337-342`).
  `resolve_arango_params` (`project.py:558`) and `resolve_wiki_env`
  (`project.py:792`) keep their signatures and call through it. A missing
  credential produces one actionable message naming the key and the
  resolution order tried — never a loopback default.
- **Depends on**: Module 1

### Module 5: MCP dual transport
- **Path**: `parrot/knowledge/wiki/mcp_server.py`
- **Responsibility**: `create_wiki_mcp_server` (`mcp_server.py:90`) and `main`
  (`mcp_server.py:202`) select the `parrot.mcp` `StdioMCPServer` path when
  `parrot.mcp` is importable and an `mcp`-SDK stdio server (mcp 1.29.0, already
  installed) otherwise. **`mcp_server.py:27` imports `create_wiki_tools` from
  `wiki/tools.py`, which Module 3 relocates** — so the SDK path must register
  the same six operations from plain wiki service functions rather than from
  `AbstractTool` instances. The exposed tool names and schemas must not change:
  `.claude/settings.local.json` entries keep their shape.
- **Depends on**: Module 3 (it consumes what Module 3 moves)

### Module 6: Local `Document` / `Loader` shapes
- **Path**: `parrot/knowledge/graphindex/models.py` (new),
  `parrot/knowledge/graphindex/extractors/loader.py`,
  `parrot/knowledge/graphindex/loader.py`
- **Responsibility**: define `GraphDocument` (and the minimal loader shape) so
  `extractors/loader.py:38` and `loader.py:31-32` stop importing
  `parrot.stores.models.Document` and `parrot.loaders.abstract.AbstractLoader`;
  add the core-side adapter that converts a `parrot.stores.models.Document`
  into a `GraphDocument` at the framework boundary.
- **Depends on**: Module 1

### Module 7: Ontology seam
- **Path**: `parrot/knowledge/graphindex/persist.py`,
  `parrot/knowledge/graphindex/loader.py`
- **Responsibility**: `parrot/knowledge/ontology/schema.py` is already
  import-clean (only `re` + pydantic) and stays as the shared model source;
  the **9** `from parrot.knowledge.ontology.schema import …` call sites in
  `graphindex/` become cheap once Module 1 lands. Move the two
  `OntologyGraphStore` imports (`persist.py:36`, `loader.py:34`) behind the
  arango seam — injected or lazily imported, never at module level.
- **Depends on**: Module 1, Module 2

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_ontology_root_lazy` | 1 | `from parrot.knowledge.ontology import OntologyRAGMixin` still resolves; `parrot.knowledge.ontology.mixin` absent from `sys.modules` after importing only `schema` |
| `test_stores_root_lazy` | 1 | `from parrot.stores import AbstractStore` resolves; `supported_stores` unchanged |
| `test_documents_aiohttp_lazy` | 1 | importing `wiki.documents` leaves `aiohttp` out of `sys.modules`; the fetch path still works |
| `test_protocols_structural_match` | 2 | `isinstance(GraphIndexEmbedder(...), Embedder)`, `PageIndexLLMAdapter` satisfies `LLMCaller`, `PageIndexToolkit` satisfies `PageIndexer` |
| `test_builder_accepts_protocol_double` | 2 | `GraphIndexBuilder` runs with a stub embedder that only implements `embed_nodes` |
| `test_default_embedder_is_hashing` | 2 | with no provider injected, `factory` yields `HashingGraphEmbedder` |
| `test_provider_not_available_message` | 2 | `ProviderNotAvailable` names the role and the supplying distribution |
| `test_wiki_toolkit_importable_from_parrot_tools` | 3 | `from parrot_tools.wiki import LLMWikiToolkit, CodeStructuralToolkit` |
| `test_wiki_tools_produce_same_schemas` | 3 | tool names + input schemas byte-identical to pre-move (golden file) |
| `test_resolve_setting_order` | 4 | explicit → env → navconfig → wiki.json → default, each level asserted |
| `test_resolve_setting_navconfig_broken` | 4 | a raising navconfig import degrades to `os.environ` and logs at debug |
| `test_missing_credential_message` | 4 | names the key and the resolution order; asserts no loopback default |
| `test_mcp_sdk_path_selected` | 5 | with `parrot.mcp` unimportable (monkeypatched finder), the SDK server is built and exposes the same tool names |
| `test_mcp_framework_path_preserved` | 5 | with `parrot.mcp` present, `create_wiki_mcp_server` returns `StdioMCPServer` |
| `test_graph_document_roundtrip` | 6 | core adapter converts `stores.models.Document` ↔ `GraphDocument` losslessly for `page_content` + `metadata` |

### Integration Tests

| Test | Description |
|---|---|
| `test_import_ceilings` | Parametrized subprocess check — the acceptance gate for G1/G2/G3 (see §5) |
| `test_no_framework_imports_in_graph_tree` | AST scan of `parrot/knowledge/{wiki,graphindex}/**/*.py`: no module-level `parrot.tools`, `parrot.clients`, `parrot.loaders`, `parrot.stores`, `parrot.embeddings` import |
| `test_wikitoolkit_build_end_to_end` | `wikitoolkit build` over a fixture repo produces the same page/edge counts as before the change |
| `test_wiki_plane_backward_readable` | A `wiki.db` built by pre-FEAT-540 code opens and queries unchanged |
| `test_agent_path_unchanged` | An agent wired with `LLMWikiToolkit` + `GraphIndexToolkit` answers a query using a real embedder and adapter |

### Test Data / Fixtures

```python
@pytest.fixture
def import_ceiling():
    """Run one import in a clean subprocess; return (module_count, heavy_loaded)."""
    def _run(module: str) -> tuple[int, list[str]]:
        ...  # subprocess.run([sys.executable, "-c", ...]) — counts are not
             # resettable in-process, so every measurement forks
    return _run

@pytest.fixture
def stub_embedder():
    class _Stub:
        async def embed_nodes(self, nodes, **kw): return nodes
    return _Stub()
```

---

## 5. Acceptance Criteria

- [ ] `import parrot.knowledge.wiki.cli` loads **≤ 850** modules in a clean
      subprocess (baseline on `dev` @ `81e087bd8`: 1995)
- [ ] `import parrot.knowledge.ontology.schema` loads **≤ 260** modules
      (baseline: 1607)
- [ ] `import parrot.knowledge.graphindex` loads **≤ 800** modules
      (baseline: 1959)
- [ ] `import parrot.knowledge.graphindex.builder` loads **≤ 1200** modules
      (baseline: 2511)
- [ ] None of `navconfig`, `parrot.conf`, `navigator_eventbus`, `asyncdb`,
      `pandas`, `faiss`, `pyarrow`, `redis`, `asyncpg` appears in `sys.modules`
      after any of the four imports above
- [ ] No module under `parrot/knowledge/wiki/` or
      `parrot/knowledge/graphindex/` imports `parrot.tools.*`,
      `parrot.clients.*`, `parrot.loaders.*`, `parrot.stores.*` or
      `parrot.embeddings.*` at module level (AST-scan test)
- [ ] `from parrot_tools.wiki import LLMWikiToolkit, CodeStructuralToolkit`
      resolves; the moved tools expose byte-identical names and input schemas
- [ ] `wikitoolkit` CLI surface unchanged: `build`, `query`, `page`, `related`,
      `remember`, `note`, `link`, `memories`, `audit`, `status`, `export`,
      `symbols {lookup,outline,blast}`, `ns {list,add,remove}`, `mcp`
- [ ] The wiki MCP server starts and serves the same tool names with
      `parrot.mcp` unimportable, and still returns `StdioMCPServer` when it is
- [ ] `resolve_setting()` is the only configuration reader in the graph tree —
      `_env_setting`, `_env_credential` and the inline navconfig block are gone
- [ ] A `wiki.db` plane built before this change opens and queries unchanged
- [ ] `pytest packages/ai-parrot/tests/knowledge/ -v` passes
- [ ] `pytest packages/ai-parrot-tools/tests/ -v` passes
- [ ] `ruff check .` clean on changed files
- [ ] Google-style docstrings + type hints on every new/changed public symbol
- [ ] No breaking change to any documented public import path

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every entry below was re-verified against `dev` @ `81e087bd8` on
> **2026-09-09**. Line numbers drifted from the 2026-09-03 brainstorm because
> FEAT-520 (graphindex-postgres-backend) and FEAT-539 (contracts) landed in
> between — the numbers here supersede the brainstorm's.

### Verified Imports

```python
from parrot.knowledge.ontology.schema import TenantContext, MergedOntology   # schema.py:529, 452
from parrot.knowledge.wiki.project import _navconfig, resolve_arango_params  # project.py:499, 558
from parrot.knowledge.wiki.store import register_wiki_backend                # store.py:401
from parrot.knowledge.wiki.tools import create_wiki_tools                    # tools.py:544
from parrot.mcp.local_server import StdioMCPServer                           # local_server.py:36
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter       # llm_adapter.py:42
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit              # toolkit.py:50
from parrot.embeddings.registry import EmbeddingRegistry                     # registry.py:55
from parrot.utils.faiss_logging import quiet_faiss_loader                    # faiss_logging.py:34
from parrot.stores.models import Document                                    # models.py:19
from parrot_tools.graphindex.toolkit import GraphIndexToolkit                # toolkit.py:110
from parrot._imports import lazy_import                                      # _imports.py:110
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/__init__.py
class _AliasLoader(importlib.abc.Loader): ...                    # line 31
class _ParrotToolsRedirector(importlib.abc.MetaPathFinder): ...  # line 50
#   → the compat pattern FEAT-541 clones; NOT used in this spec

# packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py
class GraphIndexEmbedder: ...                                    # line 25
    async def embed_nodes(...)                                   # line 58
# top-level imports to sever:
from parrot.embeddings.registry import EmbeddingRegistry         # line 15
from parrot.utils.faiss_logging import quiet_faiss_loader        # line 17
quiet_faiss_loader()                                             # line 19 (import-time call)
import faiss                                                     # line 20

# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # line 55  ← sever
from parrot.knowledge.ontology.schema import TenantContext       # line 54
class GraphIndexBuilder: ...                                     # line 60
    def __init__(self, ..., pageindex_toolkit: PageIndexToolkit | None = None, ...)  # line 123
    self.pageindex_toolkit = pageindex_toolkit                   # line 136

# packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext  # line 35
class HashingGraphEmbedder: ...                                  # line 116  ← default Embedder

# packages/ai-parrot/src/parrot/knowledge/graphindex/grounding.py
class GroundingEvaluator: ...                                    # line 96

# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py
class NoveltyScorer: ...                                         # line 67
class IngestTriageRouter: ...                                    # line 252

# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter: ...                                   # line 42
    async def ask(...)                                           # line 61
    async def ask_structured(...)                                # line 99
    async def ask_with_finish_info(...)                          # line 151
    async def ask_json(...)                                      # line 201
#   → LLMCaller mirrors ask / ask_structured / ask_json

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit): ...                     # line 50 (__init__ line 88)

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py  (imports: re + pydantic ONLY)
class MergedOntology(BaseModel): ...                             # line 452
class TenantContext(BaseModel): ...                              # line 529
class ResolvedIntent(BaseModel): ...                             # line 547
class EnrichedContext(BaseModel): ...                            # line 582

# packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py  — EAGER today (lines 2-7)
from .cache import OntologyCache
from .graph_store import OntologyGraphStore
from .intent import OntologyIntentResolver
from .mixin import OntologyRAGMixin          # ← the expensive one
from .schema import EnrichedContext, MergedOntology, ResolvedIntent, TenantContext
from .tenant import TenantOntologyManager

# packages/ai-parrot/src/parrot/stores/__init__.py  — EAGER today
__path__ = extend_path(__path__, __name__)                       # line 2
from .abstract import AbstractStore                              # line 4  ← the expensive one
supported_stores = {...}                                         # lines 6-13

# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):                                       # line 19
    page_content: str                                            # line 24
    metadata: Dict[str, Any] = Field(default_factory=dict)       # line 25

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def _navconfig() -> Any | None: ...                              # line 499
def _env_credential(key: str, default: Any) -> Any: ...          # line 529
def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]: ...  # line 558
def resolve_wiki_env(env: str | None = None) -> str: ...         # line 792

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _env_setting(name: str) -> str | None: ...                   # line 464

# packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py
from parrot.loaders.abstract import AbstractLoader               # line 31  ← sever
from parrot.stores.models import Document                        # line 32  ← sever
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # line 34  ← arango seam
from parrot.knowledge.ontology.schema import TenantContext       # line 35
    from navconfig import config                                 # line 337 (local import)

# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py
from parrot.stores.models import Document                        # line 38  ← sever

# packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # line 36  ← arango seam

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None: ...  # line 401

# packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
from asyncdb import AsyncDB                                      # line 34
    AsyncDB("arangodb", params={**self._params, "database": ...})  # line 292

# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py
import aiohttp                                                   # line 26  ← make lazy
    aiohttp.ClientTimeout / ClientSession / ClientError          # lines 568, 573, 595 (only uses)

# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
from parrot.knowledge.wiki.store import create_wiki_store        # line 26
from parrot.knowledge.wiki.tools import create_wiki_tools        # line 27  ← Module 3 moves this
def create_wiki_mcp_server(root: Path) -> StdioMCPServer: ...    # line 90
def main() -> None: ...                                          # line 202

# packages/ai-parrot/src/parrot/mcp/local_server.py
class StdioMCPServer(LocalMCPServerBase): ...                    # line 36

# ── Agent-facing surface to relocate (Module 3) ──
# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
def _scoped_store(store: BaseWikiStore, namespace: str | None) -> BaseWikiStore  # line 24  ← STAYS
def _unknown_namespace_error(store: BaseWikiStore, namespace: str) -> str        # line 80  ← STAYS
class WikiQueryInput / WikiPageInput / WikiRelatedInput / WikiRememberInput
      / WikiNoteInput / VaultIngestInput / WikiStatusInput(BaseModel)  # lines 99,114,122,130,138,143,157
class WikiQueryTool(AbstractTool): ...                           # line 161
class WikiPageTool(AbstractTool): ...                            # line 203
class WikiRelatedTool(AbstractTool): ...                         # line 240
class WikiRememberTool(AbstractTool): ...                        # line 272
class WikiNoteTool(AbstractTool): ...                            # line 354
class WikiStatusTool(AbstractTool): ...                          # line 419
class VaultIngestTool(AbstractTool): ...                         # line 435
def create_wiki_tools(store, root=None, config=None) -> list[AbstractTool]  # line 544
from parrot.tools.abstract import AbstractTool, ToolResult       # line 21  ← the framework tie

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
def _is_federated(store: Any) -> bool: ...                       # line 34
class LLMWikiToolkit(AbstractToolkit): ...                       # line 41
from parrot.tools.toolkit import AbstractToolkit                 # line 31  ← the framework tie

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py
class CodeStructuralToolkit(AbstractToolkit): ...                # line 25
from parrot.tools.toolkit import AbstractToolkit                 # line 22

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py
class WikiSymbolLookupTool(AbstractTool): ...                    # line 105
class WikiCodeOutlineTool(AbstractTool): ...                     # line 145
class WikiBlastRadiusTool(AbstractTool): ...                     # line 180
from parrot.knowledge.wiki.tools import _scoped_store, _unknown_namespace_error  # line 29
from parrot.tools.abstract import AbstractTool, ToolResult       # line 30

# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py
class GraphIndexToolkit(AbstractToolkit): ...                    # line 110  ← relocation precedent
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `Embedder` Protocol | `GraphIndexEmbedder.embed_nodes()` | structural typing | `graphindex/embed.py:58` |
| `LLMCaller` Protocol | `PageIndexLLMAdapter.ask/ask_structured/ask_json` | structural typing | `pageindex/llm_adapter.py:61,99,201` |
| `PageIndexer` Protocol | `PageIndexToolkit` | injected into `GraphIndexBuilder` | `graphindex/builder.py:123,136` |
| default `Embedder` | `HashingGraphEmbedder` | `factory.py` fallback | `graphindex/factory.py:116` |
| `resolve_setting()` | navconfig | lazy import inside the function | `wiki/project.py:499` (pattern) |
| `parrot_tools.wiki` | `AbstractToolkit` | subclass, same as precedent | `parrot_tools/graphindex/toolkit.py:110` |
| MCP SDK path | `mcp` 1.29.0 | stdio server | installed, verified 2026-09-09 |
| MCP framework path | `StdioMCPServer` | returned by `create_wiki_mcp_server` | `mcp/local_server.py:36` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.graphindex.protocols`~~ — created by this spec.
- ~~`Embedder`, `LLMCaller`, `PageIndexer`, `ProviderNotAvailable`~~ — do not exist.
- ~~`parrot.knowledge.graphindex.models`~~ / ~~`GraphDocument`~~ — created by this spec.
- ~~`resolve_setting()`~~ — does not exist; today's readers are `_env_setting`
  (`cli.py:464`), `_env_credential` (`project.py:529`), and the inline
  navconfig block (`graphindex/loader.py:337`).
- ~~`parrot_tools.wiki`~~ — the directory does not exist
  (`parrot_tools/` has `graphindex/{__init__,toolkit,flowtask}.py`, no `wiki/`).
- ~~`packages/parrot-graphindex/`~~ / ~~`parrot_graphindex`~~ — FEAT-541, not this spec.
- ~~`HashingGraphEmbedder` in `embed.py`~~ — it is in `factory.py:116`;
  `embed.py` defines only `GraphIndexEmbedder`.
- ~~`.mcp.json` at the repo root~~ — CLAUDE.md mentions it, but the file is
  absent; the `wikitoolkit` MCP entry lives in `.claude/settings.local.json`.
- ~~`parrot/knowledge/__init__.py` imports~~ — the file exists but is
  import-clean already; it is not a gateway.
- ~~A dependency-free `parrot.stores.models` path~~ — importing it executes
  `parrot/stores/__init__.py` (eager `AbstractStore`) until Module 1 lands.
- ~~`hyperscan` / `google-re2` as parrot dependencies~~ — optional `pathspec`
  backends auto-detected at import; do not declare them.
- ~~`ai-parrot-tools` as a leaf package~~ — it declares
  `dependencies = ["ai-parrot", …]`; the precedent it sets is naming and
  toolkit placement, **not** dependency direction.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **PEP 562 lazy root** — module-level `__getattr__` + a complete `__all__`,
  so `dir()` and IDE completion keep working. Do not delete names.
- **Protocols, not ABCs** — `typing.Protocol` with `@runtime_checkable`;
  the framework classes must satisfy them *without* being modified to inherit.
- **Injection order** — explicit constructor argument first, then the
  registered provider, then the built-in default, then `ProviderNotAvailable`.
  (The entry-point group that makes registration automatic is FEAT-541; this
  spec wires explicit + default + error.)
- **Lazy imports name modules, not objects** — so that importing the graph
  tree never triggers `import parrot`.
- Google-style docstrings, strict type hints, Pydantic for structured data,
  `self.logger` over `print` — per `CLAUDE.md`.
- Async-first: no blocking I/O in async paths; `aiohttp`, never `requests`.

### Known Risks / Gotchas

- **Module counts are not measurable in-process.** `sys.modules` cannot be
  reset reliably. Every ceiling assertion must fork a subprocess, or it will
  silently pass by measuring an already-warm interpreter.
- **`mcp_server.py:27` depends on what Module 3 moves.** Sequence Module 3
  before Module 5, or the MCP server breaks mid-feature.
- **`structural/tools.py:29` imports two private helpers from `tools.py`.**
  If `_scoped_store` / `_unknown_namespace_error` move to `parrot_tools`, the
  remaining wiki code gains a `parrot_tools` dependency — the exact inversion
  this spec exists to prevent. They stay on the framework-free side.
- **`embed.py:19` calls `quiet_faiss_loader()` at import time** before
  `import faiss` on line 20. Severing these two lines changes faiss log
  behaviour for anything that relied on graphindex to silence it; the core
  adapter must keep calling it.
- **`from parrot.stores import ...` has an `extend_path` line** (`__init__.py:2`)
  that makes the PEP 420 namespace merge with `ai-parrot-embeddings` work.
  A lazy root must keep `__path__ = extend_path(...)` eager or the satellite
  backends stop resolving.
- **Both old and new tool import paths will exist during the transition.**
  Tests referencing `parrot.knowledge.wiki.tools` (three files, listed in
  Module 3) must be repointed in the same task, not left for FEAT-541.
- **`ontology/__init__.py` is imported by non-graph code too**
  (`OntologyRAGMixin`, `TenantOntologyManager` consumers). Laziness must not
  change what those callers get, only when they pay for it.
- **Concurrent branches touching the same files**: FEAT-481
  `fireflies-wiki-knowledgebase-agent` (16 tasks pending) is a wiki consumer;
  FEAT-520 has merged. Re-check for new in-flight work before starting.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `mcp` | `>=1.29` | stdio MCP server without `parrot.mcp` (already installed, 1.29.0) |
| `navconfig` | `>=2.4` | optional lazy credential provider — **not** promoted to a base import |
| `asyncdb` | `>=2.15` | unchanged; still the Arango/Postgres driver |

No new third-party dependency is added by this spec.

---

## Worktree Strategy

**Default isolation unit: `mixed`.**

Modules 1, 3 and 4 touch disjoint files and can run in parallel worktrees.
Module 2 overlaps `graphindex/embed.py` + `factory.py`; Module 7 depends on
both 1 and 2; Module 5 consumes Module 3's output.

| Lane | Modules | Files | Parallel with |
|---|---|---|---|
| L1 | 1 | `ontology/__init__.py`, `stores/__init__.py`, `wiki/documents.py`, new ceiling test | — (land first; it is the gate) |
| L2 | 2 → 7 | `graphindex/protocols.py`, `builder.py`, `embed.py`, `factory.py`, `wiki/triage.py`, `persist.py`, `loader.py` | L3, L4 |
| L3 | 3 → 5 | `parrot_tools/wiki/`, `wiki/tools.py`, `toolkit.py`, `structural/*`, `mcp_server.py` | L2, L4 |
| L4 | 4, 6 | `wiki/project.py`, `wiki/cli.py`, `graphindex/loader.py` (config lines), `graphindex/models.py`, `extractors/loader.py` | L2, L3 |

L2 and L4 both edit `graphindex/loader.py` — L2 the ontology imports
(lines 34-35), L4 the navconfig block (line 337) and the Document import
(line 32). Sequence them or accept a small merge.

**Cross-feature dependencies**: none blocking. FEAT-520 has merged
(`persist_postgres.py`, `pg_schema.py`, `wiki/postgres_store.py` present on
`dev`). **FEAT-541 must not start until this spec is merged.**

---

## 8. Open Questions

**Resolved in the brainstorm — carried forward, not reopened:**

- [x] Flow type / base branch — *Resolved in brainstorm*: feature on `dev`.
- [x] Import name — *Resolved in brainstorm*: `parrot_graphindex`
      (distribution `parrot-graphindex`). Applies to FEAT-541.
- [x] Where does pageindex go — *Resolved in brainstorm*: split; pure core
      (tree, `md_builder`, `store`, …) moves in FEAT-541, while `toolkit.py`,
      `llm_adapter.py`, `loader.py` and `pdf_to_markdown.py` stay in core.
      This spec keeps all four in core and reaches them through Protocols.
- [x] LLM-dependent CLI commands — *Resolved in brainstorm*: an `LLMCaller`
      Protocol; without a provider the commands warn and are unavailable;
      core registers its client. This spec defines the Protocol and the
      `ProviderNotAvailable` error (§2 New Public Interfaces).
- [x] Backward-compat mechanism — *Resolved in brainstorm*: `sys.meta_path`
      finder, as `parrot.tools` → `parrot_tools`. FEAT-541; no import path
      changes in this spec.
- [x] Fate of `exp-lazy-ontology` — *Resolved in brainstorm*: discard; this
      feature re-does the lazy roots in its own worktree (§1 keeps the
      evidence log reference).
- [x] Versioning — *Resolved in brainstorm*: workspace member, lockstep with
      `/release`. FEAT-541.
- [x] Phasing — *Resolved in brainstorm*: two FEATs — seams in core (this
      spec, FEAT-540), then the physical move (FEAT-541).
- [x] navconfig — *Resolved in brainstorm*: kept as an optional lazy
      credential provider; a dependency of `[postgres]`/`[arangodb]` only;
      `parrot.conf` never enters the standalone. Realized here by
      `resolve_setting()` (Module 4).
- [x] Where is `HashingGraphEmbedder` defined today? — *Resolved in
      brainstorm*: `graphindex/factory.py:118` — **re-verified 2026-09-09 as
      `factory.py:116`**; it becomes the default `Embedder` (Module 2).
- [x] `pageindex/hybrid_search.py` uses `parrot._imports.lazy_import`
      (`_imports.py:110`) — *Resolved in brainstorm*: it moves in FEAT-541 and
      the standalone carries its own small `lazy_import`. Out of scope here.

**Still open (none block this spec):**

- [ ] Should core's extras `graphindex` / `wiki-languages` / `wiki-structural`
      / `leiden` / `wiki` (`packages/ai-parrot/pyproject.toml:250,275,290,299,307`)
      be kept as forwards (`ai-parrot[wiki]` → `parrot-graphindex[all]`) or
      removed with a deprecation note? — *Owner: Jesus Lara*
      *(FEAT-541 decision; this spec does not touch extras.)*
- [ ] Does `PageIndexer` need the full `PageIndexToolkit` surface, or only the
      calls reachable from `GraphIndexBuilder`? — *Owner: FEAT-540 implementer*
      *(Derive from the call sites during Module 2; keep the Protocol minimal.)*
- [ ] Should the `mcp`-SDK stdio path be selected by import probe
      (`parrot.mcp` importable?) or by an explicit CLI flag / env var? —
      *Owner: FEAT-540 implementer* *(Module 5; probe is the brainstorm's
      wording, a flag is testable — decide with the test in hand.)*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-09 | Jesus Lara (with Claude) | Initial draft from `parrot-graphindex-standalone.brainstorm.md` (Option B, phase 1 of 2) |
