# LiveAvatar Voice Adapters — Operator Reference (FEAT-246)

`voice_adapters.py` provides env-driven STT and TTS factories used by the
Phase C LiveKit pipeline instead of hardcoded Deepgram/Cartesia defaults.

## Environment Variables

### Provider selection

| Variable | Default | Description |
|---|---|---|
| `LIVEAVATAR_STT_PROVIDER` | `whisper` | STT provider. Values: `whisper`, `moonshine`, `deepgram`, `openai`. |
| `LIVEAVATAR_TTS_PROVIDER` | `supertonic` | TTS provider. Values: `supertonic`, `cartesia`, `inference`. |

### STT provider options

| Variable | Applies to | Default | Description |
|---|---|---|---|
| `LIVEAVATAR_STT_MODEL` | `deepgram` | `nova-3` | Deepgram model name (e.g. `nova-2`, `nova-3`). |
| `LIVEAVATAR_WHISPER_MODEL_SIZE` | `whisper` | `small` | faster-whisper model size (e.g. `tiny`, `base`, `small`, `medium`). |
| `LIVEAVATAR_MOONSHINE_MODEL` | `moonshine` | `moonshine/base` | Moonshine model identifier. Moonshine is English-only. |

### TTS provider options

| Variable | Applies to | Default | Description |
|---|---|---|---|
| `SUPERTONIC_MODEL_DIR` | `supertonic` | *(required)* | Path to the directory containing Supertonic-3 ONNX model files. `resolve_tts()` raises `ValueError` when this is unset and provider is `supertonic`. |

## Provider notes

### `whisper` (default STT)

Uses AI-Parrot's `FasterWhisperBackend`. Wrapped in `stt.StreamAdapter` + Silero VAD.
Runs entirely on-device — no network calls.

### `moonshine` (STT)

Uses AI-Parrot's `MoonshineSTTBackend` (ONNX). English-only; sub-second latency on CPU.
Wrapped in `stt.StreamAdapter` + Silero VAD.

### `deepgram` (STT)

Delegates to `livekit.plugins.deepgram.STT`. Requires the `liveavatar-voice` extra and
a valid `DEEPGRAM_API_KEY` environment variable (consumed by the plugin).

### `supertonic` (default TTS)

Uses AI-Parrot's Supertonic-3 ONNX TTS pipeline. Synthesis runs off the event loop via
`asyncio.to_thread`. Native sample rate is typically 44 100 Hz; LiveKit resamples as needed.

### `cartesia` (TTS)

Delegates to `livekit.plugins.cartesia.TTS`. Requires the `liveavatar-voice` extra and
a valid `CARTESIA_API_KEY`.

## Minimal `.env` example

```dotenv
# STT: use Deepgram cloud with nova-3
LIVEAVATAR_STT_PROVIDER=deepgram
LIVEAVATAR_STT_MODEL=nova-3
DEEPGRAM_API_KEY=<your-key>

# TTS: on-device Supertonic
LIVEAVATAR_TTS_PROVIDER=supertonic
SUPERTONIC_MODEL_DIR=/models/supertonic-3
```
