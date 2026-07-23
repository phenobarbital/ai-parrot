# VoiceBot Example — Provider Switch & Usage Tracking

Demonstrates how to use `VoiceBot` with multiple voice backends (Gemini Live and
Amazon Nova 2 Sonic) and how to hot-swap between them at runtime without
reconstructing the bot.

## Prerequisites

### Gemini Live (default)

- Set `GOOGLE_API_KEY` environment variable, or configure Vertex AI credentials
  (`--vertexai`, `--project`, `--location`).

```bash
export GOOGLE_API_KEY="your-key"
```

### Amazon Nova 2 Sonic

- AWS credentials configured (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` or
  an IAM role).
- The experimental SDK (Python >= 3.12 only):

```bash
uv pip install 'aws_sdk_bedrock_runtime==0.7.0'
```

## Demos

### 1. Text-to-speech (single provider)

Send a text question, receive streamed audio + text back. Prints a token usage
report at the end.

```bash
# Gemini Live (default)
python examples/voice/bot.py

# Nova 2 Sonic
python examples/voice/bot.py --provider nova
```

Sample output:

```
  [text] The weather in Buenos Aires is sunny, 25 C with light wind.
  [audio] 48000 bytes
  [tool] get_weather({'location': 'Buenos Aires'}) -> The weather in ...
  [usage] 320 ms, tokens: 152

===== Session Usage Report =====
  Rounds:             1
  Prompt tokens:      102
  Completion tokens:  50
  Total tokens:       152
  Audio in:           0 ms
  Audio out:          3,200 ms
  Audio bytes:        48,000
  Tool calls:         1
  Tool time:          45.2 ms
================================
```

### 2. Runtime provider switch

Starts with Gemini Live, switches to Nova mid-session, then switches back.
Conversation memory is preserved across switches. The usage report shows
per-round token breakdown by provider.

```bash
python examples/voice/bot.py --demo-switch
```

The switch flow:

```
Round 1: Gemini Live   -> "Tell me the time in UTC"
         switch -> nova
Round 2: Nova 2 Sonic  -> "What's the weather in Miami?"
         switch -> google_live
Round 3: Gemini Live   -> "Say goodbye!"
```

### 3. Side-by-side comparison

Sends the same question to both providers sequentially and compares text length,
audio size, and token usage.

```bash
python examples/voice/bot.py --compare
```

### 4. Factory shorthand

Quick setup using the `create_voice_bot()` convenience function.

```bash
python examples/voice/bot.py --factory
```

## How the provider switch works

`VoiceBot` lazily creates its LLM client (`self._llm`) on the first `ask()` or
`ask_stream()` call. The `switch_provider()` helper exploits this:

1. **Close** the current voice client (`bot._llm.close()`).
2. **Reset** `bot._llm = None`.
3. **Update** `bot.voice_config` (provider, voice name, model).
4. The next `ask()` call detects `_llm is None` and creates a fresh client
   matching the new provider.

```python
from parrot.bots.voice import VoiceBot
from parrot.models.voice import VoiceConfig

bot = VoiceBot(
    name="My Bot",
    voice_config=VoiceConfig(provider="google_live"),
)

async with bot:
    # Use Gemini Live
    async for resp in bot.ask("Hello"):
        ...

    # Switch to Nova
    await bot._llm.close()
    bot._llm = None
    bot.voice_config.provider = "nova"
    bot.voice_config.voice_name = "matthew"
    bot.voice_config.model = "nova-2-sonic"

    # Now uses Nova
    async for resp in bot.ask("Hello again"):
        ...
```

## Token usage tracking

The example includes a `SessionUsageTracker` dataclass that accumulates metrics
across streaming chunks and provider switches:

| Metric | Source |
|---|---|
| `prompt_tokens` / `completion_tokens` | `LiveCompletionUsage` on each chunk |
| `audio_in_ms` / `audio_out_ms` | Audio duration from the voice client |
| `audio_bytes` | Raw PCM byte count from `resp.audio_data` |
| `tool_calls_executed` / `tool_execution_time_ms` | Tool call counters |

Call `tracker.close_round(provider)` after each `ask()` loop to snapshot
per-round stats, then `tracker.report()` for a formatted summary.

## Available tools

The example registers two `@tool`-decorated functions the voice agent can call
during conversation:

- **`get_weather(location)`** -- returns simulated weather data.
- **`get_time(timezone)`** -- returns the current UTC time.

## Related files

| File | Description |
|---|---|
| `parrot/bots/voice.py` | `VoiceBot` implementation |
| `parrot/models/voice.py` | `VoiceConfig` dataclass |
| `parrot/clients/live.py` | `GeminiLiveClient`, `LiveVoiceResponse`, `LiveCompletionUsage` |
| `parrot/clients/nova/audio.py` | `NovaAudio` mixin (Nova 2 Sonic streaming) |
| `tests/bots/test_voicebot_provider_switch.py` | Unit tests for the switch and usage accumulation |
