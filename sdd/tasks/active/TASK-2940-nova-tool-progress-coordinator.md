# TASK-2940: Coordinate provider events and tool completion without stalls

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 4h)
**Depends-on**: TASK-2939
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial dependency boundary. Shared production/test files must not be edited concurrently; complete listed prerequisites first.

---

## Context

Implements §3 Module 3 and contributes to AC6, AC7, AC8. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Replace next-event flushing with one provider reader and a coordinator that wakes on both provider events and completed tool jobs. Admit fully parsed calls at TOOL contentEnd immediately.
- Correlate tool/content IDs, reject malformed or uncorrelatable input, and deduplicate already-admitted IDs without re-executing.
- Implement arrival-order serial execution by default and bounded parallel execution up to four distinct tool instances. Respect the manager same-instance lock and deliver completed results in completion order.
- Serialize all stream writes, including audio input, tool frames and shutdown, without holding a lock across tool execution/provider waits or recursively acquiring it.
- Deliver one tool result and Python delta while writable, before awaiting any subsequent provider event. Preserve wire contentStart/toolResult/contentEnd IDs and arrival-ordered final snapshots.
- Bound unfinished admission to 32 and emit correlated overload errors. Retain cancellation-safe ownership/finally cleanup; detailed deadlines and generation handling are completed next.

**NOT in scope**: Detailed timeout/reconnect/barge-in generation policy belongs to the next task. Do not redesign the transport or buffered ask_voice.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | MODIFY | Scoped deliverable owned by TASK-2940 |
| `packages/ai-parrot/tests/clients/test_nova_tool_progress.py` | CREATE | Scoped deliverable owned by TASK-2940 |
| `packages/ai-parrot/tests/clients/test_nova_tool_result.py` | MODIFY | Scoped deliverable owned by TASK-2940 |

Only the files above belong to this task, plus its task state and per-spec index. You are not alone in this codebase: preserve others' edits and adapt to completed dependencies. Read-only references below do not grant edit ownership.

## Codebase Contract (Anti-Hallucination)

Re-read and verified on 2026-09-07 against dev `77bd1a50c1282694444e05b4f41ad4138c880ff2`. These are baseline definitions, not invented future APIs. Dependencies may change their lines/signatures: refresh them before implementation.

### Verified Imports

```python
from parrot.clients.amazon.nova import NovaClient
from parrot.models.voice import LiveVoiceResponse, LiveToolCall, VoiceStreamOptions
from parrot.tools.manager import ToolManager, ToolDefinition
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

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:152
class _TurnState

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:275
class NovaAudio

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:515
async def _end_session(self, stream: Any, prompt_name: str, content_name: str | None=None) -> None

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:580
def _build_tool_configuration(self) -> Optional[Dict[str, Any]]

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:667
async def _send_tool_result(self, stream: Any, prompt_name: str, tool_use_id: str, result: Any) -> None

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:736
async def _flush_pending_tools(self, stream: Any, prompt_name: str, pending_tools: List[tuple], tool_calls_list: List[LiveToolCall], usage: LiveCompletionUsage, session_id: Optional[str], turn_id: str, user_id: Optional[str], parallel_tool_execution: bool) -> List[LiveVoiceResponse]

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:825
async def stream_voice(self, audio_iterator: AsyncIterator[bytes], system_prompt: Optional[str]=None, session_id: Optional[str]=None, user_id: Optional[str]=None, stt_only: bool=False, options: Optional[VoiceStreamOptions]=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:1329
async def _audio_sender(self, stream: Any, audio_iterator: AsyncIterator[bytes], prompt_name: str, content_name: str) -> None

# packages/ai-parrot/src/parrot/models/voice.py:150
class VoiceStreamOptions

# packages/ai-parrot/src/parrot/models/voice.py:320
class LiveToolCall

# packages/ai-parrot/src/parrot/models/voice.py:361
class LiveVoiceResponse

# packages/ai-parrot/src/parrot/tools/manager.py:2067
def clone(self, *, include_search_tool: bool=False) -> 'ToolManager'
```

### Task-specific References

- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` — Current queue admission 1200–1233 waits for next non-tool flush at 1087–1110. _send_tool_result 667–734 owns wire association; audio sender 1329–1392 must share safe writer ownership.
- `packages/ai-parrot/tests/clients/test_nova_tool_progress.py` — NEW deliverable of this feature; verify dependent task exports before importing.
- `packages/ai-parrot/tests/clients/test_nova_tool_result.py` — Verified definitions: _run:13, _frames:50, TestToolTiming:54, TestToolArguments:77, TestToolResultEnvelope:95, capture:26.
- `packages/ai-parrot/src/parrot/models/voice.py` — Verified definitions: AudioFormat:27, VoiceProvider:34, VoiceConfig:55, VoiceStreamOptions:150, VoiceCapabilities:187, LiveCompletionUsage:263.
- `packages/ai-parrot/src/parrot/tools/manager.py` — execute_tool currently reduces AbstractTool result at 1781–1852; full-result option is proposed. clone at 2067 shares tool registrations. ToolDefinition fields: name, description, input_schema, function, routing_meta, required_permissions.
- `packages/ai-parrot/tests/clients/test_nova_dual_output.py` — NEW deliverable of this feature; verify dependent task exports before importing.

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

- [ ] Causally gated fake provider receives tool result after TOOL-end without emitting another event.
- [ ] Slow tool does not prevent audio reception. Serial order, parallel out-of-order completion, IDs and duplicate handling are observable with event gates.
- [ ] No overlapping SDK writes; schema and tool-result framing regressions pass.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- test_tool_result_without_next_provider_event
- test_audio_and_interruption_during_slow_tool
- test_parallel_completion_correlates_ids
- test_sequential_and_same_instance_execution
- test_duplicate_tool_completion_and_final_snapshot

Use behavioral fixtures with real tools/manager where that path is under test. Mock only provider/transport boundaries for conformance. Event gates and patched deadlines should replace timing-sensitive sleeps. Browser tests load the actual demo page. No live test runs are required for automated CI.

Commands to run from the feature worktree using its configured environment (capture output in artifacts/logs/):

```bash
pytest packages/ai-parrot/tests/clients/test_nova_tool_progress.py packages/ai-parrot/tests/clients/test_nova_tool_result.py -q
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
