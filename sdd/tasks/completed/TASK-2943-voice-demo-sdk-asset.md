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

Implemented `_UI_PACKAGE_DIR`/`_LIVEKIT_UMD_ROUTE`/`_resolve_livekit_umd_path()`
and `voice_assets_livekit_handler()` in `examples/clients/voice/server.py`.
The route resolves `packages/ai-parrot-server/ui/node_modules/livekit-client/
dist/livekit-client.umd.js`, validates the resolved real path stays inside
the package directory (`Path.relative_to()` — rejects a symlink-escape),
and returns a controlled 503 (`text/plain`, "not installed for the UI
workspace ... run its install step") when the artifact is absent — the
sandbox's actual state, since `packages/ai-parrot-server/ui/node_modules`
is not installed here. `index_handler()`'s `__CONFIG__` bootstrap gained
an `"avatar": {"sdkUrl": ..., "available": ...}` section via the existing
single anchored `str.replace(..., count=1)` — no second replacement call
added, no credentials in the payload. `build_app()` registers the new
route alongside the existing `/ws/gemini`, `/ws/nova`, `/static/` mounts;
those routes and the index page are unaffected when the SDK is missing.

Created `packages/ai-parrot-integrations/tests/voice/test_voice_demo_assets.py`
(11 tests, all passing) covering: a fixture UMD file serving successfully
with the correct content-type; the real missing-SDK case returning 503
with an "not installed" message; traversal-shaped adjacent URLs failing
to route to the handler (404/400, no path parameter exists on the route);
a symlink-escape defense-in-depth test (`_resolve_livekit_umd_path()`
returns `None` when a `dist` symlink points outside the package dir);
`/health/gemini`, `/`, and both `/ws/*` routes staying mounted/working
with the SDK missing; `window.__CONFIG__` bootstrap JSON validity via a
`json.JSONDecoder().raw_decode()`-based extractor (robust to semicolons
inside nested config strings); the avatar section reflecting both the
available and unavailable cases; no credential-shaped keys in the
rendered config; and a regression guard (`inspect.getsource`) asserting
the templating remains a single anchored `count=1` replace so it cannot
also corrupt the page's `window.__CONFIG__.providers`/`.capabilities`
property-access lines.

Verification: `ruff check` clean on both files
(`artifacts/logs/TASK-2943-ruff.log`); `pytest .../test_voice_demo_assets.py`
— 11 passed (`artifacts/logs/TASK-2943-pytest.log`).

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-09-07
**Notes**: The real `livekit-client` UMD build is not installed in this
sandbox (`packages/ai-parrot-server/ui/node_modules` absent) — a
documented prerequisite per the task's own instructions, not something
this task's test suite can install. The "known fixture SDK file serves
successfully" acceptance criterion is covered via a monkeypatched fixture
file standing in for the real 2.22.1 artifact; the genuinely-missing case
is also covered directly (this sandbox's real state).
**Deviations from spec**: none recorded
