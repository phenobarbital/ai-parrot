# TASK-2948: Add shared dual-output demo tool and acceptance runbook

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 3h)
**Depends-on**: TASK-2945
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run alongside TASK-2946/TASK-2947/TASK-2948 after TASK-2945; each owns disjoint files. Read-only references confer no edit ownership.

---

## Context

Implements §3 Module 6 and §4 Real-live acceptance and contributes to AC2, AC12, AC13. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Replace the plain demo weather tool with a deterministic voice-aware AbstractTool producing a short voice_text, structured display_data and result. Keep equivalent definition/behavior but instantiate fresh mutable tools per bot factory.
- Include a bounded controllable slow-tool example/scenario so the real-live interruption acceptance can actually be exercised; clearly label any data as demo fixtures.
- Document launch, provider setup, existing locked LiveKit SDK prerequisite, avatar tenant/agent opt-in and server configuration, and the actual page controls.
- Correct stale Gemini-only/model-path and unconditional-avatar-audio statements in the frontend guide. Describe fallback until actual playability and existing top-level session/credential fields.
- Provide exact acceptance steps for both providers with/without avatar, second turn, tool interruption, reconnect/switch and failure fallback. Link the final evidence report destination without claiming it already passed.

**NOT in scope**: No HTML/controller changes, new voice provider or live acceptance claim. Serialize server.py edits after TASK-2943.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/voice/server.py` | MODIFY | Scoped deliverable owned by TASK-2948 |
| `packages/ai-parrot-integrations/tests/voice/test_voice_demo_tools.py` | CREATE | Scoped deliverable owned by TASK-2948 |
| `examples/clients/voice/README.md` | MODIFY | Scoped deliverable owned by TASK-2948 |
| `docs/frontend/voicebot-realtime-frontend-guide.md` | MODIFY | Scoped deliverable owned by TASK-2948 |

Only the files above belong to this task, plus its task state and per-spec index. You are not alone in this codebase: preserve others' edits and adapt to completed dependencies. Read-only references below do not grant edit ownership.

## Codebase Contract (Anti-Hallucination)

Re-read and verified on 2026-09-07 against dev `77bd1a50c1282694444e05b4f41ad4138c880ff2`. These are baseline definitions, not invented future APIs. Dependencies may change their lines/signatures: refresh them before implementation.

### Verified Imports

```python
from aiohttp import web
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager, ToolDefinition
from parrot.bots.voice import VoiceBot
from parrot.models.voice import LiveVoiceResponse, LiveToolCall, VoiceStreamOptions
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

# examples/clients/voice/server.py:116
def get_weather(location: str) -> str

# examples/clients/voice/server.py:155
def make_gemini_bot() -> VoiceBot

# examples/clients/voice/server.py:165
def make_nova_bot() -> VoiceBot

# examples/clients/voice/server.py:239
async def index_handler(request: web.Request) -> web.Response

# examples/clients/voice/server.py:276
def build_app() -> web.Application

# packages/ai-parrot/src/parrot/tools/manager.py:2067
def clone(self, *, include_search_tool: bool=False) -> 'ToolManager'

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py:58
def is_avatar_enabled(*, tenant_id: Optional[str], agent_name: Optional[str]=None) -> bool
```

### Task-specific References

- `examples/clients/voice/server.py` — index_handler injects window.__CONFIG__ once; build_app mounts /ws/gemini, /ws/nova and /static/. Existing get_weather returns a plain string; factories copy a shared tool list.
- `packages/ai-parrot-integrations/tests/voice/test_voice_demo_tools.py` — NEW deliverable of this feature; verify dependent task exports before importing.
- `examples/clients/voice/README.md` — Existing Dual VoiceChatHandler Provider-Switch Demo run instructions refer to server.py and static/dual_provider.html. Retain that harness.
- `docs/frontend/voicebot-realtime-frontend-guide.md` — Existing sections describe WebSocket and avatar fields, but Gemini-only construction at 69, unconditional mute guidance around 413 and historical client path at 670 need correction.
- `packages/ai-parrot/src/parrot/tools/abstract.py` — ToolResult at 250–278 includes result/success/status/error/metadata/voice_text/display_data. _current_pctx at 892–899 is mutable. Guard helper returns (processed_value, flag_reports); existing output block 1041–1092 omits voice/display.
- `packages/ai-parrot/src/parrot/tools/manager.py` — execute_tool currently reduces AbstractTool result at 1781–1852; full-result option is proposed. clone at 2067 shares tool registrations. ToolDefinition fields: name, description, input_schema, function, routing_meta, required_permissions.
- `packages/ai-parrot/src/parrot/bots/voice.py` — Verified definitions: VoiceBot:89, create_voice_bot:838, __init__:119, _default_voice_prompt:186, _resolve_llm_config:190, _create_llm_client:281.
- `packages/ai-parrot/src/parrot/models/voice.py` — Verified definitions: AudioFormat:27, VoiceProvider:34, VoiceConfig:55, VoiceStreamOptions:150, VoiceCapabilities:187, LiveCompletionUsage:263.
- `examples/clients/voice/static/dual_provider.html` — handleMessage 1112–1158 lacks display_data/tool_call/avatar handling. startSession 1161–1173 sends config only. queueAudioChunk/playStreamingAudio at 1368 onward drive local PCM. Existing startRecording rejects !canSpeak.
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py` — is_avatar_enabled is the existing tenant/agent default-deny gate; viewer does not bypass it.
- `packages/ai-parrot-server/ui/package.json` — Existing livekit-client ^2.19.2 at line 45; test script runs vitest run. Use the existing installation, no new package.
- `packages/ai-parrot-server/ui/pnpm-lock.yaml` — Lines 92–94 resolve livekit-client 2.22.1. The installed UMD artifact may be absent; verify prerequisite during implementation.

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

- [ ] Both factories create separate real tools with identical spoken/visual behavior; tests do not require cloud credentials.
- [ ] Runbook uses existing /ws/gemini and /ws/nova page and explains missing SDK/services without adding dependencies.
- [ ] Documented matrix matches spec §4/AC13 and includes how to trigger a slow tool and explicit interruption.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- test_voice_demo_factories_do_not_share_tools
- test_voice_demo_tool_returns_speech_and_display
- test_voice_demo_slow_tool_is_bounded

Use behavioral fixtures with real tools/manager where that path is under test. Mock only provider/transport boundaries for conformance. Event gates and patched deadlines should replace timing-sensitive sleeps. Browser tests load the actual demo page. No live test runs are required for automated CI.

Commands to run from the feature worktree using its configured environment (capture output in artifacts/logs/):

```bash
pytest packages/ai-parrot-integrations/tests/voice/test_voice_demo_tools.py -q
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
