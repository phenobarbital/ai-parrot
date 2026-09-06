# TASK-2913: Bookstore — relation/community models and catalog schema

**Feature**: FEAT-533 — Bookstore Conceptual Relations
**Spec**: `sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models + §3 Module 1 (schema half). Everything downstream
(deterministic relations, LLM judgements, communities, tools, export)
persists through the catalog, so the models, the additive SQLite
migrations, the FTS rebuild and the CRUD/merged readers land first, with
no behaviour change for existing libraries.

---

## Scope

- `models.py`: add `Genre`, `RelationKind`, `SYMMETRIC_RELS`, `REL_WEIGHTS`
  (values from spec §2 Overview step 3); add `genre`/`traditions`/`period`
  to `CardDraft` (with `Field(description=…)` so the structured-output
  schema documents them) and to `BookCard` plus `community_id`,
  `community_label`; extend `brief()` with the five new keys; add
  `BookRelation`, `RelationJudgement`, `RelationDraft`,
  `CommunityLabelDraft`, `BookCommunity`, `RelateSummary` exactly as in
  spec §2 Data Models (Google docstrings, strict types).
- `catalog.py`:
  - `_ADDED_COLUMNS` entries for `genre`, `traditions`, `period`,
    `community_id`, `community_label`; add `"traditions"` to
    `_JSON_COLUMNS`.
  - New DDL constants `_RELATIONS_DDL`, `_JUDGEMENTS_DDL`,
    `_COMMUNITIES_DDL` (+ index) from spec §2, executed in
    `_ensure_schema`.
  - FTS: extend `_FTS_DDL` with `genre` and `traditions_text`; add a
    `_FTS_COLUMNS` tuple; in `_ensure_schema`, if `books_fts` exists
    with a different column set (`PRAGMA table_info(books_fts)`),
    remove the old virtual table, recreate it from `_FTS_DDL` and
    re-populate it from `books`, all inside one transaction. `upsert`
    writes the two new FTS values.
  - Normalise `traditions` with `slugify` on `upsert` (import from
    `.carding`; keep order, dedupe).
  - CRUD: `upsert_relations(list[BookRelation])` (canonicalise symmetric
    pairs `src < dst`; `INSERT OR REPLACE`), `delete_relations(book_id=None,
    origin=None)` (either/both filters; `book_id` matches src OR dst),
    `list_relations(book_id, rel=None) -> list[BookRelation]` (both
    directions), `record_judgements(src, list[RelationJudgement], model)`,
    `judged_pairs(src) -> set[str]`, `delete_judgements(book_id)`,
    `upsert_communities(list[BookCommunity])` (replace all),
    `list_communities()`, `get_community(id)`, `set_card_community(book_id,
    community_id, label)`.
- Module-level `merged_relations(stores, visible_ids: set[str]) ->
  list[BookRelation]` (union, drop edges with an endpoint not in
  `visible_ids`, earlier scope wins duplicates) and
  `merged_communities(stores)` (first store that has rows wins).
- Tests per the Test Specification, including a **legacy-DB fixture**
  built from the pre-feature DDL literals.

**NOT in scope**: prompt changes, `refresh_card`, CLI output (TASK-2914);
computing any relation (TASK-2915+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/models.py` | MODIFY | enums, new fields, new models |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | MODIFY | migrations, DDL, FTS rebuild, CRUD, merged readers |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/__init__.py` | MODIFY | export the new model names in `__all__` (models only; keep lazy `__getattr__` for heavy classes) |
| `packages/ai-parrot/tests/knowledge/bookstore/test_models.py` | MODIFY | new model tests |
| `packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py` | MODIFY | migration/FTS/CRUD tests |
| `packages/ai-parrot/tests/knowledge/bookstore/conftest.py` | MODIFY | `legacy_library_db` fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.models import BookCard, CardDraft, TocEntry        # models.py:64, 34, 15
from parrot.knowledge.bookstore.catalog import CatalogStore, merged_cards, merged_search   # catalog.py:85, 329, 355
from parrot.knowledge.bookstore.carding import slugify                               # carding.py:44
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# bookstore/models.py
class CardDraft(BaseModel):   # line 34 — title, authors=[], year=None, language=None, topics=[], summary=""  (all with Field(description=...))
class BookCard(BaseModel):    # line 64 — book_id, title, authors, year, language, topics, summary, toc_digest, toc, tree_name,
                              #   scope: Literal["project","global"]="project", source_path, source_sha256, source_format, page_count, chapter_count=0, added_at, card_origin
    def brief(self) -> dict   # line 93 — book_id, title, authors, year, language, topics, summary(first line), chapter_count, page_count, scope

# bookstore/catalog.py
_BOOKS_DDL       # line 40 — books(book_id PK, title, authors '[]', year, language, topics '[]', summary '', toc_digest '', toc '[]', tree_name UNIQUE, source_path, source_sha256, source_format, page_count, chapter_count 0, added_at, card_origin 'llm')
_FTS_DDL         # line 62 — books_fts(book_id UNINDEXED, title, authors_text, topics_text, summary, toc_digest, tokenize='unicode61 remove_diacritics 2')
_ADDED_COLUMNS: list[tuple[str, str]] = []   # line 77 — ("col", "col TYPE DEFAULT ...") applied by _ensure_schema (lines 124-129: PRAGMA table_info(books) → ALTER TABLE books ADD COLUMN {clause})
_JSON_COLUMNS = ("authors", "topics", "toc")   # line 82
class CatalogStore:                            # line 85
    def __init__(self, db_path: Path | str) -> None                 # line 93 — mkdir, _ensure_schema
    def _connection(self) -> Iterator[sqlite3.Connection]           # line 106 — contextmanager, Row factory, close()
    def _ensure_schema(self, conn: sqlite3.Connection) -> None      # line 118 — WAL, DDL, migrations, FTS probe → self._fts_available
    def supports_fts(self) -> bool                                  # line ~142
    @staticmethod def _row_to_card(row: sqlite3.Row) -> BookCard    # line ~160 — json.loads for _JSON_COLUMNS; pops scope
    def upsert(self, card: BookCard) -> None                        # line 174 — payload = model_dump; pops scope; json.dumps JSON cols; INSERT OR REPLACE; DELETE+INSERT books_fts (6 values)
    def remove(self, book_id: str) -> bool                          # line ~212
    def get(self, book_id) -> Optional[BookCard]; find_by_sha(sha) ; list_cards() ; taken_slugs() ; search(query, top_k=8) -> list[tuple[BookCard, float]]
def merged_cards(stores: list[tuple[str, CatalogStore]]) -> list[BookCard]   # line 329 — earlier scope wins; sets card.scope
def merged_search(stores, query, top_k) -> list[BookCard]                    # line 355

# bookstore/carding.py
def slugify(text: str) -> str   # line 44 — NFKD → ascii → lower → [a-z0-9-]+, ≤64, never empty ("book")

# tests/knowledge/bookstore/conftest.py
SAMPLE_MARKDOWN; def make_adapter() -> MagicMock (line 31); fixture fake_adapter (63); autouse _stub_tiktoken (68); fixture sample_tree (83)
```

### Does NOT Exist
- ~~`BookCard.genre/traditions/period/community_id/community_label`~~, ~~`CardDraft.genre/traditions/period`~~ — this task adds them.
- ~~`BookRelation`, `RelationJudgement`, `RelationDraft`, `CommunityLabelDraft`, `BookCommunity`, `RelateSummary`, `Genre`, `RelationKind`, `SYMMETRIC_RELS`, `REL_WEIGHTS`~~ — this task adds them.
- ~~`book_relations` / `relation_judgements` / `communities` tables~~ — this task adds them.
- ~~`CatalogStore.upsert_relations/list_relations/delete_relations/record_judgements/judged_pairs/delete_judgements/upsert_communities/list_communities/get_community/set_card_community`~~, ~~`merged_relations`, `merged_communities`~~ — this task adds them.
- ~~`ALTER TABLE` on the FTS5 virtual table~~ — not supported by SQLite; the rebuild path (remove + recreate + repopulate) is the only way.
- ~~aiosqlite in the catalog~~ — the catalog is synchronous `sqlite3` by design (module docstring); keep it so.

---

## Implementation Notes

### Pattern to Follow
```python
# catalog.py — additive migration entries (append, never edit existing)
_ADDED_COLUMNS: list[tuple[str, str]] = [
    ("genre", "genre TEXT NOT NULL DEFAULT 'other'"),
    ("traditions", "traditions TEXT NOT NULL DEFAULT '[]'"),
    ("period", "period TEXT"),
    ("community_id", "community_id TEXT"),
    ("community_label", "community_label TEXT"),
]
```
```python
# FTS drift check inside _ensure_schema (after the books migrations)
existing_fts = tuple(r["name"] for r in conn.execute("PRAGMA table_info(books_fts)"))
if existing_fts and existing_fts != _FTS_COLUMNS:
    # remove the stale virtual table, recreate from _FTS_DDL, repopulate from `books`
    ...
```

### Key Constraints
- Symmetric canonical order: for `rel in SYMMETRIC_RELS`, store `(min(src,dst), max(src,dst))`; readers return the pair as stored.
- `CHECK (src_book_id <> dst_book_id)` in DDL; `BookRelation` rejects self-pairs in a model validator so the DB constraint is a backstop, not the primary check.
- `merged_relations` must never raise on an unknown endpoint — filter silently (cross-scope dangling rule, spec §7).
- The `communities` table lives once per merged graph; `CatalogStore` stays scope-agnostic — `Bookstore` (TASK-2917) decides which DB receives it.
- Keep `card.scope` out of the DB (existing rule).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` — the whole file is the pattern
- `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py` — same additive-migration discipline (reference only)

---

## Acceptance Criteria

- [ ] A DB created from the pre-feature DDL literals opens, gains the five columns, keeps its rows, and its `books_fts` is rebuilt to 8 columns once (second open: no rebuild)
- [ ] `search("estoicismo")` hits a card whose only mention is in `traditions`
- [ ] `upsert` slug-normalises traditions; `brief()` returns the five new keys
- [ ] Relation CRUD round-trips; symmetric pairs canonicalised; `src == dst` rejected; judgement log and `judged_pairs` work; communities replace-all
- [ ] `merged_relations` drops dangling endpoints and honours project-wins
- [ ] `pytest packages/ai-parrot/tests/knowledge/bookstore/ -q` green (existing 60+ untouched)
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/bookstore/`

---

## Test Specification

```python
# tests/knowledge/bookstore/test_catalog.py (append)
def test_added_columns_migrate_old_db(legacy_library_db): ...
def test_fts_rebuilt_on_column_drift(legacy_library_db): ...
def test_fts_not_rebuilt_when_current(tmp_path): ...            # sqlite_master rowid of books_fts stable across two opens
def test_traditions_slug_normalised_on_upsert(tmp_path): ...
def test_search_hits_traditions_and_genre(tmp_path): ...
def test_relation_pk_replaces_and_self_pair_rejected(tmp_path): ...
def test_symmetric_rel_canonical_order(tmp_path): ...
def test_directed_rel_keeps_direction(tmp_path): ...
def test_list_relations_both_directions_and_rel_filter(tmp_path): ...
def test_delete_relations_by_book_and_origin(tmp_path): ...
def test_judgements_record_and_judged_pairs(tmp_path): ...
def test_communities_replace_all_and_get(tmp_path): ...
def test_merged_relations_filters_dangling_and_project_wins(tmp_path): ...

# tests/knowledge/bookstore/test_models.py (append)
def test_card_draft_classification_defaults(): ...
def test_brief_includes_classification_and_community(): ...
def test_book_relation_rejects_self_pair(): ...
def test_relation_judgement_confidence_bounds(): ...
def test_rel_weights_cover_every_relation_kind(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm line numbers in `catalog.py`/`models.py` before editing
4. **Update status** in `sdd/tasks/index/wikitoolkit-bookstore-conceptual-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2913-bookstore-relation-models-and-catalog-schema.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
