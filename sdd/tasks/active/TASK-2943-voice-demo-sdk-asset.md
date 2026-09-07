# TASK-2943: Serve the locked LiveKit SDK to the Voice demo

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 2h)
**Depends-on**: TASK-2942
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run alongside TASK-2944; owns server.py and SDK route tests only.

---

## Context

Implements §3 Module 5 and contributes to AC12, AC14, AC16. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Add the exact /voice-assets/livekit-client.umd.js route for the installed UI dependency dist/livekit-client.umd.js. Resolve its repository package/symlink path and check the selected file exists.
- Expose only asset URL and availability through existing rendered __CONFIG__ bootstrap, preserving its single anchored replacement.
- Handle missing installation with a controlled response and avatar-unavailable config while both voice routes still work. Do not mount node_modules or allow arbitrary asset paths.
- Verify the installed artifact matches the existing lock (2.22.1); no manifest upgrade, CDN latest fallback or separate build. If not installed, record the prerequisite.

**NOT in scope**: No avatar controller/HTML integration or demo tool changes; TASK-2948 edits server.py only after this task.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/voice/server.py` | MODIFY | Scoped deliverable owned by TASK-2943 |
| `packages/ai-parrot-integrations/tests/voice/test_voice_demo_assets.py` | CREATE | Scoped deliverable owned by TASK-2943 |

Only the files above belong to this task, plus its task state and per-spec index. You are not alone in this codebase: preserve others' edits and adapt to completed dependencies. Read-only references below do not grant edit ownership.

## Codebase Contract (Anti-Hallucination)

Re-read and verified on 2026-09-07 against dev `77bd1a50c1282694444e05b4f41ad4138c880ff2`. These are baseline definitions, not invented future APIs. Dependencies may change their lines/signatures: refresh them before implementation.

### Verified Imports

```python
from aiohttp import web
```

Imports are verified from local definitions/usage, not an all-package runtime smoke. Browser SDK access is through the existing livekit-client package exposed as LivekitClient UMD; the controller accepts an injected SDK in tests.

### Existing Signatures to Use

```python
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
```

### Task-specific References

- `examples/clients/voice/server.py` — index_handler injects window.__CONFIG__ once; build_app mounts /ws/gemini, /ws/nova and /static/. Existing get_weather returns a plain string; factories copy a shared tool list.
- `packages/ai-parrot-integrations/tests/voice/test_voice_demo_assets.py` — NEW deliverable of this feature; verify dependent task exports before importing.
- `packages/ai-parrot-server/ui/package.json` — Existing livekit-client ^2.19.2 at line 45; test script runs vitest run. Use the existing installation, no new package.
- `packages/ai-parrot-server/ui/pnpm-lock.yaml` — Lines 92–94 resolve livekit-client 2.22.1. The installed UMD artifact may be absent; verify prerequisite during implementation.
- `examples/clients/voice/static/dual_provider.html` — handleMessage 1112–1158 lacks display_data/tool_call/avatar handling. startSession 1161–1173 sends config only. queueAudioChunk/playStreamingAudio at 1368 onward drive local PCM. Existing startRecording rejects !canSpeak.

### Does NOT Exist

- No root parrot/ source tree; use workspace package paths. No model-native JSON-schema voice output is added.
- No shared last-result storage or LiveVoiceResponse.display_data attribute; structured output uses response.metadata["display_data"].
- The demo avatar controller and /voice-assets/livekit-client.umd.js route are NEW; no existing exports or route should be assumed.
- The admin Svelte viewer is not importable into standalone HTML. No second REST avatar session or microphone publication is allowed.

## Implementation Notes

### Pattern to Follow

Use the task-specific source anchors and spec §2 behavior. Preserve existing execution/transport ownership. Keep helpers typed and private where possible; match Python black and frontend prettier conventions.

### Key Constraints

- No new dependencies or unrelated refactors. No production change to AbstractClient or GeminiLiveClient.
- Keep secrets/permission objects out of provider arguments, browser panels and logs.
- Follow the task DAG and file ownership above; report cross-scope failures to the owning task.
- Save exact verification commands and results under artifacts/logs/ and reference them in completion notes.

## Acceptance Criteria

- [ ] Known fixture SDK file serves successfully; absent file reports unavailable without breaking the page or provider routes.
- [ ] Traversal/arbitrary node_modules requests cannot read unrelated files.
- [ ] Configuration is valid JavaScript/JSON and contains no credentials.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- test_voice_demo_sdk_route_is_scoped
- test_voice_demo_missing_sdk_keeps_voice_routes
- test_voice_demo_config_bootstrap

Use behavioral fixtures with real tools/manager where that path is under test. Mock only provider/transport boundaries for conformance. Event gates and patched deadlines should replace timing-sensitive sleeps. Browser tests load the actual demo page. No live test runs are required for automated CI.

Commands to run from the feature worktree using its configured environment (capture output in artifacts/logs/):

```bash
pytest packages/ai-parrot-integrations/tests/voice/test_voice_demo_assets.py -q
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
