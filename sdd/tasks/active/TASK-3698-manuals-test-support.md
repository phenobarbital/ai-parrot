# TASK-3698: Promote contracts test doubles to tests/knowledge/_support + manuals conftest fixtures

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §4 "Test Data / Fixtures" and §7 "Patterns to Follow" (*Contracts test doubles … copied into
`tests/knowledge/_support/` — never imported from `tests.knowledge.contracts.test_*`*). Every manuals test
module (TASK-3699 onward) needs the same in-memory graph store, scripted LLM adapter, fake PageIndex indexer,
fake file manager and synthetic PDFs. This task creates them once, in a shared, importable support package, and
exposes them as fixtures from `tests/knowledge/manuals/conftest.py`.

**Exclusive** (`parallel: false`): it creates `packages/ai-parrot/tests/knowledge/manuals/conftest.py`, which every
later manuals test module loads.

---

## Scope

- Create `tests/knowledge/_support/` with: `graph.py` (`FakeGraphStore`, `FakeUpsertResult`, `FakeTenantManager`),
  `adapter.py` (`FakeAdapter`, `FakeIndexer`), `files.py` (`FakeFileManager`), `pdfs.py` (synthetic PDF builders).
- `FakeGraphStore` = the contracts double **plus** `query_documents`, `execute_traversal`, `upsert_document`,
  `get_document` in-memory equivalents (tips relink and retrieval need them).
- Create `tests/knowledge/manuals/__init__.py` and `conftest.py` exposing fixtures `manual_pdf`, `manual_pdf_rev_b`,
  `image_only_pdf`, `fake_graph_store`, `fake_adapter`, `fake_file_manager`, `fake_indexer_factory`, `frozen_now`.
- Write `test_support_smoke.py` proving each double/fixture works.

**NOT in scope**: any production code; the `InMemoryManualCatalog` double (TASK-3702 creates
`_support/catalog.py`); the `request_context` fixture (it needs `parrot_tools.procedures.RequestContext` and lives
in `ai-parrot-tools/tests/procedures/_doubles.py`, TASK-3720). Do **not** edit
`tests/knowledge/contracts/*` — copy, do not move.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/_support/__init__.py` | CREATE | Support package marker + docstring |
| `packages/ai-parrot/tests/knowledge/_support/graph.py` | CREATE | FakeGraphStore / FakeUpsertResult / FakeTenantManager |
| `packages/ai-parrot/tests/knowledge/_support/adapter.py` | CREATE | FakeAdapter (scripted ask_structured / ask_to_image) + FakeIndexer |
| `packages/ai-parrot/tests/knowledge/_support/files.py` | CREATE | FakeFileManager (upload/get_file_url/download) |
| `packages/ai-parrot/tests/knowledge/_support/pdfs.py` | CREATE | build_manual_pdf / build_manual_pdf_rev_b / build_image_only_pdf |
| `packages/ai-parrot/tests/knowledge/manuals/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot/tests/knowledge/manuals/conftest.py` | CREATE | Fixtures wrapping `_support` |
| `packages/ai-parrot/tests/knowledge/manuals/test_support_smoke.py` | CREATE | Smoke tests for every double |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest                                            # pytest-asyncio asyncio_mode = "auto" (packages/ai-parrot/pyproject.toml:1015)
from pathlib import Path
from typing import Any, Optional
from parrot.knowledge.pageindex.content_store import NodeContentStore   # used by FakeIndexer, tests/knowledge/contracts/test_ingestion.py:55
from parrot.knowledge.pageindex.store import JSONTreeStore              # tests/knowledge/contracts/test_ingestion.py:56
pymupdf = pytest.importorskip("pymupdf")                 # pattern: tests/knowledge/contracts/conftest.py:193 (pymupdf 1.27.1 in venv)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py  (copy source)
class UpsertResult:            # :32-38  inserted/updated/unchanged
class FakeGraphStore:          # :41-124  nodes/edges/fail_on/swallow_writes; upsert_nodes :55, get_all_nodes :71 (hides _active False),
                               #   soft_delete_nodes :76, create_edges :82 (UPSERT on (_from,_to), NEVER updates props), get_all_edges :94,
                               #   edges_incident :99 (source_id/target_id), remove_edge_by_triple :104; helpers edge_pairs :119, active_keys :122
class FakeTenantManager:       # :125-146  resolve(tenant_id, domain) -> ctx with ontology.entities
# packages/ai-parrot/tests/knowledge/contracts/test_carding.py
class FakeAdapter:             # :95-125  calls/prompts/system_prompts/fail_*; async ask_structured(prompt, output_type, temperature=0.0, system_prompt=None)
# packages/ai-parrot/tests/knowledge/contracts/test_ingestion.py
class FakeIndexer:             # :46-115  create_tree :64, insert_markdown :71 (splits on #/## headings, node ids f"{n:04d}"), get_tree :107, delete_tree :110
# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py  (real API the fake mirrors)
async def execute_traversal(self, ctx, aql, bind_vars=None, collection_binds=None) -> list[dict]   # :271
async def get_document(self, ctx, collection, key) -> Optional[dict[str, Any]]   # :598-603
async def upsert_document(self, ctx, collection, doc: dict[str, Any]) -> None   # :622-627
async def query_documents(self, ctx, collection, filters=None, sort_desc=None, limit=None) -> list[dict]   # :697-736 ANDed equality filters
# navigator FileManagerInterface (.venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py)
async def get_file_url(self, path: str, expiry: int = 3600) -> str                          # :67
async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata   # :79
async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path      # :93
```

### Does NOT Exist
- ~~Shared doubles in `tests/knowledge/contracts/conftest.py`~~ — that conftest only holds corpora/live gates; the doubles live inside test modules (spec F007). Never `from ..contracts.test_graph_loader import …`.
- ~~`tests/knowledge/_support/`~~ — created here.
- ~~A `FakeGraphStore.execute_traversal` in contracts~~ — the contracts double has none; this task adds a *scriptable* one (returns rows registered per AQL substring), it does not interpret AQL.
- ~~`FileMetadata` construction requirements~~ — the fake may return a `SimpleNamespace(path=destination, …)`; do not import navigator in the fake.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/_support/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/_support/graph.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/_support/adapter.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/_support/files.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/_support/pdfs.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/conftest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_support_smoke.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py#FakeGraphStore",
    "sym:packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py#FakeTenantManager",
    "sym:packages/ai-parrot/tests/knowledge/contracts/test_carding.py#FakeAdapter",
    "sym:packages/ai-parrot/tests/knowledge/contracts/test_ingestion.py#FakeIndexer",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.query_documents",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.execute_traversal"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Fakes must reproduce the two real-store behaviours loaders work around: `create_edges` never updates properties of
  an existing `(_from,_to)` edge, and `get_all_nodes` hides soft-deleted vertices (spec §7 "Edge collapse").
- `FakeAdapter` is **domain-agnostic**: script responses by `output_type` and by a key extracted from the prompt via
  an injectable callable (default: the `"Section node: <id>"` convention) — manuals carding prompts will use it.
  It also offers `ask_to_image(prompt, image, structured_output=None, **kw)` so figure tests can reuse it.
- Synthetic PDFs (spec §4): `manual_pdf` = 6 pages: cover, parts table, one assembly procedure with 5 numbered steps,
  two images with captions `Fig. 1` / `Fig. 2` directly below them, one `WARNING` hazard box. `manual_pdf_rev_b` =
  same with step 3 renumbered (source identity kept), step 4 reworded, step 5 removed. `image_only_pdf` = drawn rect,
  no text. Embed images with `page.insert_image(rect, stream=png_bytes)`; build `png_bytes` from a
  `pymupdf.Pixmap` (`tobytes("png")`) so no binary fixture file is committed.
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`.
- Test helpers still get docstrings and type hints; no `print`.

---

## Implementation Blueprint

### Steps (in order)
1. Copy `FakeGraphStore`/`UpsertResult`/`FakeTenantManager` into `_support/graph.py`, rename `UpsertResult` → `FakeUpsertResult` — *why*: avoid shadowing the real `UpsertResult` name in test namespaces.
2. Add document helpers and scripted `execute_traversal` to the fake — *why*: tips (TASK-3710) and graph-loader verify paths call them.
3. Copy `FakeAdapter`/`FakeIndexer` into `_support/adapter.py`, generalising the adapter's scripting — *why*: manuals drafts differ from contracts drafts.
4. Write `FakeFileManager` and the PDF builders — *why*: figures/export/library tests need storage keys and real PDFs.
5. Write the manuals `conftest.py` and smoke tests.

### `packages/ai-parrot/tests/knowledge/_support/graph.py` (CREATE)
```python
"""In-memory OntologyGraphStore double shared by knowledge test suites (FEAT-601).

Promoted copy of ``tests/knowledge/contracts/test_graph_loader.py:32-146``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


class FakeUpsertResult:
    """Mimics ``OntologyGraphStore.upsert_nodes``'s return value."""

    def __init__(self, inserted: int = 0, updated: int = 0) -> None:
        self.inserted = inserted
        self.updated = updated
        self.unchanged = 0


class FakeGraphStore:
    """In-memory graph store: edges upsert on (_from,_to) and never update; soft-deleted nodes are hidden."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, dict[str, Any]]] = {}
        self.edges: dict[str, list[dict[str, Any]]] = {}
        self.fail_on: set[str] = set()
        self.swallow_writes: set[str] = set()
        self.traversals: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self._traversal_rows: list[tuple[str, Callable[[dict[str, Any]], list[dict[str, Any]]]]] = []

    # FILL IN: copy upsert_nodes / get_all_nodes / soft_delete_nodes / create_edges / get_all_edges /
    #   edges_incident / remove_edge_by_triple / edge_pairs / active_keys verbatim from
    #   contracts/test_graph_loader.py:55-124 (use FakeUpsertResult) — bounded by "same observable semantics"

    async def query_documents(self, ctx: Any, collection: str, filters: Optional[dict[str, Any]] = None,
                              sort_desc: Optional[str] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """ANDed equality filters over vertex AND edge buckets, like graph_store.py:697."""
        # FILL IN: search nodes[collection] values then edges[collection]; hide _active False; apply sort/limit

    async def get_document(self, ctx: Any, collection: str, key: str) -> Optional[dict[str, Any]]:
        """Return one vertex by key or None."""
        return self.nodes.get(collection, {}).get(key)

    async def upsert_document(self, ctx: Any, collection: str, doc: dict[str, Any]) -> None:
        """Insert/replace a vertex by ``_key`` (real store returns None, graph_store.py:622-627)."""
        # FILL IN: store under doc["_key"]; default _active True

    def script_traversal(self, contains: str, rows: Callable[[dict[str, Any]], list[dict[str, Any]]]) -> None:
        """Register rows returned by execute_traversal when the AQL contains ``contains``."""
        self._traversal_rows.append((contains, rows))

    async def execute_traversal(self, ctx: Any, aql: str, bind_vars: Optional[dict[str, Any]] = None,
                                collection_binds: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
        """Record the call and return the first scripted match (empty list otherwise)."""
        # FILL IN: append to self.traversals; first matching script wins


class FakeTenantManager:
    """Resolves a context whose ontology carries the requested entities (default: procedures domain)."""

    def __init__(self, entities: tuple[str, ...] = ("Procedure", "Step", "Media", "Tip")) -> None:
        self.entities = entities
        self.calls: list[tuple[str, Optional[str]]] = []

    def resolve(self, tenant_id: str, domain: Optional[str] = None) -> Any:
        # FILL IN: copy contracts/test_graph_loader.py:132-146 body — bounded by same ctx attributes
        ...
```

### `packages/ai-parrot/tests/knowledge/_support/adapter.py` (CREATE)
```python
"""Scripted LLM adapter and fake PageIndex indexer shared by knowledge tests (FEAT-601)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional


def section_node_key(prompt: str) -> Optional[str]:
    """Default script key: the id after ``Section node: `` in a prompt, else None."""
    # FILL IN: mirror contracts/test_carding.py:121 parsing without raising on absence


class FakeAdapter:
    """Counts structured calls and replays scripted outputs by (output_type, key)."""

    def __init__(self, *, key_of: Callable[[str], Optional[str]] = section_node_key) -> None:
        self.key_of = key_of
        self.scripts: dict[tuple[type, Optional[str]], Any] = {}
        self.defaults: dict[type, Callable[[], Any]] = {}
        self.calls: list[tuple[str, type]] = []
        self.prompts: list[str] = []
        self.system_prompts: list[Optional[str]] = []
        self.image_calls: list[tuple[str, Any, Any]] = []
        self.fail_types: set[type] = set()
        self.fail_keys: set[str] = set()

    def script(self, output_type: type, value: Any, *, key: Optional[str] = None) -> None:
        """Register the value returned for ``output_type`` (optionally only for one prompt key)."""
        self.scripts[(output_type, key)] = value

    async def ask_structured(self, prompt: str, output_type: type, temperature: float = 0.0,
                             system_prompt: Optional[str] = None) -> Any:
        """Replay: keyed script, then unkeyed script, then defaults[output_type](), else output_type()."""
        # FILL IN: record call; raise RuntimeError("model unavailable") for fail_types/fail_keys

    async def ask_to_image(self, prompt: str, image: Any, *, structured_output: Any = None, **kwargs: Any) -> Any:
        """Vision double: returns a scripted structured_output instance or an object with ``.output`` text."""
        # FILL IN: record in image_calls; reject str URLs with ValueError (spec F023: Path/bytes only)


_HEADING = re.compile(r"^##?\s+(.*)$")


class FakeIndexer:
    """Minimal PageIndex tree builder over a real NodeContentStore (copy of contracts test_ingestion.py:46-115)."""
    # FILL IN: copy verbatim (imports of NodeContentStore/JSONTreeStore stay inside __init__)
```

### `packages/ai-parrot/tests/knowledge/_support/files.py` (CREATE)
```python
"""FileManagerInterface double (navigator-api 4.0.0 shape) for figure/export tests (FEAT-601)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO, Union


class FakeFileManager:
    """upload_file stores bytes by key; get_file_url returns https://fake/<key>?expiry=<n>; download_file writes bytes."""

    def __init__(self, *, scheme: str = "https") -> None:
        self.scheme = scheme
        self.objects: dict[str, bytes] = {}
        self.url_calls: list[tuple[str, int]] = []
        self.missing: set[str] = set()

    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> Any:
        # FILL IN: read bytes from Path or file object; store; return SimpleNamespace(path=destination, size=len(data))
        ...

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        # FILL IN: record (path, expiry); scheme "file" → f"file:///{path}" (to exercise MediaUnavailable)
        ...

    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:
        # FILL IN: FileNotFoundError for keys in self.missing or absent; write bytes; return Path
        ...
```

### `packages/ai-parrot/tests/knowledge/_support/pdfs.py` (CREATE)
```python
"""Synthetic manual PDFs built with pymupdf at test time (FEAT-601 §4)."""

from __future__ import annotations

from pathlib import Path

STEPS_REV_A: tuple[str, ...] = (
    "1. Remove the four M6 bolts from the base plate.",
    "2. Lift the cover and set it aside.",
    "3. Insert the drive belt around the pulley. See Fig. 1.",
    "4. Torque the tensioner bolt to 12 Nm.",
    "5. Reinstall the cover. See Fig. 2.",
)


def _png(width: int = 120, height: int = 80) -> bytes:
    """Solid-colour PNG bytes generated with pymupdf.Pixmap."""
    # FILL IN: import pymupdf lazily; Pixmap(csRGB, IRect(0,0,w,h), 0); clear_with(180); tobytes("png")


def build_manual_pdf(path: Path, *, steps: tuple[str, ...] = STEPS_REV_A) -> Path:
    """6 pages: cover, parts table, assembly procedure (numbered steps), Fig. 1/Fig. 2 images with captions below, WARNING box."""
    # FILL IN: layout per Implementation Notes — captions placed just below each image bbox


def build_manual_pdf_rev_b(path: Path) -> Path:
    """Rev B: step 3 renumbered, step 4 reworded, step 5 removed."""
    # FILL IN: derive steps from STEPS_REV_A and call build_manual_pdf


def build_image_only_pdf(path: Path) -> Path:
    """One page, a filled rectangle, no text (copy of contracts/conftest.py:209-221)."""
    # FILL IN
```

### `packages/ai-parrot/tests/knowledge/manuals/conftest.py` (CREATE)
```python
"""Fixtures for the manuals suites (FEAT-601). Doubles live in tests/knowledge/_support."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from .._support.adapter import FakeAdapter, FakeIndexer
from .._support.files import FakeFileManager
from .._support.graph import FakeGraphStore
from .._support.pdfs import build_image_only_pdf, build_manual_pdf, build_manual_pdf_rev_b

FROZEN_NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def frozen_now() -> datetime:
    return FROZEN_NOW


@pytest.fixture()
def manual_pdf(tmp_path: Path) -> Path:
    pytest.importorskip("pymupdf")
    return build_manual_pdf(tmp_path / "manuals" / "model-x-rev-a.pdf")

# FILL IN: manual_pdf_rev_b, image_only_pdf, fake_graph_store, fake_adapter, fake_file_manager,
#   fake_indexer_factory (returns a factory(storage_dir, adapter) -> FakeIndexer, caching instances by dir)
```

### FILL IN checklist
- [ ] `graph.py` — verbatim copies + `query_documents` / `upsert_document` / `execute_traversal`
- [ ] `adapter.py` — replay order, failure injection, URL rejection in `ask_to_image`, FakeIndexer copy
- [ ] `files.py` — three async methods
- [ ] `pdfs.py` — three builders, captions directly under image bboxes
- [ ] `conftest.py` — remaining fixtures
- [ ] `test_support_smoke.py` — tests below

---

## Acceptance Criteria

- [ ] `from .._support.graph import FakeGraphStore` works from `tests/knowledge/manuals/*`
- [ ] `FakeGraphStore.create_edges` never updates an existing `(_from,_to)` edge; soft-deleted nodes are hidden
- [ ] `manual_pdf` opens with pymupdf, has 6 pages, 2 images, and text `Fig. 1` / `Fig. 2` below the images
- [ ] `image_only_pdf` has no extractable text
- [ ] No file under `tests/knowledge/contracts/` modified; no import from `tests.knowledge.contracts.test_*`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_support_smoke.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_support_smoke.py
import pytest


async def test_create_edges_never_updates(fake_graph_store):
    await fake_graph_store.create_edges(None, "has_step", [{"_from": "p/1", "_to": "s/1", "order": 1}])
    await fake_graph_store.create_edges(None, "has_step", [{"_from": "p/1", "_to": "s/1", "order": 9}])
    assert fake_graph_store.edges["has_step"][0]["order"] == 1


async def test_query_documents_filters(fake_graph_store):
    ...


async def test_scripted_traversal(fake_graph_store):
    ...


async def test_fake_adapter_replays_by_type_and_key(fake_adapter):
    ...


async def test_fake_file_manager_roundtrip(fake_file_manager, tmp_path):
    ...


def test_manual_pdf_has_images_and_captions(manual_pdf):
    pymupdf = pytest.importorskip("pymupdf")
    ...


def test_image_only_pdf_has_no_text(image_only_pdf):
    ...
```

---

## Agent Instructions

1. Read spec §4 (fixtures) and §7 (patterns).
2. Re-verify the copy-source line ranges above before copying.
3. Update the per-spec index status → `in-progress`.
4. Implement from the blueprint; complete every `# FILL IN:`.
5. Run the Validation Commands with the worktree `PYTHONPATH`.
6. Move this file to `sdd/tasks/completed/`, update the index → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
