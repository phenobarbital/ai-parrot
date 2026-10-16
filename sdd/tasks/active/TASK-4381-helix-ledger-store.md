# TASK-4381: HelixLedgerStore + LedgerService backend dispatch

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4377, TASK-4379, TASK-4380
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (G3, AC5): the SDD work ledger can live on HelixDB. TASK-4380 made the ledger talk to its
store only through `LedgerTxn` / `LedgerReader`; this task provides the HelixDB implementation
(`HelixLedgerStore(HelixWikiStore)`, `ledger_state` → `Meta` nodes `ledger_state:<key>`) and makes
`LedgerService.from_root` / `from_dir` choose it when `WikiProjectConfig.backend == "helixdb"` (the ledger is
outside FEAT-540's registries — plane-local dispatch is the spec's decision). The ledger's canonical source
stays the local `events.jsonl` (`LedgerLog`); switching backend = `wikitoolkit ledger rebuild`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/helix_store.py`: `LEDGER_PLANE`,
  `HelixLedgerStore(HelixWikiStore)` with `ledger_transaction(operation)` (yields `_HelixLedgerTxn`, one
  write batch committed at context exit, discarded on exception), `ledger_read()` (yields
  `_HelixLedgerReader`), `read_cursor()`, `sqlite_settings()` (audit compatibility), and a cross-process
  writer lock around each transaction.
- Modify `wiki/ledger/service.py`: `from_root` dispatches on `config.backend == "helixdb"`; `from_dir`
  gains `helix_settings: HelixSettings | None = None`; widen the `store` annotation.
- Write `packages/ai-parrot/tests/knowledge/wiki/test_helix_ledger.py` (parity on sqlite + helix-memory).

**NOT in scope**: the protocols / SQLite txn (TASK-4380); `resolve_helix_params` and the `helix_*` config
fields (TASK-4379); registry rows (TASK-4392); docs (TASK-4397); any `LedgerIndex` / `LedgerLog` change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/helix_store.py` | CREATE | `HelixLedgerStore`, `_HelixLedgerTxn`, `_HelixLedgerReader`, `LEDGER_PLANE` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | Backend dispatch in `from_root` / `from_dir` |
| `packages/ai-parrot/tests/knowledge/wiki/test_helix_ledger.py` | CREATE | Ledger parity + dispatch tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import SCHEMA_VERSION, WikiPageRecord, WikiStoreBusy  # verified: wiki/store.py:51, :433, :284
from parrot.knowledge.wiki.ledger.service import LedgerService  # verified: wiki/ledger/service.py:127
from parrot.knowledge.wiki.ledger.index import LedgerIndex  # verified: wiki/ledger/index.py:86
from parrot.knowledge.wiki.ledger.log import LedgerLog  # verified: wiki/ledger/log.py:10
# Created upstream (not on dev yet):
from parrot.knowledge.wiki.ledger.store import LedgerTxn, LedgerReader  # TASK-4380
from parrot.knowledge.wiki.helix_store import HelixWikiStore, WIKI_PLANE  # TASK-4376 (+ get_meta/set_meta from TASK-4377)
from parrot.knowledge.wiki.project import resolve_helix_params  # TASK-4379: resolve_helix_params(config, *, root=None) -> HelixSettings
from parrot.knowledge.helix.settings import HelixSettings  # TASK-4372 (with_database(name) -> HelixSettings)
from parrot.knowledge.helix.bootstrap import PlaneSchema  # TASK-4374
from parrot.knowledge.helix import dsl as hdsl  # TASK-4374
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService:                                                                    # line 127
    def __init__(self, index: LedgerIndex, store: LedgerStore, log: LedgerLog, shared_root: Path) -> None   # line 130
    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService"                     # line 145
        # config = load_effective_config(shared_root).config ; ledger_dir = config.ledger_path(shared_root) ; policy = …
    @classmethod
    def from_dir(cls, ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy | None = None) -> "LedgerService"   # line 175
    async def audit(self) -> dict[str, Any]   # line 502 — uses store.read_cursor() and store.sqlite_settings() (:528)
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiStoreBusy(sqlite3.OperationalError):   # line 284; __init__(self, db_path: Path, operation: str, waited_seconds: float) :297
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig: backend: str (:618, registry-validated by _check_backend_name :562); wiki_name :616; ledger_path(root) :738
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py (dev today; TASK-4380 adds the protocol methods)
class LedgerStore(SQLiteWikiStore): read_cursor() -> tuple[int, str | None]   # line 75 (keys 'cursor_offset', 'last_event_id')
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py — the txn contract consumers:
#   _sync_locked → store.read_cursor() (:290) ; _write_cursor → txn.set_state ; rebuild → txn.clear_all ;
#   claim/close/unclaim read the issue AFTER applying events in the same txn (index.py:440-525)
```

### Verified anchors (MODIFY `ledger/service.py`)
| Anchor (verbatim) | `grep -c -F` | Line |
|---|---|---|
| `        store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=policy)` | 1 | 169 |
| `        store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=sqlite_policy)` | 1 | 193 |
| `    def from_dir(cls, ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy \| None = None) -> "LedgerService":` | 1 | 175 |

### Does NOT Exist
- ~~`parrot.knowledge.wiki.ledger.helix_store`~~ — created here.
- ~~`HelixWikiStore.ledger_transaction`~~ — only on `HelixLedgerStore`.
- ~~Ledger rows in FEAT-540 registries~~ — the ledger dispatches locally (spec §2 table).
- ~~Multi-statement HelixDB transactions with interactive reads~~ — a write batch is submitted whole; reads inside
  a `LedgerTxn` must be served from an in-memory overlay of pending writes + committed state.
- ~~`HelixWikiStore.sqlite_settings()`~~ — added here on `HelixLedgerStore` only, for `audit()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/helix_store.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_helix_ledger.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_dir",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.audit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiStoreBusy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.read_cursor"
  ]
}
```

---

## Implementation Notes

### Design decisions fixed here
- **Overlay accumulator.** `_HelixLedgerTxn` keeps `pages: dict[str, WikiPageRecord]`, `edges: list[tuple]`,
  `state: dict[str, str]`, `cleared: bool`. Reads (`get_page_body`, `list_pages`) consult the overlay first,
  then committed data (unless `cleared`). `commit()` issues **one** write batch: (if `cleared`) drop every
  `Page`, edge and `Meta` whose key starts with `ledger_state:`; then the page entries, edge entries and
  `Meta(ledger_state:<k>)` entries — reuse TASK-4376's `_add_page_entries` / `_add_edge_entries`.
- **Cross-process serialisation.** SQLite's `BEGIN IMMEDIATE` is what makes "first claim in log order wins"
  atomic (`index.py:403-445`). HelixDB batches do not hold a lock across the read-check-append sequence, so
  `ledger_transaction` holds an exclusive `fcntl.flock` on `<lock_dir>/ledger.helix.lock` for the whole
  transaction. All writers share the local `events.jsonl`, so a local lock is sufficient. Acquisition polls
  `LOCK_EX | LOCK_NB` off-thread (`asyncio.to_thread`) until `busy_timeout`, then raises
  `WikiStoreBusy(lock_path, operation, busy_timeout)` — exactly what `LedgerService._sync_best_effort`
  already tolerates.
- **State keys**: `Meta` key `f"ledger_state:{key}"`; `read_cursor()` reads `cursor_offset` / `last_event_id`
  through `get_meta` (TASK-4377) and returns `(0, None)` on absence or any read error (SQLite parity, `store.py:75-104`).
- **Database names**: `ledger_<wiki_name>` via `resolve_helix_params(config, root=shared_root).with_database(...)`.
- `audit()` calls `store.sqlite_settings()`; `HelixLedgerStore.sqlite_settings()` returns
  `{"backend": "helixdb", "database": <name>, "mode": <mode>}` so the report key stays present.

### Key Constraints
- No `if backend == "helixdb"` outside `LedgerService.from_root` / `from_dir` (ledger-local dispatch only).
- Import `HelixLedgerStore` / `resolve_helix_params` **lazily inside the helix branch** so `LedgerService`
  never imports `parrot.knowledge.helix` for SQLite users.
- `LedgerService.__init__`'s `store` annotation becomes `"LedgerStore | HelixLedgerStore"` (TYPE_CHECKING import).

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-4380's protocol names and TASK-4376/4377 helper names in the worktree.
2. Write `ledger/helix_store.py`; then the service dispatch; then tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/helix_store.py` (CREATE)
```python
"""HelixDB ledger plane (FEAT-670 M5): ledger_state → Meta nodes, LedgerTxn as one write batch."""
from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from parrot.knowledge.helix.bootstrap import PlaneSchema
from parrot.knowledge.helix.settings import HelixSettings
from parrot.knowledge.wiki.helix_store import WIKI_PLANE, HelixWikiStore
from parrot.knowledge.wiki.ledger.store import LedgerReader, LedgerTxn
from parrot.knowledge.wiki.store import SCHEMA_VERSION, WikiPageRecord, WikiStoreBusy

STATE_PREFIX = "ledger_state:"
LOCK_NAME = "ledger.helix.lock"
LEDGER_PLANE = PlaneSchema(plane="ledger", schema_version=SCHEMA_VERSION, labels=list(WIKI_PLANE.labels), edge_labels=["*"])
_POLL_S = 0.05

logger = logging.getLogger(__name__)


class _HelixLedgerReader:
    """LedgerReader over committed HelixDB state."""

    def __init__(self, store: "HelixLedgerStore") -> None:
        self._store = store

    async def get_page_body(self, concept_id: str) -> str | None:
        page = await self._store.get_page(concept_id, include_body=True)
        return None if page is None else page.get("body")

    async def list_pages(self, category: str) -> list[tuple[str, str, str]]:
        return await self._store._category_rows(category)

    async def get_state(self, key: str) -> str | None:
        return await self._store.get_meta(STATE_PREFIX + key)

    async def count_dangling_edges(self) -> int:
        rows = await self._store.broken_edges()
        return sum(1 for r in rows if not str(r["dst"]).startswith(("sym:", "file:")))


class _HelixLedgerTxn(_HelixLedgerReader):
    """LedgerTxn accumulating one write batch; reads see pending writes (overlay)."""

    def __init__(self, store: "HelixLedgerStore") -> None:
        super().__init__(store)
        self.pages: dict[str, WikiPageRecord] = {}
        self.edges: list[tuple] = []
        self.state: dict[str, str] = {}
        self.cleared = False

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> None:
        for page in pages:
            self.pages[page.concept_id] = page

    async def add_edges(self, edges: list[tuple]) -> None:
        self.edges.extend(edges)

    async def set_state(self, key: str, value: str) -> None:
        self.state[key] = value

    async def clear_all(self) -> None:
        self.pages.clear()
        self.edges.clear()
        self.state.clear()
        self.cleared = True

    async def get_page_body(self, concept_id: str) -> str | None:
        if concept_id in self.pages:
            return self.pages[concept_id].body
        return None if self.cleared else await super().get_page_body(concept_id)

    async def list_pages(self, category: str) -> list[tuple[str, str, str]]:
        merged = {} if self.cleared else {cid: (cid, body, ts) for cid, body, ts in await super().list_pages(category)}
        for cid, page in self.pages.items():
            if page.category == category:
                merged[cid] = (cid, page.body, page.updated_at or "")
        return list(merged.values())

    async def get_state(self, key: str) -> str | None:
        if key in self.state:
            return self.state[key]
        return None if self.cleared else await super().get_state(key)

    async def commit(self) -> None:
        """Submit everything as ONE atomic write batch."""
        if not (self.cleared or self.pages or self.edges or self.state):
            return
        await self._store._commit_txn(self)


class HelixLedgerStore(HelixWikiStore):
    """Ledger plane on HelixDB: ledger_state → Meta nodes ``ledger_state:<key>``."""

    plane_schema = LEDGER_PLANE

    def __init__(self, settings: HelixSettings, wiki_name: str = "ledger", *, lock_dir: Path,
                 read_only: bool = False, busy_timeout: float = 15.0) -> None:
        super().__init__(settings, wiki_name=wiki_name, read_only=read_only)
        self._lock_path = Path(lock_dir) / LOCK_NAME
        self._busy_timeout = busy_timeout

    async def _acquire(self, operation: str) -> int:
        """Exclusive flock on <lock_dir>/ledger.helix.lock, polled off-thread until busy_timeout."""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + self._busy_timeout
        while True:
            try:
                await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise WikiStoreBusy(self._lock_path, operation, self._busy_timeout) from None
                await asyncio.sleep(_POLL_S)

    @asynccontextmanager
    async def ledger_transaction(self, operation: str) -> AsyncIterator[LedgerTxn]:
        """Yield a _HelixLedgerTxn; commit one batch on clean exit, discard on exception."""
        self._assert_writable()
        await self.initialize()
        fd = await self._acquire(operation)
        try:
            txn = _HelixLedgerTxn(self)
            yield txn
            await txn.commit()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @asynccontextmanager
    async def ledger_read(self) -> AsyncIterator[LedgerReader]:
        """Yield a reader over committed state."""
        yield _HelixLedgerReader(self)

    async def read_cursor(self) -> tuple[int, str | None]:
        """(offset, last_event_id); (0, None) when absent or unreadable."""
        try:
            offset = await self.get_meta(STATE_PREFIX + "cursor_offset")
            event_id = await self.get_meta(STATE_PREFIX + "last_event_id")
        except Exception:  # noqa: BLE001 — parity with LedgerStore.read_cursor's defensive default
            return (0, None)
        return (int(offset) if offset else 0, event_id)

    async def sqlite_settings(self) -> dict[str, Any]:
        """Backend descriptor so LedgerService.audit() keeps its "sqlite" report key."""
        return {"backend": "helixdb", "database": self.settings.database, "mode": self.settings.mode.value}

    async def _category_rows(self, category: str) -> list[tuple[str, str, str]]:
        """(concept_id, body, updated_at) of every non-stub page in `category` (ONE read batch)."""
        # FILL IN: Page where category == category and stub False, projecting concept_id, body, updated_at
        #          — bounded by LedgerReader.list_pages contract (TASK-4380) / SQLite `SELECT … WHERE category = ?`
        raise NotImplementedError

    async def _commit_txn(self, txn: _HelixLedgerTxn) -> None:
        """Apply a txn's accumulated writes in ONE write batch."""
        client = await self._c()
        # FILL IN: batch = _sdk().write_batch() (import from parrot.knowledge.helix.client); if txn.cleared: drop all Page nodes (edges go with them) and
        #          Meta nodes whose key starts with STATE_PREFIX; then self._add_page_entries(batch, list(txn.pages.values()), now),
        #          self._add_edge_entries(batch, txn.edges, "e"), upsert Meta(STATE_PREFIX + k, v) per txn.state item;
        #          await client.write(batch, query_name="ledger.txn") — bounded by spec §3 M5 "commits on exit"
        raise NotImplementedError
```
**Why this shape**: the overlay keeps `claim_issue`'s "read after apply in the same transaction" correct;
the flock reproduces `BEGIN IMMEDIATE` exclusivity for the single-host ledger; a failed body discards the
overlay so nothing partial is written (rollback = discard, spec §3 M5).

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F '        store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=policy)' …/ledger/service.py) — line 169
# REPLACE that line (from_root) with:
        if config.backend == "helixdb":
            from parrot.knowledge.wiki.ledger.helix_store import HelixLedgerStore
            from parrot.knowledge.wiki.project import resolve_helix_params

            settings = resolve_helix_params(config, root=shared_root).with_database(f"ledger_{config.wiki_name}")
            store = HelixLedgerStore(settings, lock_dir=ledger_dir, busy_timeout=policy.busy_timeout_s)
        else:
            store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=policy)
```
```python
# occurrences: 1 — line 175: from_dir signature gains the helix option
    def from_dir(cls, ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy | None = None,
                 helix_settings: "HelixSettings | None" = None) -> "LedgerService":
# occurrences: 1 — line 193: REPLACE the construction with
        if helix_settings is not None:
            from parrot.knowledge.wiki.ledger.helix_store import HelixLedgerStore

            store = HelixLedgerStore(helix_settings, lock_dir=ledger_dir)
        else:
            store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=sqlite_policy)
```
**Why**: plane-local dispatch per spec §2 table; `policy.busy_timeout_s` is verified
(`SQLitePragmaPolicy.busy_timeout_s`, `wiki/store.py:279`, fed from `config.sqlite_busy_timeout` at `project.py:1001`). Add the
`HelixSettings` / `HelixLedgerStore` names under `TYPE_CHECKING` and document `helix_settings` in the docstring.

### FILL IN checklist
- [ ] `_category_rows` read batch
- [ ] `_commit_txn` single batch incl. the `cleared` drop

---

## Acceptance Criteria

- [ ] AC5 (HelixDB half): `HelixLedgerStore.ledger_transaction()` yields a `LedgerTxn`; ingest → claim → close → compact → rebuild produce the same issue states on `LedgerStore` and `HelixLedgerStore` (`test_ledger_txn_sqlite_and_helix_parity`).
- [ ] A body exception inside `ledger_transaction` writes nothing; a held lock raises `WikiStoreBusy`.
- [ ] `LedgerService.from_root` with `backend: helixdb` opens `HelixLedgerStore` on database `ledger_<wiki_name>`; with `sqlite` behaviour is unchanged.
- [ ] `ruff check` clean on both source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_helix_ledger.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_txn.py -q`
- `pytest tests/knowledge/wiki/test_ledger_service.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_from_dir.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_helix_ledger.py
import uuid

import pytest

pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")
from parrot.knowledge.helix.settings import HelixMode, HelixSettings
from parrot.knowledge.wiki.ledger.helix_store import HelixLedgerStore
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.store import LedgerStore, LedgerTxn


@pytest.fixture(params=["sqlite", "helix-memory"])
async def ledger_store(request, tmp_path):
    if request.param == "sqlite":
        store = LedgerStore(tmp_path / "ledger.db", wiki_name="ledger")
    else:
        store = HelixLedgerStore(HelixSettings(mode=HelixMode.MEMORY, database=f"ledger_{uuid.uuid4().hex}"), lock_dir=tmp_path)
    yield store
    if hasattr(store, "close"):
        await store.close()


async def test_ledger_txn_sqlite_and_helix_parity(ledger_store, tmp_path): ...  # open → claim → close → compact → rebuild via LedgerIndex
async def test_txn_reads_own_writes(ledger_store): ...                            # overlay: upsert then get_page_body in same txn
async def test_exception_discards_batch(ledger_store): ...                        # raise inside txn → page absent afterwards
async def test_cursor_roundtrip(ledger_store): ...                                # set_state cursor → read_cursor
async def test_lock_busy_raises_wiki_store_busy(tmp_path): ...                    # helix only: hold the flock, busy_timeout=0.1
async def test_service_from_root_dispatches_helix(tmp_path, monkeypatch): ...      # monkeypatch ledger.service.load_effective_config to a config
                                                                                   # built with WikiProjectConfig.model_construct(backend="helixdb", …)
                                                                                   # and resolve_helix_params → memory settings; assert isinstance(store, HelixLedgerStore)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`)
2. **Read the spec** (§3 M5, migration note)
3. **Check dependencies** — TASK-4377, TASK-4379, TASK-4380 must be `"done"`
4. **Verify the Codebase Contract** — re-run the three `grep -c -F` anchors (TASK-4380 edits the same file)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**; no `NotImplementedError` may remain
7. **Verify** with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4381 helixdb-provider verified`
10. **Fill in the Completion Note**, commit the SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
