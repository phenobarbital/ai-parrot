# HOTFIX-bookstore-reindex-identity-4: Preserve manual card edits on in-place re-index

**Feature**: bookstore-reindex-identity — Bookstore re-index identity, graph invalidation, title collision guard and card editing (hotfix)
**Spec**: `sdd/specs/bookstore-reindex-identity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: HOTFIX-bookstore-reindex-identity-3
**Assigned-to**: agent:sdd-fix
**Index**: `sdd/tasks/index/bookstore-reindex-identity.json`
**discovered_from**: `issue:9013034b010f` (ledger, major — filed by the adversarial review of tasks 1-3)

---

## Context

`/sdd-fix issue:9013034b010f`. After tasks 1 and 3 landed, an in-place
re-index (`add_book` status `updated`) rebuilds the `BookCard` entirely from
the fresh draft, so `title`/`authors`/`topics`/`summary` set through
`Bookstore.update_card()` (task 3, `card_origin="manual"`) — or through
explicit overrides at a previous `add` — are silently reverted the next time
the source file changes. The review rated this major because it defeats the
purpose of M4.

The group also holds `issue:759176f0cf1a` (minor: tree deleted / graph
invalidated before the new ingest succeeds). That one is **not** fixed here —
it needs a temp-tree + swap that `PageIndexToolkit` does not offer — and is
released back to the ledger.

---

## Scope

- In `add_book()`, when `status == "updated"` and `existing.card_origin == "manual"`, keep the existing `title` (unless an explicit `title` is passed), `authors` (unless `authors` is passed), `topics` (unless `topics` is passed) and `summary` (when non-empty), and keep `card_origin="manual"`.
- Non-manual cards (`llm` / `fallback`) keep the current behaviour: rebuilt from the fresh draft.
- Three tests.

**NOT in scope**: `issue:759176f0cf1a`, `refresh_card()` (an explicit LLM refresh is the operator's choice), genre/traditions/period/year/language.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `preserved` branch in `add_book` card build |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | 3 re-index/manual tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError   # verified: library.py:181 / 100
from .conftest import SAMPLE_MARKDOWN                                     # verified: test_library.py:13
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py (branch hotfix/bookstore-reindex-identity @ d9ccd63ed)
#   existing = catalog.find_by_sha(sha256) … existing = catalog.find_by_path(str(path))   # lines 967-970
#   status = "added" / "updated"                                                            # lines 971-975
#   if not title: … final_title = disambiguate_title(...) else: final_title = title         # lines 1053-1057
#   card_origin = "fallback" if not self.has_llm else "llm"; if title or authors or topics: card_origin = "manual"   # 1058-1060
#   card = BookCard(book_id=slug, title=final_title, authors=authors if authors is not None else draft.authors, …,
#                   topics=topics if topics is not None else draft.topics, summary=draft.summary, …, card_origin=card_origin, …)   # 1066-1088
class BookCard: card_origin: Literal["llm", "fallback", "manual"]; title; authors; topics; summary   # models.py:152-181
def update_card(self, book_id, *, title=None, authors=None, topics=None, summary=None) -> BookCard   # library.py:1349 (task 3)
```

### Does NOT Exist
- ~~`BookCard.manual_fields`~~ / any per-field provenance — only the single `card_origin` literal exists.
- ~~`add_book(..., keep_manual=…)`~~ — no new flag; preservation is implicit for manual cards.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/bookstore/test_library.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.update_card",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookCard"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. After the `card_origin` block in `add_book`, compute `preserved` — *why*: the decision needs `status`, `existing` and the explicit overrides, all known at that point.
2. Use `preserved` in the `BookCard(...)` constructor for `authors`/`topics`/`summary` — *why*: explicit call arguments must still win.
3. Tests, Validation Commands, `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            card_origin = "manual"' library.py)
# AFTER — insert below `            card_origin = "manual"` (library.py:1060):
        preserved = existing if existing is not None and status == "updated" and existing.card_origin == "manual" else None
        if preserved is not None:
            if not title:
                final_title = preserved.title
            card_origin = "manual"
# then in BookCard(...): 
#   authors=authors if authors is not None else (preserved.authors if preserved else draft.authors),
#   topics=topics if topics is not None else (preserved.topics if preserved else draft.topics),
#   summary=preserved.summary if preserved and preserved.summary else draft.summary,
```
**Why**: the only provenance signal is `card_origin`; a manual card is treated as operator-owned for the four editable fields, while structural fields (toc, sha, page/chapter counts, classification) always come from the fresh index.

### `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` (MODIFY)
Three tests inserted before `test_update_card_requires_a_field`:
`test_reindex_preserves_manual_card_edits`, `test_reindex_explicit_overrides_beat_preserved_manual_fields`,
`test_reindex_of_llm_card_takes_fresh_draft`.

### FILL IN checklist
- [x] none — the fix is fully specified.

---

## Acceptance Criteria

- [ ] A card edited with `update_card` keeps title/authors/topics/summary and `card_origin="manual"` after its file changes and is re-added.
- [ ] Explicit `title=`/`authors=` on the re-index call override the preserved values; untouched fields stay preserved.
- [ ] `llm`/`fallback` cards are still rebuilt from the fresh draft.
- [ ] Whole bookstore suite green; `ruff check` adds no new findings.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_cli.py -q`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
