# TASK-4308: Ledger, bulk/sync and vault operations

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4306
**Assigned-to**: unassigned

---

## Context

Spec §3 M3. Ledger tools (tools.py:829-929), bulk/sync tools (:1003-1153) and `VaultIngestTool` (:665) still hold their logic in `execute()`.

---

## Scope

- Create `wiki/ledger/operations.py` with `op_ledger_open/ready/claim/close/context` + input models (tools.py:787-824).
- Add `op_page_hashes`, `op_ingest_batch`, `op_sync_push`, `op_sync_pull`, `op_vault_ingest` + their models to `wiki/operations.py`.
- Make the matching tools in `wiki/tools.py` delegate.
- Tests: parity on tmp wiki + ledger dir.

**NOT in scope**: Moving classes to parrot_tools (TASK-4309); ledger store transaction model (FEAT-670).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py` | CREATE | ledger ops |
| `packages/ai-parrot/src/parrot/knowledge/wiki/operations.py` | MODIFY | bulk/sync/vault ops |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | delegate |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_bulk_operations.py` | CREATE | parity tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.wiki.operations import OperationResult  # TASK-4306
```

### Existing Signatures to Use
```python
# wiki/tools.py: VaultIngestTool :665; Ledger inputs :787-824; LedgerOpen/Ready/Claim/Close/ContextTool :829/:864/:885/:904/:929
#   SourceSlicePayload :954; IngestBatchInput :963; PageHashesInput :971; IngestBatchReport :977; SyncPagesInput :992
#   WikiPageHashesTool :1003; WikiIngestBatchTool :1024; WikiSyncPushTool :1098; WikiSyncPullTool :1153; create_bulk_tools :1211
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.ledger.operations` (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/operations.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_bulk_operations.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#LedgerOpenTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiIngestBatchTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#VaultIngestTool"
  ]
}
```

---

## Implementation Notes

Ledger ownership checks and actor propagation move with the op bodies. Vault ingest must keep its Obsidian-free path (the ObsidianToolkit stays framework-side in mcp_server.py).

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Ledger ops module — *why*: G4.
2. Bulk/sync/vault ops — *why*: server-only tools reuse the same logic.
3. Delegate + parity tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/operations.py` (CREATE)
```python
"""Framework-free ledger operations (FEAT-540 M3)."""
from __future__ import annotations

from typing import Any

from parrot.knowledge.wiki.operations import OperationResult

# FILL IN: move LedgerOpenInput..LedgerContextInput; op_ledger_open/ready/claim/close/context lifted from the tools
```
**Why**: Same pattern.

### `packages/ai-parrot/src/parrot/knowledge/wiki/operations.py` (MODIFY)
```python
# occurrences: n/a — wiki/operations.py is created by TASK-4306; append at module end
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# APPEND: SourceSlicePayload, IngestBatchInput, PageHashesInput, IngestBatchReport, SyncPagesInput, VaultIngestInput (moved)
# and op_page_hashes, op_ingest_batch, op_sync_push, op_sync_pull, op_vault_ingest
```
**Why**: Bulk/sync models are part of the canonical schemas.

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.abstract import AbstractTool, ToolResult' parrot/knowledge/wiki/tools.py)
# AFTER/AT — anchor `from parrot.tools.abstract import AbstractTool, ToolResult` (verified: tools.py:29)
# FILL IN: ledger/bulk/vault tools delegate to the new ops; delete moved model definitions; keep names importable via re-export
```
**Why**: Thin adapters.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_bulk_operations.py` (CREATE)
```python
"""Ledger/bulk/vault operations parity (FEAT-540 M3)."""
import pytest

# FILL IN: parity tests reusing fixtures from test_bulk_tools.py / test_sync_tools.py / ledger tests
```
**Why**: Parity against existing fixtures.

### FILL IN checklist
- [ ] ledger ops
- [ ] bulk/sync/vault ops
- [ ] delegation
- [ ] parity tests

---

## Acceptance Criteria

- [ ] existing `test_bulk_tools.py`, `test_sync_tools.py`, `test_vault_ingest_tool.py` pass
- [ ] ops modules import no `parrot.tools`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_bulk_operations.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_bulk_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4308 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: native sonnet, consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: wiki/ledger/operations.py (Ledger*Input + op_ledger_*), bulk/sync/vault ops appended to wiki/operations.py, tools.py delegating and re-exporting; 7 parity tests. Deviations reported by the coder: tools.py line numbers in the task were stale (located by symbol); wiki_write_lock imported lazily so operations.py stays free of parrot.tools; tools build params with model_construct to keep old no-new-validation behaviour. No review corrections. Verification is `partial`: the engine merge-tier sandbox cannot reach Postgres and has pre-existing reds. With GRAPHINDEX_PG_DSN on local docker-postgres-1, tests/knowledge + tests/embeddings (4286 passed) show no failure absent from the clean origin/dev baseline.

**Deviations from spec**: see Notes (stale line numbers, lazy import, model_construct)
