# speech_report TTS backends

Document the routing matrix, configuration examples, installation extras, output formats, and operational constraints decided in FEAT-591.

## Table of Contents

- [Backend and mode matrix](#backend-and-mode-matrix)
- [Agent attributes](#agent-attributes)
- [Per-call override precedence](#per-call-override-precedence)
- [Installation extras](#installation-extras)
- [Output formats](#output-formats)
- [Supertonic configuration](#supertonic-configuration)
- [Amazon Polly configuration](#amazon-polly-configuration)
- [Operational constraints](#operational-constraints)

## Backend and mode matrix

The behavior of `speech_report()` depends on both the **backend** and the **mode**. The table below shows the exact behavior for each combination.

| mode \ backend | `gemini` (default) | `google_tts` | `supertonic` | `aws_polly` |
|---|---|---|---|---|
| `script` | **unchanged**: multi-speaker script + multi-voice `client.generate_speech()` | script requested with **1 speaker** (single narrator); speaker labels stripped; markdown normalised; TTS via backend | script requested with **1 speaker** (single narrator); speaker labels stripped; markdown normalised; TTS via backend | script requested with **1 speaker** (single narrator); speaker labels stripped; markdown normalised; TTS via backend |
| `verbatim` | report normalised → single-voice `client.generate_speech()` (voice `speech_voice` or `"Charon"`) | report normalised → TTS via backend (**zero LLM calls**) | report normalised → TTS via backend (**zero LLM calls**) | report normalised → TTS via backend (**zero LLM calls**) |

### Key points

- **`gemini` + `script`**: This is the default behavior today. It makes two LLM calls: `create_conversation_script()` to generate a multi-speaker podcast script, and then `generate_speech()` to synthesize audio with multiple voices.
- **`gemini` + `verbatim`**: The report is normalized and sent to `generate_speech()` with a single voice (either `speech_voice` or the default `"Charon"`). This still makes one LLM call (the TTS call itself).
- **`gemini` + non-verbatim**: Not supported. The `gemini` backend only supports `script` mode.
- **Non-Gemini backends + `verbatim`**: Zero LLM calls. The report is normalized and sent directly to the TTS backend.
- **Non-Gemini backends + `script`**: One LLM call to `create_conversation_script()` with exactly one speaker. The speaker labels (e.g., `"Interviewer:"`) are stripped before TTS.

## Agent attributes

`BasicAgent` exposes the following attributes to configure TTS behavior:

| Attribute | Type | Default | Description |
|---|---|---|---|
| `speech_backend` | `Literal["gemini", "google_tts", "supertonic", "aws_polly"]` | `"gemini"` | The TTS backend to use for `speech_report()`. |
| `speech_mode` | `Literal["script", "verbatim"]` | `"script"` | The mode to use: `"script"` for multi-speaker podcast generation, `"verbatim"` for direct text-to-speech. |
| `speech_voice` | `Optional[str]` | `None` | The voice to use for TTS. If not set, the backend uses its default voice. |
| `speech_language` | `Optional[str]` | `None` | The language to use for TTS (e.g., `"en-US"`). If not set, the backend uses its default language. |
| `speech_format` | `Optional[str]` | `None` | The output format to request from the backend (e.g., `"audio/wav"`, `"audio/mpeg"`). If not set, the backend uses its default format. |
| `speech_tts_options` | `Dict[str, Any]` | `{}` | Additional backend-specific options. For example: `{"total_step": 8, "speed": 1.05, "polly_engine": "long-form", "polly_region": "us-east-1"}`. |

### Backend → TTS config mapping

The agent attributes are mapped to the TTS backend configuration as follows:

| Agent attribute | TTS config field | Example |
|---|---|---|
| `speech_backend` | `backend` | `"google_tts"` → `"google"`, `"supertonic"` → `"supertonic"`, `"aws_polly"` → `"polly"` |
| `speech_voice` | `voice` | `"Charon"` |
| `speech_language` | `language` | `"en-US"` |
| `speech_format` | `mime_format` | `"audio/wav"` |
| `speech_tts_options["polly_engine"]` | `polly_engine` | `"long-form"` |
| `speech_tts_options["polly_region"]` | `polly_region` | `"us-east-1"` |

## Per-call override precedence

Per-call keyword arguments to `speech_report()` take precedence over agent attributes:

1. **Keyword argument** (highest priority)
2. **Agent attribute**
3. **Backend default** (lowest priority)

Example:

```python
agent = BasicAgent(speech_backend="supertonic", speech_mode="verbatim")
# agent.speech_backend = "supertonic"
# agent.speech_mode = "verbatim"

# This call uses "google_tts" (kwarg overrides attribute)
await agent.speech_report(report, tts_backend="google_tts")

# This call uses "verbatim" (kwarg overrides attribute)
await agent.speech_report(report, speech_mode="verbatim")

# This call uses "script" (attribute, no kwarg)
await agent.speech_report(report)
```

## Installation extras

### Required extras

| Extra | Description | Package |
|---|---|---|
| `voice-supertonic` | Supertonic ONNX TTS backend | `ai-parrot-integrations` |
| `voice-polly` | Amazon Polly TTS backend | `ai-parrot-integrations` |

### Installing extras

```bash
# Install all voice extras
uv pip install "ai-parrot-integrations[voice]"

# Install only Supertonic
uv pip install "ai-parrot-integrations[voice-supertonic]"

# Install only Polly
uv pip install "ai-parrot-integrations[voice-polly]"
```

### Optional extras

| Extra | Description | Package |
|---|---|---|
| `voice` | All voice extras (supertonic + polly) | `ai-parrot-integrations` |

## Output formats

Each backend produces a native output format. The file extension follows the `mime_format`:

| Backend | Default mime_format | File extension | Notes |
|---|---|---|---|
| `google_tts` | `audio/wav` | `.wav` | PCM wrapped in WAV header (24 kHz, mono, s16le) |
| `supertonic` | `audio/wav` | `.wav` | 44.1 kHz WAV |
| `aws_polly` | `audio/mpeg` | `.mp3` | Can be overridden to `audio/ogg` or `audio/pcm` |

### Overriding the format

You can override the default format per call using `speech_format`:

```python
# Request MP3 from Supertonic
await agent.speech_report(
    report,
    tts_backend="supertonic",
    speech_format="audio/mpeg"
)
```

### MIME to extension mapping

| MIME type | Extension |
|---|---|
| `audio/wav` | `.wav` |
| `audio/mpeg` | `.mp3` |
| `audio/ogg` | `.ogg` |
| `audio/pcm` | `.pcm` |

## Supertonic configuration

### Model path

Supertonic loads its ONNX model from the path specified by the environment variable `SUPERTONIC_MODEL_PATH`. If not set, it uses the default model path.

```bash
export SUPERTONIC_MODEL_PATH=/path/to/supertonic/model.onnx
```

### Thread safety

Supertonic's model loading is guarded by a `threading.Lock` to ensure the model is loaded at most once per process, even under concurrent first calls.

### Performance

- **Latency**: Sub-second synthesis time.
- **Cost**: Free (local ONNX model).
- **Quality**: High-quality English speech.

## Amazon Polly configuration

### Credentials

Polly uses the standard AWS credential chain:

1. Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`)
2. Shared credentials file (`~/.aws/credentials`)
3. IAM role (if running on EC2/ECS)
4. Instance profile (if running on EC2/ECS)

**Note**: Bedrock bearer tokens (`AWS_BEARER_TOKEN_BEDROCK`) are **not** supported for Polly authentication.

### Region resolution

The region is resolved in the following order:

1. `TTSConfig.polly_region` (if set)
2. `AWS_POLLY_REGION` environment variable
3. Default: `"us-east-1"` (long-form is only available in this region)

### Engine options

| Engine | Description | Use case |
|---|---|---|
| `long-form` | Best quality, supports longer text (up to 3000 chars per chunk) | Default, production use |
| `generative` | Fast, lower quality | Low-latency requirements |
| `neural` | Balanced quality and speed | General use |
| `standard` | Fastest, lowest quality | Low-latency requirements |

### Voice options

Polly supports many voices. The default voice for `long-form` is `"Danielle"` (en-US). You can specify any available voice by name.

### Text chunking

Polly has a 3000-character limit per `synthesize_speech` call. Text longer than 2,800 characters is split on sentence boundaries into chunks of at most 2,800 characters. Each chunk is synthesized sequentially, and the audio bytes are concatenated.

**Important**: A failed chunk fails the entire call. There is no fallback to Gemini.

### Example configuration

```python
agent = BasicAgent(
    speech_backend="aws_polly",
    speech_tts_options={
        "polly_engine": "long-form",
        "polly_region": "us-east-1"
    }
)
```

## Operational constraints

### No fallback to Gemini

Non-default backends (Google TTS, Supertonic, Polly) do **not** fall back to Gemini if they fail. The error is logged, and the report is still generated without a podcast.

### No Supertonic-as-Telegram-default

Making Supertonic the Telegram default and mapping voice IDs between backends is out of scope for this feature. These belong to ledger `issue:0fe9c8221dfa`.

### Multi-speaker audio on non-Gemini backends

Non-Gemini backends always use a single narrator. Multi-speaker audio is only supported with the `gemini` backend in `script` mode.

### Google Cloud Text-to-Speech

Google Cloud Text-to-Speech (`google-cloud-texttospeech`) is not used. The `google_tts` backend uses the existing `GoogleTTSBackend` which wraps Gemini's TTS output in a WAV header.

### Nova 2 Sonic

Nova 2 Sonic is a bidirectional speech-to-speech model with no one-shot text-to-audio endpoint. It is not supported as a TTS backend.

### Polly S3 path

The Polly S3 `StartSpeechSynthesisTask` path is not used. We chunk and concatenate audio instead.

### Markdown normalization

Markdown is normalized through `markdown_to_plain()` on every path except `gemini`+`script`. In `script` mode, leading `<Speaker>:` labels are also stripped per line.

### Shared synthesizer cache

A process-wide synthesizer cache is used to share `VoiceSynthesizer` instances across agents. The cache is keyed by the full `TTSConfig`. Callers must not `close()` a shared synthesizer.

### Supertonic thread race

Supertonic's model loading is guarded by a `threading.Lock` to prevent concurrent first calls from loading the model twice.

### Telegram voice reply

The Telegram voice reply converter decodes audio by `mime_format` (WAV, MP3, OGG, or legacy raw PCM) before re-encoding to OGG/Opus. This ensures compatibility with Google WAV output from `google_tts` and Supertonic.

### Google WAV output

`GoogleTTSBackend` wraps the Gemini PCM in a WAV header (24 kHz, mono, s16le) and always reports `mime_format="audio/wav"`. The Telegram converter handles this correctly.

### OGG concatenation

Joining `ogg_vorbis` chunks produces a chained Ogg stream, which is valid and most players handle it. MP3 and PCM concatenate cleanly.

### Long-form availability

Long-form Polly engine is only available in some regions and voices. An invalid engine/voice/region combination surfaces the AWS error code unchanged; there is no automatic engine downgrade.

### Speaker labels

In `script` mode with a non-Gemini backend, the single narrator is the first entry of `self.speakers`. The system instruction resolves as follows:

- If the caller passed an explicit `podcast_instructions` (anything other than the default `"for_podcast.txt"`), use it as-is.
- Otherwise, use a built-in narration instruction: *"Narrate the following report as a single presenter, clearly and concisely, highlighting the key findings."*
