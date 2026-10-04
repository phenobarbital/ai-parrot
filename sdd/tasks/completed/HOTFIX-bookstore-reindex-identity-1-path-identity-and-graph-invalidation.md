# HOTFIX-bookstore-reindex-identity-1: Source-path re-index identity and shared graph-invalidation cascade

**Feature**: bookstore-reindex-identity — Bookstore re-index identity, graph invalidation, title collision guard and card editing (hotfix)
**Spec**: `sdd/specs/bookstore-reindex-identity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Index**: `sdd/tasks/index/bookstore-reindex-identity.json`

---

## Context

Spec §1 problems 1 and 2, modules **M1** and **M2**, acceptance criteria
AC-1..AC-5. `Bookstore.add_book()` identifies an already-catalogued book only
by the sha256 of the file bytes, so a changed file at the same path takes the
*added* branch and `unique_slug()` mints `<slug>-2` next to the stale row.
Separately, the existing `updated` path (sha match + `force`) rebuilds the
tree but leaves relations, judgements and the community partition behind,
unlike `remove_book()`.

---

## Scope

- Add `CatalogStore.find_by_path(source_path)` next to `find_by_sha()`.
- In `add_book()`, resolve `existing` as sha match **or** path match; a path
  match with a different sha becomes status `updated` (no `force` needed),
  reusing `existing.book_id` / tree name.
- Extract the relation/judgement/community cascade of `remove_book()` into
  `Bookstore._invalidate_graph(book_id)`; call it from `remove_book()` and
  from every `updated` re-index in `add_book()` right after `delete_tree()`.
- Update the `force:` / `Returns:` docstring lines of `add_book()` and the
  `force:` line of `add_folder()` to state the path rule.
- Tests for AC-1..AC-5.

**NOT in scope**: the title collision guard (task 2), `update_card` / CLI
(task 3), any change to `unique_slug`, the `books` DDL, `BookstoreToolkit`,
`mcp_server.py`, or `_CARD_PROMPT`. Do not rewrite `source_path` for a sha
match at a new path (stays `skipped`, spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | MODIFY | add `find_by_path()` after `find_by_sha()` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | identity resolution in `add_book`, new `_invalidate_graph`, `remove_book` delegates |
| `packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py` | MODIFY | `find_by_path` roundtrip test |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | AC-1, AC-3, AC-5 tests + folder rerun test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.catalog import CatalogStore                 # verified: catalog.py:163
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError     # verified: library.py:181 / library.py:100
from parrot.knowledge.bookstore.models import BookCard, BookRelation, RelationJudgement, REL_WEIGHTS  # verified: models.py:152, 210, 255; REL_WEIGHTS imported at library.py:40
from parrot.knowledge.bookstore.config import LibraryLocation               # verified: test_library.py:10
from .conftest import SAMPLE_MARKDOWN                                       # verified: test_library.py:13 (tests only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py
class CatalogStore:                                                           # line 163
    def _connection(self) -> Iterator[sqlite3.Connection]                     # line 183 (contextmanager, sqlite3.Row rows)
    def _row_to_card(row: sqlite3.Row) -> BookCard                            # line 286 (staticmethod)
    def upsert(self, card: BookCard) -> None                                  # line 300
    def remove(self, book_id: str) -> bool                                    # line 357
    def get(self, book_id: str) -> Optional[BookCard]                         # line 374
    def find_by_sha(self, sha256: str) -> Optional[BookCard]                  # line 380  ← mirror this
    def upsert_relations(self, relations: list[BookRelation]) -> None         # line 485
    def delete_relations(self, book_id: Optional[str] = None, origin: Optional[str] = None) -> int  # line 515
    def record_judgements(self, src: str, judgements: list[RelationJudgement], model: str = "") -> None  # line 597
    def judged_pairs(self, src: str) -> set[str]                              # line 630
    def delete_judgements(self, book_id: str) -> int                          # line 639
    def list_communities(self) -> list[BookCommunity]                         # line 704
# books DDL: book_id TEXT PRIMARY KEY (44) … source_path TEXT NOT NULL (54), source_sha256 TEXT NOT NULL (55)

# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
class Bookstore:
    def _catalog(self, scope: str) -> CatalogStore                            # line 217
    def _toolkit(self, scope: str) -> PageIndexToolkit                        # line 222
    def _stores(self) -> list[tuple[str, CatalogStore]]                       # line 238
    def list_books(self) -> list[BookCard]                                    # line 261
    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]  # line 269
    def related_books(self, book_id, *, rel=None, depth=1, ...)               # line 493
    def _clear_communities(self) -> None                                      # line 806
    def communities(self) -> list[BookCommunity]                              # line 823
    async def add_book(self, file_path, scope="project", title=None, authors=None, topics=None, force=False, *, relate=False) -> tuple[BookCard, str]  # line 922
    async def add_folder(self, folder, scope="project", recursive=False, force=False, *, relate=False) -> dict  # line 1194
    async def remove_book(self, book_id: str) -> bool                         # line 1249
# add_book identity block, lines 957-979:
#   path = Path(file_path).expanduser().resolve()                             # 957
#   sha256 = hashlib.sha256(payload).hexdigest()                              # 966
#   existing = catalog.find_by_sha(sha256)                                    # 967
#   status = "added"                                                          # 968
#   if existing is not None: if not force: return existing.model_copy(update={"scope": scope}), "skipped"; status = "updated"   # 969-972
#   toolkit = self._toolkit(scope)                                            # 974
#   if status == "updated": slug = existing.book_id; await toolkit.delete_tree(slug)   # 975-977
#   else: slug = unique_slug(slugify(title or path.stem), self._all_taken_slugs())   # 978-979
# remove_book cascade, lines 1264-1277:
#   card, loc = self.resolve_book(book_id); toolkit = self._toolkit(loc.scope); try: await toolkit.delete_tree(card.tree_name) except …
#   for _scope, store in self._stores(): store.delete_relations(book_id=book_id); store.delete_judgements(book_id)   # 1270-1272
#   removed = self._catalog(loc.scope).remove(book_id); if removed: self._clear_communities(); return removed          # 1273-1276

# tests/knowledge/bookstore/test_library.py fixtures: locations (line 16), book_md (line 25, writes SAMPLE_MARKDOWN to tmp_path/"synthetic-handbook.md"),
#   store (line 32, fake_adapter), store_no_llm (line 37); existing tests test_add_book_sha_skip_and_force (58), test_slug_collision_suffixing (154),
#   test_add_folder_rerun_skips_by_sha (293), test_remove_book (304)
# tests/knowledge/bookstore/test_communities.py:48 — BookRelation(src_book_id="a", dst_book_id="b", rel="parallels", origin="llm", confidence=0.7, weight=REL_WEIGHTS["parallels"], computed_at=_NOW)
```

### Does NOT Exist
- ~~`CatalogStore.find_by_path()`~~ — created by THIS task; nothing else provides it.
- ~~`CatalogStore.find_by_source_path()` / `get_by_source()`~~ — do not exist; use `find_by_path`.
- ~~`Bookstore._invalidate_graph()`~~ — created by THIS task.
- ~~`CatalogStore.find_by_sha(sha, scope=…)`~~ — no scope parameter; catalogs are per-scope objects.
- ~~`add_book(..., replace=True)`~~ — no new flag; the path rule is implicit.
- ~~`BookCard.updated_at`~~ — no such field/column.
- ~~`CatalogStore.clear_communities()`~~ — the clearing lives on `Bookstore._clear_communities()` (library.py:806).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/bookstore/test_library.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore.find_by_sha",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore.delete_relations",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore.delete_judgements",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.remove_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._clear_communities"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# catalog.py:380-384 — copy verbatim, swap the column
def find_by_sha(self, sha256: str) -> Optional[BookCard]:
    """Find the card for an already-ingested source file, if any."""
    with self._connection() as conn:
        row = conn.execute("SELECT * FROM books WHERE source_sha256 = ?", (sha256,)).fetchone()
    return self._row_to_card(row) if row else None
```

### Key Constraints
- `source_path` is stored as `str(path)` of the **resolved** path (library.py:957 + 1065), so `find_by_path` is an exact string match; do not normalise in SQL.
- sha is checked **first** so a byte-identical file at a new path stays `skipped` (AC-3) and `force` semantics are unchanged (AC-2).
- `_invalidate_graph` is sync (all catalog calls are sync sqlite). It runs `_clear_communities()` unconditionally — idempotent (`upsert_communities([])` + stamp reset), spec §3 M2 note.
- Minimal diff; no reformatting; black 120; `ruff check` clean.

### References in Codebase
- `library.py:1249-1277` — `remove_book`, the cascade being extracted.
- `library.py:922-1079` — `add_book`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `find_by_path` to `catalog.py` below `find_by_sha` — *why*: M1 needs a path lookup and the sha method is the exact template.
2. Add `_invalidate_graph` to `library.py` immediately above `remove_book`, then make `remove_book` call it — *why*: the cascade must exist before `add_book` can reuse it, and `remove_book` must keep its behaviour (AC-5).
3. Change the identity block of `add_book` (lines 967-977) — *why*: path match ⇒ `updated`, and the cascade must run right after the old tree is deleted.
4. Update the `force:`/`Returns:` docstrings of `add_book` and `force:` of `add_folder` — *why*: the CLI `--help` text and docstrings are the documentation (AC-11).
5. Write the tests, run the Validation Commands, `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def find_by_sha(self, sha256: str) -> Optional\[BookCard\]:' catalog.py)
# AFTER — insert below the whole find_by_sha method (ends at catalog.py:384, the `return self._row_to_card(row) if row else None` line)

    def find_by_path(self, source_path: str) -> Optional[BookCard]:
        """Find the card whose stored ``source_path`` equals ``source_path``.

        The value is the resolved path string ``Bookstore.add_book`` stores, so
        this is an exact string match — callers pass ``str(path)`` of a
        resolved ``Path``.
        """
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM books WHERE source_path = ?", (source_path,)).fetchone()
        return self._row_to_card(row) if row else None
```
**Why**: same shape as `find_by_sha` so both lookups behave identically; no index is added (tens of rows).

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY — identity block)
```python
# occurrences: 1 (verified: grep -c '        existing = catalog.find_by_sha(sha256)' library.py)
# REPLACE library.py:967 with:
        existing = catalog.find_by_sha(sha256)
        same_bytes = existing is not None
        if existing is None:
            existing = catalog.find_by_path(str(path))
# REPLACE library.py:969-972 (the `if existing is not None:` block) with:
        if existing is not None:
            if same_bytes and not force:
                return existing.model_copy(update={"scope": scope}), "skipped"
            status = "updated"
# occurrences: 1 (verified: grep -c '            slug = existing.book_id' library.py)
# AFTER — insert below `            await toolkit.delete_tree(slug)` (library.py:977, the line following `slug = existing.book_id`):
            self._invalidate_graph(slug)
```
**Why**: sha wins first (AC-2/AC-3); a path hit with different bytes is a new version of the same book (AC-1); the cascade runs after the tree is gone and before the rebuild (AC-5). Docstring: change `force:` to "Re-index even when the same file (by sha256) is already catalogued. A file whose content changed at an already-catalogued path is always re-indexed in place, ``force`` or not." and `Returns:` to mention `"updated"` covers both cases. Apply the same one-sentence note to `add_folder`'s `force:` (library.py:1214).

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY — cascade)
```python
# occurrences: 1 (verified: grep -c '    async def remove_book(self, book_id: str) -> bool:' library.py)
# BEFORE — insert above `    async def remove_book(self, book_id: str) -> bool:` (library.py:1249):
    def _invalidate_graph(self, book_id: str) -> None:
        """Drop every relation/judgement touching ``book_id`` and clear the community partition.

        Edges touching ``book_id`` may live in either scope's DB (the scope
        owning an edge's ``src``), so the cascade runs across every store.
        Community ids are membership hashes, so any change to a member
        invalidates the whole partition; the next ``relate_books`` recomputes it.
        """
        for _scope, store in self._stores():
            store.delete_relations(book_id=book_id)
            store.delete_judgements(book_id)
        self._clear_communities()

# FILL IN: disambiguate — the anchor `        for _scope, store in self._stores():` occurs 4 times in library.py;
# inside remove_book it is followed by `            store.delete_relations(book_id=book_id)` and
# `            store.delete_judgements(book_id)` (library.py:1270-1272). REPLACE those three lines plus the
# following `removed = …` / `if removed: self._clear_communities()` (1273-1275) with:
        removed = self._catalog(loc.scope).remove(book_id)
        self._invalidate_graph(book_id)
        return removed
```
**Why**: one cascade, two callers (spec M2). Moving the docstring prose from `remove_book` into `_invalidate_graph` is fine; keep `remove_book`'s own docstring summary line.

### `packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py` (MODIFY)
```python
# AFTER — append at end of file (last test: `def test_merged_relations_filters_dangling_and_project_wins(tmp_path):`, test_catalog.py:393)
def test_find_by_path_roundtrip(store):
    # FILL IN: build a BookCard as the other tests in this file do (look at the `store` fixture and an
    # existing upsert), upsert it, assert find_by_path(card.source_path) returns it and
    # find_by_path("/nope.md") is None — bounded by AC-1
    raise NotImplementedError
```

### `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` (MODIFY)
```python
# AFTER — insert below `async def test_add_book_sha_skip_and_force(store, book_md):` (test_library.py:58, whole test)
@pytest.mark.asyncio
async def test_add_book_changed_content_same_path_updates_in_place(store, book_md):
    card1, status1 = await store.add_book(book_md)
    book_md.write_text(SAMPLE_MARKDOWN + "\n## New chapter\n\nChanged content.\n", encoding="utf-8")
    card2, status2 = await store.add_book(book_md)
    assert (status1, status2) == ("added", "updated")
    assert card2.book_id == card1.book_id
    assert card2.source_sha256 != card1.source_sha256
    assert [c.book_id for c in store.list_books()] == [card1.book_id]
    # FILL IN: assert the tree is readable (store.get_toc(card2.book_id)) — bounded by AC-1


@pytest.mark.asyncio
async def test_add_book_same_bytes_other_path_is_skipped(store, book_md, tmp_path):
    # FILL IN: copy book_md bytes to tmp_path / "copy.md", add both, second is "skipped" and
    # source_path still points at book_md — bounded by AC-3
    raise NotImplementedError


@pytest.mark.asyncio
async def test_reindex_invalidates_relations_and_communities(store, book_md, tmp_path):
    # FILL IN: add book A (book_md) and book B (a second file with different content); seed one
    # BookRelation A->B via store._catalog("project").upsert_relations([...]) (shape: test_communities.py:48)
    # and one judgement via record_judgements(A, [RelationJudgement(dst_book_id=B, rel="parallels",
    # confidence=0.7)]); rewrite book_md and add again; assert store.related_books(A) == [],
    # store._catalog("project").judged_pairs(A) == set(), store.communities() == [] — bounded by AC-5
    raise NotImplementedError


@pytest.mark.asyncio
async def test_add_folder_changed_file_updates_not_duplicates(store, tmp_path):
    # FILL IN: folder with two md files; add_folder; rewrite one; add_folder again; statuses are
    # {"updated", "skipped"}; len(store.list_books()) == 2 — bounded by AC-1
    raise NotImplementedError
```
**Why**: the four tests map 1:1 to AC-1, AC-3, AC-5 and the folder rerun; existing tests `test_add_book_sha_skip_and_force`, `test_slug_collision_suffixing`, `test_add_folder_rerun_skips_by_sha`, `test_remove_book` must stay untouched and green (AC-2, AC-4, AC-5).

### FILL IN checklist
- [ ] `test_catalog.py::test_find_by_path_roundtrip` — card construction; bounded by AC-1
- [ ] `test_library.py::test_add_book_same_bytes_other_path_is_skipped` — copy + assertions; bounded by AC-3
- [ ] `test_library.py::test_reindex_invalidates_relations_and_communities` — seeding + assertions; bounded by AC-5
- [ ] `test_library.py::test_add_folder_changed_file_updates_not_duplicates` — folder setup; bounded by AC-1

---

## Acceptance Criteria

- [ ] AC-1 — changed bytes at the same resolved path ⇒ `updated`, same `book_id`, one catalog row, no `-2`.
- [ ] AC-2 — byte-identical file ⇒ `skipped` without force, `updated` with force (existing test unchanged).
- [ ] AC-3 — byte-identical file at another path ⇒ `skipped`, `source_path` unchanged.
- [ ] AC-4 — `test_slug_collision_suffixing` unchanged and green.
- [ ] AC-5 — every `updated` re-index and `remove_book` go through `_invalidate_graph`; `test_remove_book` green.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/bookstore packages/ai-parrot/tests/knowledge/bookstore` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_relations.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_communities.py -q`

---

## Test Specification

See the blueprint blocks above; run with `PYTHONPATH=packages/ai-parrot/src` from the worktree root.

---

## Agent Instructions

1. Work in the hotfix worktree `.claude/worktrees/hotfix-bookstore-reindex-identity` (branch `hotfix/bookstore-reindex-identity`), never on `main`.
2. Read the spec §2, §3 M1/M2, §6, §7.
3. Verify every entry of the Codebase Contract before editing; if a line moved, fix the contract first.
4. Mark this task `in-progress` in `sdd/tasks/index/bookstore-reindex-identity.json` and commit only the index.
5. Implement from the blueprint; complete every `FILL IN`.
6. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, then `ruff check` on the four files.
7. Commit only the four listed files: `fix(bookstore): HOTFIX-bookstore-reindex-identity-1 — path re-index identity + graph invalidation`.
8. Close with `scripts/sdd/close_task.sh HOTFIX-bookstore-reindex-identity-1 bookstore-reindex-identity verified`, fill the Completion Note, commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker (sequential self-implementation; parrot-sdd-coder not used for hotfix ids)
**Date**: 2026-09-30
**Implementation commit**: 55ee7922f
**Tests**: test_catalog 24 passed, test_library 33 passed, test_relations 20 passed, test_communities 12 passed; ruff clean on touched files (2 pre-existing ASYNC240 in library.py untouched lines)
**Notes**: Copied git-ignored Cython .so files from main checkout into worktree so tests import; in-progress index commit skipped (closed directly).

**Deviations from spec**: none
