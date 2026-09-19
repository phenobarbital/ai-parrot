# TASK-3484: `compare_and_swap_page` on `PostgresWikiStore`

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3481
**Assigned-to**: unassigned

---

## Context

Module 2, fourth backend. Spec §2: *"Postgres uses a conditional update or
absent-only insert"*. This backend is bitemporal — `_upsert_page` closes the
open `node_versions` row (`validity = tstzrange(lower(validity), now())`) and
inserts a new one. The CAS precondition is therefore evaluated against the
**currently open** version row, and the whole compare-and-write must sit inside
one `conn.transaction()` with the row locked.

Spec §6 is explicit that Postgres is **not** a selectable project backend
(`WikiProjectConfig.backend` stays `sqlite|memory|arangodb`); it is supported
for directly instantiated stores only. Do not widen the config Literal here.

---

## Scope

- Implement `compare_and_swap_page` on `PostgresWikiStore` inside one
  transaction, locking the open version row before comparing.
- Return `False` on a lost race; raise only on genuine failures.
- Test against a live Postgres when credentials are present; **skip with an
  explicit reason** otherwise (AC8 reporting requirement).

**NOT in scope**: the base default and SQLite (TASK-3481, a dependency), the
file backend (TASK-3482), Arango (TASK-3483), **and any change to
`WikiProjectConfig.backend`**.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py` | MODIFY | Transactional `compare_and_swap_page` |
| `packages/ai-parrot/tests/knowledge/wiki/test_postgres_store_cas.py` | CREATE | Live-fixture CAS contract + explicit skip reporting |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Everything needed is already imported by `postgres_store.py`. Add **no** import
from `parrot.knowledge.wiki.decisions`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py:127
class PostgresWikiStore(BaseWikiStore):
    def __init__(self, ..., wiki_name: str = "", ...) -> None: ...   # line 149
        self._wiki_name: str                                          # line 158
        self._schema: str            # schema-qualifies every statement
    async def _ensure_pool(self) -> asyncpg.Pool: ...                 # line 166
    async def _upsert_page(self, conn: asyncpg.Connection, page: WikiPageRecord) -> None: ...  # line 187
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...  # line 293
    async def delete_page(self, concept_id: str) -> bool: ...              # line 419
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...  # line 496
```

Verified schema facts from `_upsert_page` (`postgres_store.py:187-235`):

- `{schema}.nodes` — identity, `ON CONFLICT (concept_id) DO UPDATE`, carries
  `namespace` (= `self._wiki_name`), `category`, `node_id`, `lang`.
- `{schema}.node_versions` — versions, with `validity tstzrange`. The **open**
  row is the one matching `upper_inf(validity)`. Columns include
  `concept_id, title, summary, body, source_id, content_hash, token_count,
  origin, asserted_by, updated_at, fts`.
- `upsert_pages` (line 293) wraps its per-page calls in
  `async with pool.acquire() as conn: async with conn.transaction():`.

### Does NOT Exist

- ~~an in-place `UPDATE` of a page row~~ — this backend is close-and-insert. A
  CAS that updates the open row in place would destroy the version history.
- ~~`WikiProjectConfig.backend == "postgres"`~~ — the Literal is
  `sqlite|memory|arangodb` (`project.py:414`). Spec §6: "Do not promise a new
  project backend selector." Out of scope here.
- ~~`PostgresWikiStore.read_only`~~ — no read-only mode on this backend;
  `_assert_writable` resolves to the base no-op (`store.py:610`).
- ~~a global `content_hash` uniqueness constraint~~ — none. The precondition is
  the open version row's value, scoped by `concept_id`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_postgres_store_cas.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py#PostgresWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Compare and write inside **one** `conn.transaction()`, with the open version
  row selected `FOR UPDATE` so a concurrent writer blocks rather than
  interleaving.
- Reuse `_upsert_page` for the write, so `nodes`, the close-out `UPDATE`, and
  the `fts` tsvector all stay identical to the ordinary path.
- Scope everything by `self._wiki_name` where `_upsert_page` does — a shared
  schema hosts several wikis (`postgres_store.py:13-15`, `:342`).
- `expected_content_hash=None` means **no open version row exists**.
- No schema migration: spec §2 Module 2 says "No schema migration."

---

## Implementation Blueprint

### Steps (in order)

1. Re-read `_upsert_page` (`postgres_store.py:187-235`) — *why*: the CAS write
   must be that exact sequence, or the version history and FTS drift.
2. Write the precondition `SELECT ... FOR UPDATE` on the open row — *why*: the
   row lock, not the isolation level, is what serializes two reviewers.
3. Delegate the write to `_upsert_page` — *why*: one write path, one place to
   fix when the schema changes.

### `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:' packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py)
# AFTER — insert directly below the end of `async def upsert_pages`
# (verified: packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py:293,
# whose last statement is `        return len(pages)` at line 309), i.e.
# immediately before `    async def add_edges(self, edges: list[tuple]) -> int:`
# at line 311:

    async def compare_and_swap_page(
        self,
        page: WikiPageRecord,
        expected_content_hash: Optional[str],
    ) -> bool:
        """Conditionally write one page against its open version row's hash.

        See :meth:`BaseWikiStore.compare_and_swap_page` for the contract.
        The compare and the close-and-insert share one transaction, and the
        open ``node_versions`` row is locked ``FOR UPDATE`` first, so a
        concurrent reviewer blocks instead of interleaving.
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    SELECT v.content_hash
                    FROM {self._schema}.node_versions v
                    JOIN {self._schema}.nodes n ON n.concept_id = v.concept_id
                    WHERE v.concept_id = $1
                      AND n.namespace = $2
                      AND upper_inf(v.validity)
                    FOR UPDATE OF v
                    """,
                    page.concept_id,
                    self._wiki_name,
                )
                # FILL IN: evaluate the precondition and `return False` when it
                # fails — bounded by BaseWikiStore.compare_and_swap_page:
                #   expected is None     -> `row` must be None
                #   expected is not None -> row is not None and
                #                           row["content_hash"] == expected
                # Returning inside `conn.transaction()` commits the (empty)
                # transaction, which is correct: nothing was written.
                raise NotImplementedError
                await self._upsert_page(conn, page)
        self.logger.debug("compare_and_swap_page: wrote %s", page.concept_id)
        return True
```

**Why**: joining `nodes` and filtering `n.namespace = $2` mirrors
`replace_source_slice` (`postgres_store.py:342`) — without it, one wiki's CAS
could read (and lock) another wiki's row in a shared schema. `FOR UPDATE OF v`
locks only the version row, not the shared `nodes` identity row. Delegating to
`_upsert_page` keeps the close-and-insert and the `fts` tsvector in one place.
Do not add a schema migration and do not touch `WikiProjectConfig`.

### `packages/ai-parrot/tests/knowledge/wiki/test_postgres_store_cas.py` (CREATE)

```python
"""PostgresWikiStore CAS contract against a live plane (FEAT-578 M2, AC8)."""

from __future__ import annotations

import asyncio
import os

import pytest

from parrot.knowledge.wiki.store import WikiPageRecord

#: AC8 requires a MISSING live backend to be reported, not silently green.
SKIP_REASON = "Postgres live fixture unavailable: set the wiki Postgres DSN env to validate AC8 parity"

pytestmark = pytest.mark.skipif(not os.getenv("WIKI_POSTGRES_DSN"), reason=SKIP_REASON)


def _page(body: str = "v1", content_hash: str = "h1") -> WikiPageRecord:
    return WikiPageRecord(concept_id="adr:doc:a", title="t", category="adr", body=body, content_hash=content_hash)


@pytest.fixture
async def store():
    """A live Postgres plane on a throwaway schema."""
    # FILL IN: build PostgresWikiStore following
    # packages/ai-parrot/tests/knowledge/wiki/test_postgres_store.py's existing
    # fixture (same DSN env var and schema-teardown convention); yield, then
    # drop the schema — bounded by "tests must not share state"
    raise NotImplementedError


class TestCasInsertUpdateConflict:
    async def test_insert_when_absent(self, store):
        assert await store.compare_and_swap_page(_page(), None) is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_insert_refuses_when_present(self, store):
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page("v2", "h2"), None) is False
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_replace_on_matching_hash(self, store):
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page("v2", "h2"), "h1") is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v2"

    async def test_conflict_leaves_open_row_intact(self, store):
        await store.compare_and_swap_page(_page(), None)
        await store.compare_and_swap_page(_page("winner", "h2"), "h1")
        assert await store.compare_and_swap_page(_page("loser", "h3"), "h1") is False
        assert (await store.get_page("adr:doc:a"))["body"] == "winner"

    async def test_version_history_is_preserved(self, store):
        """Close-and-insert, not in-place update: the old version survives."""
        # FILL IN: after two successful CAS writes, query node_versions for this
        # concept_id and assert there are 2 rows, exactly one with
        # upper_inf(validity) — bounded by "this backend is close-and-insert"
        raise NotImplementedError

    async def test_full_record_roundtrips(self, store):
        """Every page field written by _upsert_page survives a CAS write."""
        # FILL IN: CAS a fully populated page, read it back, assert field parity
        # — bounded by AC8 "full record roundtrip"
        raise NotImplementedError


async def test_concurrent_cas_has_exactly_one_winner(store):
    """AC6/AC8: two writers from the same read — exactly one lands."""
    await store.compare_and_swap_page(_page(), None)
    results = await asyncio.gather(
        store.compare_and_swap_page(_page("a", "h2"), "h1"),
        store.compare_and_swap_page(_page("b", "h3"), "h1"),
    )
    assert sorted(results) == [False, True]
    # FILL IN: assert the stored body belongs to whichever call returned True
    raise NotImplementedError
```

### FILL IN checklist

- [ ] `postgres_store.py::compare_and_swap_page` — precondition branches; bounded by the base docstring
- [ ] `test_postgres_store_cas.py::store` fixture — throwaway schema, mirroring `test_postgres_store.py`
- [ ] `test_postgres_store_cas.py::test_version_history_is_preserved` — bounded by close-and-insert
- [ ] `test_postgres_store_cas.py::test_full_record_roundtrips` — bounded by AC8
- [ ] `test_postgres_store_cas.py::test_concurrent_cas_has_exactly_one_winner` — winner assertion; bounded by AC6

---

## Acceptance Criteria

- [ ] Compare and write share one `conn.transaction()`, with the open version row locked `FOR UPDATE`
- [ ] The precondition is scoped by `self._wiki_name` (shared-schema safety)
- [ ] Insert-if-absent, matching-hash replace and stale-hash conflict behave per the base contract
- [ ] The write delegates to `_upsert_page` — version history is preserved, not overwritten
- [ ] Two concurrent CAS calls from the same read yield exactly one winner (AC6)
- [ ] `WikiProjectConfig.backend` is **unchanged** (spec §6)
- [ ] No schema migration is added
- [ ] Without the DSN env the suite **skips with `SKIP_REASON`**, so the gap is visible (AC8)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_postgres_store_cas.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_postgres_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_postgres_symbols.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "Identity, storage, and concurrency", §6 "Does NOT Exist", and AC8.
2. **Verify the Codebase Contract** — re-read `postgres_store.py:187-235` and `:293-309`.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** all three Validation Commands pass. If Postgres is unavailable,
   record the skip explicitly in the Completion Note — AC8 forbids reporting
   parity as complete on a skipped backend.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-coder (native, backend=native, model=haiku), orchestrated by sdd-worker
**Date**: 2026-09-19
**Notes**: Implemented `PostgresWikiStore.compare_and_swap_page` exactly per blueprint — single
`conn.transaction()` with `FOR UPDATE OF v` on the open `node_versions` row, precondition
evaluated against `content_hash` (None=insert-only, else must match), namespace-scoped by
`self._wiki_name` (mirrors `replace_source_slice`'s join pattern), write delegated to
`_upsert_page` to preserve close-and-insert version history. No `WikiProjectConfig.backend`
change, no schema migration, no import from `parrot.knowledge.wiki.decisions`.
Orchestrator verification: this sandbox has no live Postgres route (`OSError: [Errno 113] No
route to host`, identical to the pre-existing `test_postgres_store.py` failures verified after
TASK-3480/3481) — `WIKI_POSTGRES_DSN` is set in this environment but unreachable, so the test's
own `skipif` does not trigger (same behavior as every other Postgres-backed test in this repo,
confirmed pre-existing). AC8 requires reporting this gap rather than claiming parity: **backend
parity for PostgresWikiStore is NOT validated end-to-end in this environment.** Verified by
code review instead: the diff exactly mirrors the already-merged SQLite CAS implementation
(TASK-3481) and the existing `_upsert_page`/`upsert_pages` transaction pattern; logic,
precondition branches, and delegation are correct on inspection.
Seat: haiku (native) · Backend: native · Model: haiku · Attempts: 1 · Duration: 303.3s · Tokens: 105991 (subagent total, in/out not separately reported by native path)

**Deviations from spec**: Live-backend validation (AC8) blocked by sandbox network restrictions — documented per AC8's own requirement, not silently declared complete.
