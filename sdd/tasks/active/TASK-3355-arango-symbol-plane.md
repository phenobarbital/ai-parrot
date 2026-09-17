# TASK-3355: ArangoDB symbol plane — `wiki_symbols` collection + four `BaseWikiStore` overrides (M5b)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5b, AC5, §8 Q5 (resolved: implement in this feature). SQLite has
a native `symbols` table + `symbols_fts` (store.py:131, :193); `ArangoDBWikiStore`
has neither, so `BaseWikiStore`'s defaults apply: `upsert_symbols` is a no-op and
`symbols_for` / `find_symbols` / `search_symbols_fts` fall back to scanning
`category="symbol"` pages (slow, byte offsets zeroed). On an ArangoDB-backed
remote server that makes the structural tools inert and drops every symbol that
`wiki_ingest_batch` (TASK-3356) pushes. This task gives ArangoDB a real symbol
plane with the same contract SQLite honours.

---

## Scope

- `SYMBOLS_COLLECTION = "wiki_symbols"`; created in `initialize()` alongside the other collections; `_create_symbols_view()` builds an ArangoSearch view `f"{wiki_name}_symbols_view"` over `name`, `qualname`, `doc`, `signature` with `self.analyzers` (mirror `_create_pages_view` + `_view_properties`).
- Override `upsert_symbols(symbols, source_id=None) -> int` (AQL UPSERT keyed by `document_key(sym_concept_id(rel_path, qualname))`; when `source_id` is given, first REMOVE rows with that `source_id` that are not in the new set — slice semantics), `symbols_for(rel_path)`, `find_symbols(name=None, *, qualname_prefix, kind, language, path_prefix, limit=50)`, `search_symbols_fts(query, limit=20)` (BM25 over the symbols view), plus `_doc_to_symbol_record()`.
- `replace_source_slice()` must also drop `wiki_symbols` rows of that `source_id` (so a re-pushed slice never leaves stale symbols).
- Unit tests with a fake `_query` / `_db` (no live ArangoDB), mirroring `test_arango_document_key.py` / `tests/knowledge/wiki/test_factory_arango.py` style.

**NOT in scope**: bulk tools (TASK-3356), read-repair on the server (TASK-3353), migration of existing `sym:` pages (they stay as pages; the view is additive).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` | MODIFY | collection constant, view, four overrides, slice cleanup |
| `packages/ai-parrot/tests/knowledge/wiki/test_arango_symbols.py` | CREATE | Unit tests with fake AQL layer |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore, document_key, PAGES_COLLECTION, EDGES_COLLECTION   # arango_store.py:135, :73, :46, :47
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens, rank_by_cosine             # already imported at arango_store.py:36-41
from parrot.knowledge.wiki.symbols import SymbolRecord, SymbolKind, sym_concept_id, parse_sym_id                      # symbols.py:56, :141, :159 — NOT yet imported in arango_store.py (add)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
PAGES_COLLECTION = "wiki_pages"; EDGES_COLLECTION = "wiki_edges"; EMBEDDINGS_COLLECTION = "wiki_embeddings"
SOURCES_COLLECTION = "wiki_sources"; META_COLLECTION = "wiki_meta"                       # :46-50 (META line is the anchor, 1 occurrence)
def document_key(identity: str) -> str                                                  # :73-114 — valid _key from a wiki id
class ArangoDBWikiStore(BaseWikiStore):                                                 # :135
    def _assert_writable(self) -> None                                                  # :203
    def analyzers(self) -> ...                                                          # :218-241 (property)
    async def initialize(self) -> None                                                  # :258-307 — collection loop `for name, is_edge in ((PAGES_COLLECTION, False), … (META_COLLECTION, False),):` then `await self._create_pages_view()` (each anchor 1 occurrence)
    def _view_properties(self) -> dict[str, Any]                                        # :340 (property) — link/analyzer shape for the pages view
    async def _create_pages_view(self) -> None                                          # :355-~400 — uses self._db._connection.views()/create_view(name=self._view_name, view_type="arangosearch", properties=self._view_properties)/replace_view
    async def _ensure_init(self) -> None                                                # :476
    async def _query(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]            # :488
    async def upsert_pages(self, pages) -> int                                          # :517-564 — AQL UPSERT doc shape {"_key": document_key(cid), ...}
    async def replace_source_slice(self, source_id, pages, edges=None) -> dict          # :599-675 — REMOVE by source_id then insert
    async def search_fts(self, query, category=None, limit=10) -> list[dict]            # :816 (anchor `    async def search_fts(` 1 occurrence) — BM25 over the pages view
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py — contract being overridden
async def upsert_symbols(self, symbols: list[SymbolRecord], source_id: Optional[str] = None) -> int   # :687-705 (default returns 0)
async def symbols_for(self, rel_path: str) -> list[SymbolRecord]                                      # :707
async def find_symbols(self, name=None, *, qualname_prefix=None, kind=None, language=None, path_prefix=None, limit=50) -> list[SymbolRecord]   # :734-780 (exact-name hits first, then others)
async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]                 # :782
# packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py
class SymbolRecord(BaseModel)   # :56 — rel_path, language, kind: SymbolKind, name, qualname, parent, signature, doc, exported, is_async, start_line, end_line, start_byte, end_byte, node_kind, decorators, content_hash, depth
def sym_concept_id(rel_path: str, qualname: str, ordinal: int = 1) -> str   # :141
```

### Does NOT Exist
- ~~`SYMBOLS_COLLECTION`~~, ~~`ArangoDBWikiStore.upsert_symbols/symbols_for/find_symbols/search_symbols_fts`~~, ~~`_create_symbols_view`~~ — created here (grep confirmed none defined in arango_store.py).
- ~~`self._view_name = ...` assignment~~ — `_view_name` is derived (grep finds no assignment); read how `_create_pages_view` obtains it (:355-400) and mirror with a `_symbols_view_name` property; do not invent an attribute.
- ~~`self._db.create_arangosearch_view(...)`~~ — the asyncdb wrapper is broken (documented at :355-380); drive `self._db._connection` exactly as `_create_pages_view` does.
- ~~ArangoDB multi-document transactions~~ — not used anywhere in this store; per-slice semantics only (§8 Q4).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_arango_symbols.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py#ArangoDBWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py#ArangoDBWikiStore.initialize",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py#ArangoDBWikiStore.replace_source_slice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py#document_key",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.upsert_symbols",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#SymbolRecord"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Signatures are the `BaseWikiStore` ones (store.py:687-782) — do not add parameters.
- `read_only=True` stores (`_connect_existing`, :309) must **verify** the symbols collection exists rather than create it — same rule as the pages collection (FEAT-450).
- Document shape: every `SymbolRecord` field + `concept_id` (= `sym_concept_id(rel_path, qualname)`) + `source_id` + `updated_at`; `kind` stored as `kind.value`.
- `find_symbols` ordering must match SQLite's: exact `name` matches first, then the rest, capped at `limit`.
- Tests never need a server: monkeypatch `_ensure_init` (no-op) and `_query` (record AQL + bind vars, return canned rows).

---

## Implementation Blueprint

### Steps (in order)
1. Add the `symbols` import and `SYMBOLS_COLLECTION` — *why*: constants and types first.
2. Register the collection in `initialize()` and create the view — *why*: provisioning must exist before any override runs on a fresh database.
3. Add `_create_symbols_view()` next to `_create_pages_view()` — *why*: same connection quirk, same reconciliation logic.
4. Add the four overrides + `_doc_to_symbol_record()` before `search_fts` — *why*: groups read/search methods together.
5. Extend `replace_source_slice` to remove that source's symbol rows — *why*: slice replacement must not leave orphan symbols.
6. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` (MODIFY — block 1: constants & imports)
```python
# occurrences: 1 (verified: grep -c '^META_COLLECTION = "wiki_meta"' packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py)
# AFTER — insert below `META_COLLECTION = "wiki_meta"` (verified: arango_store.py:50)
SYMBOLS_COLLECTION = "wiki_symbols"
# ALSO add to the import block (after `from parrot.knowledge.wiki.store import (...)`, arango_store.py:36-41):
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord, sym_concept_id

# occurrences: 1 (verified: grep -c '                (META_COLLECTION, False),' arango_store.py)
# AFTER — insert below `                (META_COLLECTION, False),` (inside initialize(), arango_store.py:~299)
                (SYMBOLS_COLLECTION, False),
# occurrences: 1 (verified: grep -c '            await self._create_pages_view()' arango_store.py)
# AFTER — insert below `            await self._create_pages_view()` (arango_store.py:~305)
            await self._create_symbols_view()
```
**Why**: the create loop is the single provisioning point; a `read_only` store never reaches it (`_connect_existing` returns earlier) — add a `SYMBOLS_COLLECTION` existence check to `_connect_existing` (:309) with the same `FileNotFoundError` wording it uses for pages.

### `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` (MODIFY — block 2: view)
```python
# occurrences: 1 (verified: grep -c '    async def _create_pages_view(self) -> None:' arango_store.py)
# BEFORE — insert above `    async def _create_pages_view(self) -> None:` (verified: arango_store.py:355)
    @property
    def _symbols_view_name(self) -> str:
        """ArangoSearch view over ``wiki_symbols`` (``{wiki_name}_symbols_view``)."""
        # FILL IN: build the name the same way _view_name derives "{wiki_name}_pages_view" (read :180-200 / the _view_name property)
        raise NotImplementedError

    @property
    def _symbols_view_properties(self) -> dict[str, Any]:
        """Link ``SYMBOLS_COLLECTION`` fields name/qualname/doc/signature with :attr:`analyzers` — mirrors :attr:`_view_properties`."""
        # FILL IN: copy _view_properties (:340-354) and swap the collection + field list — bounded by the pages view shape
        raise NotImplementedError

    async def _create_symbols_view(self) -> None:
        """Create or reconcile the symbols view exactly like :meth:`_create_pages_view`."""
        connection = self._db._connection
        existing = await connection.views()
        if not any(v.get("name") == self._symbols_view_name for v in existing):
            await connection.create_view(name=self._symbols_view_name, view_type="arangosearch", properties=self._symbols_view_properties)
            return
        # FILL IN: analyzer reconciliation — reuse _view_analyzers_match/replace_view pattern from :390-400, parametrised by view name
```
**Why**: the asyncdb wrapper's view helpers are broken (documented :355-380), so the raw `_connection` path is mandatory. Keep the reconciliation so adding an analyzer later re-links the view.

### `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` (MODIFY — block 3: overrides)
```python
# occurrences: 1 (verified: grep -c '    async def search_fts(self, query: str, category: Optional\[str\] = None, limit: int = 10) -> list\[dict\[str, Any\]\]:' arango_store.py)
# BEFORE — insert above `    async def search_fts(` (verified: arango_store.py:816)
    def _symbol_doc(self, record: SymbolRecord, source_id: Optional[str], now: str) -> dict[str, Any]:
        """Document shape for one symbol row (inverse of :meth:`_doc_to_symbol_record`)."""
        concept_id = sym_concept_id(record.rel_path, record.qualname)
        return {"_key": document_key(concept_id), "concept_id": concept_id, "source_id": source_id or f"file:{record.rel_path}",
                "updated_at": now, **record.model_dump(mode="json")}

    def _doc_to_symbol_record(self, doc: dict[str, Any]) -> SymbolRecord:
        """Rebuild a :class:`SymbolRecord` from a ``wiki_symbols`` document."""
        fields = {k: v for k, v in doc.items() if k in SymbolRecord.model_fields}
        return SymbolRecord.model_validate(fields)

    async def upsert_symbols(self, symbols: list[SymbolRecord], source_id: Optional[str] = None) -> int:
        """Persist symbols; with ``source_id`` first drop that source's rows absent from ``symbols`` (slice semantics)."""
        if not symbols and source_id is None:
            return 0
        self._assert_writable()
        await self._ensure_init()
        now = _now_iso()
        docs = [self._symbol_doc(r, source_id, now) for r in symbols]
        if source_id is not None:
            keep = [d["_key"] for d in docs]
            await self._query("FOR s IN @@c FILTER s.source_id == @sid AND s._key NOT IN @keep REMOVE s IN @@c",
                              {"@c": SYMBOLS_COLLECTION, "sid": source_id, "keep": keep})
        if docs:
            await self._query("FOR d IN @docs UPSERT {_key: d._key} INSERT d REPLACE d IN @@c",
                              {"@c": SYMBOLS_COLLECTION, "docs": docs})
        return len(docs)

    async def symbols_for(self, rel_path: str) -> list[SymbolRecord]:
        """Every symbol of one file, ordered by ``start_line``."""
        await self._ensure_init()
        rows = await self._query("FOR s IN @@c FILTER s.rel_path == @p SORT s.start_line RETURN s", {"@c": SYMBOLS_COLLECTION, "p": rel_path})
        return [self._doc_to_symbol_record(r) for r in rows]

    async def find_symbols(self, name: Optional[str] = None, *, qualname_prefix: Optional[str] = None, kind: Optional[str] = None,
                           language: Optional[str] = None, path_prefix: Optional[str] = None, limit: int = 50) -> list[SymbolRecord]:
        """Filtered lookup; exact-``name`` hits sort first (same order as the SQLite store)."""
        await self._ensure_init()
        # FILL IN: build FILTER clauses only for non-None args (STARTS_WITH for prefixes, == for kind/language/name);
        #          SORT (s.name == @name ? 0 : 1), s.qualname LIMIT @limit — bounded by store.py:734-780 ordering contract
        raise NotImplementedError

    async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]:
        """BM25 search over the symbols view (name/qualname/doc/signature)."""
        await self._ensure_init()
        # FILL IN: mirror search_fts (:816-…) — SEARCH ANALYZER(...) over self._symbols_view_name, SORT BM25(s) DESC LIMIT @limit
        raise NotImplementedError
```
**Why this shape**: keyed UPSERT makes pushes idempotent (TASK-3356 re-runs converge); the `REMOVE … NOT IN keep` gives `upsert_symbols(symbols, source_id)` the slice semantics the SQLite table has; record fields round-trip through `model_dump(mode="json")` so `kind` is stored as its value.

### `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` (MODIFY — block 4: slice cleanup)
```python
# occurrences: 1 (verified: grep -c '    async def replace_source_slice(' arango_store.py)
# INSIDE replace_source_slice (arango_store.py:599-675), right after the existing REMOVE of old pages/edges and BEFORE the inserts, add:
        await self._query("FOR s IN @@c FILTER s.source_id == @sid REMOVE s IN @@c", {"@c": SYMBOLS_COLLECTION, "sid": source_id})
# FILL IN: place it exactly where old_keys are removed (read :640-660) so a slice replacement drops stale symbols too — bounded by AC5/AC10
```
**Why**: `wiki_ingest_batch` calls `replace_source_slice` then `upsert_symbols(source_id=…)`; deleting a file (`pages=[]`, no symbols) must leave zero symbol rows.

### FILL IN checklist
- [ ] `_symbols_view_name` / `_symbols_view_properties` — mirror the pages view (:340-354 and the `_view_name` derivation).
- [ ] `_create_symbols_view` analyzer reconciliation — reuse the pages-view helper pattern.
- [ ] `find_symbols` AQL filters + ordering — bounded by store.py:734-780.
- [ ] `search_symbols_fts` AQL — bounded by `search_fts` (:816).
- [ ] `_connect_existing` verifies `SYMBOLS_COLLECTION` for read-only opens.
- [ ] `replace_source_slice` symbol cleanup placement.

---

## Acceptance Criteria

- [ ] With `_query` faked: `upsert_symbols([a, b], source_id="file:x.py")` issues one REMOVE (`keep` = both keys) and one UPSERT with 2 docs whose `_key == document_key(sym_concept_id(...))` and `kind` is a string.
- [ ] `symbols_for("x.py")` decodes canned rows into `SymbolRecord`s with correct `start_byte`/`end_byte`.
- [ ] `find_symbols(name="f", kind="function")` produces AQL with both filters and `LIMIT`; results keep exact-name hits first.
- [ ] `search_symbols_fts("parse")` targets the symbols view name.
- [ ] `initialize()` create loop includes `wiki_symbols` (assert on a fake `_db.create_collection` recorder) and calls `_create_symbols_view()`.
- [ ] `replace_source_slice("file:x.py", [])` issues a symbols REMOVE for that source.
- [ ] Existing `tests/knowledge/wiki/test_factory_arango.py`, `test_arango_document_key.py` pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_arango_symbols.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_arango_document_key.py -q`
- `pytest tests/knowledge/wiki/test_factory_arango.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_arango_symbols.py
import pytest
from parrot.knowledge.wiki.arango_store import SYMBOLS_COLLECTION, ArangoDBWikiStore, document_key
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord, sym_concept_id


@pytest.fixture
def store(monkeypatch):
    s = ArangoDBWikiStore(arango_params={}, database="db", wiki_name="w", text_analyzer="text_en")
    calls = []
    async def fake_query(aql, bind_vars): calls.append((aql, bind_vars)); return fake_query.rows
    fake_query.rows = []
    async def noop(): return None
    monkeypatch.setattr(s, "_query", fake_query); monkeypatch.setattr(s, "_ensure_init", noop)
    s._calls = calls; s._fake = fake_query
    return s


def _rec(name="f", path="x.py"):
    return SymbolRecord(rel_path=path, language="python", kind=SymbolKind.FUNCTION, name=name, qualname=name,
                        start_line=1, end_line=2, start_byte=0, end_byte=9)   # FILL IN: required fields


async def test_upsert_symbols_slice_semantics(store):
    n = await store.upsert_symbols([_rec("a"), _rec("b")], source_id="file:x.py")
    assert n == 2
    remove, upsert = store._calls
    assert "REMOVE" in remove[0] and remove[1]["sid"] == "file:x.py" and len(remove[1]["keep"]) == 2
    assert upsert[1]["docs"][0]["_key"] == document_key(sym_concept_id("x.py", "a"))
    assert upsert[1]["docs"][0]["kind"] == "function"


async def test_symbols_for_roundtrip(store):
    store._fake.rows = [store._symbol_doc(_rec(), "file:x.py", "2026-01-01T00:00:00Z")]
    recs = await store.symbols_for("x.py")
    assert recs[0].qualname == "f" and recs[0].end_byte == 9
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — re-read `_create_pages_view` (:355-400) and `search_fts` (:816) before writing AQL
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
