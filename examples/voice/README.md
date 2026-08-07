# VoiceBot Examples — Provider Switch

> **Note (FEAT-418, TASK-2178):** this file previously documented an
> `examples/voice/bot.py` CLI script (a runtime `switch_provider()` helper
> hot-swapping `bot._llm` mid-session, a `SessionUsageTracker`,
> `--demo-switch`/`--compare`/`--factory` flags) that was never actually
> committed to the repository — the doc had drifted ahead of the code. The
> in-place runtime hot-swap approach it described is also explicitly **out
> of scope** for `VoiceBot` (rejected in the FEAT-418 brainstorm; a
> provider switch is a fresh session, not a live-swapped client — see
> `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md` §1 Non-Goals).
> This file is reconciled to point at the example that actually exists and
> actually runs.

## The real provider-switch example

`examples/clients/voice/server.py` is the working demonstration of
provider parity between `GeminiLiveClient` and `NovaClient`: one aiohttp
app, two `VoiceChatHandler` instances (`/ws/gemini`, `/ws/nova`), each
backed by its own fresh `VoiceBot` — same name, same system prompt, same
tools, only `VoiceConfig` differs. See
[`examples/clients/voice/README.md`](../clients/voice/README.md) for how
to run it.

Unlike the old, undocumented hot-swap idea, switching providers there
means: close the current WebSocket, open a new one on the other route,
and start a **brand-new session** (no memory replay, no transcript
migration) — `bot_factory()` builds a fresh `VoiceBot` per connection.

## Other single-provider voice examples

- `examples/clients/nova/audio.py` — a self-contained aiohttp + push-to-talk
  web UI driving `NovaClient` directly (no `VoiceBot`, no
  `VoiceChatHandler`) — demonstrates the raw client contract end to end,
  using the core `parrot.voice.session.VoiceSession` turn-lifecycle
  manager. See its module docstring for usage.

## Minimal `VoiceBot` usage (single provider, no switching)

```python
from parrot.bots.voice import VoiceBot
from parrot.models.voice import VoiceConfig

bot = VoiceBot(
    name="My Bot",
    system_prompt="You are a helpful voice assistant.",
    voice_config=VoiceConfig(provider="google_live", voice_name="Puck"),
)

async for response in bot.ask_stream(audio_iterator):
    if response.audio_data:
        play_audio(response.audio_data)
    if response.usage:
        print(f"Tokens: {response.usage.total_tokens}")
```

Swap `VoiceConfig(provider="google_live", ...)` for
`VoiceConfig(provider="nova", voice_name="matthew")` to target Amazon Nova
2 Sonic instead — everything else about the `VoiceBot` call site is
identical, which is the homologation this feature (FEAT-418) verifies.

## Related files

| File | Description |
|---|---|
| `parrot/bots/voice.py` | `VoiceBot` implementation |
| `parrot/models/voice.py` | `VoiceConfig`, `VoiceStreamOptions`, `VoiceCapabilities` |
| `parrot/clients/live.py` | `GeminiLiveClient`, `LiveVoiceResponse`, `LiveCompletionUsage` |
| `parrot/clients/nova/` | `NovaClient` (Nova 2 Sonic streaming) |
| `parrot/voice/session.py` | `VoiceSession` — provider-agnostic turn lifecycle |
| `parrot/voice/handler.py` (ai-parrot-integrations) | `VoiceChatHandler` — WebSocket handler |
| `examples/clients/voice/server.py` | The dual-provider example (TASK-2178) |
| `examples/clients/nova/audio.py` | Raw-client single-provider example (TASK-2177) |
| `tests/voice/test_provider_conformance.py` | Parametrized drop-in parity suite (TASK-2176) |
