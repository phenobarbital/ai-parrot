# TASK-2946: Prove Gemini/Nova dual output through real tools and VoiceBot

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 4h)
**Depends-on**: TASK-2945
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run alongside TASK-2946/TASK-2947/TASK-2948 after TASK-2945; each owns disjoint files. Read-only references confer no edit ownership.

---

## Context

Implements §3 Modules 4 and 6 and contributes to AC1, AC2, AC3, AC4, AC5, AC6, AC8, AC9, AC10, AC11. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Extend provider-boundary fixtures for the same deterministic real voice-aware AbstractTool on Gemini and Nova; compare semantic spoken and visual output.
- Add actual VoiceBot → Nova → _AskStreamVoiceClient/_HandlerVoiceSession tests with a real manager, capturing provider toolResult, PCM, one display frame and one tool event.
- Include the real VoiceAvatarSession over fake HTTP/avatar/room transports; assert identical PCM, finish/interrupt/close and failure fallback.
- Exercise interleaved sessions, later turns, final-only tools and delta/final dedup. Use a causally gated provider fixture for tool progress.
- Run focused feature and existing conformance/enforcement/protocol regressions, retaining commands/results in artifacts/logs. Fix production failures via the owning scoped task, not unplanned code edits here.

**NOT in scope**: No production changes and no cloud calls. Automated conformance does not establish operational homologation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/voice/test_nova_dual_output_integration.py` | CREATE | Scoped deliverable owned by TASK-2946 |
| `packages/ai-parrot/tests/voice/conftest.py` | MODIFY | Scoped deliverable owned by TASK-2946 |
| `packages/ai-parrot/tests/voice/test_provider_conformance.py` | MODIFY | Scoped deliverable owned by TASK-2946 |

Only the files above belong to this task, plus its task state and per-spec index. You are not alone in this codebase: preserve others' edits and adapt to completed dependencies. Read-only references below do not grant edit ownership.

## Codebase Contract (Anti-Hallucination)

Re-read and verified on 2026-09-07 against dev `77bd1a50c1282694444e05b4f41ad4138c880ff2`. These are baseline definitions, not invented future APIs. Dependencies may change their lines/signatures: refresh them before implementation.

### Verified Imports

```python
from parrot.clients.amazon.nova import NovaClient
from parrot.clients.google.live import GeminiLiveClient
from parrot.bots.voice import VoiceBot
from parrot.tools.manager import ToolManager, ToolDefinition
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.models.voice import LiveVoiceResponse, LiveToolCall, VoiceStreamOptions
from parrot.voice.handler import VoiceChatHandler, WebSocketConnection
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession
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

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:184
class WebSocketConnection

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:296
class _AskStreamVoiceClient

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:353
class _HandlerVoiceSession

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:370
def build_frames(self, resp, turn_no: int) -> list

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:510
async def _relay(self, resp, turn_no: int) -> None

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:1631
async def _run_voice_session(self, connection: WebSocketConnection) -> None

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:1688
async def _send_voice_response(self, connection: WebSocketConnection, response: Any) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:55
class VoiceAvatarSession

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:223
async def speak(self, pcm: bytes) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:235
async def finish_turn(self) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:243
async def interrupt(self) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:252
async def aclose(self) -> None

# packages/ai-parrot/src/parrot/models/voice.py:150
class VoiceStreamOptions

# packages/ai-parrot/src/parrot/models/voice.py:320
class LiveToolCall

# packages/ai-parrot/src/parrot/models/voice.py:361
class LiveVoiceResponse

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:1274
async def _handle_start_recording(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:208
def viewer_credentials(self) -> dict[str, str]

# packages/ai-parrot/src/parrot/tools/manager.py:2067
def clone(self, *, include_search_tool: bool=False) -> 'ToolManager'
```

### Task-specific References

- `packages/ai-parrot-integrations/tests/voice/test_nova_dual_output_integration.py` — NEW deliverable of this feature; verify dependent task exports before importing.
- `packages/ai-parrot/tests/voice/conftest.py` — Provider SDK boundaries are mocked; existing build_gemini_client/build_nova_client and collect_responses are verified definitions. Add causal gates, not just preloaded arrays.
- `packages/ai-parrot/tests/voice/test_provider_conformance.py` — Current tests cover options, canonical roles, reconnect and capability honesty; they do not prove real-tool dual output.
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` — Current queue admission 1200–1233 waits for next non-tool flush at 1087–1110. _send_tool_result 667–734 owns wire association; audio sender 1329–1392 must share safe writer ownership.
- `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` — Verified definitions: LiveToolAdapter:81, GeminiLiveClient:328, create_live_client:1491, __init__:89, _build_tool_map:109, _clean_schema_for_google:124.
- `packages/ai-parrot/src/parrot/bots/voice.py` — Verified definitions: VoiceBot:89, create_voice_bot:838, __init__:119, _default_voice_prompt:186, _resolve_llm_config:190, _create_llm_client:281.
- `packages/ai-parrot/src/parrot/tools/manager.py` — execute_tool currently reduces AbstractTool result at 1781–1852; full-result option is proposed. clone at 2067 shares tool registrations. ToolDefinition fields: name, description, input_schema, function, routing_meta, required_permissions.
- `packages/ai-parrot/src/parrot/tools/abstract.py` — ToolResult at 250–278 includes result/success/status/error/metadata/voice_text/display_data. _current_pctx at 892–899 is mutable. Guard helper returns (processed_value, flag_reports); existing output block 1041–1092 omits voice/display.
- `packages/ai-parrot/src/parrot/models/voice.py` — Verified definitions: AudioFormat:27, VoiceProvider:34, VoiceConfig:55, VoiceStreamOptions:150, VoiceCapabilities:187, LiveCompletionUsage:263.
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py` — display_data.data and tool_call frames at 437–458 and 1749–1778. Avatar request/response at 1150–1214 uses top-level avatar/tenant_id/avatar_id and viewer credentials. start_recording currently invokes start_turn without avatar interruption.
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py` — viewer_credentials returns only livekit_url/client_token/room. speak forwards 24 kHz PCM unchanged. Session teardown method is aclose(), not close().
- `packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py` — Verified definitions: _capable_mock_client:28, handler:60, connection:75, _sent_types:85, TestHandlerRefactor:89, TestFrameProtocolUnchanged:148.
- `packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py` — Verified definitions: handler:26, connection:41, test_gemini_audio_to_avatar_end_to_end:56, test_gemini_audio_mid_turn_no_finish:94, test_barge_in_clears_avatar:112, test_pcm_bytes_unchanged_no_resample:131.
- `packages/ai-parrot/tests/clients/test_live_tool_routing.py` — Verified definitions: VoiceTool:13, ForbiddenTool:25, ErroringTool:48, plain_callable:56, _call:60, live_client:65.

### Does NOT Exist

- No root parrot/ source tree; use workspace package paths. No model-native JSON-schema voice output is added.
- No shared last-result storage or LiveVoiceResponse.display_data attribute; structured output uses response.metadata["display_data"].
- The demo avatar controller and /voice-assets/livekit-client.umd.js route are NEW; no existing exports or route should be assumed.
- The admin Svelte viewer is not importable into standalone HTML. No second REST avatar session or microphone publication is allowed.
- Passing mocked provider/browser tests is not proof of a real AWS/Gemini/LiveAvatar session.

## Implementation Notes

### Pattern to Follow

Use the task-specific source anchors and spec §2 behavior. Preserve existing execution/transport ownership. Keep helpers typed and private where possible; match Python black and frontend prettier conventions.

### Key Constraints

- No new dependencies or unrelated refactors. No production change to AbstractClient or GeminiLiveClient.
- Keep secrets/permission objects out of provider arguments, browser panels and logs.
- Follow the task DAG and file ownership above; report cross-scope failures to the owning task.
- Save exact verification commands and results under artifacts/logs/ and reference them in completion notes.

## Acceptance Criteria

- [ ] No mocks replace stream_voice, _execute_tool or ToolManager.execute_tool on paths intended to prove dual output.
- [ ] Both real provider adapters preserve speech and structured data; tool executes once and context/results remain isolated.
- [ ] Avatar errors preserve WebSocket output and inherited VoiceSession continues to invoke VoiceBot.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- test_provider_dual_output_conformance
- test_voicebot_nova_websocket_tool_audio_display
- test_voicebot_nova_avatar_audio_and_lifecycle
- test_avatar_failure_preserves_websocket_delivery
- test_two_voice_sessions_do_not_mix_results
- test_tool_final_only_and_next_turn_id_reuse

Use behavioral fixtures with real tools/manager where that path is under test. Mock only provider/transport boundaries for conformance. Event gates and patched deadlines should replace timing-sensitive sleeps. Browser tests load the actual demo page. No live test runs are required for automated CI.

Commands to run from the feature worktree using its configured environment (capture output in artifacts/logs/):

```bash
pytest packages/ai-parrot-integrations/tests/voice/test_nova_dual_output_integration.py packages/ai-parrot/tests/voice/conftest.py packages/ai-parrot/tests/voice/test_provider_conformance.py -q
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

Created `packages/ai-parrot-integrations/tests/voice/test_nova_dual_output_integration.py`
(6 tests, all real path — only Nova's own SDK-transport boundary is
mocked): a real `VoiceBot` (with a real `ToolManager`/`AbstractTool`
registered via normal construction) has its `_llm` wired to the SAME
real `NovaClient` `VoiceBot._create_llm_client()` would build, with only
`_open_stream`/`_send_event`/`_iter_events` mocked; turns are driven
through the real `_AskStreamVoiceClient.stream_voice()` (→
`VoiceBot.ask_stream()` → Nova's real `stream_voice()`) and relayed
through a real `_HandlerVoiceSession._relay()`/`build_frames()` — the
exact objects `VoiceChatHandler._run_voice_session()` constructs in
production. `test_voicebot_nova_websocket_tool_audio_display` proves
exactly one `tool_call` frame, one `display_data` frame and the correct
audio bytes reach the WebSocket. `test_voicebot_nova_avatar_audio_and_lifecycle`
(+ a barge-in variant) proves identical PCM reaches a real
`VoiceAvatarSession` over `patched_stack` (FEAT-245) and
`finish_turn`/`interrupt` forward correctly.
`test_avatar_failure_preserves_websocket_delivery` proves an avatar
transport exception never blocks the browser's audio/tool/display
frames. `test_two_voice_sessions_do_not_mix_results` runs two fully
independent bot/tool/connection/session sets concurrently
(`asyncio.gather`) and proves zero cross-talk. 
`test_tool_final_only_and_next_turn_id_reuse` uses a genuine causal gate
(`_GatedEchoTool` awaiting a test-controlled `asyncio.Event`, NOT a
sleep or a preloaded-array assumption) to deterministically force Nova's
real `_drain_admitted_tools()` branch (tool still running when
`completionEnd` arrives) and proves the resulting tool is still
delivered exactly once at the WS-frame level, then reuses the same
`tool_use_id` in a second turn and proves it is delivered again (no
stale cross-turn dedup).

Extended `packages/ai-parrot/tests/voice/conftest.py` (Module 9's shared
provider-conformance fixtures, backward compatible — every new
parameter is optional/keyword-only with a default that reproduces the
prior behavior exactly) with `VoiceAwareEchoTool`/`make_tool_manager()`
(the same deterministic real tool for both providers),
`gemini_tool_call_events()`/`nova_tool_call_events()`, a new
`"tool_call"` scenario on `build_gemini_client()`/`build_nova_client()`/
`build_client()`, and `gated_nova_iter_events()` — a reusable two-phase
causal-gate Nova event iterator (pre-gate events, suspend on an
`asyncio.Event`, post-gate events) satisfying the Codebase Contract's
"add causal gates, not just preloaded arrays" note, available for future
tests in this directory even though this task's own conformance test
did not need timing control.

Added `TestDualOutputConformance::test_provider_dual_output_conformance`
to `test_provider_conformance.py` (parametrized Gemini/Nova via the
existing `provider` fixture): the same tool executes exactly once per
provider (deduped by id when flattening — Nova's own architecture
re-lists an already-delivered call in its final completion snapshot;
that is a Python-object-level fact distinct from the WS-frame-level
dedup already proven in the new integration file) and both providers
converge on the identical `{"output": "Echo: weather"}` spoken shape and
`{"topic": "weather", "kind": "echo"}` visual shape via
`metadata["display_data"]`.

Verification:
- `pytest packages/ai-parrot-integrations/tests/voice/test_nova_dual_output_integration.py`
  — 6 passed (`artifacts/logs/TASK-2946-pytest-integration.log`).
- `pytest packages/ai-parrot/tests/voice/conftest.py
  packages/ai-parrot/tests/voice/test_provider_conformance.py` — 26
  passed, 2 failed
  (`artifacts/logs/TASK-2946-pytest-conformance.log`).
- `ruff check` clean on all three files.

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-09-07
**Notes**: The 2 failures in `test_provider_conformance.py`
(`TestCanonicalEnvelope::test_user_and_assistant_both_present[gemini]`,
`TestDropInEquivalence::test_role_sequence_structurally_identical`) are
PRE-EXISTING on baseline `dev` — confirmed by `git stash`-ing every file
this task touched (including `conftest.py`) and re-running the exact
same two tests, which still failed identically with my changes fully
removed. A third pre-existing failure,
`test_voice_session.py::TestVoiceSession::test_no_aiohttp_import`, was
also confirmed pre-existing the same way when it appeared in a
directory-wide run. None of these three are in this task's file scope
(`test_provider_conformance.py`'s two failing tests predate this task's
new `TestDualOutputConformance` class and are unrelated to it;
`test_voice_session.py` is not a file this task touches at all) — they
are reported here for the code reviewer's visibility, not fixed, per
the task's explicit instruction to "Fix production failures via the
owning scoped task, not unplanned code edits here." Running the full
`packages/ai-parrot/tests/voice/` and
`packages/ai-parrot-integrations/tests/voice/` directories in a SINGLE
pytest invocation together raises an unrelated `ImportPathMismatchError`
(both packages' `tests/voice/conftest.py` collide on the module name
`tests.voice.conftest` because neither package tree has `__init__.py`
markers) — a pre-existing, repo-wide pytest-configuration fact
(each package has its own `pyproject.toml`/test root), not something
this task's file scope can or should change; verification commands
above run each package's voice test directory as a separate invocation.
**Deviations from spec**: none recorded
