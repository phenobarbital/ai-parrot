# TASK-2581: A2UI closure — adapter warning removal, docs §4, FEAT-469 spec amendment

**Feature**: FEAT-474 — ToolManager ToolDefinition Enforcement Parity (G7 remediation)
**Spec**: `sdd/specs/toolmanager-tooldefinition-enforcement.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2580
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 / Goal G8 (first half). With enforcement parity landed
(TASK-2580), the compensating artifacts FEAT-469 shipped for the gap are now
stale and actively misleading: the per-call `WARNING` in
`ToolManagerExecutor.call()`, the "known limitation" bullet in
`docs/outputs/a2ui-agent-functions.md` §4, and the unresolved escalation
trail in the FEAT-469 spec. This task removes/updates all three, formally
closing the PR #1270 escalation.

---

## Scope

- Remove the known-gap `WARNING` block in `ToolManagerExecutor.call()`
  (`adapters.py:~71-80`) — the `isinstance(tool, ToolDefinition)` check,
  its `get_tool(name)` lookup (if now unused), the local `ToolDefinition`
  import (if now unused), and the warning itself. KEEP the `a2ui_audit`
  INFO line and `_normalize()` untouched.
- Rewrite the §4 "Known limitation, not fixed by this feature" bullet in
  `docs/outputs/a2ui-agent-functions.md` into a statement that enforcement
  is uniform as of FEAT-474: `@tool` functions honor guardrails,
  `requires_confirmation`, and `required_permissions`; note that grants
  (FEAT-211) remain `AbstractTool`-only with a registration warning.
- Amend `sdd/specs/a2ui-agent-functions.spec.md`: add a dated note in its
  risks/§7 area recording that the G7 gap escalated in PR #1270 was closed
  by FEAT-474's manager-level enforcement — satisfying (not contradicting)
  G7 — with a pointer to `sdd/specs/toolmanager-tooldefinition-enforcement.spec.md`.
- Update the `ToolManagerExecutor.call()` docstring (it currently documents
  the gap) and the TASK-2570-related comment if it references the gap.
- Adjust/remove any FEAT-469 unit test that asserts the warning is logged
  (search the a2ui runtime test suite for it).

**NOT in scope**: any enforcement logic (TASK-2580); the new FORBIDDEN e2e
(TASK-2582); changes to the a2ui_audit line or `_normalize()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/adapters.py` | MODIFY | Remove warning block + docstring update (lines ~55-82) |
| `docs/outputs/a2ui-agent-functions.md` | MODIFY | §4 bullet rewrite |
| `sdd/specs/a2ui-agent-functions.spec.md` | MODIFY | Dated closure amendment |
| `packages/ai-parrot/tests/outputs/a2ui/...` | MODIFY | Remove/adjust warning-assertion test if one exists (verify by grep) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.runtime.adapters import ToolManagerExecutor  # adapters.py:44
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/runtime/adapters.py:44-110
class ToolManagerExecutor:
    def __init__(self, tool_manager: ToolManager) -> None: ...
    async def call(self, name: str, args: dict[str, Any], ctx: A2UICallContext) -> ToolResult:
        # ~68: local `from parrot.tools.manager import ToolDefinition`
        # ~70: tool = self._tool_manager.get_tool(name)
        # ~71-80: isinstance ToolDefinition ⇒ logger.warning(known G7 gap…)  ← REMOVE
        # ~82: raw = await self._tool_manager.execute_tool(name, args,
        #          permission_context=ctx.permission_context)              ← KEEP
        # ~84: result = self._normalize(raw)                               ← KEEP
        # ~88-95: a2ui_audit INFO line                                     ← KEEP
    def _normalize(self, raw: Any) -> ToolResult: ...                      # KEEP
    def list_functions(self) -> list[FunctionDefinition]: ...              # untouched

# docs/outputs/a2ui-agent-functions.md §4 "Security posture" — the bullet
# starting "**Known limitation, not fixed by this feature**:" (verified
# 2026-08-29) is the one to replace.

# sdd/specs/a2ui-agent-functions.spec.md — G7 at lines 64-65; AC-G7 at 392.
# Do NOT rewrite G7/AC-G7 themselves — only ADD a dated closure note.
```

### Does NOT Exist
- ~~Any enforcement code in the adapter~~ — enforcement lives in
  `ToolManager.execute_tool()` after TASK-2580; the adapter must NOT
  duplicate checks
- ~~A per-surface allowlist / A2UI opt-in~~ — rejected in FEAT-469
  Non-Goals; do not introduce one while editing docs

---

## Implementation Notes

### Key Constraints
- The docs rewrite must keep §4's overall structure (it is a deploy-facing
  security checklist); only the limitation bullet changes meaning.
- The FEAT-469 spec amendment is additive and dated — SDD specs are
  historical records; never delete the original risk text, append the
  resolution.
- If `tool = self._tool_manager.get_tool(name)` becomes unused after
  removing the warning, remove it too (dead lookup per call is waste);
  verify nothing else in `call()` uses `tool`.
- Grep for tests asserting the warning
  (`rg "known G7 gap|does not enforce permission_context" packages/`) and
  update them rather than leaving a red suite.

### References in Codebase
- `docs/outputs/a2ui-agent-functions.md` §4 — current text to rewrite
- Spec FEAT-474 §2 Overview item 8 — exact closure wording intent

---

## Acceptance Criteria

- [ ] AC-11 (partial): warning block gone from `ToolManagerExecutor.call()`;
  a2ui_audit line and `_normalize()` behaviour unchanged
- [ ] docs §4 no longer claims the ToolDefinition bypass exists; documents
  uniform enforcement + the grants residual
- [ ] FEAT-469 spec carries a dated closure amendment pointing at FEAT-474
- [ ] No test asserts the removed warning; a2ui runtime suite green:
  `pytest packages/ai-parrot/tests/outputs/ -k a2ui -v`
- [ ] `ruff check` clean on modified files

---

## Test Specification

```python
# Adjust existing a2ui runtime tests (locate by grep). New assertion example:
async def test_call_logs_no_gap_warning(caplog, executor_with_tooldef):
    """ToolDefinition dispatch through the adapter emits no G7-gap warning."""
    with caplog.at_level(logging.WARNING):
        await executor.call("plain_fn", {"x": 1}, ctx)
    assert not any("does not enforce permission_context" in r.message
                   for r in caplog.records)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2580 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/toolmanager-tooldefinition-enforcement.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2581-a2ui-closure-docs-spec.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
