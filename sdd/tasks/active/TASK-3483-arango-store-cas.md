# TASK-3483: `compare_and_swap_page` on `ArangoDBWikiStore`

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3481
**Assigned-to**: unassigned

---

## Context

Module 2. Spec §2 requires all four built-in backends to implement the CAS
primitive, with ArangoDB using *"an atomic document revision precondition"* and
handling its conflicts. AC8 makes backend parity behavioral, not just a JSON
round-trip — and explicitly says a missing live-backend validation must be
**reported** and blocks declaring parity complete, rather than being silently
skipped.

---

## Scope

- Implement `compare_and_swap_page` on `ArangoDBWikiStore` as a single atomic
  server-side operation with a revision/hash precondition.
- Map Arango's conflict response to a `False` return, not an exception.
- Honour the existing `read_only` property.
- Test against a live ArangoDB when credentials are present; **skip with an
  explicit reason** otherwise, so AC8's reporting requirement is satisfiable.

**NOT in scope**: the base default and SQLite (TASK-3481, a dependency), the
file backend (TASK-3482), Postgres (TASK-3484), any ADR model or error code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` | MODIFY | `compare_and_swap_page` with a revision precondition |
| `packages/ai-parrot/tests/knowledge/wiki/test_arango_store_cas.py` | CREATE | Live-fixture CAS contract + explicit skip reporting |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Everything needed is already imported by `arango_store.py`. Add **no** import
from `parrot.knowledge.wiki.decisions`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py:135
class ArangoDBWikiStore(BaseWikiStore):
    @property
    def read_only(self) -> bool: ...                        # line 199
    async def _ensure_init(self) -> None: ...               # used by upsert_pages
    def _assert_writable(self) -> None: ...                 # inherited/overridden
    async def _execute(self, aql: str, bind_vars: dict) -> Any: ...  # used at line 562
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...  # line 517
    async def delete_page(self, concept_id: str) -> bool: ...              # line 677
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...  # line 732

# module-level, same file
PAGES_COLLECTION        # collection name bound as @@collection at line 563
def document_key(concept_id: str) -> str: ...   # used at line 533
```

`upsert_pages` (line 517-563) is the pattern to mirror: `_assert_writable()` →
`_ensure_init()` → build the doc dict (the exact field list is at lines 531-548)
→ one `await self._execute(aql, bind_vars)`.

### Does NOT Exist

- ~~a `revision` field on the Arango page document~~ — the document fields are
  exactly those at `arango_store.py:531-548` (`_key`, `concept_id`, `node_id`,
  `title`, `category`, `summary`, `body`, `source_id`, `token_count`, `origin`,
  `asserted_by`, `content_hash`, `created_at`, `updated_at`). The precondition
  is Arango's own `_rev`, or `content_hash`.
- ~~a two-statement read-then-write CAS~~ — spec §2 forbids emulating CAS as an
  unlocked read followed by a write. It must be one server-side operation.
- ~~`python-arango` imported at module scope~~ — check how `arango_store.py`
  actually obtains its driver before importing an exception class from it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_arango_store_cas.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py#ArangoDBWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- One server-side statement. Either a single AQL that filters on the current
  `content_hash` before writing, or an `UPDATE ... OPTIONS {ignoreRevs: false}`
  carrying a `_rev` read in the same statement. Not two round trips.
- A conflict (`ARANGO_CONFLICT` / unique-key violation on the insert path)
  returns `False`. Only genuine failures propagate.
- `expected_content_hash=None` is insert-only and must fail when the document
  exists — an `UPSERT` would silently update instead, which is wrong here.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py:517-563` — the
  doc-dict shape and `_execute` call convention to mirror exactly.
- `packages/ai-parrot/tests/knowledge/wiki/test_arango_document_key.py` — the
  existing Arango test's skip/fixture convention.

---

## Implementation Blueprint

### Steps (in order)

1. Read `upsert_pages` at `arango_store.py:517-563` and copy its doc-dict
   construction verbatim — *why*: a CAS that writes a different field set would
   silently drop columns the rest of the wiki reads.
2. Write the single-statement CAS — *why*: spec §2 forbids an unlocked
   read-then-write, and Arango offers no transaction handle here.
3. Write the live-fixture tests with an explicit skip reason — *why*: AC8
   requires a missing live backend to be **reported**, not silently green.

### `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:' packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py)
# AFTER — insert directly below the end of `async def upsert_pages`
# (verified: packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py:517,
# whose last statement is `        return len(pages)` at line 563), i.e.
# immediately before `    async def add_edges(self, edges: list[tuple]) -> int:`
# at line 565:

    async def compare_and_swap_page(
        self,
        page: WikiPageRecord,
        expected_content_hash: Optional[str],
    ) -> bool:
        """Conditionally write one page with a document revision precondition.

        See :meth:`BaseWikiStore.compare_and_swap_page` for the contract.
        Executed as ONE server-side operation — an unlocked read followed by
        a write would reintroduce exactly the race this primitive closes.
        """
        self._assert_writable()
        await self._ensure_init()
        now = _now_iso()
        doc = {
            # FILL IN: the SAME field dict `upsert_pages` builds at
            # arango_store.py:531-548, for this single `page` — bounded by
            # "a CAS must not write a narrower document than upsert_pages"
        }
        # FILL IN: choose and implement ONE atomic precondition strategy —
        # either a single AQL that reads the current doc and FILTERs on
        # `content_hash == @expected` (with the @expected IS NULL branch
        # requiring absence) before INSERT/UPDATE, or an UPDATE with
        # OPTIONS {ignoreRevs: false} carrying the `_rev` read in the same
        # statement. Bounded by spec §2 "Arango uses an atomic document
        # revision precondition and handles conflicts" and by the requirement
        # that a lost race RETURNS False rather than raising.
        raise NotImplementedError
```

**Why**: `_assert_writable()` first means a read-only plane raises before any
network call, matching `upsert_pages` (`arango_store.py:524`). Reusing the exact
doc dict keeps `created_at`/`updated_at` semantics identical across write paths.
The `bool` return is the contract TASK-3485 maps to `ADR_REVISION_CONFLICT`; do
not raise a driver exception through it.

### `packages/ai-parrot/tests/knowledge/wiki/test_arango_store_cas.py` (CREATE)

```python
"""ArangoDB CAS contract against a live plane (FEAT-578 M2, AC8)."""

from __future__ import annotations

import os

import pytest

from parrot.knowledge.wiki.store import WikiPageRecord

#: AC8 requires a MISSING live backend to be reported, not silently green.
#: The reason string is asserted on by the parity test in TASK-3497.
SKIP_REASON = "ArangoDB live fixture unavailable: set ARANGODB_HOST/ARANGODB_PASSWORD to validate AC8 parity"

pytestmark = pytest.mark.skipif(not os.getenv("ARANGODB_HOST"), reason=SKIP_REASON)


def _page(body: str = "v1", content_hash: str = "h1") -> WikiPageRecord:
    return WikiPageRecord(concept_id="adr:doc:a", title="t", category="adr", body=body, content_hash=content_hash)


@pytest.fixture
async def store():
    """A live ArangoDB plane on a throwaway database."""
    # FILL IN: build ArangoDBWikiStore against a uniquely-named test database
    # following test_arango_document_key.py's fixture convention; yield it,
    # then drop the database — bounded by "tests must not share state"
    raise NotImplementedError


class TestCasInsertUpdateConflict:
    async def test_insert_when_absent(self, store):
        assert await store.compare_and_swap_page(_page(), None) is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_insert_refuses_when_present(self, store):
        """expected=None must NOT behave like an UPSERT."""
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page("v2", "h2"), None) is False
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_replace_on_matching_hash(self, store):
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page("v2", "h2"), "h1") is True

    async def test_conflict_returns_false_not_raises(self, store):
        """A lost race is a False return — the driver's error never escapes."""
        await store.compare_and_swap_page(_page(), None)
        await store.compare_and_swap_page(_page("winner", "h2"), "h1")
        assert await store.compare_and_swap_page(_page("loser", "h3"), "h1") is False
        assert (await store.get_page("adr:doc:a"))["body"] == "winner"

    async def test_full_record_roundtrips(self, store):
        """Every page field written by upsert_pages survives a CAS write."""
        # FILL IN: CAS a page with every field populated, read it back, and
        # assert each field matches — bounded by AC8 "full record roundtrip"
        raise NotImplementedError

    async def test_read_only_store_refuses(self):
        """read_only=True raises before any network call."""
        # FILL IN: build a read-only ArangoDBWikiStore and assert PermissionError
        # — bounded by arango_store.py:199
        raise NotImplementedError


async def test_concurrent_cas_has_exactly_one_winner(store):
    """AC6/AC8: two concurrent writers from the same read — one wins."""
    # FILL IN: insert a base page, then asyncio.gather two compare_and_swap_page
    # calls both expecting "h1"; assert exactly one True and one False, and that
    # the stored body belongs to the winner — bounded by AC6
    raise NotImplementedError
```

**Why**: `test_concurrent_cas_has_exactly_one_winner` is the behavioral half of
AC8 — a JSON round-trip alone would pass even with a non-atomic implementation.

### FILL IN checklist

- [ ] `arango_store.py::compare_and_swap_page` — doc dict copied from `upsert_pages` (`:531-548`)
- [ ] `arango_store.py::compare_and_swap_page` — the single-statement precondition; bounded by spec §2
- [ ] `test_arango_store_cas.py::store` fixture — throwaway database, mirroring `test_arango_document_key.py`
- [ ] `test_arango_store_cas.py::test_full_record_roundtrips` — bounded by AC8
- [ ] `test_arango_store_cas.py::test_read_only_store_refuses` — bounded by `arango_store.py:199`
- [ ] `test_arango_store_cas.py::test_concurrent_cas_has_exactly_one_winner` — bounded by AC6

---

## Acceptance Criteria

- [ ] `compare_and_swap_page` is one server-side operation — no read-then-write round trip (spec §2)
- [ ] Insert-if-absent, matching-hash replace and stale-hash conflict behave per the base contract
- [ ] A conflict returns `False`; no driver exception escapes
- [ ] A `read_only=True` store raises `PermissionError`
- [ ] Two concurrent CAS calls from the same read yield exactly one winner (AC6)
- [ ] Without `ARANGODB_HOST` the suite **skips with `SKIP_REASON`**, so the gap is visible (AC8)
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/test_arango_document_key.py -q` still passes (AC10)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_arango_store_cas.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_arango_document_key.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "Identity, storage, and concurrency" and AC8.
2. **Verify the Codebase Contract** — re-read `arango_store.py:517-563` before copying the doc dict.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** both Validation Commands pass. If ArangoDB is unavailable, record
   the skip explicitly in the Completion Note — AC8 forbids reporting parity as
   complete on a skipped backend.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
