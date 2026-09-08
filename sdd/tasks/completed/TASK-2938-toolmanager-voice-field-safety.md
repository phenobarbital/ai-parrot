# TASK-2938: Protect voice fields and isolate shared tool invocations

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 3h)
**Depends-on**: TASK-2937
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial dependency boundary. Shared production/test files must not be edited concurrently; complete listed prerequisites first.

---

## Context

Implements §3 Module 1 and contributes to AC4, AC5. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Complete full-mode output processing for voice_text and display_data using the existing guard helper when output guardrails/redaction are enabled. Preserve flag reports and do not process result/error/metadata twice.
- If a newly exposed field cannot be safely processed, suppress it and surface a controlled error. Suppress visual content that ceases to have dictionary shape; never forward the original unsafe value.
- Add a lazily initialized private lock on each AbstractTool instance for full-mode calls, covering pipeline stamping through result copying. Manager clones share the same tool and lock; different instances can overlap.
- Release locks on cancellation and exclude internal state from tool schemas. Preserve ordinary-mode concurrency semantics and the original tool-owned envelope.

**NOT in scope**: No global concurrency refactor, Gemini migration or provider scheduling. Follow the first task’s opt-in interface.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Scoped deliverable owned by TASK-2938 |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | Scoped deliverable owned by TASK-2938 |
| `packages/ai-parrot/tests/tools/test_toolmanager_full_result.py` | CREATE | Scoped deliverable owned by TASK-2938 |

Only the files above belong to this task, plus its task state and per-spec index. You are not alone in this codebase: preserve others' edits and adapt to completed dependencies. Read-only references below do not grant edit ownership.

## Codebase Contract (Anti-Hallucination)

Re-read and verified on 2026-09-07 against dev `77bd1a50c1282694444e05b4f41ad4138c880ff2`. These are baseline definitions, not invented future APIs. Dependencies may change their lines/signatures: refresh them before implementation.

### Verified Imports

```python
from parrot.tools.manager import ToolManager, ToolDefinition
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.auth.permission import PermissionContext
```

Imports are verified from local definitions/usage, not an all-package runtime smoke. Browser SDK access is through the existing livekit-client package exposed as LivekitClient UMD; the controller accepts an injected SDK in tests.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/manager.py:29
class ToolDefinition

# packages/ai-parrot/src/parrot/tools/manager.py:249
class ToolManager

# packages/ai-parrot/src/parrot/tools/manager.py:1241
def get_tool(self, tool_name: str) -> Optional[Any]

# packages/ai-parrot/src/parrot/tools/manager.py:1514
async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional['PermissionContext']=None) -> Any

# packages/ai-parrot/src/parrot/tools/manager.py:2183
def _run_result_hooks(self, tool_name: str, result: Any, metadata: Dict[str, Any]) -> None

# packages/ai-parrot/src/parrot/tools/abstract.py:142
async def _run_tool_output_guardrails(pipeline: Optional[Any], value: Any, tool_name: str) -> tuple[Any, dict[str, dict[str, Any]]]

# packages/ai-parrot/src/parrot/tools/abstract.py:250
class ToolResult

# packages/ai-parrot/src/parrot/tools/abstract.py:281
class AbstractTool

# packages/ai-parrot/src/parrot/tools/abstract.py:837
async def execute(self, *args, **kwargs) -> ToolResult

# packages/ai-parrot/src/parrot/auth/permission.py:81
class PermissionContext

# packages/ai-parrot/src/parrot/tools/manager.py:2067
def clone(self, *, include_search_tool: bool=False) -> 'ToolManager'
```

### Task-specific References

- `packages/ai-parrot/src/parrot/tools/manager.py` — execute_tool currently reduces AbstractTool result at 1781–1852; full-result option is proposed. clone at 2067 shares tool registrations. ToolDefinition fields: name, description, input_schema, function, routing_meta, required_permissions.
- `packages/ai-parrot/src/parrot/tools/abstract.py` — ToolResult at 250–278 includes result/success/status/error/metadata/voice_text/display_data. _current_pctx at 892–899 is mutable. Guard helper returns (processed_value, flag_reports); existing output block 1041–1092 omits voice/display.
- `packages/ai-parrot/tests/tools/test_toolmanager_full_result.py` — NEW deliverable of this feature; verify dependent task exports before importing.
- `packages/ai-parrot/src/parrot/auth/permission.py` — Verified definitions: UserSession:21, PermissionContext:81, build_principal_context:166, to_eval_context:209, __post_init__:51, has_role:57.
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — Verified definitions: ToolkitTool:35, AbstractToolkit:206, __init__:40, _is_unsupported_type:75, _generate_args_schema_from_method:98, _execute:145.

### Does NOT Exist

- No root parrot/ source tree; use workspace package paths. No model-native JSON-schema voice output is added.
- No shared last-result storage or LiveVoiceResponse.display_data attribute; structured output uses response.metadata["display_data"].
- return_tool_result is absent at this baseline and introduced by TASK-2937; downstream tasks must re-read its completed implementation.
- NovaClient._execute_tool override is not part of this feature.

## Implementation Notes

### Pattern to Follow

Use the task-specific source anchors and spec §2 behavior. Preserve existing execution/transport ownership. Keep helpers typed and private where possible; match Python black and frontend prettier conventions.

### Key Constraints

- No new dependencies or unrelated refactors. No production change to AbstractClient or GeminiLiveClient.
- Keep secrets/permission objects out of provider arguments, browser panels and logs.
- Follow the task DAG and file ownership above; report cross-scope failures to the owning task.
- Save exact verification commands and results under artifacts/logs/ and reference them in completion notes.

## Acceptance Criteria

- [ ] Transform/block/flag and processing-error fixtures prove no original sensitive voice/display field escapes.
- [ ] Two cloned managers sharing one tool cannot overlap mutable permission/pipeline state, while distinct tools run concurrently.
- [ ] Cancellation releases the lock and a following invocation completes. Existing result processing stays once-only.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- test_full_result_output_fields_obey_guards
- test_full_result_shared_tool_context_isolation
- test_full_result_preserves_enforcement_order

Use behavioral fixtures with real tools/manager where that path is under test. Mock only provider/transport boundaries for conformance. Event gates and patched deadlines should replace timing-sensitive sleeps. Browser tests load the actual demo page. No live test runs are required for automated CI.

Commands to run from the feature worktree using its configured environment (capture output in artifacts/logs/):

```bash
pytest packages/ai-parrot/tests/tools/test_toolmanager_full_result.py -q
```

Missing optional SDK/browser/live credentials are prerequisites to record explicitly; they cannot be reported as passing verification. For the operational acceptance task, the live matrix itself is mandatory and completion remains pending until all required scenarios pass.

## Agent Instructions

1. Read the approved spec and this task; check dependencies in the per-spec index.
2. Refresh the Codebase Contract before writing code; verify new dependency exports rather than assuming them.
3. Update status to in-progress with assignment/start timestamp in `sdd/tasks/index/voicebot-liveavatar-implementation.json` only; do not use the historical monolithic index.
4. Implement only owned files and run the required behavioral verification.
5. Perform the repository task review workflow; resolve findings within scope.
6. Once acceptance passes, move this file to sdd/tasks/completed/ and set its per-spec entry to done with completion timestamp and updated path.
7. Fill in the Completion Note with code/test evidence and deviations. Do not mark done merely because work was attempted or a required live scenario was not run.

## Completion Note

Implemented both scope items on top of TASK-2937's `return_tool_result`:

1. **Output-field guard processing** — `ToolManager._finish_abstract_tool_full_result()`
   now runs `voice_text`/`display_data` through the existing
   `_run_tool_output_guardrails()` helper (imported from `.abstract`)
   when `tool.enable_redaction or tool._has_tool_output_guardrails()`
   — the identical gate `AbstractTool.execute()` already uses for
   `result`/`error`/`metadata`, so those three fields are never
   re-processed by this new code (only the two newly-exposed fields
   are handled here). FLAG reports merge into
   `metadata["guardrails"]`. A `display_data` value that no longer has
   dict shape after processing (a misbehaving guardrail's `scrub()`
   returning a non-dict) is suppressed to `None`; a field whose
   processing genuinely raises is likewise suppressed with a note in
   `metadata["output_guard_errors"]`. Verified the original sensitive
   value never appears in the returned envelope for every case (block,
   malformed-scrub, raising pipeline, fail-closed scrub error).
2. **Per-instance lock** — `AbstractTool._get_full_result_lock()`
   (abstract.py) lazily creates and caches `self._full_result_lock`
   (`asyncio.Lock`). `ToolManager.execute_tool()` acquires it — only
   when `return_tool_result=True` — as the very first statement inside
   the `AbstractTool` branch (before the existing redaction/pipeline
   stamping), and releases it in a `finally` added to the method's
   *existing* outer `try/except`. This required NO re-indentation of
   the existing (large) AbstractTool-branch body: the lock variable
   (`full_result_lock`, initialized to `None` before the `try`) is only
   ever set to a real lock *after* a successful `acquire()`, so the
   `finally`'s `if full_result_lock is not None: full_result_lock.release()`
   is a true no-op in default mode (zero behavioral change verified by
   the full regression suite) and correctly skips releasing a
   never-acquired lock if `acquire()` itself is cancelled while
   waiting. Verified: two managers sharing one tool instance (via
   `clone()`) serialize full-mode calls (the second never enters
   `_execute()` until the first releases the gate); two *different*
   tool instances run fully concurrently (no cross-instance
   contention); a cancelled in-flight call releases the lock so the
   next call on the same instance completes without deadlocking.

**Evidence**:
- `pytest packages/ai-parrot/tests/tools/test_toolmanager_full_result.py -q`
  → 33 passed (22 from TASK-2937 + 11 new: 7 output-guard fixtures + 3
  isolation/concurrency + 1 cancellation) — `artifacts/logs/task-2938-regression-pytest.log`.
- Regression: `test_tooldefinition_enforcement.py` +
  `test_manager_integration.py` (compression) +
  `test_toolmanager_confirmation.py` + the full-result suite → 74
  passed (`artifacts/logs/task-2938-regression-pytest.log`).
- Full `packages/ai-parrot/tests/tools/` suite → 1091 passed, 52
  failed, 7 skipped (`artifacts/logs/task-2938-full-tools-suite.log`);
  the 52 failures are the same pre-existing `dev`-baseline failures
  documented in TASK-2937's completion note (unrelated
  `test_toolkit_ddl_guard.py`/`test_auto_registration_hooks.py`
  fixtures) — 11 more passing tests than TASK-2937's run, matching
  the 11 tests added here; no new regressions.
- `ruff check` on all three changed/created files: `abstract.py` and
  the test file are clean; `manager.py` has the same 2 pre-existing
  findings noted in TASK-2937 (unused `codecs` import, `F821
  AbstractToolkit` forward-ref) — not introduced by this task.

**Discovered while implementing**: a test fixture initially stamped
`_tool_output_pipeline` directly onto the tool INSTANCE — the
pre-existing manager code (lines ~1757-1758, unmodified by this task)
unconditionally re-stamps `tool._tool_output_pipeline =
self._tool_output_pipeline` (the MANAGER's own, defaulting to `None`)
whenever they differ, silently overwriting a directly-set instance
pipeline right before dispatch. Fixed by configuring the pipeline on
the `ToolManager` (`tm._tool_output_pipeline = ...`) instead, matching
real usage (the manager owns/stamps the pipeline, not the tool). Not a
code change — a test-authoring correction; noted here since it is easy
to reproduce by accident.

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-07
**Notes**: No deviations from the Codebase Contract; all Verified
Imports/Signatures/References matched the current baseline (post
TASK-2937) as read.
**Deviations from spec**: none
