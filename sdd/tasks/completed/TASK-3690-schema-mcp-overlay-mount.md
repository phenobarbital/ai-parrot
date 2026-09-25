# TASK-3690: Mount the `schema` overlay namespace and register `wiki_schema_*` tools in `create_wiki_mcp_server`

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3689
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (mount half). Copies the ledger block (mcp_server.py:154-201): initialise `SchemaPlaneService.from_root(root)` only when `find_shared_root(root)` is not None AND `config.schema.enabled` AND the plane dir already exists (never create `.parrot/schema/` from a bare test dir — that would change tool counts, the same reason the ledger guard exists); wrap the open store in a read-only `NamespaceHandle(name="schema", overlay_prefixes=["source","schema","table"])`; append `create_schema_tools(...)` after the decision tools. Also adds the two-overlay federation regression test (brainstorm spike 2, AC6).

---

## Scope

- Modify `mcp_server.py`: schema service init + handle append (after the ledger block, before `if handles or skipped:`) and tool registration (after `tools = tools + decision_tools`).
- Write `test_mcp_mount.py`: no plane → no `schema` handle, tool count unchanged; plane present → handle + exactly four tools; two overlays (ledger + schema) → `wiki_related` hydrates `table:` ↔ `sym:` both ways.

**NOT in scope**: Tool implementations (TASK-3689), remote/HTTP server (FEAT-569 `serve.py`), CLI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | schema overlay + tools |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_mcp_mount.py` | CREATE | mount + two-overlay tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server          # verified: packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py (ledger block :154-201)
from parrot.knowledge.wiki.project import WikiNamespaceConfig, find_shared_root   # verified: project.py:183, :1197
from parrot.knowledge.wiki.federation import NamespaceHandle, FederatedWikiStore  # verified: federation.py:96 (@dataclass), :638
from parrot.knowledge.wiki.schema.service import SchemaPlaneService              # TASK-3684
from parrot.knowledge.wiki.schema.tools import create_schema_tools               # TASK-3689
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py — create_wiki_mcp_server
#   :154-171  ledger_service = None; with contextlib.redirect_stdout(sys.stderr): from …project import find_shared_root; if find_shared_root(root) is not None: try: LedgerService.from_root(root) except Exception: warning
#   :178      if ledger_service is not None:                       ← schema block goes AFTER this block's end (:198)
#   :184-197  ledger_config = WikiNamespaceConfig(store=str(ledger_dir), description=…, weight=0.5, overlay_prefixes=[…]); handles.append(NamespaceHandle(name="ledger", store=ledger_service.store, config=ledger_config, storage_dir=ledger_dir, read_only=True))
#   :200-201  if handles or skipped: read_store = FederatedWikiStore(store, config.wiki_name, handles, skipped)
#   :226      tools = tools + decision_tools                       ← append schema tools AFTER
# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:95-105 @dataclass NamespaceHandle(name, store, config, origin, storage_dir, read_only)
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:183 WikiNamespaceConfig(store=…, description=…, weight=…, overlay_prefixes=[…]) — exactly one of path/store/database/vault
# TASK-3684: SchemaPlaneService.from_root(root); .store; .plane_dir; .config.enabled
```

### Does NOT Exist
- ~~`build_wiki_tools()` / `WikiToolBundle`~~ — FEAT-569 TASK-3358, not merged; append to `tools` like the structural/decision blocks do
- ~~a `schema` namespace in `.parrot/wiki.json` `namespaces`~~ — the handle is built in code, `store=` is set only to satisfy the validator (same as ledger)
- ~~auto-creating `.parrot/schema/`~~ — mount only when the dir already exists (AC11)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_mcp_mount.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#create_wiki_mcp_server",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#NamespaceHandle",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiNamespaceConfig"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
mcp_server.py:154-201 (ledger init + mount) and :223-226 (decision tools append). Test pattern: `tests/knowledge/wiki/test_ledger_integration.py::_federated` and `test_federation_overlay.py`.

### Key Constraints
- All new imports inside `contextlib.redirect_stdout(sys.stderr)` (navconfig stdout leak, spec §7).
- Guard: `find_shared_root(root) is not None and config.schema.enabled and config.schema_path(shared_root).exists()`.
- Tool count unchanged when no plane (AC11).

### References in Codebase
- packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py:154-226
- tests/knowledge/wiki/test_ledger_integration.py
- tests/knowledge/wiki/test_federation_overlay.py

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Insert the schema init+mount block after the ledger `if` block (before :200 `if handles or skipped:`) — why: handles must exist before `FederatedWikiStore` is built.
2. Append `create_schema_tools(read_store, root, config, schema_service)` after :226 — why: same read_store, same federation.
3. Write mount tests and the two-overlay `wiki_related` test — why: AC6/AC11; the brainstorm's spike 2 becomes a regression test.

### `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    if handles or skipped:' packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py) → mcp_server.py:200
# BEFORE — insert ABOVE `    if handles or skipped:` (i.e. after the ledger mount block that starts at :178):
    # FEAT-600: mount the SQL schema plane as a read-only overlay (same shape as the ledger block above).
    # Mount only when a plane already exists — never grow `.parrot/schema/` from a bare directory (tool counts, AC11).
    schema_service = None
    with contextlib.redirect_stdout(sys.stderr):
        shared_root = find_shared_root(root)
        if shared_root is not None and config.schema.enabled and config.schema_path(shared_root).exists():
            try:
                from parrot.knowledge.wiki.schema.service import SchemaPlaneService

                schema_service = SchemaPlaneService.from_root(root)
            except Exception as exc:  # noqa: BLE001 — the plane is optional
                logging.getLogger(__name__).warning("Could not initialize schema plane: %s", exc)
    if schema_service is not None:
        with contextlib.redirect_stdout(sys.stderr):
            from parrot.knowledge.wiki.federation import NamespaceHandle
            from parrot.knowledge.wiki.project import WikiNamespaceConfig

            schema_dir = schema_service.plane_dir
            schema_config = WikiNamespaceConfig(
                store=str(schema_dir),
                description="SQL schema plane (sources, schemas, tables)",
                weight=0.5,
                overlay_prefixes=["source", "schema", "table"],
            )
            handles.append(NamespaceHandle(name="schema", store=schema_service.store, config=schema_config,
                                           storage_dir=schema_dir, read_only=True))

# occurrences: 1 (verified: grep -c '    tools = tools + decision_tools' …/mcp_server.py) → mcp_server.py:226
# AFTER — insert below:
    # FEAT-600: schema-plane tools share read_store; [] when no plane is mounted (AC11).
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.knowledge.wiki.schema.tools import create_schema_tools

        schema_tools = create_schema_tools(read_store, root, config, schema_service)
    tools = tools + schema_tools
```
**Why**: Verbatim copy of the ledger mount and the decision-tools append: federation routes bare `table:` ids to this overlay (federation.py:917) and hydrates cross-kind neighbors (:976-1059) with no new read path.

### FILL IN checklist
- [ ] `test_mcp_mount.py`: bare tmp dir → no `schema` handle, same tool names as before; git-backed tmp root with `.parrot/schema/schema.db` → handle + 4 tools
- [ ] two-overlay test: ledger + schema handles on one `FederatedWikiStore`; add `table:x/a.b --references--> table:x/a.c` and `sym:m.py#Model --maps_to--> table:x/a.b` in the right stores; assert `neighbors('sym:m.py#Model')` and `neighbors('table:x/a.b')` both hydrate (AC6)

---

## Acceptance Criteria

- [ ] no plane → no `schema` namespace, tool list identical to before this task (AC11)
- [ ] plane present → `schema` handle mounted read-only with prefixes source/schema/table and exactly four `wiki_schema_*` tools (AC11)
- [ ] two-overlay `wiki_related` hydration works both directions (AC6)
- [ ] existing `tests/knowledge/wiki/test_ledger_integration.py` and `test_federation_overlay.py` green
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_mcp_mount.py -q`
- `pytest tests/knowledge/wiki/test_ledger_integration.py -q`
- `pytest tests/knowledge/wiki/test_federation_overlay.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_mcp_mount.py
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle
from parrot.knowledge.wiki.project import WikiNamespaceConfig
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.schema.store import SchemaStore

async def test_two_overlays_cross_kind(tmp_path):
    local = SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="w")
    await local.upsert_pages([WikiPageRecord(concept_id="sym:m.py#Model", title="Model", category="symbol")])
    await local.add_edges([("sym:m.py#Model", "table:x/a.b", "maps_to")])
    schema = SchemaStore(tmp_path / "schema.db")
    await schema.upsert_pages([WikiPageRecord(concept_id="table:x/a.b", title="a.b", category="table"),
                               WikiPageRecord(concept_id="table:x/a.c", title="a.c", category="table")])
    await schema.add_edges([("table:x/a.b", "table:x/a.c", "references")])
    ledger = SQLiteWikiStore(tmp_path / "ledger.db", wiki_name="ledger")
    handles = [
        NamespaceHandle(name="ledger", store=ledger, config=WikiNamespaceConfig(store=str(tmp_path), overlay_prefixes=["issue"]), origin="repo", storage_dir=tmp_path, read_only=True),
        NamespaceHandle(name="schema", store=schema, config=WikiNamespaceConfig(store=str(tmp_path), overlay_prefixes=["source", "schema", "table"]), origin="repo", storage_dir=tmp_path, read_only=True),
    ]
    fed = FederatedWikiStore(local, "w", handles, [])
    assert any(n["concept_id"].endswith("table:x/a.b") for n in await fed.neighbors("sym:m.py#Model"))
    assert any(n["concept_id"].endswith("sym:m.py#Model") for n in await fed.neighbors("table:x/a.b"))   # FILL IN: exact id form per federation qualify rules
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3689` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
