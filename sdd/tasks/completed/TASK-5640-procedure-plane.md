# TASK-5640: `ProcedurePlane` — fold specs into the wiki store

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5633, TASK-5639
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (plane half), design research S6 (reuse the source-slice and provenance
mechanisms, no store subclass) and spec rev 0.3 decision 5 (the store file is `wiki.db`). The plane
is a plain wiki store under `<shared-root>/.parrot/procedure/` plus the compiled index, which is
published **last** so a crash leaves the previous index (then read as stale).

---

## Scope

- Implement `ProcedurePlane` (`__init__`, `for_root`, `build`, `specs`) in `plane.py`.
- Add the plane tests to `test_index_plane.py`.

**NOT in scope**: the index functions (TASK-5639, used here); registering the plane as a wiki
namespace (operator step, documented by TASK-5652); the CLI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/plane.py` | CREATE | `ProcedurePlane` |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_index_plane.py` | MODIFY | Plane tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). Models and index functions come from TASK-5633 / TASK-5639.

### Verified Imports
```python
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, create_wiki_store   # wiki/store.py:1265, :606, :3288
from parrot.knowledge.wiki.project import find_shared_root                                    # wiki/project.py:1563
from parrot.knowledge.wiki.procedure.index import compile_index, publish_index                # TASK-5639
from parrot.knowledge.wiki.procedure.models import PLANE_DIR, ProbeCost, ProcedureSpec        # TASK-5633
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiPageRecord(BaseModel):                                   # :606
    concept_id: str; title: str = ""; category: str = "concept"; summary: str = ""; body: str = ""
    source_id: Optional[str] = None; origin: str = "ingest"; content_hash: Optional[str] = None
    attrs: dict[str, str] = Field(default_factory=dict)            # :656 — persisted with the page, replaces previous attrs
class SQLiteWikiStore(BaseWikiStore):                              # :1265
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False, ...) -> None   # :1317
    #   read_only=True raises FileNotFoundError when the file does not exist (:1336)
    async def add_edges(self, edges: list[tuple]) -> int           # :2370 — (src, dst, rel) or (src, dst, rel, provenance)
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord],
                                   edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]   # :2391
    #   deletes the source's pages, their attrs and every edge touching them, then inserts `pages`
    async def get_attrs(self, concept_id: str) -> dict[str, str]   # base default at :891; the SQLite store overrides it
    async def list_pages(self, category: Optional[str] = None, limit: int = 100, origin: Optional[list[str]] = None) -> list[dict[str, Any]]   # :941
    async def dump_pages(self) -> list[dict[str, Any]]             # :963 — every page, with body and source_id
    async def dump_edges(self) -> list[dict[str, Any]]             # :966 — src, dst, rel
def create_wiki_store(storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs) -> BaseWikiStore   # :3288
#   sqlite -> SQLiteWikiStore(Path(storage_dir) / "wiki.db", ...)   (:740)

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def find_shared_root(start: Path | None = None) -> Path | None    # :1563 — primary checkout, even from a linked worktree
```

### Does NOT Exist
- ~~A file named `procedure.db`~~ — the store file is `<plane_dir>/wiki.db` (rev 0.3 decision 5).
- ~~`create_wiki_store(..., read_only=True)`~~ — the sqlite factory takes no `read_only`; build
  `SQLiteWikiStore(plane_dir / "wiki.db", wiki_name="procedure", read_only=True)` for reads.
- ~~`replace_source_slice` carrying edge provenance~~ — its edges are 3-tuples; pass no edges to it
  and add all edges afterwards with `add_edges` 4-tuples.
- ~~A `close()` on the store~~ — connections are opened per operation; nothing to close.
- ~~A store subclass for this plane~~ — not needed and not wanted (S6).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/procedure/plane.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/procedure/test_index_plane.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.replace_source_slice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.add_edges",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- **Page per node**: `concept_id = spec.id`, `title = spec.title`, `category = "procedure"`,
  `origin = "ingest"`, `source_id = "procedure:" + spec.origin_path`, `summary = spec.advice or
  spec.command`, `body` = a short readable rendering (title, mode, command, the non-empty lists,
  then `spec.body`), `content_hash` = sha1 of `spec.model_dump_json()`.
- **Attrs**: `{"spec": spec.model_dump_json(), "mode": spec.mode, "kind": spec.kind,
  "scope_kind": spec.scope_kind, "source": spec.source}` set on the `WikiPageRecord` (`attrs`), so
  they are written in the same transaction as the page.
- **Build order**: (1) group specs by `origin_path`; (2) for every source id present in the store
  but not in this build, `replace_source_slice(source_id, [])`; (3) one
  `replace_source_slice(source_id, pages)` per source; (4) `add_edges` with every
  `(src, dst, rel, provenance)` where `provenance` is the producer prefix of `src`
  (`"sdd"`, `"skill"`); (5) `publish_index(...)` — last.
- `specs()` reads with a read-only handle and rebuilds each `ProcedureSpec` from the `spec` attr,
  sorted by id; it returns `[]` when the store file does not exist.
- Only pages whose `source_id` starts with `"procedure:"` are ever removed in step (2).
- Tests are `async` (`pytest-asyncio`; check how sibling tests under
  `packages/ai-parrot/tests/knowledge/wiki/schema/` mark them and do the same).

---

## Implementation Blueprint

### Steps (in order)
1. Write the page rendering helpers — *why*: `build` and the tests share the id/source conventions.
2. Write `build` in the order of the Implementation Notes — *why*: the index must be the last
   thing published.
3. Write `specs` and `for_root`.
4. Add the plane tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/plane.py` (CREATE)
```python
"""The procedure plane: a wiki store plus the compiled index under <shared-root>/.parrot/procedure (FEAT-891)."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

from parrot.knowledge.wiki.procedure.index import compile_index, publish_index
from parrot.knowledge.wiki.procedure.models import PLANE_DIR, ProbeCost, ProcedureSpec
from parrot.knowledge.wiki.project import find_shared_root
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, create_wiki_store

STORE_FILE = "wiki.db"
WIKI_NAME = "procedure"
SOURCE_PREFIX = "procedure:"
CATEGORY = "procedure"


def _page(spec: ProcedureSpec) -> WikiPageRecord:
    """The wiki page of one node (see the task's Implementation Notes)."""
    # FILL IN


class ProcedurePlane:
    """wiki.db + procedures.json under ``<shared-root>/.parrot/procedure``."""

    def __init__(self, plane_dir: Path) -> None:
        self.plane_dir = Path(plane_dir)
        self.logger = logging.getLogger(__name__)

    @classmethod
    def for_root(cls, start: Path | None = None) -> "ProcedurePlane | None":
        """Plane of the shared root (find_shared_root); None outside a repository."""
        root = find_shared_root(start)
        return cls(root / PLANE_DIR) if root is not None else None

    async def build(self, specs: Sequence[ProcedureSpec], sources: Sequence[Path], *, root: Path,
                    probe_costs: Mapping[str, ProbeCost]) -> dict[str, int]:
        """Rebuild the store, then publish the index last. Returns {'pages', 'edges', 'sources'}."""
        store = create_wiki_store(storage_dir=self.plane_dir, wiki_name=WIKI_NAME)
        # FILL IN: steps (1)-(4) of the Implementation Notes "Build order", counting pages and edges.
        publish_index(self.plane_dir, compile_index(specs, sources, root=root, probe_costs=probe_costs))
        self.logger.info("procedure plane built: %d pages, %d edges", pages, edges)
        return {"pages": pages, "edges": edges, "sources": len(sources)}

    async def specs(self) -> list[ProcedureSpec]:
        """Read every node back from the store (read-only handle); [] when no store exists."""
        db_path = self.plane_dir / STORE_FILE
        if not db_path.is_file():
            return []
        store = SQLiteWikiStore(db_path, wiki_name=WIKI_NAME, read_only=True)
        # FILL IN: list_pages(category=CATEGORY, limit=<large enough>), get_attrs(concept_id)["spec"],
        # ProcedureSpec.model_validate_json; skip a page without the attr; sort by id.
```
**Why this shape**: signatures are fixed by spec §3 M4. Putting the whole spec JSON in one attr
makes `specs()` an exact round trip, so the resolver never depends on how the body is rendered.
Edges go through `add_edges` because only that call accepts a provenance.

### `packages/ai-parrot/tests/knowledge/wiki/procedure/test_index_plane.py` (MODIFY)
```python
# Append at the end of the file TASK-5639 created. Anchor (re-verify): `def test_index_contract(tmp_path: Path) -> None:`
# occurrences: 1 expected (verify: grep -c 'def test_index_contract' packages/ai-parrot/tests/knowledge/wiki/procedure/test_index_plane.py)
# Add `from parrot.knowledge.wiki.procedure.plane import ProcedurePlane` to the imports.

async def test_plane_build_idempotent(tmp_path: Path) -> None:
    """Two builds give the same pages and edges; a removed source drops its slice."""
    # FILL IN: (tmp_path / ".git").mkdir(); two source files with one spec each (origin_path set), one
    # `requires` edge between them; build twice and compare sorted dump_pages ids and dump_edges;
    # rebuild with only the first source -> the second node's page is gone.


async def test_plane_specs_round_trip(tmp_path: Path) -> None:
    """specs() returns exactly the specs that were built, sorted by id."""
    # FILL IN


async def test_plane_publishes_index_last(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure while writing the store leaves no new index."""
    # FILL IN: make the store's add_edges raise (monkeypatch SQLiteWikiStore.add_edges); build raises;
    # read_index(plane_dir) is None.


def test_for_root_uses_shared_root(tmp_path: Path) -> None:
    """for_root resolves <root>/.parrot/procedure for a repository and its subdirectories."""
    # FILL IN: (tmp_path / "repo" / ".git").mkdir(parents=True); for_root(repo / "sub").plane_dir == repo / PLANE_DIR
```

### FILL IN checklist
- [ ] `plane.py::_page`, `ProcedurePlane.build`, `ProcedurePlane.specs` — bounded by the Implementation Notes
- [ ] `test_index_plane.py` — four test bodies

---

## Acceptance Criteria

- [ ] `build` is idempotent: two runs leave the same pages and edges.
- [ ] A source that is no longer built loses its pages; pages of other origins are never removed.
- [ ] `procedures.json` is published after the store writes; a store failure leaves no new index.
- [ ] `specs()` round-trips every `ProcedureSpec` and returns `[]` when no store exists.
- [ ] Edges carry the producer name as provenance.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_index_plane.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5633 and TASK-5639 are `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`; never change a signature the blueprint fixes.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5640 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note


- Task: TASK-5640
- Feature: procedural-graph-plane
- Implementation SHA: b54f1ffba13f41f513afab01da6c32a823b4a411
- Closed at (UTC): 2026-11-13T22:16:47+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 319.3s · Tokens: n/a |
