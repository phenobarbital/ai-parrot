# HOTFIX-bookstore-reindex-identity-2: Deterministic title collision guard at carding

**Feature**: bookstore-reindex-identity — Bookstore re-index identity, graph invalidation, title collision guard and card editing (hotfix)
**Spec**: `sdd/specs/bookstore-reindex-identity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: HOTFIX-bookstore-reindex-identity-1
**Assigned-to**: unassigned
**Index**: `sdd/tasks/index/bookstore-reindex-identity.json`

---

## Context

Spec §1 problem 3, module **M3**, acceptance criterion AC-6. The carding
prompt asks the LLM for "the real book title", so the 20 chapter files of one
work were all carded *Odoo 19 Development Cookbook*. Nothing in `add_book()`
notices that a freshly drafted title already exists in the library. This task
adds a pure, LLM-free disambiguation step applied only to *drafted* titles.

Depends on task 1 because both edit `add_book()` in `library.py` and append
tests to `test_library.py` (shared-file serialization, spec Worktree
Strategy) — no symbol dependency.

---

## Scope

- Add `carding.disambiguate_title()` right after `unique_slug()`, plus a tiny
  private `_stem_to_title(stem)` helper reused by `fallback_card_fields()`
  (no behaviour change there).
- In `add_book()`, after `_draft_card()`, when the caller gave no explicit
  `title`, compute the taken set from `self.list_books()` (both scopes,
  excluding the book being (re)indexed) and pass `draft.title` through
  `disambiguate_title()`; use the result as the card title.
- Tests: 4 pure-function cases + LLM-duplicate ingest + explicit-title bypass.

**NOT in scope**: `_CARD_PROMPT` changes, `refresh_card()` (explicitly not
guarded, spec M3), `update_card`/CLI (task 3), any change to `unique_slug`,
`card_origin` values.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py` | MODIFY | `_stem_to_title`, `disambiguate_title` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | wire the guard into `add_book` |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | guard tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.carding import disambiguate_title, fallback_card_fields, unique_slug  # unique_slug verified: carding.py:73; fallback_card_fields: carding.py:140; disambiguate_title created by THIS task
from parrot.knowledge.bookstore.models import CardDraft, TocEntry            # verified: models.py:117, 98
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError     # verified: library.py:181 / 100
from .conftest import SAMPLE_MARKDOWN                                       # verified: test_library.py:13 (tests only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py
from .models import CardDraft, Genre, TocEntry                                 # line 15 (already imported)
def slugify(text: str) -> str                                                  # line 49
def unique_slug(base: str, taken: set[str]) -> str                             # line 73-85  ← insert new functions after this
def derive_toc(tree, max_depth=2) -> tuple[list[TocEntry], str]                # line 88
def fallback_card_fields(file_path: Path, toc_entries: list[TocEntry]) -> CardDraft   # line 140
#   stem = file_path.stem.replace("_", " ").replace("-", " ").strip()          # line 151
#   title = " ".join(part.capitalize() for part in stem.split()) or file_path.name   # line 152

# packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
class TocEntry(BaseModel): node_id: str; title: str; depth: int = 1            # line 98-114

# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
from .carding import (derive_toc, fallback_card_fields, generate_card_fields, sample_sections, slugify, unique_slug)  # lines 30-37 ← add disambiguate_title here
class Bookstore:
    def list_books(self) -> list[BookCard]                                     # line 261 (merged both scopes)
    async def add_book(...)                                                    # line 922
#   toc_entries, toc_digest = derive_toc(tree)                                 # line 1034
#   draft = await self._draft_card(path=path, tree_name=slug, scope=scope, ...) # lines 1035-1042
#   card_origin = "fallback" if not self.has_llm else "llm"                    # line 1045 (may have shifted by task 1 — re-grep)
#   card = BookCard(book_id=slug, title=title or draft.title, ...)             # lines 1053-1055
# NOTE: after task 1 the line numbers above move by a few lines; re-run the grep -c for each anchor.

# tests: fixtures store (fake_adapter → fixed card title for EVERY structured call, conftest.py:77-106), store_no_llm, book_md, tmp_path
```

### Does NOT Exist
- ~~`carding.unique_title()` / `dedupe_title()`~~ — the function is `disambiguate_title`, created by THIS task.
- ~~`CatalogStore.taken_titles()`~~ — does not exist and must NOT be added; build the set from `Bookstore.list_books()`.
- ~~`CardDraft.disambiguated`~~ / any new model field — none.
- ~~`tests/knowledge/bookstore/test_carding.py`~~ — no such file; put the pure-function tests in `test_library.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/bookstore/test_library.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#unique_slug",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#fallback_card_fields",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#TocEntry",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.list_books"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `taken` holds **casefolded** titles; the function never returns a title whose casefold is in `taken`.
- Fallback order is fixed by the spec (§3 M3): (1) first ToC entry whose casefold differs from the title's and whose combination is free; (2) `"<title> — <Stem>"`; (3) `"<title> — <Stem> (N)"`, N ≥ 2.
- Explicit `title=` bypasses the guard entirely (AC-6); `card_origin` is untouched.
- Exclude the book being (re)indexed from the taken set (`c.book_id != slug`) so an in-place update keeps its own title.
- The em dash separator is the literal `" — "` (U+2014 with spaces), matching the spec examples.

### References in Codebase
- `carding.py:73-85` — `unique_slug`, the slug-level analogue.
- `carding.py:140-154` — `fallback_card_fields`, source of the stem transform.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_stem_to_title` and `disambiguate_title` to `carding.py` after `unique_slug`; make `fallback_card_fields` call `_stem_to_title` — *why*: one stem transform, no drift between the fallback title and the guard hint.
2. Import `disambiguate_title` in `library.py` and wire it in `add_book` — *why*: the guard must run on the drafted title only, after the tree/ToC exist.
3. Tests, Validation Commands, `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def unique_slug(base: str, taken: set\[str\]) -> str:' carding.py)
# AFTER — insert below the whole unique_slug function (ends carding.py:85 `    return f"{base}-{n}"`)


def _stem_to_title(stem: str) -> str:
    """De-slugify a filename stem into a display title (``odoo19-cookbook_ch03`` → ``Odoo19 Cookbook Ch03``)."""
    words = stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in words.split())


def disambiguate_title(title: str, taken: set[str], *, toc_entries: list[TocEntry], stem: str) -> str:
    """Return ``title`` unless its casefold is in ``taken``; otherwise a unique ``"<title> — <hint>"``.

    Hint order: (1) the first ``toc_entries`` title whose casefold differs from
    ``title``'s and whose combination is not taken; (2) the de-slugified
    ``stem``; (3) ``"<title> — <stem> (N)"`` for the first free ``N >= 2``.
    ``taken`` holds casefolded titles. Never returns a taken title.
    """
    if title.casefold() not in taken:
        return title
    # FILL IN: implement the three-step fallback exactly as documented — bounded by AC-6
    raise NotImplementedError

# then in fallback_card_fields (carding.py:151-152) replace the two stem/title lines with:
    title = _stem_to_title(file_path.stem) or file_path.name
```
**Why this shape**: pure and deterministic so it is unit-testable without a store; the stem helper keeps the no-LLM fallback title and the guard hint identical (spec §7 pattern note).

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    derive_toc,' library.py) — add `    disambiguate_title,` to the `from .carding import (` block (library.py:30-37), keeping alphabetical order

# occurrences: 1 (verified: grep -c 'card_origin = "fallback" if not self.has_llm else "llm"' library.py — re-check after task 1)
# BEFORE — insert above `        card_origin = "fallback" if not self.has_llm else "llm"`:
        if title is None:
            taken_titles = {c.title.casefold() for c in self.list_books() if c.book_id != slug}
            final_title = disambiguate_title(draft.title, taken_titles, toc_entries=toc_entries, stem=path.stem)
        else:
            final_title = title
# then in the BookCard(...) constructor a few lines below, REPLACE `title=title or draft.title,` with `title=final_title,`
```
**Why**: the guard sees the merged library (both scopes) minus the book itself, so re-indexing in place never collides with its own previous title; an explicit title is persisted verbatim (AC-6).

### `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` (MODIFY)
```python
# AFTER — append at end of file (last test: `def test_card_prompt_requests_classification():`)
from parrot.knowledge.bookstore.carding import disambiguate_title  # put with the other imports at the top of the file
from parrot.knowledge.bookstore.models import TocEntry


def test_disambiguate_title_not_taken_is_unchanged():
    assert disambiguate_title("Book", set(), toc_entries=[], stem="book") == "Book"


def test_disambiguate_title_uses_first_distinct_toc_entry():
    toc = [TocEntry(node_id="n1", title="Book"), TocEntry(node_id="n2", title="Chapter 3 — Modules")]
    assert disambiguate_title("Book", {"book"}, toc_entries=toc, stem="ch03") == "Book — Chapter 3 — Modules"


def test_disambiguate_title_falls_back_to_stem_then_counter():
    # FILL IN: no usable ToC → "Book — Odoo Ch03"; that taken too → "Book — Odoo Ch03 (2)"; case-insensitive — bounded by AC-6
    raise NotImplementedError


@pytest.mark.asyncio
async def test_add_book_llm_duplicate_title_is_disambiguated(store, tmp_path):
    # FILL IN: two different files (different bytes), both carded by fake_adapter to the same title;
    # second card's title != first's, first unchanged — bounded by AC-6
    raise NotImplementedError


@pytest.mark.asyncio
async def test_add_book_explicit_title_never_disambiguated(store, tmp_path):
    # FILL IN: two different files added with title="Same Title" → both titles == "Same Title",
    # ids "same-title" / "same-title-2" — bounded by AC-6 and AC-4
    raise NotImplementedError
```
**Why**: covers each fallback step and both ingest paths; `test_slug_collision_across_scopes_is_suffixed` (line 137) and `test_slug_collision_suffixing` (154) assert on ids only and must stay green.

### FILL IN checklist
- [ ] `carding.py::disambiguate_title` — three-step fallback body; bounded by AC-6
- [ ] `test_library.py::test_disambiguate_title_falls_back_to_stem_then_counter` — bounded by AC-6
- [ ] `test_library.py::test_add_book_llm_duplicate_title_is_disambiguated` — bounded by AC-6
- [ ] `test_library.py::test_add_book_explicit_title_never_disambiguated` — bounded by AC-6/AC-4

---

## Acceptance Criteria

- [ ] AC-6 — drafted duplicate titles are disambiguated per the fixed order; explicit titles are verbatim.
- [ ] `fallback_card_fields` output is byte-identical to before for every stem (`test_add_book_no_llm_fallback_card` green).
- [ ] AC-10 — `_CARD_PROMPT` untouched (`test_card_prompt_requests_classification` green).
- [ ] `ruff check` clean on the three files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_models.py -q`

---

## Test Specification

See the blueprint; run with `PYTHONPATH=packages/ai-parrot/src`.

---

## Agent Instructions

1. Work in `.claude/worktrees/hotfix-bookstore-reindex-identity` (branch `hotfix/bookstore-reindex-identity`); task 1 must be `done` in the index.
2. Re-grep every anchor — task 1 shifted `library.py` line numbers.
3. Mark `in-progress` in the index, commit the index only.
4. Implement from the blueprint; complete every `FILL IN`.
5. Validation Commands + `ruff check`; commit only the three files: `fix(bookstore): HOTFIX-bookstore-reindex-identity-2 — title collision guard`.
6. `scripts/sdd/close_task.sh HOTFIX-bookstore-reindex-identity-2 bookstore-reindex-identity verified`, Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
