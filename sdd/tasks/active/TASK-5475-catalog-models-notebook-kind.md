# TASK-5475: Catalog `kind`/`notes_for` columns and notebook models

**Feature**: FEAT-876 — Bookstore notebooks over a shared PageIndex
**Spec**: `sdd/specs/bookstore-notebooks-shared-pageindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec **Module 1** (§3) and goal G1/G2. Every other task builds on the notebook row shape:
a catalog row is either a book (`kind="book"`, the default for every existing row) or a notebook
(`kind="notes"`, `notes_for=<book_id>` for a book notebook, `None` for the scope's `_library_notes`).
Every card-enumerating read must keep returning books only (S1), so the default of `list_cards` and
`search` is books.

---

## Scope

- Add `Anchor`, `Annotation`, `SectorDraft` models to `models.py` (exact fields in spec §2 Data Models).
- Add `BookCard.kind: Literal["book", "notes"] = "book"` and `BookCard.notes_for: Optional[str] = None`.
- Extend `BookCard.source_format` with `"tree"` and `BookRelation.origin` with `"manual"`.
- Add `("kind", "kind TEXT NOT NULL DEFAULT 'book'")` and `("notes_for", "notes_for TEXT")` to `_ADDED_COLUMNS`.
- `CatalogStore.list_cards(kind="book")` — `None` returns every row; `taken_slugs()` keeps returning **all** ids
  (a notebook tree name must stay taken).
- `CatalogStore.search` (FTS and LIKE paths) returns only `kind='book'` rows.
- Add `CatalogStore.notebook_for(book_id)` and `CatalogStore.library_notebook()`.
- `CatalogStore.upsert_relations`: a row with `origin="manual"` is never replaced by a non-manual edge on the
  same `(src, dst, rel)` key (so `relate_books` keeps sheet edges, spec M5 "`relate_books` must skip overwriting
  rows with `origin == "manual"`"); a manual edge does replace a computed one.
- Tests in `test_catalog.py` and `test_models.py`.

**NOT in scope**: anything in `library.py` (TASK-5477), relation-origin filtering in `_invalidate_graph`
(TASK-5477), the FTS `kind` column (see Implementation Notes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py` | MODIFY | New models; `kind`/`notes_for`; literal extensions |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | MODIFY | Migration columns, kind-filtered reads, notebook accessors |
| `packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py` | MODIFY | Migration + filtering + accessor tests |
| `packages/ai-parrot/tests/knowledge/bookstore/test_models.py` | MODIFY | Model default/literal tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` at task-writing time (2026-11-11). Use these exact names.
> If you need anything not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from typing import Literal, Optional                      # verified: models.py:10
from pydantic import BaseModel, Field, model_validator     # verified: models.py:12
from parrot.knowledge.bookstore.models import BookCard, BookRelation   # verified: models.py:152, :210
from parrot.knowledge.bookstore.catalog import CatalogStore, merged_cards   # verified: catalog.py:163, :751
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
class BookCard(BaseModel):                                   # line 152 — book_id == tree_name
    tree_name: str; scope: Literal["project", "global"] = "project"; source_path: str; source_sha256: str
    source_format: Literal["pdf", "md", "txt", "epub", "mobi", "docx"]   # line 172
    added_at: str; card_origin: Literal["llm", "fallback", "manual"] = "llm"   # line 176
class BookRelation(BaseModel):                               # line 210
    origin: Literal["deterministic", "llm", "community"]    # line 242

# packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py
_FTS_DDL = """..."""                                       # line 64 (unchanged by this task)
_ADDED_COLUMNS: list[tuple[str, str]] = [                    # line 95 — genre, traditions, period, community_id, community_label
class CatalogStore:                                          # line 163
    def _ensure_schema(self, conn) -> None                   # line 197 — ALTERs missing _ADDED_COLUMNS
    def _row_to_card(row: sqlite3.Row) -> BookCard           # line 286 (staticmethod; dict(row) → model_validate)
    def upsert(self, card: BookCard) -> None                 # line 300 — writes every model_dump key as a column (scope popped)
    def get(self, book_id: str) -> Optional[BookCard]        # line 374
    def list_cards(self) -> list[BookCard]                   # line 397 — "SELECT * FROM books ORDER BY title COLLATE NOCASE"
    def taken_slugs(self) -> set[str]                        # line 403
    def search(self, query: str, top_k: int = 8) -> list[tuple[BookCard, float]]   # line 409 (FTS JOIN books b)
    def _like_search(self, query, top_k)                     # iterates self.list_cards()
def merged_cards(stores) -> list[BookCard]                   # line 751 — calls store.list_cards()
```

### Does NOT Exist
- ~~`books.kind` / `books.notes_for`~~ — added by this task.
- ~~`CatalogStore.notebook_for` / `library_notebook`~~ — added by this task.
- ~~`Anchor`, `Annotation`, `SectorDraft`~~ — added by this task.
- ~~`CatalogStore.list_notebooks`~~ — not planned; use `list_cards(kind="notes")`.
- ~~a `kind` column in `books_fts`~~ — not added (see Implementation Notes).
- SQLite UPSERT (`ON CONFLICT ... DO UPDATE ... WHERE`) needs SQLite ≥ 3.24 — the bundled CPython sqlite is newer; the PK is `(src_book_id, dst_book_id, rel)` (catalog.py:116).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_models.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookCard",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookRelation",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#merged_cards"
  ]
}
```

---

## Implementation Notes

- **FTS decision (planner)**: the spec's §7 mentions adding `kind` to `_FTS_DDL`. Do **not** rebuild the FTS
  table: `search` already JOINs `books b`, so `AND b.kind = 'book'` filters notebooks without forcing an FTS
  rebuild on every existing library. AC "search excludes notes" is what matters.
- `upsert` serialises every `model_dump` key as a column, so the two new fields persist automatically once the
  columns exist — do not hand-edit the INSERT.
- Keep `taken_slugs()` over **all** rows: slug allocation must never hand out a notebook's tree name.
- Old DBs: `_ensure_schema` ALTERs on first open; rows read back `kind="book"` from the column default.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Edit `models.py` (new fields + literals + three classes) — *why*: every later task imports them.
2. Add the two `_ADDED_COLUMNS` entries — *why*: migration of existing `library.db` files is the column default.
3. Change `list_cards`, `search`, `_like_search`; add `notebook_for`, `library_notebook` — *why*: S1 keeps notes out of book listings.
4. Write the tests, run them, `ruff check --fix`.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    source_format: Literal["pdf", "md", "txt", "epub", "mobi", "docx"]' models.py)
# REPLACE line 172:
    source_format: Literal["pdf", "md", "txt", "epub", "mobi", "docx", "tree"]
# occurrences: 1 — AFTER `    community_label: Optional[str] = None` inside BookCard (verified: models.py:181, 1 occurrence)
    kind: Literal["book", "notes"] = "book"
    notes_for: Optional[str] = None
# occurrences: 1 (verified: grep -c '    origin: Literal["deterministic", "llm", "community"]' models.py) — REPLACE line 242:
    origin: Literal["deterministic", "llm", "community", "manual"]
```
```python
# APPEND at end of models.py
class Anchor(BaseModel):
    """One reference from a notebook node into a book (optionally into a node of it)."""

    book_id: str
    scope: Literal["project", "global"] = "project"
    node_id: Optional[str] = None
    doc_id: Optional[str] = None
    revision: Optional[str] = None


class Annotation(BaseModel):
    """A notebook node as returned next to a book section."""

    note_tree: str
    node_id: str
    title: str
    body: str
    note_kind: Literal["footnote", "note", "sector", "sheet"] = "note"
    origin: Literal["human", "agent", "draft"] = "human"
    anchor_status: Literal["current", "remapped", "stale"] = "current"


class SectorDraft(BaseModel):
    """LLM-proposed sector for the library notebook."""

    code: str
    title: str
    rationale: str = ""
    books: list[Anchor] = Field(default_factory=list)
```
**Why**: spec §2 Data Models fixes these fields; defaults keep every existing row and relation valid.
`community_label` is a multi-line-safe anchor only once inside `BookCard` — check with `grep -n` before inserting;
if it occurs more than once, insert directly before `    def brief(self) -> dict:` instead.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_ADDED_COLUMNS: list\[tuple\[str, str\]\] = \[' catalog.py) — append two entries before `]`
    ("kind", "kind TEXT NOT NULL DEFAULT 'book'"),
    ("notes_for", "notes_for TEXT"),
```
```python
# occurrences: 1 (verified: grep -c '    def list_cards(self) -> list\[BookCard\]:' catalog.py) — REPLACE the method
    def list_cards(self, kind: Optional[str] = "book") -> list[BookCard]:
        """Cards of one ``kind`` ordered by title; ``None`` returns every row."""
        with self._connection() as conn:
            if kind is None:
                rows = conn.execute("SELECT * FROM books ORDER BY title COLLATE NOCASE").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM books WHERE kind = ? ORDER BY title COLLATE NOCASE", (kind,)
                ).fetchall()
        return [self._row_to_card(row) for row in rows]

    def notebook_for(self, book_id: str) -> Optional[BookCard]:
        """The ``kind='notes'`` row whose ``notes_for == book_id``, or ``None``."""
        # FILL IN: SELECT ... WHERE kind='notes' AND notes_for=? LIMIT 1 — bounded by spec M1 skeleton
        raise NotImplementedError

    def library_notebook(self) -> Optional[BookCard]:
        """The ``kind='notes'`` row with ``notes_for IS NULL`` (tree ``_library_notes``), or ``None``."""
        # FILL IN: SELECT ... WHERE kind='notes' AND notes_for IS NULL AND tree_name='_library_notes'
        raise NotImplementedError
```
```python
# search(): in the FTS SQL change   "WHERE books_fts MATCH ? ORDER BY rank LIMIT ?"
#                         to        "WHERE books_fts MATCH ? AND b.kind = 'book' ORDER BY rank LIMIT ?"
# _like_search(): keeps iterating self.list_cards() — the new default already filters books.
```
```python
# upsert_relations (verified: catalog.py:496, 1 occurrence) — REPLACE the "INSERT OR REPLACE INTO book_relations ..." statement
                conn.execute(
                    "INSERT INTO book_relations "
                    "(src_book_id, dst_book_id, rel, weight, origin, confidence, rationale, computed_at) "
                    "VALUES (:src, :dst, :rel, :weight, :origin, :confidence, :rationale, :computed_at) "
                    "ON CONFLICT(src_book_id, dst_book_id, rel) DO UPDATE SET "
                    "weight = excluded.weight, origin = excluded.origin, confidence = excluded.confidence, "
                    "rationale = excluded.rationale, computed_at = excluded.computed_at "
                    "WHERE book_relations.origin <> 'manual' OR excluded.origin = 'manual'",
                    {...same parameter dict as today...},
                )
# Also update the docstring: "Existing rows sharing the key are replaced, except a manual row by a computed edge."
```
**Why**: S1 — every listing that feeds `list_books`, `catalog_search`, `merged_cards`, `related_books` and
`communities` goes through `list_cards()`/`search()`, so the default filter covers them without touching
`library.py`. `CatalogStore.__init__` (catalog.py:171-176) already runs `_ensure_schema`, so an old DB has the
new columns before any read — no extra call is needed in the read paths.

### FILL IN checklist
- [ ] `catalog.py::CatalogStore.notebook_for` — single-row query; bounded by M1 skeleton
- [ ] `catalog.py::CatalogStore.library_notebook` — single-row query; bounded by M1 skeleton
- [ ] `upsert_relations` parameter dict — keep the existing keys verbatim
- [ ] Tests listed in Test Specification — bounded by spec §4 M1 rows

---

## Acceptance Criteria

- [ ] An old `library.db` (fixture `legacy_library_db` in `conftest.py`) opens; every row reads `kind="book"`, `notes_for=None`.
- [ ] `list_cards()` excludes `kind="notes"` rows; `list_cards(kind=None)` returns them; `taken_slugs()` includes them.
- [ ] `search()` never returns a notes row (FTS and LIKE paths).
- [ ] `BookCard(source_format="tree", kind="notes", ...)` and `BookRelation(origin="manual", ...)` validate.
- [ ] `upsert_relations([computed edge])` over an existing `origin="manual"` row leaves the manual row intact; a manual edge replaces a computed one.
- [ ] `ruff check` clean on the touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_models.py -q`

---

## Test Specification

```python
# test_catalog.py (additions) — reuse `legacy_library_db` from conftest.py; build cards like the existing tests do
def test_catalog_kind_migration_keeps_existing_rows(legacy_library_db): ...
def test_list_cards_default_excludes_notes(tmp_path): ...       # upsert one book + one notes card
def test_search_excludes_notes(tmp_path): ...
def test_notebook_accessors(tmp_path): ...                      # notebook_for / library_notebook
def test_upsert_relations_keeps_manual_rows(tmp_path): ...
# test_models.py (additions)
def test_book_card_defaults_kind_book(): ...
def test_relation_origin_manual_and_source_format_tree(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug bookstore-notebooks-shared-pageindex --feature-id FEAT-876`).
   Run tests with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
2. **Read the spec** at the path above (§2 Overview, the module section named in Context, §6, §7).
3. **Check dependencies** — every `Depends-on` task must be `done` in
   `sdd/tasks/index/bookstore-notebooks-shared-pageindex.json`.
4. **Verify the Codebase Contract** before writing code; if an entry is stale, fix the contract here first.
   Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `in-progress` (set `started_at`) and commit only that file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
7. **Validate**: `ruff check --fix <files>` and the Validation Commands below.
8. **Commit the code** — stage only the files listed in this task.
9. **Close** with `parrot sdd task close TASK-5475 bookstore-notebooks-shared-pageindex verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
