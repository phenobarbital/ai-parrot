# TASK-3356: Bulk tools `wiki_page_hashes` + `wiki_ingest_batch` and payload models (M5a)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3352
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, AC3, AC10, §8 Q4 (per-slice atomicity). `build`/`upsert`/
`ingest` stay local; their results reach the server through MCP. This task adds
the two server-side tools that make that possible — the delta oracle
(`wiki_page_hashes`) and the slice writer (`wiki_ingest_batch`) — plus the
Pydantic payload models the client (TASK-3363) serialises, and the
`create_bulk_tools()` factory the builder (TASK-3358) registers only in server
mode. Depends on TASK-3352 because both tasks edit `tools.py` (serialisation, not
a symbol dependency).

---

## Scope

- Models in `tools.py`: `SourceSlicePayload`, `IngestBatchInput`, `IngestBatchReport`, `PageHashesInput` (spec §2 Data Models, incl. `deleted_source_ids`, `batch_id`, `symbols_dropped`).
- `WikiPageHashesTool` (`name = "wiki_page_hashes"`, ≤2000 ids).
- `WikiIngestBatchTool` (`name = "wiki_ingest_batch"`): ≤200 slices, ≤1 MiB serialised; per slice `replace_source_slice(source_id, pages, edges)` then `upsert_symbols(symbols, source_id=source_id)`; `deleted_source_ids` → `replace_source_slice(sid, [], [])`; count `symbols_dropped` when `upsert_symbols` returns 0 for a non-empty list; everything under `wiki_write_lock`; log `batch_id` per slice via `self.logger`.
- `create_bulk_tools(store, root, config) -> list[AbstractTool]` returning these two (TASK-3357 appends the sync tools).
- Unit tests on a SQLite store in `tmp_path`.

**NOT in scope**: sync tools (TASK-3357), the client-side chunking/hash diff (TASK-3363), registering in the builder (TASK-3358).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | payload models, two tools, `create_bulk_tools()` |
| `packages/ai-parrot/tests/knowledge/wiki/test_bulk_tools.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already at the top of tools.py (:10-22): asyncio, hashlib, datetime/UTC, Path, TYPE_CHECKING/Union, BaseModel/Field,
#   WikiBookkeeper, DEFAULT_BUDGET_TOKENS/pack_results, WikiProjectConfig, BaseWikiStore/WikiPageRecord/estimate_tokens, AbstractTool/ToolResult
from parrot.knowledge.wiki.actor import current_actor                 # added by TASK-3352 (tools.py, below the WikiBookkeeper import)
from parrot.knowledge.wiki.symbols import SymbolRecord                 # symbols.py:56 — NOT yet imported in tools.py (add)
from parrot.knowledge.wiki.project import wiki_write_lock              # project.py:71-131 — NOT yet imported in tools.py (extend the existing project import)
import json                                                            # stdlib — for the 1 MiB size check
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiPageRecord(BaseModel)                                                                  # :409-455
async def BaseWikiStore.replace_source_slice(self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]   # :550-555 → {"pages_deleted","pages_written","edges_written"}
async def BaseWikiStore.upsert_symbols(self, symbols: list[SymbolRecord], source_id: Optional[str] = None) -> int   # :687-705 (default returns 0 → "dropped")
async def BaseWikiStore.page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]    # :803
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def wiki_write_lock(...)                                                                          # :71-131 — read its exact parameters (storage dir / timeout) before use
# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
class WikiStatusTool(AbstractTool): name = "wiki_status"; def __init__(self, store); async def _execute(self) -> ToolResult   # :466-479 — the minimal tool pattern to copy
def create_wiki_tools(store, root=None, config=None, ledger_service=None) -> list[AbstractTool]   # :741 (anchor `^def create_wiki_tools(` 1 occurrence)
# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult: ToolResult(result=...) / ToolResult(success=False, status="error", result=None, error=str(exc))   # usage pattern tools.py:~9-30
```

### Does NOT Exist
- ~~`wiki_page_hashes` / `wiki_ingest_batch` tools~~, ~~`create_bulk_tools`~~, ~~`SourceSlicePayload`~~ — created here.
- ~~`BaseWikiStore.delete_source(...)`~~ — deletion is `replace_source_slice(sid, [], [])` (SQLite impl deletes the old slice, store.py:1557-1562; Arango :599).
- ~~`BaseWikiStore.upsert_symbols(..., replace=True)`~~ — no such kwarg; slice semantics come from `source_id`.
- ~~a store-level transaction API~~ — none; atomicity is per slice (§8 Q4).
- ~~`ToolResult.json()`~~ — build plain dicts for `result`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_bulk_tools.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#create_wiki_tools",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiStatusTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.replace_source_slice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.upsert_symbols",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.page_hashes",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#wiki_write_lock"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Limits are constants: `INGEST_MAX_SLICES = 200`, `INGEST_MAX_BYTES = 1_048_576`, `HASHES_MAX_IDS = 2000`; violating them returns `ToolResult(success=False, error=...)` — never raise.
- The tool docstrings ARE the MCP descriptions: say plainly they are for the `wikitoolkit` CLI's build push, not for agents.
- `WikiStoreBusy` → `ToolResult(success=False, error=f"busy: {exc}")` so the client can retry once (spec §7 Patterns).
- Size check: `len(json.dumps([s.model_dump(mode="json") for s in slices]).encode())`.

---

## Implementation Blueprint

### Steps (in order)
1. Extend imports (`json`, `SymbolRecord`, `wiki_write_lock`) — *why*: the blueprint may not introduce unlisted symbols.
2. Insert models + two tools + factory **before** `def create_wiki_tools(` — *why*: single unique anchor; keeps `create_wiki_tools` last in the module as today.
3. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def create_wiki_tools(' packages/ai-parrot/src/parrot/knowledge/wiki/tools.py)
# BEFORE — insert above `def create_wiki_tools(` (verified: tools.py:741)
INGEST_MAX_SLICES = 200
INGEST_MAX_BYTES = 1_048_576
HASHES_MAX_IDS = 2000


class SourceSlicePayload(BaseModel):
    """One `replace_source_slice` unit crossing the wire (FEAT-569)."""
    source_id: str
    pages: list[WikiPageRecord] = Field(default_factory=list)
    edges: list[tuple[str, str, str]] = Field(default_factory=list)
    symbols: list[SymbolRecord] = Field(default_factory=list)


class IngestBatchReport(BaseModel):
    """Outcome of one `wiki_ingest_batch` call."""
    slices_applied: int = 0
    slices_deleted: int = 0
    pages_written: int = 0
    edges_written: int = 0
    symbols_written: int = 0
    symbols_dropped: int = 0
    rejected: list[str] = Field(default_factory=list)


class WikiPageHashesTool(AbstractTool):
    """Return the stored content hash for up to 2000 page ids (delta oracle for `wikitoolkit build` pushes; not for agents)."""
    name = "wiki_page_hashes"

    def __init__(self, store: BaseWikiStore):
        super().__init__()
        self._store = store

    async def _execute(self, concept_ids: list[str]) -> ToolResult:
        if len(concept_ids) > HASHES_MAX_IDS:
            return ToolResult(success=False, status="error", result=None, error=f"at most {HASHES_MAX_IDS} ids per call")
        return ToolResult(result={"hashes": await self._store.page_hashes(concept_ids)})


class WikiIngestBatchTool(AbstractTool):
    """Apply source slices pushed by `wikitoolkit build/upsert/ingest` in remote mode (≤200 slices, ≤1 MiB). Not for agents."""
    name = "wiki_ingest_batch"

    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig):
        super().__init__()
        self._store, self._root, self._config = store, root, config

    async def _execute(self, slices: list[SourceSlicePayload], deleted_source_ids: list[str] | None = None,
                       batch_id: str | None = None) -> ToolResult:
        deleted_source_ids = deleted_source_ids or []
        if len(slices) > INGEST_MAX_SLICES or len(deleted_source_ids) > INGEST_MAX_SLICES:
            return ToolResult(success=False, status="error", result=None, error=f"at most {INGEST_MAX_SLICES} slices per call")
        if len(json.dumps([s.model_dump(mode="json") for s in slices]).encode()) > INGEST_MAX_BYTES:
            return ToolResult(success=False, status="error", result=None, error="payload too large (max 1 MiB)")
        report = IngestBatchReport()
        # FILL IN: `with wiki_write_lock(<args per project.py:71-131>):` then for each slice:
        #   r = await self._store.replace_source_slice(s.source_id, s.pages, s.edges); accumulate pages/edges_written
        #   n = await self._store.upsert_symbols(s.symbols, source_id=s.source_id); symbols_written += n; if s.symbols and n == 0: symbols_dropped += len(s.symbols)
        #   self.logger.info("ingest_batch %s applied %s", batch_id, s.source_id)
        #   for sid in deleted_source_ids: await self._store.replace_source_slice(sid, [], []); slices_deleted += 1
        #   WikiStoreBusy → ToolResult(success=False, ..., error=f"busy: {exc}")  — bounded by AC10 and §8 Q4 (per-slice atomicity, no cross-slice rollback)
        return ToolResult(result=report.model_dump())


def create_bulk_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> list[AbstractTool]:
    """Server-only tools that move data for the CLI (registered by `build_wiki_tools(include_bulk_tools=True)`)."""
    return [WikiPageHashesTool(store), WikiIngestBatchTool(store, root, config)]


```
**Why this shape**: the spec fixes names, limits and the per-slice sequence (replace slice → upsert symbols); `symbols_dropped` is how AC5/AC10 detect a backend without a symbol plane until TASK-3355 lands on ArangoDB. `WikiStoreBusy` is imported where `wiki_write_lock` is (check `store.py:264`).

### FILL IN checklist
- [ ] `wiki_write_lock` call arguments — read project.py:71-131 (storage dir from `config.storage_path(root)`, timeout from `config.sqlite_busy_timeout`).
- [ ] The loop body incl. `WikiStoreBusy` mapping — bounded by AC10.
- [ ] Extend the existing `from parrot.knowledge.wiki.project import WikiProjectConfig` line to also import `wiki_write_lock`.

---

## Acceptance Criteria

- [ ] `wiki_page_hashes` returns `{"hashes": {...}}` with `None` for unknown ids; 2001 ids → `success=False`.
- [ ] `wiki_ingest_batch` with 2 slices writes pages+edges+symbols to a SQLite store (`symbols_for` returns them; `symbols_dropped == 0`); `deleted_source_ids=["file:gone.py"]` removes that slice's pages (`list_pages` no longer shows them) and `slices_deleted == 1`.
- [ ] 201 slices → error; a slice batch > 1 MiB → error `payload too large`; no partial write in either case (validated before the lock).
- [ ] On a store whose `upsert_symbols` returns 0 (stub), `symbols_dropped == len(symbols)`.
- [ ] `create_bulk_tools()` returns exactly two tools named `wiki_page_hashes`, `wiki_ingest_batch`; `create_wiki_tools()` output is unchanged (14 tools with ledger).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_bulk_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_bulk_tools.py
import pytest
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord
from parrot.knowledge.wiki.tools import SourceSlicePayload, WikiIngestBatchTool, WikiPageHashesTool, create_bulk_tools


@pytest.fixture
def plane(tmp_path):
    (tmp_path / ".parrot" / "wiki").mkdir(parents=True)
    store = create_wiki_store(tmp_path / ".parrot" / "wiki", wiki_name="t", backend="sqlite")
    return tmp_path, store, WikiProjectConfig(wiki_name="t")


def _slice(path="pkg/a.py"):
    page = WikiPageRecord(concept_id=f"file:{path}", title=path, body="x", source_id=f"file:{path}", content_hash="h1")
    sym = SymbolRecord(rel_path=path, language="python", kind=SymbolKind.FUNCTION, name="f", qualname="f",
                       start_line=1, end_line=1, start_byte=0, end_byte=1)   # FILL IN: required fields
    return SourceSlicePayload(source_id=f"file:{path}", pages=[page], symbols=[sym])


async def test_ingest_then_hashes_then_delete(plane):
    root, store, cfg = plane
    tool = WikiIngestBatchTool(store, root, cfg)
    res = await tool._execute(slices=[_slice(), _slice("pkg/b.py")], batch_id="b1")
    assert res.result["slices_applied"] == 2 and res.result["symbols_dropped"] == 0
    assert (await store.symbols_for("pkg/a.py"))[0].qualname == "f"
    hashes = (await WikiPageHashesTool(store)._execute(["file:pkg/a.py", "file:nope"])).result["hashes"]
    assert hashes == {"file:pkg/a.py": "h1", "file:nope": None}
    res = await tool._execute(slices=[], deleted_source_ids=["file:pkg/b.py"])
    assert res.result["slices_deleted"] == 1 and await store.get_page("file:pkg/b.py") is None


async def test_limits(plane):
    root, store, cfg = plane
    tool = WikiIngestBatchTool(store, root, cfg)
    assert (await tool._execute(slices=[_slice(f"p/{i}.py") for i in range(201)])).success is False
    assert len(create_bulk_tools(store, root, cfg)) == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3352 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `def create_wiki_tools(` is still the unique anchor and `wiki_write_lock`'s parameters
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
