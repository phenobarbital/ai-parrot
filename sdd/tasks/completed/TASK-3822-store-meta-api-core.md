# TASK-3822: Store meta API: `BaseWikiStore` defaults, SQLite, in-memory and federated

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §8 Q2 (answered by Jesús: "a new meta per backend") / §3 Module 2. The extractor
fingerprint (TASK-3828) needs a backend-agnostic key/value store on the plane itself. It cannot
be a JSON file, because a database-kind namespace may have no meaningful local `storage_dir`.
This task defines the contract and implements it for the SQLite, in-memory and federated
stores. TASK-3825 does ArangoDB and Postgres.

The pair is **concrete, not abstract** (spec v0.3). There are seven in-tree `BaseWikiStore`
subclasses (including `parrot_tools/legal/wiki_store.py`) plus a test fake
(`packages/ai-parrot/tests/knowledge/wiki/test_store_cas.py`). An abstract pair would break
the ones this feature does not own. The precedent is `compare_and_swap_page`, which defaults
to `NotImplementedError` (`store.py:610-642`).

---

## Scope

- Add to `BaseWikiStore` the concrete methods `get_meta(key) -> str | None` and
  `set_meta(key, value) -> None`. Both raise
  `NotImplementedError(f"{type(self).__name__} does not support get_meta|set_meta")` by default.
- `SQLiteWikiStore`: implement them over the existing `meta (key TEXT PRIMARY KEY, value TEXT
  NOT NULL)` table (`store.py:57`).
  - `get_meta` uses `_read()`.
  - `set_meta` uses `_write("set_meta")` with `INSERT ... ON CONFLICT(key) DO UPDATE`, and must
    refuse on a `read_only=True` store exactly as other writes do.
- `InMemoryWikiStore`: implement them over a dict persisted to `<bundle_dir>/.meta.json`, so
  the value survives a reopen (spec v0.3). The file name must not end in `.md`:
  `_load_bundle` globs `*.md` (`file_store.py:131-135`).
- `FederatedWikiStore`: delegate both to `self._local` only. The federated store never writes
  to a foreign namespace.
- `_EmptyStore`: `get_meta` returns `None`. `set_meta` raises
  `PermissionError("no local plane in this scope")`, the class's existing refusal for writes.
- Write tests.

**NOT in scope**: ArangoDB/Postgres (TASK-3825), the fingerprint itself (TASK-3828),
`parrot_tools/legal/wiki_store.py` and the test fake (they keep the default).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | base defaults + SQLite implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` | MODIFY | in-memory implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | federated + `_EmptyStore` |
| `packages/ai-parrot/tests/knowledge/wiki/test_store_meta.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore   # store.py:525, :855
from parrot.knowledge.wiki.file_store import InMemoryWikiStore           # file_store.py:73
from parrot.knowledge.wiki.federation import FederatedWikiStore          # federation.py:622
```

### Existing Signatures to Use
```python
# store.py:57 — schema
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
# store.py:610-642 — the precedent
async def compare_and_swap_page(...):
    ...
    raise NotImplementedError(f"{type(self).__name__} does not support compare_and_swap_page")  # store.py:642, occurrences: 1
# store.py:855
class SQLiteWikiStore(BaseWikiStore):
    def __init__(self, db_path, wiki_name="", *, read_only=False, sqlite_policy=None, persistent_writer=False)
    @asynccontextmanager
    async def _read(self) -> AsyncIterator[aiosqlite.Connection]:        # store.py:1093
    @asynccontextmanager
    async def _write(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:  # store.py:1143
    # usage precedent: `async with self._write("upsert_pages") as conn:`  store.py:1563
# store.py:1340 — existing meta read precedent
async with conn.execute("SELECT value FROM meta WHERE key = 'schema_version'") as cur:
# file_store.py:73
class InMemoryWikiStore(BaseWikiStore):
    def __init__(self, bundle_dir: str | Path, wiki_name: str = "") -> None:   # self._bundle_dir: Path
    async def _ensure_loaded(self) -> None:                                     # file_store.py:121
    async def orphan_sources(self) -> list[str]:                                # file_store.py:741, occurrences: 1
# federation.py:622
class FederatedWikiStore(BaseWikiStore):
    self._local: BaseWikiStore
    async def page_hashes(self, concept_ids: list[str]) -> dict[str, str | None]:  # federation.py:1431, occurrences: 1
# federation.py:1550
class _EmptyStore(BaseWikiStore):
    async def upsert_pages(self, pages) -> int:
        raise PermissionError("no local plane in this scope")
```

### Does NOT Exist
- ~~`BaseWikiStore.get_meta` / `set_meta`~~: created here.
- ~~`SQLiteWikiStore._meta_get` or any public meta accessor~~: only the raw `meta` table.
- ~~A `meta` attribute on `InMemoryWikiStore`~~: create `self._meta: dict[str, str]`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/federation.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_store_meta.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#_EmptyStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Values are plain `str`: callers JSON-encode (TASK-3828 stores `model_dump_json()`).
- A read-only SQLite store must be able to `get_meta` (a federated foreign plane is read-only).
- Write the in-memory `.meta.json` atomically (write to a temp file, then `os.replace`), off the
  event loop (`asyncio.to_thread`), which is the module's existing style.

---

## Implementation Blueprint

### Steps (in order)
1. Add the base defaults right after `compare_and_swap_page`. *Why*: the same precedent, and
   the same place a reader looks.
2. Implement SQLite. *Why*: it is the default backend, and the table already exists.
3. Implement in-memory with persistence. *Why*: a dict alone would lose the fingerprint on every
   reopen, which would force a re-ingest on every build.
4. Implement federated/empty delegation. *Why*: the build path may hand a federated store to
   the fingerprint code.
5. Write the tests and run them.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY) — base defaults
```python
# occurrences: 1 (verified: grep -c 'does not support compare_and_swap_page' store.py)
# AFTER — insert below `        raise NotImplementedError(f"{type(self).__name__} does not support compare_and_swap_page")` (verified: store.py:642)

    async def get_meta(self, key: str) -> Optional[str]:
        """Read one plane-level metadata value (FEAT-609 Q2).

        Args:
            key: Metadata key (e.g. ``"extractor_fingerprint"``).

        Returns:
            The stored string, or ``None`` when the key is absent.

        Raises:
            NotImplementedError: When the backend has no meta support.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support get_meta")

    async def set_meta(self, key: str, value: str) -> None:
        """Write one plane-level metadata value (FEAT-609 Q2).

        Raises:
            NotImplementedError: When the backend has no meta support.
            PermissionError: When the store was opened read-only.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support set_meta")
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY) — SQLite
```python
# occurrences: 2 for the bare anchor (verified: grep -c '    async def page_hashes(self, concept_ids: list\[str\]) -> dict\[str, Optional\[str\]\]:' store.py)
# Disambiguated: insert BEFORE the SECOND occurrence (SQLiteWikiStore, store.py:1909), i.e. right after
#                 return [_row_to_symbol_record(row) for row in await cur.fetchall()]
#   (the end of SQLiteWikiStore.search_symbols_fts, store.py:1907)

    async def get_meta(self, key: str) -> Optional[str]:
        """Read ``key`` from the ``meta`` table (works on read-only planes)."""
        async with self._read() as conn:
            async with conn.execute("SELECT value FROM meta WHERE key = ?", (key,)) as cur:
                row = await cur.fetchone()
        return None if row is None else str(row[0])

    async def set_meta(self, key: str, value: str) -> None:
        """Upsert ``key`` into the ``meta`` table."""
        self._assert_writable()
        async with self._write("set_meta") as conn:
            await conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            # FILL IN: commit exactly as the neighbouring _write users do — bounded by
            # "read how `upsert_pages` (store.py:1563) finishes its _write block".
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def orphan_sources(self) -> list\[str\]:' file_store.py)
# BEFORE — insert above `    async def orphan_sources(self) -> list[str]:` (verified: file_store.py:741)

    def _meta_path(self) -> Path:
        """``<bundle_dir>/.meta.json`` — not ``*.md``, so ``_load_bundle`` ignores it."""
        return self._bundle_dir / ".meta.json"

    async def get_meta(self, key: str) -> str | None:
        """Read one metadata value persisted next to the bundle."""
        # FILL IN: lazy-load self._meta from _meta_path() once (json; {} when missing/corrupt,
        # never raise) — bounded by "survives a reopen of the same bundle_dir"
        return self._meta.get(key)

    async def set_meta(self, key: str, value: str) -> None:
        """Persist one metadata value next to the bundle (atomic replace)."""
        # FILL IN: update self._meta and write it atomically via asyncio.to_thread
        # (tmp file + os.replace) — bounded by the module's threaded-I/O style
```
Also initialise `self._meta: dict[str, str] = {}` (and a loaded flag) in `__init__`.
`asyncio`, `json` and `os` are already imported (`file_store.py:29-33`). `Optional` is NOT, so
use `str | None`, as the blueprint does.

### `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` (MODIFY) — federated
```python
# occurrences: 1 (verified: grep -c '    async def page_hashes(self, concept_ids: list\[str\]) -> dict\[str, str | None\]:' federation.py)
# BEFORE — insert above that line (verified: federation.py:1431)

    async def get_meta(self, key: str) -> str | None:
        """Local plane only — a namespace's metadata is not ours to read."""
        return await self._local.get_meta(key)

    async def set_meta(self, key: str, value: str) -> None:
        """Local plane only — never writes into a foreign namespace."""
        await self._local.set_meta(key, value)
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` (MODIFY) — `_EmptyStore`
```python
# occurrences: 1 (verified: grep -c 'class _EmptyStore(BaseWikiStore):' federation.py)
# AFTER — insert as the first methods after the class docstring of `class _EmptyStore(BaseWikiStore):` (verified: federation.py:1550-1555)

    async def get_meta(self, key: str) -> str | None:
        return None

    async def set_meta(self, key: str, value: str) -> None:
        raise PermissionError("no local plane in this scope")
```

### `packages/ai-parrot/tests/knowledge/wiki/test_store_meta.py` (CREATE)
```python
"""FEAT-609 Q2: per-backend plane metadata (get_meta / set_meta)."""

from __future__ import annotations

import pytest
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.store import SQLiteWikiStore


@pytest.fixture
async def sqlite_store(tmp_path):
    store = SQLiteWikiStore(tmp_path / "wiki.db", "t")
    # FILL IN: initialise the schema the way the existing sqlite tests do
    # (see test_sqlite_fts_external_content.py) — bounded by "meta table exists"
    yield store


async def test_meta_roundtrip_sqlite(sqlite_store) -> None:
    assert await sqlite_store.get_meta("k") is None
    await sqlite_store.set_meta("k", "v1")
    await sqlite_store.set_meta("k", "v2")
    assert await sqlite_store.get_meta("k") == "v2"


async def test_meta_read_only_refuses(tmp_path) -> None:
    # FILL IN: build the plane writable, then reopen read_only=True; get_meta works,
    # set_meta raises the same exception type other writes raise on a read-only store
    ...


async def test_meta_roundtrip_memory_survives_reopen(tmp_path) -> None:
    store = InMemoryWikiStore(tmp_path / "bundle", "t")
    await store.set_meta("k", "v")
    reopened = InMemoryWikiStore(tmp_path / "bundle", "t")
    assert await reopened.get_meta("k") == "v"


async def test_federated_meta_never_writes_foreign(tmp_path) -> None:
    # FILL IN: FederatedWikiStore(local=<sqlite A>, handles=[<handle over sqlite B>]);
    # set_meta lands in A only; B.get_meta("k") is None — build handles the way
    # tests/knowledge/wiki/test_federation.py does
    ...


async def test_base_default_not_implemented() -> None:
    # FILL IN: minimal BaseWikiStore subclass (or reuse the test_store_cas.py fake pattern)
    # -> get_meta raises NotImplementedError
    ...
```
**Why**: the read-only and federated tests are the ones that pin the security-relevant
behaviour (no foreign writes, no writes on read-only planes). Mutation-check them.

### FILL IN checklist
- [ ] SQLite `set_meta` commit semantics. Bound: mirror `upsert_pages`'s `_write` block.
- [ ] In-memory lazy load and atomic persist. Bound: survives reopen; a corrupt file reads as empty.
- [ ] Test fixtures. Bound: reuse the existing sqlite and federation test patterns, with no
  mocks of the store itself (ARCH Rule 6 spirit: real objects at the boundary).

---

## Acceptance Criteria

- [ ] `get_meta`/`set_meta` round-trip on SQLite and in-memory. In-memory survives a reopen.
- [ ] A read-only SQLite store can `get_meta` and refuses `set_meta`.
- [ ] `FederatedWikiStore.set_meta` writes only the local plane (mutation-checked).
- [ ] `_EmptyStore.get_meta` returns `None`, and `set_meta` raises `PermissionError`.
- [ ] Untouched subclasses (`parrot_tools/legal/wiki_store.py`, the `test_store_cas.py` fake)
      still instantiate: `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_cas.py -q` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_meta.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_cas.py -q`
- `pytest tests/knowledge/wiki/test_federation.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Verify the contract, re-run each `grep -c`, then set the task in-progress in the index.
3. Implement, validate, and stage only the listed files.
4. Close with `scripts/sdd/close_task.sh TASK-3822 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note.

---

## Completion Note

Implemented as specified (base NotImplementedError defaults; SQLite meta table; InMemory .meta.json atomic; Federated local-only; _EmptyStore). Mutation check: making FederatedWikiStore.set_meta a no-op turned test_meta_roundtrip_federated_local_only and test_federated_meta_never_writes_foreign RED.
