# TASK-3353: `StructuralService(read_repair=False)` rootless mode (M2b)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (structural part), AC5, design research S1. `StructuralService`
hashes files under `root`, re-scans stale ones (`_ensure_fresh`) and reads
source bytes for `include_source` excerpts. The remote server has **no source
tree**, so the service must run in a store-only mode: no disk hashing, no
read-repair, no excerpts — outlines and lookups come from the persisted symbol
plane only. This task adds the `read_repair` flag to the service and to
`create_structural_tools()`; TASK-3358 passes `read_repair=False` from the
server-side builder.

---

## Scope

- `StructuralService.__init__(..., *, read_repair: bool = True)`; store on `self._read_repair`.
- `_ensure_fresh()` returns `[]` immediately when `read_repair` is off (no `_disk_hash`, no `_ingest_files`, no lock).
- `_read_source_excerpt()` returns `(None, False)` when `read_repair` is off (no `read_bytes`).
- `create_structural_tools(store, root, config, *, read_repair: bool = True)` threads the flag into BOTH `StructuralService(...)` constructions (local and per-namespace).
- Tests proving no filesystem access happens in rootless mode.

**NOT in scope**: builder wiring (TASK-3358), ArangoDB symbol methods (TASK-3355).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` | MODIFY | ctor flag; guards in `_ensure_fresh` / `_read_source_excerpt` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` | MODIFY | `read_repair` kwarg threaded to both service constructions |
| `packages/ai-parrot/tests/knowledge/wiki/test_structural_read_repair.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.structural.service import StructuralService          # service.py:~110
from parrot.knowledge.wiki.structural.tools import create_structural_tools      # tools.py:225
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store         # store.py:525, :2247
from parrot.knowledge.wiki.symbols import SymbolRecord, SymbolKind, sym_concept_id, parse_sym_id   # symbols.py:56, :141, :159
from parrot.knowledge.wiki.project import WikiProjectConfig                       # project.py:379
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py
class StructuralService:
    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> None:   # :127 (anchor, 1 occurrence)
        self._store = store; self._root = root.resolve(); self._config = config
        self._sources = _open_sources(self._root, config, store=store)                         # :131
        self._lock_busy = False                                                                 # :132
    async def outline(self, target: str, ..., include_source: bool = ...)                       # :218 — calls `await self._ensure_fresh([rel_path])` (:~243, 1 occurrence) then `self._store.symbols_for(rel_path)`
    def _read_source_excerpt(self, sym_id: str, records: list[SymbolRecord]) -> tuple[str | None, bool]   # :258-285; first statement `try: _rel, qualname, _ordinal = parse_sym_id(sym_id)` (parse_sym_id(sym_id) occurs 1×); reads (self._root / record.rel_path).read_bytes() at :276
    def _disk_hash(self, rel_path: str) -> str | None                                           # :417 — read_bytes() at :420
    async def _ensure_fresh(self, rel_paths: list[str]) -> list[str]                            # :425 (anchor, 1 occurrence); first statements: `self._lock_busy = False` / `if not rel_paths: return []`
# packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py
def create_structural_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> list[AbstractTool]:   # :225-263 (anchor `^def create_structural_tools(` 1×)
    local_service = StructuralService(store, root, config)                  # :244 (1 occurrence)
    def service_factory(namespace: str | None) -> StructuralService: ...
        return StructuralService(scoped, root, config)                      # :257 (1 occurrence)
```

### Does NOT Exist
- ~~`StructuralService.read_repair`~~ (public attribute) — store it as `self._read_repair`; expose nothing new publicly.
- ~~`StructuralService(store, config)`~~ — `root` stays a required positional even in rootless mode (it is the wiki dir on the server); do not make it optional.
- ~~`create_structural_tools(..., server_mode=...)`~~ — the flag is named `read_repair`, nothing else.
- ~~`WikiCodeOutlineTool(read_repair=...)`~~ — tools take only `service_factory`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_structural_read_repair.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService._ensure_fresh",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService._read_source_excerpt",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py#create_structural_tools"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keyword-only flag, default `True` → every existing caller (`cli._structural_tool`, `mcp_server`) is byte-identical (AC14).
- `_open_sources(...)` is still constructed in rootless mode (lookups need the manifest for the ArangoDB path); only the two disk-touching paths are guarded.
- Prove "no disk access" in tests by pointing `root` at an empty `tmp_path` while the store holds symbols for `pkg/mod.py`: with `read_repair=False` the outline must still return those symbols; with the default it may prune them (that is today's behaviour).

---

## Implementation Blueprint

### Steps (in order)
1. Extend `__init__` with the keyword-only flag — *why*: the flag must exist before the guards reference it.
2. Guard `_ensure_fresh` — *why*: it is the only path that hashes disk files and rewrites the plane.
3. Guard `_read_source_excerpt` — *why*: the only other `read_bytes()` caller reachable from a tool (`_disk_hash` is only reached through `_ensure_fresh`).
4. Thread the flag through `create_structural_tools` (both constructions) — *why*: the builder (TASK-3358) can only reach the service through this factory.
5. Tests; `ruff check` both files.

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` (MODIFY — block 1)
```python
# occurrences: 1 (verified: grep -c '    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> None:' packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py)
# REPLACE the signature line (verified: service.py:127) with:
    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig, *, read_repair: bool = True) -> None:
# AFTER — insert below `        self._lock_busy = False` INSIDE __init__ only (service.py:132; the same line also appears at :437 inside _ensure_fresh — do NOT touch that one):
        self._read_repair = read_repair
```
**Why**: rootless mode is a construction-time property of the service (the server never has a tree); add `read_repair:` to the class docstring Args.

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` (MODIFY — block 2)
```python
# occurrences: 1 (verified: grep -c '    async def _ensure_fresh(self, rel_paths: list\[str\]) -> list\[str\]:' service.py)
# AFTER the docstring of `_ensure_fresh` (verified: service.py:425-436) — insert as the FIRST statement:
        if not self._read_repair:
            self._lock_busy = False
            return []
```
**Why**: returning `[]` is the documented "nothing was stale" value (docstring :431-434), so `outline()`/`blast_radius()` proceed to `symbols_for()` unchanged and never touch `_disk_hash` or the writer lock.

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` (MODIFY — block 3)
```python
# occurrences: 1 (verified: grep -c 'parse_sym_id(sym_id)' service.py)
# BEFORE — insert above the `try:` that wraps `_rel, qualname, _ordinal = parse_sym_id(sym_id)` (verified: service.py:~268), as the first statement of _read_source_excerpt:
        if not self._read_repair:
            return None, False
```
**Why**: `(None, False)` is the existing "no excerpt, not truncated" return (service.py:271, :281), so `outline(include_source=True)` renders `source=None` exactly as it does when the file is missing today (AC5).

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def create_structural_tools(' packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py)
# REPLACE the signature (tools.py:225-229) with:
def create_structural_tools(
    store: BaseWikiStore,
    root: Path,
    config: WikiProjectConfig,
    *,
    read_repair: bool = True,
) -> list[AbstractTool]:
# occurrences: 1 (verified: grep -c '    local_service = StructuralService(store, root, config)' tools.py) — REPLACE with:
    local_service = StructuralService(store, root, config, read_repair=read_repair)
# occurrences: 1 (verified: grep -c '        return StructuralService(scoped, root, config)' tools.py) — REPLACE with:
        return StructuralService(scoped, root, config, read_repair=read_repair)
```
**Why**: both constructions must honour the flag or a `--ns`-scoped call on the server would silently re-enable disk access. Add `read_repair:` to the docstring Args.

### FILL IN checklist
- [ ] `service.py` class docstring + `create_structural_tools` docstring Args updated — bounded by Google style.
- [ ] Test asserts no `read_bytes` call via `monkeypatch.setattr(Path, "read_bytes", boom)` in rootless mode — bounded by AC5.

---

## Acceptance Criteria

- [ ] `StructuralService(store, tmp_path, cfg, read_repair=False).outline("file:pkg/mod.py")` returns the stored symbols although `tmp_path/pkg/mod.py` does not exist; `Path.read_bytes` is never called (monkeypatched to raise).
- [ ] `outline("sym:pkg/mod.py#f", include_source=True)` in rootless mode → `source is None`, `truncated is False`.
- [ ] Default `read_repair=True` behaviour unchanged: existing `tests/knowledge/wiki/test_mcp_server_structural.py` and `test_structural_*` pass.
- [ ] `create_structural_tools(..., read_repair=False)` yields tools whose service has `_read_repair is False` for both the local and a namespace-scoped factory call.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_structural_read_repair.py -q`
- `pytest tests/knowledge/wiki/test_mcp_server_structural.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_structural_read_repair.py
from pathlib import Path
import pytest
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import create_wiki_store
from parrot.knowledge.wiki.structural.service import StructuralService
from parrot.knowledge.wiki.structural.tools import create_structural_tools
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord


@pytest.fixture
async def seeded(tmp_path):
    (tmp_path / ".parrot" / "wiki").mkdir(parents=True)
    store = create_wiki_store(tmp_path / ".parrot" / "wiki", wiki_name="t", backend="sqlite")
    rec = SymbolRecord(rel_path="pkg/mod.py", language="python", kind=SymbolKind.FUNCTION, name="f", qualname="f",
                       start_line=1, end_line=2, start_byte=0, end_byte=10)   # FILL IN: any required fields the model enforces
    await store.upsert_symbols([rec], source_id="file:pkg/mod.py")
    return store


async def test_rootless_outline_never_touches_disk(seeded, tmp_path, monkeypatch):
    def boom(self): raise AssertionError("disk access in rootless mode")
    monkeypatch.setattr(Path, "read_bytes", boom)
    svc = StructuralService(seeded, tmp_path, WikiProjectConfig(wiki_name="t"), read_repair=False)
    out = await svc.outline("file:pkg/mod.py")
    assert [s.qualname for s in out.symbols] == ["f"]
    out2 = await svc.outline("sym:pkg/mod.py#f", include_source=True)
    assert out2.source is None and out2.truncated is False


def test_factory_threads_flag(seeded, tmp_path):
    tools = create_structural_tools(seeded, tmp_path, WikiProjectConfig(wiki_name="t"), read_repair=False)
    assert tools[0]._service_factory(None)._read_repair is False   # FILL IN: use the real attribute name holding service_factory (structural/tools.py:110-200)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm anchors (`__init__` line :127, `_ensure_fresh` :425, `parse_sym_id(sym_id)` 1×, both `StructuralService(` constructions in tools.py)
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
