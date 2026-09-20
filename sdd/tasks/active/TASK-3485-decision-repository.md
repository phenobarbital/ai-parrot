# TASK-3485: `DecisionRepository` — bounded inventory and CAS-backed save

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3480, TASK-3481
**Assigned-to**: unassigned

---

## Context

Module 2's service-facing half. It is the **only** place the decisions package
touches a store, so `store.py` never learns about ADRs and the ADR code never
writes a page any other way. It also owns the store→error-code mapping:
`compare_and_swap_page` returns a bare `False` and raises `NotImplementedError`
or `PermissionError`; this class turns those into `ADR_REVISION_CONFLICT`,
`ADR_WRITE_UNSUPPORTED` and `ADR_READ_ONLY`.

---

## Scope

- Implement `DecisionRepository.inventory()` — bounded full load via
  `list_pages(category='adr', limit=max_records + 1)`, hydrating full pages,
  failing with `ADR_INVENTORY_LIMIT` rather than returning a silently
  incomplete "no decisions" answer.
- Implement `DecisionRepository.save(record, expected_content_hash)` on top of
  the CAS primitive, with the full store→`DecisionError` mapping.
- Implement `get(decision_id)` returning the record **and** the page hash the
  caller must pass back to `save` on the next write.
- Unit-test the bound, the conflict, and the unsupported/read-only backends.

**NOT in scope**: parsing (TASK-3486), retrieval ranking (TASK-3490), review
semantics (TASK-3492), any CLI or tool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py` | CREATE | Bounded inventory + CAS save + error mapping |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py` | CREATE | Bound, conflict, unsupported, read-only |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord  # store.py:525, :409
from parrot.knowledge.wiki.decisions.codec import decision_from_page, decision_to_page  # TASK-3480
from parrot.knowledge.wiki.decisions.models import (  # TASK-3479
    ADR_CATEGORY, ADR_INVENTORY_LIMIT, ADR_READ_ONLY, ADR_REVISION_CONFLICT,
    ADR_SCHEMA_UNSUPPORTED, ADR_WRITE_UNSUPPORTED, DecisionError, DecisionRecord,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):
    async def list_pages(self, category: Optional[str] = None, limit: int = 100,
                         origin: Optional[list[str]] = None) -> list[dict[str, Any]]: ...   # line 568
    async def get_page(self, concept_id: str, include_body: bool = True
                       ) -> Optional[dict[str, Any]]: ...                                    # line 565
    async def compare_and_swap_page(self, page: WikiPageRecord,
                                    expected_content_hash: Optional[str]) -> bool: ...       # TASK-3481, store.py:608 block
```

**`list_pages` may omit page bodies** — the returned dicts are stubs on some
backends. The envelope lives in the body, so every id from `list_pages` must be
re-read with `get_page(cid, include_body=True)` before decoding.

`compare_and_swap_page` raises `NotImplementedError` on an unsupported backend
and `PermissionError` on a read-only one; it returns `False` for a lost race.

### Does NOT Exist

- ~~a persistent ADR index or cache~~ — spec §2: "no persistent cache without an
  invalidation contract". The inventory is rebuilt per call, by design; that is
  v1's stated performance tradeoff.
- ~~`store.list_pages(..., category="adr")` returning `DecisionRecord`s~~ — it
  returns `list[dict[str, Any]]`.
- ~~a store-level revision counter~~ — the precondition is the page
  `content_hash` computed by `decision_to_page` (TASK-3480).
- ~~`store.delete_page` as a review action~~ — spec §2: "Generic deletion is not
  an ADR review action." Do not expose a delete here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- `limit=max_records + 1` is the overflow probe: getting back more than
  `max_records` rows means the inventory is not fully representable, so raise
  `ADR_INVENTORY_LIMIT`. Never truncate to `max_records` and answer anyway.
- A single page that fails to decode must **not** sink the whole inventory —
  collect it as a diagnostic and continue (spec §2: "expected diagnostics in
  batch reads/sync remain in typed outputs").
- Async throughout; `self.logger = logging.getLogger(__name__)`.

---

## Implementation Blueprint

### Steps (in order)

1. Implement `get` first — *why*: `save` and every reviewer need the
   `(record, page_hash)` pair, and returning the hash from the same read is what
   makes the later CAS honest.
2. Implement `inventory` with the `+1` probe — *why*: a bound that is checked
   after truncation cannot distinguish "exactly at the bound" from "over it".
3. Implement `save` and its exception mapping — *why*: mapping at this single
   seam keeps `DecisionError` out of `store.py` entirely.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py` (CREATE)

```python
"""Store-facing persistence for ADR records (FEAT-578 Module 2).

The only module in ``decisions/`` that touches a :class:`BaseWikiStore`, and
the only place the store's raw failures become typed :class:`DecisionError`
codes. Every ADR mutation in the feature goes through :meth:`save`.
"""

from __future__ import annotations

import logging
from typing import Any

from parrot.knowledge.wiki.decisions.codec import decision_from_page, decision_to_page
from parrot.knowledge.wiki.decisions.models import (
    ADR_CATEGORY,
    ADR_INVENTORY_LIMIT,
    ADR_READ_ONLY,
    ADR_REVISION_CONFLICT,
    ADR_WRITE_UNSUPPORTED,
    DecisionDiagnostic,
    DecisionError,
    DecisionRecord,
)
from parrot.knowledge.wiki.store import BaseWikiStore


class DecisionRepository:
    """Bounded ADR inventory reads and compare-and-swap writes."""

    def __init__(self, store: BaseWikiStore, max_records: int = 10_000) -> None:
        """Bind a backend without bypassing its read-only policy.

        Args:
            store: Any wiki backend. A read-only or CAS-less store is
                accepted here and refused at write time, so reads keep
                working on a foreign or archived plane.
            max_records: Inventory bound from ``DecisionConfig.max_records``.
        """
        self._store = store
        self._max_records = max_records
        self.logger = logging.getLogger(__name__)
        #: Decode failures from the last ``inventory()`` call, surfaced by the
        #: service as dossier diagnostics rather than raised.
        self.last_diagnostics: list[DecisionDiagnostic] = []

    async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None:
        """Load one record together with the page hash to CAS against.

        Returns:
            ``(record, content_hash)``, or ``None`` when no such page
            exists. Pass the returned hash straight back to :meth:`save`
            as ``expected_content_hash`` — reading it from anywhere else
            reopens the race this class exists to close.

        Raises:
            DecisionError: ``ADR_SCHEMA_UNSUPPORTED`` when the page exists
                but is not a decodable managed record.
        """
        page = await self._store.get_page(decision_id, include_body=True)
        if page is None:
            return None
        return decision_from_page(page), page.get("content_hash")

    async def inventory(self) -> list[DecisionRecord]:
        """Load the complete bounded ADR inventory.

        Reads ``limit=max_records + 1`` so an overflow is detectable rather
        than silently truncated into a wrong "no decisions" answer.

        Raises:
            DecisionError: ``ADR_INVENTORY_LIMIT`` when the plane holds more
                than ``max_records`` ADR pages.
        """
        self.last_diagnostics = []
        stubs = await self._store.list_pages(category=ADR_CATEGORY, limit=self._max_records + 1)
        if len(stubs) > self._max_records:
            raise DecisionError(
                ADR_INVENTORY_LIMIT,
                f"ADR inventory exceeds max_records={self._max_records}; raise the bound or prune records",
            )
        # FILL IN: for each stub, re-read the full page with
        # get_page(cid, include_body=True) — list_pages may omit bodies — decode
        # it, and on DecisionError append a DecisionDiagnostic to
        # self.last_diagnostics and SKIP that record instead of raising.
        # Bounded by spec §2 "hydrate full pages" and "expected diagnostics in
        # batch reads remain in typed outputs".
        raise NotImplementedError

    async def save(self, record: DecisionRecord, expected_content_hash: str | None) -> DecisionRecord:
        """CAS one full record and its audit history.

        Args:
            record: The complete replacement record, audit history included.
                Partial writes do not exist — the page body is the record.
            expected_content_hash: The hash returned by :meth:`get`, or
                ``None`` to insert a record that must not already exist.

        Returns:
            The record as written.

        Raises:
            DecisionError: ``ADR_REVISION_CONFLICT`` when the precondition
                did not hold, ``ADR_WRITE_UNSUPPORTED`` on a backend without
                a conditional write, ``ADR_READ_ONLY`` on a read-only plane,
                ``ADR_RECORD_TOO_LARGE`` from the codec.
        """
        page = decision_to_page(record)
        try:
            ok = await self._store.compare_and_swap_page(page, expected_content_hash)
        except NotImplementedError as exc:
            raise DecisionError(
                ADR_WRITE_UNSUPPORTED,
                f"backend {type(self._store).__name__} has no conditional page write",
                decision_id=record.decision_id,
            ) from exc
        except PermissionError as exc:
            raise DecisionError(ADR_READ_ONLY, str(exc), decision_id=record.decision_id) from exc
        if not ok:
            raise DecisionError(
                ADR_REVISION_CONFLICT,
                f"{record.decision_id} changed since it was read; re-read and retry the review",
                decision_id=record.decision_id,
            )
        self.logger.debug("save: wrote %s revision %s", record.decision_id, record.revision)
        return record
```

**Why this shape**: `get` returns the hash alongside the record because any
other source for that hash (a second read, a cached page) reopens the race. The
`save` mapping is a translation layer only — it adds no retry, because spec §2
says "no automatic review overwrite/retry". `inventory` collecting decode
failures instead of raising is what keeps one corrupt page from making the whole
wiki answer "no decisions", which spec §2 calls out by name.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py` (CREATE)

```python
"""DecisionRepository bounds, conflicts and backend policy (FEAT-578 M2)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.codec import decision_to_page
from parrot.knowledge.wiki.decisions.models import DecisionError, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository


@pytest.fixture
def record() -> DecisionRecord:
    """A minimal valid documented record."""
    return DecisionRecord(decision_id="adr:doc:a", decision="use pgvector", origin="documented")


@pytest.fixture
async def store(tmp_path):
    """A real file-backed plane — CAS semantics must be genuine (TASK-3482)."""
    from parrot.knowledge.wiki.file_store import InMemoryWikiStore

    return InMemoryWikiStore(tmp_path / "pages", wiki_name="t")


class TestSave:
    async def test_insert_then_conflict(self, store, record):
        """A second insert of the same id is ADR_REVISION_CONFLICT."""
        repo = DecisionRepository(store)
        await repo.save(record, None)
        with pytest.raises(DecisionError) as exc:
            await repo.save(record, None)
        assert exc.value.code == "ADR_REVISION_CONFLICT"
        assert exc.value.decision_id == "adr:doc:a"

    async def test_round_trip_through_get(self, store, record):
        """get() returns the record and the hash save() needs next."""
        repo = DecisionRepository(store)
        await repo.save(record, None)
        loaded, page_hash = await repo.get("adr:doc:a")
        assert loaded == record
        assert page_hash == decision_to_page(record).content_hash
        # FILL IN: bump the record's revision and save with `page_hash`;
        # assert it succeeds, then assert saving again with the SAME stale
        # page_hash raises ADR_REVISION_CONFLICT — bounded by AC6
        raise NotImplementedError

    async def test_get_missing_returns_none(self, store):
        assert await DecisionRepository(store).get("adr:doc:nope") is None

    async def test_unsupported_backend_is_typed(self, record):
        """A CAS-less backend yields ADR_WRITE_UNSUPPORTED, not NotImplementedError."""
        # FILL IN: build a stub store whose compare_and_swap_page raises
        # NotImplementedError; assert DecisionError.code == "ADR_WRITE_UNSUPPORTED"
        raise NotImplementedError

    async def test_read_only_backend_is_typed(self, record):
        """A read-only plane yields ADR_READ_ONLY, not PermissionError."""
        # FILL IN: stub store raising PermissionError; assert code ADR_READ_ONLY
        raise NotImplementedError


class TestInventory:
    async def test_returns_all_records(self, store):
        """Every stored ADR page is hydrated and decoded."""
        # FILL IN: save three records, assert inventory() returns all three
        raise NotImplementedError

    async def test_exceeding_the_bound_is_an_explicit_error(self, store, record):
        """Never a silently incomplete 'no decisions' answer (spec §2, AC14)."""
        repo = DecisionRepository(store, max_records=2)
        # FILL IN: save 3 records, then assert DecisionError.code ==
        # "ADR_INVENTORY_LIMIT" — bounded by AC14
        raise NotImplementedError

    async def test_at_the_bound_still_succeeds(self, store):
        """max_records records is fine; max_records + 1 is not."""
        # FILL IN: with max_records=2, save exactly 2 and assert inventory() works
        raise NotImplementedError

    async def test_one_corrupt_page_becomes_a_diagnostic(self, store, record):
        """A single bad page must not blank the whole inventory."""
        # FILL IN: save one good record, then upsert_pages a page with
        # category="adr" and a garbage body; assert inventory() returns the good
        # record and repo.last_diagnostics has one entry with code
        # ADR_SCHEMA_UNSUPPORTED — bounded by spec §2 batch-read diagnostics
        raise NotImplementedError

    async def test_hydrates_bodies_even_when_list_pages_omits_them(self, record):
        """list_pages stubs are not decodable — get_page must be called."""
        # FILL IN: stub store whose list_pages returns rows with body="" and
        # whose get_page returns the full page; assert inventory() decodes it
        raise NotImplementedError
```

### FILL IN checklist

- [ ] `repository.py::inventory` — hydrate + per-page diagnostic collection; bounded by spec §2
- [ ] `test_repository.py::test_round_trip_through_get` — stale-hash conflict; bounded by AC6
- [ ] `test_repository.py::test_unsupported_backend_is_typed` / `test_read_only_backend_is_typed`
- [ ] `test_repository.py` — five `TestInventory` bodies; bounded by AC14 and spec §2

---

## Acceptance Criteria

- [ ] `inventory()` reads with `limit=max_records + 1` and raises `ADR_INVENTORY_LIMIT` on overflow (AC14)
- [ ] Exactly `max_records` records still succeeds
- [ ] Each inventory entry is re-read with `include_body=True` before decoding
- [ ] One undecodable page becomes a diagnostic; the rest of the inventory is returned
- [ ] `get()` returns `(record, content_hash)`; that hash drives the next `save`
- [ ] `save()` maps `False` → `ADR_REVISION_CONFLICT`, `NotImplementedError` → `ADR_WRITE_UNSUPPORTED`, `PermissionError` → `ADR_READ_ONLY`
- [ ] `save()` performs **no** retry (spec §2)
- [ ] No `delete` surface is exposed (spec §2: deletion is not a review action)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py -q`

---

## Agent Instructions

1. **Read the spec** §2 Module 2 and "Retrieval and freshness" (inventory bound).
2. **Verify the Codebase Contract** — confirm `list_pages` / `get_page` signatures at `store.py:565-580`.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** the Validation Command passes.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
