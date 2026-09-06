# TASK-2915: Bookstore — deterministic relations engine, `related_books`, remove cascade

**Feature**: FEAT-533 — Bookstore Conceptual Relations
**Spec**: `sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2913
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 3 (Stage 1) and step 4 (read path), §3 Module 2
(first half), goals G2/G7. Stage 1 needs no LLM and gives every library
a usable graph immediately: `same_author`, `shares_topic`,
`same_tradition`, `same_genre`, `same_era`, `same_language`. This task
also lands the read path the tools and CLI will use, and the cascade so
removing a book never leaves dangling edges in its own scope.

---

## Scope

- Create `bookstore/relations.py` with:
  - `_author_key(name) -> str | None` (slugify; `None` when the slug is
    the `"book"` fallback or shorter than 3 chars — spec §7 gotcha).
  - `deterministic_relations(cards: list[BookCard], *, now: str,
    topic_jaccard_min: float = 0.2, era_window_years: int = 50) ->
    list[BookRelation]` implementing the six rels with weights from
    `REL_WEIGHTS` (`shares_topic` weight = Jaccard). O(n²) over the
    merged card list; symmetric canonical order `src < dst`.
- `Bookstore`:
  - `_visible_ids() -> set[str]` (ids of `list_books()`).
  - `_relations_store_for(book_id) -> CatalogStore` — the scope DB that
    owns the `src` book (cross-scope rule).
  - `_write_deterministic(relations)` — group by src scope; per scope:
    `delete_relations(book_id=<each target book>, origin="deterministic")`
    then `upsert_relations`.
  - `related_books(book_id, rel=None, depth=1, top_k=10, min_confidence=0.0)
    -> list[dict]`: `merged_relations(self._stores(), visible)`, filter
    by rel/confidence, walk `depth` hops (max 2), return dicts
    `{book: brief, rel, origin, weight, confidence, rationale, hop,
    via?}` ordered by hop then weight desc, capped at `top_k`.
  - `remove_book`: before `catalog.remove`, call
    `delete_relations(book_id=…)` and `delete_judgements(book_id)` on
    **every** store (edges to this book may live in the other scope's
    DB when the other scope owns the src).
- CLI: `bookstore related BOOK_ID [--rel REL] [--depth N] [--json]`
  (table: rel | book | title | origin | weight | confidence).
- Tests per the Test Specification.

**NOT in scope**: `relate_books` orchestration and `bookstore relate`
(TASK-2916); LLM anything; communities.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py` | CREATE | Stage 1 pure functions |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | helpers, `related_books`, `remove_book` cascade |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `related` command |
| `packages/ai-parrot/tests/knowledge/bookstore/test_relations.py` | CREATE | Stage 1 + read path tests |
| `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` | MODIFY | `related` output |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.models import BookCard, BookRelation, RelationKind, SYMMETRIC_RELS, REL_WEIGHTS   # TASK-2913
from parrot.knowledge.bookstore.catalog import CatalogStore, merged_cards, merged_relations   # catalog.py:85, 329; merged_relations from TASK-2913
from parrot.knowledge.bookstore.carding import slugify                     # carding.py:44
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError   # library.py:88, 55
```

### Existing Signatures to Use
```python
# bookstore/library.py
class Bookstore:                                                          # line 88
    locations: list[LibraryLocation]   # project first
    def _catalog(self, scope: str) -> CatalogStore                        # line 138
    def _stores(self) -> list[tuple[str, CatalogStore]]                   # line 161 — [(scope, store)] project first
    def list_books(self) -> list[BookCard]                                # line 184 — merged_cards(self._stores())
    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]   # line 192 — raises BookstoreError when unknown
    async def remove_book(self, book_id: str) -> bool                     # line 663 — delete_tree (warn if missing) → self._catalog(loc.scope).remove(book_id)

# bookstore/catalog.py (after TASK-2913)
CatalogStore.upsert_relations(list[BookRelation]); delete_relations(book_id=None, origin=None); list_relations(book_id, rel=None); delete_judgements(book_id)
def merged_relations(stores, visible_ids: set[str]) -> list[BookRelation]

# bookstore/models.py (after TASK-2913)
class BookRelation(BaseModel): src_book_id, dst_book_id, rel, weight=1.0, origin, confidence=None, rationale="", computed_at
SYMMETRIC_RELS: frozenset[str]; REL_WEIGHTS: dict[str, float]
BookCard fields used here: authors, topics, traditions, genre, year, period, language, scope

# bookstore/cli.py
def _open_bookstore(llm_spec=None, require_exists=False, scope_needed=None, use_llm=True) -> Bookstore   # line 31
@bookstore.command("show") def show(book_id, as_json)   # line 257 — pattern for a read command (require_exists=True, use_llm=False)
```

### Does NOT Exist
- ~~`parrot.knowledge.bookstore.relations`~~ — created here.
- ~~`Bookstore.related_books/_visible_ids/_relations_store_for/_write_deterministic`~~ — created here.
- ~~`Bookstore.relate_books`~~ — TASK-2916, not this task.
- ~~Any author-alias table or fuzzy author matching~~ — deterministic only (slug equality); aliases are the LLM layer's job.
- ~~`BookCard.era`~~ — no such field; era comes from `year` window or equal `period` slug.

---

## Implementation Notes

### Pattern to Follow
```python
# relations.py — pure, testable, no I/O
def deterministic_relations(cards, *, now, topic_jaccard_min=0.2, era_window_years=50):
    out: list[BookRelation] = []
    for a, b in itertools.combinations(sorted(cards, key=lambda c: c.book_id), 2):
        if _author_keys(a) & _author_keys(b): out.append(_rel(a, b, "same_author", REL_WEIGHTS["same_author"], now))
        j = _jaccard(_slugs(a.topics), _slugs(b.topics))
        if j >= topic_jaccard_min: out.append(_rel(a, b, "shares_topic", j, now, rationale=f"jaccard={j:.2f}"))
        ...
    return out
```

### Key Constraints
- `rationale` for deterministic edges is a short machine string (`"author=calderon-de-la-barca"`, `"jaccard=0.33"`, `"tradition=estoicismo"`) — useful to the agent, cheap to store.
- `same_era`: `year` window OR equal non-empty `period` slug; skip when both are missing.
- `same_language`: only when both `language` set and equal.
- Depth-2 walk must not revisit the origin book and must dedupe books reached via several paths (keep the strongest edge).
- `related_books` must be synchronous and SQL-only (no adapter, no graph library) — it backs the MCP tool.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:329` — `merged_cards` (project-wins pattern to mirror)
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:184-220` — read surface style

---

## Acceptance Criteria

- [ ] "Calderón de la Barca" vs "Calderon de la Barca" → `same_author`; a single-token author collapsing to `"book"` produces no edge
- [ ] `shares_topic` weight equals Jaccard; below 0.2 → no edge
- [ ] `same_era` from year window and from equal period; `same_language` only when both set
- [ ] `related_books` depth 2 returns hop numbers, dedupes, honours `rel`/`min_confidence`/`top_k`
- [ ] Cross-scope: an edge whose src is global lands in the global DB; unknown dst filtered on read
- [ ] `remove_book` removes edges in both directions across both scope DBs and the book's judgements
- [ ] `bookstore related <id>` prints a table and `--json` a list
- [ ] `pytest packages/ai-parrot/tests/knowledge/bookstore/ -q` green; `ruff check` clean

---

## Test Specification

```python
# tests/knowledge/bookstore/test_relations.py
def _card(book_id, **kw) -> BookCard: ...   # helper with sane defaults (tree_name=book_id, source_path=..., source_sha256=..., source_format="md", added_at=...)

def test_deterministic_same_author_slugified(): ...
def test_deterministic_author_fallback_slug_ignored(): ...
def test_deterministic_shares_topic_jaccard(): ...
def test_deterministic_same_tradition_and_genre(): ...
def test_deterministic_same_era_window_and_period(): ...
def test_deterministic_same_language_requires_both(): ...
def test_deterministic_canonical_symmetric_order(): ...

async def test_related_books_depth2_and_filters(store, ...): ...
async def test_cross_scope_edge_stored_in_src_scope_and_dangling_filtered(store, ...): ...
async def test_remove_book_cascades_relations_and_judgements(store, ...): ...

# test_cli.py
def test_related_cli_table_and_json(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2913 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/wikitoolkit-bookstore-conceptual-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2915-bookstore-deterministic-relations.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
