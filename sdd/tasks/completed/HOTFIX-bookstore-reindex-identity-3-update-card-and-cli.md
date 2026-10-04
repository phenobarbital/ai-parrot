# HOTFIX-bookstore-reindex-identity-3: `Bookstore.update_card()` and `bookstore update` command

**Feature**: bookstore-reindex-identity — Bookstore re-index identity, graph invalidation, title collision guard and card editing (hotfix)
**Spec**: `sdd/specs/bookstore-reindex-identity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: HOTFIX-bookstore-reindex-identity-2
**Assigned-to**: unassigned
**Index**: `sdd/tasks/index/bookstore-reindex-identity.json`

---

## Context

Spec §1 problem 4, module **M4**, acceptance criteria AC-7 and AC-8. There is
no public way to edit a ficha after ingest: `add-folder` takes no title,
`card --refresh` re-runs the LLM, and the only workaround called the private
`_catalog(...).upsert()`. This task adds a sync `update_card()` on
`Bookstore` and a `bookstore update` Click command.

Depends on task 2 only because both edit `library.py` and `test_library.py`
(shared-file serialization) — no symbol dependency.

---

## Scope

- Add `Bookstore.update_card(book_id, *, title=None, authors=None, topics=None, summary=None) -> BookCard` right after `refresh_card()`.
- Add `@bookstore.command("update")` in `cli.py` right before the `related` command.
- Tests: library (fields + manual origin + community preserved; error cases) and CLI (`update --title`, no-field failure).

**NOT in scope**: renaming the PageIndex tree / `doc_name`, editing `genre`/`traditions`/`period`/`year`/`language` (not requested), any LLM call, `BookstoreToolkit`/MCP changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `update_card()` after `refresh_card()` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `update` command before `related` |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | `update_card` tests |
| `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` | MODIFY | `update` command tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError     # verified: library.py:181 / 100
from parrot.knowledge.bookstore.models import BookCard                       # verified: models.py:152
from parrot.knowledge.bookstore.catalog import CatalogStore                  # verified: catalog.py:163
from parrot.knowledge.bookstore import cli as bookstore_cli                  # verified: test_cli.py:9
from parrot.knowledge.bookstore.config import ENV_LIBRARY_DIR                # verified: test_cli.py:10
from click.testing import CliRunner                                          # verified: test_cli.py:7
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
class BookstoreError(RuntimeError)                                            # line 100
class Bookstore:
    def _catalog(self, scope: str) -> CatalogStore                            # line 217
    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]  # line 269 (raises BookstoreError)
    def get_card(self, book_id: str) -> BookCard                              # line 281
    async def refresh_card(self, book_id: str) -> BookCard                    # line 1279 (+ shift from tasks 1-2) — pattern:
#       card, loc = self.resolve_book(book_id); updated = card.model_copy(update={...}); self._catalog(loc.scope).upsert(updated); return updated

# packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
class BookCard(BaseModel):                                                    # line 152
    book_id: str; title: str; authors: list[str]; topics: list[str]; summary: str = ""
    card_origin: Literal["llm", "fallback", "manual"] = "llm"                 # line 176
    community_id: Optional[str] = None; community_label: Optional[str] = None # lines 180-181

# packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py
    def upsert(self, card: BookCard) -> None                                  # line 300 (refreshes the FTS row)
    def set_card_community(self, book_id, community_id, community_label)      # used at library.py:822

# packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py
import asyncio, click; from typing import Optional; from pathlib import Path   # top of file
def _open_bookstore(llm_spec=None, *, require_exists=False, scope_needed=None, use_llm=True)   # line 33
def _echo_card(card: Any) -> None                                             # line 62
@bookstore.command("card") … def card_cmd(book_id: str, refresh: bool, llm: Optional[str]) -> None   # lines 351-370
#   if not refresh: raise click.ClickException("Nothing to do — pass --refresh")           # line 363
#   store = _open_bookstore(llm_spec=llm, require_exists=True)                               # line 364
#   try: card = asyncio.run(store.refresh_card(book_id)) except BookstoreError as exc: raise click.ClickException(str(exc)) from exc
@bookstore.command("related")                                                 # line 373 ← insert the new command ABOVE this decorator

# tests/knowledge/bookstore/test_cli.py: CLI tests set monkeypatch.setenv(ENV_LIBRARY_DIR, str(tmp_path / "lib")) (line 64) and seed a
#   CatalogStore(lib_dir / "library.db") with BookCard(...) rows (pattern lines 236-247), then CliRunner().invoke(bookstore_cli.bookstore, [...])
```

### Does NOT Exist
- ~~`Bookstore.update_card()` / `set_title()` / `retitle()`~~ — `update_card` is created by THIS task; the others never.
- ~~`bookstore set-title` / `bookstore retitle` / `bookstore edit`~~ — the command is `update`.
- ~~`CatalogStore.update()` / `patch()`~~ — only `upsert()` exists.
- ~~`PageIndexToolkit.rename_tree()`~~ — not used, not needed (tree name stays).
- ~~`BookCard.updated_at`~~ — no such field.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/bookstore/test_library.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/bookstore/test_cli.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.refresh_card",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.resolve_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#BookstoreError",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore.upsert",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookCard",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#card_cmd",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#_open_bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#_echo_card"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `update_card` is **sync** (no awaits: `resolve_book` and `upsert` are sync) — do not wrap it in `asyncio.run` in the CLI.
- Only non-`None` arguments are applied; `title`/`summary` are `.strip()`ped; an empty stripped `title` raises `BookstoreError`; no field at all raises `BookstoreError("Nothing to update")`.
- Always set `card_origin="manual"`; never touch `community_id`/`community_label` (same rule as `refresh_card`).
- CLI `--author`/`--topic` are repeatable and **replace** the list; an empty tuple means "not given" (pass `None`).
- Mirror `card_cmd`'s error style and `_open_bookstore(require_exists=True, use_llm=False)` as `show`/`toc` do (cli.py:285, 306).

---

## Implementation Blueprint

### Steps (in order)
1. Add `update_card` below `refresh_card` in `library.py` — *why*: same resolve → model_copy → upsert pattern, kept adjacent.
2. Add the `update` command above `related` in `cli.py` — *why*: groups it with `card`, the other ficha command.
3. Tests, Validation Commands, `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def refresh_card(self, book_id: str) -> BookCard:' library.py)
# AFTER — insert below the whole refresh_card method (it ends with `        return updated`; re-grep, tasks 1-2 shifted lines)

    def update_card(
        self,
        book_id: str,
        *,
        title: Optional[str] = None,
        authors: Optional[list[str]] = None,
        topics: Optional[list[str]] = None,
        summary: Optional[str] = None,
    ) -> BookCard:
        """Overwrite the given descriptive fields of an existing card and persist it.

        Only non-``None`` arguments are applied. ``title``/``summary`` are
        stripped; an empty ``title`` is rejected. Marks the card
        ``card_origin="manual"``; community stamps survive untouched.

        Raises:
            BookstoreError: Unknown ``book_id``, empty ``title``, or no field given.
        """
        if title is None and authors is None and topics is None and summary is None:
            raise BookstoreError("Nothing to update — pass title, authors, topics or summary")
        card, loc = self.resolve_book(book_id)
        changes: dict[str, Any] = {"card_origin": "manual"}
        # FILL IN: apply each non-None field into `changes` (strip title/summary; empty title → BookstoreError) — bounded by AC-7
        updated = card.model_copy(update=changes)
        self._catalog(loc.scope).upsert(updated)
        logger.info("update_card: %s (%s)", book_id, ", ".join(k for k in changes if k != "card_origin"))
        return updated
```
**Why**: identical persistence path to `refresh_card` so FTS stays in sync (AC-7); `Any` and `Optional` are already imported at library.py:25.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '@bookstore.command("related")' cli.py)
# BEFORE — insert above `@bookstore.command("related")` (cli.py:373)
@bookstore.command("update")
@click.argument("book_id")
@click.option("--title", default=None, help="New title.")
@click.option("--author", "authors", multiple=True, help="Replace the authors (repeatable).")
@click.option("--topic", "topics", multiple=True, help="Replace the topics (repeatable).")
@click.option("--summary", default=None, help="New summary.")
def update_cmd(
    book_id: str,
    title: Optional[str],
    authors: tuple[str, ...],
    topics: tuple[str, ...],
    summary: Optional[str],
) -> None:
    """Edit a book's ficha fields without re-indexing (marks the card as manual)."""
    from .library import BookstoreError

    if title is None and not authors and not topics and summary is None:
        raise click.ClickException("Nothing to do — pass --title, --author, --topic or --summary")
    store = _open_bookstore(require_exists=True, use_llm=False)
    try:
        card = store.update_card(
            book_id,
            title=title,
            authors=list(authors) or None,
            topics=list(topics) or None,
            summary=summary,
        )
    except BookstoreError as exc:
        raise click.ClickException(str(exc)) from exc
    _echo_card(card)


```
**Why**: mirrors `card_cmd` (lazy `BookstoreError` import, `ClickException` mapping, `_echo_card`); sync call, no `asyncio.run` (AC-8).

### `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` (MODIFY)
```python
# AFTER — append at end of file
@pytest.mark.asyncio
async def test_update_card_fields_and_manual_origin(store, book_md):
    card, _ = await store.add_book(book_md)
    store._catalog("project").set_card_community(card.book_id, "c1", "Community One")
    updated = store.update_card(card.book_id, title="  New Title ", authors=["A"], topics=["t1"], summary="S")
    assert (updated.title, updated.authors, updated.topics, updated.summary) == ("New Title", ["A"], ["t1"], "S")
    assert updated.card_origin == "manual"
    reread = store.get_card(card.book_id)
    assert reread.title == "New Title" and reread.community_id == "c1"


@pytest.mark.asyncio
async def test_update_card_requires_a_field(store, book_md):
    # FILL IN: no kwargs → BookstoreError; title="  " → BookstoreError; unknown id → BookstoreError — bounded by AC-7
    raise NotImplementedError
```

### `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` (MODIFY)
```python
# AFTER — append at end of file (last test: `def test_show_prints_classification(capsys):`, test_cli.py:297)
def test_update_command_edits_title(tmp_path, monkeypatch):
    # FILL IN: seed a CatalogStore(lib_dir / "library.db") with one BookCard (pattern test_cli.py:236-247),
    # monkeypatch.setenv(ENV_LIBRARY_DIR, str(lib_dir)); invoke ["update", book_id, "--title", "Renamed"];
    # exit_code == 0 and "Renamed" in output — bounded by AC-8
    raise NotImplementedError


def test_update_command_without_fields_fails(tmp_path, monkeypatch):
    # FILL IN: same setup; invoke ["update", book_id]; exit_code != 0 and "Nothing to do" in output — bounded by AC-8
    raise NotImplementedError
```
**Why**: one happy path and the error contract per layer; the CLI tests follow the existing `ENV_LIBRARY_DIR` + seeded-catalog pattern so no PageIndex tree is needed.

### FILL IN checklist
- [ ] `library.py::Bookstore.update_card` — field application + validation; bounded by AC-7
- [ ] `test_library.py::test_update_card_requires_a_field` — bounded by AC-7
- [ ] `test_cli.py::test_update_command_edits_title` — bounded by AC-8
- [ ] `test_cli.py::test_update_command_without_fields_fails` — bounded by AC-8

---

## Acceptance Criteria

- [ ] AC-7 — `update_card` applies only given fields, sets `manual`, keeps community stamps, persists, raises on unknown id / empty title / no field.
- [ ] AC-8 — `bookstore update` exists with the four options, prints the card, non-zero exit with "Nothing to do" when no field is given.
- [ ] `ruff check` clean on the four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_cli.py -q`

---

## Test Specification

See the blueprint; run with `PYTHONPATH=packages/ai-parrot/src`.

---

## Agent Instructions

1. Work in `.claude/worktrees/hotfix-bookstore-reindex-identity` (branch `hotfix/bookstore-reindex-identity`); task 2 must be `done` in the index.
2. Re-grep every anchor — tasks 1-2 shifted `library.py` lines.
3. Mark `in-progress` in the index, commit the index only.
4. Implement from the blueprint; complete every `FILL IN`.
5. Validation Commands + `ruff check`; commit only the four files: `feat(bookstore): HOTFIX-bookstore-reindex-identity-3 — update_card + bookstore update`.
6. `scripts/sdd/close_task.sh HOTFIX-bookstore-reindex-identity-3 bookstore-reindex-identity verified`, Completion Note, commit SDD state.

---

## Completion Note

**Completed by**: sdd-worker (sequential self-implementation; parrot-sdd-coder not used for hotfix ids)
**Date**: 2026-09-30
**Implementation commit**: c3f716342bea184a000fd90c39413cc851b2a0f0
**Tests**: test_library 40 passed, test_cli 15 passed; ruff clean
**Notes**: Sync update_card + bookstore update per blueprint.

**Deviations from spec**: none
