# TASK-4390: BookStore HelixDB projection owned by `Bookstore` (async boundary)

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 10, §9 S7, AC9, AC22)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4374
**Assigned-to**: unassigned

---

## Context

`CatalogStore` is deliberately synchronous (short-lived `sqlite3` connections) and the async boundary is the
library class (design research S7). The projection therefore lives in the library, **not** in `CatalogStore`
(which is not modified): one `BookstoreHelixProjection` per scope mirrors cards (`Book`), relations (`RELATES_TO`)
and communities (`BookCommunity` + `MEMBER_OF`) after each successful canonical write, and the cross-book catalog
shortlist consults it first. The canonical SQLite commit always wins: a projection failure is logged and sets
`projection_stale[scope] = True`; stale scopes use the SQLite FTS path until `reproject(scope)` succeeds.

---

## Scope

- Create `bookstore/helix_projection.py` — `BookstoreHelixProjection` (spec §3 M10 surface) + `BOOKSTORE_PLANE`.
- `bookstore/library.py` (`class Bookstore`): `helix_settings` ctor kwarg; per-scope projections;
  `projection_stale`; `reproject(scope)`; mirroring after the async mutations; stale-marking after sync mutations;
  projected shortlist inside `search()`.
- Tests in `tests/knowledge/bookstore/test_helix_projection.py`.

**NOT in scope**: `bookstore/catalog.py` (must stay byte-identical — AC22); PageIndex tree content search
(`search_book` searches inside one book's tree — that is PageIndex/TASK-4389's projection, see drift); MCP/CLI flags.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/helix_projection.py` | CREATE | `BookstoreHelixProjection`, `BOOKSTORE_PLANE` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | projection ownership, mirroring, stale fallback, `reproject` |
| `packages/ai-parrot/tests/knowledge/bookstore/test_helix_projection.py` | CREATE | AC9 / AC22 tests |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca`.

### Verified Imports
```python
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError     # library.py:178, :111
from parrot.knowledge.bookstore.catalog import CatalogStore, merged_search    # catalog.py:163, :766
from parrot.knowledge.bookstore.models import BookCard, BookRelation, BookCommunity  # models.py:152, :210, :302
from parrot.knowledge.bookstore.config import LibraryLocation                 # imported by library.py:42
# created by TASK-4372/4373/4374 (verify before use):
from parrot.knowledge.helix.settings import HelixSettings                     # .with_database(name)
from parrot.knowledge.helix.client import HelixClient, open_helix_client
from parrot.knowledge.helix.bootstrap import LabelSpec, PlaneSchema, ensure_plane
from parrot.knowledge.helix import dsl
```

### Existing Signatures to Use
```python
# bookstore/library.py
class Bookstore:                                                    # :178  (the spec calls it "Library")
    def __init__(self, locations, adapter=None, lightweight_model: Optional[str] = None) -> None   # :192-197
    self.logger = logger                                            # :210
    self._catalogs / self._toolkits / self._content_stores          # :210-212
    def _catalog(self, scope: str) -> CatalogStore                  # :228
    def _stores(self) -> list[tuple[str, CatalogStore]]             # :249
    def catalog_search(self, query, top_k=8) -> list[BookCard]      # :320 — merged_search over every scope (sync)
    def resolve_book(self, book_id) -> tuple[BookCard, LibraryLocation]   # :324
    async def search_book(self, book_id, query, top_k=8)            # :351 — PageIndex tree search (not a card search)
    async def search(self, query, book_ids=None, max_books=3, top_k=5, expand_related=False) -> dict   # :411
        cards = self.catalog_search(query, top_k=max_books)         # :444  ← shortlist consulted here
    def _write_deterministic(self, relations, target_ids=None)      # :506 SYNC; upsert_relations :546
    async def relate_books(...) -> RelateSummary                    # :627; single `return summary` :742
    async def _relate_stage3(...)                                   # :744; upsert_communities :811; upsert_relations :834; set_card_community :841
    def _clear_communities(self) -> None                            # :861 SYNC
    async def add_book(...)                                         # :977; `catalog.upsert(card)` :1158
    async def remove_book(self, book_id) -> bool                    # :1346; `removed = self._catalog(loc.scope).remove(book_id)` :1368
    async def refresh_card(self, book_id) -> BookCard               # :1372; `self._catalog(loc.scope).upsert(updated)` :1411
    def update_card(self, book_id, *, title=None, authors=None, topics=None, summary=None) -> BookCard   # :1414 SYNC; upsert :1448

# bookstore/catalog.py (read-only use)
def list_cards(self) -> list[BookCard]                              # :397
def get(self, book_id) -> Optional[BookCard]                        # :374
def _all_relations(self) -> list[BookRelation]                      # :599 (private — used only by reproject)
def list_communities(self) -> list[BookCommunity]                   # :715
def search(self, query, top_k=8) -> list[tuple[BookCard, float]]    # :409
# BookCommunity.member_book_ids: list[str]                          # models.py:331
```

### Does NOT Exist
- ~~`class Library`~~ — the class is `Bookstore` (`library.py:178`); "Library" in the spec is the module.
- ~~`CatalogStore.list_relations()` without a `book_id`~~ — `list_relations(book_id, rel=None)` (`:585`); use `_all_relations()`.
- ~~An async `CatalogStore` API~~ — sync only; never `await` catalog calls.
- ~~`Bookstore.projection_stale` / `reproject` / `helix_settings`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/helix_projection.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/bookstore/test_helix_projection.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.search",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.relate_books",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.remove_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.refresh_card",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.update_card",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#merged_search",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookCard",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookRelation",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookCommunity"
  ]
}
```

---

## Implementation Notes

### Spec drift
- The class is **`Bookstore`**, not `Library` (spec §2/§3 M10 wording).
- Spec says `search_book` (:351) consults the projection. `search_book` runs PageIndex hybrid search **inside one
  book's tree**; the BookStore projection indexes **cards**, so it cannot serve that call. `search_book` is left
  unchanged; tree-level projection is TASK-4389's `PageIndexToolkit(helix_settings=…)` (not wired from `Bookstore`
  here — record as a follow-up in the Completion Note).
- AC9 says "`CatalogStore.search()` delegates"; per S7 `CatalogStore` is unmodified, so the delegation is in
  `Bookstore.search()`'s shortlist (`:444`), which is the only async caller of the catalog search.
- Several mutations are **sync** (`update_card`, `_write_deterministic`, `_clear_communities`, the `upsert_relations`
  / `set_card_community` loops in `_relate_stage3`). Sync paths cannot await the projection: they set
  `projection_stale[scope] = True`; the public async mutators end with `await self._sync_projections()`, which
  `reproject`s every stale scope. Single-card async writes (`add_book`, `refresh_card`, `remove_book`) mirror
  incrementally.

### Key Constraints
- Opt-in: `helix_settings=None` (default) ⇒ no projection object, no helix import, byte-identical behaviour.
- Database per scope: `helix_settings.with_database(f"bookstore_{scope}")`.
- Canonical write first, projection after; projection exceptions are caught, logged (`self.logger.warning`) and mark
  the scope stale — they never propagate (AC22).
- `search()` uses the projection shortlist only when **every** scope has a non-stale projection; otherwise the
  existing `catalog_search` line runs unchanged. Projected hits are resolved to cards with `self._catalog(scope).get()`
  (scope stamped like `merged_search` does: `card.model_copy(update={"scope": scope})`), merged by score, ties to the
  earlier scope.
- `Book.search_text` = title + authors + topics + summary (the fields `books_fts` indexes — check
  `catalog.py:220-240` `_ensure_fts_schema` and mirror its columns exactly).

---

## Implementation Blueprint

### Steps (in order)
1. Create `helix_projection.py`.
2. Add ownership/stale/reproject helpers to `Bookstore`.
3. Hook the mutation paths and the `search()` shortlist.
4. Tests + validation.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/helix_projection.py` (CREATE)
```python
"""HelixDB projection of one BookStore scope's catalog (FEAT-670 M10, design research S7)."""
from __future__ import annotations

import logging
from typing import Optional

from parrot.knowledge.helix import dsl
from parrot.knowledge.helix.bootstrap import LabelSpec, PlaneSchema, ensure_plane
from parrot.knowledge.helix.client import HelixClient, open_helix_client
from parrot.knowledge.helix.settings import HelixSettings

from .models import BookCard, BookCommunity, BookRelation

BOOKSTORE_PLANE = PlaneSchema(
    plane="bookstore",
    schema_version="1",
    labels=[
        LabelSpec(label="Book", unique_key="book_id", text_property="search_text"),
        LabelSpec(label="BookCommunity", unique_key="community_id"),
    ],
    edge_labels=["RELATES_TO", "MEMBER_OF"],
)


class BookstoreHelixProjection:
    """Mirror of one scope's cards, relations and communities; serves BM25 card search."""

    def __init__(self, settings: HelixSettings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self._client: Optional[HelixClient] = None

    async def _ensure(self) -> HelixClient:
        if self._client is None:
            client = await open_helix_client(self.settings)
            await ensure_plane(client, BOOKSTORE_PLANE)
            self._client = client
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def upsert_card(self, card: BookCard) -> None:
        """Upsert one ``Book`` node (conditional entries — HelixDB has no upsert op)."""
        # FILL IN: dsl.upsert_node_entries on Book keyed book_id with search_text — bounded by spec §2 "no upsert"
        raise NotImplementedError

    async def remove_card(self, book_id: str) -> None:
        """Drop the ``Book`` node and its incident edges."""
        # FILL IN — bounded by spec §3 M10
        raise NotImplementedError

    async def upsert_relations(self, relations: list[BookRelation]) -> None:
        """``RELATES_TO`` edges (src→dst, props rel/weight/origin) via find-or-add (multigraph)."""
        # FILL IN: dsl.find_or_add_edge_entries per relation, ONE write batch — bounded by spec §7 multigraph risk
        raise NotImplementedError

    async def upsert_communities(self, communities: list[BookCommunity]) -> None:
        """Replace every ``BookCommunity`` + ``MEMBER_OF`` (Book→community) — partitions are rewritten wholesale."""
        # FILL IN: drop all BookCommunity nodes, add the given ones and MEMBER_OF for member_book_ids, ONE batch
        raise NotImplementedError

    async def reproject(
        self, cards: list[BookCard], relations: list[BookRelation], communities: list[BookCommunity]
    ) -> dict[str, int]:
        """Full rebuild from the canonical catalog in one batch; returns counts per kind."""
        # FILL IN: drop all Book/BookCommunity nodes, re-add everything, ONE batch (split at ~4 MiB text, spec §7)
        raise NotImplementedError

    async def search(self, query: str, top_k: int = 8) -> list[tuple[str, float]]:
        """``(book_id, $score)`` via text search on ``Book.search_text``; limit clamped to 800."""
        # FILL IN: dsl.text_search("Book", "search_text", query, min(top_k, 800), ["book_id"]) — bounded by AC9
        raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)
```python
# Edit 1 — ctor signature; occurrences: 1 (verified: grep -c -F '        lightweight_model: Optional[str] = None,' library.py) — line 196
# AFTER it insert:
        helix_settings: Optional[Any] = None,
# Edit 2 — occurrences: 1 (verified: grep -c -F '        self._content_stores: dict[str, NodeContentStore] = {}' library.py) — line 212
# AFTER it insert:
        self._helix_settings = helix_settings
        self._projections: dict[str, Any] = {}
        self.projection_stale: dict[str, bool] = {}

# Edit 3 — new helpers; insert after `_stores()` (line 249-250):
    def _projection(self, scope: str) -> Optional[Any]:
        """Lazy per-scope projection, or ``None`` when HelixDB is not configured (opt-in)."""
        if self._helix_settings is None:
            return None
        if scope not in self._projections:
            from .helix_projection import BookstoreHelixProjection  # lazy: no helix import unless configured

            self._projections[scope] = BookstoreHelixProjection(self._helix_settings.with_database(f"bookstore_{scope}"))
        return self._projections[scope]

    def _mark_stale(self, scope: str) -> None:
        """Sync mutation paths cannot await the projection: fall back until reproject."""
        if self._helix_settings is not None:
            self.projection_stale[scope] = True

    async def _mirror(self, scope: str, op: str, *args: Any) -> None:
        """Call ``projection.<op>(*args)`` after a canonical write; failure ⇒ stale, never raised (S7)."""
        projection = self._projection(scope)
        if projection is None or self.projection_stale.get(scope):
            return
        try:
            await getattr(projection, op)(*args)
        except Exception as exc:  # noqa: BLE001 — the canonical SQLite commit already won
            self.logger.warning("bookstore projection %s failed for scope %s: %s", op, scope, exc)
            self.projection_stale[scope] = True

    async def reproject(self, scope: str) -> dict[str, int]:
        """Rebuild ``scope``'s projection from the canonical catalog; clears ``projection_stale`` on success."""
        projection = self._projection(scope)
        if projection is None:
            raise BookstoreError("HelixDB projection is not configured (pass helix_settings=)")
        catalog = self._catalog(scope)
        counts = await projection.reproject(catalog.list_cards(), catalog._all_relations(), catalog.list_communities())
        self.projection_stale[scope] = False
        return counts

    async def _sync_projections(self) -> None:
        """Reproject every stale scope; failures keep it stale."""
        for scope in [s for s, stale in self.projection_stale.items() if stale]:
            try:
                await self.reproject(scope)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("bookstore reproject failed for scope %s: %s", scope, exc)

    async def _projected_shortlist(self, query: str, top_k: int) -> Optional[list[BookCard]]:
        """Card shortlist from the projections, or ``None`` when any scope is unprojected/stale."""
        # FILL IN: None unless every location scope has a projection and is not stale; else merge projection.search()
        #   hits across scopes like merged_search (score desc, earlier scope wins ties, dedupe book_id, scope stamped);
        #   any exception ⇒ mark that scope stale and return None — bounded by AC9, AC22
        raise NotImplementedError

# Edit 4 — search shortlist; occurrences: 1 (verified: grep -c -F '            cards = self.catalog_search(query, top_k=max_books)' library.py) — line 444
# REPLACE that line with:
            projected = await self._projected_shortlist(query, max_books)
            cards = projected if projected is not None else self.catalog_search(query, top_k=max_books)

# Edit 5 — add_book; occurrences: 1 (verified: grep -c -F '        catalog.upsert(card)' library.py) — line 1158
# AFTER it insert:
        await self._mirror(scope, "upsert_card", card)

# Edit 6 — remove_book; occurrences: 1 (verified: grep -c -F '        removed = self._catalog(loc.scope).remove(book_id)' library.py) — line 1368
# AFTER the following `self._invalidate_graph(book_id)` line insert:
        await self._mirror(loc.scope, "remove_card", book_id)
        await self._sync_projections()
#   (_invalidate_graph → _clear_communities is sync and marks scopes stale via Edit 8)

# Edit 7 — `        self._catalog(loc.scope).upsert(updated)` occurs 2 times (:1411 refresh_card async, :1448 update_card sync).
#   refresh_card — disambiguate with the preceding context (lines 1406-1411):
#                 # a refresh untouched (Bookstore.relate_books owns them).
#             }
#         )
#         self._catalog(loc.scope).upsert(updated)
#         return updated
#   AFTER that upsert (line 1411) insert:  `        await self._mirror(loc.scope, "upsert_card", updated)`
#   update_card — context `        updated = card.model_copy(update=changes)` then the upsert (line 1447-1448):
#   AFTER that upsert (line 1448) insert:  `        self._mark_stale(loc.scope)`

# Edit 8 — sync relation/community writes; mark stale (occurrences 1 each):
#   after `            self._catalog(scope).upsert_relations(scoped_relations)` (:546) → `            self._mark_stale(scope)`
#   after `            self._catalog(scope).upsert_relations(edges)` (:834)            → `            self._mark_stale(scope)`
#   after `        self._communities_store().upsert_communities(book_communities)` (:811) → mark stale every location scope
#   in `_clear_communities` (:861) after its loops                                     → mark stale every location scope
# Edit 9 — relate_books; `        return summary` occurrences: 1 (line 742)
# BEFORE it insert:
        await self._sync_projections()
```
**Why this shape**: one async mirror helper keeps the failure policy in one place (S7); stale-then-reproject turns
every sync mutation into a correct eventual mirror without making `CatalogStore` async.

### FILL IN checklist
- [ ] `helix_projection.py` — six method bodies; bounded by spec §2 data model, §7 multigraph / 800 cap / 4 MiB split.
- [ ] `library.py::_projected_shortlist` — bounded by AC9/AC22.
- [ ] `Book.search_text` columns match `books_fts` (read `catalog.py:220-240`).

---

## Acceptance Criteria

- [ ] AC9: with a projection, `Bookstore.search()` shortlists through HelixDB; relations and communities are mirrored; without one, behaviour is unchanged (existing `test_library.py` passes).
- [ ] AC22: `catalog.py` unmodified (`git diff --quiet origin/dev -- packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py`); projection failure never fails the canonical write and sets `projection_stale`; `reproject` clears it.
- [ ] No helix import when `helix_settings` is not passed.
- [ ] `ruff check` clean on both source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_helix_projection.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/bookstore/test_helix_projection.py
"""FEAT-670 M10 — Bookstore-owned HelixDB projection (embedded InMemory)."""
import pytest

pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")

# fixtures: reuse tests/knowledge/bookstore/conftest.py (fake_adapter, sample_tree) and the `locations`
# shape of test_library.py:28-32; helix settings = HelixSettings(mode=HelixMode.MEMORY, database=f"test_{uuid4().hex}")


async def test_bookstore_projection_search():
    """add_book → search() shortlists via projection (spy); relations → RELATES_TO; communities → MEMBER_OF."""


async def test_projection_failure_marks_stale_and_falls_back():
    """projection.upsert_card raises → card still in SQLite catalog, projection_stale[scope] True, search uses catalog_search."""


async def test_reproject_clears_stale():
    """reproject(scope) after a failure → projection_stale False and projected search returns the card."""


async def test_sync_update_card_marks_stale():
    """update_card (sync) → projection_stale True; next relate_books()/remove_book() reprojects."""


def test_no_projection_by_default():
    """Bookstore(locations) never imports parrot.knowledge.bookstore.helix_projection."""
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`
2. **Read the spec** §3 M10 and §9 S7.
3. **Check dependencies** — TASK-4374 must be `done`; read `helix/dsl.py` + `bootstrap.py` first.
4. **Verify the Codebase Contract** — re-run each `grep -c -F`; the two-occurrence anchor in Edit 7 must be placed with the quoted context.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit the code** — only the three listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4390 helixdb-provider verified`.
10. **Fill in the Completion Note** (mention the `search_book` follow-up), then commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
