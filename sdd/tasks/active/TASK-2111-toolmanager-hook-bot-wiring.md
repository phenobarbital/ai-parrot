# TASK-2111: ToolManager Hook + AbstractBot Wiring

**Feature**: FEAT-406 — PBAC Guardrails
**Spec**: `sdd/specs/pbac-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2109, TASK-2110
**Assigned-to**: unassigned

---

## Context

This task wires the TOOL_CALL pipeline into the execution path. It adds a
`_tool_call_pipeline` attribute to `ToolManager`, runs it at the TOP of the guard
chain in `execute_tool()` (before GrantGuard and ConfirmationGuard), translates a
BLOCK outcome into `ToolResult(status="forbidden")`, and stamps the pipeline from
`AbstractBot` during bot initialization — mirroring the existing `_tool_output_pipeline`
seam.

It also constructs `PBACToolCallGuardrail(evaluator=...)` in bot wiring when PBAC is
enabled and `"pbac"` is requested in the `guardrails=[...]` config.

Implements spec §3 Module 3.

---

## Scope

- Add `self._tool_call_pipeline: Optional[Any] = None` to `ToolManager.__init__` (mirror `_tool_output_pipeline` at line 290)
- In `ToolManager.execute_tool()`, at the TOP of the `AbstractTool` branch (after the `ToolDefinition` early return), run the TOOL_CALL pipeline BEFORE GrantGuard:
  - If `_tool_call_pipeline` is not None and `has_guardrails`:
    - Build `GuardrailContext(stage=TOOL_CALL, agent_name=..., tool_name=..., extras={"permission_context": permission_context, "tool_name": tool_name, "arguments": parameters})`
    - Run pipeline with compact serialized content (e.g. `f"tool_call:{tool_name}"`)
    - If `outcome.blocked` → return `ToolResult(success=False, status="forbidden", error=<outcome.reason or report message>, result=None)`
- In `AbstractBot.__init__` (after line 747 seam), stamp:
  `self.tool_manager._tool_call_pipeline = self._guardrail_pipelines[GuardrailStage.TOOL_CALL]`
- Construct `PBACToolCallGuardrail` when PBAC is enabled: detect shared evaluator from `setup_pbac()`, build guardrail instance, add to TOOL_CALL pipeline when `"pbac"` is in `guardrails=[...]` config (or passed as an instance)
- Skip registration when `setup_pbac()` returned `(None, None, None)`
- Write unit tests

**NOT in scope**: UserInfoService (TASK-2112), UserinfoTool (TASK-2113), attribute
enrichment (TASK-2114).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Add `_tool_call_pipeline` attr + pre-execution hook in `execute_tool()` |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Stamp `_tool_call_pipeline` + construct PBAC guardrail when enabled |
| `packages/ai-parrot/tests/bots/guardrails/test_tool_call_hook.py` | CREATE | Unit tests for the wiring |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails.base import (
    GuardrailAction, GuardrailContext, GuardrailStage, GuardrailPipeline, PipelineOutcome,
)
from parrot.tools.result import ToolResult     # tools/result.py
from parrot.auth import PermissionContext      # auth/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py:290
self._tool_output_pipeline: Optional[Any] = None   # mirror this for _tool_call_pipeline

# packages/ai-parrot/src/parrot/tools/manager.py:1422
async def execute_tool(
    self, tool_name: str, parameters: Dict[str, Any],
    permission_context: Optional["PermissionContext"] = None,
) -> Any
# ToolDefinition early-return at ~line 1452-1463
# AbstractTool branch starts at line 1465
# GrantGuard check at line 1477-1491
# ConfirmationGuard after GrantGuard

# packages/ai-parrot/src/parrot/tools/manager.py — denial shape precedent (GrantGuard):
# ToolResult(success=False, status="forbidden", error=f"Grant denied: {decision.reason}", result=None)

# packages/ai-parrot/src/parrot/bots/abstract.py:668
self._guardrail_pipelines: Dict[GuardrailStage, GuardrailPipeline] = build_pipelines_from_config(...)

# packages/ai-parrot/src/parrot/bots/abstract.py:747
self.tool_manager._tool_output_pipeline = self._guardrail_pipelines[GuardrailStage.TOOL_OUTPUT]
# ← stamp _tool_call_pipeline right after this line

# packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py:122
class GuardrailPipeline:
    has_guardrails: bool  # property, line 122
    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome  # line 138

# packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py:62
class PipelineOutcome(BaseModel):
    content: str | None; blocked: bool; reason: str | None
    flag_reports: dict[str, dict[str, Any]]; telemetry: list[GuardrailTelemetryEntry]
```

### Does NOT Exist
- ~~`ToolManager._tool_call_pipeline`~~ — only `_tool_output_pipeline` exists; this task introduces the new attr.
- ~~Pre-execution guardrail hook in `execute_tool()`~~ — nothing runs before GrantGuard except the ToolDefinition early return.
- ~~`AbstractBot._pbac_evaluator`~~ — there's no such attribute; the evaluator comes from `setup_pbac()`.
- ~~`ToolManager.run_guardrails()`~~ — no such method; the pipeline is called directly.

---

## Implementation Notes

### Pattern to Follow
Mirror the `_tool_output_pipeline` stamping at `abstract.py:747`:
```python
# After line 747:
self.tool_manager._tool_call_pipeline = self._guardrail_pipelines[GuardrailStage.TOOL_CALL]
```

In `execute_tool()`, insert the TOOL_CALL hook before GrantGuard (line 1477):
```python
# === TOOL_CALL guardrail pipeline (FEAT-406) ===
if self._tool_call_pipeline is not None and self._tool_call_pipeline.has_guardrails:
    ctx = GuardrailContext(
        stage=GuardrailStage.TOOL_CALL,
        agent_name=getattr(self, '_agent_name', ''),
        tool_name=tool_name,
        extras={"permission_context": permission_context},
    )
    outcome = await self._tool_call_pipeline.run(
        f"tool_call:{tool_name}", ctx
    )
    if outcome.blocked:
        return ToolResult(
            success=False,
            status="forbidden",
            error=outcome.reason or "Policy denied",
            result=None,
        )
# === End TOOL_CALL guardrail ===
```

### Key Constraints
- Keep the hook additive — do NOT reorder grant → confirm relative to each other
- `ToolDefinition` path (simple function wrappers) is NOT affected by the pipeline
- `_tool_call_pipeline is None` path must be identical to today's behavior (regression)
- Parallel tool calls: each call evaluated independently; one denial must not abort siblings
- `content` for telemetry must never include tool arguments (spec §4)

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/manager.py:1465-1491` — existing guard chain
- `packages/ai-parrot/src/parrot/bots/abstract.py:747` — pipeline stamping seam
- `packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py:138-191` — pipeline.run() and BLOCK handling

---

## Acceptance Criteria

- [ ] `ToolManager._tool_call_pipeline` attribute exists
- [ ] TOOL_CALL pipeline runs BEFORE GrantGuard/ConfirmationGuard (order assertion)
- [ ] Blocked outcome → `ToolResult(success=False, status="forbidden", error=<message>)`; tool never executed
- [ ] `_tool_call_pipeline is None` → behavior identical to today
- [ ] Bot wiring stamps `tool_manager._tool_call_pipeline` from TOOL_CALL pipeline
- [ ] PBAC not registered when `setup_pbac()` returned `(None, None, None)`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/bots/guardrails/test_tool_call_hook.py -v`
- [ ] Existing ToolManager tests pass: `pytest packages/ai-parrot/tests/tools/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/guardrails/test_tool_call_hook.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestToolCallPipelineHook:
    async def test_execute_tool_runs_tool_call_pipeline_first(self):
        """Pipeline runs BEFORE GrantGuard (order assertion via mocks)."""

    async def test_block_translates_to_forbidden_toolresult(self):
        """Blocked outcome → ToolResult(success=False, status='forbidden')."""

    async def test_no_pipeline_path_unchanged(self):
        """_tool_call_pipeline is None → behavior identical to today."""

    async def test_bot_wiring_stamps_tool_call_pipeline(self):
        """tool_manager._tool_call_pipeline is the bot's TOOL_CALL pipeline."""

    async def test_pbac_not_registered_without_engine(self):
        """setup_pbac degraded → 'pbac' not in any pipeline."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2109 and TASK-2110 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm line numbers in `manager.py` and `abstract.py`
4. **Re-check `tools/manager.py` for in-flight edits** (high-traffic file — see spec §7)
5. **Update status** in `sdd/tasks/index/pbac-guardrails.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2111-toolmanager-hook-bot-wiring.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
