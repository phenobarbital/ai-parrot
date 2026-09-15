# TASK-3259: Sever embedder, builder and triage from the framework (Protocol injection)

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3257, TASK-3258
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 2** (Provider Protocols + injection), second half. TASK-3258
created `parrot/knowledge/graphindex/protocols.py` (`Embedder`, `LLMCaller`,
`PageIndexer`, `ProviderNotAvailable`). This task makes the graph tree *use*
them, so that `import parrot.knowledge.graphindex.builder` stops pulling
`parrot.embeddings`, `faiss` and `parrot.knowledge.pageindex.toolkit`
(→ `parrot.tools` → navigator_eventbus/pandas/pyarrow).

Today `graphindex/embed.py` imports `EmbeddingRegistry` (:15),
`quiet_faiss_loader` (:17), calls it at import time (:19) and imports `faiss`
(:20). `builder.py` imports `GraphIndexEmbedder` (:34) and `PageIndexToolkit`
(:55) at module level purely for annotations. `wiki/triage.py` imports
`PageIndexLLMAdapter` (:42) for two annotations.

Binding design (brief D4): the concrete `GraphIndexEmbedder` class moves
**verbatim** to a new core adapter module `parrot/embeddings/graphindex.py`;
`graphindex/embed.py` becomes a PEP 562 shim so the old import path keeps
working (spec AC "No breaking change to any documented public import path").

---

## Scope

- Move the `GraphIndexEmbedder` class body (embed.py lines 25-206) verbatim to NEW
  `packages/ai-parrot/src/parrot/embeddings/graphindex.py`, together with the
  `EmbeddingRegistry` / `quiet_faiss_loader()` / `faiss` imports (the import-time
  `quiet_faiss_loader()` call MUST stay immediately before `import faiss` —
  spec §7 gotcha).
- Rewrite `graphindex/embed.py` as a PEP 562 shim (`__all__ = ["GraphIndexEmbedder"]`,
  `__getattr__` resolving `"parrot.embeddings.graphindex"` by string).
- `builder.py`: drop module-level `GraphIndexEmbedder` and `PageIndexToolkit` imports;
  type `embedder: Embedder`, `pageindex_toolkit: PageIndexer | None`.
- `retriever.py` / `signals.py`: TYPE_CHECKING import → `Embedder`; retype the
  `Optional["GraphIndexEmbedder"]` annotations (1 in retriever, 4 in signals).
- `factory.py`: add `resolve_embedder()` (explicit → `HashingGraphEmbedder`) and use it in
  `build_graph_memory_toolkit`.
- `wiki/triage.py`: `IngestTriageRouter(adapter: LLMCaller, heavy_adapter: LLMCaller | None)`;
  remove the module-level `PageIndexLLMAdapter` import.
- Repoint `tests/knowledge/graphindex/test_embed.py:7` and
  `parrot_tools/graphindex/flowtask.py:26` to `parrot.embeddings.graphindex`.
- Tests: `test_builder_accepts_protocol_double`, `test_default_embedder_is_hashing`,
  shim/AST checks, triage accepts an `LLMCaller` stub.

**NOT in scope**:
- `graphindex/loader.py` (still imports `from .embed import GraphIndexEmbedder` :38 — the
  shim keeps it working; TASK-3266 relocates the whole loader).
- `graphindex/extractors/loader.py` `parrot.stores.models` import (TASK-3266).
- `NoveltyScorer.grounding_evaluator` — `GroundingEvaluator` (graphindex/grounding.py:96)
  is already framework-free (imports only pydantic + graphindex modules); leave it typed as is.
- `ProviderNotAvailable` wiring into the CLI (no call site needs it yet; TASK-3258 defines it).
- `parrot_tools/graphindex/toolkit.py:84` — TYPE_CHECKING-only import; the shim path is
  never executed, leave it.
- Ceiling-test xfail marks (TASK-3268 removes them).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/graphindex.py` | CREATE | Core adapter: `GraphIndexEmbedder` moved verbatim |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py` | MODIFY (rewrite) | PEP 562 shim |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | MODIFY | Protocol-typed `embedder` / `pageindex_toolkit` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` | MODIFY | TYPE_CHECKING import + 1 annotation |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py` | MODIFY | TYPE_CHECKING import + 4 annotations |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` | MODIFY | `resolve_embedder()` + use it |
| `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` | MODIFY | `LLMCaller`-typed adapters |
| `packages/ai-parrot/tests/knowledge/graphindex/test_embed.py` | MODIFY | import from new path |
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py` | MODIFY | import from new path |
| `packages/ai-parrot/tests/knowledge/graphindex/test_protocol_injection.py` | CREATE | new unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `2c54cbac2` on 2026-09-15. Re-verify before editing.

### Verified Imports
```python
from parrot.embeddings.registry import EmbeddingRegistry          # embeddings/registry.py:55
from parrot.utils.faiss_logging import quiet_faiss_loader         # utils/faiss_logging.py:34
from parrot.knowledge.graphindex.schema import UniversalNode      # used at embed.py:16
from parrot.knowledge.graphindex.factory import HashingGraphEmbedder, DEFAULT_DIMENSION  # factory.py:116, :42
from parrot.knowledge.graphindex.builder import GraphIndexBuilder  # builder.py:60
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter  # llm_adapter.py:42 (TYPE_CHECKING / tests only)
# Created by TASK-3258 (verify the file exists before starting):
from parrot.knowledge.graphindex.protocols import Embedder, LLMCaller, PageIndexer
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py (206 lines)
from parrot.embeddings.registry import EmbeddingRegistry          # line 15
from parrot.knowledge.graphindex.schema import UniversalNode      # line 16
from parrot.utils.faiss_logging import quiet_faiss_loader         # line 17
quiet_faiss_loader()  # silence faiss boot logs before the first import   # line 19
import faiss  # noqa: E402 — must follow quiet_faiss_loader()      # line 20
logger = logging.getLogger(__name__)                              # line 22
class GraphIndexEmbedder:                                          # line 25
    def __init__(self, model_name: str = "default", dimension: int = 384,
                 pgvector_dsn: Optional[str] = None) -> None       # line 40
    async def embed_nodes(self, nodes: list[UniversalNode], batch_size: int = 64) -> list[UniversalNode]  # line 58
    async def search_similar(...)                                  # line 122
    def get_embedding(self, node_id: str) -> Optional[np.ndarray]  # line 160
    async def _persist_to_pgvector(...)                            # line 193 (last method, file ends 206)

# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
from __future__ import annotations                                 # line 18
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder   # line 34
from parrot.knowledge.graphindex.signals import SignalRelevanceConfig  # line 53
from parrot.knowledge.ontology.schema import TenantContext         # line 54
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit    # line 55
class GraphIndexBuilder:                                           # line 60
    def __init__(self, persistence, embedder: GraphIndexEmbedder,  # line 116 / 119
                 ..., pageindex_toolkit: PageIndexToolkit | None = None, ...)  # line 123
    # embedder uses: embed_nodes (:192, :383); passed to resolve_cross_domain (:211) and
    # signals (:232) which call get_embedding; pageindex_toolkit used via
    # getattr(self.pageindex_toolkit, "_content_store", None) (:289) and LoaderExtractor(toolkit=...) (:539, :637)

# packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py
if TYPE_CHECKING:
    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder  # line 39
        embedder: Optional["GraphIndexEmbedder"] = None,             # line 190 (only occurrence)

# packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py
if TYPE_CHECKING:
    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder  # line 40
    embedder: Optional["GraphIndexEmbedder"] ...                     # lines 395, 466, 528, 557 (4 occurrences)

# packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
DEFAULT_DIMENSION = 256                                            # line 42
class HashingGraphEmbedder:                                        # line 116 (lazy faiss import :131-134)
    async def embed_nodes(self, nodes, batch_size: int = 64)       # line 142
    def get_embedding(self, node_id: str)                          # line 172
    async def search_similar(self, query: str, top_k: int = 10)    # line 176
async def build_graph_memory_toolkit(..., embedder: Optional[Any] = None, ..., dimension: int = DEFAULT_DIMENSION, ...)  # line 197
    embedder = embedder or HashingGraphEmbedder(dimension=dimension)  # line 279
    # then uses embedder.index (:285) and embedder._node_id_map (:287) — NOT on the Protocol

# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py
from parrot.knowledge.graphindex.grounding import GroundingEvaluator   # line 41 (stays)
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter # line 42 (remove)
class IngestTriageRouter:                                          # line 252
    def __init__(self, charter: Charter, adapter: PageIndexLLMAdapter,  # line 271 / 274
                 sources, novelty_scorer, *, heavy_adapter: PageIndexLLMAdapter | None = None, ...)  # line 278
    # uses self.adapter.ask_structured (:322), self.heavy_adapter.ask_structured (:337)

# packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder   # line 26
        return GraphIndexEmbedder(model_name=model_name, dimension=dimension)  # line 199

# packages/ai-parrot/tests/knowledge/graphindex/test_embed.py
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder   # line 7
#   fixture uses patch.object(GraphIndexEmbedder, "__init__", ...) (:31) — class-object patch,
#   survives the move unchanged.

# Precedent for PEP 562 lazy export:
# packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py:117 (_LAZY_ATTRS), :136 (__getattr__)
```

### Does NOT Exist
- ~~`parrot.embeddings.graphindex`~~ — created by THIS task.
- ~~`parrot.knowledge.graphindex.factory.resolve_embedder`~~ — created by THIS task.
- ~~`HashingGraphEmbedder` in `embed.py`~~ — it is in `factory.py:116`.
- ~~`Embedder.index` / `Embedder._node_id_map`~~ — not Protocol members; `build_graph_memory_toolkit`
  reads them from the concrete embedder (keep that code, it is typing-only).
- ~~`PageIndexer._content_store`~~ — not a Protocol member; builder keeps `getattr(..., "_content_store", None)`.
- ~~A `wiki/tests/test_triage.py`~~ — no triage unit test file exists today; create coverage in the new test module.
- ~~`ai-parrot-embeddings` owning `graphindex.py`~~ — satellite `packages/ai-parrot-embeddings/src/parrot/embeddings/`
  has only google/huggingface/openai; the new module goes in CORE `packages/ai-parrot/src/parrot/embeddings/`.

---

## Implementation Notes

### Key Constraints
- Protocols are structural: never make `GraphIndexEmbedder` / `PageIndexToolkit` /
  `PageIndexLLMAdapter` inherit from them (spec §7).
- `builder.py` has `from __future__ import annotations`; annotations are strings, so importing
  `Embedder`/`PageIndexer` from `protocols.py` (typing-only module) at module level is fine and cheap.
- Keep `quiet_faiss_loader()` before `import faiss` in the new module (spec §7 gotcha).
- `from parrot.knowledge.graphindex.embed import GraphIndexEmbedder` must keep working
  (graphindex/loader.py:38, `parrot_tools` TYPE_CHECKING, examples).
- Do not change any behaviour of `GraphIndexEmbedder`; it is a pure move.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py:44-110` — PEP 562 lazy-export pattern.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py:117-144` — same pattern in graphindex.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm `packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py` exists (TASK-3258) — *why*: every retype imports from it.
2. `git mv`-free move: create `parrot/embeddings/graphindex.py` with the header below, then cut embed.py lines 25-206 (class `GraphIndexEmbedder` to EOF) and paste them verbatim below the header — *why*: history of a partial-file move is not preserved by git anyway; a verbatim paste guarantees zero behaviour change.
3. Replace the entire content of `graphindex/embed.py` with the shim block — *why*: old path keeps resolving, but importing the graph tree no longer loads faiss.
4. Apply the builder / retriever / signals retypes — *why*: they were the module-level reasons `PageIndexToolkit` and the faiss embedder were imported.
5. Add `resolve_embedder` to factory.py and call it at line 279 — *why*: spec injection order explicit → default (registered-provider level is FEAT-541).
6. Retype triage.py adapters to `LLMCaller` — *why*: `PageIndexLLMAdapter` import drags `parrot.clients`.
7. Repoint test_embed.py and flowtask.py imports; write the new tests; run the test commands in Acceptance Criteria.

### `packages/ai-parrot/src/parrot/embeddings/graphindex.py` (CREATE)
```python
"""GraphIndex embedding adapter (framework side).

Concrete :class:`GraphIndexEmbedder` backed by :class:`EmbeddingRegistry`
and an in-memory FAISS index. It satisfies the framework-free
:class:`parrot.knowledge.graphindex.protocols.Embedder` Protocol
structurally and is injected into ``GraphIndexBuilder`` by framework
callers (FEAT-540). Moved verbatim from
``parrot/knowledge/graphindex/embed.py``, which is now a lazy shim.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from parrot.embeddings.registry import EmbeddingRegistry
from parrot.knowledge.graphindex.schema import UniversalNode
from parrot.utils.faiss_logging import quiet_faiss_loader

quiet_faiss_loader()  # silence faiss boot logs before the first import
import faiss  # noqa: E402 — must follow quiet_faiss_loader()

logger = logging.getLogger(__name__)

__all__ = ["GraphIndexEmbedder"]


# FILL IN: paste packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py lines 25-206
#          (class GraphIndexEmbedder ... end of file) VERBATIM here — bounded by
#          "pure move, no behaviour change"; do not edit method bodies.
```
**Why this shape**: the adapter lives on the framework side of the seam (spec §2 Overview: "`GraphIndexEmbedder` becomes an *adapter* in core"). Imports are exactly the ones embed.py had, so `Optional`, `np`, `logger` references inside the pasted body keep resolving.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py` (MODIFY — replace whole file)
```python
"""Backward-compatible shim for :class:`GraphIndexEmbedder` (FEAT-540).

The concrete FAISS/EmbeddingRegistry embedder moved to
:mod:`parrot.embeddings.graphindex` so that importing the graph tree never
loads ``faiss`` or ``parrot.embeddings``. Graph code types against
:class:`parrot.knowledge.graphindex.protocols.Embedder` instead.
``from parrot.knowledge.graphindex.embed import GraphIndexEmbedder`` keeps
working: the name resolves lazily on first access (PEP 562).
"""

from __future__ import annotations

from typing import Any

__all__ = ["GraphIndexEmbedder"]

_LAZY_ATTRS: dict[str, str] = {
    "GraphIndexEmbedder": "parrot.embeddings.graphindex",
}


def __getattr__(name: str) -> Any:
    """Resolve ``GraphIndexEmbedder`` from its framework module on first access.

    Args:
        name: Attribute requested on this module.

    Returns:
        The resolved object.

    Raises:
        AttributeError: If ``name`` is not a lazily exported attribute.
    """
    module_path = _LAZY_ATTRS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return the public names, including lazily exported ones."""
    return sorted(__all__)
```
**Why**: module names are strings, so the AST scan (TASK-3268) sees no `parrot.embeddings` import and `import parrot.knowledge.graphindex.embed` costs nothing.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.graphindex.embed import GraphIndexEmbedder' builder.py)
# DELETE line 34:
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder

# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.toolkit import PageIndexToolkit' builder.py)
# REPLACE line 55 with:
from parrot.knowledge.graphindex.protocols import Embedder, PageIndexer

# occurrences: 1 (verified: grep -c '        embedder: GraphIndexEmbedder,' builder.py)  — line 119
        embedder: Embedder,
# occurrences: 1 (verified: grep -c '        pageindex_toolkit: PageIndexToolkit | None = None,' builder.py)  — line 123
        pageindex_toolkit: PageIndexer | None = None,
```
**Why**: both imports existed only for annotations. Also update the class docstring lines 69 and 74 to say "an object satisfying :class:`Embedder`" / ":class:`PageIndexer`" (FILL IN wording). Keep import order sorted where the protocols import lands (line 55 area, after `ontology.schema`).

### `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` and `signals.py` (MODIFY)
```python
# retriever.py — occurrences: 1 (verified: grep -c '    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder' retriever.py) — line 39
    from parrot.knowledge.graphindex.protocols import Embedder
# retriever.py — occurrences: 1 (verified: grep -c 'Optional\["GraphIndexEmbedder"\]' retriever.py) — line 190
        embedder: Optional["Embedder"] = None,

# signals.py — occurrences: 1 (verified: grep -c '    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder' signals.py) — line 40
    from parrot.knowledge.graphindex.protocols import Embedder
# signals.py — occurrences: 4 (verified: grep -c 'Optional\["GraphIndexEmbedder"\]' signals.py) — lines 395, 466, 528, 557
# replace_all 'Optional["GraphIndexEmbedder"]' -> 'Optional["Embedder"]' (every occurrence is an annotation)
```
**Why**: typing-only; replace-all is safe because all 4 hits are parameter annotations (verified).

### `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^async def build_graph_memory_toolkit(' factory.py)
# BEFORE — insert above `async def build_graph_memory_toolkit(` (verified: factory.py:197)
def resolve_embedder(
    embedder: Optional[Embedder] = None,
    *,
    dimension: int = DEFAULT_DIMENSION,
) -> Embedder:
    """Resolve the embedder to use, following the FEAT-540 injection order.

    Order: explicit ``embedder`` argument → built-in deterministic
    :class:`HashingGraphEmbedder`. (A registered-provider level between the
    two arrives with FEAT-541's entry points.)

    Args:
        embedder: An explicitly injected embedder, or ``None``.
        dimension: Vector dimension for the default embedder.

    Returns:
        The injected embedder, or a new ``HashingGraphEmbedder``.
    """
    if embedder is not None:
        return embedder
    logger.debug("No embedder injected; using HashingGraphEmbedder(dimension=%d)", dimension)
    return HashingGraphEmbedder(dimension=dimension)


# occurrences: 1 (verified: grep -c '    embedder = embedder or HashingGraphEmbedder(dimension=dimension)' factory.py) — line 279
    embedder = resolve_embedder(embedder, dimension=dimension)

# Add near the other graphindex imports (after factory.py:34 `from parrot.knowledge.graphindex.schema import UniversalNode`):
from parrot.knowledge.graphindex.protocols import Embedder
```
**Why**: `embedder is not None` (not truthiness) is the explicit-first rule; a Mock/zero-length object must not be silently replaced. Leave the `embedder: Optional[Any]` parameter of `build_graph_memory_toolkit` as is — it later reads `.index` / `._node_id_map`, which are outside the Protocol.

### `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter' triage.py) — line 42
# REPLACE with:
from parrot.knowledge.graphindex.protocols import LLMCaller

# occurrences: 1 (verified: grep -c '        adapter: PageIndexLLMAdapter,' triage.py) — line 274
        adapter: LLMCaller,
# occurrences: 1 (verified: grep -c '        heavy_adapter: PageIndexLLMAdapter | None = None,' triage.py) — line 278
        heavy_adapter: LLMCaller | None = None,
```
**Why**: the router only calls `ask_structured` (:322, :337). The two docstring mentions at lines 10 and 31 may keep naming `PageIndexLLMAdapter` as the typical implementation (prose, not imports).

### `test_embed.py` / `flowtask.py` (MODIFY)
```python
# test_embed.py — occurrences: 1 (verified: grep -c '^from parrot.knowledge.graphindex.embed import GraphIndexEmbedder' test_embed.py) — line 7
from parrot.embeddings.graphindex import GraphIndexEmbedder
# flowtask.py — occurrences: 1 (verified: grep -c '^from parrot.knowledge.graphindex.embed import GraphIndexEmbedder' flowtask.py) — line 26
from parrot.embeddings.graphindex import GraphIndexEmbedder
```

### `packages/ai-parrot/tests/knowledge/graphindex/test_protocol_injection.py` (CREATE)
See Test Specification — write it as given, completing FILL IN bodies.

### FILL IN checklist
- [ ] `embeddings/graphindex.py` — paste embed.py:25-206 verbatim; bounded by "pure move".
- [ ] `builder.py` docstring lines 69/74 — Protocol wording; bounded by Google-style docstrings AC.
- [ ] `test_protocol_injection.py::test_builder_accepts_protocol_double` — build a minimal `GraphIndexBuilder` with a stub persistence (mirror `tests/knowledge/graphindex/test_builder.py:80` fixture) and a stub embedder implementing only `embed_nodes`; bounded by spec §4 row `test_builder_accepts_protocol_double`.
- [ ] `test_protocol_injection.py::test_triage_router_accepts_llmcaller_stub` — construct `IngestTriageRouter` with an object exposing `ask/ask_structured/ask_json`; bounded by `LLMCaller` Protocol (TASK-3258).

---

## Addendum — repo-root `tests/` tree (review, 2026-09-15)

Note: the repo-root `tests/knowledge/wiki/test_triage.py:13` constructs `IngestTriageRouter(charter, adapter, sources, novelty_scorer)` with a duck-typed stub adapter (only `ask_structured`) — retyping to `LLMCaller` must stay annotation-only (no `isinstance` check), or that stub breaks.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/embeddings/graphindex.py` defines `GraphIndexEmbedder`; `from parrot.knowledge.graphindex.embed import GraphIndexEmbedder` still returns the same class object.
- [ ] `graphindex/embed.py`, `builder.py`, `wiki/triage.py` contain no module-level import of `parrot.embeddings`, `parrot.utils.faiss_logging`, `faiss`, `parrot.knowledge.pageindex.toolkit` or `parrot.knowledge.pageindex.llm_adapter`.
- [ ] In a clean subprocess, `import parrot.knowledge.graphindex.embed` leaves `faiss` and `parrot.embeddings.registry` out of `sys.modules`.
- [ ] `resolve_embedder(None)` returns a `HashingGraphEmbedder`; `resolve_embedder(x)` returns `x`.
- [ ] `isinstance(HashingGraphEmbedder(), Embedder)` is `True`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/ packages/ai-parrot-tools/tests/graphindex/ -v`
- [ ] Wiki tests unaffected: `pytest packages/ai-parrot/tests/knowledge/wiki/ -q`
- [ ] `ruff check` clean on every changed file.
- [ ] `pytest tests/knowledge/wiki/test_triage.py -v` (repo-root tree) passes

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_protocol_injection.py
"""FEAT-540 Module 2 — graph code accepts Protocol doubles (TASK-3259)."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.knowledge.graphindex.factory import HashingGraphEmbedder, resolve_embedder
from parrot.knowledge.graphindex.protocols import Embedder

_SRC = Path(__file__).resolve().parents[3] / "src" / "parrot" / "knowledge"


def test_default_embedder_is_hashing():
    assert isinstance(resolve_embedder(None), HashingGraphEmbedder)


def test_explicit_embedder_wins():
    sentinel = HashingGraphEmbedder(dimension=8)
    assert resolve_embedder(sentinel) is sentinel


def test_hashing_embedder_satisfies_protocol():
    assert isinstance(HashingGraphEmbedder(dimension=8), Embedder)


def test_embed_shim_resolves_same_class():
    from parrot.embeddings.graphindex import GraphIndexEmbedder as real
    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder as shim
    assert shim is real


def test_embed_shim_import_is_faiss_free():
    code = (
        "import sys, parrot.knowledge.graphindex.embed; "
        "print(int('faiss' in sys.modules), int('parrot.embeddings.registry' in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.split()[-2:] == ["0", "0"]


@pytest.mark.parametrize("rel", ["graphindex/embed.py", "graphindex/builder.py", "wiki/triage.py"])
def test_no_framework_module_level_imports(rel):
    banned = ("parrot.embeddings", "parrot.utils.faiss_logging", "faiss",
              "parrot.knowledge.pageindex.toolkit", "parrot.knowledge.pageindex.llm_adapter")
    tree = ast.parse((_SRC / rel).read_text())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(banned), f"{rel}: {ast.unparse(node)}"
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith(banned) for a in node.names), f"{rel}: {ast.unparse(node)}"


@pytest.mark.asyncio
async def test_builder_accepts_protocol_double(tmp_path):
    class _StubEmbedder:
        async def embed_nodes(self, nodes, **kw):
            return nodes

    # FILL IN: construct GraphIndexBuilder(persistence=<stub>, embedder=_StubEmbedder(), output_dir=tmp_path)
    #          mirroring tests/knowledge/graphindex/test_builder.py:80, run build() over an empty or
    #          one-file source list with resolution disabled, and assert it returns a BuildResult.


@pytest.mark.asyncio
async def test_triage_router_accepts_llmcaller_stub():
    # FILL IN: build IngestTriageRouter(charter, adapter=<stub with ask/ask_structured/ask_json>,
    #          sources=MagicMock(), novelty_scorer=MagicMock()) and assert heavy_adapter defaults to adapter.
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§3 Module 2, §7 gotchas).
2. **Check dependencies** — TASK-3257 and TASK-3258 must be `done` in `sdd/tasks/index/graphindex-core-seams.json`.
3. **Verify the Codebase Contract** — re-run the `grep -c` anchors in the blueprint; if a line moved, update the contract first.
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `FILL IN`.
6. **Run tests inside the worktree with** `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest ...` — the shared venv is editable-installed against the main checkout.
7. **Move this file** to `sdd/tasks/completed/`, update the index → `"done"`, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: `Embedder` Protocol (TASK-3258) carries `embed_nodes` + `get_embedding` + `search_similar`, not `embed_nodes` alone — the builder forwards the embedder to resolve/signals/retriever, which call the other two. `NoveltyScorer.grounding_evaluator` left typed as `GroundingEvaluator` (already framework-free).
