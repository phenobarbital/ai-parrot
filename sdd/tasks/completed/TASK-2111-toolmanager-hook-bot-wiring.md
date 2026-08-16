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
| `packages/ai-parrot/tests/unit/test_guardrails_tool_call_hook.py` | CREATE | Unit tests for the wiring |

**Codebase Contract corrections (verified 2026-08-04)**:
1. Test path corrected from `packages/ai-parrot/tests/bots/guardrails/test_tool_call_hook.py`
   (no such directory) to `packages/ai-parrot/tests/unit/test_guardrails_tool_call_hook.py`.
2. `ToolManager` has no `_agent_name` attribute (`getattr(self, '_agent_name', '')`
   in the task's snippet does not exist and would always be `''`). The established
   precedent at this exact seam — `tools/abstract.py`'s `_run_tool_output_guardrails()`
   (line ~142), which builds `GuardrailContext` at a call site with the same
   information available (a tool name, no bot back-reference) — uses
   `agent_name=tool_name` (the tool name doubles as the agent_name field since
   `ToolManager` has no bot reference). Followed the same precedent here for
   consistency instead of inventing a new fallback.
3. Guardrail imports are **lazy** (function-local), not top-level, mirroring
   `tools/abstract.py`'s own `from ..bots.guardrails.base import GuardrailContext,
   GuardrailStage  # noqa: PLC0415` — `tools/manager.py` currently has zero
   `bots.guardrails` imports; introducing one at module level would be a new,
   heavier import-time coupling this task's scope doesn't require.
4. **"Construct `PBACToolCallGuardrail` when PBAC is enabled" — verified this
   requires ZERO new code in `AbstractBot.__init__`.** `AbstractBot` has no
   `app`/aiohttp reference and no `_pbac_evaluator` attribute (confirmed —
   `setup_pbac(app, ...)` is only called at the application/handler level,
   e.g. `auth/dataset_guard.py:28`, never inside `bots/abstract.py`), so
   there is no verified in-bot hook to "detect" PBAC and auto-build the
   guardrail — inventing one (a new `app=`/`pbac_evaluator=` constructor
   kwarg) would be unverified architecture invention beyond this task's
   Codebase Contract. Instead: `AbstractBot.__init__`'s existing
   `guardrails: Optional[List[Union[str, Dict[str, Any], Guardrail]]] = None`
   parameter (line 277) already flows into `build_pipelines_from_config()` →
   `build_guardrails()` (both unchanged since TASK-2109/2110), which already
   accepts a `Guardrail` **instance** as-is, or a `{"name": "pbac", **kwargs}`
   **dict** forwarded to the TASK-2110-registered lazy factory as keyword
   arguments — i.e. `guardrails=[PBACToolCallGuardrail(evaluator=shared_evaluator)]`
   or `guardrails=[{"name": "pbac", "evaluator": shared_evaluator}]` both
   already work end-to-end today, land in
   `self._guardrail_pipelines[GuardrailStage.TOOL_CALL]` via the existing
   per-stage loop in `config.py` (`for stage in guardrail.stages: pipelines[stage].add(guardrail)`),
   and are reachable via `tool_manager._tool_call_pipeline` once stamped.
   This is exactly the "bot wiring" the spec's resolved Q7 describes ("the
   concrete instance is constructed by bot wiring... passed as an instance
   entry in `guardrails=[...]`") — "bot wiring" is the caller code that
   calls `setup_pbac(app)` and instantiates the bot, not `AbstractBot.__init__`
   itself. A bare string `guardrails=["pbac"]` (no evaluator) correctly
   raises `TypeError` from the guardrail's required `evaluator` parameter —
   by design, since the registry name is documented as discoverability-only
   (`registry.py`'s own comment) and there is no default evaluator to fall
   back to. "Skip registration when `setup_pbac()` returned `(None, None,
   None)`" is therefore satisfied trivially by the caller simply not passing
   a `PBACToolCallGuardrail` when it has no evaluator — no new conditional
   code needed in `AbstractBot`.

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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-04
**Notes**: Added `ToolManager._tool_call_pipeline` (mirrors `_tool_output_pipeline`)
and a pre-execution TOOL_CALL guardrail hook in `execute_tool()`, inserted
right before the Grant guard block — runs first in the chain
(TOOL_CALL → grant → confirm). A blocked outcome returns
`ToolResult(success=False, status="forbidden", error=<message>)` before the
tool ever executes, preferring the blocking guardrail's human-readable
`report["message"]` over the bare category-label `reason`. Stamped
`tool_manager._tool_call_pipeline` in `AbstractBot.__init__` right after the
existing `_tool_output_pipeline` stamp (same seam, `abstract.py:747`). 7 new
unit tests (order, BLOCK translation, no-pipeline/empty-pipeline regression,
bot-wiring stamp, custom-instance guardrail actually running, PBAC-absent
regression) + full guardrails/auth/grants/confirmation regression suite
(207 tests) pass. Confirmed pre-existing, unrelated failures in
`tests/tools/databasequery/test_toolkit_ddl_guard.py` and
`tests/tools/test_auto_registration_hooks.py` (identical failures with and
without this diff, verified via `git stash`) — out of scope. `ruff check`:
no new lint categories introduced (`abstract.py` unchanged at 256
pre-existing errors; `manager.py` gained exactly one `UP045` on the new
`_tool_call_pipeline: Optional[Any] = None` line, stylistically identical
to the adjacent pre-existing `_tool_output_pipeline` line it mirrors — new
test file is itself ruff-clean).

**Deviations from spec**: (1) Test file path corrected to
`tests/unit/test_guardrails_tool_call_hook.py` (no `tests/bots/guardrails/`
directory exists). (2) `ToolManager` has no `_agent_name` attribute (the
task's suggested `getattr(self, '_agent_name', '')` would always be `''`)
— followed the exact precedent at this same architectural seam
(`tools/abstract.py`'s `_run_tool_output_guardrails()`), which uses the
tool name for both `GuardrailContext.agent_name` and `.tool_name` since
`ToolManager` has no bot back-reference. (3) Guardrail imports are
function-local/lazy (`# noqa` removed since `PLC0415` isn't an enabled
ruff rule here), mirroring `tools/abstract.py`'s own lazy-import
convention — `tools/manager.py` had zero `bots.guardrails` imports
before this task. (4) **No PBAC-specific construction code was added to
`AbstractBot.__init__`** — verified this is unnecessary: `AbstractBot` has
no `app`/evaluator reference (`setup_pbac(app)` is only ever called at the
application/handler layer), so there is no in-bot hook to build the
guardrail from; inventing one would be unverified architecture invention.
Instead, the existing (unchanged since TASK-2109/2110) `guardrails=[...]`
constructor kwarg + `build_guardrails()`/`build_pipelines_from_config()`
machinery already routes either a `PBACToolCallGuardrail(evaluator=...)`
instance or a `{"name": "pbac", "evaluator": ...}` dict into the TOOL_CALL
pipeline end-to-end — this IS the "bot wiring" the spec's Q7 describes (the
caller code that calls `setup_pbac(app)` and instantiates the bot), not
`AbstractBot.__init__` itself. Verified with a new integration-style test
(`test_custom_tool_call_guardrail_instance_actually_runs`). All findings
documented in the task's corrected Codebase Contract section above before
implementing.
