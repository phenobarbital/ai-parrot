# TASK-4377: HelixWikiStore — CAS, meta, attrs, symbols, page_hashes

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4376
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G1, AC1): `HelixWikiStore` must also override the **concrete-with-default** surface of
`BaseWikiStore` that `SQLiteWikiStore` implements natively: `compare_and_swap_page` (FEAT-578 ADR
writes), `get_meta`/`set_meta` (FEAT-609), the public attrs API (FEAT-627), the native symbol plane
(FEAT-498) and `page_hashes`. TASK-4376 created the module, the `Page`/`Symbol`/`Meta`/`PageAttr` labels
in `WIKI_PLANE` and already writes attrs inside page batches; this task adds the remaining public methods
to the same class. TASK-4381 (ledger state as `Meta` nodes) and TASK-4382 depend on `get_meta`/`set_meta`.

---

## Scope

- Add to `HelixWikiStore` in `packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py`:
  `compare_and_swap_page`, `get_meta`, `set_meta`, `get_attrs`, `list_by_attrs`, `upsert_attrs`,
  `upsert_symbols`, `symbols_for`, `find_symbols`, `search_symbols_fts`, `page_hashes`,
  plus module-private helpers `_symbol_props(sym, source_id)` / `_symbol_from_props(props)`.
- Write `packages/ai-parrot/tests/knowledge/wiki/test_helix_store_cas.py` (CAS + meta + attrs, cloned from
  `test_store_cas.py`, `test_store_meta.py`, `test_store_attrs.py` cases) and
  `packages/ai-parrot/tests/knowledge/wiki/test_helix_symbols.py` (cloned from `test_postgres_symbols.py`).

**NOT in scope**: anything already in TASK-4376 (abstract surface, plane schema, lifecycle); bulk
`dump_attrs`/`dump_meta`/`dump_symbols`/`dump_embeddings` (TASK-4393); registry rows (TASK-4392);
`wiki/store.py` edits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` | MODIFY | Add CAS / meta / attrs / symbols / page_hashes methods |
| `packages/ai-parrot/tests/knowledge/wiki/test_helix_store_cas.py` | CREATE | CAS, meta and attrs parity tests |
| `packages/ai-parrot/tests/knowledge/wiki/test_helix_symbols.py` | CREATE | Symbol-plane parity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, AttrsUnsupportedError  # verified: wiki/store.py:697, :433, :429
from parrot.knowledge.wiki.symbols import SymbolRecord, SymbolKind, sym_concept_id  # verified: wiki/symbols.py:58, (SymbolKind used at store.py:407), :150
# Created by TASK-4376 (same file, not on dev yet): HelixWikiStore, WIKI_PLANE, PAGE_LABEL, SYMBOL_LABEL, META_LABEL,
#   PAGE_ATTR_LABEL, attr_key, MAX_SEARCH_LIMIT, HelixWikiStore._c / _assert_writable / _add_page_entries
# Created by TASK-4374: from parrot.knowledge.helix import dsl as hdsl  (cas_page_entries → returning var "cas_applied", upsert_node_entries, lookup_by_key, text_search, clamp_limit)
# Created by TASK-4373: from parrot.knowledge.helix.client import _sdk  (write_batch()/read_batch())
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py — base defaults being overridden
async def get_attrs(self, concept_id: str) -> dict[str, str]                                   # line 718
async def list_by_attrs(self, filters: Mapping[str, str | Sequence[str]], *, date_key: str | None = None,
                        since: str | None = None, until: str | None = None, limit: int = 200) -> list[dict[str, Any]]  # line 722
async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int  # line 734
async def compare_and_swap_page(self, page: WikiPageRecord, expected_content_hash: Optional[str]) -> bool  # line 824
async def get_meta(self, key: str) -> Optional[str]                                           # line 858
async def set_meta(self, key: str, value: str) -> None                                        # line 872
async def upsert_symbols(self, symbols: list[SymbolRecord], source_id: Optional[str] = None) -> int  # line 958
async def symbols_for(self, rel_path: str) -> list[SymbolRecord]                              # line 978
async def find_symbols(self, name=None, qualname_prefix=None, kind=None, language=None, path_prefix=None,
                       limit: int = 50) -> list[SymbolRecord]                                 # line 1005
async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]          # line 1053
async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]               # line 1074
# SQLite natives to mirror (semantics):
#   compare_and_swap_page :1865 — None ⇒ insert-only (fails if ANY row exists); else row must exist with equal hash
#   upsert_attrs :2027 — unknown page ⇒ 0, replace=True clears first, returns rows written
#   list_by_attrs :2087 — AND across keys, list value = IN, date bounds inclusive on date_key attr,
#       ValueError("since/until require date_key"), no filters ⇒ pages having ≥1 attr, ORDER BY updated_at DESC, concept_id,
#       stub cols + "attrs"
#   upsert_symbols :2183 — concept_id = sym_concept_id(rel_path, qualname); stamps source_id
#   symbols_for :2254 (ORDER BY start_line) ; find_symbols :2270 (ORDER BY rel_path, qualname; prefix filters)
#   search_symbols_fts :2320 ; get_meta :2346 ; set_meta :2353 ; page_hashes :2362 (None for absent ids)
#   _row_to_symbol_record :396 — field decoding (kind → SymbolKind, falsy → defaults)
# packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py
class SymbolRecord(BaseModel):   # line 58 — rel_path, language, kind, name, qualname, parent, signature, doc, exported,
                                 #   is_async, start_line, end_line, start_byte, end_byte, node_kind, decorators,
                                 #   content_hash, depth (lines 90-107)
def sym_concept_id(rel_path: str, qualname: str, ordinal: int = 1) -> str   # line 150
```

### Does NOT Exist
- ~~A HelixDB upsert op~~ — use `hdsl.upsert_node_entries`.
- ~~`HelixWikiStore.dump_meta` / `dump_symbols` / `dump_attrs`~~ — TASK-4393.
- ~~`SymbolRecord.concept_id`~~ — not a field; derive with `sym_concept_id`.
- ~~Symbol `decorators` column in SQLite~~ — SQLite does not persist `decorators` (`store.py:2183` row tuple); persisting it on HelixDB is allowed but parity tests must not require it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_helix_store_cas.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_helix_symbols.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.compare_and_swap_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.get_meta",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.set_meta",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.list_by_attrs",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.upsert_symbols",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.list_by_attrs",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#SymbolRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#sym_concept_id"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **CAS is one batch** (spec §2 Transactions): conditional entries via `hdsl.cas_page_entries(batch, page_props,
  expected_hash)` — the condition variable reads `Page(concept_id)`'s `content_hash`; the write entries
  (page props + PageAttr replacement, reuse TASK-4376's `_add_page_entries` shape) run only under
  `var_as_if`. Return value: whether the conditional branch executed (expose it as a `returning` var).
  `None` expected ⇒ insert-only: fails when ANY `Page(concept_id)` exists, **including a stub** — decide:
  a stub page (edge target only) counts as absent for insert-only (SQLite has no row for it). Document the
  choice in a code comment.
- `get_meta`/`set_meta`: `Meta` node, unique `key`, property `value` (string). `get_meta` works on
  read-only stores; `set_meta` calls `_assert_writable()`.
- Attrs: `PageAttr(attr_key, concept_id, key, value)`. `upsert_attrs` on a missing / stub page returns 0
  without writing; `replace=True` drops the page's attrs in the same batch. `list_by_attrs`: read candidate
  `PageAttr` rows by key (equality index), intersect concept ids per filter key in Python, apply inclusive
  string date bounds, then fetch the page stubs; sort `(updated_at DESC, concept_id)`; truncate to `limit`.
- Symbols: `Symbol` node props = every SQLite `symbols` column (`store.py:2209-2231`) + `concept_id` +
  `search_text = "\n".join([name, qualname, doc, signature])`. `upsert_symbols` = one batch of
  `upsert_node_entries`. `search_symbols_fts` uses `hdsl.text_search("Symbol", "search_text", q, min(limit,800), …)`.
  Decode with `_symbol_from_props` mirroring `_row_to_symbol_record` (`store.py:396-426`).
- `page_hashes`: one read batch over the ids; absent or stub ⇒ `None`; every requested id present in the result.

---

## Implementation Blueprint

### Steps (in order)
1. Re-read TASK-4376's final `helix_store.py` (helpers and batch-constructor names) — *why*: these methods reuse them.
2. Add meta, then attrs, then CAS, then symbols, then `page_hashes` — *why*: CAS tests use attrs on the page.
3. Write both test files; run them.

### `packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` (MODIFY)
```python
# occurrences: 1 (anchor is created by TASK-4376 — verify: grep -c -F 'class HelixWikiStore(BaseWikiStore):' packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py)
# AFTER — append these methods inside `class HelixWikiStore(BaseWikiStore):`, before the module-level `_now_iso`
    async def get_meta(self, key: str) -> Optional[str]:
        """Read one Meta value (works on read-only planes)."""
        client = await self._c()
        # FILL IN: read hdsl.lookup_by_key("Meta", "key", key) → value | None — bounded by store.py:2346
        raise NotImplementedError

    async def set_meta(self, key: str, value: str) -> None:
        """Upsert one Meta value in a single batch."""
        self._assert_writable()
        client = await self._c()
        batch = _sdk().write_batch()
        hdsl.upsert_node_entries(batch, "m", "Meta", "key", {"key": key, "value": value})
        await client.write(batch, query_name="wiki.set_meta")

    async def get_attrs(self, concept_id: str) -> dict[str, str]:
        """Persisted attrs of one page ({} when none)."""
        raise NotImplementedError  # FILL IN: PageAttr where concept_id == concept_id → {key: value}

    async def list_by_attrs(self, filters: Mapping[str, str | Sequence[str]], *, date_key: str | None = None,
                            since: str | None = None, until: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Page stubs (+ "attrs") whose attrs match every filter (store.py:2087 semantics)."""
        if (since is not None or until is not None) and not date_key:
            raise ValueError("since/until require date_key")
        # FILL IN: per-key candidate sets from PageAttr(key) rows; empty list value ⇒ []; date bounds inclusive;
        #          no filters/bounds ⇒ every page with ≥1 attr; fetch stubs, sort (updated_at DESC, concept_id), limit
        raise NotImplementedError

    async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int:
        """Write attrs for an EXISTING page (0 when missing/stub) in one batch."""
        self._assert_writable()
        # FILL IN: existence check + (replace ⇒ drop PageAttr(concept_id)) + upsert PageAttr per item, ONE batch;
        #          return len(attrs) or 0 — bounded by store.py:2027
        raise NotImplementedError

    async def compare_and_swap_page(self, page: WikiPageRecord, expected_content_hash: Optional[str]) -> bool:
        """Insert-only when expected is None, else replace iff the stored hash matches — one batch."""
        self._assert_writable()
        # FILL IN: hdsl.cas_page_entries(batch, self._page_props(page, _now_iso()), expected_content_hash)
        #          + PageAttr replacement under the same condition; return bool(result["cas_applied"]) (TASK-4374's returning var) — bounded by store.py:1865
        raise NotImplementedError

    async def upsert_symbols(self, symbols: list[SymbolRecord], source_id: Optional[str] = None) -> int:
        """Upsert native Symbol nodes keyed by sym_concept_id(rel_path, qualname)."""
        self._assert_writable()
        if not symbols:
            return 0
        client = await self._c()
        batch = _sdk().write_batch()
        for i, sym in enumerate(symbols):
            hdsl.upsert_node_entries(batch, f"s{i}", "Symbol", "concept_id", _symbol_props(sym, source_id))
        await client.write(batch, query_name="wiki.upsert_symbols")
        return len(symbols)

    async def symbols_for(self, rel_path: str) -> list[SymbolRecord]:
        """Symbols of one file ordered by start_line."""
        raise NotImplementedError  # FILL IN: Symbol where rel_path == rel_path, sort start_line

    async def find_symbols(self, name: Optional[str] = None, qualname_prefix: Optional[str] = None,
                           kind: Optional[str] = None, language: Optional[str] = None,
                           path_prefix: Optional[str] = None, limit: int = 50) -> list[SymbolRecord]:
        """Filtered symbols ordered by (rel_path, qualname) (store.py:2270)."""
        raise NotImplementedError  # FILL IN: equality filters server-side, prefix filters client-side

    async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]:
        """BM25 over Symbol.search_text, best first."""
        raise NotImplementedError  # FILL IN: hdsl.text_search("Symbol", "search_text", query, min(limit, MAX_SEARCH_LIMIT), ...)

    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]:
        """{concept_id: content_hash | None} for every requested id."""
        if not concept_ids:
            return {}
        out: dict[str, Optional[str]] = dict.fromkeys(concept_ids)
        # FILL IN: one read batch over concept_ids (stub pages stay None)
        return out
```
```python
# AFTER — module level, below the class (helpers used above)
def _symbol_props(sym: SymbolRecord, source_id: Optional[str]) -> dict[str, Any]:
    """Symbol node properties (SQLite symbols-table columns + concept_id + search_text)."""
    from parrot.knowledge.wiki.symbols import sym_concept_id

    return {
        "concept_id": sym_concept_id(sym.rel_path, sym.qualname), "rel_path": sym.rel_path, "language": sym.language,
        "kind": sym.kind.value, "name": sym.name, "qualname": sym.qualname, "parent": sym.parent,
        "signature": sym.signature, "doc": sym.doc, "exported": bool(sym.exported), "is_async": bool(sym.is_async),
        "depth": sym.depth, "start_line": sym.start_line, "end_line": sym.end_line, "start_byte": sym.start_byte,
        "end_byte": sym.end_byte, "node_kind": sym.node_kind, "content_hash": sym.content_hash, "source_id": source_id,
        "search_text": "\n".join([sym.name, sym.qualname, sym.doc or "", sym.signature or ""]),
    }


def _symbol_from_props(props: Mapping[str, Any]) -> SymbolRecord:
    """Decode a Symbol node (mirror of wiki/store.py:_row_to_symbol_record)."""
    from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord as _SymbolRecord

    return _SymbolRecord(
        rel_path=props["rel_path"], language=props["language"], kind=SymbolKind(props["kind"]), name=props["name"],
        qualname=props["qualname"], parent=props.get("parent"), signature=props.get("signature") or "",
        doc=props.get("doc") or "", exported=bool(props.get("exported")), is_async=bool(props.get("is_async")),
        start_line=props.get("start_line") or 0, end_line=props.get("end_line") or 0,
        start_byte=props.get("start_byte") or 0, end_byte=props.get("end_byte") or 0,
        node_kind=props.get("node_kind") or "", content_hash=props.get("content_hash") or "", depth=props.get("depth") or 1,
    )
```
**Why**: same contracts as the SQLite natives so ADR (CAS), extractor-fingerprint (meta), standup (attrs)
and structural (symbols) consumers work unchanged. Add `Mapping`, `Sequence` to the module's typing
imports and `SymbolRecord` under `TYPE_CHECKING` (as `wiki/store.py:47` does) to avoid an import cycle.

### FILL IN checklist
- [ ] `get_meta`, `get_attrs`, `list_by_attrs`, `upsert_attrs` — bounded by `store.py:2027-2158,2346`
- [ ] `compare_and_swap_page` — stub-as-absent decision commented; bounded by `store.py:1865` + spec §2 Transactions
- [ ] `symbols_for`, `find_symbols`, `search_symbols_fts`, `page_hashes`

---

## Acceptance Criteria

- [ ] AC1 (rest of the surface): CAS / attrs / meta / symbols / `page_hashes` pass the cloned parity cases on embedded InMemory.
- [ ] CAS: insert-only refuses an existing page; stale hash leaves the stored row intact; read-only raises `PermissionError`.
- [ ] `list_by_attrs` without `date_key` but with `since` raises `ValueError`.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_helix_store_cas.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_helix_symbols.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_helix_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_helix_store_cas.py
import uuid
import pytest

pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")
from parrot.knowledge.helix.settings import HelixMode, HelixSettings
from parrot.knowledge.wiki.helix_store import HelixWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord


@pytest.fixture
async def store():
    s = HelixWikiStore(HelixSettings(mode=HelixMode.MEMORY, database=f"test_{uuid.uuid4().hex}"), wiki_name="t")
    await s.initialize()
    yield s
    await s.close()


class TestCasInsertUpdateConflict:   # clone of tests/knowledge/wiki/test_store_cas.py:23-60
    async def test_insert_when_absent(self, store): ...
    async def test_insert_refuses_when_present(self, store): ...
    async def test_replace_on_matching_hash(self, store): ...
    async def test_conflict_on_stale_hash_leaves_row_intact(self, store): ...
    async def test_update_of_absent_row_is_a_conflict(self, store): ...
    async def test_stub_page_counts_as_absent_for_insert(self, store): ...   # edge-only target, insert-only succeeds

class TestMeta:      # clone of test_store_meta.py:12-30 roundtrip + read-only refusal
    ...

class TestAttrs:     # clone of test_store_attrs.py: lifecycle, replace vs merge, filters (IN, date bounds), missing page → 0
    ...

# packages/ai-parrot/tests/knowledge/wiki/test_helix_symbols.py — clone of test_postgres_symbols.py:54-160
# test_symbol_roundtrip / test_upsert_is_idempotent_update / test_symbols_for_empty_file / test_find_symbols_filters /
# test_search_symbols_fts / test_page_hashes_covers_symbol_pages / test_replace_source_slice_drops_symbols
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`)
2. **Read the spec** (§2 Transactions, §3 M3)
3. **Check dependencies** — TASK-4376 must be `"done"` in `sdd/tasks/index/helixdb-provider.json`
4. **Verify the Codebase Contract** (re-grep the `store.py` line refs; FEAT-633 may move them)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; no `NotImplementedError` may remain
7. **Verify** with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4377 helixdb-provider verified`
10. **Fill in the Completion Note**, commit the SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
