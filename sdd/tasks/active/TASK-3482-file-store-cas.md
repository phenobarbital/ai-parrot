# TASK-3482: `compare_and_swap_page` on `InMemoryWikiStore` (file-backed)

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3481
**Assigned-to**: unassigned

---

## Context

Module 2. `InMemoryWikiStore` keeps RAM indexes over an OKF markdown bundle on
disk, and spec §7 names its specific hazard: *"In-memory backend can retain
stale indexes across processes: ADR inventory/CAS reads must reload persisted
ADR pages when relevant files change; do not trust only a startup snapshot."*

A CAS that compares against `self._pages` alone would therefore compare against
a snapshot another process has already superseded, and the write would look
like it succeeded. This task implements the reload-under-lock variant the spec
prescribes. It is one of the two **mandatory** backends for AC8.

---

## Scope

- Add a per-store ADR write lock and implement `compare_and_swap_page` on
  `InMemoryWikiStore`: take the lock, **reload the target page from its bundle
  file**, compare, atomically replace the file, then refresh the RAM indexes.
- Keep every file operation off the event loop via `asyncio.to_thread`.
- Test insert / replace / conflict, and the cross-process staleness case.

**NOT in scope**: the base default and SQLite (TASK-3481, a dependency), Arango
(TASK-3483), Postgres (TASK-3484), any ADR model or error code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` | MODIFY | ADR write lock + `compare_and_swap_page` |
| `packages/ai-parrot/tests/knowledge/wiki/test_file_store_cas.py` | CREATE | CAS contract + stale-snapshot regression |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

`asyncio`, `Path`, `WikiPageRecord` and `BaseWikiStore` are already imported by
`file_store.py`. Add **no** import from `parrot.knowledge.wiki.decisions`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py:71
class InMemoryWikiStore(BaseWikiStore):
    def __init__(self, bundle_dir: str | Path, wiki_name: str = "") -> None: ...   # line 86
        self._bundle_dir: Path                                                     # line 87
        self._loaded: bool = False                                                 # line 92
        self._lock = asyncio.Lock()          # guards _load_bundle ONLY            # line 93
        self._pages: dict[str, dict[str, Any]] = {}                                # line 96
    @property
    def bundle_dir(self) -> Path: ...                                              # line 104
    async def _ensure_loaded(self) -> None: ...                                    # line 114
    def _load_bundle(self) -> None: ...          # sync, run via asyncio.to_thread # line 125
    def _page_path(self, page: dict[str, Any]) -> Path: ...                        # line 198
    def _write_page_file(self, page: dict[str, Any]) -> None: ...  # sync          # line 204
    async def _persist_pages(self, pages: list[dict[str, Any]]) -> None: ...       # line 247
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...          # line 347
    async def delete_page(self, concept_id: str) -> bool: ...                      # line 434
    async def get_page(self, concept_id: str, include_body: bool = True) -> dict[str, Any] | None: ...  # line 470

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:608 block (TASK-3481)
    async def compare_and_swap_page(self, page: WikiPageRecord,
                                    expected_content_hash: Optional[str]) -> bool: ...
```

`_page_path` takes the **page dict**, not a concept_id. `_persist_pages` already
offloads its writes with `asyncio.to_thread` (`file_store.py:255`).

### Does NOT Exist

- ~~`InMemoryWikiStore.read_only`~~ — this backend has no read-only mode.
  `_assert_writable` resolves to the base no-op (`store.py:610`). Do not call
  `self.read_only`.
- ~~a bundle-level manifest of content hashes~~ — the hash lives in each page
  file, so the reload must read that file.
- ~~`self._lock` as a general write lock~~ — it guards `_load_bundle` only
  (`file_store.py:114-122`). Reusing it inside CAS while calling
  `_ensure_loaded` would deadlock: `asyncio.Lock` is **not** reentrant. Add a
  separate lock.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_file_store_cas.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Never** reuse `self._lock` inside CAS — it is held by `_ensure_loaded` and
  `asyncio.Lock` is not reentrant. Add `self._adr_lock = asyncio.Lock()`.
- The comparison reads the page **file**, not `self._pages`. That is the entire
  point of the task (spec §7).
- "Atomically replaces its file" means write-to-temp + `os.replace` in the same
  directory, so a crash cannot leave a half-written record.
- All blocking I/O goes through `asyncio.to_thread` (spec §2: "File I/O and lock
  waits must not block the event loop").

---

## Implementation Blueprint

### Steps (in order)

1. Add `self._adr_lock` in `__init__` — *why*: a dedicated, non-reentrant lock
   lets CAS call `_ensure_loaded` (which takes `self._lock`) without deadlock.
2. Add a sync `_read_page_file` helper — *why*: the compare must see the bytes
   on disk right now, and a sync helper is what `asyncio.to_thread` wants.
3. Implement `compare_and_swap_page` — *why*: reload, compare, atomic replace,
   index refresh, in that order, is the only sequence where a lost race cannot
   corrupt the bundle.

### `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` (MODIFY — lock)

```python
# occurrences: 1 (verified: grep -c '        self._lock = asyncio.Lock()' packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py)
# AFTER — insert directly below `        self._lock = asyncio.Lock()`
# (verified: packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py:93):

        # FEAT-578: serializes compare-and-swap writes on managed ADR pages.
        # Deliberately NOT `self._lock`, which `_ensure_loaded` holds while
        # loading the bundle — asyncio.Lock is not reentrant.
        self._adr_lock = asyncio.Lock()
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` (MODIFY — CAS)

```python
# occurrences: 1 (verified: grep -c '    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:' packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py)
# AFTER — insert directly below the end of `async def upsert_pages`
# (verified: packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py:347),
# i.e. immediately before `    async def replace_source_slice(` at line 396:

    def _read_page_file_hash(self, concept_id: str) -> tuple[bool, str | None]:
        """Read one page's persisted ``content_hash`` straight from its file.

        Sync by design — call it through :func:`asyncio.to_thread`.

        Returns:
            ``(exists, content_hash)``. ``(False, None)`` when no file is
            present. Never consults the RAM indexes, so it sees writes made
            by another process since this store loaded its bundle.
        """
        # FILL IN: resolve the file via self._page_path({"concept_id": ...,
        # plus whatever other keys _page_path reads at file_store.py:198}) and
        # parse only the stored content_hash out of it, reusing the same
        # front-matter/parsing helper `_load_bundle` uses at file_store.py:125
        # — bounded by spec §7 "do not trust only a startup snapshot"
        raise NotImplementedError

    async def compare_and_swap_page(
        self,
        page: WikiPageRecord,
        expected_content_hash: str | None,
    ) -> bool:
        """Conditionally write one page against the bundle file's current hash.

        See :meth:`BaseWikiStore.compare_and_swap_page` for the contract.
        The precondition is evaluated against the **persisted file**, not the
        RAM snapshot, so a peer process's write is never silently clobbered.
        """
        await self._ensure_loaded()
        async with self._adr_lock:
            exists, stored = await asyncio.to_thread(self._read_page_file_hash, page.concept_id)
            # FILL IN: return False unless the precondition holds —
            #   expected is None     -> `exists` must be False
            #   expected is not None -> `exists` and stored == expected
            # bounded by BaseWikiStore.compare_and_swap_page's docstring
            raise NotImplementedError
            # FILL IN: write the replacement atomically (temp file in the same
            # directory + os.replace, offloaded with asyncio.to_thread, reusing
            # _write_page_file at file_store.py:204 for the rendering), then
            # refresh the RAM indexes for this one concept_id so a subsequent
            # get_page/search_fts sees it — bounded by spec §2 "atomically
            # replaces its file, and refreshes indexes after success"
        self.logger.debug("compare_and_swap_page: wrote %s", page.concept_id)
        return True
```

**Why**: the lock is held across read-compare-write, so two coroutines in this
process serialize; reading the file rather than `self._pages` closes the
cross-process gap that `self._loaded` would otherwise hide. `_ensure_loaded` is
called **before** taking `_adr_lock` to keep the two locks strictly ordered and
un-nested. Do not change the `bool` return contract or raise on a lost race.

### `packages/ai-parrot/tests/knowledge/wiki/test_file_store_cas.py` (CREATE)

```python
"""InMemoryWikiStore CAS contract + stale-snapshot regression (FEAT-578 M2)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord


def _page(body: str = "v1", content_hash: str = "h1") -> WikiPageRecord:
    return WikiPageRecord(concept_id="adr:doc:a", title="t", category="adr", body=body, content_hash=content_hash)


@pytest.fixture
def bundle(tmp_path):
    """A fresh OKF bundle directory."""
    return tmp_path / "pages"


class TestCasInsertUpdateConflict:
    async def test_insert_when_absent(self, bundle):
        store = InMemoryWikiStore(bundle, wiki_name="t")
        assert await store.compare_and_swap_page(_page(), None) is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_insert_refuses_when_present(self, bundle):
        store = InMemoryWikiStore(bundle, wiki_name="t")
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page("v2", "h2"), None) is False

    async def test_replace_on_matching_hash(self, bundle):
        store = InMemoryWikiStore(bundle, wiki_name="t")
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page("v2", "h2"), "h1") is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v2"

    async def test_conflict_leaves_row_intact(self, bundle):
        store = InMemoryWikiStore(bundle, wiki_name="t")
        await store.compare_and_swap_page(_page(), None)
        await store.compare_and_swap_page(_page("winner", "h2"), "h1")
        assert await store.compare_and_swap_page(_page("loser", "h3"), "h1") is False
        assert (await store.get_page("adr:doc:a"))["body"] == "winner"


class TestStaleSnapshot:
    async def test_cas_sees_a_peer_process_write(self, bundle):
        """spec §7: a startup snapshot must never authorize a write.

        Two stores over one bundle stand in for two processes.
        """
        # FILL IN: writer_a and writer_b both open `bundle` and load it;
        # writer_a CASes to h2; writer_b (whose RAM snapshot still says h1)
        # must get False for expected="h1", and the file must still hold
        # writer_a's body — bounded by spec §7 in-memory-staleness gotcha
        raise NotImplementedError

    async def test_write_is_atomic_on_disk(self, bundle):
        """A replacement never leaves a partial page file behind."""
        # FILL IN: after a successful CAS, assert the bundle dir contains no
        # leftover temp/partial files beside the page file — bounded by spec §2
        # "atomically replaces its file"
        raise NotImplementedError
```

### FILL IN checklist

- [ ] `file_store.py::_read_page_file_hash` — file resolution + hash parse reusing `_load_bundle`'s parser; bounded by spec §7
- [ ] `file_store.py::compare_and_swap_page` — precondition branches; bounded by the base docstring
- [ ] `file_store.py::compare_and_swap_page` — atomic temp+replace and index refresh; bounded by spec §2
- [ ] `test_file_store_cas.py::test_cas_sees_a_peer_process_write` — bounded by spec §7
- [ ] `test_file_store_cas.py::test_write_is_atomic_on_disk` — bounded by spec §2

---

## Acceptance Criteria

- [ ] `compare_and_swap_page` compares against the persisted file, not `self._pages` (spec §7)
- [ ] Insert-if-absent, matching-hash replace, and stale-hash conflict all behave per the base contract
- [ ] A second store over the same bundle cannot overwrite a peer's write with a stale expectation (AC6)
- [ ] All file I/O and lock waits are off the event loop (`asyncio.to_thread`)
- [ ] `self._lock` is not taken inside `compare_and_swap_page`
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/test_extra_backends.py -q` still passes (AC10)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_file_store_cas.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_extra_backends.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "Identity, storage, and concurrency" and §7 "Known Risks / Gotchas".
2. **Verify the Codebase Contract** — re-check `file_store.py:93`, `:198`, `:204`, `:347`.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** both Validation Commands pass.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
