# Dual VoiceChatHandler Provider-Switch Demo (FEAT-418)

One aiohttp app, two [`VoiceChatHandler`](../../../packages/ai-parrot-integrations/src/parrot/voice/handler.py)
instances mounted at `/ws/gemini` and `/ws/nova`, each backed by its own
[`VoiceBot`](../../../packages/ai-parrot/src/parrot/bots/voice.py) — same
name, same system prompt, same tools; only `VoiceConfig` (and therefore
the underlying provider) differs. One browser page, one push-to-talk
button, one provider toggle.

If the FEAT-418 homologation between `GeminiLiveClient` and `NovaClient`
is real, flipping the toggle changes nothing you can perceive except the
voice — that's the acceptance test a human can run end to end.

## Why this reuses `chat.html`, not the TASK-2177 static asset

`examples/clients/voice/static/index.html` + `app.js` (created by
TASK-2177 for `examples/clients/nova/audio.py`) speak a deliberately
simple **raw-client** WebSocket protocol: `start_turn` / `audio` /
`end_turn` client-side, `text` / `audio` / `turn_complete` server-side —
matching `VoiceSession.build_frames()`'s default vocabulary.

`VoiceChatHandler.handle_websocket()` speaks a different, richer protocol:
`start_session` / `audio_data` / `stop_recording` client-side,
`response_chunk` / `transcription` / `response_complete` /
`ready_to_speak` server-side. The two are **not interchangeable** — see
`sdd/tasks/completed/TASK-2178-provider-switch-example.md`'s Completion
Note for the full analysis of why this example instead adapts
`packages/ai-parrot-integrations/src/parrot/voice/ui/chat.html` (the
shipped, protocol-correct UI for `VoiceChatHandler`) into
[`static/dual_provider.html`](static/dual_provider.html), adding:

- a **provider toggle** in the header (switches the WebSocket route and
  starts a fresh session — no memory replay, no transcript migration),
- a **capability panel** rendered live from each client's
  `voice_capabilities` descriptor (never hardcoded), and
- a **per-turn usage strip** (tokens/latency) sourced from
  `response_complete`'s `usage` field.

## Prerequisites

### Gemini Live

```bash
export GOOGLE_API_KEY="your-key"
# or configure Vertex AI credentials (project/location/credentials file)
```

### Amazon Nova 2 Sonic

- AWS Bedrock credentials (access key / secret key or an IAM role).
- **Python >= 3.12** with the experimental voice SDK:

  ```bash
  # The [awscrt] extra is NOT optional: without it the package installs but
  # `import aws_sdk_bedrock_runtime` raises ModuleNotFoundError, which reads
  # exactly like "the SDK is not installed".
  uv pip install 'aws_sdk_bedrock_runtime[awscrt]==0.11.0'
  ```

If the SDK isn't installed (e.g. running on Python 3.11), the server
**still starts** — the Nova route stays mounted but reports itself
unavailable: the browser's Nova toggle is shown disabled with the reason,
and a session-start attempt on `/ws/nova` returns a clear WebSocket
`error` frame instead of hanging. The Gemini route is unaffected.

### LiveAvatar viewer (optional, FEAT-536)

The page's Avatar toggle is **off by default** and layered entirely on
top of the two voice routes above — leaving it off (or missing any of
the following) never affects ordinary voice with either provider.

1. **Backend opt-in.** LiveAvatar sessions are default-deny
   (`parrot.integrations.liveavatar.optin.is_avatar_enabled()`). Enable
   the tenant/agent combination you plan to test through whatever
   mechanism your deployment's opt-in store uses before expecting
   `session_started.avatar.active` to ever be `true`.
2. **LiveAvatar/LiveKit server configuration.** The same environment
   variables `VoiceAvatarSession.start()` already reads:
   `LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID` (required), plus optional
   `LIVEAVATAR_BASE_URL` / `LIVEAVATAR_SANDBOX`, and this deployment's own
   LiveKit room-token configuration (`LiveKitRoomManager`).
3. **Locked frontend SDK install.** The viewer loads the SAME
   `livekit-client` dependency `packages/ai-parrot-server/ui/package.json`
   already declares (`^2.19.2`, `pnpm-lock.yaml` resolves `2.22.1`) from
   that package's own `node_modules` — never a CDN, never a different
   version. Install it once for the UI workspace:

   ```bash
   pnpm --dir packages/ai-parrot-server/ui install --frozen-lockfile
   ```

   Without this step, `/voice-assets/livekit-client.umd.js` responds with
   a controlled `503` and the page's Avatar section reports "SDK not
   installed — voice-only"; both `/ws/gemini` and `/ws/nova` are
   completely unaffected.

With all three prerequisites met: open Settings (⚙️), check "Enable
avatar (off by default)", optionally set a Tenant ID / Avatar ID
override, and start (or restart) a session — the video card in the
bottom-left corner shows the LiveKit room once `session_started.avatar`
reports `active: true`.

### Broadcast mode (FEAT-537)

A **moderated multi-browser broadcast**: one Nova VoiceBot conversation, one
LiveAvatar session and one LiveKit room, fanned out to up to **10** browsers.
The first participant admitted becomes moderator and can grant a single
exclusive speaking floor to anyone else. Ordinary single-user Gemini/Nova
testing is untouched — broadcast mode is a third handler on the same page.

> **Live-vendor status.** The real-vendor gate for this feature has **NOT** been
> run: see `docs/testing/voicebot-multiroom-live-gate.md` (0 of 12 scenarios).
> Everything below is verified against deterministic tests and local Redis;
> LiveAvatar/LiveKit/Nova behaviour is documented intent, not measured fact.

**Prerequisites** (any missing one disables broadcast mode with a reason shown
on the page; the two single-user routes keep working):

| Variable | Required | Purpose |
|---|---|---|
| `VOICEBOT_BROADCAST_REDIS_URL` | yes | Cross-worker state, admission and moderation. Broadcast mode is off without it. |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | yes | The output room and its role-specific tokens. |
| `LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID` | for avatar mode | Without them the broadcast still runs, in audio-only mode. |
| AWS Nova credentials + `aws_sdk_bedrock_runtime` | yes | A broadcast is Nova-only for its lifetime. |
| `VOICEBOT_DEMO_PARTICIPANTS` | demo only | `alice:tokA,bob:tokB` — maps shared tokens to fixed principals. **Localhost only**: the server refuses a non-loopback `--host` while this is set. |
| `VOICEBOT_BROADCAST_WORKER_ID` | no | Defaults to `demo-<pid>`. |
| `PARROT_BROADCAST_WORKER_TOKEN` | multi-worker only | Shared service token for the internal speaker relay. Required before the relay will mount. |
| `VOICEBOT_BROADCAST_FAILURE_HOOK` | no | `1` mounts the demo failure-injection route. Off by default; never mounted in production. |

**Install and run:**

```bash
source .venv/bin/activate
uv pip install -e "packages/ai-parrot-integrations[broadcast]"
pnpm --dir packages/ai-parrot-server/ui install --frozen-lockfile   # LiveKit UMD asset

docker run --rm -p 6379:6379 redis:7        # or: redis-server

export VOICEBOT_BROADCAST_REDIS_URL=redis://localhost:6379/3
export VOICEBOT_DEMO_PARTICIPANTS="alice:tok-alice,bob:tok-bob,carol:tok-carol"
python examples/clients/voice/server.py --host localhost
```

**Ten-browser walkthrough:**

1. Open <http://localhost:8080>, pick a demo token in the Broadcast panel and
   click **Create**. You are admitted first, so **you are the moderator** — not
   because you created it, but because admission is what decides the role.
2. Copy the share link (`http://localhost:8080/?broadcast=<id>`). It carries the
   broadcast id and **nothing else** — no role, no credential.
3. Open the link in nine more browser profiles/windows, each with a different
   demo token. Every one of them sees the same avatar video and hears the same
   audio. An **eleventh** join is refused with `viewer_limit_reached`.
4. In a viewer tab click **Raise hand**. The moderator sees the queue in server
   order and clicks **Grant**.
5. The granted tab's **Talk** button becomes enabled. Click it — only now is the
   microphone requested. Speak; every tab hears the reply.
6. Click **Finish speaking** (or the moderator's **Revoke**): the floor returns
   to the moderator and the old speaker's Talk button disables immediately.
7. Close the moderator's tab: the earliest remaining participant is elected and
   every tab shows the new role without a reload. Closing the **last** tab ends
   the broadcast.

**Failure injection** (`VOICEBOT_BROADCAST_FAILURE_HOOK=1`):

```bash
curl -X POST localhost:8080/__demo__/broadcasts/<bid>/inject \
     -H 'Content-Type: application/json' -d '{"kind":"avatar_control_close"}'
```

| `kind` | Expected in every browser |
|---|---|
| `avatar_control_close` | Avatar video disappears, audio continues from the room's direct publisher, badge shows `audio_only`. One-way: the avatar does not come back. |
| `avatar_track_lost` | Same, with reason `avatar_track_lost`. |
| `owner_death` | Media stops; another worker fences the dead owner and cleans the room within ~30 s (`ended`/`failed` with `owner_lost`). The terminal state stays readable for 5 minutes. |

**Full operations guide:** [`docs/voice/voicebot-multiroom-heygen-avatar.md`](../../../docs/voice/voicebot-multiroom-heygen-avatar.md).

## Run it

```bash
source .venv/bin/activate
python examples/clients/voice/server.py
python examples/clients/voice/server.py --port 9000
```

Then open http://localhost:8080:

1. Hold the record button and talk on Gemini Live.
2. Click the "Nova 2 Sonic" toggle — the transcript clears and a fresh
   session starts on `/ws/nova`.
3. Hold the record button and ask the same question.
4. Confirm: same agent behavior, same tool call (`get_weather`), only the
   voice differs. Open the settings panel (⚙️) to compare the two
   providers' capability tables side by side.

## What's shared vs. what differs between the two bots

Both `make_gemini_bot()` and `make_nova_bot()` (`server.py`) construct a
`VoiceBot` with:

- the same `name` ("Assistant") and `system_prompt`,
- the same tool **definition and behavior**: `VoiceDemoWeatherTool`, a
  deterministic `AbstractTool` (`name="get_weather"`) that returns a
  short spoken sentence (`voice_text`) plus a structured visual payload
  (`display_data`) — every value it returns is a labeled demo fixture,
  not a real weather lookup. Each factory call constructs its **own
  fresh instance** — never a shared module-level object — so the two
  bots (and every new connection) get isolated tool state while still
  being directly comparable across providers,

and differ only in `VoiceConfig.provider` (`GOOGLE_LIVE` vs. `NOVA`) and
the corresponding default voice (`Puck` vs. `matthew`).

`VoiceChatHandler` calls `bot_factory()` fresh for every new WebSocket
connection — so the "fresh session" behavior when switching providers
falls directly out of that contract, not out of anything special this
example does.

### Triggering a slow tool (for the interruption scenario below)

Set `VOICEBOT_DEMO_TOOL_DELAY_SECONDS` (0–30, clamped) before starting
the server to make `get_weather` sleep before answering — bounded and
clearly a demo knob, not a permanent slowdown:

```bash
VOICEBOT_DEMO_TOOL_DELAY_SECONDS=8 python examples/clients/voice/server.py
```

## Real-live acceptance runbook (spec §4, AC13)

Run this matrix by hand against the actually-served page above — not a
hand-written stand-in — with real Gemini/Nova credentials and (for the
avatar rows) a real LiveAvatar/LiveKit backend. Record which scenarios
actually passed and link that evidence from your own report; this
runbook does not itself claim a passing run.

| # | Scenario | Steps | Expected |
|---|---|---|---|
| 1 | Gemini, voice-only | Hold record, ask "what's the weather in Miami?" | Spoken + text reply; a `get_weather` tool event with Miami's fixture data appears in settings/tool panel |
| 2 | Nova, voice-only | Switch provider, repeat step 1 | Same agent behavior/tool result, different voice (matthew) |
| 3 | Gemini + Avatar | Enable Avatar (Settings), start a session, ask a question | Video card shows the LiveKit room; avatar audio takes over once its track is playable (see the demo's "Enable avatar audio" prompt if autoplay is blocked); text/tool panels keep updating |
| 4 | Nova + Avatar | Same as #3 on the Nova route | Identical avatar behavior — the avatar path is provider-agnostic |
| 5 | Second turn (either provider) | After a completed turn, ask a follow-up | New turn starts cleanly; no leftover audio/tool state from turn 1 |
| 6 | Tool interruption | Start the server with `VOICEBOT_DEMO_TOOL_DELAY_SECONDS=8`, ask for the weather, click **Interrupt** while it is "thinking" | Local (and, if Avatar is on, avatar) playback stops immediately; a fresh recording starts via the existing `start_recording` path — no hang, no duplicate reply once the slow tool eventually finishes |
| 7 | Reconnect / provider switch with Avatar on | With Avatar enabled and connected, switch provider (or wait out a session limit) | Old WebSocket/avatar session closes cleanly, a fresh one starts, no two-rooms/two-audio-sources state |
| 8 | Avatar failure fallback | Point `LIVEAVATAR_*` at an invalid/unreachable config, enable Avatar | Session reports `avatar.active: false` with a reason; voice-only keeps working exactly as scenario #1/#2 |

Evidence for a completed run belongs in this feature's operational
acceptance report (`sdd/tasks/completed/TASK-2949-voice-liveavatar-operational-acceptance.md`
once filed) — link results there rather than duplicating them here.

## Files

| File | Description |
|---|---|
| `server.py` | aiohttp app: two `VoiceChatHandler`s, two `VoiceBot` factories, the `VoiceDemoWeatherTool` dual-output demo tool, the `__CONFIG__`-templated index route, the capability-descriptor JSON builder, and the scoped `/voice-assets/livekit-client.umd.js` route |
| `static/dual_provider.html` | The provider-switch UI (adapted from `chat.html`), including the Avatar viewer card, tool/data events panel and Interrupt control |
| `static/avatar-viewer.js` | The subscribe-only LiveKit Room lifecycle controller the avatar viewer above uses (`AvatarViewerController`), plus FEAT-537's broadcast policy (`mode: "broadcast"`) |
| `static/broadcast-ui.js` | FEAT-537 broadcast client: the stateful 16 kHz resampler, the REST/control-socket client and the pure `derivePermissions()` floor gate |
| `static/index.html`, `static/app.js` | **Not used by this example** — the raw-client asset from TASK-2177, served by `examples/clients/nova/audio.py` instead |

## Related

- `examples/voice/README.md` — general single-provider `VoiceBot` usage
- `examples/clients/nova/audio.py` — the raw-client, single-provider Nova example
- `packages/ai-parrot/tests/voice/test_provider_conformance.py` — the
  automated drop-in parity suite this example demonstrates by hand
- `docs/voice/voicebot-multiroom-heygen-avatar.md` — FEAT-537 broadcast
  architecture and operations guide
- `docs/testing/voicebot-multiroom-live-gate.md` — FEAT-537 real-vendor gate
  (currently **NOT RUN**)
- `docs/testing/voicebot-liveavatar-acceptance.md` — FEAT-536's acceptance
  matrix (also NOT RUN)
