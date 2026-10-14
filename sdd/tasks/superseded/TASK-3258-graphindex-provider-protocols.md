# TASK-3258: GraphIndex provider Protocols (`Embedder`, `LLMCaller`, `PageIndexer`, `ProviderNotAvailable`)

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 seam 2 ("Protocols") and §3 **Module 2, first half**. Graph code
reaches into the framework to type three providers: `GraphIndexEmbedder`
(faiss + `EmbeddingRegistry`), `PageIndexLLMAdapter` (an `AbstractClient`
wrapper) and `PageIndexToolkit` (an `AbstractToolkit`). This task declares the
structural `typing.Protocol`s those classes already satisfy, plus the
`ProviderNotAvailable` error, in a new framework-free module. TASK-3259 then
retypes `GraphIndexBuilder`, `IngestTriageRouter` and friends against them.

This task only **creates** the protocols module and its tests — it modifies no
existing file. Implements spec §4 `test_protocols_structural_match` and
`test_provider_not_available_message`; resolves spec Open Question 2
("keep `PageIndexer` minimal — derive from call sites").

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py` with
  `@runtime_checkable` Protocols `Embedder`, `LLMCaller`, `PageIndexer` and the
  exception `ProviderNotAvailable(RuntimeError)`.
- Surfaces are derived from **real call sites** (design D3):
  - `Embedder`: `embed_nodes`, `get_embedding`, `search_similar` — builder calls
    `embed_nodes` (builder.py:192,383) and hands the embedder to
    `resolve_cross_domain` / signals which call `get_embedding` (resolve.py:172,
    signals.py:404); retriever.py:321 calls `search_similar(query, top_k=top_k)`.
  - `LLMCaller`: `ask`, `ask_structured`, `ask_json`.
  - `PageIndexer`: `list_trees`, `create_tree`, `delete_tree`, `get_tree`,
    `insert_markdown`, `insert_ebook` (extractors/loader.py:216-337). **Not** the
    private `_content_store` — builder.py:289 keeps its `getattr(..., None)`.
- The module imports only `__future__`, `typing` (and `pathlib`/`collections.abc` if needed for annotations). No numpy, no pydantic, no parrot import.
- Write `packages/ai-parrot/tests/knowledge/graphindex/test_protocols.py`.

**NOT in scope**:
- Retyping `builder.py`, `triage.py`, `retriever.py`, `signals.py`, `factory.py` — TASK-3259.
- Relocating `GraphIndexEmbedder` — TASK-3259.
- Any provider registry / entry-point group — FEAT-541 (spec §7 "Injection order").
- Mapping `ProviderNotAvailable` to CLI exit code 2 — wire it where the CLI first raises it (TASK-3259 / later); this task only defines the class.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py` | CREATE | Protocols + `ProviderNotAvailable` |
| `packages/ai-parrot/tests/knowledge/graphindex/test_protocols.py` | CREATE | Structural-match + message tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# Production module: stdlib only
from typing import Any, Protocol, runtime_checkable

# Tests only (framework classes the Protocols must match WITHOUT being modified):
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder            # embed.py:25 (until TASK-3259 relocates it; shim keeps this path)
from parrot.knowledge.graphindex.factory import HashingGraphEmbedder        # factory.py:116
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter      # llm_adapter.py:42
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit             # toolkit.py:50
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py
class GraphIndexEmbedder:                                                    # line 25
    def __init__(self, model_name: str = "default", dimension: int = 384, pgvector_dsn: Optional[str] = None) -> None:  # line 40
    async def embed_nodes(self, nodes: list[UniversalNode], batch_size: int = 64) -> list[UniversalNode]:  # line 58
    async def search_similar(self, query_text: str, top_k: int = 10) -> list[tuple[str, float]]:          # line 122
    def get_embedding(self, node_id: str) -> Optional[np.ndarray]:                                        # line 160

# packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
class HashingGraphEmbedder:                                                  # line 116
    def __init__(self, dimension: int = DEFAULT_DIMENSION) -> None:          # line 130
    async def embed_nodes(self, nodes: list[UniversalNode], batch_size: int = 64) -> list[UniversalNode]:  # line 142
    def get_embedding(self, node_id: str) -> Optional[np.ndarray]:          # line 172
    async def search_similar(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:  # line 176
#   NOTE: first param of search_similar is `query_text` in one class and `query` in the other.
#   All callers pass it positionally (retriever.py:321-323; vector_seed.py:231) → the Protocol
#   declares it positional-only.

# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:                                                   # line 42
    def __init__(self, client: AbstractClient, model: Optional[str] = "gemini-3.1-flash-lite-preview", max_retries: int = 3, retry_delay: float = 1.0):  # line 49
    async def ask(self, prompt: str, structured_output=None, temperature: float = 0.0, system_prompt: Optional[str] = None) -> str:  # line 61
    async def ask_structured(self, prompt: str, output_type: type, temperature: float = 0.0, system_prompt: Optional[str] = None) -> Any:  # line 99
    async def ask_json(self, prompt: str, temperature: float = 0.0, system_prompt: Optional[str] = None) -> Any:  # line 201

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                                     # line 50
    def __init__(self, adapter: PageIndexLLMAdapter, storage_dir: str | Path, reranker=None, ...):  # line 88
    async def list_trees(self) -> list[str]:                                 # line 373
    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]:  # line 377
    async def delete_tree(self, tree_name: str) -> dict[str, Any]:           # line 398
    async def get_tree(self, tree_name: str) -> dict[str, Any]:              # line 410
    async def insert_markdown(self, tree_name: str, markdown: str, parent_node_id: Optional[str] = None, doc_name: Optional[str] = None) -> dict[str, Any]:  # line 692
    async def insert_ebook(self, tree_name: str, sections: list[dict[str, Any]], parent_node_id: Optional[str] = None) -> dict[str, Any]:  # line 730
```

### Does NOT Exist
- ~~`parrot.knowledge.graphindex.protocols`~~ — created by this task.
- ~~`Embedder`, `LLMCaller`, `PageIndexer`, `ProviderNotAvailable`~~ — do not exist anywhere yet.
- ~~`PageIndexLLMAdapter.ask_with_finish_info` in `LLMCaller`~~ — exists on the adapter (line 151) but graph code does not call it; keep it OUT of the Protocol.
- ~~`HashingGraphEmbedder` in `embed.py`~~ — it is in `factory.py:116`.
- ~~A `parrot.knowledge.graphindex.registry` / provider registry~~ — FEAT-541.

---

## Implementation Notes

### Key Constraints
- **Protocols, not ABCs** (spec §7): the framework classes must satisfy them *without* being modified to inherit.
- `@runtime_checkable` `isinstance` checks only attribute presence — that is fine; tests assert presence, TASK-3259's builder never `isinstance`-checks.
- Constructing `GraphIndexEmbedder` in tests calls `EmbeddingRegistry.instance().get_or_create_sync(...)`; follow `packages/ai-parrot/tests/knowledge/graphindex/test_embed.py:31-47` (`patch.object` on `__init__`) or use `object.__new__(GraphIndexEmbedder)` — no model download.
- `PageIndexLLMAdapter(client=MagicMock())` constructs without I/O (lines 49-59). `PageIndexToolkit.__init__` builds stores under `storage_dir` — use `tmp_path`, or `object.__new__(PageIndexToolkit)` if construction proves heavy.
- The module must be importable in a subprocess with `len(sys.modules)` barely above `import parrot` — TASK-3268's AST scan covers it, but add a quick subprocess assertion here too.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/stores.py:16` — `Protocol, runtime_checkable` already used in core.

---

## Implementation Blueprint

### Steps (in order)
1. Write `test_protocols.py` first — *why*: the structural matches are the whole contract.
2. Create `protocols.py` from the block below — *why*: spec §2 New Public Interfaces, refined per D3.
3. Run `pytest packages/ai-parrot/tests/knowledge/graphindex/test_protocols.py -v` and `ruff check` both files.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py` (CREATE)
```python
"""Provider Protocols for GraphIndex (FEAT-540).

Graph code types its providers against these structural Protocols instead of
importing the framework classes that implement them
(:class:`~parrot.knowledge.graphindex.embed.GraphIndexEmbedder`,
:class:`~parrot.knowledge.pageindex.llm_adapter.PageIndexLLMAdapter`,
:class:`~parrot.knowledge.pageindex.toolkit.PageIndexToolkit`). Those classes
satisfy the Protocols without inheriting from them. This module imports only
the standard library — keep it that way.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    """Vector provider for graph nodes.

    Mirrors the subset of ``GraphIndexEmbedder`` / ``HashingGraphEmbedder`` that
    graph code calls: ``embed_nodes`` (builder), ``get_embedding`` (resolve,
    signals) and ``search_similar`` (retriever).
    """

    async def embed_nodes(self, nodes: list[Any], batch_size: int = 64) -> list[Any]:
        """Embed ``nodes`` in batches and return them with ``embedding_ref`` set."""
        ...

    def get_embedding(self, node_id: str) -> Any | None:
        """Return the stored vector for ``node_id``, or ``None``."""
        ...

    async def search_similar(self, query: str, /, top_k: int = 10) -> list[tuple[str, float]]:
        """Return ``(node_id, score)`` pairs most similar to ``query``."""
        ...


@runtime_checkable
class LLMCaller(Protocol):
    """The subset of ``PageIndexLLMAdapter`` that wiki/graphindex call."""

    async def ask(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        """Send ``prompt`` and return the raw text response."""
        ...

    async def ask_structured(self, prompt: str, output_type: type, *args: Any, **kwargs: Any) -> Any:
        """Send ``prompt`` and return an instance of ``output_type``."""
        ...

    async def ask_json(self, prompt: str, *args: Any, **kwargs: Any) -> Any:
        """Send ``prompt`` and return parsed JSON."""
        ...
```
**Why this shape**: D3 — spec skeleton's `embed_nodes`-only `Embedder` is insufficient because the builder forwards the embedder to resolve/signals/retriever (recorded deviation). `search_similar`'s first parameter is positional-only because the two implementations name it differently.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py` (CREATE, continued)
```python
@runtime_checkable
class PageIndexer(Protocol):
    """What graph extractors need from ``PageIndexToolkit``.

    Derived from ``graphindex/extractors/loader.py`` call sites. The private
    ``_content_store`` is deliberately NOT part of the contract —
    ``GraphIndexBuilder`` reads it with ``getattr(..., None)``.
    """

    async def list_trees(self) -> list[str]:
        """List tree names in the backing store."""
        ...

    async def create_tree(self, tree_name: str, doc_name: str | None = None) -> dict[str, Any]:
        """Create an empty tree."""
        ...

    async def delete_tree(self, tree_name: str) -> dict[str, Any]:
        """Delete a tree and its sidecars."""
        ...

    async def get_tree(self, tree_name: str) -> dict[str, Any]:
        """Return the full tree dict."""
        ...

    async def insert_markdown(
        self, tree_name: str, markdown: str, parent_node_id: str | None = None, doc_name: str | None = None
    ) -> dict[str, Any]:
        """Parse ``markdown`` into a subtree and splice it in."""
        ...

    async def insert_ebook(
        self, tree_name: str, sections: list[dict[str, Any]], parent_node_id: str | None = None
    ) -> dict[str, Any]:
        """Persist ebook sections with their TOC relationships."""
        ...


class ProviderNotAvailable(RuntimeError):
    """Raised when a required provider was neither injected nor has a default.

    The message names the provider role and the distribution (and extra) that
    supplies it; the CLI maps this error to exit code 2.

    Args:
        role: Provider role, e.g. ``"LLMCaller"``.
        distribution: Distribution that supplies it, e.g. ``"ai-parrot"``.
        extra: Optional pip extra, e.g. ``"google"``.
    """

    def __init__(self, role: str, distribution: str, extra: str | None = None) -> None:
        self.role = role
        self.distribution = distribution
        self.extra = extra
        # FILL IN: message text — must contain `role` and `pip install <distribution>[<extra>]`
        # (no brackets when extra is None) — bounded by spec §4 test_provider_not_available_message.
        super().__init__(...)
```
**Why**: split only to respect the 80-line block cap — both blocks form one file. Order-of-injection logic (explicit → registered → default → error) lives in TASK-3259, not here.

### `packages/ai-parrot/tests/knowledge/graphindex/test_protocols.py` (CREATE)
```python
"""Structural Protocol tests for FEAT-540 (spec §4 Module 2)."""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import MagicMock

from parrot.knowledge.graphindex.protocols import Embedder, LLMCaller, PageIndexer, ProviderNotAvailable


def test_protocols_structural_match(tmp_path) -> None:
    """Framework classes satisfy the Protocols without inheriting from them."""
    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
    from parrot.knowledge.graphindex.factory import HashingGraphEmbedder
    from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

    assert isinstance(HashingGraphEmbedder(dimension=8), Embedder)
    assert isinstance(PageIndexLLMAdapter(client=MagicMock()), LLMCaller)
    # FILL IN: GraphIndexEmbedder instance without loading a model (object.__new__ or the
    # patch.object pattern from test_embed.py:31-47) → isinstance(..., Embedder);
    # PageIndexToolkit instance (tmp_path storage or object.__new__) → isinstance(..., PageIndexer)
    # — bounded by "no model download, no network".
    assert Embedder not in GraphIndexEmbedder.__mro__
    raise NotImplementedError


def test_stub_with_missing_method_is_not_embedder() -> None:
    """A stub lacking ``get_embedding`` / ``search_similar`` is not an ``Embedder``."""
    class _Stub:
        async def embed_nodes(self, nodes, batch_size=64):
            return nodes

    assert not isinstance(_Stub(), Embedder)


def test_provider_not_available_message() -> None:
    """Message names the role and the supplying distribution."""
    # FILL IN: assert role, "pip install ai-parrot[google]" in str(ProviderNotAvailable("LLMCaller",
    # "ai-parrot", "google")); and no "[" when extra is None; isinstance RuntimeError.
    raise NotImplementedError


def test_protocols_module_is_stdlib_only() -> None:
    """Importing the protocols module pulls in no heavy package."""
    code = ("import sys, parrot.knowledge.graphindex.protocols as p\n"
            "bad=[m for m in ('numpy','pydantic','navconfig','faiss') if m in sys.modules]\n"
            "print(bad)")
    # FILL IN: run in subprocess (env=os.environ.copy()); assert last stdout line == "[]".
    # NOTE: importing the protocols module executes parrot/knowledge/graphindex/__init__.py,
    # which imports numpy/pydantic today — so check only that protocols.py's OWN top-level
    # imports are stdlib (ast-parse the file) if the subprocess check cannot be made clean;
    # bounded by D3 "Module imports only typing".
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `ProviderNotAvailable.__init__` — message format; bounded by spec §4.
- [ ] `test_protocols_structural_match` — build `GraphIndexEmbedder` / `PageIndexToolkit` instances cheaply; bounded by no model download / no network.
- [ ] `test_provider_not_available_message` — assertions.
- [ ] `test_protocols_module_is_stdlib_only` — subprocess or AST check (graphindex package root imports numpy/pydantic, so prefer the AST check on `protocols.py`).

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.graphindex.protocols import Embedder, LLMCaller, PageIndexer, ProviderNotAvailable` works
- [ ] `GraphIndexEmbedder` and `HashingGraphEmbedder` instances are `Embedder`; `PageIndexLLMAdapter` is `LLMCaller`; `PageIndexToolkit` is `PageIndexer` — none of those classes modified
- [ ] `protocols.py` top-level imports are only `__future__` and `typing`
- [ ] `ProviderNotAvailable` names role + distribution (+ extra)
- [ ] `pytest packages/ai-parrot/tests/knowledge/graphindex/test_protocols.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py packages/ai-parrot/tests/knowledge/graphindex/test_protocols.py` clean
- [ ] Google-style docstrings + type hints on every public symbol

---

## Test Specification

See the `test_protocols.py` CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none (parallel-safe: creates new files only)
3. **Verify the Codebase Contract** — re-grep the signatures above (call sites in `extractors/loader.py`, `resolve.py`, `signals.py`, `retriever.py`); if a new provider method is called by graph code, add it to the Protocol and note it
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`
6. In a worktree, run tests with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/TASK-3258-graphindex-provider-protocols.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: `Embedder` includes `get_embedding` + `search_similar` (spec skeleton listed only `embed_nodes`) — required by builder → resolve/signals/retriever call sites (design D3).
