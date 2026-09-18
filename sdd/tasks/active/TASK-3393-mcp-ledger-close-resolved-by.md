# TASK-3393: MCP `ledger_close` tool forwards `resolved_by`

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3391
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (MCP half), design research **S4**: fixing only the service and the CLI
would leave every agent-driven close through the `ledger_close` MCP tool unverifiable —
`LedgerCloseTool._execute(issue_id, reason)` calls `close_issue(..., "agent:mcp")` with no
`resolved_by`, and `LedgerCloseInput` has no such field. "On **every** close surface, the MCP
tool included."

Depends on TASK-3391 for the `resolved_by` keyword on `LedgerService.close_issue`.

---

## Scope

- Add `resolved_by: str | None = None` to `LedgerCloseInput`.
- Extend `LedgerCloseTool._execute(issue_id, reason, resolved_by=None)`; forward
  `resolved_by=` **only when not `None`** so the existing call assertion
  (`assert_called_once_with("issue:def456", "Fixed", "agent:mcp")`) stays valid — default
  behaviour byte-unchanged.
- Two tests in `tests/knowledge/wiki/test_ledger_tools.py`.

**NOT in scope**: new MCP tools (`ledger_blockers` / `ledger_acknowledge` are explicit
Non-Goals), `mcp_server.py`, the CLI (TASK-3392), tool registration order (`tools.py:777-781`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `LedgerCloseInput.resolved_by`; `_execute` forwards it |
| `tests/knowledge/wiki/test_ledger_tools.py` | MODIFY | `test_mcp_ledger_close_passes_resolved_by`, `..._without_resolved_by_unchanged` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.tools import LedgerCloseInput, LedgerCloseTool   # verified: tools.py:616,703
from parrot.tools.abstract import AbstractTool, ToolResult                 # verified: tools.py:22
from pydantic import BaseModel, Field                                      # verified: tools.py:16
from unittest.mock import AsyncMock                                        # verified: test_ledger_tools.py:4
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
class LedgerCloseInput(BaseModel):                                          # 616
    issue_id: str = Field(..., description="Issue ID to close")             # 617
    reason: str = Field(..., description="Reason for closing")              # 618  ← add resolved_by below
class LedgerCloseTool(AbstractTool):                                        # 703
    name = "ledger_close"; description = "Close an issue in the SDD ledger."; args_schema = LedgerCloseInput   # 706-708
    def __init__(self, ledger_service: "LedgerService"): super().__init__(name=self.name, description=self.description); self._ledger_service = ledger_service  # 710-712
    async def _execute(self, issue_id: str, reason: str) -> ToolResult:     # 714 ← REPLACE
        try:
            success = await self._ledger_service.close_issue(issue_id, reason, "agent:mcp")   # 716 ← REPLACE
            return ToolResult(result={"success": success})
        except Exception as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))
# registration (unchanged): tools.extend([LedgerOpenTool, LedgerReadyTool, LedgerClaimTool, LedgerCloseTool, LedgerContextTool])  # 777-781

# service (TASK-3391): async def close_issue(self, issue_id, reason, actor, resolved_by: str | None = None) -> bool

# tests/knowledge/wiki/test_ledger_tools.py
@pytest.fixture mock_ledger_service() -> AsyncMock                          # 24-27
class TestLedgerTools:                                                       # 86
    async def test_ledger_close_tool(self, mock_ledger_service):             # 142-152 — asserts
        mock_ledger_service.close_issue.assert_called_once_with("issue:def456", "Fixed", "agent:mcp")   # MUST keep passing
    def test_no_acknowledge_tool_exists(self):                               # 165 ← insert the two new tests ABOVE this
```

### Does NOT Exist
- ~~`LedgerCloseInput.resolved_by`~~ — added here.
- ~~`LedgerCloseTool._execute(..., resolved_by=...)`~~ — added here.
- ~~`ledger_blockers` / `ledger_acknowledge` / `ledger_unclaim` / `ledger_plan_fix` MCP tools~~ — out of scope (spec §1 Non-Goals); exactly five ledger tools stay registered.
- ~~`actor` parameter on the MCP tool~~ — the actor stays the literal `"agent:mcp"`.
- ~~`routing_meta["requires_confirmation"]`~~ — not needed for close; do not add.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_tools.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#LedgerCloseInput",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#LedgerCloseTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#LedgerCloseTool._execute",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.close_issue"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The **existing** `test_ledger_close_tool` asserts the exact positional call; forwarding a
  `resolved_by=None` kwarg would break it. Forward the kwarg only when given.
- `LedgerCloseInput` is the LLM-facing schema — the new field's `description` is what the
  agent reads; say what a valid ref looks like.
- FEAT-570 (`expose-local-mcp-tools`) may touch `tools.py`; re-verify anchors if it lands first.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py:626-659` — `LedgerOpenTool`, the richest `_execute` in the group.

---

## Implementation Blueprint

### Steps (in order)
1. Add the input field — *why*: the MCP schema must advertise the evidence argument or no agent will pass it.
2. Extend `_execute` with conditional forwarding — *why*: S4 without changing default behaviour.
3. Add the two tests above `test_no_acknowledge_tool_exists`; run the file.

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    reason: str = Field(..., description="Reason for closing")' packages/ai-parrot/src/parrot/knowledge/wiki/tools.py)
# AFTER — insert below that line (verified: tools.py:618)
    resolved_by: str | None = Field(
        default=None, description="Evidence that resolved the issue, e.g. commit:<sha> or task:TASK-<NNN> (FEAT-572 S4)"
    )
```
```python
# occurrences: 1 (verified: grep -cF '    async def _execute(self, issue_id: str, reason: str) -> ToolResult:' packages/ai-parrot/src/parrot/knowledge/wiki/tools.py)
# REPLACE that signature line (verified: tools.py:714) with:
    async def _execute(self, issue_id: str, reason: str, resolved_by: str | None = None) -> ToolResult:
        """Close a ledger issue, carrying the evidence reference through (actor stays ``agent:mcp``)."""
# occurrences: 1 (verified: grep -cF 'success = await self._ledger_service.close_issue(issue_id, reason, "agent:mcp")' …/tools.py)
# REPLACE that call line (verified: tools.py:716) with:
            kwargs = {"resolved_by": resolved_by} if resolved_by is not None else {}
            success = await self._ledger_service.close_issue(issue_id, reason, "agent:mcp", **kwargs)
```
**Why this shape**: one optional field, one optional kwarg — the smallest change that makes
an MCP close falsifiable while leaving every existing call (and its test) byte-identical.

### `tests/knowledge/wiki/test_ledger_tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    def test_no_acknowledge_tool_exists(self):' tests/knowledge/wiki/test_ledger_tools.py)
# BEFORE — insert ABOVE that method inside class TestLedgerTools (verified: :165); add `LedgerCloseInput` to the import list
    @pytest.mark.asyncio
    async def test_mcp_ledger_close_passes_resolved_by(self, mock_ledger_service):
        """LedgerCloseTool forwards the evidence ref (S4)."""
        tool = LedgerCloseTool(mock_ledger_service)
        mock_ledger_service.close_issue.return_value = True
        result = await tool._execute(issue_id="issue:def456", reason="Fixed", resolved_by="commit:abc123")
        assert result.result == {"success": True}
        mock_ledger_service.close_issue.assert_called_once_with("issue:def456", "Fixed", "agent:mcp", resolved_by="commit:abc123")

    @pytest.mark.asyncio
    async def test_mcp_ledger_close_without_resolved_by_unchanged(self, mock_ledger_service):
        """Default None keeps the pre-FEAT-572 call shape."""
        # FILL IN: _execute(issue_id, reason) → close_issue.assert_called_once_with("issue:def456", "Fixed", "agent:mcp")
        #          and LedgerCloseInput(issue_id="x", reason="y").resolved_by is None — bounded by AC "omitting it unchanged"
```
**Why**: the first test is S4's proof; the second pins the compatibility promise at both the
schema and call level.

### FILL IN checklist
- [ ] `test_ledger_tools.py::TestLedgerTools::test_mcp_ledger_close_without_resolved_by_unchanged` — body; bounded by AC "omitting it unchanged"

---

## Acceptance Criteria

- [ ] `LedgerCloseInput` has `resolved_by: str | None = None` with a descriptive `Field`.
- [ ] `LedgerCloseTool._execute(..., resolved_by="commit:x")` calls `close_issue(issue_id, reason, "agent:mcp", resolved_by="commit:x")`.
- [ ] Omitting `resolved_by` calls `close_issue(issue_id, reason, "agent:mcp")` exactly as before; existing `test_ledger_close_tool` passes unmodified.
- [ ] Still exactly five ledger MCP tools registered.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_ledger_tools.py -v`
- [ ] `ruff check` and `black --check -l 120` clean on `tools.py`.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_tools.py -q`

---

## Test Specification

```python
class TestLedgerTools:
    async def test_mcp_ledger_close_passes_resolved_by(self, mock_ledger_service): ...
    async def test_mcp_ledger_close_without_resolved_by_unchanged(self, mock_ledger_service): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 4 MCP skeleton, §9 S4).
2. **Check dependencies** — TASK-3391 completed.
3. **Verify the Codebase Contract** — the three anchors occur once each.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement** from the blueprint.
6. **Verify** the Validation Command (`PYTHONPATH=packages/ai-parrot/src` in a worktree).
7. **Move this file** to `sdd/tasks/completed/TASK-3393-mcp-ledger-close-resolved-by.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
