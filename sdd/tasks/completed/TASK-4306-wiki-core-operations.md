# TASK-4306: wiki/operations.py — framework-free core operations + shared helpers

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 M3. Business logic of the core wiki tools lives inside `AbstractTool.execute()` methods in `wiki/tools.py`, so the SDK MCP transport cannot reuse it without importing the framework. Extract plain async operations + input models + helpers.

---

## Scope

- Create `wiki/operations.py`: `OperationResult` model; move `_scoped_store` (:32), `_reject_foreign_id` (:58), `_reject_managed_page` (:88), `_qualify_ledger_target` (:123), `_unknown_namespace_error` (:147) and the input models (:166-226, `WikiLintInput` :535, `WikiStandupInput` :592) here.
- Add `op_query`, `op_page`, `op_related`, `op_remember`, `op_note`, `op_status`, `op_lint`, `op_standup` with bodies lifted from the matching `execute()`.
- `wiki/tools.py`: import helpers/models from `operations` (re-export the old names for `structural/tools.py:30`) and make each core tool's `execute()` call its op and convert `OperationResult` → `ToolResult`.
- Test: each op returns the same text/data the tool returned before, on a tmp SQLite wiki.

**NOT in scope**: ledger/bulk/vault tools (TASK-4308); moving tool classes to parrot_tools (TASK-4309); structural/decisions/schema (TASK-4307).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/operations.py` | CREATE | plain ops, helpers, input models |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | core tools delegate to operations |
| `packages/ai-parrot/tests/knowledge/wiki/test_wiki_operations.py` | CREATE | op parity tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord  # store.py:553, :433
from parrot.tools.abstract import AbstractTool, ToolResult  # wiki/tools.py:29 (stays in tools.py only)
```

### Existing Signatures to Use
```python
# wiki/tools.py: helpers :32, :58, :88, :123, :147; input models :166-226; WikiQueryTool :230 · WikiPageTool :272 · WikiRelatedTool :309
#   WikiRememberTool :341 · WikiNoteTool :448 · WikiStatusTool :519 · WikiLintInput :535 · _StorageDirConfig :544 · WikiLintTool :552
#   WikiStandupInput :592 · WikiStandupTool :605 · create_wiki_tools :1221
# structural/tools.py:30 imports _scoped_store, _unknown_namespace_error from wiki.tools
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.operations` (created here)~~
- ~~a ToolResult-free result type today~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/operations.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_wiki_operations.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiQueryTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#create_wiki_tools",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore"
  ]
}
```

---

## Implementation Notes

Operations must keep actor context, write guards, locking, ledger ownership checks, error conversion and output budgeting — those live in the execute bodies today and move with them. `operations.py` must not import `parrot.tools`.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Create `OperationResult(text, data=None, is_error=False)` — *why*: transport-neutral result both adapters map.
2. Move helpers + models — *why*: `structural/tools.py` imports them; they are framework-free.
3. Lift each core `execute()` body into an `op_*` function — *why*: one implementation for both transports (G4).
4. Make tools delegate and keep old helper names importable from `wiki.tools` — *why*: no behaviour change in this task.

### `packages/ai-parrot/src/parrot/knowledge/wiki/operations.py` (CREATE)
```python
"""Framework-free wiki operations shared by the framework tools and the SDK MCP transport (FEAT-540 M3)."""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from parrot.knowledge.wiki.store import BaseWikiStore

logger = logging.getLogger(__name__)


class OperationResult(BaseModel):
    """Transport-neutral outcome of one wiki operation."""

    text: str
    data: dict[str, Any] | None = None
    is_error: bool = False


# FILL IN: move _scoped_store, _reject_foreign_id, _reject_managed_page, _qualify_ledger_target, _unknown_namespace_error
#          and WikiQueryInput..WikiStatusInput, WikiLintInput, WikiStandupInput verbatim from wiki/tools.py


async def op_query(store: BaseWikiStore, params: "WikiQueryInput", **context: Any) -> OperationResult:
    """wiki_query — body lifted from WikiQueryTool.execute (tools.py:230)."""
    # FILL IN: verbatim logic; context carries root/config/actor the tool held as attributes
    raise NotImplementedError

# FILL IN: op_page, op_related, op_remember, op_note, op_status, op_lint, op_standup — same pattern
```
**Why**: `**context` replaces tool instance attributes so ops stay plain functions; keep the exact text the tools produced (golden manifests compare it).

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.abstract import AbstractTool, ToolResult' parrot/knowledge/wiki/tools.py)
# AFTER/AT — anchor `from parrot.tools.abstract import AbstractTool, ToolResult` (verified: tools.py:29)
# KEEP this import; ADD below it:
from parrot.knowledge.wiki.operations import (  # noqa: F401 — re-exported for structural/tools.py until TASK-4307
    OperationResult, _scoped_store, _unknown_namespace_error, _reject_foreign_id, _reject_managed_page, _qualify_ledger_target,
    op_lint, op_note, op_page, op_query, op_related, op_remember, op_standup, op_status,
)
# FILL IN: delete the moved helper/model definitions here; each core tool's execute() becomes
#   result = await op_query(self.store, params, **self._op_context()); return _to_tool_result(result)
# with one private _to_tool_result(OperationResult) -> ToolResult mapping (status/is_error, content, metadata)
```
**Why**: Tools become thin adapters; nothing observable changes in this task.

### `packages/ai-parrot/tests/knowledge/wiki/test_wiki_operations.py` (CREATE)
```python
"""Core wiki operations parity with the tools (FEAT-540 M3)."""
import pytest

from parrot.knowledge.wiki.operations import OperationResult, op_query


@pytest.mark.asyncio
async def test_op_query_matches_tool(tmp_path) -> None:
    # FILL IN: SQLite wiki with two pages; compare op_query(...).text with WikiQueryTool(...).execute(...) content
    ...


def test_operations_module_is_framework_free() -> None:
    # FILL IN: run_import_probe('parrot.knowledge.wiki.operations'); assert 'parrot.tools.abstract' not loaded
    ...
```
**Why**: Parity proves the lift is behaviour-preserving.

### FILL IN checklist
- [ ] helpers/models moved verbatim
- [ ] eight `op_*` bodies
- [ ] `_to_tool_result` mapping
- [ ] parity tests for every op

---

## Acceptance Criteria

- [ ] `wiki/operations.py` imports no `parrot.tools`
- [ ] core tools delegate to ops; their outputs are unchanged (existing `test_wiki_tools.py` passes)
- [ ] `structural/tools.py` still imports its helpers

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_operations.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4306 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: native sonnet, consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: wiki/operations.py holds OperationResult, the moved helpers/input models and the eight op_* functions; wiki/tools.py re-exports them so old imports keep working; 11 parity tests. Coder noted op_query returns an unknown-namespace message as plain text (is_error unset) to match the old tool, and that WikiProjectConfig is a TYPE_CHECKING-only import to keep operations.py free of parrot.tools. Verification is `partial`: the engine merge-tier sandbox cannot reach Postgres and has pre-existing reds. With GRAPHINDEX_PG_DSN on local docker-postgres-1, tests/knowledge + tests/embeddings show no failure absent from the clean origin/dev baseline.

**Deviations from spec**: none
