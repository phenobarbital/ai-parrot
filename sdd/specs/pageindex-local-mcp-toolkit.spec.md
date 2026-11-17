---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — carried from sdd/proposals/pageindex-tree-optimizer.brainstorm.md; only core files are touched
tags: [pageindex, mcp, tree-optimizer, local-toolkits, claude-code, codex]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-local-mcp.md, wiki/tools/mcp-local-toolkits.md]
  api_modules: [parrot.knowledge.pageindex.toolkit]
---

# Feature Specification: PageIndex Local MCP Toolkit

**Feature ID**: FEAT-842
**Date**: 2026-11-07
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

> Sixth slice of `sdd/proposals/pageindex-tree-optimizer.brainstorm.md` (revision 4), the
> only one whose declared dependency is just the first slice (FEAT-831
> `pageindex-generation-publication`, merged in PR #2024). It makes `PageIndexToolkit`
> servable by the existing `parrot mcp-local` / `parrot toolkits` machinery and ships a
> packaged `pageindex` template. It deliberately changes nothing in the runner, the
> installer or the host adapters, and it does not add tools of its own: the read tools of
> FEAT-840 (`pageindex-segment-store`, tasks TASK-5300..5313) and the later slices appear
> on the server automatically when they land, because the server lists whatever
> `PageIndexToolkit.get_tools()` returns. Source paths below are relative to
> `packages/ai-parrot/src/parrot/` unless stated; line numbers were verified at `dev` @
> `9c4c9390a0`.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

PageIndex is the structured-document plane of ai-parrot, yet a coding agent working in a
repository cannot reach it. Bookstore has a hand-built stdio server
(`knowledge/bookstore/mcp_server.py:101`) over a user-level library; PageIndex itself has
none, and it cannot be served by the generic machinery either:

- `PageIndexToolkit.__init__` (`knowledge/pageindex/toolkit.py:101`) requires a
  `PageIndexLLMAdapter` as its first positional argument. The toolkit server factory
  (`mcp/toolkit_server.py:338-342`) instantiates a toolkit as `toolkit_cls(**kwargs)` and
  passes the configured model as `kwargs["llm_client"]`; it never builds an adapter. A
  `pageindex:` section in `.parrot/mcp-toolkits.yaml` therefore fails with
  `Failed to instantiate toolkit 'pageindex'`.
- The class declares no `llm_dependent_tools` (default `frozenset()` at
  `tools/toolkit.py:313`), so the factory has no way to know which tools to hide when no
  `llm:` is configured — and most of the toolkit does not need one: tree management,
  markdown and ebook ingest, node edits, BM25 search and body retrieval are deterministic.
- `search` defaults to `use_llm_walk=True` (`toolkit.py:661`) and `retrieve` hard-codes it
  (`toolkit.py:739`); with no adapter both would crash inside
  `HybridPageIndexSearch._llm_rank` (`hybrid_search.py:284`).
- The nine packaged templates under `mcp/_toolkit_templates/` are bounded-source,
  browsing, database-query, lsp, memory, querysource, scraping, sdd-coder and
  targeted-writer. There is no `pageindex.yaml`, so `parrot toolkits install pageindex`
  has nothing to seed and no host (`.mcp.json`, `.codex/config.toml`, Antigravity) can be
  registered.
- `retrieve` returns the concatenated bodies of the top-k nodes with no bound; in a
  stdio host every character lands in the model's context.

The brainstorm decided (revision 3 and 4 open questions, all `[x]`): a stdio server for
Claude Code, Codex and Antigravity; per-repository storage under `.parrot/pageindex/`;
every tool enabled, with the model-dependent ones appearing once an `llm` is configured;
the internal agentic loop opt-in; a server with no `llm` is the supported default; the
Bookstore server stays separate.

### Goals

1. `PageIndexToolkit` is constructible from a YAML section: `adapter` becomes optional,
   `llm_client` (what the factory passes) is accepted and turned into the adapter, and
   `lightweight_model` keeps working on either path.
2. The class declares `llm_dependent_tools` so the factory hides exactly the tools that
   cannot run without a model: `pageindex_insert_content`, `pageindex_import_file`,
   `pageindex_import_folder`, `pageindex_import_pdf`, `pageindex_search_documents_scoped`.
3. Every other tool works with no adapter: `search` runs BM25 (plus the embedding signals
   when enabled) and `retrieve` follows it; `insert_markdown` builds the structure offline
   (`md_to_tree(adapter=None)`); `tag_node` keeps its existing no-adapter branch. A call
   that explicitly asks for the LLM walk with no model raises a clear `ValueError`.
4. A packaged `pageindex.yaml` template: no `llm`, storage at
   `{{repo_root}}/.parrot/pageindex`, every tool enabled, the agentic-loop exclusion slot
   documented, install metadata so `parrot self add` installs `ai-parrot[bookstore]`
   (bm25s, pymupdf) and `parrot toolkits list` reports the distributions it needs.
5. Results sized for a coding agent: a `max_result_chars` constructor option bounds
   `retrieve` (and only `retrieve`) with an explicit truncation marker; the template sets
   it, the class default leaves behaviour unchanged.
6. Proof over the real transport: `parrot mcp-local pageindex` completes the MCP
   handshake, lists the deterministic tools, creates a tree, ingests markdown and searches
   it through stdio with nothing but JSON-RPC on stdout; a second toolkit on the same
   storage directory observes the server's writes (FEAT-831 signature reload) and the
   server observes external writes.
7. Documentation: a `wiki/knowledge/pageindex-local-mcp.md` page and a `pageindex`
   section in `wiki/tools/mcp-local-toolkits.md`, linked from `wiki/knowledge/pageindex.md`.

### Non-Goals (explicitly out of scope)

- No new PageIndex tools. Page/segment readers are FEAT-840; outline-style tools, the
  agentic loop, layout structure and the optimizer are their own slices. This spec only
  guarantees that whatever `get_tools()` returns is served.
- No change to `mcp/toolkit_server.py`, `mcp/toolkit_seed.py`, `mcp/toolkit_install.py`,
  `mcp/hosts.py` or `mcp/local_cli.py`. The brainstorm's Impact table says "no change to
  the runner, the installer or the host adapters"; if a change there turns out to be
  needed, that is a spec defect to report, not a task to improvise.
- No Bookstore change. Its stdio server stays separate (brainstorm, resolved).
- No user-level or shared library; storage is per repository (brainstorm, resolved).
- No LLM in the shipped template, and no default model name anywhere in the toolkit: the
  operator adds `llm:` to the section.
- No bound on `get_tree` or `search` output (see §8, resolved): `search` is already bounded
  by `top_k` and returns summaries only; FEAT-840's bounded `outline` is the agent-facing
  tree view, so `get_tree` stays as it is.
- No OKF toolkit wiring for the MCP server beyond what `get_tools()` already does.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:456a536da7ede8ac486a6c4efcebc98c08aa0e2738b0359bcd7f7e3bb029dc15 evaluation_digest=sha256:e447bbc95d13978e8dcbe8d0e0641b9afd84af545302e8b849598b5b13f76180 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

The whole feature is a small adapter layer on `PageIndexToolkit` plus one YAML file. The
generic local-MCP pipeline is reused unchanged:

```
parrot toolkits install pageindex
   └─ toolkit_seed.seed_toolkit_sections(root, ["pageindex"])  → .parrot/mcp-toolkits.yaml  (section rendered from pageindex.yaml,
   └─ hosts.*Adapter.register("parrot-pageindex", command=parrot mcp-local pageindex ...)   {{repo_root}} replaced)

parrot mcp-local pageindex
   └─ toolkit_server.create_toolkit_mcp_server("pageindex")
        ├─ import parrot.knowledge.pageindex.toolkit.PageIndexToolkit     (inside redirect_stdout(stderr))
        ├─ llm:  absent  → drop_tools = PageIndexToolkit.llm_dependent_tools
        │        present → kwargs["llm_client"] = LLMFactory.create(llm, **llm_kwargs)
        ├─ PageIndexToolkit(**kwargs)                                    ← M1: no adapter required
        ├─ toolkit.get_tools()  − include/exclude − drop_tools            ← dynamic: FEAT-840 tools appear when merged
        └─ _ToolkitStdioMCPServer(LocalServerConfig("parrot-pageindex")).register_tools(...)
```

**Constructor (M1).** `adapter` becomes `Optional[PageIndexLLMAdapter] = None` and a new
keyword `llm_client: Optional[AbstractClient] = None` is accepted. Exactly one resolution
rule: `adapter` given → used as is; else `llm_client` given → `PageIndexLLMAdapter(client=
llm_client, model=model)`; else no adapter. Passing both raises `ValueError` (the two
would disagree about the client). `self._model` is `model or (adapter.model if adapter
else None)`; `lightweight_model` builds the light adapter from whichever adapter resulted.
`llm_dependent_tools` is a class attribute with the five prefixed names (the factory
matches on `tool.name`, which carries the `pageindex_` prefix from `tool_prefix`).

**Deterministic degradation (M2).** `search` computes `llm_walk = use_llm_walk and
self._adapter is not None`; when the caller asked for the walk and there is no adapter
and no other signal is enabled, it raises `ValueError("LLM walk requested but no LLM is
configured for this toolkit")` instead of letting the engine fail. `retrieve` passes
`use_llm_walk=self._adapter is not None`. `HybridPageIndexSearch` accepts
`adapter: Optional[...]` and `_llm_rank` raises the same `ValueError` when it is `None`
(defence in depth; the toolkit never reaches it). `insert_markdown` already forwards
`self._adapter` to `md_to_tree`, whose adapter is optional (`md_builder.py:256`); with
`None` the node summaries and the doc description are skipped and `ConceptType.SECTION`
is assigned, which is the documented offline behaviour. `tag_node` keeps its
`if self._adapter is not None` branch (`toolkit.py:427`). `_ingester()` is only reached
from the five LLM-dependent tools.

**Result sizing (M3).** `max_result_chars: Optional[int] = None` on the constructor. When
set, `retrieve` cuts the joined text at a part boundary when possible and appends
`\n\n[truncated: N more characters in K further sections — lower top_k or narrow the
query]`. Never cuts inside a `## title` header line. `None` keeps today's output
byte-identical. The template sets `max_result_chars: 24000`, the same order as the
bounded-source toolkit's `max_output_bytes` (24,576).

**Template (M4).** `mcp/_toolkit_templates/pageindex.yaml`:

```yaml
# parrot:summary: PageIndex document trees — per-repository search, read and edit over stdio.
# parrot:requires_llm: false
# parrot:requires_dist: bm25s,pymupdf
# parrot:requires_pip: ai-parrot[bookstore]
  pageindex:
    class: parrot.knowledge.pageindex.toolkit.PageIndexToolkit
    kwargs:
      storage_dir: {{repo_root}}/.parrot/pageindex
      max_result_chars: 24000
    # Add a model to enable the LLM-dependent tools (import_pdf, insert_content,
    # import_file, import_folder, search_documents_scoped) and the LLM tree walk.
    # llm: anthropic:claude-haiku-5-5
    # llm_kwargs: {}
    # The internal agentic retrieval tool (pageindex-agentic-retrieval) is opt-in:
    # remove it from this list to expose it.
    exclude: []
    env: {}
```

The `requires_dist` names are import-probed with `find_spec` (never imported) by
`parrot toolkits list`; `requires_pip` is what `parrot self add pageindex` installs. The
`exclude: []` slot is the agreed hand-off point: `pageindex-agentic-retrieval` adds its
tool name there (an empty list is falsy for the factory's `elif exclude:` branch, so it
changes nothing today). An `examples/pageindex-mcp.yaml` mirrors the section with an
`llm:` line active, following `examples/lsp-mcp.yaml`.

**Storage.** `JSONTreeStore.__init__` (`knowledge/pageindex/store.py:33`) creates
`storage_dir` with `mkdir(parents=True, exist_ok=True)`, so a fresh repository needs no
setup; `.parrot/*` is git-ignored (`.gitignore:392`). Trees, bodies and generations use
the FEAT-831 layout under that directory, and the per-tree `flock` makes the long-lived
server a safe second writer next to an in-process toolkit or a second server.

**Stdout purity.** The factory imports the class and constructs it inside
`contextlib.redirect_stdout(sys.stderr)`; the constructor's lazy `from parrot.conf import
EMBEDDING_DEFAULT_MODEL` (only when an embedding feature is on) therefore cannot leak the
navconfig banner. Tool calls run outside that block, so M2/M3 must not add imports that
print at import time; the stdio integration test asserts every stdout line is JSON.

### Component Diagram

```
.parrot/mcp-toolkits.yaml ──► toolkit_config.ToolkitSection ──► toolkit_server.create_toolkit_mcp_server
                                                                      │
                             mcp/_toolkit_templates/pageindex.yaml ───┘ (seeded by parrot toolkits install)
                                                                      ▼
                                             knowledge/pageindex/toolkit.PageIndexToolkit(llm_client=?, storage_dir, max_result_chars)
                                                   │ llm_dependent_tools (class)         │ get_tools()
                                                   ▼                                     ▼
                                      hidden without llm: insert_content,      served: list/create/delete/rename/get_tree,
                                      import_file, import_folder, import_pdf,  get_generation, vacuum_tree, search (BM25),
                                      search_documents_scoped                  retrieve (bounded), insert_markdown, insert_ebook,
                                                                               tag_node, add/update/delete_node, update_node_content
                                                                               + FEAT-840 read tools when merged
```

### Integration Points

| Component | How it is touched |
|---|---|
| `knowledge/pageindex/toolkit.py` | optional `adapter`, `llm_client`, `max_result_chars`, `llm_dependent_tools`, guards in `search`/`retrieve` |
| `knowledge/pageindex/hybrid_search.py` | `adapter` optional; `_llm_rank` raises `ValueError` on `None` |
| `mcp/_toolkit_templates/pageindex.yaml` | new packaged template (auto-discovered by `available_templates()`) |
| `examples/pageindex-mcp.yaml` | new example with `llm:` active |
| `mcp/toolkit_server.py`, `toolkit_seed.py`, `toolkit_install.py`, `hosts.py`, `local_cli.py` | unchanged — consumers only |
| `tests/mcp/test_toolkit_seed_install_metadata.py::test_every_shipped_template_still_loads` | picks the new template up automatically |
| `tests/docs/test_getting_started_claims.py` | the docs may now name `pageindex` after `toolkits install` |
| `wiki/tools/mcp-local-toolkits.md`, `wiki/knowledge/pageindex.md` | new section / link |

### Data Models

No new persisted data. Configuration surface added to `PageIndexToolkit`:

| kwarg | type | default | effect |
|---|---|---|---|
| `adapter` | `Optional[PageIndexLLMAdapter]` | `None` | unchanged semantics when given |
| `llm_client` | `Optional[AbstractClient]` | `None` | wrapped into an adapter with `model` |
| `max_result_chars` | `Optional[int]` | `None` | bound on `retrieve` output |

### New Public Interfaces

```python
class PageIndexToolkit(AbstractToolkit):
    llm_dependent_tools: frozenset[str] = frozenset({
        "pageindex_insert_content", "pageindex_import_file", "pageindex_import_folder",
        "pageindex_import_pdf", "pageindex_search_documents_scoped",
    })
    def __init__(self, adapter: Optional[PageIndexLLMAdapter] = None, storage_dir: str | Path = ..., *,
                 llm_client: Optional[AbstractClient] = None, max_result_chars: Optional[int] = None, ...): ...
    @property
    def has_llm(self) -> bool: ...        # True when an adapter is configured
```

`storage_dir` stays the second positional parameter so every existing call
`PageIndexToolkit(adapter, storage_dir)` and `PageIndexToolkit(adapter=..., storage_dir=...)`
keeps working; it keeps no default (`...` above means "required keyword or positional").

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: constructor + `llm_dependent_tools` | yes | resolution rule, `ValueError` text, five names, `has_llm` | — |
| M2: deterministic degradation | yes | guard expressions and error text fixed in §2 | — |
| M3: result sizing | no | — | cut-at-boundary heuristic and marker wording need judgement |
| M4: template + example | yes | file content given in §2 | — |
| M5: server integration tests | no | — | subprocess harness choices |
| M6: documentation | no | — | prose |

### Module 1: Constructor without an LLM

**Files**: `knowledge/pageindex/toolkit.py`
**Interface Skeleton**:

```python
from parrot.clients.base import AbstractClient            # verified: clients/base.py (AbstractClient), imported by llm_adapter.py:9

class PageIndexToolkit(AbstractToolkit):                   # verified: toolkit.py:63
    name = "pageindex"                                     # verified: toolkit.py:98
    tool_prefix = "pageindex"                              # verified: toolkit.py:99
    #: Tools the local MCP factory hides when the section has no ``llm`` (tool names carry the prefix).
    llm_dependent_tools: frozenset[str] = frozenset({...five names...})

    def __init__(
        self,
        adapter: Optional[PageIndexLLMAdapter] = None,     # was required: toolkit.py:103
        storage_dir: str | Path = None,                    # keep position; raise TypeError-equivalent ValueError when None
        reranker: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
        model: Optional[str] = None,
        ...,                                               # existing kwargs unchanged, toolkit.py:104-118
        llm_client: Optional[AbstractClient] = None,
        max_result_chars: Optional[int] = None,
        **kwargs: Any,
    ):
        """... Args: llm_client: an AbstractClient (what ``parrot mcp-local`` passes); wrapped into
        ``PageIndexLLMAdapter(client=llm_client, model=model)``. Mutually exclusive with ``adapter``.
        max_result_chars: upper bound on the text ``retrieve`` returns; ``None`` = unbounded."""

    @property
    def has_llm(self) -> bool:
        """True when an LLM adapter is configured (LLM walk and ingest tools available)."""
```

Resolution: `if adapter is not None and llm_client is not None: raise ValueError("pass either adapter or llm_client, not both")`.
`self._model = model or (self._adapter.model if self._adapter is not None else None)`
(replaces `toolkit.py:131`); the light adapter is built from `self._adapter.client` only
when `self._adapter is not None and lightweight_model` (replaces `toolkit.py:126`).

### Module 2: Deterministic degradation

**Files**: `knowledge/pageindex/toolkit.py`, `knowledge/pageindex/hybrid_search.py`
**Interface Skeleton**:

```python
# toolkit.search — after `engine = self._search_for(tree_name)` (verified: toolkit.py:679)
llm_walk = use_llm_walk and self._adapter is not None
if use_llm_walk and not llm_walk and not (use_bm25 or self._use_vec_rank or self._use_embedding_walk):
    raise ValueError("LLM walk requested but no LLM is configured for this toolkit")
# ... engine.search(..., use_llm_walk=llm_walk, ...)      # replaces toolkit.py:690

# toolkit.retrieve — replaces `use_llm_walk=True,` (verified: toolkit.py:739)
use_llm_walk=self._adapter is not None,

# hybrid_search.HybridPageIndexSearch.__init__ (verified: hybrid_search.py:73-76)
adapter: Optional[PageIndexLLMAdapter] = None,

async def _llm_rank(self, query: str) -> list[str]:        # verified: hybrid_search.py:284
    if self._adapter is None:
        raise ValueError("LLM walk requested but no LLM is configured for this toolkit")
```

`_search_for` (`toolkit.py:321`) already passes `adapter=self._adapter`; with `None` the
engine is built for BM25/vec only. No change to `retriever.py`: `PageIndexRetriever` is
only constructed by `_llm_rank` and `search_documents_scoped` (an LLM-dependent tool).

### Module 3: Result sizing

**Files**: `knowledge/pageindex/toolkit.py`
**Interface Skeleton**:

```python
def _bound_text(self, parts: list[str]) -> str:
    """Join ``parts`` and apply ``max_result_chars``.

    Keeps whole parts while they fit; when the first part alone exceeds the bound it is cut
    at the last paragraph break before the bound, never inside its ``## title`` line. Appends
    ``"\n\n[truncated: {n} more characters in {k} further sections — lower top_k or narrow the query]"``.
    With ``max_result_chars`` None, returns ``"\n\n".join(parts)`` unchanged.
    """
# retrieve: `return "\n\n".join(parts)` (verified: toolkit.py:757) becomes `return self._bound_text(parts)`
```

### Module 4: Packaged template and example

**Files**: `mcp/_toolkit_templates/pageindex.yaml` (create), `examples/pageindex-mcp.yaml` (create)

Content as in §2. Constraints: the body is indented two spaces like every sibling
template (it is spliced under `toolkits:`); header lines use the `# parrot:` prefix parsed
by `load_template` (`mcp/toolkit_seed.py:96-121`); no `enabled:` key (templates seed it
absent; `_DRIFT_IGNORED_KEYS`). The example file is a full standalone config
(`toolkits:` root) servable with `parrot mcp-local pageindex --config examples/pageindex-mcp.yaml`.

### Module 5: Server integration tests

**Files**: `tests/knowledge/pageindex/test_toolkit_no_llm.py` (create),
`tests/mcp/test_pageindex_template.py` (create)

- In-process: `create_toolkit_mcp_server("pageindex", root)` from a seeded section lists
  every deterministic tool and none of the five LLM-dependent names; with `llm:` set and
  `LLMFactory.create` monkeypatched to return a fake `AbstractClient`, the five appear and
  the toolkit's adapter wraps that client.
- Subprocess: `parrot mcp-local pageindex` spawned with the `_spawn/_send/_recv/_shutdown`
  pattern of `tests/mcp/test_toolkit_matrix.py:74,247-266`: `initialize` → serverInfo
  `parrot-pageindex`; `tools/list`; `tools/call pageindex_create_tree`,
  `pageindex_insert_markdown`, `pageindex_search` (BM25 hit on the inserted text),
  `pageindex_retrieve` (bounded by a small `max_result_chars` set in the test config and
  carrying the marker); every stdout line parses as JSON; exit code 0 after EOF.
- Two writers: after the server ingests, a `PageIndexToolkit(storage_dir=same)` in the
  test process lists the tree and reads the body; after the test process runs
  `insert_markdown` itself, a `pageindex_search` over stdio finds the new text (signature
  reload from FEAT-831).
- Template metadata: `load_template("pageindex")` → `requires_llm False`,
  `requires_dist == ("bm25s", "pymupdf")`, `requires_pip == ("ai-parrot[bookstore]",)`;
  `seed_toolkit_sections` renders `{{repo_root}}`; `parrot toolkits install pageindex --yes`
  registers `parrot-pageindex` with the Claude host (`repo_with_hosts` fixture).

The subprocess tests use the `_stub_tiktoken`-free path: the server process cannot be
monkeypatched, so the test markdown must be long enough that `thin_tree` keeps the nodes,
and the tests skip when `bm25s` is not importable (same guard as the Bookstore tests).

### Module 6: Documentation

**Files**: `wiki/knowledge/pageindex-local-mcp.md` (create), `wiki/tools/mcp-local-toolkits.md`
(update: `## \`pageindex\`` section before `## \`sdd-coder\``, `mcp-local-toolkits.md:269`),
`wiki/knowledge/pageindex.md` (update: link), `tests/knowledge/pageindex/test_local_mcp_docs.py` (create,
pattern `tests/knowledge/pageindex/test_generation_docs.py`).

---

## 4. Test Specification

### Unit Tests

| Test file | Covers |
|---|---|
| `tests/knowledge/pageindex/test_toolkit_no_llm.py` | constructor resolution (adapter / llm_client / neither / both→ValueError), `has_llm`, `llm_dependent_tools` names ⊆ `list_tool_names()`, `search` without adapter uses BM25 only, explicit LLM-walk-only request raises, `retrieve` without adapter, `_bound_text` boundaries and marker, `insert_markdown` offline assigns SECTION types, `lightweight_model` with `llm_client` |
| `tests/knowledge/pageindex/test_hybrid_search.py` (existing, extend) | `HybridPageIndexSearch(adapter=None)` BM25 search works; `_llm_rank` raises `ValueError` |
| `tests/mcp/test_pageindex_template.py` | template metadata, seeding, factory tool lists with/without `llm`, install registers the host entry |
| `tests/knowledge/pageindex/test_local_mcp_docs.py` | wiki pages exist, name the kwargs and the five hidden tools, are linked |

### Integration Tests

| Scenario | Test |
|---|---|
| stdio handshake, tools/list, create/insert/search/retrieve, stdout purity, exit 0 | `tests/mcp/test_pageindex_template.py::test_pageindex_serves_over_stdio` |
| two writers on one storage dir (server + in-process toolkit) | `tests/mcp/test_pageindex_template.py::test_pageindex_server_shares_storage_with_second_toolkit` |
| existing toolkit tests unchanged with an adapter | `tests/knowledge/pageindex/test_toolkit.py`, `test_generation_integration.py` |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py
- packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py
- packages/ai-parrot/tests/mcp/test_pageindex_template.py
- packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py
- packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py
- packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py
- packages/ai-parrot/tests/mcp/test_toolkit_seed_install_metadata.py
- packages/ai-parrot/tests/mcp/test_toolkit_matrix.py
- packages/ai-parrot/tests/mcp/test_lsp_template.py
- packages/ai-parrot/tests/docs/test_getting_started_claims.py
markers: none

### Test Data / Fixtures

- Markdown documents ≥ 3 sections × ≥ 60 words each (clears `thin_tree` without the
  tiktoken stub in the subprocess).
- Fake `AbstractClient` subclass from `tests/knowledge/pageindex/test_toolkit.py:_adapter`
  reused for the `llm_client` path.
- `repo_with_hosts` fixture from `tests/mcp/test_toolkit_matrix.py` for the install test.
- `pytest.importorskip("bm25s")` on every test that searches.

---

## 5. Acceptance Criteria

- [ ] AC-1 `PageIndexToolkit(storage_dir=d)` constructs with no adapter; `has_llm is False`; `PageIndexToolkit(adapter=a, storage_dir=d)` and `PageIndexToolkit(a, d)` behave exactly as before.
- [ ] AC-2 `PageIndexToolkit(storage_dir=d, llm_client=c, model="m")` has an adapter whose `client is c` and `model == "m"`; passing both `adapter` and `llm_client` raises `ValueError`.
- [ ] AC-3 `PageIndexToolkit.llm_dependent_tools == {"pageindex_insert_content", "pageindex_import_file", "pageindex_import_folder", "pageindex_import_pdf", "pageindex_search_documents_scoped"}` and every name is in `list_tool_names()`.
- [ ] AC-4 Without an adapter: `search(..., use_llm_walk=True)` returns BM25 results with `source == "bm25"`; `search(..., use_bm25=False, use_llm_walk=True)` raises `ValueError`; `retrieve` returns text; `insert_markdown` succeeds and assigns `SECTION` types.
- [ ] AC-5 `HybridPageIndexSearch(tree, adapter=None, ...)` searches with BM25; `_llm_rank` raises `ValueError`.
- [ ] AC-6 With `max_result_chars=N`, `retrieve` output length ≤ N + len(marker), ends with the marker when cut, never cuts a `## ` header line; with `None` the output is byte-identical to today.
- [ ] AC-7 `load_template("pageindex")` has `requires_llm False`, `requires_dist ("bm25s","pymupdf")`, `requires_pip ("ai-parrot[bookstore]",)`; `seed_toolkit_sections` writes a `pageindex:` section whose `storage_dir` is `<root>/.parrot/pageindex` and `max_result_chars` is 24000; `test_every_shipped_template_still_loads` passes.
- [ ] AC-8 `create_toolkit_mcp_server("pageindex", root)` without `llm:` serves no LLM-dependent tool and serves `pageindex_search`, `pageindex_retrieve`, `pageindex_insert_markdown`, `pageindex_create_tree`; with `llm:` (factory monkeypatched) all five appear.
- [ ] AC-9 `parrot mcp-local pageindex` over stdio: handshake (`serverInfo.name == "parrot-pageindex"`), `tools/list`, create tree, insert markdown, BM25 search hit, bounded retrieve; every stdout line is JSON; exit code 0.
- [ ] AC-10 A second `PageIndexToolkit` on the same `storage_dir` lists the tree the server created and the server finds text the second toolkit inserted.
- [ ] AC-11 `parrot toolkits install pageindex --yes` seeds the section and registers `parrot-pageindex` in the Claude host config.
- [ ] AC-12 `mcp/toolkit_server.py`, `toolkit_seed.py`, `toolkit_install.py`, `hosts.py`, `local_cli.py` have no diff.
- [ ] AC-13 Wiki pages per §10 exist and are linked; `parrot sdd techwiki check --spec sdd/specs/pageindex-local-mcp-toolkit.spec.md --root .` passes.

---

## 6. Codebase Contract

> Verified at `dev` @ `9c4c9390a0`. Paths relative to `packages/ai-parrot/src/parrot/` unless they start with `packages/`, `tests/`, `examples/` or `wiki/`.

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit                               # tools/toolkit.py; llm_dependent_tools default at :313
from parrot.clients.base import AbstractClient                                 # used by knowledge/pageindex/llm_adapter.py:9
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                # knowledge/pageindex/toolkit.py:63
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter         # knowledge/pageindex/llm_adapter.py:43 (class), __init__ at :49
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch     # knowledge/pageindex/hybrid_search.py:73 (__init__)
from parrot.knowledge.pageindex.retriever import PageIndexRetriever            # knowledge/pageindex/retriever.py:19 (__init__, adapter required)
from parrot.knowledge.pageindex.md_builder import md_to_tree                   # knowledge/pageindex/md_builder.py:254 (adapter: PageIndexLLMAdapter | None = None)
from parrot.knowledge.pageindex.store import JSONTreeStore                     # knowledge/pageindex/store.py:31 (mkdir parents at :33)
from parrot.mcp.toolkit_server import create_toolkit_mcp_server                # mcp/toolkit_server.py:258
from parrot.mcp.toolkit_config import ToolkitSection, load_toolkits_config     # mcp/toolkit_config.py:20, :90
from parrot.mcp.toolkit_seed import available_templates, load_template, seed_toolkit_sections, ToolkitTemplate  # mcp/toolkit_seed.py:53, :67, :335, :28
from parrot.mcp.toolkit_install import install_toolkits, dist_available        # mcp/toolkit_install.py:163, :63
from parrot.mcp.local_cli import mcp_local                                     # mcp/local_cli.py:214 (click command "mcp-local", :178)
```

### Existing Class Signatures

```python
# knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                                       # :63
    name = "pageindex"                                                         # :98
    tool_prefix = "pageindex"                                                  # :99
    def __init__(self, adapter: PageIndexLLMAdapter, storage_dir: str | Path, reranker=None,
                 lightweight_model=None, model=None, default_bm25_k=20, folder_concurrency=4,
                 content_cache_size=256, embedding_model=None, embedding_dimension=256,
                 embedding_backend=None, use_vec_rank=False, use_embedding_walk=False,
                 generation_grace_s=3600, lock_timeout_s=30.0, **kwargs)        # :101-119
        self._adapter = adapter                                                # :121
        self._light_adapter = PageIndexLLMAdapter(client=adapter.client, model=lightweight_model) if lightweight_model else None  # :125-127
        self._model = model or adapter.model                                   # :131
        self._use_embedding_walk = use_embedding_walk                          # :135
    def _ingester(self) -> TwoStepIngester                                     # :296 (adapter + light adapter)
    def _search_for(self, tree_name) -> HybridPageIndexSearch                  # :321 (passes adapter=self._adapter at :329)
    # tag_node helper: `if self._adapter is not None:` branch                  # :427
    def get_tools(self, permission_context=None, resolver=None) -> list        # :451 (base tools + OKF tools)
    async def search(self, tree_name, query, top_k=10, use_bm25=True, use_llm_walk=True, rerank=False,
                     categories=None, metadata_filter=None) -> list[dict]      # :655-697; engine = self._search_for(tree_name) at :679; use_llm_walk=use_llm_walk at :690
    async def retrieve(self, tree_name, query, top_k=5) -> str                 # :722-757; use_llm_walk=True at :739; return "\n\n".join(parts) at :757
    async def search_documents_scoped(...)                                     # :759; builds PageIndexRetriever(adapter=self._adapter) at :829-833
    async def insert_markdown(...)                                             # :922; md_to_tree(..., adapter=self._adapter, ...) at :945
    async def insert_ebook(...)                                                # :963 (no adapter use)
    async def insert_content(...)                                              # :997 (self._ingester().ingest — LLM)
    async def import_file(...)                                                 # :1021 (→ insert_content — LLM)
    async def import_pdf(...)                                                  # :1040 (build_page_index with adapter — LLM)
    async def import_folder(...)                                               # :1107 (→ insert_content — LLM)
_MAX_TREES_HARD_CAP = 10                                                       # :54

# Tool names produced by tool_prefix (verified via list_tool_names in tests/knowledge/pageindex/test_toolkit.py:77-79):
# pageindex_list_trees, pageindex_create_tree, pageindex_delete_tree, pageindex_rename_tree, pageindex_get_tree,
# pageindex_get_generation, pageindex_vacuum_tree, pageindex_search, pageindex_retrieve,
# pageindex_search_documents_scoped, pageindex_tag_node, pageindex_insert_markdown, pageindex_insert_ebook,
# pageindex_insert_content, pageindex_import_file, pageindex_import_pdf, pageindex_import_folder,
# pageindex_delete_node, pageindex_add_node, pageindex_update_node_content, pageindex_update_node

# knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:
    def __init__(self, tree, adapter: PageIndexLLMAdapter, reranker=None, model=None, ...)   # :73-76; self._adapter = adapter at :90
    async def _llm_rank(self, query: str) -> list[str]                        # :284 (PageIndexRetriever(adapter=self._adapter, model=self._model or self._adapter.model))
    async def search(self, query, top_k, use_bm25=True, use_llm_walk=True, rerank=False, use_vec=False, ...)  # :307; raises when no signal at :348

# knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:
    def __init__(self, client: AbstractClient, model: Optional[str] = "gemini-3.1-flash-lite-preview", ...)  # :49-52; self.client/.model at :56-57

# knowledge/pageindex/md_builder.py
async def md_to_tree(md_text, adapter: PageIndexLLMAdapter | None = None, options=None, doc_name="document.md") -> dict  # :254-259

# mcp/toolkit_server.py
def create_toolkit_mcp_server(name: str, root: Optional[Path] = None, *, login_file=None, **overrides) -> StdioMCPServer  # :258
#   drop_tools = set(toolkit_cls.llm_dependent_tools)  (class attribute, no llm)                  # :335
#   kwargs["llm_client"] = llm_client; toolkit = toolkit_cls(**kwargs)                             # :340-342
#   include / `elif exclude:` / drop_tools filtering on t.name                                     # :348-376
#   LocalServerConfig(name=f"parrot-{name}", version="1.0.0")                                      # :381

# mcp/toolkit_config.py
class ToolkitSection(BaseModel): class_path (alias "class"), enabled, kwargs, include, exclude, llm, llm_kwargs, env   # :20-59

# mcp/toolkit_seed.py
REPO_ROOT_PLACEHOLDER = "{{repo_root}}"                                        # :21
class ToolkitTemplate(BaseModel): name, body, requires_llm, summary, requires_dist, requires_pip, post_install, requires_env  # :28-38
def available_templates() -> tuple[str, ...]                                   # :53 (sorted .yaml stems)
def load_template(name: str) -> ToolkitTemplate                                # :67 (header parser :96-121)
def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult      # :335

# mcp/toolkit_install.py
def dist_available(requires_dist: Sequence[str]) -> bool                      # :63 (find_spec, never imports)
def install_toolkits(...)                                                      # :163

# knowledge/pageindex/store.py
class JSONTreeStore: def __init__(self, storage_dir)                           # :31; self._dir.mkdir(parents=True, exist_ok=True) at :33
```

### Integration Points

- `tests/mcp/test_toolkit_matrix.py:74` `_spawn(cwd, *args)`, `:247-266` handshake pattern (`_send`, `_recv`, `_shutdown`, `repo_with_hosts` fixture).
- `tests/mcp/test_toolkit_seed_install_metadata.py:118` `test_every_shipped_template_still_loads`; `:108-114` per-template metadata test pattern.
- `tests/mcp/test_lsp_template.py:28-61` template + seed test pattern.
- `tests/knowledge/pageindex/test_toolkit.py:52-70` tiktoken stub and `toolkit` fixture; `_adapter()` fake client helper above `:50`.
- `tests/knowledge/pageindex/test_generation_docs.py` docs-test pattern (`parents[5]`).
- `tests/docs/test_getting_started_claims.py:433-453` every component named after `toolkits install` in the docs must be a packaged template.
- `wiki/tools/mcp-local-toolkits.md:269` `## \`sdd-coder\`` heading (insert the `pageindex` section before it); `wiki/knowledge/pageindex.md:14` Table of Contents.
- `.gitignore:392` `.parrot/*`.
- `packages/ai-parrot/pyproject.toml:368-372` `bookstore` extra (`bm25s`, `pymupdf`, `pymupdf4llm`).

### Does NOT Exist (Anti-Hallucination)

- No `pageindex.yaml` in `mcp/_toolkit_templates/` and no `examples/pageindex-mcp.yaml`.
- `PageIndexToolkit` has no `llm_client` parameter, no `has_llm`, no `max_result_chars`, no `_bound_text`, and no `llm_dependent_tools` of its own (inherits the empty default).
- `HybridPageIndexSearch.__init__` does not accept `adapter=None` today (it dereferences `self._adapter.model` in `_llm_rank`).
- `create_toolkit_mcp_server` has no hook for per-toolkit "opt-in" tools beyond `include`/`exclude`; there is no `opt_in_tools` attribute on `AbstractToolkit`.
- There is no `parrot pageindex` CLI and no `knowledge/pageindex/mcp_server.py`; the Bookstore server (`knowledge/bookstore/mcp_server.py`) is not a template and is not reused.
- `ToolkitSection` has no `storage_dir` or `repo_root` field; paths live under `kwargs`.
- `tests/knowledge/pageindex/test_toolkit_no_llm.py`, `tests/mcp/test_pageindex_template.py`, `tests/knowledge/pageindex/test_local_mcp_docs.py`, `wiki/knowledge/pageindex-local-mcp.md` do not exist.
- No agentic retrieval tool exists yet (it is `pageindex-agentic-retrieval`); the template's `exclude: []` is an empty slot, not a reference to a tool.

### Edit Sites (Blueprint Anchors)

Base commit: `dev` @ `9c4c9390a0`. Counts from `grep -cF '<anchor>' <path>`.

| File | Anchor (verbatim) | path:NN | count | Change |
|---|---|---|---|---|
| `knowledge/pageindex/toolkit.py` | `    tool_prefix = "pageindex"` | :99 | 1 | after: `llm_dependent_tools` class attribute |
| `knowledge/pageindex/toolkit.py` | `        adapter: PageIndexLLMAdapter,` | :103 | 1 | replace: `adapter: Optional[PageIndexLLMAdapter] = None,` + `storage_dir` default |
| `knowledge/pageindex/toolkit.py` | `        lock_timeout_s: float = 30.0,` | :118 | 1 | after: `llm_client`, `max_result_chars` keyword parameters |
| `knowledge/pageindex/toolkit.py` | `        self._adapter = adapter` | :121 | 1 | replace: resolution rule (adapter / llm_client / both → ValueError) |
| `knowledge/pageindex/toolkit.py` | `            PageIndexLLMAdapter(client=adapter.client, model=lightweight_model) if lightweight_model else None` | :126 | 1 | replace: guard on `self._adapter is not None` |
| `knowledge/pageindex/toolkit.py` | `        self._model = model or adapter.model` | :131 | 1 | replace: nullable model |
| `knowledge/pageindex/toolkit.py` | `        self._use_embedding_walk = use_embedding_walk` | :135 | 1 | after: `self._max_result_chars = max_result_chars` |
| `knowledge/pageindex/toolkit.py` | `        engine = self._search_for(tree_name)` | :679 | 1 | after: `llm_walk` guard |
| `knowledge/pageindex/toolkit.py` | `            use_llm_walk=use_llm_walk,` | :690 | 1 | replace: `use_llm_walk=llm_walk,` |
| `knowledge/pageindex/toolkit.py` | `            use_llm_walk=True,` | :739 | 1 | replace: `use_llm_walk=self._adapter is not None,` |
| `knowledge/pageindex/toolkit.py` | `        return "\n\n".join(parts)` | :757 | 1 | replace: `return self._bound_text(parts)`; add `_bound_text` + `has_llm` near `_ingester` (:296) |
| `knowledge/pageindex/hybrid_search.py` | `        adapter: PageIndexLLMAdapter,` | :76 | 1 | replace: `adapter: Optional[PageIndexLLMAdapter] = None,` |
| `knowledge/pageindex/hybrid_search.py` | `    async def _llm_rank(self, query: str) -> list[str]:` | :284 | 1 | after: `None` guard raising `ValueError` |
| `mcp/_toolkit_templates/pageindex.yaml` | — | create | — | §2 content |
| `examples/pageindex-mcp.yaml` | — | create | — | standalone config with `llm:` active |
| `wiki/tools/mcp-local-toolkits.md` | `## \`sdd-coder\` — orchestration kernel for the interactive sdd-worker (FEAT-549)` | :269 | 1 | before: `## \`pageindex\`` section |
| `wiki/knowledge/pageindex.md` | `## Table of Contents` | :14 | 1 | after: link to the new page |
| `wiki/knowledge/pageindex-local-mcp.md` | — | create | — | §10 |

`hybrid_search.py:76` and `toolkit.py:103` share the anchor text `        adapter: PageIndexLLMAdapter,` but live in different files; each count is per file.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Tool-name matching in the factory uses `t.name` (prefixed); `llm_dependent_tools` must
  list `pageindex_*` names, unlike `WebScrapingToolkit` (`plan_create`, no prefix).
- Keep `storage_dir` positional-second: `PageIndexToolkit(adapter, tmp_path)` is used by
  the FEAT-831 tests and by Bookstore.
- The template body is indented under `toolkits:`; copy the indentation of
  `bounded-source.yaml`. Header `# parrot:requires_pip:` is one requirement per line.
- Everything that may print at import time must be imported either at module top (already
  under the factory's redirect) or inside the request path with no stdout side effect;
  prefer module-level imports for anything M2/M3 adds (none expected).
- `pytest.importorskip("bm25s")` guards; the test markdown must be long enough for
  `thin_tree` in the subprocess (no tiktoken stub there).
- Docs tests follow `test_generation_docs.py` (`parents[5]` = repo root).

### Known Risks / Gotchas

- **`md_to_tree` without adapter** assigns `ConceptType.SECTION` and skips summaries, so
  BM25 over a no-LLM tree indexes titles and bodies only. Expected and documented; the
  wiki page says what `llm:` adds.
- **`import_pdf` hidden without a model** until `pageindex-layout-structure` lands; the
  template comment says so. When that slice makes PDF import deterministic it must remove
  `pageindex_import_pdf` from `llm_dependent_tools` (recorded in §8 as a hand-off).
- **`search_documents_scoped` is LLM-only** today (it builds `PageIndexRetriever`
  directly, not the hybrid engine). Making it BM25-capable is a behaviour change outside
  this slice; it stays hidden without `llm:`.
- **Two servers on one directory** (e.g. Claude Code and Codex both running) are covered
  by the FEAT-831 `flock` + signature reload; the tests here exercise one server plus an
  in-process toolkit, which is the same code path.
- **Navconfig banner**: `import parrot.conf` prints `USE SSL::` to stdout. The factory
  redirects during import/construct; a tool call that triggers a first-time `parrot.conf`
  import would corrupt the stream. `use_vec_rank`/`use_embedding_walk` import it in the
  constructor (safe); nothing in M2/M3 may import it later.
- **`exclude: []` drift**: `template_drift` compares keys, so a configured section without
  `exclude` is reported as drift from the template. Acceptable — it points the operator at
  the opt-in slot; the wiki page explains the message.
- **`thin_tree`/`count_tokens`**: the in-process unit tests must install the
  `_stub_tiktoken` fixture like `test_toolkit.py:52`.

### External Dependencies

None added. Runtime extras the template declares: `ai-parrot[bookstore]` (`bm25s`,
`pymupdf`, `pymupdf4llm`), already pinned in `packages/ai-parrot/pyproject.toml:368-372`.

---

## Decisions

```yaml
schema_version: 1
document_id: pageindex-local-mcp-toolkit
entries:
  - id: pageindex-toolkit-servable-without-llm
    statement: PageIndexToolkit must be constructible with no LLM adapter (accepting the factory's llm_client when one is configured), must declare the prefixed names of every tool that needs a model in llm_dependent_tools, and every other tool must work deterministically without one.
    relation: requires
    about: [knowledge-pageindex]
    targets: ["file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py"]
    contradicts: []
    supersedes: []
    rationale: The local MCP factory instantiates toolkits from YAML and hides LLM-dependent tools by class metadata; a no-llm server is the agreed default mode for coding-agent hosts.
    rejected_alternatives: ["A separate hand-built stdio server like Bookstore's", "Requiring llm in the template"]
  - id: pageindex-served-by-packaged-template-only
    statement: PageIndex is exposed to Claude Code, Codex and Antigravity only through a packaged pageindex template consumed by the existing parrot toolkits / parrot mcp-local machinery, with per-repository storage under .parrot/pageindex, no llm in the template, every tool enabled and the agentic loop opt-in via the exclude slot; the runner, seeder, installer and host adapters are not modified.
    relation: constrains
    about: [knowledge-pageindex, tools]
    targets: ["file:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py", "file:packages/ai-parrot/src/parrot/mcp/toolkit_server.py"]
    contradicts: []
    supersedes: []
    rationale: One registration path for every host; the server lists whatever get_tools returns, so later slices need no MCP work.
    rejected_alternatives: ["User-level shared library (Bookstore scopes)", "Read-only default with write tools opt-in", "A dedicated parrot pageindex CLI"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:456a536da7ede8ac486a6c4efcebc98c08aa0e2738b0359bcd7f7e3bb029dc15 evaluation_digest=sha256:e447bbc95d13978e8dcbe8d0e0641b9afd84af545302e8b849598b5b13f76180 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: claude-code, codex, local-toolkits, tree-optimizer
- Targets resolved: 3/3
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 3,
    "targets_total": 3,
    "unmapped_tags": [
      "claude-code",
      "codex",
      "local-toolkits",
      "tree-optimizer"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:e447bbc95d13978e8dcbe8d0e0641b9afd84af545302e8b849598b5b13f76180",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:456a536da7ede8ac486a6c4efcebc98c08aa0e2738b0359bcd7f7e3bb029dc15",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:2638e5ca6e355ef48c77db26b7b1ab41a0a22b52ceb4745b5ff1af4a20cb9a11",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] A local MCP server for PageIndex — *Resolved in brainstorm*: yes, as its own related spec, stdio, for Claude Code, Codex and `agy`.
- [x] MCP storage location — *Resolved in brainstorm*: per repository, under `.parrot/pageindex/`.
- [x] MCP default tool surface — *Resolved in brainstorm*: every tool enabled; the ones that need a model appear once an `llm` is configured.
- [x] Is the internal agentic loop exposed over MCP — *Resolved in brainstorm*: not by default; it is opt-in.
- [x] Does the Bookstore stdio server stay separate — *Resolved in brainstorm*: it stays separate.
- [x] Is a server with no `llm` a supported default — *Resolved in brainstorm*: yes, it is the default mode.
- [x] How the opt-in is expressed with no runner change — *Resolved in this spec*: the template's `exclude: []` slot; `pageindex-agentic-retrieval` adds its tool name there when it lands.
- [x] Which tools are LLM-dependent — *Resolved in this spec*: `insert_content`, `import_file`, `import_folder`, `import_pdf`, `search_documents_scoped`; `insert_markdown`, `insert_ebook`, `tag_node`, `search`, `retrieve` run without a model.
- [x] Should `get_tree` and `search` output also be bounded for stdio hosts? — *Resolved (Jesus Lara, 2026-11-07)*: no. `search` returns at most `top_k` candidates with summaries only, so it needs no bound. `get_tree` stays unbounded and served; once FEAT-840 lands its bounded `outline` (`max_chars=6000`) is the tool a coding agent uses to browse a tree, and `wiki/knowledge/pageindex-local-mcp.md` says so. `get_tree` is not added to `exclude:`.
- [x] FEAT-840 read budgets for coding-agent hosts (`read_max_chars=12000`, `outline` `max_chars=6000`) — *Resolved (Jesus Lara, 2026-11-07)*: keep FEAT-840's defaults. Both sit under this template's `max_result_chars: 24000`; they are per-call parameters, so the template gets no knob for them.
- [x] Hand-off (recorded, not a decision of this spec): when `pageindex-layout-structure` makes PDF import deterministic, it removes `pageindex_import_pdf` from `llm_dependent_tools` — *Owner: that spec*.
- [x] Hand-off (recorded, not a decision of this spec): `pageindex-agentic-retrieval` adds its tool name to the template's `exclude:` list and to `llm_dependent_tools` — *Owner: that spec*.

---

## 9. Design Research Cross-Check

Status: skipped (exploration doc `sdd/proposals/pageindex-tree-optimizer.brainstorm.md` is `**Status**: exploration`, not `accepted`; `codex` is installed)

| # | Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/knowledge/pageindex-local-mcp.md` — create: install (`parrot toolkits install pageindex`), what is served with and without `llm:`, the five hidden tools, `storage_dir`/`max_result_chars`/`llm_client`, the `exclude:` opt-in slot, `outline` (FEAT-840) over `get_tree` for browsing large trees, two-writer behaviour, troubleshooting (`bm25s` missing, drift message).
  - `wiki/tools/mcp-local-toolkits.md` — update: `## \`pageindex\`` section before the `sdd-coder` section with the quickstart and a link to the page above.
  - `wiki/knowledge/pageindex.md` — update: link to `pageindex-local-mcp.md` from the Table of Contents.
- **API modules**:
  - `parrot.knowledge.pageindex.toolkit` (`__init__` docstring for `llm_client`, `max_result_chars`; `has_llm`; `llm_dependent_tools` comment)

---

## Revision History

| Rev | Date | Summary |
|---|---|---|
| 0.1 | 2026-11-07 | Initial spec from brainstorm revision 4 (slice 6). Anchors verified at `dev` @ `9c4c9390a0`. |
| 0.2 | 2026-11-07 | Open questions resolved: no bound on `get_tree`/`search` (`outline` is the bounded tree view); FEAT-840 read budgets kept; hand-offs recorded. |
