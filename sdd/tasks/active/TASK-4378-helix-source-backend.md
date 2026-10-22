# TASK-4378: HelixSourceBackend — source manifest on HelixDB

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4376
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G1, AC2): `SourceCollectionManager` persists the source manifest through FEAT-540's
source-backend registry (`wiki/sources_backend.py`). This task implements the HelixDB backend: the eleven
manifest operations over `Source` nodes stored in the **same database as the wiki plane**
(`wiki_<wiki_name>`), so `HelixWikiStore.orphan_sources()` / `broken_edges()` / `stats()["sources"]`
(TASK-4376) see them. Registration of the `"helixdb"` row is TASK-4392.

**Spec drift (FEAT-540 real code)**: the spec says `HelixSourceBackend` "satisfies `SourceManifestBackend`
structurally". On dev, `SourceManifestBackend` is a **synchronous** Protocol and network backends
implement the async twin `AsyncSourceManifestBackend`, wrapped in `AsyncSourceBackendBridge` at
registration (precedent: `_create_arango_backend`, `sources_backend.py:394-400`). This task therefore
implements `AsyncSourceManifestBackend`; TASK-4392's registry row wraps it in the bridge.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/helix_sources.py` with `HelixSourceBackend`
  implementing all eleven `AsyncSourceManifestBackend` operations over `Source` nodes, constructed from
  either `settings: HelixSettings` (opens its own client lazily) or `store: HelixWikiStore` (re-uses the
  store's client, `initialize()` lazily — mirrors `ArangoSourceBackend(arango_db=…, arango_store=…)`).
- Bootstrap through the store's `WIKI_PLANE` (the `Source` label lives there — TASK-4376's `SOURCE_LABEL`).
- Write `packages/ai-parrot/tests/knowledge/wiki/test_helix_sources.py`: async parity + the bridged sync API.

**NOT in scope**: `register_source_backend("helixdb", …)` (TASK-4392); any edit to `sources.py` or
`sources_backend.py`; wiring `LLMWikiToolkit`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/helix_sources.py` | CREATE | `HelixSourceBackend` (async manifest backend) |
| `packages/ai-parrot/tests/knowledge/wiki/test_helix_sources.py` | CREATE | Parity tests (async + bridged sync) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.models import SourceManifestEntry  # verified: wiki/models.py:168
from parrot.knowledge.wiki.sources_backend import AsyncSourceManifestBackend, AsyncSourceBackendBridge, SourceManifestBackend  # verified: wiki/sources_backend.py:65, :297, :48
# Created upstream (not on dev yet):
from parrot.knowledge.wiki.helix_store import HelixWikiStore, WIKI_PLANE, SOURCE_LABEL  # TASK-4376
from parrot.knowledge.helix.settings import HelixSettings, HelixMode  # TASK-4372
from parrot.knowledge.helix.client import HelixClient, open_helix_client, _sdk  # TASK-4373 (_sdk().write_batch()/read_batch())
from parrot.knowledge.helix.bootstrap import ensure_plane  # TASK-4374
from parrot.knowledge.helix import dsl as hdsl  # TASK-4374
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py
@runtime_checkable
class AsyncSourceManifestBackend(Protocol):                                  # line 65
    async def upsert(self, entry: SourceManifestEntry) -> None
    async def upsert_many(self, entries: list[SourceManifestEntry]) -> None
    async def list_sources(self) -> list[SourceManifestEntry]
    async def get_source(self, source_id: str) -> SourceManifestEntry | None
    async def remove_source(self, source_id: str) -> bool
    async def find_id_by_uri(self, source_uri: str) -> str | None
    async def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None
    async def find_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]
    async def find_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]
    async def find_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]
    async def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]
class AsyncSourceBackendBridge:   # line 297; __init__(self, backend) captures the running loop (:315)
def _create_arango_backend(**options: Any) -> SourceManifestBackend   # line 394 — registration precedent
# SQLite semantics to mirror: SqliteSourceBackend :112 — list_sources ORDER BY rowid (insertion order);
#   find_by_external_ids skips None external_id (:196); list_by_external_prefix is a literal prefix (:200)
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class SourceManifestEntry(BaseModel):   # line 168 — source_id, source_uri, file_hash, mtime, ingested_at, pages_generated,
                                        #   status, destination, decision_source, charter_version, composite_score,
                                        #   doc_metadata, content_type, loader, external_id
# packages/ai-parrot/src/parrot/knowledge/wiki/arango_sources.py
class ArangoSourceBackend:  # line 12 — __init__(*, arango_db=None, arango_store=None) raises ValueError when both None (:15-23)
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py — SourceCollectionManager.__init__ :108 passes ONLY
#   manager=, arango_db=, arango_store= to create_source_backend (:157-162)
```

### Does NOT Exist
- ~~`HelixSourceBackend` as a synchronous `SourceManifestBackend`~~ — it is async; the bridge provides sync.
- ~~A `helix_settings` / `helix_store` kwarg on `SourceCollectionManager.__init__`~~ — not on dev (see Implementation Notes → drift for TASK-4392).
- ~~`register_source_backend("helixdb", …)` on dev~~ — TASK-4392.
- ~~A HelixDB `LIKE`/prefix predicate~~ — not in the wheel-verified DSL list; filter prefixes client-side.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/helix_sources.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_helix_sources.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py#AsyncSourceManifestBackend",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py#AsyncSourceBackendBridge",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py#SourceManifestBackend",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#SourceManifestEntry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/arango_sources.py#ArangoSourceBackend"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `Source` node props = `entry.model_dump(mode="json")` + `seq` (monotonic insertion counter, so
  `list_sources()` returns insertion order like SQLite's `ORDER BY rowid`); `doc_metadata` / `pages_generated`
  stored as JSON strings if the DSL rejects nested values (decide once, document in a comment).
  `upsert` keeps the original `seq` on update.
- One batch per write (`upsert_many` = one batch). `remove_source` returns whether a node was dropped.
- Equality-index lookups for `source_id`, `source_uri`, `external_id`; batch lookups (`find_by_*`) issue
  ONE read batch for the whole list. Prefix search reads `Source` nodes with a non-null `external_id`
  and filters `startswith(prefix)` client-side, sorted by `seq`.
- Event-loop rule: `AsyncSourceBackendBridge` runs coroutines either on the loop captured at construction
  or on a fresh worker loop. A server-mode client is loop-bound, so when constructed from `settings` the
  backend opens its client lazily **on first use** and never shares it across loops (track the loop it was
  opened on; reopen when `asyncio.get_running_loop()` differs). When built from `store`, it uses
  `store._c()` (same loop rule as `ArangoSourceBackend._resolve_arango_db`).
- **Drift to report for TASK-4392 (registration owner)**: `SourceCollectionManager` forwards only
  `manager` / `arango_db` / `arango_store` to the factory, so a `"helixdb"` row cannot receive settings
  without either (a) a generic options passthrough in `sources.py` or (b) the factory resolving settings
  from `options["manager"]` (e.g. its `sources_dir` → project config). Do not edit `sources.py` here;
  record the choice needed in the Completion Note.

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-4376's `SOURCE_LABEL` / `WIKI_PLANE` / `HelixWikiStore._c` names — *why*: re-used verbatim.
2. Write the backend; then tests (direct async + bridge) — *why*: AC2 parity evidence.

### `packages/ai-parrot/src/parrot/knowledge/wiki/helix_sources.py` (CREATE)
```python
"""HelixDB source-manifest backend (FEAT-670 M3) — async; registered wrapped in AsyncSourceBackendBridge."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from parrot.knowledge.helix import dsl as hdsl
from parrot.knowledge.helix.bootstrap import ensure_plane
from parrot.knowledge.helix.client import HelixClient, _sdk, open_helix_client
from parrot.knowledge.helix.settings import HelixSettings
from parrot.knowledge.wiki.helix_store import WIKI_PLANE, HelixWikiStore
from parrot.knowledge.wiki.models import SourceManifestEntry

_JSON_FIELDS = ("pages_generated", "doc_metadata")


class HelixSourceBackend:
    """Persist source-manifest entries as ``Source`` nodes in the wiki's HelixDB database."""

    def __init__(self, settings: Optional[HelixSettings] = None, *, store: Optional[HelixWikiStore] = None) -> None:
        if settings is None and store is None:
            raise ValueError("HelixSourceBackend requires either settings or store (a HelixWikiStore)")
        self._settings = settings
        self._store = store
        self._client: Optional[HelixClient] = None
        self._client_loop: Optional[asyncio.AbstractEventLoop] = None
        self.logger = logging.getLogger(__name__)

    async def _c(self) -> HelixClient:
        """Return a client bound to the running loop (store's client when built from a store)."""
        if self._store is not None:
            return await self._store._c()
        loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not loop:
            assert self._settings is not None
            self._client = await open_helix_client(self._settings)
            self._client_loop = loop
            if not self._settings.read_only:
                await ensure_plane(self._client, WIKI_PLANE)
        return self._client

    @staticmethod
    def _to_props(entry: SourceManifestEntry) -> dict[str, Any]:
        """Node properties for one entry (nested fields JSON-encoded)."""
        props = entry.model_dump(mode="json")
        for key in _JSON_FIELDS:
            props[key] = json.dumps(props.get(key))
        return props

    @staticmethod
    def _from_props(props: dict[str, Any]) -> SourceManifestEntry:
        """Decode one Source node back into an entry."""
        data = {k: v for k, v in props.items() if k in SourceManifestEntry.model_fields}
        for key in _JSON_FIELDS:
            if isinstance(data.get(key), str):
                data[key] = json.loads(data[key])
        if data.get("pages_generated") is None:
            data["pages_generated"] = []
        return SourceManifestEntry(**data)

    async def upsert(self, entry: SourceManifestEntry) -> None:
        await self.upsert_many([entry])

    async def upsert_many(self, entries: list[SourceManifestEntry]) -> None:
        if not entries:
            return
        client = await self._c()
        # FILL IN: one batch (_sdk().write_batch()); upsert_node_entries("Source", "source_id", props) per entry, assigning `seq` only on the
        #          insert branch (next value from a Meta counter "sources_seq" read-increment-written in the same batch)
        #          — bounded by insertion-order parity with SqliteSourceBackend.list_sources (ORDER BY rowid)
        raise NotImplementedError

    async def list_sources(self) -> list[SourceManifestEntry]:
        raise NotImplementedError  # FILL IN: all Source nodes sorted by seq

    async def get_source(self, source_id: str) -> SourceManifestEntry | None:
        raise NotImplementedError  # FILL IN: hdsl.lookup_by_key("Source", "source_id", source_id)

    async def remove_source(self, source_id: str) -> bool:
        raise NotImplementedError  # FILL IN: one batch: existence var + drop; True iff it existed

    async def find_id_by_uri(self, source_uri: str) -> str | None:
        raise NotImplementedError  # FILL IN: equality on source_uri, first hit's source_id

    async def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None:
        raise NotImplementedError  # FILL IN: equality on external_id, first by seq

    async def find_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]:
        if not uris:
            return {}
        raise NotImplementedError  # FILL IN: ONE read batch over set(uris) → {source_uri: entry}

    async def find_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]:
        if not source_ids:
            return {}
        raise NotImplementedError  # FILL IN: ONE read batch → {source_id: entry}

    async def find_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]:
        if not external_ids:
            return {}
        raise NotImplementedError  # FILL IN: ONE read batch → {external_id: entry}, skipping None

    async def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]:
        raise NotImplementedError  # FILL IN: Source nodes with external_id not null, startswith(prefix) client-side, by seq

    async def close(self) -> None:
        """Close an owned client (never the store's)."""
        client, self._client = self._client, None
        if client is not None and self._store is None:
            await client.close()
```
**Why this shape**: identical construction contract to `ArangoSourceBackend` (eager settings or lazy store)
so TASK-4392's factory mirrors `_create_arango_backend`; JSON-encoding the two nested fields keeps
properties scalar (HelixDB text/vector indexes are top-level only, spec §6 limits).

### FILL IN checklist
- [ ] `upsert_many` with insertion-order `seq` (Meta counter in the same batch)
- [ ] the ten read/remove operations (one round trip each; batch lookups in one read batch)

---

## Acceptance Criteria

- [ ] AC2 (source half): `HelixSourceBackend` is an `AsyncSourceManifestBackend` (`isinstance` with the runtime-checkable Protocol) and, wrapped in `AsyncSourceBackendBridge`, is a `SourceManifestBackend` passing the `test_source_backend_parity` assertions (`tests/knowledge/wiki/test_source_backends.py:70-91`).
- [ ] Source nodes share the wiki database: after `upsert`, `HelixWikiStore.stats()["sources"]` counts them and `orphan_sources()` lists a source with no page.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/helix_sources.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_helix_sources.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_source_backends.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_helix_sources.py
import asyncio
import uuid

import pytest

pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")
from parrot.knowledge.helix.settings import HelixMode, HelixSettings
from parrot.knowledge.wiki.helix_sources import HelixSourceBackend
from parrot.knowledge.wiki.helix_store import HelixWikiStore
from parrot.knowledge.wiki.models import SourceManifestEntry
from parrot.knowledge.wiki.sources_backend import AsyncSourceBackendBridge, AsyncSourceManifestBackend, SourceManifestBackend


def _entry(source_id, external_id=None):   # same shape as test_source_backends.py:57
    return SourceManifestEntry(source_id=source_id, source_uri=f"/documents/{source_id}.md", file_hash=f"hash-{source_id}",
                               mtime=1.0, ingested_at="2026-10-15T00:00:00Z", external_id=external_id)


@pytest.fixture
async def store():
    s = HelixWikiStore(HelixSettings(mode=HelixMode.MEMORY, database=f"test_{uuid.uuid4().hex}"), wiki_name="t")
    await s.initialize()
    yield s
    await s.close()


async def test_async_parity(store): ...           # every assertion of test_source_backend_parity, awaited, on HelixSourceBackend(store=store)
async def test_protocols(store): ...              # isinstance(backend, AsyncSourceManifestBackend); bridge isinstance SourceManifestBackend
async def test_bridged_sync_api(store): ...       # bridge built in-loop, sync calls via asyncio.to_thread (as sources.py callers do)
async def test_sources_visible_to_wiki_lint(store): ...   # stats()["sources"] and orphan_sources()
def test_requires_settings_or_store(): ...        # ValueError
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`)
2. **Read the spec** (§3 M3 sources paragraph)
3. **Check dependencies** — TASK-4376 must be `"done"` in `sdd/tasks/index/helixdb-provider.json`
4. **Verify the Codebase Contract** (`sources_backend.py` line refs; FEAT-540 is merged)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**; no `NotImplementedError` may remain
7. **Verify** with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4378 helixdb-provider verified`
10. **Fill in the Completion Note** (include the `sources.py` passthrough decision needed by TASK-4392), commit the SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
