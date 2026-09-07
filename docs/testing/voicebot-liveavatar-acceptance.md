# FEAT-536 — VoiceBot Nova Dual Output + LiveAvatar: Real-Live Operational Acceptance

**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md` §4 ("Real-live acceptance")
**Task**: TASK-2949
**Tested commit**: `9c21135715e1c90370b35918fa659da1fa396f22`
**Branch**: `feat-FEAT-536-voicebot-liveavatar-implementation`
**Date (UTC)**: 2026-09-07
**Environment**: sandboxed autonomous `sdd-worker` CLI session — no interactive human tester,
no outbound access to Google/AWS/LiveAvatar cloud services, no browser-with-a-human-in-the-loop.

## Result: **NOT RUN — operational acceptance remains pending**

Per this task's own explicit instruction ("If credentials/services/browser interaction are
unavailable, mark affected scenarios NOT RUN with reason and keep this task and operational
acceptance pending; do not mark the feature complete") and its "Does NOT Exist" note ("Passing
mocked provider/browser tests is not proof of a real AWS/Gemini/LiveAvatar session"), **none of
the eight required real-live scenarios below were executed against real providers or a real
LiveAvatar/LiveKit backend**. This is not a failed run — it is an environment that structurally
cannot run it, and this report says so rather than fabricating or inferring a pass from
automated/mocked test evidence.

## Prerequisite check performed at this session (reasons for NOT RUN)

| Prerequisite | Status | Detail |
|---|---|---|
| `GOOGLE_API_KEY` / Vertex AI credentials (Gemini Live) | **Absent** | Not set in this environment; no `env/.env` file present either |
| AWS Bedrock credentials (Nova 2 Sonic) | **Absent** | `AWS_NOVA_SONIC_KEY_ID`/`AWS_NOVA_SONIC_SECRET_KEY`/`AWS_ACCESS_KEY_ID` all unset |
| `aws_sdk_bedrock_runtime` (Nova voice SDK, Python ≥ 3.12) | **Not installed** | `import aws_sdk_bedrock_runtime` fails; the demo's own `NOVA_AVAILABLE` check reports the Nova route unavailable at startup |
| `LIVEAVATAR_API_KEY` / `LIVEAVATAR_AVATAR_ID` (LiveAvatar) | **Absent** | Both unset; `VoiceAvatarSession.start()` would raise `RuntimeError` immediately |
| Real LiveKit room/media server reachability | **Not attempted** | No credentials to mint tokens against; no outbound network access to a real LiveKit deployment from this sandbox |
| Interactive human tester / real browser session | **Absent** | This session is an autonomous CLI agent; the acceptance matrix below requires a human to hear audio, see lip-synced video, and judge subjective UX (e.g. "does the avatar look right") |
| `packages/ai-parrot-server/ui`'s locked `livekit-client` UMD build | **Present** (2.22.1, matches the locked `pnpm-lock.yaml` resolution) | Confirmed installed and served correctly by `/voice-assets/livekit-client.umd.js` in this sandbox — the ONE prerequisite that IS satisfied here |

**What this session's environment DOES have** (recorded for completeness, not as a
substitute for the above): Python 3.12.3; `playwright==1.52.0` with a working headless
Chromium (`chromium-1169`) confirmed launchable; `google-genai==2.19.0` installed (the
Gemini Live client's SDK dependency — importable, but unusable without `GOOGLE_API_KEY`);
Node v24.18.0 / pnpm 9.15.9; `livekit-client` 2.22.1 UMD artifact genuinely present under
`packages/ai-parrot-server/ui/node_modules/`.

## Automated evidence already gathered by this feature's prerequisite tasks

These are cited for context and code-reviewer visibility — **they are explicitly not
claimed as equivalent to the real-live matrix below**:

| Task | What it proved (mocked/behavioral, not real-live) |
|---|---|
| TASK-2937–2941 | `ToolManager`/`AbstractTool` full-result execution, Nova dual-output mapping, tool scheduling/deadlines/interruption — all via real `ToolManager`+tools, only Nova's own SDK transport mocked |
| TASK-2942 | WebSocket relay tool-frame dedup and avatar-turn-replacement interruption |
| TASK-2943 | `/voice-assets/livekit-client.umd.js` route serves the real installed artifact (confirmed 200 in this very sandbox) |
| TASK-2944 | `AvatarViewerController`'s subscribe-only lifecycle, one-source audio policy, generation guard — SDK-injected fake `Room`, no real LiveKit |
| TASK-2945 | The actual `dual_provider.html`/`avatar-viewer.js` wiring — verified via a fake-transport aiohttp smoke, not a real session |
| TASK-2946 | Real `VoiceBot`+`ToolManager`+Nova `stream_voice()` dual-output, only Nova's SDK transport mocked; real `VoiceAvatarSession` over a mocked LiveAvatar transport stack |
| TASK-2947 | The actual served page driven by a real headless Chromium browser — `window.WebSocket`/`window.LivekitClient` faked, no real backend or LiveKit |
| TASK-2948 | The shared dual-output demo tool's isolation and bounded slow-tool behavior |

None of the above exercises a real Google Gemini Live API call, a real AWS Bedrock Nova 2
Sonic call, or a real LiveAvatar/LiveKit session — by design (this feature's tests are
explicitly required to mock only the provider/transport boundary, not to reach real cloud
services), and every one of those tasks' own completion notes says so explicitly.

## Required real-live scenario matrix (spec §4) — status

Per-scenario status, using the exact matrix from `examples/clients/voice/README.md`'s
runbook (added by TASK-2948) and spec §4's own required coverage (AC11/AC13/AC14/AC15/AC16):

| # | Scenario | Status | Reason |
|---|---|---|---|
| 1 | Gemini, voice-only — spoken + text reply, `get_weather` tool call visible | **NOT RUN** | No `GOOGLE_API_KEY`/Vertex AI credentials in this environment |
| 2 | Nova, voice-only — same behavior, different voice | **NOT RUN** | No AWS Bedrock credentials; `aws_sdk_bedrock_runtime` not installed |
| 3 | Gemini + Avatar — visible lip-synced video, one audio source | **NOT RUN** | Requires both Gemini credentials AND a real LiveAvatar/LiveKit backend (`LIVEAVATAR_API_KEY`/`LIVEAVATAR_AVATAR_ID` absent) |
| 4 | Nova + Avatar — identical avatar behavior, provider-agnostic | **NOT RUN** | Requires both Nova credentials/SDK AND a real LiveAvatar/LiveKit backend, neither available |
| 5 | Second turn (either provider) — clean new turn, no leftover state | **NOT RUN** | Requires a real provider session to open a first turn at all |
| 6 | Tool interruption — slow tool + Interrupt button, no hang/duplicate reply | **NOT RUN** | Requires a real provider session; the bounded slow-tool mechanism itself (`VOICEBOT_DEMO_TOOL_DELAY_SECONDS`) is unit-tested (TASK-2948) but has never been exercised through a live turn |
| 7 | Reconnect / provider switch with Avatar on — no two-rooms/two-audio-sources | **NOT RUN** | Requires real credentials for both providers plus a real avatar session to switch between |
| 8 | Avatar failure fallback — invalid LiveAvatar config, voice-only keeps working | **NOT RUN** | Requires a real (even if intentionally misconfigured) LiveAvatar endpoint to observe a genuine failure mode, as opposed to the mocked failure already covered by TASK-2946/2947's automated tests |

**0 of 8 required scenarios executed. 8 of 8 marked NOT RUN with reason.**

## What would be needed to complete this task

1. AWS Bedrock credentials with Nova 2 Sonic model access, on Python ≥ 3.12 with
   `aws_sdk_bedrock_runtime==0.7.0` installed (`examples/clients/voice/README.md`'s
   Prerequisites section).
2. A Google API key (or Vertex AI service-account credentials) with Gemini Live model access.
3. A LiveAvatar account (`LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID`) and its LiveKit room
   configuration, with the relevant tenant/agent opted in via
   `parrot.integrations.liveavatar.optin.is_avatar_enabled()`'s backing store.
4. A human tester (or a from-scratch real-live automation harness — out of this task's
   scope, which is a human-executed runbook) able to open
   `examples/clients/voice/static/dual_provider.html` in a real browser, speak into a real
   microphone, and visually/aurally judge the avatar's lip-sync and the single-audio-source
   transitions.
5. Re-run this task (or a follow-up task under a fresh FEAT/TASK id, at the maintainers'
   discretion) with all four in place, executing the exact 8-row matrix above and replacing
   every "NOT RUN" with a dated PASS/FAIL plus artifact links (screen recording, browser
   console log with credentials redacted, server log excerpt).

## Explicit non-claims (per this task's "NOT in scope")

- No production code was changed by this task.
- No implementation fixes were made here (any bug found by a prerequisite task's automated
  tests was already reported in that task's own Completion Note, not fixed in this report).
- No token, credential, or sensitive tool payload appears anywhere in this document or was
  published anywhere.
- No scenario above is reported as passing. A mocked/automated test passing (see the table
  above) is never treated as equivalent to, or evidence for, a real-live pass.

## Recommendation

**FEAT-536 should NOT be marked feature-complete from an operational-acceptance standpoint.**
The implementation (TASK-2937–2948) is complete and covered by automated evidence at the
mocked-boundary level, and `/sdd-done FEAT-536` can proceed for the purpose of merging the
*implementation* — but the real-live matrix in this document must be executed and reported
with actual dated results, by someone with the credentials/services/human-tester access this
sandboxed session structurally lacks, before this feature's LiveAvatar/Nova-dual-output
behavior is considered operationally accepted end-to-end.
