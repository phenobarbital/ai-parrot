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
  uv pip install 'aws_sdk_bedrock_runtime==0.7.0'
  ```

If the SDK isn't installed (e.g. running on Python 3.11), the server
**still starts** — the Nova route stays mounted but reports itself
unavailable: the browser's Nova toggle is shown disabled with the reason,
and a session-start attempt on `/ws/nova` returns a clear WebSocket
`error` frame instead of hanging. The Gemini route is unaffected.

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
- the same tool: a single `@tool`-decorated `get_weather(location)`,

and differ only in `VoiceConfig.provider` (`GOOGLE_LIVE` vs. `NOVA`) and
the corresponding default voice (`Puck` vs. `matthew`).

`VoiceChatHandler` calls `bot_factory()` fresh for every new WebSocket
connection — so the "fresh session" behavior when switching providers
falls directly out of that contract, not out of anything special this
example does.

## Files

| File | Description |
|---|---|
| `server.py` | aiohttp app: two `VoiceChatHandler`s, two `VoiceBot` factories, the `__CONFIG__`-templated index route, and the capability-descriptor JSON builder |
| `static/dual_provider.html` | The provider-switch UI (adapted from `chat.html`) |
| `static/index.html`, `static/app.js` | **Not used by this example** — the raw-client asset from TASK-2177, served by `examples/clients/nova/audio.py` instead |

## Related

- `examples/voice/README.md` — general single-provider `VoiceBot` usage
- `examples/clients/nova/audio.py` — the raw-client, single-provider Nova example
- `packages/ai-parrot/tests/voice/test_provider_conformance.py` — the
  automated drop-in parity suite this example demonstrates by hand
