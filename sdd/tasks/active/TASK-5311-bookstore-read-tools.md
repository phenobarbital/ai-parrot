# TASK-5311: Bookstore read_pages, read_segments and outline per book

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5309
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 10**. Bookstore inherits the read tools: an agent can read a page
range or paragraphs of a book and cite them, instead of a whole section. The hand-built Bookstore
stdio server lists toolkit methods automatically, so it gains the tools with no server change.

---

## Scope

- `Bookstore`: `_document_of`, `read_pages`, `read_segments`, `outline` (async, delegating).
- `BookstoreToolkit`: `read_pages`, `read_segments`, `outline` (tools `bookstore_read_pages`,
  `bookstore_read_segments`, `bookstore_outline`).
- Update `EXPECTED_TOOLS` in `tests/knowledge/bookstore/test_toolkit.py` (it asserts the exact set).
- Write `tests/knowledge/bookstore/test_segment_reads.py`.

**NOT in scope**: `read_section` and `get_toc` (unchanged); the Bookstore skill text; reindexing old books.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Delegating methods |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py` | MODIFY | Three tools |
| `packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py` | MODIFY | `EXPECTED_TOOLS` gains three names |
| `packages/ai-parrot/tests/knowledge/bookstore/test_segment_reads.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Any, Optional          # bookstore/toolkit.py:22 (already)
# library.py already defines BookstoreError (:111) and imports PageIndexToolkit (:29-30)
```

### Existing Signatures to Use
```python
# knowledge/bookstore/library.py
class BookstoreError(...)                                              # :111
class Bookstore:
    def _toolkit(self, scope: str) -> PageIndexToolkit                 # :233
    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]   # :337 (card.tree_name, loc.scope)
    def read_section(self, book_id: str, node_id: str) -> dict[str, Any]       # :380-399 — insert the new methods after it
    async def add_book(...)                                            # :992 — markdown books go through toolkit.insert_markdown

# knowledge/bookstore/toolkit.py
class BookstoreToolkit(AbstractToolkit):                               # :29
    async def read_section(self, book_id: str, node_id: str) -> dict[str, Any]:  # :112-122 — docstring style to copy
        return self._bookstore.read_section(book_id, node_id)

# tests/knowledge/bookstore/test_toolkit.py
EXPECTED_TOOLS = { ... "bookstore_search", }                           # :13-24
    assert set(toolkit.list_tool_names()) == EXPECTED_TOOLS            # :49

# tests/knowledge/bookstore/test_library.py — fixtures to mirror: locations, store (Bookstore(locations, adapter=fake_adapter)),
#   book_md (a markdown book), `card, status = await store.add_book(book_md)` (:36-60)
```

### Does NOT Exist
- ~~`Bookstore.read_pages` / `read_segments` / `outline`~~, ~~`bookstore_read_pages` …~~ — created here
- ~~an exact tool-name assertion in `test_mcp_server.py`~~ — only `test_toolkit.py:49` asserts the set

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_segment_reads.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py#BookstoreToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `_document_of(card, toolkit)` = first row of `await toolkit.list_documents(card.tree_name)`; none →
  `BookstoreError("book has no segments — reindex it or run pageindex_index_segments")`.
- Each method: `card, loc = self.resolve_book(book_id)`, `toolkit = self._toolkit(loc.scope)`, then delegate.
  Add `book_id` and `book_title` to the returned dict (like `read_section`).
- Tool docstrings: say results are quoted book text, how to cite (`address.label`), and how to continue (`cursor`).
- Markdown books are unpaged: `read_pages` surfaces the toolkit's `ValueError` as `BookstoreError` with the same message.

---

## Implementation Blueprint

### Steps (in order)
1. Library methods, then toolkit tools.
2. Update `EXPECTED_TOOLS`.
3. Tests.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)
```python
# AFTER — insert below the body of `    def read_section(self, book_id: str, node_id: str) -> dict[str, Any]:`
#   (verified: library.py:380, occurrences: 1; the method ends at :399)
    async def _document_of(self, card: Any, toolkit: PageIndexToolkit) -> dict[str, Any]:
        """The single imported document of a book's tree."""
        # FILL IN — bounded by Key Constraints
        raise NotImplementedError

    async def read_pages(self, book_id: str, pages: str, max_chars: int = 12000,
                         cursor: Optional[str] = None) -> dict[str, Any]:
        """Read a page range of a book (``"5-7,12"``) with citable segment addresses."""
        # FILL IN — bounded by AC-1, AC-3
        raise NotImplementedError

    async def read_segments(self, book_id: str, start: Optional[int] = None, end: Optional[int] = None,
                            node_id: Optional[str] = None, max_chars: int = 12000,
                            cursor: Optional[str] = None) -> dict[str, Any]:
        """Read paragraphs of a book by position or a section's own text (``node_id``)."""
        # FILL IN — bounded by AC-1
        raise NotImplementedError

    async def outline(self, book_id: str, node_id: Optional[str] = None, max_depth: int = 3) -> dict[str, Any]:
        """Compact outline of a book or one of its sections."""
        # FILL IN — bounded by AC-1
        raise NotImplementedError
# FILL IN: confirm `Optional` is imported in library.py (add to its typing import if not)
```

### `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py` (MODIFY)
```python
# AFTER — insert below the body of `    async def read_section(self, book_id: str, node_id: str) -> dict[str, Any]:`
#   (verified: bookstore/toolkit.py:112, occurrences: 1; the method ends at :122)
    async def read_pages(self, book_id: str, pages: str, max_chars: int = 12000,
                         cursor: Optional[str] = None) -> dict[str, Any]:
        """Read pages of a book, e.g. ``pages="5-7,12"``.

        Returns quoted book text split into segments; cite a segment by its ``address.label``
        (e.g. *p. 12 ¶3*). When ``truncated`` is true, call again with ``cursor=next_cursor``.

        Args:
            book_id: The book.
            pages: Page ranges, comma separated.
            max_chars: Character budget for this call.
            cursor: ``next_cursor`` from a previous call.
        """
        return await self._bookstore.read_pages(book_id, pages, max_chars=max_chars, cursor=cursor)

    # FILL IN: read_segments(book_id, start=None, end=None, node_id=None, max_chars=12000, cursor=None) and
    #   outline(book_id, node_id=None, max_depth=3) with the same docstring style — bounded by AC-2
```

### `packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py` (MODIFY)
```python
# AFTER — `    "bookstore_search",` inside EXPECTED_TOOLS (verified: test_toolkit.py:23, occurrences: 1)
    "bookstore_read_pages",
    "bookstore_read_segments",
    "bookstore_outline",
```

### FILL IN checklist
- [ ] `_document_of` + three library methods; bounded by AC-1, AC-3
- [ ] two remaining tools; bounded by AC-2

---

## Acceptance Criteria

- [ ] AC-1: after `add_book(book_md)`, `read_segments(book_id, node_id=…)` and `outline(book_id)` return results carrying `book_id`, `book_title` and segment addresses.
- [ ] AC-2: `BookstoreToolkit.list_tool_names()` equals the updated `EXPECTED_TOOLS`.
- [ ] AC-3: a book whose tree has no segmented document raises `BookstoreError` naming `pageindex_index_segments`; `read_pages` on a markdown book raises `BookstoreError` naming `read_segments`.
- [ ] `read_section` tests in `test_library.py` pass unchanged; `ruff check` on both source files passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_segment_reads.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/bookstore/test_segment_reads.py
# Mirror the `locations` / `store` / `book_md` fixtures of tests/knowledge/bookstore/test_library.py:20-47
# (the conftest provides fake_adapter and the tiktoken stub).
import pytest

from parrot.knowledge.bookstore.library import BookstoreError


@pytest.mark.asyncio
async def test_bookstore_read_segments_and_outline(store, book_md):
    card, _ = await store.add_book(book_md)
    # FILL IN — AC-1
    ...


@pytest.mark.asyncio
async def test_bookstore_read_pages_unpaged_book(store, book_md):
    # FILL IN — AC-3 (markdown book → BookstoreError naming read_segments)
    ...


@pytest.mark.asyncio
async def test_bookstore_book_without_segments(store, book_md, monkeypatch):
    # FILL IN — AC-3 (monkeypatch the toolkit's list_documents to return [])
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-segment-store --feature-id FEAT-840`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design,
   §7 holds the splitter rules and the known risks).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-segment-store.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   within the constraint it names; touch only the files in *Files to Create / Modify*.
7. **Validate** — `ruff check --fix` on your files, then every command under *Validation Commands*.
8. **Commit code** (`feat(pageindex-segment-store): TASK-5311 — Bookstore read_pages, read_segments and outline per book`), then close with
   `parrot sdd task close TASK-5311 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
