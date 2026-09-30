---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: hotfix
base_branch: main
projects: [ai-parrot]
tags: [bookstore, pageindex, cli, ingest, catalog]
---

# Feature Specification: Bookstore re-index identity, graph invalidation, title collision guard and card editing

**Identity**: bookstore-reindex-identity (hotfix — slug identity, no Jira key yet; see §8 Q1)
**Date**: 2026-09-30
**Author**: jesuslarag@gmail.com
**Status**: draft
**Target version**: next patch release of `ai-parrot`
**Type**: hotfix
**Base branch**: main

---

## 1. Motivation & Business Requirements

### Problem Statement

Two defects surfaced while indexing the *Odoo 19 Development Cookbook* code
companion (20 chapter files) into a project-scoped bookstore library
(`agents/odoo_hd/library`, git-ignored):

1. **`--force` after changing a file creates a `<slug>-2` duplicate instead
   of replacing the book.** `Bookstore.add_book()` identifies an already
   catalogued book **only** by the sha256 of the file bytes
   (`library.py:966-971`). When the source file content changes, the sha no
   longer matches, `existing` is `None`, the call takes the *added* branch,
   `unique_slug()` finds the stem's slug already taken and yields
   `<slug>-2`. The old row and old PageIndex tree stay behind. Today
   `--force` only ever re-indexes a byte-identical file — the least useful
   case — and the only way to replace a changed book is
   `bookstore remove` + `bookstore add` (or rebuilding the whole library, as
   was done).

2. **The existing "updated" path leaves stale graph edges.** When `--force`
   *does* hit (byte-identical file), `add_book()` deletes and rebuilds the
   tree and upserts the card, but never touches `book_relations`,
   `relation_judgements` or the community partition — unlike
   `remove_book()` (`library.py:1249-1277`), which cascades across every
   scope store. Relations judged over the old content survive the re-index.

3. **Twenty chapter-books received the same LLM title.** The carding prompt
   (`carding.py:20-43`) instructs the model to return "the real book title
   (not the filename)"; the 20 chapter files are parts of one work, so the
   model answered *Odoo 19 Development Cookbook* for every one. Nothing in
   the ingest path detects that a freshly carded title already exists in
   the catalog, so `bookstore list` and `catalog_search` show 20
   indistinguishable entries. A private script
   (`agents/odoo_hd/retitle_library.py`) worked around it by calling
   `Bookstore._catalog("project").upsert(card)` — a private API.

4. **There is no public way to edit a ficha field.** `bookstore add` takes
   `--title/--author/--topic` at ingest time, `bookstore add-folder` takes
   none, and `bookstore card --refresh` re-runs LLM carding. Correcting a
   title, authors, topics or summary after the fact requires either a
   full re-index or the private-API workaround above.

### Goals

- G1 — A changed file at the **same resolved source path** re-indexes **in
  place** (same `book_id`, same tree name, row replaced), with status
  `updated`, without `--force`. `--force` keeps its current meaning
  (re-index a byte-identical file).
- G2 — Every in-place re-index (`updated`, whether by sha+force or by
  path+changed content) invalidates that book's relations, judgements and
  the community partition through the **same cascade `remove_book()` uses**.
- G3 — A freshly carded title that already exists in the library
  (case-insensitive, across both scopes) is deterministically disambiguated
  before the card is persisted, without an LLM call. An explicit
  `title=`/`--title` is never altered.
- G4 — A public `Bookstore.update_card()` method and a `bookstore update`
  CLI command edit `title`, `authors`, `topics` and `summary` of an existing
  card, marking it `card_origin="manual"`.
- G5 — Existing behaviour is preserved: sha match without `--force` is
  still `skipped`; two **different** files with the same title still get
  `<slug>` and `<slug>-2` (`test_slug_collision_suffixing`); a book moved
  to another path with identical bytes is still `skipped`.

### Non-Goals (explicitly out of scope)

- Changing the carding prompt (`_CARD_PROMPT`) or passing the markdown H1
  to the LLM. The deterministic guard (G3) covers the collision; prompt
  tuning is a separate, LLM-behaviour change.
- A `--title` option on `bookstore add-folder`, or any per-file title
  mapping for folder ingest.
- Renaming the PageIndex tree (`tree_name`) or its `doc_name` when a title
  is edited — the tree name is the stable `book_id` and stays untouched.
- Treating "same sha at a different path" as a move/rename (updating
  `source_path`). It remains `skipped` as today.
- Handling a re-index failure mid-way (tree deleted, row still present) —
  pre-existing behaviour of the `updated` path, recorded in §7 risks.
- Schema migrations. `source_path` already exists as a `NOT NULL` column
  (`catalog.py:54`); only a lookup is added.
- Any change to `BookstoreToolkit` / the MCP server (read-only surface).
- Migrating or fixing the existing `agents/odoo_hd/library` data.

---

## 2. Architectural Design

### Overview

Four small, additive changes inside `parrot/knowledge/bookstore/`:

1. **Source-path identity (M1).** `CatalogStore.find_by_path()` looks a card
   up by its stored `source_path`. `add_book()` resolves `existing` as
   *sha match* first, then *path match*. A path match with a different sha
   is a new version of the same book → status `updated`, `book_id` reused,
   old tree deleted, tree rebuilt under the same name, row upserted (same
   primary key, so no duplicate). A sha match keeps today's `skipped` /
   `updated`-with-`force` semantics. `unique_slug()` is only consulted on
   the `added` branch, exactly as today.

2. **Shared graph-invalidation cascade (M2).** The block in
   `remove_book()` that walks every scope store calling
   `delete_relations(book_id=…)` + `delete_judgements(book_id)` and then
   `_clear_communities()` is extracted into
   `Bookstore._invalidate_graph(book_id)`. `remove_book()` calls it
   (behaviour unchanged) and `add_book()` calls it on every `updated`
   re-index right after `delete_tree()`.

3. **Title collision guard (M3).** A pure function
   `carding.disambiguate_title()` returns the title unchanged when it is
   not taken, otherwise `"<title> — <hint>"`, where the hint is the first
   ToC entry whose title differs from the card title, else the
   de-slugified filename stem, else `"<title> — <stem> (N)"`. `add_book()`
   applies it to the *drafted* title only (never to an explicit `title=`),
   with the taken set built from `self.list_books()` across both scopes
   minus the book being (re)indexed.

4. **Card editing (M4).** `Bookstore.update_card(book_id, *, title=None,
   authors=None, topics=None, summary=None)` (sync — it is a catalog
   write, no awaits) resolves the book, applies the provided fields via
   `model_copy(update=…)`, sets `card_origin="manual"`, upserts into the
   owning scope and returns the card. Community stamps are preserved (same
   rule as `refresh_card()`). A new `bookstore update <book_id>` Click
   command exposes it; passing no field is a `ClickException`.

### Component Diagram
```
bookstore add / add-folder ──→ Bookstore.add_book()
                                  │  sha match? ──yes──→ skipped | (force) updated
                                  │  path match? ─yes──→ updated  (same book_id)
                                  │  else ───────────→ added    (unique_slug)
                                  ├─ updated: delete_tree → _invalidate_graph (M2) → rebuild
                                  ├─ _draft_card → disambiguate_title (M3) → BookCard
                                  └─ catalog.upsert
bookstore remove ─────────────→ Bookstore.remove_book() ──→ _invalidate_graph (M2)
bookstore update ─────────────→ Bookstore.update_card()  ──→ catalog.upsert   (M4)
CatalogStore.find_by_path()  ←── M1 (SELECT * FROM books WHERE source_path = ?)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `CatalogStore` (`catalog.py:163`) | extends | new `find_by_path()` next to `find_by_sha()` |
| `Bookstore.add_book()` (`library.py:922`) | modifies | identity resolution, cascade call, title guard |
| `Bookstore.remove_book()` (`library.py:1249`) | modifies | delegates its cascade to `_invalidate_graph()` |
| `Bookstore.refresh_card()` (`library.py:1279`) | sibling | `update_card()` follows its `model_copy` + `upsert` pattern |
| `carding.unique_slug()` (`carding.py:73`) | sibling | `disambiguate_title()` is the title-level analogue |
| `cli.card_cmd` (`cli.py:351`) | sibling | new `update` command placed right after it |
| `BookCard.card_origin` (`models.py:176`) | uses | `"manual"` already a valid literal |

### Data Models

No new models and no schema change. `BookCard` is reused as-is; `status`
strings returned by `add_book()` stay `"added" | "updated" | "skipped"`.

### New Public Interfaces
```python
# parrot/knowledge/bookstore/catalog.py
class CatalogStore:
    def find_by_path(self, source_path: str) -> Optional[BookCard]: ...

# parrot/knowledge/bookstore/carding.py
def disambiguate_title(title: str, taken: set[str], *, toc_entries: list[TocEntry], stem: str) -> str: ...

# parrot/knowledge/bookstore/library.py
class Bookstore:
    def update_card(self, book_id: str, *, title: Optional[str] = None, authors: Optional[list[str]] = None,
                    topics: Optional[list[str]] = None, summary: Optional[str] = None) -> BookCard: ...

# CLI
# bookstore update <book_id> [--title T] [--author A]... [--topic X]... [--summary S]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: source-path identity | yes | `find_by_path` mirrors `find_by_sha` byte for byte; `existing = find_by_sha(sha) or find_by_path(str(path))`; status matrix in §5 AC-1..AC-4 | — |
| M2: graph invalidation cascade | yes | method body is the verbatim block moved out of `remove_book()` (`library.py:1270-1275`) plus `_clear_communities()` | — |
| M3: title collision guard | yes | pure function, exact fallback order fixed in §3 skeleton; applied only when `title is None` | — |
| M4: `update_card` + CLI | yes | `model_copy(update=…)` + `upsert` as in `refresh_card()`; Click options fixed below | — |

### Module 1: Source-path identity in `add_book`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py`, `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py`
- **Responsibility**: resolve "is this book already in the catalog?" by sha **or** by resolved source path, and rebuild in place on a path match.
- **Depends on**: Module 2 (`_invalidate_graph` is called from the `updated` branch).
- **Interface Skeleton**:
  ```python
  # catalog.py  (modifies catalog.py:380 — insert after find_by_sha)
  def find_by_path(self, source_path: str) -> Optional[BookCard]:  # sibling of find_by_sha verified: catalog.py:380
      """Find the card whose ``source_path`` equals ``source_path`` (exact string match on the stored resolved path)."""

  # library.py  (modifies add_book, library.py:966-979)
  # existing = catalog.find_by_sha(sha256) or catalog.find_by_path(str(path))   # verified anchor: library.py:967
  # status matrix:
  #   sha match & not force        -> return existing (scope-stamped), "skipped"   (unchanged)
  #   sha match & force            -> "updated"                                   (unchanged)
  #   no sha match & path match    -> "updated"  (NEW — no force needed)
  #   neither                      -> "added"    (unchanged; unique_slug)
  # on "updated": slug = existing.book_id; await toolkit.delete_tree(slug); self._invalidate_graph(slug)  # verified: library.py:976-977
  ```
  `add_book()`'s docstring `force:` and `Returns:` lines are updated to
  state the path rule. `add_folder()` docstring `force:` likewise
  (`library.py:1214`).

### Module 2: Graph invalidation cascade
- **Path**: `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py`
- **Responsibility**: one method that drops a book's relations, judgements and the community partition across every scope store; used by `remove_book()` and by every `updated` re-index.
- **Depends on**: nothing new (`CatalogStore.delete_relations` `catalog.py:515`, `delete_judgements` `catalog.py:639`, `Bookstore._clear_communities` `library.py:806`).
- **Interface Skeleton**:
  ```python
  # library.py  (new method, placed immediately before remove_book, library.py:1249)
  def _invalidate_graph(self, book_id: str) -> None:
      """Drop every relation/judgement touching ``book_id`` in every scope store and clear the persisted
      community partition (spec §7 cross-scope rule: an edge lives in the store owning its ``src``)."""
      # body = the loop at library.py:1270-1272 + self._clear_communities()

  # remove_book (modifies library.py:1270-1276): replace the inline loop + conditional clear with
  #   removed = self._catalog(loc.scope).remove(book_id); self._invalidate_graph(book_id); return removed
  # NOTE: today _clear_communities() runs only when a row was removed; after the change it runs unconditionally
  # inside _invalidate_graph — acceptable, it is idempotent (deletes rows + clears stamps).
  ```

### Module 3: Title collision guard
- **Path**: `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py`, `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py`
- **Responsibility**: make an LLM/fallback-drafted title unique within the merged library, deterministically.
- **Depends on**: nothing new (`TocEntry` `models.py:98`).
- **Interface Skeleton**:
  ```python
  # carding.py  (new function, placed immediately after unique_slug, carding.py:73-85)
  def disambiguate_title(title: str, taken: set[str], *, toc_entries: list[TocEntry], stem: str) -> str:
      """Return ``title`` when its casefold is not in ``taken``; otherwise ``"<title> — <hint>"`` with, in order:
      (1) the first ``toc_entries`` title whose casefold differs from ``title``'s casefold and whose combination
      is not taken; (2) the de-slugified ``stem`` (same transform as fallback_card_fields, carding.py:151-152);
      (3) ``"<title> — <stem> (N)"`` for the first free N >= 2. ``taken`` holds casefolded titles.
      Never returns a title whose casefold is in ``taken``."""

  # library.py  (modifies add_book after _draft_card, anchor library.py:1045)
  # if title is None:
  #     taken = {c.title.casefold() for c in self.list_books() if c.book_id != slug}
  #     final_title = disambiguate_title(draft.title, taken, toc_entries=toc_entries, stem=path.stem)
  # else: final_title = title
  # BookCard(title=final_title, ...)   — card_origin unchanged ("llm" / "fallback" / "manual")
  ```
  `refresh_card()` is **not** guarded (it rewrites one existing card; a
  collision there is the operator's explicit action).

### Module 4: `update_card` + `bookstore update`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py`, `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py`
- **Responsibility**: public, non-LLM edit of the descriptive card fields.
- **Depends on**: nothing new (`resolve_book` `library.py:269`, `CatalogStore.upsert` `catalog.py:300`, `_echo_card` `cli.py:62`, `_open_bookstore` `cli.py:33`).
- **Interface Skeleton**:
  ```python
  # library.py  (new method, placed immediately after refresh_card, library.py:1279-1320)
  def update_card(
      self,
      book_id: str,
      *,
      title: Optional[str] = None,
      authors: Optional[list[str]] = None,
      topics: Optional[list[str]] = None,
      summary: Optional[str] = None,
  ) -> BookCard:
      """Overwrite the given descriptive fields of an existing card and persist it in its owning scope.
      Only non-``None`` arguments are applied; ``title``/``summary`` are stripped and an empty ``title`` raises
      ``BookstoreError``. Sets ``card_origin="manual"``. ``community_id``/``community_label`` survive untouched.
      Raises ``BookstoreError`` when ``book_id`` is unknown or no field was given."""

  # cli.py  (new command, placed immediately before @bookstore.command("related"), cli.py:373)
  @bookstore.command("update")
  @click.argument("book_id")
  @click.option("--title", default=None, help="New title.")
  @click.option("--author", "authors", multiple=True, help="Replace authors (repeatable).")
  @click.option("--topic", "topics", multiple=True, help="Replace topics (repeatable).")
  @click.option("--summary", default=None, help="New summary.")
  def update_cmd(book_id: str, title: Optional[str], authors: tuple[str, ...], topics: tuple[str, ...], summary: Optional[str]) -> None:
      """Edit a book's ficha fields without re-indexing (marks the card as manual)."""
      # no field given -> click.ClickException("Nothing to do — pass --title/--author/--topic/--summary")
      # store = _open_bookstore(require_exists=True, use_llm=False); BookstoreError -> ClickException; _echo_card(card)
  ```

---

## 4. Test Specification

All tests live in `packages/ai-parrot/tests/knowledge/bookstore/` and reuse
the existing fixtures (`store`, `store_no_llm`, `book_md`, `locations`,
`fake_adapter` — `conftest.py`). The `fake_adapter` returns a fixed card
title for every structured call, which is exactly the collision M3 guards.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_find_by_path_roundtrip` (`test_catalog.py`) | M1 | `upsert` then `find_by_path(card.source_path)` returns the card; unknown path → `None` |
| `test_add_book_changed_content_same_path_updates_in_place` (`test_library.py`) | M1 | add, rewrite file with different bytes, add again **without** force → `("added","updated")`, same `book_id`, `list_books()` has exactly one entry, no `-2` slug, new sha stored, tree readable |
| `test_add_book_sha_skip_and_force` (existing) | M1 | unchanged — still `("added","skipped")` then `updated` with force |
| `test_add_book_same_bytes_other_path_is_skipped` (`test_library.py`) | M1 | copy file to a new path, add → `skipped`, `source_path` unchanged |
| `test_slug_collision_suffixing` (existing) | M1 | unchanged — different paths, different bytes → `-2` |
| `test_add_folder_changed_file_updates_not_duplicates` (`test_library.py`) | M1 | folder rerun after editing one file → that file `updated`, others `skipped`, book count unchanged |
| `test_reindex_invalidates_relations_and_communities` (`test_library.py`) | M2 | seed a relation + judgement + community stamp for the book, re-index in place → `related_books()` empty, `judged_pairs()` empty, `communities()` empty |
| `test_remove_book` (existing) | M2 | unchanged behaviour after the extraction |
| `test_disambiguate_title_*` (`test_library.py`, 4 cases) | M3 | not taken → unchanged; taken + distinct ToC entry → `"T — <toc>"`; taken + no usable ToC → `"T — <Stem>"`; both taken → `"T — <Stem> (2)"`; case-insensitive membership |
| `test_add_book_llm_duplicate_title_is_disambiguated` (`test_library.py`) | M3 | two different files carded to the same title (fake adapter) → second title differs, first unchanged |
| `test_add_book_explicit_title_never_disambiguated` (`test_library.py`) | M3 | `title="Same Title"` twice on different files → both cards keep `"Same Title"` (slug `-2` only) |
| `test_update_card_fields_and_manual_origin` (`test_library.py`) | M4 | edits title/authors/topics/summary, `card_origin == "manual"`, community stamp preserved, persisted (re-read via `get_card`) |
| `test_update_card_requires_a_field` (`test_library.py`) | M4 | no kwargs → `BookstoreError`; unknown id → `BookstoreError` |
| `test_update_command_edits_title` (`test_cli.py`) | M4 | `CliRunner` invokes `update <id> --title X`, exit 0, echoed card shows X |
| `test_update_command_without_fields_fails` (`test_cli.py`) | M4 | exit code ≠ 0 with "Nothing to do" |

### Integration Tests
| Test | Description |
|---|---|
| `test_add_folder_changed_file_updates_not_duplicates` | end-to-end folder rerun through `Bookstore.add_folder()` (counts as integration for this hotfix) |

### Test Data / Fixtures
```python
# Reuse conftest.py fixtures; the only new helper is an inline "rewrite the file" step:
book_md.write_text(SAMPLE_MARKDOWN + "\n## New chapter\n\nChanged content.\n", encoding="utf-8")
```

Validation commands:
```bash
source .venv/bin/activate
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/bookstore -q
ruff check packages/ai-parrot/src/parrot/knowledge/bookstore packages/ai-parrot/tests/knowledge/bookstore
```

---

## 5. Acceptance Criteria

> This hotfix is complete when ALL of the following are true:

- [ ] AC-1 — `add_book(path)` on a file whose bytes changed since it was catalogued at the **same resolved path** returns status `updated`, reuses the previous `book_id`/`tree_name`, and the catalog holds exactly one row for that path (no `<slug>-2`). No `force` needed.
- [ ] AC-2 — `add_book(path)` on a byte-identical file still returns `skipped` without `force` and `updated` with `force` (existing test unchanged).
- [ ] AC-3 — A byte-identical file at a **different** path is still `skipped` and `source_path` is not rewritten.
- [ ] AC-4 — Two different files that would slug to the same id still produce `<slug>` and `<slug>-2` (`test_slug_collision_suffixing` unchanged).
- [ ] AC-5 — Every `updated` re-index deletes that book's relations and judgements in every scope store and clears the community partition, via the same `_invalidate_graph()` that `remove_book()` now calls; `test_remove_book` still passes.
- [ ] AC-6 — When no explicit title is given and the drafted title (LLM or fallback) already exists in the merged library (case-insensitive), the persisted title is `"<title> — <hint>"` per the §3 M3 order, never equal to an existing title; an explicit `title=`/`--title` is persisted verbatim.
- [ ] AC-7 — `Bookstore.update_card()` applies only the given fields, sets `card_origin="manual"`, keeps `community_id`/`community_label`, persists via `upsert` (FTS row refreshed), and raises `BookstoreError` on unknown id, empty title, or no field.
- [ ] AC-8 — `bookstore update <book_id> [--title] [--author…] [--topic…] [--summary]` exists, prints the card, exits non-zero with a clear message when no field is passed.
- [ ] AC-9 — `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/bookstore -q` passes, and `ruff check` on the bookstore package and its tests is clean.
- [ ] AC-10 — No change to `BookstoreToolkit`, `mcp_server.py`, the `books` DDL, or `_CARD_PROMPT`.
- [ ] AC-11 — `docs/bookstore-codex.md` is untouched (it does not document `--force`); the CLI `--help` strings for `add`/`add-folder --force` and the new `update` command are the documentation.

---

## 6. Codebase Contract

> Verified against `origin/main` @ `08a71b55b` (2026-09-30). The bookstore
> package and its tests are byte-identical between `origin/main` and
> `origin/dev` at spec time (`git diff --stat` empty), so line numbers hold
> on both.

### Verified Imports
```python
from parrot.knowledge.bookstore.catalog import CatalogStore            # verified: catalog.py:163
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError  # verified: library.py:181 (class), BookstoreError(RuntimeError) verified: library.py:100
from parrot.knowledge.bookstore.carding import slugify, unique_slug, derive_toc, fallback_card_fields  # verified: carding.py:49,73,88,140
from parrot.knowledge.bookstore.models import BookCard, CardDraft, TocEntry  # verified: models.py:152,117,98
from parrot.knowledge.bookstore import cli as bookstore_cli             # verified: tests/knowledge/bookstore/test_cli.py:9
from click.testing import CliRunner                                     # verified: tests/knowledge/bookstore/test_cli.py:7
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py
class CatalogStore:                                                       # line 163
    def __init__(self, db_path: Path | str) -> None                       # line 171
    def _connection(self) -> Iterator[sqlite3.Connection]                 # line 183 (contextmanager; rows are sqlite3.Row)
    def _row_to_card(row: sqlite3.Row) -> BookCard                        # line 286 (staticmethod)
    def upsert(self, card: BookCard) -> None                              # line 300 (DELETE+INSERT FTS row; scope not stored)
    def remove(self, book_id: str) -> bool                                # line 357
    def get(self, book_id: str) -> Optional[BookCard]                     # line 374
    def find_by_sha(self, sha256: str) -> Optional[BookCard]              # line 380  ← M1 mirrors this
    def list_cards(self) -> list[BookCard]                                # line 386
    def taken_slugs(self) -> set[str]                                     # line 392
    def delete_relations(self, book_id: Optional[str] = None, origin: Optional[str] = None) -> int  # line 515
    def delete_judgements(self, book_id: str) -> int                      # line 639
# books DDL: book_id TEXT PRIMARY KEY (line 44) … source_path TEXT NOT NULL (54), source_sha256 TEXT NOT NULL (55)
# _JSON_COLUMNS = ("authors", "topics", "toc", "traditions")             # line 160

# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
class Bookstore:                                                          # line 181 (__init__)
    def has_llm(self) -> bool                                             # line 204 (property)
    def _catalog(self, scope: str) -> CatalogStore                        # line 217
    def _toolkit(self, scope: str) -> PageIndexToolkit                    # line 222
    def _stores(self) -> list[tuple[str, CatalogStore]]                   # line 238
    def _all_taken_slugs(self) -> set[str]                                # line 241
    def list_books(self) -> list[BookCard]                                # line 261 (merged, project precedence)
    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]  # line 269 (raises BookstoreError)
    def get_card(self, book_id: str) -> BookCard                          # line 281
    def related_books(...)                                                # line 493
    def _clear_communities(self) -> None                                  # line 806
    def communities(self) -> list[BookCommunity]                          # line 823
    async def add_book(self, file_path, scope="project", title=None, authors=None, topics=None, force=False, *, relate=False) -> tuple[BookCard, str]  # line 922
    async def _draft_card(self, path, tree_name, scope, doc_description, toc_digest, toc_entries) -> CardDraft  # line 1081
    async def add_folder(self, folder, scope="project", recursive=False, force=False, *, relate=False) -> dict[str, Any]  # line 1194
    async def remove_book(self, book_id: str) -> bool                     # line 1249
    async def refresh_card(self, book_id: str) -> BookCard                # line 1279 (model_copy(update=…) + upsert pattern)
# add_book identity block (lines 966-979):
#   sha256 = hashlib.sha256(payload).hexdigest()
#   existing = catalog.find_by_sha(sha256)
#   status = "added"; if existing: if not force: return existing.model_copy(update={"scope": scope}), "skipped"; status = "updated"
#   if status == "updated": slug = existing.book_id; await toolkit.delete_tree(slug)
#   else: slug = unique_slug(slugify(title or path.stem), self._all_taken_slugs())
# add_book card build: draft = await self._draft_card(...) (1035-1042); card_origin = ... (1045); BookCard(title=title or draft.title, ...) (1053+); catalog.upsert(card) (1076)
# remove_book cascade (lines 1270-1275):
#   for _scope, store in self._stores(): store.delete_relations(book_id=book_id); store.delete_judgements(book_id)
#   removed = self._catalog(loc.scope).remove(book_id); if removed: self._clear_communities()

# packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py
def slugify(text: str) -> str                                             # line 49
def unique_slug(base: str, taken: set[str]) -> str                        # line 73
def derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str]  # line 88
def fallback_card_fields(file_path: Path, toc_entries: list[TocEntry]) -> CardDraft     # line 140 (stem → title transform at 151-152)
async def generate_card_fields(adapter, *, filename, doc_description, toc_digest, samples) -> CardDraft  # line 157

# packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
class TocEntry(BaseModel): node_id: str; title: str; depth: int = 1; start_page; end_page   # line 98
class CardDraft(BaseModel): title: str; authors; year; language; topics; summary; genre; traditions; period  # line 117
class BookCard(BaseModel):                                                # line 152
    book_id: str; title: str; authors: list[str]; topics: list[str]; summary: str = ""
    tree_name: str; scope: Literal["project","global"]; source_path: str; source_sha256: str
    card_origin: Literal["llm","fallback","manual"] = "llm"               # line 176
    community_id: Optional[str]; community_label: Optional[str]           # lines 180-181

# packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py
def _open_bookstore(llm_spec=None, *, require_exists=False, scope_needed=None, use_llm=True)  # line 33 (see call sites 252, 431)
def _echo_card(card: Any) -> None                                         # line 62
@bookstore.command("add")        def add(...)                             # lines 102-155 (--title/--author/--topic/--force)
@bookstore.command("add-folder") def add_folder(...)                      # lines 158-244 (--force, no --title)
@bookstore.command("card")       def card_cmd(book_id, refresh, llm)      # lines 351-370 ("Nothing to do — pass --refresh" pattern)
@bookstore.command("related")                                             # line 373  ← M4 command inserted before this
@bookstore.command("remove")     def remove(book_id, yes)                 # line 524
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CatalogStore.find_by_path()` | `books.source_path` column | `SELECT * FROM books WHERE source_path = ?` | `catalog.py:54`, pattern `catalog.py:380-384` |
| `Bookstore.add_book()` (M1) | `find_by_sha` / `find_by_path` | `or` chain | `library.py:967` |
| `Bookstore.add_book()` (M2) | `_invalidate_graph()` | call after `delete_tree(slug)` | `library.py:977` |
| `Bookstore._invalidate_graph()` | `CatalogStore.delete_relations/delete_judgements`, `_clear_communities` | loop over `_stores()` | `library.py:1270-1275`, `catalog.py:515,639`, `library.py:806` |
| `Bookstore.add_book()` (M3) | `disambiguate_title()` | applied to `draft.title` when `title is None` | `library.py:1045-1053` |
| `Bookstore.update_card()` | `resolve_book()`, `CatalogStore.upsert()` | `model_copy(update=…)` then upsert into `loc.scope` | `library.py:269`, `catalog.py:300`, pattern `library.py:1279-1320` |
| `cli.update_cmd` | `Bookstore.update_card()`, `_echo_card` | `asyncio` not needed (sync) | `cli.py:62`, `cli.py:359-370` |

### Does NOT Exist (Anti-Hallucination)
- ~~`CatalogStore.find_by_path()`~~ — does not exist yet (M1 creates it). Only `find_by_sha()` exists.
- ~~`CatalogStore.get_by_source()` / `find_by_source_path()`~~ — do not exist; use the M1 name.
- ~~`Bookstore._invalidate_graph()`~~ — does not exist yet (M2 creates it); the cascade is inline in `remove_book()`.
- ~~`Bookstore.update_card()` / `set_title()` / `retitle()`~~ — do not exist (M4 creates `update_card`).
- ~~`carding.disambiguate_title()` / `unique_title()`~~ — do not exist (M3 creates `disambiguate_title`).
- ~~`bookstore update` / `bookstore set-title` / `bookstore retitle` CLI commands~~ — do not exist (M4 adds `update`).
- ~~`CatalogStore.taken_titles()`~~ — does not exist; M3 builds the set from `Bookstore.list_books()` instead (no new catalog method).
- ~~`BookCard.updated_at`~~ — no such column/field; do not add one.
- ~~`CatalogStore.find_by_sha(sha, scope=…)`~~ — catalogs are per-scope objects; there is no scope parameter.
- ~~`add_book(..., replace=True)`~~ — no new flag; the path rule is implicit.
- ~~`tests/knowledge/bookstore/test_carding.py`~~ — no such file; carding tests live in `test_library.py` (e.g. `test_card_prompt_requests_classification`, line 401).

### Edit Sites (Blueprint Anchors)

Verified against: `08a71b55b` (`origin/main`, 2026-09-30)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | MODIFY | `    def find_by_sha(self, sha256: str) -> Optional[BookCard]:` | `catalog.py:380` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `        existing = catalog.find_by_sha(sha256)` | `library.py:967` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `            slug = existing.book_id` | `library.py:976` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `        card_origin = "fallback" if not self.has_llm else "llm"` | `library.py:1045` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `        for _scope, store in self._stores():` **inside `remove_book`**, followed by `            store.delete_relations(book_id=book_id)` and `            store.delete_judgements(book_id)` | `library.py:1270-1272` | 4 (ambiguous — use the 3-line context) |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    async def refresh_card(self, book_id: str) -> BookCard:` | `library.py:1279` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py` | MODIFY | `def unique_slug(base: str, taken: set[str]) -> str:` | `carding.py:73` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `@bookstore.command("related")` | `cli.py:373` | 1 |
| `packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py` | MODIFY | `def test_merged_relations_filters_dangling_and_project_wins(tmp_path):` (append after) | `test_catalog.py:393` | 1 |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | `async def test_add_book_sha_skip_and_force(store, book_md):` (insert after) | `test_library.py:58` | 1 |
| `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` | MODIFY | `def test_show_prints_classification(capsys):` (append after) | `test_cli.py:297` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `find_by_path` copies `find_by_sha` verbatim with the column swapped; the stored value is `str(path)` of the **resolved** path (`add_book` already resolves: `Path(file_path).expanduser().resolve()`, `library.py:957`), so the lookup is an exact string match — no normalisation in SQL.
- `update_card` follows `refresh_card` (`library.py:1279-1320`): `resolve_book` → `model_copy(update=…)` → `self._catalog(loc.scope).upsert(updated)`; never touch `community_id`/`community_label`.
- `_invalidate_graph` is a plain sync method (all catalog calls are sync sqlite); keep the cross-scope loop exactly as it is in `remove_book` today (spec §7 of `wikitoolkit-bookstore-conceptual-relations`: an edge lives in the store owning its `src`).
- `disambiguate_title` is pure and lives next to `unique_slug`; the stem transform reuses the two-line expression from `fallback_card_fields` (`carding.py:151-152`) — factor it into a tiny private helper `_stem_to_title(stem)` used by both, no behaviour change.
- The M3 taken-set is built **after** the slug is known so the book being re-indexed excludes its own previous title (`c.book_id != slug`).
- `bookstore update` mirrors `card_cmd`'s error style ("Nothing to do — pass …") and `_open_bookstore(require_exists=True, use_llm=False)` as in `show`/`toc` (`cli.py:285,306`).
- Keep diffs minimal; no reformatting of untouched code. `black` line length 120; `ruff check` clean.

### Known Risks / Gotchas
- **Path match with `--force` on a byte-identical file at a *new* path**: sha wins (checked first) → today's behaviour (`updated`, old `book_id`, but `source_path` is rewritten to the new path since the card is rebuilt from `path`). This is pre-existing and acceptable; note it in the docstring.
- **Two catalog rows sharing a `source_path`** cannot arise from `add_book` after this change, but legacy libraries created before it can hold `<slug>` and `<slug>-2` for the same path. `find_by_path` returns the first row by `rowid`; the operator resolves legacy duplicates with `bookstore remove`. Not migrated here (Non-Goal).
- **Re-index failure after `delete_tree`**: on the `updated` path an exception during import deletes the *new* tree but the old catalog row survives pointing at a missing tree (pre-existing). The cascade (M2) has already run, so relations are gone too. Documented, not fixed here.
- **`_clear_communities` now runs on every `updated` re-index**, so a folder rerun that updates several files clears the partition several times — idempotent and cheap (tiny tables); `add_folder(relate=True)` recomputes communities once at the end as today.
- **Fallback (no-LLM) titles** derive from the stem and are unique per file name, so M3 rarely triggers there; the guard still applies uniformly.
- **`fake_adapter` in tests returns one fixed title** — existing tests that add two different files with the LLM store (`test_slug_collision_across_scopes_is_suffixed`, line 137) may now observe a disambiguated *title* on the second book. Those tests assert on `book_id`, not title; verify and adjust only assertions on `title` if any exist.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none added; sqlite3, click, pydantic already in use |

---

## 8. Open Questions

- [ ] Q1 — Jira key for this hotfix: none was provided. The worktree naming rule (`hotfix-<JIRA-KEY>-<slug>`) needs one; until then the work proceeds on branch `hotfix/bookstore-reindex-identity` (created from `origin/main`) with slug identity, as `codex-dispatch-stdin-isolation.spec.md` did. — *Owner: user*
- [x] Should a changed file at the same path require `--force`? — *Resolved by the user in conversation (2026-09-30)*: no — automatic `updated`; `--force` keeps meaning "re-index a byte-identical file".
- [x] Prompt change vs deterministic guard for duplicate titles? — *Resolved by the user*: deterministic guard only (M3); the prompt is untouched.
- [x] Separate `update` command vs extending `card`? — *Decided in spec*: separate `bookstore update` command; `card --refresh` keeps its single LLM-refresh purpose.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: — · Status: skipped (no accepted brainstorm/proposal exists for this hotfix; the spec was written directly from the conversation and the code)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one hotfix worktree, `.claude/worktrees/hotfix-bookstore-reindex-identity` on branch `hotfix/bookstore-reindex-identity` from `origin/main` (the shared primary checkout stays on `dev`; other sessions were active on it at spec time). If a Jira key arrives, rename per `plan_worktree` (`hotfix-<KEY>-bookstore-reindex-identity`).
- **Module dependency graph**: M1 → M2 (`add_book`'s `updated` branch calls `_invalidate_graph`). M3 and M4 are independent of each other and of M1/M2.
- **Shared files**: `library.py` is touched by M1, M2, M3 and M4 (distinct regions: 966-979 / 1045-1053 / 1249-1276 / after 1279); `test_library.py` by all. Tasks on `library.py` serialize. `catalog.py` (M1 only), `carding.py` (M3 only), `cli.py` (M4 only).
- **Exclusive resources**: none (no extension rebuild, lockfile or migration).
- **Cross-feature dependencies**: none. `FEAT-613 pageindex-md-builder-fixes` touches `parrot/knowledge/pageindex/md_builder.py`, not the bookstore package.
- **Decomposition**: this is a one-or-two-commit hotfix; the single-agent path may implement it directly from this spec without `/sdd-task`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-30 | jesuslarag@gmail.com | Initial draft — path identity, graph invalidation, title collision guard, card editing |
