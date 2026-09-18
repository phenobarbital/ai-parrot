# TASK-3266: Local `GraphDocument` / loader shape + relocate `GraphIndexLoader` to core loaders

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3257, TASK-3259, TASK-3264
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6** (and the `loader.py:34` half of Module 7). Two graph-tree modules
still import the framework at module level:

- `graphindex/extractors/loader.py:38` — `from parrot.stores.models import Document`
  (only to build one `Document` in `PlainTextLoader._load`). This module is on the
  `wikitoolkit` CLI path (`wiki/documents.py:31` imports `PLAIN_TEXT_EXTENSIONS` from it)
  and on the builder path (`builder.py:36`), so it blocks G1.
- `graphindex/loader.py:31-34` — `GraphIndexLoader(AbstractLoader)` imports
  `parrot.loaders.abstract.AbstractLoader`, `parrot.stores.models.Document` and
  `OntologyGraphStore`. `GraphIndexLoader` *is* a framework loader
  (`tests/knowledge/graphindex/test_loader.py:81` asserts `issubclass(GraphIndexLoader, AbstractLoader)`),
  so it cannot stop subclassing `AbstractLoader`; it must leave the graph tree instead.

Binding design (brief D10): add framework-free `GraphDocument` + `DocumentLoader` shapes in
`graphindex/models.py`; relocate `GraphIndexLoader` (+ its two private persistence helpers)
verbatim to NEW core `parrot/loaders/graphindex.py`, with the `Document ↔ GraphDocument`
adapter living there (framework boundary); `graphindex/loader.py` becomes a PEP 562 shim.

State this task starts from (re-verify):
- After **TASK-3259**: `GraphIndexEmbedder` lives in `parrot.embeddings.graphindex`;
  `graphindex/embed.py` is a shim; `graphindex/loader.py:38` still says `from .embed import GraphIndexEmbedder`.
  `graphindex/protocols.py` (TASK-3258) provides `PageIndexer`.
- After **TASK-3264**: `GraphIndexLoader._resolve_arango` no longer has the inline navconfig
  block — it lazily imports `require_setting, resolve_setting` from `parrot.knowledge.wiki.project`.
- After **TASK-3257**: `parrot/stores/__init__.py` is a lazy root, so `parrot.stores.models` is cheap on the framework side.

---

## Scope

- CREATE `packages/ai-parrot/src/parrot/knowledge/graphindex/models.py`: `GraphDocument` (Pydantic) and `DocumentLoader` (`@runtime_checkable` Protocol, `async _load(source, **kwargs) -> list[Any]`).
- MODIFY `graphindex/extractors/loader.py`: drop the `parrot.stores.models` import; `PlainTextLoader._load` returns `list[GraphDocument]`; TYPE_CHECKING `PageIndexToolkit` → `PageIndexer`.
- CREATE `packages/ai-parrot/src/parrot/loaders/graphindex.py`: move old `graphindex/loader.py` lines 44-416 (`_NullPersistence`, `_CapturingPersistence`, `GraphIndexLoader`) verbatim; module header with absolute imports; add `to_graph_document()` / `from_graph_document()`.
- REPLACE `graphindex/loader.py` with a PEP 562 shim for `GraphIndexLoader`, `_NullPersistence`, `_CapturingPersistence`.
- MODIFY `graphindex/__init__.py` `_LAZY_ATTRS["GraphIndexLoader"]` → `"parrot.loaders.graphindex"`.
- MODIFY `tests/knowledge/graphindex/test_loader.py`: `loader_mod` must be the real module (`parrot.loaders.graphindex`) so `monkeypatch.setattr(loader_mod, ...)` still intercepts.
- Tests: `test_graph_document_roundtrip`, shim identity, extractors/loader AST check, `PlainTextLoader` returns `GraphDocument`.

**NOT in scope**:
- `graphindex/persist.py:36` `OntologyGraphStore` import (TASK-3267).
- `wiki/documents.py` aiohttp laziness (TASK-3257).
- Removing xfail marks from `test_import_ceilings.py` or the tree-wide AST scan (TASK-3268).
- `extractors/loader.py` TYPE_CHECKING `from parrot.loaders.ebook import EbookSection` (:42) — TYPE_CHECKING-only, excluded from the AST scan; leave it.
- Any behaviour change in `GraphIndexLoader` (pure move).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/models.py` | CREATE | `GraphDocument`, `DocumentLoader` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py` | MODIFY | use `GraphDocument` / `PageIndexer` |
| `packages/ai-parrot/src/parrot/loaders/graphindex.py` | CREATE | relocated `GraphIndexLoader` + adapters |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` | MODIFY (rewrite) | PEP 562 shim |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py` | MODIFY | lazy map target |
| `packages/ai-parrot/tests/knowledge/graphindex/test_loader.py` | MODIFY | repoint `loader_mod` + imports |
| `packages/ai-parrot/tests/knowledge/graphindex/test_graph_document.py` | CREATE | new unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `2c54cbac2` on 2026-09-15 (pre-3259/3264). Lines marked
> **post-3259/3264** must be re-verified by the executor.

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader                       # loaders/__init__.py:115 re-exports; defined in loaders/abstract.py
from parrot.stores.models import Document                                # stores/models.py:19 (page_content :24, metadata :25)
from parrot.knowledge.ontology.graph_store import OntologyGraphStore     # ontology/graph_store.py (imports only logging/re/typing/pydantic/.schema)
from parrot.knowledge.ontology.schema import TenantContext               # ontology/schema.py:529
from parrot.knowledge.graphindex.builder import GraphIndexBuilder        # builder.py:60
from parrot.knowledge.graphindex.meta_ontology import build_graphindex_ontology
from parrot.knowledge.graphindex.persist import GraphIndexPersistence
from parrot.knowledge.graphindex.schema import BuildResult, SourceConfig, UniversalEdge, UniversalNode
from parrot.embeddings.graphindex import GraphIndexEmbedder              # created by TASK-3259
from parrot.knowledge.graphindex.protocols import PageIndexer            # created by TASK-3258
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py (416 lines)
from __future__ import annotations                                        # line 25
import tempfile                                                           # line 27
from pathlib import Path                                                  # line 28
from typing import Any, List, Optional, Union                             # line 29
from parrot.loaders.abstract import AbstractLoader                        # line 31
from parrot.stores.models import Document                                 # line 32
from parrot.knowledge.ontology.graph_store import OntologyGraphStore      # line 34
from parrot.knowledge.ontology.schema import TenantContext                # line 35
from .builder import GraphIndexBuilder                                    # line 37
from .embed import GraphIndexEmbedder                                     # line 38 (unchanged by TASK-3259 — shim path)
from .meta_ontology import build_graphindex_ontology                      # line 39
from .persist import GraphIndexPersistence                                # line 40
from .schema import BuildResult, SourceConfig, UniversalEdge, UniversalNode  # line 41
class _NullPersistence:                                                   # line 44
class _CapturingPersistence:                                              # line 69
class GraphIndexLoader(AbstractLoader):                                   # line 96
    def __init__(self, source=None, *, tenant_id="default", client=None, model=None, adapter=None,
                 output_dir=None, embedding_model="default", embedding_dim=384, pgvector_dsn=None,
                 detect_communities=False, arango=None, arango_host=None, ..., storage_dir=None,
                 sqlite_dir=None, **kwargs)                               # line 130
        self.embedder = GraphIndexEmbedder(...)                           # line 173
    async def _make_persistence(self) -> Any:                             # line 288; OntologyGraphStore(arango_client=db) line 305
    def _resolve_arango(...) -> Optional[dict]:                           # line 314 (body rewritten by TASK-3264 — post-3264)
    def _node_to_document(self, node: UniversalNode) -> Document:         # line 399; returns Document(...) line 416 (EOF)

# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py (585 lines)
from typing import TYPE_CHECKING, Optional                                # line 29
from parrot.stores.models import Document                                 # line 38 (occurrences: 1)
if TYPE_CHECKING:
    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit       # line 41 (occurrences: 1)
    from parrot.loaders.ebook import EbookSection                         # line 42 (stays)
PLAIN_TEXT_EXTENSIONS: set[str] = {...}                                   # line 58-ish (imported by wiki/documents.py:31)
class PlainTextLoader:                                                    # line 64
    async def _load(self, source: str | Path, **kwargs: object) -> list[Document]:  # line 88 (occurrences: 1)
        return [Document(page_content=text, metadata={...})]              # `Document(` at line 103 (only constructor call)
class LoaderExtractor:                                                    # line 138
    def __init__(self, ..., toolkit: Optional["PageIndexToolkit"] = None, ...)  # line 162 (occurrences: 1)
    # toolkit calls: list_trees/delete_tree/create_tree/insert_ebook/get_tree/insert_markdown (:216-337)
# Other `Document` mentions (lines 21, 68, 89, 96, 145, 180, 267, 271, 336, 546, 562, 565, 569) are docstrings/comments.

# packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py
_LAZY_ATTRS = {                                                            # line 117
    "GraphIndexLoader": "parrot.knowledge.graphindex.loader",             # line 118 (occurrences: 1)

# packages/ai-parrot/src/parrot/loaders/__init__.py — sys.meta_path redirector to parrot_loaders
_CORE_SUBMODULES = {p.stem for p in _CORE_LOADERS_DIR.glob("*.py") ...}   # line 44-46 → a new core `graphindex.py`
#   is automatically treated as local (not redirected). parrot_loaders has no `graphindex` module (verified).

# packages/ai-parrot/tests/knowledge/graphindex/test_loader.py
import parrot.knowledge.graphindex.loader as loader_mod                   # line 17
from parrot.knowledge.graphindex.loader import (GraphIndexLoader, _NullPersistence)  # lines 18-21
from parrot.loaders.abstract import AbstractLoader                        # line 26
from parrot.stores.models import Document                                 # line 27
monkeypatch.setattr(loader_mod, "GraphIndexEmbedder", MagicMock())        # line 54
monkeypatch.setattr(loader_mod, "GraphIndexBuilder", _FakeBuilder)        # line 75
monkeypatch.setattr(loader_mod, "OntologyGraphStore", store_cls)          # line 160
monkeypatch.setattr(loader_mod, "GraphIndexPersistence", persistence_cls) # line 161

# packages/ai-parrot/tests/knowledge/graphindex/test_builder_odoo.py:258,265,273
#   `from parrot.knowledge.graphindex.loader import GraphIndexLoader` (no monkeypatching) — shim covers it.
# packages/ai-parrot/tests/knowledge/graphindex/test_builder_loader_sources.py:66-90
#   asserts docs[0].page_content / docs[0].metadata["source"] from PlainTextLoader._load — GraphDocument satisfies.
```

### Does NOT Exist
- ~~`parrot.knowledge.graphindex.models`~~ / ~~`GraphDocument`~~ / ~~`DocumentLoader`~~ — created by THIS task.
- ~~`parrot.loaders.graphindex`~~ — created by THIS task.
- ~~`parrot_loaders.graphindex`~~ — does not exist (the core module is not shadowed).
- ~~`to_graph_document` / `from_graph_document`~~ — created by THIS task.
- ~~`GraphIndexLoader` without `AbstractLoader`~~ — must keep subclassing it (test_loader.py:81).
- ~~Shim monkeypatching~~ — `monkeypatch.setattr(<shim>, "GraphIndexBuilder", ...)` does NOT affect the relocated module; tests must patch `parrot.loaders.graphindex`.

---

## Implementation Notes

### Key Constraints
- Move `GraphIndexLoader` verbatim; the only header change is relative → absolute imports and
  `GraphIndexEmbedder` from `parrot.embeddings.graphindex` (the real module, not the shim).
- Keep `OntologyGraphStore`, `GraphIndexBuilder`, `GraphIndexEmbedder`, `GraphIndexPersistence` as
  **module-level names** in `parrot/loaders/graphindex.py` — test_loader.py monkeypatches them there.
  The new module is framework side, so module-level imports are allowed.
- `GraphDocument` must duck-type as the loader output extractors consume: `.page_content: str`, `.metadata: dict`.
- `graphindex/models.py` imports only `typing`, `pathlib`, `pydantic` (it is inside the ceiling tree).
- PEP 562 `from shim import _NullPersistence` works: `from X import name` falls back to module `__getattr__`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py:113-144` — existing lazy map pattern.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py` — shim shape written by TASK-3259 (copy it).

---

## Implementation Blueprint

### Steps (in order)
1. Re-verify the post-3259/3264 anchors (`grep -n "from .embed import GraphIndexEmbedder" graphindex/loader.py`, `grep -n "resolve_setting" graphindex/loader.py`, `ls graphindex/protocols.py parrot/embeddings/graphindex.py`) — *why*: this task moves code those tasks edited.
2. Create `graphindex/models.py` — *why*: framework-free shape the extractor can return.
3. Edit `extractors/loader.py` — *why*: removes the `parrot.stores` edge from the CLI/builder import path (G1/G3).
4. Create `parrot/loaders/graphindex.py` with the header below, then cut old `graphindex/loader.py` lines 44-EOF verbatim below it — *why*: the loader is a framework `AbstractLoader`; it belongs on the framework side.
5. Append the adapter functions to `parrot/loaders/graphindex.py` — *why*: spec Module 6 "core-side adapter".
6. Replace `graphindex/loader.py` with the shim; update `graphindex/__init__.py` map — *why*: old import paths keep working.
7. Update the module docstring of the new file (old loader.py lines 1-23 — move it too, with "via ``navconfig``" already changed by TASK-3264).
8. Repoint `test_loader.py`; write `test_graph_document.py`; run tests.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/models.py` (CREATE)
```python
"""Framework-free document shapes for GraphIndex (FEAT-540).

GraphIndex extractors need only two things from a loaded document —
``page_content`` and ``metadata`` — and only one thing from a loader —
``async _load(source) -> list[document]``. These shapes let the graph
tree express that without importing ``parrot.stores`` or
``parrot.loaders``. Framework adapters live in
:mod:`parrot.loaders.graphindex`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

__all__ = ["DocumentLoader", "GraphDocument"]


class GraphDocument(BaseModel):
    """Minimal document shape graphindex loaders need.

    Mirrors the two fields graphindex reads from ``parrot.stores.models
    .Document`` (``page_content``, ``metadata``) without importing the
    stores package. Core adapters convert between the two.

    Attributes:
        page_content: The document text.
        metadata: Free-form metadata (source path, filename, doctype, …).
    """

    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class DocumentLoader(Protocol):
    """Loader shape :class:`LoaderExtractor` consumes.

    Any object whose ``_load`` returns documents exposing
    ``page_content`` and ``metadata`` qualifies — ai-parrot loaders and
    :class:`PlainTextLoader` alike.
    """

    async def _load(self, source: str | Path, **kwargs: Any) -> list[Any]:
        """Load ``source`` and return its documents."""
        ...
```
**Why**: exact field set from spec §2 Data Models; the Protocol mirrors the contract already documented in `PlainTextLoader`'s docstring (extractors/loader.py:67-68).

### `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from parrot.stores.models import Document' extractors/loader.py) — line 38
# REPLACE with:
from parrot.knowledge.graphindex.models import GraphDocument

# occurrences: 1 (verified: grep -c '^    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit' extractors/loader.py) — line 41
# REPLACE with:
    from parrot.knowledge.graphindex.protocols import PageIndexer

# occurrences: 1 (verified: grep -c 'async def _load(self, source: str | Path, \*\*kwargs: object) -> list\[Document\]:' extractors/loader.py) — line 88
    async def _load(self, source: str | Path, **kwargs: object) -> list[GraphDocument]:

# line 103 — the only constructor call (`            Document(`):
            GraphDocument(

# occurrences: 1 (verified: grep -c 'toolkit: Optional\["PageIndexToolkit"\] = None,' extractors/loader.py) — line 162
        toolkit: Optional["PageIndexer"] = None,
```
**Why**: `PlainTextLoader` output only ever flows into `LoaderExtractor`, which reads `.page_content` / `.metadata`. FILL IN: update docstrings at lines 89, 96 (":class:`Document`" → ":class:`GraphDocument`") and 150 (":class:`PageIndexToolkit`" → "a :class:`PageIndexer` such as ``PageIndexToolkit``") — bounded by Google-style docstring AC; leave other prose mentions.

### `packages/ai-parrot/src/parrot/loaders/graphindex.py` (CREATE — header + adapters)
```python
# FILL IN: module docstring — move old graphindex/loader.py lines 1-23 verbatim here (post-3264 wording).

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, List, Optional, Union

from parrot.embeddings.graphindex import GraphIndexEmbedder
from parrot.knowledge.graphindex.builder import GraphIndexBuilder
from parrot.knowledge.graphindex.meta_ontology import build_graphindex_ontology
from parrot.knowledge.graphindex.models import GraphDocument
from parrot.knowledge.graphindex.persist import GraphIndexPersistence
from parrot.knowledge.graphindex.schema import BuildResult, SourceConfig, UniversalEdge, UniversalNode
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.schema import TenantContext
from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document

__all__ = ["GraphIndexLoader", "from_graph_document", "to_graph_document"]


# FILL IN: paste old packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py lines 44-EOF
#          (_NullPersistence, _CapturingPersistence, GraphIndexLoader) VERBATIM here — bounded by
#          "pure move"; do not edit bodies (TASK-3264's _resolve_arango rewrite comes along as is).


def to_graph_document(document: Document) -> GraphDocument:
    """Convert a framework :class:`Document` into a :class:`GraphDocument`.

    Args:
        document: A ``parrot.stores.models.Document``.

    Returns:
        A ``GraphDocument`` carrying the same ``page_content`` and a copy of ``metadata``.
    """
    return GraphDocument(page_content=document.page_content, metadata=dict(document.metadata))


def from_graph_document(document: GraphDocument) -> Document:
    """Convert a :class:`GraphDocument` back into a framework :class:`Document`.

    Args:
        document: A graph-tree document.

    Returns:
        A ``parrot.stores.models.Document`` with the same ``page_content`` and a copy of ``metadata``.
    """
    return Document(page_content=document.page_content, metadata=dict(document.metadata))
```
**Why**: absolute imports replace the old relative `.builder`/`.embed`/… (the module is no longer inside `graphindex/`). Import `GraphIndexEmbedder` from the real module so `self.embedder = GraphIndexEmbedder(...)` (old line 173) and test monkeypatching hit the same global. `dict(...)` copies avoid aliasing (roundtrip test asserts equality, not identity).

### `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` (MODIFY — replace whole file)
```python
"""Backward-compatible shim for :class:`GraphIndexLoader` (FEAT-540).

``GraphIndexLoader`` is a framework :class:`~parrot.loaders.abstract.AbstractLoader`
and now lives in :mod:`parrot.loaders.graphindex`, keeping the graph tree free of
``parrot.loaders`` / ``parrot.stores`` imports. Old imports keep working lazily (PEP 562).
Monkeypatch ``parrot.loaders.graphindex`` — not this shim — in tests.
"""

from __future__ import annotations

from typing import Any

__all__ = ["GraphIndexLoader"]

_LAZY_ATTRS: dict[str, str] = {
    "GraphIndexLoader": "parrot.loaders.graphindex",
    "_NullPersistence": "parrot.loaders.graphindex",
    "_CapturingPersistence": "parrot.loaders.graphindex",
}


def __getattr__(name: str) -> Any:
    """Resolve a relocated name from :mod:`parrot.loaders.graphindex` on first access.

    Raises:
        AttributeError: If ``name`` was not relocated.
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

### `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"GraphIndexLoader": "parrot.knowledge.graphindex.loader",' __init__.py) — line 118
    "GraphIndexLoader": "parrot.loaders.graphindex",
```
Also update the comment at lines 113-116 to say the loader lives in `parrot.loaders.graphindex`.

### `packages/ai-parrot/tests/knowledge/graphindex/test_loader.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^import parrot.knowledge.graphindex.loader as loader_mod' test_loader.py) — line 17
import parrot.loaders.graphindex as loader_mod
from parrot.loaders.graphindex import (
    GraphIndexLoader,
    _NullPersistence,
)
# (replaces lines 17-21; keep lines 26-27 imports as they are)
```
Update the module docstring line 1 to name `parrot.loaders.graphindex.GraphIndexLoader`.

### FILL IN checklist
- [ ] `parrot/loaders/graphindex.py` docstring + verbatim body paste; bounded by "pure move".
- [ ] `extractors/loader.py` docstrings 89/96/150; bounded by Google-style docstrings AC.
- [ ] `test_graph_document.py::test_extractor_consumes_graph_documents` body; bounded by spec §4 Module 6.

---

## Addendum — repo-root `tests/` tree (review, 2026-09-15)

Note: the repo-root `tests/knowledge/wiki/` tree (run by CI) exercises the build path through `LoaderExtractor`/`PlainTextLoader` indirectly (`test_cli.py`, `test_cli_checkpoint.py`, `test_integration.py`). Run `pytest tests/knowledge/wiki/test_cli.py tests/knowledge/wiki/test_cli_checkpoint.py tests/knowledge/wiki/test_integration.py -v` after the `GraphDocument` switch.

---

## Acceptance Criteria

- [ ] `graphindex/extractors/loader.py` and `graphindex/loader.py` have no module-level import of `parrot.stores`, `parrot.loaders` or `parrot.knowledge.ontology.graph_store` (AST check).
- [ ] `from parrot.knowledge.graphindex.loader import GraphIndexLoader` and `from parrot.knowledge.graphindex import GraphIndexLoader` both return `parrot.loaders.graphindex.GraphIndexLoader`; `issubclass(GraphIndexLoader, AbstractLoader)`.
- [ ] `PlainTextLoader()._load(path)` returns `GraphDocument` instances.
- [ ] `to_graph_document` / `from_graph_document` round-trip `page_content` + `metadata` losslessly.
- [ ] In a clean subprocess, `import parrot.knowledge.graphindex.extractors.loader` leaves `parrot.stores` out of `sys.modules`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/ -v` and `pytest packages/ai-parrot-loaders/tests/test_ebook_structure.py packages/ai-parrot-loaders/tests/test_mobiloader.py -v` (they import `LoaderExtractor`).
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/ -q` passes (`wiki/documents.py` imports the extractor module).
- [ ] `ruff check` clean on changed files.
- [ ] Repo-root build-path tests pass: `pytest tests/knowledge/wiki/test_cli.py tests/knowledge/wiki/test_cli_checkpoint.py tests/knowledge/wiki/test_integration.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_graph_document.py
"""FEAT-540 Module 6 — GraphDocument + loader relocation (TASK-3266)."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.knowledge.graphindex.models import DocumentLoader, GraphDocument

_GI = Path(__file__).resolve().parents[3] / "src" / "parrot" / "knowledge" / "graphindex"


def test_graph_document_roundtrip():
    from parrot.loaders.graphindex import from_graph_document, to_graph_document
    from parrot.stores.models import Document

    original = Document(page_content="body", metadata={"source": "a.md", "n": 1})
    graph_doc = to_graph_document(original)
    assert isinstance(graph_doc, GraphDocument)
    back = from_graph_document(graph_doc)
    assert back.page_content == original.page_content
    assert back.metadata == original.metadata


def test_shim_resolves_relocated_loader():
    from parrot.knowledge.graphindex import GraphIndexLoader as via_pkg
    from parrot.knowledge.graphindex.loader import GraphIndexLoader as via_shim
    from parrot.loaders.abstract import AbstractLoader
    from parrot.loaders.graphindex import GraphIndexLoader as real

    assert via_shim is real and via_pkg is real
    assert issubclass(real, AbstractLoader)


@pytest.mark.parametrize("rel", ["extractors/loader.py", "loader.py"])
def test_no_framework_module_level_imports(rel):
    banned = ("parrot.stores", "parrot.loaders", "parrot.knowledge.ontology.graph_store")
    tree = ast.parse((_GI / rel).read_text())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(banned), ast.unparse(node)


def test_extractor_module_does_not_load_stores():
    code = "import sys, parrot.knowledge.graphindex.extractors.loader; print(int('parrot.stores' in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip().splitlines()[-1] == "0"


@pytest.mark.asyncio
async def test_plain_text_loader_returns_graph_documents(tmp_path):
    from parrot.knowledge.graphindex.extractors.loader import PlainTextLoader

    path = tmp_path / "a.md"
    path.write_text("# Title\n\nbody\n", encoding="utf-8")
    loader = PlainTextLoader()
    assert isinstance(loader, DocumentLoader)
    docs = await loader._load(path)
    assert len(docs) == 1 and isinstance(docs[0], GraphDocument)


@pytest.mark.asyncio
async def test_extractor_consumes_graph_documents(tmp_path):
    # FILL IN: run LoaderExtractor(toolkit=None).extract(...) over a PlainTextLoader-backed markdown file
    #          (mirror tests/knowledge/graphindex/test_loader_extractor.py) and assert DOCUMENT/SECTION nodes.
    ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 6 and Module 7, §2 Data Models).
2. **Check dependencies** — TASK-3257, TASK-3259, TASK-3264 must be `done` in `sdd/tasks/index/graphindex-core-seams.json`.
3. **Verify the Codebase Contract** — especially the post-3259/3264 anchors in `graphindex/loader.py`; update the contract if anything drifted.
4. **Update status** → `"in-progress"`.
5. **Implement** from the blueprint; complete every `FILL IN`.
6. **Run tests in the worktree** with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-loaders/src pytest ...` (the shared venv is editable against the main checkout; graphindex tests also rely on `tests/knowledge/graphindex/conftest.py` for compiled `.so` files).
7. Move this file to `sdd/tasks/completed/`, set index → `"done"`, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: `GraphIndexLoader` relocated to `parrot/loaders/graphindex.py` (spec Module 6 says "loader.py stops importing AbstractLoader" — the class itself must keep subclassing it, so it leaves the graph tree; `graphindex/loader.py` is a PEP 562 shim). This also resolves Module 7's `loader.py:34` `OntologyGraphStore` import.
