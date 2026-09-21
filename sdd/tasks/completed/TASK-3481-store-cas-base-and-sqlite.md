# TASK-3481: `compare_and_swap_page` — base default + SQLite implementation

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 2, first half, and the root of FEAT-578's concurrency story: spec §9 A4
records that existing page writes have **no revision precondition**, so two
maintainers reviewing the same candidate would silently overwrite each other's
audit history (AC6). This task adds the one atomic primitive every ADR mutation
must use, plus the SQLite implementation.

It is deliberately independent of Module 1: `store.py` must **not** import the
decisions package. The primitive speaks only `WikiPageRecord` and a hash; the
repository (TASK-3485) maps its `False` return onto `ADR_REVISION_CONFLICT`.

---

## Scope

- Add `compare_and_swap_page` to `BaseWikiStore` as a **concrete** method
  raising `NotImplementedError`, so third-party subclasses stay instantiable
  (spec §2 explicitly forbids making it abstract).
- Implement it on `SQLiteWikiStore` inside one existing write transaction.
- Test insert-if-absent, correct-hash replace, wrong-hash conflict, read-only
  refusal, and the unsupported-backend default.

**NOT in scope**: the other three backends (TASK-3482 / TASK-3483 / TASK-3484),
any ADR model, code or error mapping.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Concrete `compare_and_swap_page` default + `SQLiteWikiStore` override |
| `packages/ai-parrot/tests/knowledge/wiki/test_store_cas.py` | CREATE | CAS contract tests for SQLite + the base default |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Everything needed is already imported by `store.py`. Add **no** new
module-level imports; in particular do **not** import
`parrot.knowledge.wiki.decisions.*` — that would invert the dependency.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):
    @abstractmethod
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...   # line 544
    @abstractmethod
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...  # line 565
    # line 608: `    # -- shared concrete behaviour ----------------------------------------`
    def _assert_writable(self) -> None: ...   # line 610, concrete no-op base

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py — SQLiteWikiStore
    @property
    def read_only(self) -> bool: ...                                     # line 926
    def _assert_writable(self) -> None: ...                              # line 930, raises PermissionError
    @asynccontextmanager
    async def _write(self, operation: str) -> AsyncIterator[aiosqlite.Connection]: ...  # line 1109
    async def _upsert_pages_conn(self, conn: aiosqlite.Connection, pages: list[WikiPageRecord]) -> None: ...  # line 1449
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...  # line 1514
```

`_write` opens `BEGIN IMMEDIATE` and commits or rolls back exactly once, and
raises `WikiStoreBusy` at the begin boundary only. `_upsert_pages_conn` writes
page rows on an already-open connection and must never touch `pages_fts`
directly (triggers mirror it).

### Does NOT Exist

- ~~`BaseWikiStore.compare_and_swap_page`~~ — this task adds it.
- ~~an existing conditional/versioned page write~~ — `upsert_pages`
  (`store.py:544`) and `replace_source_slice` (`:550`) are unconditional. Spec
  §9 A4 is the verified finding behind this task.
- ~~`BaseWikiStore.read_only`~~ — **not** on the base class. It exists on
  `SQLiteWikiStore` (`store.py:926`) and `ArangoDBWikiStore`
  (`arango_store.py:199`) only. Do not call it through the base type.
- ~~a `pages.revision` column~~ — there is none. The precondition is the page's
  `content_hash` column, nothing else.
- ~~emulating CAS as read-then-`upsert_pages`~~ — spec §2 forbids it explicitly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_store_cas.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- The condition and the write happen inside **one** `_write` transaction. A
  `SELECT` outside the transaction followed by a write inside it is exactly the
  race this task exists to close.
- `expected_content_hash=None` means **insert-only**: succeed if and when the
  row is absent, and return `False` if a row already exists. It does **not**
  mean "match a NULL hash".
- Return `False` for a lost race. Raise only for a genuine failure
  (`PermissionError` read-only, `WikiStoreBusy` lock timeout).
- `store.py` is a shared, high-traffic file (spec §7: "One owner coordinates
  shared `store.py`"). Touch only the two insertion points below.

---

## Implementation Blueprint

### Steps (in order)

1. Add the concrete base default first — *why*: TASK-3482/3483/3484 all override
   it and need the exact signature and docstring contract frozen before they
   start; they are dispatched in the same wave.
2. Add the SQLite override inside `_write` — *why*: `BEGIN IMMEDIATE` is what
   makes the compare and the write one atomic step.
3. Write the tests against a real temporary SQLite plane — *why*: the conflict
   semantics only exist at the DB level; a mocked store proves nothing.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — base default)

```python
# occurrences: 1 (verified: grep -c '    # -- shared concrete behaviour ----------------------------------------' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert directly below `    # -- shared concrete behaviour ----------------------------------------`
# (verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:608), i.e.
# immediately before the existing `def _assert_writable` at line 610:

    async def compare_and_swap_page(
        self,
        page: WikiPageRecord,
        expected_content_hash: Optional[str],
    ) -> bool:
        """Insert only if absent, or atomically replace an exact hash.

        The one write primitive with a revision precondition (FEAT-578
        Module 2). Every managed ``adr`` mutation goes through it, so a
        concurrent reviewer can never silently overwrite another's audit
        history.

        Args:
            page: The full replacement record. Its ``content_hash`` is the
                new stored hash.
            expected_content_hash: The hash the caller last read. ``None``
                means insert-only — succeed if the row is absent, fail if
                any row already exists (it does NOT match a NULL hash).

        Returns:
            ``True`` when the write landed; ``False`` when the precondition
            did not hold (row present for an insert, or a differing stored
            hash). A ``False`` return is a lost race, not an error.

        Raises:
            NotImplementedError: On backends that do not support a
                conditional write. Concrete by design rather than abstract,
                so out-of-tree ``BaseWikiStore`` subclasses stay
                instantiable; callers surface this as
                ``ADR_WRITE_UNSUPPORTED``.
            PermissionError: When the store was opened read-only.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support compare_and_swap_page")
```

**Why this shape**: spec §2 is explicit — "Add a concrete default method on
`BaseWikiStore` raising `NotImplementedError`, so external subclasses remain
instantiable". Making it `@abstractmethod` would break every third-party backend
registered through `register_wiki_backend` (`store.py:~520`). The `bool` return
(rather than an exception) is what lets the repository distinguish a lost race
from a real failure without string-matching.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — SQLite override)

```python
# occurrences: 1 (verified: grep -c '    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...' packages/ai-parrot/src/parrot/knowledge/wiki/store.py — the ABSTRACT one)
# The concrete SQLite `async def upsert_pages(...)` is at line 1514 (2 matches
# repo-wide for the non-`...` spelling: SQLiteWikiStore here and the abstract
# signature above, so anchor on the transaction body).
# AFTER — insert directly below the end of `SQLiteWikiStore.upsert_pages`
# (verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1514-1531,
# whose last statement is `        return len(pages)`), i.e. immediately before
# `    async def add_edges(self, edges: list[tuple]) -> int:` at line 1533:

    async def compare_and_swap_page(
        self,
        page: WikiPageRecord,
        expected_content_hash: Optional[str],
    ) -> bool:
        """Conditionally write one page inside a single immediate transaction.

        See :meth:`BaseWikiStore.compare_and_swap_page` for the contract.
        """
        self._assert_writable()
        async with self._write("compare_and_swap_page") as conn:
            cursor = await conn.execute(
                "SELECT content_hash FROM pages WHERE concept_id = ?",
                (page.concept_id,),
            )
            row = await cursor.fetchone()
            # FILL IN: decide the precondition and return early with False when
            # it fails — bounded by the contract above:
            #   expected is None  -> row must be absent
            #   expected is not None -> row must exist AND row[0] == expected
            # On success fall through to the write below. Returning inside the
            # `async with` is safe: _write commits on clean exit.
            raise NotImplementedError
            await self._upsert_pages_conn(conn, [page])
        self.logger.debug("compare_and_swap_page: wrote %s", page.concept_id)
        return True
```

**Why**: `_write` already yields a connection inside `BEGIN IMMEDIATE`, so the
`SELECT` and the `INSERT ... ON CONFLICT` cannot be interleaved by another
writer — that is the whole guarantee. Reusing `_upsert_pages_conn` rather than
hand-writing SQL keeps the FTS triggers and the column list in one place. Do not
add a `COMMIT`; `_write` owns the transaction boundary.

### `packages/ai-parrot/tests/knowledge/wiki/test_store_cas.py` (CREATE)

```python
"""compare_and_swap_page contract — SQLite + the base default (FEAT-578 M2)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord


def _page(concept_id: str = "adr:doc:a", body: str = "v1", content_hash: str = "h1") -> WikiPageRecord:
    """A minimal managed-looking page; the CAS primitive is category-agnostic."""
    return WikiPageRecord(concept_id=concept_id, title="t", category="adr", body=body, content_hash=content_hash)


@pytest.fixture
async def store(tmp_path):
    """A real SQLite plane — the conflict semantics only exist at the DB level."""
    # FILL IN: construct SQLiteWikiStore against tmp_path and initialize its
    # schema the way packages/ai-parrot/tests/knowledge/wiki/test_sqlite_policy.py
    # already does; yield it, then close it — bounded by "no mocked store"
    raise NotImplementedError


class TestCasInsertUpdateConflict:
    async def test_insert_when_absent(self, store):
        """expected=None inserts a brand-new row."""
        assert await store.compare_and_swap_page(_page(), None) is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_insert_refuses_when_present(self, store):
        """expected=None is insert-ONLY — it never matches an existing row."""
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page(body="v2", content_hash="h2"), None) is False
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_replace_on_matching_hash(self, store):
        """The happy path: the hash we last read is still stored."""
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page(body="v2", content_hash="h2"), "h1") is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v2"

    async def test_conflict_on_stale_hash_leaves_row_intact(self, store):
        """AC6: a loser must not be able to erase the winner's write."""
        await store.compare_and_swap_page(_page(), None)
        await store.compare_and_swap_page(_page(body="winner", content_hash="h2"), "h1")
        assert await store.compare_and_swap_page(_page(body="loser", content_hash="h3"), "h1") is False
        assert (await store.get_page("adr:doc:a"))["body"] == "winner"

    async def test_update_of_absent_row_is_a_conflict(self, store):
        """A non-None expectation against a missing row is False, not an insert."""
        assert await store.compare_and_swap_page(_page(), "h1") is False
        assert await store.get_page("adr:doc:a") is None

    async def test_read_only_store_refuses(self, tmp_path):
        """A read-only plane raises rather than silently reporting a conflict."""
        # FILL IN: open the same db path with read_only=True and assert
        # PermissionError — bounded by store.py:930 `_assert_writable`
        raise NotImplementedError


class TestUnsupportedBackend:
    async def test_base_default_raises_not_implemented(self):
        """An out-of-tree backend stays instantiable but cannot CAS."""
        # FILL IN: define a minimal BaseWikiStore subclass implementing the
        # abstract methods as no-ops, instantiate it (this must NOT raise), and
        # assert compare_and_swap_page raises NotImplementedError — bounded by
        # spec §2 "external subclasses remain instantiable"
        raise NotImplementedError
```

**Why**: `test_conflict_on_stale_hash_leaves_row_intact` and
`test_base_default_raises_not_implemented` are the two claims the rest of the
feature rests on — respectively AC6 and the `ADR_WRITE_UNSUPPORTED` path.

### FILL IN checklist

- [ ] `store.py::SQLiteWikiStore.compare_and_swap_page` — the two precondition branches; bounded by the base docstring contract
- [ ] `test_store_cas.py::store` fixture — real SQLite plane, mirroring `test_sqlite_policy.py`
- [ ] `test_store_cas.py::test_read_only_store_refuses` — bounded by `store.py:930`
- [ ] `test_store_cas.py::test_base_default_raises_not_implemented` — bounded by spec §2

---

## Acceptance Criteria

- [ ] `BaseWikiStore.compare_and_swap_page` is **concrete** (not `@abstractmethod`) and raises `NotImplementedError`
- [ ] A `BaseWikiStore` subclass that does not override it is still instantiable
- [ ] `expected_content_hash=None` inserts when absent and returns `False` when present
- [ ] A matching hash replaces; a differing or missing row returns `False` and leaves the stored row untouched (AC6)
- [ ] Compare and write occur in one `_write` transaction — no `SELECT` outside it
- [ ] A read-only store raises `PermissionError`
- [ ] `store.py` gains no import from `parrot.knowledge.wiki.decisions`
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_policy.py -q` still passes (AC10)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_cas.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_policy.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_fts_external_content.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "Identity, storage, and concurrency" and §9 finding A4.
2. **Verify the Codebase Contract** — re-check `store.py:608`, `:1109`, `:1449`, `:1514`.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** all three Validation Commands pass — the last two are the AC10 regression guard.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-coder (native, backend=native, model=sonnet), orchestrated by sdd-worker
**Date**: 2026-09-19
**Notes**: Added concrete `BaseWikiStore.compare_and_swap_page` (raises `NotImplementedError`,
not abstract, so third-party subclasses stay instantiable) and `SQLiteWikiStore`'s atomic
override inside a single `_write` `BEGIN IMMEDIATE` transaction. Verified no import of
`parrot.knowledge.wiki.decisions` was introduced (grep-confirmed). Touched only the two
blueprint-specified insertion points in `store.py`; `file_store.py`/`arango_store.py`/
`postgres_store.py` left untouched for sibling tasks TASK-3482/3483/3484.
`pytest test_store_cas.py`: 7 passed. AC10 regression guards: `test_sqlite_policy.py`: 10
passed; `test_sqlite_fts_external_content.py`: 17 passed. Merge-tier: full wiki-scoped suite
(excluding known no-DB `test_postgres_store.py`/`test_postgres_symbols.py`) re-run after merge.
Post-merge lint left 1 pre-existing residual (`B027` on `_assert_writable`, unrelated to this
task's diff) — deferred to `/sdd-done` per policy, not fixed here.
Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 417.9s · Tokens: 126452 (subagent total, in/out not separately reported by native path)

**Deviations from spec**: none
