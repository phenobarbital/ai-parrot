# TASK-2747: Store schema v2 — `content_hash`, `symbols` table, symbol methods on every backend

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2738
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5; resolved decisions: `content_hash` is a **new `pages`
column** (not a join on `sources.file_hash`); SQLite gets the native
`symbols` table + FTS; ArangoDB and InMemory/OKF persist `sym:` pages/edges
through existing methods and inherit **default** symbol methods built on
pages. This task touches no scanner and can run in parallel with
TASK-2739…2746 (no shared files).

---

## Scope

- `store.py`: `SCHEMA_VERSION = "2"`; `_MIGRATION_COLUMNS["pages"]` +=
  `("content_hash", "TEXT")`; `WIKI_SCHEMA_SQL` += `content_hash TEXT` in
  `pages`, the `symbols` table + indexes + `symbols_fts` (DDL in spec §2 Data
  Models); `_SCHEMA_TABLES` += `symbols`, `symbols_fts`. `upsert_pages`,
  `get_page`, `list_pages`, `dump_pages`, `replace_source_slice` read/write
  `content_hash`. FTS triggers/maintenance for `symbols_fts` mirror the
  `pages_fts` approach used today.
- `BaseWikiStore`: **concrete default** methods `upsert_symbols(symbols,
  source_id=None) -> int` (default 0 / no-op), `symbols_for(rel_path)`,
  `find_symbols(name=None, qualname_prefix=None, kind=None, language=None,
  path_prefix=None, limit=50)`, `search_symbols_fts(query, limit=20)`,
  `page_hashes(concept_ids) -> dict[str, str | None]` — defaults built on
  `list_pages(category="symbol")` / `search_fts(query, category="symbol")` /
  `get_page(cid, include_body=False)` and a `SymbolRecord`-from-page decoder
  (the `sym:` page body/summary carry enough — see TASK-2748 body format; put
  the decoder in `symbols.py` as `symbol_from_page(page: dict) -> SymbolRecord | None`).
- `SQLiteWikiStore`: native overrides for all five; `replace_source_slice()`
  also `DELETE FROM symbols WHERE source_id = ?` (+ FTS rows) in the same
  transaction; `stats()` adds `"symbols"`.
- `ArangoDBWikiStore` / `InMemoryWikiStore`: persist `content_hash`
  (document field / frontmatter key), `stats()["symbols"]` = count of
  `category == "symbol"` pages. No `wiki_symbols` collection (non-goal).
- `FederatedWikiStore` (`federation.py`): delegate the five methods to the
  local store (reads) — no fan-out in v1.
- Tests in `test_store.py` (parametrised `store` fixture: sqlite + memory),
  `test_arango_store.py` (unit, mocked), migration test with a committed v1
  fixture DB.

**NOT in scope**: producing `sym:` pages (TASK-2748), any tool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Schema v2, defaults on `BaseWikiStore`, SQLite overrides |
| `packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py` | MODIFY | `symbol_from_page()` decoder (+ `symbol_to_page_fields()` helper used by TASK-2748) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` | MODIFY | `content_hash` field; `stats()["symbols"]` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` | MODIFY | `content_hash` frontmatter; `stats()["symbols"]` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | Delegate five methods |
| `tests/knowledge/wiki/test_store.py` | MODIFY | Symbol methods + `page_hashes` on every backend |
| `tests/knowledge/wiki/test_arango_store.py` | MODIFY | `content_hash` round-trip (mocked) |
| `tests/knowledge/wiki/fixtures/wiki_v1.db` | CREATE | v1 plane for the migration test (generate with a script in the test, then commit the artefact) |
| `tests/knowledge/wiki/test_store_migration_v2.py` | CREATE | Migration test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, SQLiteWikiStore, SCHEMA_VERSION, WIKI_SCHEMA_SQL, _MIGRATION_COLUMNS, _SCHEMA_TABLES, create_wiki_store
from parrot.knowledge.wiki.symbols import SymbolRecord, SymbolKind, parse_sym_id     # TASK-2738
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore                      # arango_store.py:128
from parrot.knowledge.wiki.file_store import InMemoryWikiStore                        # file_store.py:71
from parrot.knowledge.wiki.federation import FederatedWikiStore                       # federation.py:581
import aiosqlite                                                                      # core dep
```

### Existing Signatures to Use
```python
# store.py
SCHEMA_VERSION = "1"                                              # :46
WIKI_SCHEMA_SQL = """ … pages(concept_id PK, node_id, title, category, summary, body, source_id, token_count, created_at, updated_at, origin, asserted_by) …
                      edges(src, dst, rel, provenance) … pages_fts fts5(concept_id UNINDEXED, title, summary, body) … embeddings … """   # :50-127
_MIGRATION_COLUMNS = {"pages": [("origin", "TEXT NOT NULL DEFAULT 'ingest'"), ("asserted_by", "TEXT")]}   # :131
_SCHEMA_TABLES = frozenset({"meta", "sources", "pages", "edges", "pages_fts", ...})   # :141 — presence probe
class WikiPageRecord(BaseModel)                                    # :224 (content_hash field added by TASK-2738)
class BaseWikiStore(ABC):                                          # :332
    upsert_pages :351 · add_edges :354 · replace_source_slice(source_id, pages, edges=None) -> dict :357 · get_page :372 · list_pages :375
    search_fts(query, category=None, limit=10) :383 · neighbors :389 · dump_pages :397 · stats :403 · broken_edges :410
class SQLiteWikiStore(BaseWikiStore):                              # :488
    executescript(WIKI_SCHEMA_SQL) + meta schema_version write     # :663-666
    async def _migrate(self, conn) — iterates _MIGRATION_COLUMNS   # :818-830
    upsert_pages :899 · add_edges :919 · replace_source_slice :941 · get_page :1080 · list_pages :1109 · search_fts :1147 · neighbors :1237 · stats :1300 (COUNT queries :1310-1314) · broken_edges :1337
# arango_store.py: ArangoDBWikiStore :128 ; upsert_pages :510 writes doc fields origin/asserted_by/updated_at (:535-550) — add content_hash beside them ; replace_source_slice :590 ; stats :952
# file_store.py: InMemoryWikiStore :71 ; _write_page_file :208 appends machine fields to frontmatter for keys ("category","node_id","source_id","token_count","created_at") (:218) — add content_hash ; _parse_page_file :155 ; stats :631
# federation.py: FederatedWikiStore(BaseWikiStore) :581 ; write methods delegate to local (:998-1023) ; read methods fan out (:836-896) ; _EmptyStore :1059 must also get the defaults (inherits from BaseWikiStore — defaults cover it)
# tests/knowledge/wiki/test_store.py:30  @pytest.fixture(params=["sqlite", "memory"]) def store(tmp_path, request) -> BaseWikiStore
```

### Does NOT Exist
- ~~`pages.content_hash`~~, ~~`symbols` / `symbols_fts`~~, ~~`BaseWikiStore.upsert_symbols/symbols_for/find_symbols/search_symbols_fts/page_hashes`~~ — created here.
- ~~`@abstractmethod` for the new methods~~ — they must be **concrete defaults** so `ArangoDBWikiStore`, `InMemoryWikiStore`, `FederatedWikiStore`, `_EmptyStore` keep instantiating without changes.
- ~~a `wiki_symbols` Arango collection or BM25 view change~~ — non-goal in this feature.
- ~~`search_fts(exclude_category=…)`~~ — do not add; symbol exclusion is done in `WikiQueryTool` (TASK-2750).
- ~~`sources.file_hash` join for `page_hashes`~~ — resolved against; read `pages.content_hash`.

---

## Implementation Notes

### Pattern to Follow
```python
# BaseWikiStore default (concrete):
async def page_hashes(self, concept_ids: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for cid in concept_ids:
        page = await self.get_page(cid, include_body=False)
        out[cid] = (page or {}).get("content_hash")
    return out
# SQLite override: single `SELECT concept_id, content_hash FROM pages WHERE concept_id IN (...)`
```

### Key Constraints
- Migration must be idempotent and never rewrite existing rows; the presence
  probe replays `WIKI_SCHEMA_SQL` when `symbols` is missing (add to `_SCHEMA_TABLES`).
- `symbols_fts` kept in sync inside `upsert_symbols` / the slice delete (same
  transaction as pages).
- `find_symbols` ordering: exact `name` matches first, then `qualname`, then
  `rel_path`; `limit` applied after ordering.
- Async throughout (`aiosqlite`), `asyncio.to_thread` never needed here.

### References in Codebase
- `store.py:818-830` — `_migrate` ALTER loop (extend, do not duplicate).
- `store.py:941-1078` — `replace_source_slice` transaction (add the `symbols` delete inside it).
- `tests/knowledge/wiki/test_updated_at.py` — precedent for a column added after v1 and tested on every backend.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/test_store.py tests/knowledge/wiki/test_store_migration_v2.py tests/knowledge/wiki/test_arango_store.py tests/knowledge/wiki/test_file_store.py tests/knowledge/wiki/test_federation.py -v` passes.
- [ ] Opening the committed v1 fixture DB yields `content_hash` column, `symbols`, `symbols_fts`; page rows unchanged; `meta.schema_version == "2"`; second open is a no-op.
- [ ] Five symbol methods return equivalent results on sqlite and memory for the same `sym:` pages (defaults) — sqlite additionally answers from `symbols` when rows exist.
- [ ] `replace_source_slice(source_id, …)` removes that source's `symbols` rows and FTS entries atomically.
- [ ] `stats()["symbols"]` present on all three backends.
- [ ] `WikiPageRecord.content_hash` round-trips through `upsert_pages`/`get_page` on every backend.
- [ ] `ruff` / `mypy` clean.

---

## Test Specification

```python
async def test_symbol_methods_every_backend(store):
    from parrot.knowledge.wiki.symbols import SymbolRecord, SymbolKind, sym_concept_id
    rec = SymbolRecord(rel_path="a.py", language="python", kind=SymbolKind.FUNCTION, name="helper", qualname="helper",
                       start_line=1, end_line=2, start_byte=0, end_byte=20, content_hash="h")
    page = WikiPageRecord(concept_id=sym_concept_id("a.py", "helper"), node_id="a.py", title="helper", category="symbol",
                          summary="Utility helper.", body=symbol_to_page_fields(rec)["body"], content_hash="h")
    await store.upsert_pages([page]); await store.upsert_symbols([rec], source_id="s1")
    assert (await store.page_hashes([page.concept_id]))[page.concept_id] == "h"
    assert [s.qualname for s in await store.find_symbols(name="helper")] == ["helper"]
    assert (await store.symbols_for("a.py"))[0].kind == SymbolKind.FUNCTION
```

---

## Agent Instructions

1. Read spec §2 Data Models (DDL), §3 Module 5, §7 "Store defaults". 2. Confirm
TASK-2738 completed. 3. Verify contract lines. 4. Index → `in-progress`.
5. Implement SQLite first, then defaults, then backends. 6. Run tests.
7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: `SCHEMA_VERSION="2"`; `pages.content_hash` via `_MIGRATION_COLUMNS`
(+ a new `UPDATE meta SET value=... WHERE key='schema_version'` step in
`_migrate()` — needed since `INSERT OR IGNORE` never touches an existing
row, so a v1 plane would otherwise keep reporting `"1"` forever);
`symbols`/`symbols_fts` DDL + `_SCHEMA_TABLES` probe entries. Five
concrete (non-abstract) `BaseWikiStore` defaults added right before
`class SQLiteWikiStore`, built on `list_pages(category="symbol")`/
`search_fts(category="symbol")`/`get_page` + the new `symbols.py` decoder
pair `symbol_to_page_fields()`/`symbol_from_page()` (fixed-order
`"\n\n"`-joined body sections, inverted positionally — documented as
intentionally lossy for `start_byte`/`end_byte`/`is_async`/`decorators`/
`node_kind`/`depth`, full fidelity is SQLite-only). SQLite native
overrides query the `symbols`/`symbols_fts` tables directly.
`replace_source_slice()` now also clears `symbols`/`symbols_fts` rows by
`source_id` in the same transaction. ArangoDB/InMemory/Federated: added
`content_hash` field/frontmatter key + `stats()["symbols"]` (Arango
counts `category=='symbol'` docs; InMemory reads its `categories`
Counter); `_EmptyStore` needed no changes (inherits the new defaults
unchanged, exactly as intended). Generated `tests/knowledge/wiki/fixtures/
wiki_v1.db` with a standalone script reproducing the pre-FEAT-498 schema
literally (not by reusing `WIKI_SCHEMA_SQL`, which already has the v2
additions) — 3 pages, 2 edges, `meta.schema_version=='1'`, no
`content_hash`/`symbols`/`symbols_fts` — then committed the binary
artefact per the task's Files table.
`pytest tests/knowledge/wiki/test_store.py tests/knowledge/wiki/
test_store_migration_v2.py tests/knowledge/wiki/test_arango_store.py
tests/knowledge/wiki/test_file_store.py tests/knowledge/wiki/
test_federation.py -v` → 191 passed. Full `tests/knowledge/wiki`: 1293
passed (same single pre-existing unrelated failure in
`test_claude_code.py`, verified present before this task too). `ruff
check` clean on new code (removed two `noqa: S608` comments I'd copied
from existing precedent that ruff flags as unused in this repo's config —
`RUF100` — since `S608` isn't enabled here); pre-existing UP045/SIM117/
TRY004 findings throughout `store.py`/`file_store.py`/`test_store.py`
left untouched (verified identical against the pre-task file, out of
scope). `mypy --ignore-missing-imports`: zero new findings on any of the
five touched source files — every reported error verified present
byte-for-byte in the pre-task version too.
**Deviations from spec**: none — the `symbol_from_page` lossy-decode
trade-off and the `_migrate()` schema_version bump are both explicitly
anticipated by the spec's "abstract-with-default" design and the
migration acceptance criterion, not scope changes.
