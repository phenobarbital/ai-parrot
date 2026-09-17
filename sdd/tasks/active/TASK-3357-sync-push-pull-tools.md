# TASK-3357: Bulk tools `wiki_sync_push` + `wiki_sync_pull` (M5c)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3356
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (sync part), AC11, design research S9 (pagination confirmed,
tombstones rejected). Today `wikitoolkit sync push|pull` opens the shared
ArangoDB plane from the laptop (`sync._open_remote`). In remote mode the client
must not hold DB credentials, so the LWW engine (`_sync_records`) runs
**server-side** behind two tools: `wiki_sync_push` receives the client's
memory-origin pages + asserted edges in an in-memory store and merges them into
the server plane; `wiki_sync_pull` returns the server's memory pages newer than
`since`, paginated by `(updated_at, concept_id)`. Depends on TASK-3356 (same
file; appends to `create_bulk_tools`).

---

## Scope

- `SyncPagesInput` model (`pages`, `edges` as 4-tuples `(src, dst, rel, "asserted")`, `since`, `skip_asserted_by`, `limit`, `cursor`).
- `WikiSyncPushTool` (`name = "wiki_sync_push"`): seed `InMemoryWikiStore(tmp bundle dir)` with the payload, run `_sync_records(source=mem, destination=self._store, direction="push", env=<wiki_name>, dry_run=False, skip_asserted_by=None)`, return the `SyncReport` fields.
- `WikiSyncPullTool` (`name = "wiki_sync_pull"`): memory-origin pages (+ asserted edges touching them) with `updated_at > since`, excluding `skip_asserted_by`, ordered by `(updated_at, concept_id)`, ≤`limit` (default 500, max 2000); `next_cursor = "<updated_at>|<concept_id>"` or `None`.
- Append both to `create_bulk_tools()`.
- Unit tests (LWW: older push never overwrites newer; pull pagination).

**NOT in scope**: the CLI side (TASK-3363), deletions/tombstones (the engine never propagates deletes — sync.py header), `sync obsidian`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `SyncPagesInput`, two tools, factory extension |
| `packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.sync import SyncReport, _sync_records, _synced_memory_pages, _sync_edges   # sync.py:59, :221, :180, :191 — import lazily INSIDE the tool methods (sync.py imports project/store; keep tools.py import-light)
from parrot.knowledge.wiki.file_store import InMemoryWikiStore          # file_store.py:71 — InMemoryWikiStore(bundle_dir: str | Path, wiki_name: str = "")
from parrot.knowledge.wiki.tools import create_bulk_tools, WikiPageHashesTool, WikiIngestBatchTool   # added by TASK-3356
import tempfile                                                          # stdlib — bundle dir for the in-memory store
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sync.py
class SyncReport                                                          # :59-83 — read its fields (pushed/pulled/skipped counts…) and return .model_dump()/dataclass asdict accordingly
async def _sync_records(*, source: BaseWikiStore, destination: BaseWikiStore, direction: Literal["push","pull"], env: str, dry_run: bool, skip_asserted_by: str | None) -> tuple[SyncReport, set[str]]   # :221-269 — LWW on updated_at; None sorts oldest
async def _synced_memory_pages(store: BaseWikiStore) -> list[dict[str, Any]]                  # :180-188 — list_pages(origin=["memory"], limit=_SYNC_LIST_LIMIT) + get_page(include_body=True)
async def _sync_edges(...)                                                                     # :191-218 — copies `asserted` edges touching concept_ids
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
async def BaseWikiStore.list_pages(self, category=None, limit=100, origin: Optional[list[str]] = None) -> list[dict]   # :568-573
async def BaseWikiStore.upsert_pages(self, pages: list[WikiPageRecord]) -> int   # :544 ; add_edges(self, edges: list[tuple]) -> int :547 (4-tuples (src, dst, rel, kind) — see tools.py:~360 `edges.append((page_id, link_page_id, rel or "references", "asserted"))`)
class WikiPageRecord: updated_at: Optional[str]  # ISO-8601; caller-supplied value preserved on upsert (store.py:426-436)
# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py (after TASK-3356)
def create_bulk_tools(store, root, config) -> list[AbstractTool]   # returns [WikiPageHashesTool, WikiIngestBatchTool] — extend, do not replace
```

### Does NOT Exist
- ~~`wiki_sync_push` / `wiki_sync_pull` tools~~, ~~`SyncPagesInput`~~ — created here.
- ~~`sync_push(root, ...)` usable server-side~~ — it opens planes from a repo root (sync.py:293); use `_sync_records` directly.
- ~~tombstones / deletion exchange~~ — "deletes are never propagated (v1 limitation, documented)" (sync.py:~9); do not add.
- ~~`BaseWikiStore.list_pages(since=...)`~~ — no `since` filter exists; filter `updated_at` in Python after `_synced_memory_pages`.
- ~~`InMemoryWikiStore()` with no args~~ — requires `bundle_dir`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sync.py#_sync_records",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sync.py#_synced_memory_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sync.py#SyncReport",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.list_pages"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `env` passed to `_sync_records` is the wiki name (audit label only).
- Cursor is opaque to clients but deterministic: `f"{updated_at}|{concept_id}"`; pages with `updated_at is None` sort first (oldest) — match sync's LWW convention.
- Pull `limit` clamp: `1 ≤ limit ≤ 2000`, default 500.
- Both tool docstrings must say "used by `wikitoolkit sync` in remote mode; not for agents".

---

## Implementation Blueprint

### Steps (in order)
1. Add `SyncPagesInput` + the two tools **before** `def create_bulk_tools(` — *why*: keeps M5 code contiguous.
2. Extend `create_bulk_tools()`'s return list — *why*: the builder registers whatever the factory returns.
3. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY)
```python
# occurrences: 1 (after TASK-3356: grep -c '^def create_bulk_tools(' packages/ai-parrot/src/parrot/knowledge/wiki/tools.py)
# BEFORE — insert above `def create_bulk_tools(`
SYNC_PULL_MAX = 2000


class SyncPagesInput(BaseModel):
    """Authored knowledge crossing the wire (push payload / pull result)."""
    pages: list[WikiPageRecord] = Field(default_factory=list)
    edges: list[tuple[str, str, str, str]] = Field(default_factory=list)
    since: str | None = None
    skip_asserted_by: str | None = None
    limit: int = Field(default=500, ge=1, le=SYNC_PULL_MAX)
    cursor: str | None = None


class WikiSyncPushTool(AbstractTool):
    """Merge memory pages + asserted edges pushed by `wikitoolkit sync push` (remote mode) with last-write-wins. Not for agents."""
    name = "wiki_sync_push"

    def __init__(self, store: BaseWikiStore, wiki_name: str):
        super().__init__()
        self._store, self._wiki_name = store, wiki_name

    async def _execute(self, pages: list[WikiPageRecord], edges: list[tuple[str, str, str, str]] | None = None) -> ToolResult:
        import tempfile
        from parrot.knowledge.wiki.file_store import InMemoryWikiStore
        from parrot.knowledge.wiki.sync import _sync_records
        with tempfile.TemporaryDirectory() as bundle:
            mem = InMemoryWikiStore(bundle, wiki_name=self._wiki_name)
            await mem.upsert_pages(pages)
            if edges:
                await mem.add_edges(edges)
            report, _ids = await _sync_records(source=mem, destination=self._store, direction="push",
                                               env=self._wiki_name, dry_run=False, skip_asserted_by=None)
        # FILL IN: return ToolResult(result=<report as dict>) — read SyncReport (sync.py:59-83) for the field names
        raise NotImplementedError


class WikiSyncPullTool(AbstractTool):
    """Return this plane's memory pages (+ asserted edges) newer than `since`, paginated. Used by `wikitoolkit sync pull`. Not for agents."""
    name = "wiki_sync_pull"

    def __init__(self, store: BaseWikiStore):
        super().__init__()
        self._store = store

    async def _execute(self, since: str | None = None, skip_asserted_by: str | None = None, limit: int = 500,
                       cursor: str | None = None) -> ToolResult:
        from parrot.knowledge.wiki.sync import _synced_memory_pages
        limit = max(1, min(limit, SYNC_PULL_MAX))
        pages = await _synced_memory_pages(self._store)
        # FILL IN: filter updated_at > since (None sorts oldest), drop asserted_by == skip_asserted_by, sort by (updated_at or "", concept_id),
        #          apply cursor ("<updated_at>|<concept_id>" → keep strictly greater), take `limit`, compute next_cursor,
        #          collect asserted edges touching the returned ids via store.neighbors or dump_edges — bounded by AC11 and S9 (no tombstones)
        raise NotImplementedError

# EXTEND create_bulk_tools()'s return (added by TASK-3356) to:
    return [WikiPageHashesTool(store), WikiIngestBatchTool(store, root, config), WikiSyncPushTool(store, config.wiki_name), WikiSyncPullTool(store)]
```
**Why this shape**: reusing `_sync_records` guarantees the same LWW/note-merge semantics as today's `sync push` (sync.py:221-269); the in-memory source store is the only adapter needed. Pull pagination is the design-research S9 outcome; tombstones are deliberately absent.

### FILL IN checklist
- [ ] `WikiSyncPushTool` result shape from `SyncReport` fields.
- [ ] `WikiSyncPullTool` filter/sort/cursor/edges — bounded by AC11, S9.
- [ ] Docstring of `create_bulk_tools` lists the four tools.

---

## Acceptance Criteria

- [ ] Push of a page with `updated_at` older than the server's copy leaves the server's body unchanged; a newer one replaces it (LWW).
- [ ] Push carries asserted edges (`add_edges` 4-tuples) into the destination.
- [ ] Pull over 1200 memory pages with `limit=500` returns 500/500/200 across three calls with stable cursors and `next_cursor is None` on the last.
- [ ] Pull excludes `skip_asserted_by` and respects `since`.
- [ ] `create_bulk_tools()` returns 4 tools; `create_wiki_tools()` unchanged.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py
import pytest
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.tools import WikiSyncPullTool, WikiSyncPushTool, create_bulk_tools


def _mem(cid, body, ts, by="human:a"):
    return WikiPageRecord(concept_id=cid, title=cid, body=body, origin="memory", asserted_by=by, updated_at=ts)


@pytest.fixture
def store(tmp_path):
    (tmp_path / "w").mkdir()
    return create_wiki_store(tmp_path / "w", wiki_name="t", backend="sqlite")


async def test_push_is_lww(store):
    await store.upsert_pages([_mem("memory:x", "server-new", "2026-02-01T00:00:00+00:00")])
    tool = WikiSyncPushTool(store, "t")
    await tool._execute(pages=[_mem("memory:x", "client-old", "2026-01-01T00:00:00+00:00")])
    assert (await store.get_page("memory:x"))["body"] == "server-new"
    await tool._execute(pages=[_mem("memory:x", "client-newer", "2026-03-01T00:00:00+00:00")])
    assert (await store.get_page("memory:x"))["body"] == "client-newer"


async def test_pull_paginates(store, tmp_path):
    await store.upsert_pages([_mem(f"memory:p{i:04d}", "b", f"2026-01-01T00:{i//60:02d}:{i%60:02d}+00:00") for i in range(1200)])
    tool = WikiSyncPullTool(store)
    seen, cursor = 0, None
    for expected in (500, 500, 200):
        res = (await tool._execute(limit=500, cursor=cursor)).result
        assert len(res["pages"]) == expected; seen += expected; cursor = res["next_cursor"]
    assert cursor is None and seen == 1200
    assert len(create_bulk_tools(store, tmp_path, WikiProjectConfig(wiki_name="t"))) == 4
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3356 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `SyncReport` and `_sync_records` before implementing
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
