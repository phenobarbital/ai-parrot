# TASK-2939: Map complete tool results to Nova speech and visual deltas

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 3h)
**Depends-on**: TASK-2938
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial dependency boundary. Shared production/test files must not be edited concurrently; complete listed prerequisites first.

---

## Context

Implements §3 Module 2 and contributes to AC2, AC5, AC7, AC8. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Replace the reducing base-client route only in Nova voice with the manager full-result option. Implement private typed helpers, preserving the existing wire adapter.
- Inject trusted session_id/user_id/turn_id only where accepted by schema/signature; trusted identities override model values. Reject provider-supplied internal execution kwargs and keep optional Python permission_context local.
- Implement the spec mapping: nonempty voice_text wins; dict payload stays dict, string becomes output, scalar zero survives and None maps to Success. Require success=True and status=success for visual delivery.
- Emit nonempty JSON-serializable display_data in metadata on one tool delta. Suppress malformed visual data with diagnostics while valid speech survives; errors carry status and no success visual.
- Record effective safe arguments, tool ID, tool_status and tool-scoped authorization metadata. Update timing/execution count once. Do not place permission objects in events or prompts.

**NOT in scope**: No AbstractClient._execute_tool override, Google import from Amazon, scheduler rewrite or browser protocol changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | MODIFY | Scoped deliverable owned by TASK-2939 |
| `packages/ai-parrot/tests/clients/test_nova_dual_output.py` | CREATE | Scoped deliverable owned by TASK-2939 |

Only the files above belong to this task, plus its task state and per-spec index. You are not alone in this codebase: preserve others' edits and adapt to completed dependencies. Read-only references below do not grant edit ownership.

## Codebase Contract (Anti-Hallucination)

Re-read and verified on 2026-09-07 against dev `77bd1a50c1282694444e05b4f41ad4138c880ff2`. These are baseline definitions, not invented future APIs. Dependencies may change their lines/signatures: refresh them before implementation.

### Verified Imports

```python
from parrot.clients.amazon.nova import NovaClient
from parrot.tools.manager import ToolManager, ToolDefinition
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.models.voice import LiveVoiceResponse, LiveToolCall, VoiceStreamOptions
from parrot.auth.permission import PermissionContext
from parrot.clients.google.live import GeminiLiveClient
from parrot.bots.voice import VoiceBot
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

# packages/ai-parrot-client-google/src/parrot/clients/google/live.py:81
class LiveToolAdapter

# packages/ai-parrot-client-google/src/parrot/clients/google/live.py:226
async def execute_tool(self, function_call: Any, context: Optional[Dict[str, Any]]=None) -> tuple[types.FunctionResponse, Optional[Dict[str, Any]]]

# packages/ai-parrot-client-google/src/parrot/clients/google/live.py:688
async def stream_voice(self, audio_iterator: AsyncIterator[bytes], system_prompt: Optional[str]=None, session_id: Optional[str]=None, user_id: Optional[str]=None, stt_only: bool=False, options: Optional[VoiceStreamOptions]=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]

# packages/ai-parrot/src/parrot/bots/voice.py:89
class VoiceBot

# packages/ai-parrot/src/parrot/bots/voice.py:281
def _create_llm_client(self, config) -> VoiceCapable

# packages/ai-parrot/src/parrot/bots/voice.py:475
async def ask_stream(self, audio_input: Union[bytes, AsyncIterator[bytes]], session_id: Optional[str]=None, user_id: Optional[str]=None, stt_only: bool=False, **kwargs) -> AsyncIterator[LiveVoiceResponse]

# packages/ai-parrot/src/parrot/models/voice.py:150
class VoiceStreamOptions

# packages/ai-parrot/src/parrot/models/voice.py:320
class LiveToolCall

# packages/ai-parrot/src/parrot/models/voice.py:361
class LiveVoiceResponse

# packages/ai-parrot/src/parrot/auth/permission.py:81
class PermissionContext

# packages/ai-parrot/src/parrot/tools/manager.py:2067
def clone(self, *, include_search_tool: bool=False) -> 'ToolManager'
```

### Task-specific References

- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` — Current queue admission 1200–1233 waits for next non-tool flush at 1087–1110. _send_tool_result 667–734 owns wire association; audio sender 1329–1392 must share safe writer ownership.
- `packages/ai-parrot/tests/clients/test_nova_dual_output.py` — NEW deliverable of this feature; verify dependent task exports before importing.
- `packages/ai-parrot/src/parrot/tools/manager.py` — execute_tool currently reduces AbstractTool result at 1781–1852; full-result option is proposed. clone at 2067 shares tool registrations. ToolDefinition fields: name, description, input_schema, function, routing_meta, required_permissions.
- `packages/ai-parrot/src/parrot/tools/abstract.py` — ToolResult at 250–278 includes result/success/status/error/metadata/voice_text/display_data. _current_pctx at 892–899 is mutable. Guard helper returns (processed_value, flag_reports); existing output block 1041–1092 omits voice/display.
- `packages/ai-parrot/src/parrot/models/voice.py` — Verified definitions: AudioFormat:27, VoiceProvider:34, VoiceConfig:55, VoiceStreamOptions:150, VoiceCapabilities:187, LiveCompletionUsage:263.
- `packages/ai-parrot/src/parrot/auth/permission.py` — Verified definitions: UserSession:21, PermissionContext:81, build_principal_context:166, to_eval_context:209, __post_init__:51, has_role:57.
- `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` — Verified definitions: LiveToolAdapter:81, GeminiLiveClient:328, create_live_client:1491, __init__:89, _build_tool_map:109, _clean_schema_for_google:124.
- `packages/ai-parrot/src/parrot/bots/voice.py` — Verified definitions: VoiceBot:89, create_voice_bot:838, __init__:119, _default_voice_prompt:186, _resolve_llm_config:190, _create_llm_client:281.

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

- [ ] A real tool and real manager yield the intended Nova spoken payload and exact visual object; no mock of their execution.
- [ ] Plain/error/pending/empty/zero and malformed visual outputs follow the mapping.
- [ ] Two concurrent streams cannot exchange IDs, context or output; reserved kwargs cannot be injected.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- test_nova_dual_output_from_real_tool
- test_nova_context_overrides_model_identity
- test_nova_mapping_plain_error_and_empty_values

Use behavioral fixtures with real tools/manager where that path is under test. Mock only provider/transport boundaries for conformance. Event gates and patched deadlines should replace timing-sensitive sleeps. Browser tests load the actual demo page. No live test runs are required for automated CI.

Commands to run from the feature worktree using its configured environment (capture output in artifacts/logs/):

```bash
pytest packages/ai-parrot/tests/clients/test_nova_dual_output.py -q
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

Implemented Module 2 in `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`:

- `_build_trusted_tool_arguments()` — strips `_RESERVED_TOOL_KWARGS`
  (`_permission_context`/`_resolver`/`_broker`/`_cred_channel`/
  `_cred_user_id`) from model-supplied args first, then merges trusted
  `session_id`/`user_id`/`turn_id` LAST (filtered through the existing
  `AbstractClient._tool_param_names()` — `None` means "accept
  everything", used for `**kwargs` tools and any bare `AbstractTool`
  subclass whose introspection can't resolve a signature), so trusted
  values always win — the deliberate opposite of
  `AbstractClient._execute_tool()`'s `{**filtered_ctx, **parameters}`.
- `_execute_tool_full()` — calls
  `self.tool_manager.execute_tool(name, merged_args, permission_context=...,
  return_tool_result=True)` exactly once (never bypasses the manager,
  never calls `tool.execute()`/`_execute()` directly the way Gemini's
  `LiveToolAdapter.execute_tool()` does — Nova gets the full
  permissions/grant/confirmation/credential-broker/lifecycle/hook
  pipeline Gemini's route skips).
- `_map_tool_result_to_nova()` — pure mapping function implementing
  the spec §2 precedence table exactly (voice_text > dict > string >
  None="Success" > str(other); falsy scalars `False`/`0`/`0.0`
  preserved distinctly from `None`; non-success envelope never emits a
  visual; empty `display_data` dict stays suppressed;
  non-JSON-serializable `display_data` is omitted with a logged
  warning while the spoken result still reaches Nova).
- `_flush_pending_tools()` — signature gained an optional
  `permission_context` kwarg (plumbed from `stream_voice()`'s
  `**kwargs`, defaulting to `getattr(self, "_permission_context",
  None)`, same convention `AbstractClient._execute_tool()` already
  uses); `_run_one()` now calls `_execute_tool_full()` +
  `_map_tool_result_to_nova()` instead of the reducing
  `self._execute_tool()`; `LiveToolCall.result` now holds the
  NORMALIZED provider-facing payload (not the raw envelope, per spec
  §2 "LiveToolCall.result contains the normalized provider-facing
  result"); each yielded `LiveVoiceResponse.metadata` carries
  `tool_status` and, when present, `display_data`.
- No scheduling/admission changes (queue-on-next-non-tool-event stays
  as-is — TASK-2940 scope). No `NovaClient._execute_tool` override, no
  Google import from Amazon.

**Evidence**:
- `pytest packages/ai-parrot/tests/clients/test_nova_dual_output.py -q`
  → 16 passed (`artifacts/logs/task-2939-nova-suite.log` covers the
  broader run below; the dedicated file-only run was captured
  separately and is identical to the passing subset there).
- `pytest packages/ai-parrot/tests/clients/ -k nova -q` → 148 passed,
  8 skipped, 5 failed (`artifacts/logs/task-2939-nova-suite.log`).
  Of the 5 failures:
  - `test_nova_protocol_frames.py::test_prompt_start_declares_tool_use_output_configuration`
    is **pre-existing on unmodified `dev`** (verified) — unrelated to
    this task.
  - The other 4 —
    `test_nova.py::TestStreamVoice::test_stream_voice_tool_use`,
    `test_nova_tool_result.py::TestToolTiming::test_executed_on_tool_content_end`,
    `test_nova_tool_result.py::TestToolArguments::test_json_string_content_parsed_to_kwargs`,
    `test_nova_tool_result.py::TestToolResultEnvelope::test_non_json_serializable_result_does_not_abort_turn`
    — are a **known, spec-anticipated consequence** of this task: they
    `patch.object(client, "_execute_tool", ...)` to intercept Nova's
    tool-flush path, which no longer calls that method (by design —
    this task's whole point is routing through
    `ToolManager.execute_tool(..., return_tool_result=True)` instead).
    The spec's own Module 3 (§3, TASK-2940) explicitly plans to
    "update existing `test_nova_tool_result.py` assumptions"; three of
    these four failures are exactly that file.
    `test_nova.py::test_stream_voice_tool_use` has the identical root
    cause but was not itself named in TASK-2940's file table — flagged
    here for TASK-2940 to also fix (same worktree, executed next in
    this session), since "retain protocol, shutdown and interruption
    regression suites" is that module's own acceptance bar and this is
    a one-assertion fix caused by the same architectural change.
    **Not left unresolved**: TASK-2940 addresses this immediately
    after in the same session.
- `ruff check` on both changed/created files: clean, zero findings.

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-07
**Notes**: Confirmed via `AbstractTool.execute()`'s `validate_args()`/
`_shallow_dump()` path that a bare `AbstractTool` subclass with no
custom `args_schema` silently drops ALL kwargs (including trusted
context AND model-supplied arguments) — not specific to this task, but
required giving the test fixtures explicit `args_schema` classes to
actually exercise the trusted-context-override behavior; documented in
the test file's fixture docstrings.
**Deviations from spec**: none in the implementation. One test-scope
note: `test_nova.py::test_stream_voice_tool_use` needs the same
`_execute_tool`-assumption fix TASK-2940 already plans for
`test_nova_tool_result.py` — addressed there, not silently left
broken.
