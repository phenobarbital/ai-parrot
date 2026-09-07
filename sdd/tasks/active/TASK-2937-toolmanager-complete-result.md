# TASK-2937: Add opt-in complete ToolResult execution

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial dependency boundary. Shared production/test files must not be edited concurrently; complete listed prerequisites first.

---

## Context

Implements §3 Module 1 and contributes to AC3, AC4. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Add keyword-only return_tool_result: bool = False to the existing manager dispatch. Preserve default raw values, exceptions, early statuses and processing order.
- In full mode preserve ToolResult from AbstractTool/ToolkitTool and ToolDefinition; wrap ordinary values as success without treating business dictionaries as envelopes.
- Return a copied envelope and distinct metadata. Keep AbstractTool extraction/result hooks once on original payload before normal result compression; do not compress voice_text/display_data or add compression to plain functions.
- Preserve non-success envelopes including error, forbidden, pending, not_found, cancelled, timeout and authorization_required. Keep error-payload capture where applicable; propagate resolver/dispatch errors and cancellation.
- Offload synchronous ToolDefinition functions only in full mode using the standard-library thread helper. Do not retry work or promise cancellation rollback.

**NOT in scope**: Output safeguards and shared-instance locking belong to the next task; no Nova consumer enables this mode until both manager tasks finish. No AbstractClient changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Scoped deliverable owned by TASK-2937 |
| `packages/ai-parrot/tests/tools/test_toolmanager_full_result.py` | CREATE | Scoped deliverable owned by TASK-2937 |

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
- `packages/ai-parrot/tests/tools/test_toolmanager_full_result.py` — NEW deliverable of this feature; verify dependent task exports before importing.
- `packages/ai-parrot/src/parrot/tools/abstract.py` — ToolResult at 250–278 includes result/success/status/error/metadata/voice_text/display_data. _current_pctx at 892–899 is mutable. Guard helper returns (processed_value, flag_reports); existing output block 1041–1092 omits voice/display.
- `packages/ai-parrot/src/parrot/auth/permission.py` — Verified definitions: UserSession:21, PermissionContext:81, build_principal_context:166, to_eval_context:209, __post_init__:51, has_role:57.
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — Verified definitions: ToolkitTool:35, AbstractToolkit:206, __init__:40, _is_unsupported_type:75, _generate_args_schema_from_method:98, _execute:145.
- `packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py` — Verified definitions: TestToolDefinitionModel:33, TestToolDecoratorRequiredPermissions:56, TestRegistrationMetadata:84, _AllowAllResolver:191, _DenyAllResolver:196, _BoomResolver:201.
- `packages/ai-parrot/tests/tools/compression/test_manager_integration.py` — Verified definitions: test_after_tool_call_event_new_fields_have_defaults:17, BulkyTool:52, BulkyToolkit:62, tool_manager_with_compression:71, TestStagePlacement:78, TestClone:162.
- `packages/ai-parrot/tests/test_toolmanager_confirmation.py` — Verified definitions: _FakeResult:30, _FakeManager:40, _SimpleConfirmingTool:52, _GrantAndConfirmTool:70, _make_manager:91, test_set_confirmation_guard_and_property:99.

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

- [ ] Default-mode enforcement, confirmation, raw returns and compression regressions pass.
- [ ] Real tools retain result, voice_text, display_data, error/status and metadata without mutation of the original envelope.
- [ ] Hooks run once, failures never trigger success hooks, and synchronous full-mode functions do not block an independent event-loop probe.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- test_default_result_contract_unchanged
- test_full_result_preserves_voice_display_and_status
- test_full_result_preserves_enforcement_order
- test_full_result_error_and_auth_statuses
- test_full_result_hooks_once_before_compression

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

Pending implementation and verification. No runtime or live acceptance is claimed by task creation.

**Completed by**: unassigned
**Date**: pending
**Notes**: pending
**Deviations from spec**: none recorded
