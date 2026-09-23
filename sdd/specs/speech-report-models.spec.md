---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-integrations]
tags: [tts, speech-report, supertonic, polly, voice]
---

# Feature Specification: speech_report pluggable TTS backends (fast-path)

**Feature ID**: FEAT-591
**Date**: 2026-09-22
**Author**: Jesus (with Claude)
**Status**: approved
**Target version**: next minor (0.30.x)

Source: `sdd/proposals/speech-report-models.brainstorm.md` (Option A). Follow-up: ledger `issue:0fe9c8221dfa` (make Supertonic the Telegram default).

---

## 1. Motivation & Business Requirements

### Problem Statement

`BasicAgent.speech_report()` (`packages/ai-parrot/src/parrot/bots/agent.py:605`) is
hard-wired to Google. It makes two Gemini calls on `self.client`:
`create_conversation_script()` writes a multi-speaker podcast script, and then
`generate_speech()` (Gemini TTS through `generate_content` with
`response_modalities=["AUDIO"]`) turns that script into audio. Every report podcast
therefore costs one LLM script call plus one Gemini TTS call, and `self.client`
must be a `GoogleGenAIClient`.

Agent owners need a **fast path** with two parts:
- **Mode**: read the report **verbatim** (no script LLM call), or keep the script
  step with a **single narrator**.
- **Engine**: pick **Supertonic** (local ONNX, sub-second, free), **Gemini TTS**
  (single voice via `GoogleTTSBackend`), or **Amazon Polly**. Nova 2 Sonic was
  rejected because it is a bidirectional speech-to-speech model with no one-shot
  text-to-audio endpoint.

### Goals
- G1: Two independent selectors on `BasicAgent`:
  - `speech_backend`: `"gemini"` (default) | `"google_tts"` | `"supertonic"` | `"aws_polly"`
  - `speech_mode`: `"script"` (default) | `"verbatim"`

  Each is set by an agent attribute and can be overridden per call through
  `speech_report(tts_backend=..., speech_mode=...)`.
- G2: When nothing is set, behaviour is byte-for-byte today's (Gemini
  multi-speaker script + `generate_speech`).
- G3: `verbatim` + any non-Gemini backend makes **zero LLM calls**.
- G4: Add an Amazon Polly TTS backend (`"polly"`) to `parrot.voice.tts`.
- G5: A process-wide synthesizer cache, so the Supertonic ONNX model loads once per
  process.
- G6: `GoogleTTSBackend` returns playable WAV with a truthful `mime_format`. The
  Telegram voice-reply converter is adapted in the same feature so it keeps
  working.

### Non-Goals (explicitly out of scope)
- Making Supertonic the Telegram default, and mapping voice ids between backends.
  Both belong to ledger `issue:0fe9c8221dfa`.
- Multi-speaker audio on non-Gemini backends. Those backends always use a single
  narrator (decided in the brainstorm).
- Google Cloud Text-to-Speech (`google-cloud-texttospeech`), ElevenLabs and OpenAI
  TTS.
- Nova 2 Sonic as a TTS engine (rejected in the brainstorm).
- The Polly S3 `StartSpeechSynthesisTask` path (rejected; we chunk and
  concatenate instead).
- Any runtime fallback to Gemini when a backend fails (rejected; see §2).

---

## 2. Architectural Design

### Overview

Option A: `speech_report` routes non-default backends through the existing TTS
layer in `ai-parrot-integrations` (`parrot.voice.tts`: `AbstractTTSBackend`,
`TTSConfig`, `VoiceSynthesizer`). Core `ai-parrot` never hard-depends on that
package. It **lazily imports** `parrot.voice.tts` only when a non-default backend is
selected. If the import fails, it raises an `ImportError` naming
`ai-parrot-integrations[voice-supertonic]` / `[voice-polly]`.

**Behaviour matrix (decided):**

| mode \ backend | `gemini` (default) | `google_tts` / `supertonic` / `aws_polly` |
|---|---|---|
| `script` | **unchanged**: multi-speaker script + multi-voice `client.generate_speech` | script requested with **1 speaker** (single narrator); speaker labels stripped; markdown normalised; TTS via backend |
| `verbatim` | report normalised → single-voice `client.generate_speech` (voice `speech_voice` or `"Charon"`) | report normalised → TTS via backend (**zero LLM calls**) |

**Decided behaviour carried from the brainstorm:**
- **Agent → `TTSConfig.backend` mapping**: `google_tts` → `"google"`,
  `supertonic` → `"supertonic"`, `aws_polly` → `"polly"`. There is no `aws_nova`
  alias.
- **Output format: backend-native.**
  - `supertonic` → `audio/wav`, `google_tts` → `audio/wav`, `aws_polly` →
    `audio/mpeg` by default.
  - `speech_format` overrides this when the backend supports it.
  - The file extension follows the returned `mime_format`:
    `audio/wav`→`wav`, `audio/mpeg`→`mp3`, `audio/ogg`→`ogg`, `audio/pcm`→`pcm`.
  - The one exception: Gemini PCM is wrapped in a WAV header (24 kHz, mono,
    s16le), inside `GoogleTTSBackend` itself.
- **`verbatim` `script_path`**: the exact (normalised) text sent to TTS is saved
  under `generated_scripts/` and returned as `script_path`. The return dict keeps
  its shape, `{"script_path", "podcast_path"}`.
- **Synthesizer reuse**: `get_shared_synthesizer(config)` keeps **process-wide**
  `VoiceSynthesizer` instances keyed by the full `TTSConfig`, shared across agents.
  Supertonic's lazy model load is additionally guarded by a `threading.Lock`, so
  concurrent first calls load the model once. Shutdown is best-effort through
  `close_shared_synthesizers()`.
- **Polly**:
  - Credentials: `aioboto3` with the standard AWS credential chain. Bedrock bearer
    tokens are not supported.
  - Engine: `long-form` by default; `generative`, `neural` and `standard` can be
    selected.
  - Region: `TTSConfig.polly_region`, then the `AWS_POLLY_REGION` environment
    variable, then `"us-east-1"` (long-form exists there).
  - Default voice: `"Danielle"` (long-form, en-US).
  - Long text is split on sentence boundaries into chunks of at most 2 800
    characters. There is one `synthesize_speech` call per chunk, sequential and in
    order, and the audio bytes are concatenated. A failed chunk fails the whole
    call.
- **Failure policy**: any non-default backend failure raises. There is **no
  fallback** to Gemini. `_generate_report` already logs the error and continues
  without a podcast (`agent.py:748-755`).
- **Markdown normalisation**: applied in **both** modes to every path except
  `gemini`+`script`. It uses the existing core
  `parrot.outputs.formats.text.markdown_to_plain`. In `script` mode, leading
  `"<Speaker>:"` labels are also stripped per line.

### Component Diagram
```
BasicAgent.speech_report(report, tts_backend?, speech_mode?)
   │ resolve (kwarg > attribute > default) + validate
   ├── gemini + script   ──→ [existing code path, unchanged] client.create_conversation_script → client.generate_speech
   ├── gemini + verbatim ──→ markdown_to_plain → client.generate_speech(single SpeakerConfig)
   └── non-gemini
         ├── text: verbatim → markdown_to_plain(report)
         │         script   → client.create_conversation_script(1 speaker) → strip labels → markdown_to_plain
         ├── save text → generated_scripts/  (script_path)
         └── lazy import parrot.voice.tts
               get_shared_synthesizer(TTSConfig) ──→ VoiceSynthesizer ──→ GoogleTTSBackend (WAV)
                                                                     ├──→ SupertonicONNXBackend (WAV)
                                                                     └──→ AmazonPollyTTSBackend (MP3/OGG/PCM, chunked)
               write result.audio → podcasts/podcast_<ts>.<ext>  (podcast_path)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BasicAgent.speech_report` (`agent.py:605`) | modifies | new kwargs and attributes; the default path is untouched |
| `BasicAgent._generate_report` (`agent.py:724`) | depends on | inherits the attribute defaults; no signature change |
| `ProductBot` (`bots/product.py:160`) | depends on | same as above |
| `TTSConfig` (`voice/tts/models.py:17`) | extends | `backend` Literal += `"polly"`; adds `polly_engine`, `polly_region` |
| `VoiceSynthesizer._get_backend` (`voice/tts/synthesizer.py:53`) | extends | `"polly"` branch |
| `voice/tts/synthesizer.py` | extends | `get_shared_synthesizer`, `close_shared_synthesizers` |
| `GoogleTTSBackend.synthesize` (`voice/tts/google_backend.py:97`) | modifies | PCM → WAV; `mime_format="audio/wav"` always |
| `SupertonicTTSBackend._synthesize_sync` (`voice/tts/supertonic_backend.py:257`) | modifies | `_ensure_session()` under a `threading.Lock` |
| `TelegramAgentWrapper` voice reply (`telegram/wrapper.py:3458`) | modifies | the converter decodes by `mime_format` instead of assuming raw 24 kHz PCM |
| `AgentVoiceTalk._synthesize` (`ai-parrot-server/.../handlers/agent_voice.py:379`) | depends on | now receives a truthful `audio/wav` from Google; no code change, check its test |
| `ai-parrot-integrations/pyproject.toml` | extends | extra `voice-polly = ["aioboto3>=13.2.0"]`, added to the `voice` bundle |

### Data Models
```python
# packages/ai-parrot/src/parrot/bots/agent.py (module level)
SpeechBackend = Literal["gemini", "google_tts", "supertonic", "aws_polly"]
SpeechMode = Literal["script", "verbatim"]

# packages/ai-parrot-integrations/src/parrot/voice/tts/models.py — TTSConfig additions
backend: Literal["google", "elevenlabs", "openai", "supertonic", "polly"] = "google"
polly_engine: Literal["long-form", "generative", "neural", "standard"] = "long-form"
polly_region: Optional[str] = None   # None → AWS_POLLY_REGION → "us-east-1"
```

### New Public Interfaces
```python
# parrot.voice.tts.synthesizer
async def get_shared_synthesizer(config: TTSConfig) -> VoiceSynthesizer: ...
async def close_shared_synthesizers() -> None: ...

# parrot.voice.tts.polly_backend
class AmazonPollyTTSBackend(AbstractTTSBackend): ...

# BasicAgent.speech_report — new keyword-only params
async def speech_report(self, report: str, ..., tts_backend: Optional[SpeechBackend] = None,
                        speech_mode: Optional[SpeechMode] = None, **kwargs) -> Dict[str, Any]: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Polly backend + config | yes | skeleton below; OutputFormat map; chunk ≤ 2800 chars; region/voice defaults fixed | — |
| M2: Shared synthesizer cache | yes | key = `config.model_dump_json()`; module dict + `asyncio.Lock`; Supertonic `threading.Lock` | — |
| M3: Google WAV + Telegram converter | yes | WAV 24000 Hz/1 ch/2 bytes; converter branches on `mime_format` | — |
| M4: speech_report routing | yes | matrix in §2; helper signatures below | — |
| M5: Docs | yes | file path fixed | — |

### Module 1: Amazon Polly TTS backend + config
- **Paths**:
  - `packages/ai-parrot-integrations/src/parrot/voice/tts/polly_backend.py` (new)
  - `models.py`, `synthesizer.py`, `pyproject.toml` (modify)
- **Responsibility**:
  - Async Polly synthesis through `aioboto3`, with chunking for long text.
  - `TTSConfig` fields for Polly, and the `"polly"` branch in
    `VoiceSynthesizer._get_backend`.
  - A new `voice-polly` extra.
- **Depends on**: existing `AbstractTTSBackend`, `SynthesisResult`, `TTSConfig`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/voice/tts/polly_backend.py  (new)
  _DEFAULT_VOICE = "Danielle"          # long-form, en-US
  _DEFAULT_REGION = "us-east-1"
  _MAX_CHARS = 2800                    # under Polly's 3000-char SynthesizeSpeech limit
  _MIME_TO_POLLY = {"audio/mpeg": "mp3", "audio/ogg": "ogg_vorbis", "audio/pcm": "pcm"}

  def split_text_for_polly(text: str, max_chars: int = _MAX_CHARS) -> list[str]:
      """Split on sentence boundaries into chunks of <= max_chars; hard-split oversized sentences."""

  class AmazonPollyTTSBackend(AbstractTTSBackend):  # verified: voice/tts/backend.py:17
      """TTS backend over Amazon Polly (aioboto3, standard AWS credential chain)."""
      def __init__(self, voice: Optional[str] = None, *, engine: str = "long-form",
                   region: Optional[str] = None, **kwargs) -> None:
          """No network I/O. region: arg → AWS_POLLY_REGION → 'us-east-1'."""
      async def synthesize(self, text: str, *, voice: Optional[str] = None,
                           mime_format: str = "audio/mpeg",
                           language: Optional[str] = None) -> SynthesisResult:  # verified: backend.py:38
          """Chunk, call synthesize_speech per chunk in order, concatenate bytes.
          Raises ValueError on empty text or a mime_format not in _MIME_TO_POLLY;
          ImportError naming 'ai-parrot-integrations[voice-polly]' if aioboto3 is missing;
          RuntimeError wrapping botocore errors (message keeps AWS error code)."""
      async def close(self) -> None:
          """Release the aioboto3 session (no-op if never opened)."""

  # models.py  (modifies voice/tts/models.py:47)
  backend: Literal["google", "elevenlabs", "openai", "supertonic", "polly"]
  polly_engine: Literal["long-form", "generative", "neural", "standard"] = "long-form"
  polly_region: Optional[str] = None

  # synthesizer.py  (modifies voice/tts/synthesizer.py:96 — new elif before the elevenlabs/openai branch)
  #   elif backend_name == "polly": lazy-import AmazonPollyTTSBackend(voice=..., engine=config.polly_engine, region=config.polly_region)
  ```

### Module 2: Process-wide synthesizer cache
- **Paths**:
  - `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py` (modify)
  - `supertonic_backend.py` (modify)
  - `voice/tts/__init__.py` (export)
- **Responsibility**:
  - Share a single `VoiceSynthesizer` per distinct `TTSConfig` across the process.
  - Make Supertonic's lazy model load thread-safe.
- **Depends on**: M1 (both modify `synthesizer.py` and are serialized).
- **Interface Skeleton**:
  ```python
  # synthesizer.py (append after class VoiceSynthesizer, verified: synthesizer.py:22)
  _SHARED: dict[str, VoiceSynthesizer] = {}
  _SHARED_LOCK: Optional[asyncio.Lock] = None   # created lazily on first use

  async def get_shared_synthesizer(config: TTSConfig) -> VoiceSynthesizer:
      """Return the process-wide VoiceSynthesizer for config (key: config.model_dump_json()).
      Created once under an asyncio.Lock; callers MUST NOT close() it."""

  async def close_shared_synthesizers() -> None:
      """Close and drop every shared synthesizer (best-effort; errors logged, never raised)."""

  # supertonic_backend.py (modifies SupertonicTTSBackend.__init__ verified :80 and the
  #   `self._ensure_session()` call verified :257)
  self._session_lock = threading.Lock()   # in __init__
  with self._session_lock:                # around self._ensure_session() in _synthesize_sync
      self._ensure_session()
  ```

### Module 3: Google WAV output + Telegram converter
- **Paths**:
  - `packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py`
  - `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**:
  - `GoogleTTSBackend` wraps the Gemini PCM in a WAV header and always reports
    `audio/wav`.
  - The Telegram voice reply decodes by `mime_format` (WAV, MP3, OGG, or legacy raw
    PCM) before re-encoding to OGG/Opus.
- **Depends on**: none.
- **Interface Skeleton**:
  ```python
  # google_backend.py (modifies :186 `return SynthesisResult(audio=audio_bytes, mime_format=mime_format)`)
  _PCM_RATE = 24000; _PCM_CHANNELS = 1; _PCM_WIDTH = 2
  def _pcm_to_wav(pcm: bytes) -> bytes:
      """Wrap raw s16le mono 24 kHz PCM in a WAV container (stdlib `wave`)."""
  # synthesize() → SynthesisResult(audio=_pcm_to_wav(audio_bytes), mime_format="audio/wav")
  #   (idempotent: if audio already starts with b"RIFF", do not re-wrap)

  # telegram/wrapper.py (replaces nested `def _convert_pcm_to_ogg(raw_pcm: bytes) -> bytes:` verified :3458)
  @staticmethod
  def _tts_audio_to_ogg(audio: bytes, mime_format: str) -> bytes:
      """audio/wav|audio/mpeg|audio/ogg → AudioSegment.from_file(format=wav|mp3|ogg);
      anything else → legacy raw PCM (24 kHz mono s16le). Export OGG/Opus."""
  ```

### Module 4: speech_report backend/mode routing
- **Path**: `packages/ai-parrot/src/parrot/bots/agent.py`
- **Responsibility**:
  - Resolve and validate the backend and mode.
  - Build the text for the chosen mode.
  - Synthesize through a lazily imported `parrot.voice.tts` and write the file.
  - Keep the default path byte-identical.
  - Replace `print(...)` at `agent.py:688` with `self.logger.info`.
- **Depends on**: M1 (`"polly"` literal, fields), M2 (`get_shared_synthesizer`),
  M3 (Google WAV). All are reached by name through the lazy import, and M4's tests
  mock them.
- **Interface Skeleton**:
  ```python
  # agent.py module level (near imports, verified :19/:24)
  SpeechBackend = Literal["gemini", "google_tts", "supertonic", "aws_polly"]
  SpeechMode = Literal["script", "verbatim"]
  _SPEECH_TO_TTS_BACKEND = {"google_tts": "google", "supertonic": "supertonic", "aws_polly": "polly"}
  _NATIVE_MIME = {"google": "audio/wav", "supertonic": "audio/wav", "polly": "audio/mpeg"}
  _MIME_EXT = {"audio/wav": "wav", "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/pcm": "pcm"}

  class BasicAgent(Chatbot, NotificationMixin):          # verified: agent.py:29
      # after `num_speakers: int = 1` (verified :60)
      speech_backend: SpeechBackend = "gemini"
      speech_mode: SpeechMode = "script"
      speech_voice: Optional[str] = None
      speech_language: Optional[str] = None
      speech_format: Optional[str] = None
      speech_tts_options: Dict[str, Any] = {}             # total_step, speed, polly_engine, polly_region

      async def speech_report(self, report: str, max_lines: int = 15, num_speakers: int = 2,
                              podcast_instructions: Optional[str] = "for_podcast.txt",
                              directory: Optional[Path] = None, output_directory: Optional[Path] = None,
                              script_model: Optional[str] = None, tts_model: Optional[str] = None,
                              tts_backend: Optional[SpeechBackend] = None,
                              speech_mode: Optional[SpeechMode] = None,
                              **kwargs) -> Dict[str, Any]:   # verified: agent.py:605
          """Existing contract + routing per §2 matrix. Raises ValueError on unknown backend/mode."""

      def _resolve_speech_route(self, tts_backend: Optional[str], speech_mode: Optional[str]) -> tuple[str, str]:
          """kwarg > attribute > default; ValueError listing valid values."""

      @staticmethod
      def _to_speakable(text: str, *, strip_speaker_labels: bool = False) -> str:
          """markdown_to_plain + optional removal of leading '<Name>:' labels per line."""

      async def _synthesize_with_backend(self, text: str, backend: str, output_directory: Path) -> Path:
          """Lazy-import parrot.voice.tts (ImportError names the extra); build TTSConfig from
          speech_voice/speech_language/speech_format/speech_tts_options; get_shared_synthesizer;
          synthesize(text, language=...); write podcast_<ts>.<ext>; return the path. Never closes the shared synth."""
  ```
  In `script` mode for non-Gemini backends, the single narrator is the first entry
  of `self.speakers`. The system instruction resolves as follows:
  - if the caller passed an explicit `podcast_instructions` (anything other than
    the default `"for_podcast.txt"`), use it as-is;
  - otherwise use a built-in narration instruction: *"Narrate the following report
    as a single presenter, clearly and concisely, highlighting the key findings."*

### Module 5: Documentation
- **Path**: `docs/voice/speech-report-tts-backends.md` (new)
- **Responsibility**: the backend/mode matrix, agent attributes, extras to install,
  Supertonic weights (`SUPERTONIC_MODEL_PATH`), Polly credentials, region and
  long-form limits, and output formats.
- **Depends on**: M4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_polly_split_text_sentence_boundaries` | M1 | chunks ≤ 2800 chars, split on sentences, oversized sentence hard-split, order kept |
| `test_polly_synthesize_concatenates_chunks` | M1 | mocked aioboto3 client called once per chunk in order; bytes concatenated; `mime_format="audio/mpeg"` |
| `test_polly_engine_region_voice_defaults` | M1 | defaults `long-form` / `us-east-1` / `Danielle`; `AWS_POLLY_REGION` honoured |
| `test_polly_unsupported_mime_raises` | M1 | `audio/wav` → ValueError |
| `test_polly_missing_aioboto3_importerror` | M1 | ImportError message names `voice-polly` |
| `test_synthesizer_creates_polly_backend` | M1 | `TTSConfig(backend="polly")` → `AmazonPollyTTSBackend` |
| `test_shared_synthesizer_same_config_same_instance` | M2 | equal configs → identical object; different configs → different |
| `test_shared_synthesizer_concurrent_first_call` | M2 | `asyncio.gather` of N calls creates exactly one instance |
| `test_close_shared_synthesizers_best_effort` | M2 | a failing `close()` is logged, the cache is emptied |
| `test_supertonic_ensure_session_once_under_threads` | M2 | two concurrent `synthesize` calls load the session once |
| `test_google_backend_returns_wav` | M3 | `.audio` starts with `b"RIFF"`, `mime_format == "audio/wav"`, 24 kHz mono 16-bit |
| `test_google_backend_no_double_wrap` | M3 | RIFF input not re-wrapped |
| `test_telegram_tts_audio_to_ogg_by_mime` | M3 | wav / mpeg / ogg / raw-pcm inputs each decode through the right path |
| `test_speech_report` (existing, unchanged) | M4 | default path identical |
| `test_speech_report_forwards_script_and_tts_model` (existing) | M4 | unchanged |
| `test_speech_report_omits_model_kwargs_by_default` (existing) | M4 | unchanged |
| `test_speech_report_verbatim_supertonic_zero_llm_calls` | M4 | client `create_conversation_script`/`generate_speech` never called; wav written; script_path holds normalised text |
| `test_speech_report_script_mode_single_narrator` | M4 | `ConversationalScriptConfig.speakers` has 1 entry for non-Gemini; speaker labels stripped before TTS |
| `test_speech_report_gemini_verbatim_single_voice` | M4 | `generate_speech` called with one `SpeakerConfig`, no script call |
| `test_speech_report_kwarg_overrides_attribute` | M4 | per-call `tts_backend` beats the `speech_backend` attribute |
| `test_speech_report_invalid_backend_raises` | M4 | ValueError lists the valid values |
| `test_speech_report_backend_failure_no_fallback` | M4 | a synth error propagates; Gemini never called |
| `test_speech_report_missing_integrations_importerror` | M4 | the lazy import failure names the extra |
| `test_speech_report_extension_follows_mime` | M4 | `audio/mpeg` → `.mp3`, `audio/wav` → `.wav` |

### Integration Tests
| Test | Description |
|---|---|
| `test_tts_integration` (existing, updated) | the full `VoiceSynthesizer` surface including `"polly"` (mocked AWS) |
| `test_telegram_voice_reply` (existing, updated) | the voice reply still sends OGG/Opus with WAV input from Google |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_polly_client():
    """aioboto3-like async context manager whose synthesize_speech returns {'AudioStream': <async read()>}."""

@pytest.fixture(autouse=True)
async def _reset_shared_synth():
    """Clear parrot.voice.tts.synthesizer._SHARED between tests."""
```
Tests live next to their distribution: `packages/ai-parrot/tests/test_basic_agent_new.py`,
`packages/ai-parrot-integrations/tests/voice/tts/`, `packages/ai-parrot-integrations/tests/test_telegram_voice_reply.py`.

---

## 5. Acceptance Criteria

- [ ] AC1: With no attribute and no kwarg, `speech_report` makes exactly the same client calls as today, and the three existing `test_speech_report*` tests pass **unmodified**.
- [ ] AC2: `speech_backend` / `speech_mode` attributes exist on `BasicAgent`. The `speech_report(tts_backend=, speech_mode=)` kwargs override them. Unknown values raise `ValueError`.
- [ ] AC3: `speech_mode="verbatim"` with `supertonic`, `google_tts` or `aws_polly` never calls `self.client`.
- [ ] AC4: In `script` mode with a non-Gemini backend, the script is requested with exactly one speaker, and speaker labels are stripped before TTS.
- [ ] AC5: The output file extension matches `SynthesisResult.mime_format` (backend-native). Google and Supertonic produce `.wav`; Polly defaults to `.mp3`.
- [ ] AC6: In `verbatim` mode, `script_path` points to a file containing exactly the text sent to TTS.
- [ ] AC7: Markdown is normalised through `markdown_to_plain` on every path except `gemini`+`script`.
- [ ] AC8: `TTSConfig(backend="polly")` → `AmazonPollyTTSBackend`. It uses `aioboto3` only (no sync `boto3`), defaults to engine `long-form`, region `us-east-1` (or `AWS_POLLY_REGION`) and voice `Danielle`, and chunks text above 2 800 chars.
- [ ] AC9: `get_shared_synthesizer` returns the same instance for equal configs under concurrent first calls, and `speech_report` never closes it.
- [ ] AC10: Supertonic loads its model at most once under concurrent first calls.
- [ ] AC11: `GoogleTTSBackend` returns WAV bytes (`RIFF` header, 24 kHz mono 16-bit) with `mime_format == "audio/wav"`.
- [ ] AC12: The Telegram voice reply decodes by `mime_format` and still sends a valid OGG/Opus voice note with Google WAV input.
- [ ] AC13: Non-default backend failures propagate. There is no fallback to Gemini.
- [ ] AC14: If `parrot.voice.tts` or a backend extra is missing, an `ImportError` names the pip extra to install.
- [ ] AC15: The `voice-polly = ["aioboto3>=13.2.0"]` extra exists and is included in the `voice` bundle.
- [ ] AC16: The `print(...)` at `agent.py:688` is replaced by `self.logger.info`, and the new code adds no `print`.
- [ ] AC17: `ruff check` is clean on the touched files. Tests pass: `pytest packages/ai-parrot/tests/test_basic_agent_new.py packages/ai-parrot-integrations/tests/voice/tts packages/ai-parrot-integrations/tests/test_telegram_voice_reply.py -v`.
- [ ] AC18: `docs/voice/speech-report-tts-backends.md` documents the matrix, attributes, extras and Polly limits.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**. Verified against `5fc0c29c6` (post-merge `dev`, 2026-09-22).

### Verified Imports
```python
from ..models.google import ConversationalScriptConfig, FictionalSpeaker  # verified: agent.py:19 (models/google.py:245,260)
from ..conf import STATIC_DIR, AGENTS_DIR                                  # verified: agent.py:24
from parrot.models.outputs import SpeakerConfig, SpeechGenerationPrompt    # verified: models/outputs.py:235,244 (used in google_backend.py)
from parrot.outputs.formats.text import markdown_to_plain                  # verified: packages/ai-parrot/src/parrot/outputs/formats/text.py:115
from parrot.voice.tts.synthesizer import VoiceSynthesizer                  # verified: used lazily by handlers/agent_voice.py and telegram/wrapper.py:3217
from parrot.voice.tts.models import TTSConfig, SynthesisResult             # verified: voice/tts/models.py:17,107
# parrot/voice/tts/__init__.py __all__ (verified :22): VoiceSynthesizer, AbstractTTSBackend,
#   GoogleTTSBackend, TTSConfig, SynthesisResult — Supertonic backends are NOT exported
#   (VoiceSynthesizer imports SupertonicONNXBackend lazily from .supertonic_inference).
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):                       # :29
    speech_context: str = ""                                        # :56
    speech_system_prompt: str = ""                                  # :57
    podcast_system_instruction: str = None                          # :58
    speech_length: int = 20                                         # :59
    num_speakers: int = 1                                           # :60
    speakers: Dict[str, str] = {"interviewer": {..., "gender": "female"}, "interviewee": {..., "gender": "male"}}  # :61
    def _create_filename(self, prefix: str = "report", extension: str = "pdf") -> str  # :430 → f"{prefix}_{%Y%m%d_%H%M%S}.{extension}"
    async def speech_report(self, report: str, max_lines: int = 15, num_speakers: int = 2,
        podcast_instructions: Optional[str] = "for_podcast.txt", directory: Optional[Path] = None,
        output_directory: Optional[Path] = None, script_model: Optional[str] = None,
        tts_model: Optional[str] = None, **kwargs) -> Dict[str, Any]   # :605
        # :622 script_output_directory.mkdir(...) ; script dir default STATIC_DIR/<agent_id>/generated_scripts
        # :659-668 async with self.client: create_conversation_script(report_data=, max_lines=, use_structured_output=True[, model=])
        #          voice_prompt = response.output  (SpeechGenerationPrompt; .prompt is "Name: line" text)
        # :677 output_directory default STATIC_DIR/<agent_id>/podcasts
        # :686 speech_result = await client.generate_speech(**speech_kwargs)
        # :688 print(f"✅ Multi-voice speech saved to: ...")
        # returns {"script_path": ..., "podcast_path": speech_result.files[0] | None}
    async def _generate_report(self, response: AgentResponse, with_speech: bool = True) -> AgentResponse  # :724
        # :748 self.speech_report(report=..., max_lines=self.speech_length, num_speakers=self.num_speakers) inside try/except → logger.error
class Agent(BasicAgent): ...                                        # :1335

# packages/ai-parrot/src/parrot/models/google.py
class FictionalSpeaker(BaseModel):                                  # :245
    name: str; characteristic: str; role: Literal["interviewer", "interviewee"]; gender: Literal["female","male","neutral"] = "neutral"
class ConversationalScriptConfig(BaseModel):                        # :260
    report_text: str; speakers: List[FictionalSpeaker]; context: str; length: int = 1000
    system_prompt: Optional[str] = None; system_instruction: Optional[str] = None

# packages/ai-parrot/src/parrot/models/outputs.py
class SpeakerConfig(BaseModel): name: str; voice: str; gender: Optional[str] = None      # :235
class SpeechGenerationPrompt(BaseModel):                            # :244
    prompt: str; speakers: List[SpeakerConfig]; model: Optional[str] = None; language: Optional[str] = "en-US"

# packages/ai-parrot-client-google/src/parrot/clients/google/generation.py
async def create_conversation_script(self, report_data: ConversationalScriptConfig, model=GoogleModel.GEMINI_2_5_FLASH,
    user_id=None, session_id=None, temperature=0.7, use_structured_output=False, max_lines=20) -> AIMessage  # :402
async def generate_speech(self, prompt_data: SpeechGenerationPrompt, model=GoogleModel.GEMINI_2_5_FLASH_TTS,
    output_directory: Optional[Path] = None, system_prompt=None, temperature=0.7, mime_format="audio/wav",
    user_id=None, session_id=None, max_retries=3, retry_delay=1.0) -> AIMessage              # :569

# packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py
class AbstractTTSBackend(ABC):                                      # :17
    async def synthesize(self, text: str, *, voice: Optional[str] = None, mime_format: str = "audio/ogg",
                         language: Optional[str] = None) -> SynthesisResult   # :38 (abstract)
    async def close(self) -> None                                   # :80

# packages/ai-parrot-integrations/src/parrot/voice/tts/models.py
class TTSConfig(BaseModel):                                         # :17
    backend: Literal["google", "elevenlabs", "openai", "supertonic"] = "google"   # :47
    voice: Optional[str]; language: Optional[str]; mime_format: str = "audio/ogg"
    total_step: int = 8 (1..50); speed: float = 1.05 (0..3]
class SynthesisResult(BaseModel): audio: bytes; mime_format: str; duration_s: Optional[float]   # :107

# packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py
class VoiceSynthesizer:                                             # :22
    def __init__(self, config: Optional[TTSConfig] = None) -> None  # :47
    def _get_backend(self) -> AbstractTTSBackend                    # :53 (branches google :72, supertonic :81, elevenlabs/openai raise :96)
    async def synthesize(self, text: str, *, language: Optional[str] = None) -> SynthesisResult  # :109
    async def close(self) -> None                                   # :154

# packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py
_DEFAULT_VOICE = "Charon"                                           # :28
class GoogleTTSBackend(AbstractTTSBackend):                         # :31
    def __init__(self, client=None, *, voice: Optional[str] = None, **kwargs)   # :57
    async def synthesize(...) -> SynthesisResult                    # :97 — client.generate_speech(prompt) with no output_directory;
                                                                    #   audio = ai_message.output (raw PCM); :186 returns requested mime_format

# packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py
_SAMPLE_RATE = 44100                                                # :42
class SupertonicTTSBackend(AbstractTTSBackend):                     # :51
    def __init__(self, voice=None, *, model_path=None, sample_rate=_SAMPLE_RATE, inference_fn=None, **kwargs)  # :80
    def _ensure_session(self) -> None                               # :134 (no lock)
    async def synthesize(...)                                       # :164 — asyncio.to_thread(self._synthesize_sync, ...); WAV; truthful mime
    # :257 self._ensure_session()  (inside _synthesize_sync, i.e. in a worker thread)
    def _pcm_to_wav(self, pcm_bytes: bytes) -> bytes                # :279
# packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py
class SupertonicONNXBackend(SupertonicTTSBackend):                  # :689 — __init__(*, model_dir, voice, ..., default_voice="M1", total_step=8, speed=1.05) :713
    def _ensure_session(self) -> None                               # :758 (overrides; builds SupertonicPipeline)
    # module imports numpy at top (:53) — do NOT import it from polly_backend

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
    async def _get_synthesizer(self) -> "VoiceSynthesizer"          # :3204 — per-wrapper VoiceSynthesizer(TTSConfig(backend=self.config.tts_backend, voice=..., language=...))
    # voice reply: :3432 `from pydub import AudioSegment`; :3450 tts_result = await synth.synthesize(...)
    # :3458 nested def _convert_pcm_to_ogg(raw_pcm) → AudioSegment(data=, sample_width=2, frame_rate=24000, channels=1).export(ogg, libopus)
# packages/ai-parrot-server/src/parrot/handlers/agent_voice.py
    async def _synthesize(self, text: str) -> Tuple[str, str]       # :379 — per-call VoiceSynthesizer, returns (b64, result.mime_format)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `speech_report` non-Gemini branch | `get_shared_synthesizer` → `VoiceSynthesizer.synthesize()` | lazy import + await | `synthesizer.py:109` |
| `speech_report` script (1 speaker) | `client.create_conversation_script()` | existing call | `agent.py:659-668`, `generation.py:402` |
| `speech_report` gemini+verbatim | `client.generate_speech(prompt_data=SpeechGenerationPrompt(...), output_directory=...)` | method call | `generation.py:569` |
| `_to_speakable` | `markdown_to_plain()` | function call | `outputs/formats/text.py:115` |
| `VoiceSynthesizer._get_backend` | `AmazonPollyTTSBackend` | lazy import in new `elif` | `synthesizer.py:96` |
| Telegram voice reply | `_tts_audio_to_ogg(tts_result.audio, tts_result.mime_format)` | replaces nested fn | `wrapper.py:3458,3469` |

### Does NOT Exist (Anti-Hallucination)
- ~~`BaseAgent`~~: the class is `BasicAgent` (`agent.py:29`).
- ~~Google Live API in `speech_report`~~: it uses `generate_content` TTS.
- ~~Amazon Polly anywhere in the repo~~: no backend, no import, no extra.
- ~~A Nova Sonic one-shot TTS~~: `NovaAudio.stream_voice` (`ai-parrot-client-amazon/.../nova/audio.py:1293`) is duplex-only.
- ~~`TTSConfig.backend == "polly"`~~, ~~`TTSConfig.polly_engine`~~, ~~`TTSConfig.polly_region`~~: new in M1.
- ~~`BasicAgent.speech_backend` / `speech_mode` / `speech_voice` / `speech_language` / `speech_format` / `speech_tts_options`~~: new in M4.
- ~~`get_shared_synthesizer`~~ / ~~`close_shared_synthesizers`~~: new in M2.
- ~~`parrot.voice.tts.polly_backend`~~ / ~~the `voice-polly` extra~~: new in M1.
- ~~`GoogleTTSBackend._pcm_to_wav`~~: new in M3. The Supertonic one is an instance method on a different class; do not import it across.
- ~~`TelegramAgentWrapper._tts_audio_to_ogg`~~: new in M3.
- ~~Google Cloud Text-to-Speech (`google-cloud-texttospeech`)~~: not used.
- ~~A shutdown hook on `BasicAgent` that closes TTS~~: none exists. The shared cache is process-scoped by design.

### Edit Sites (Blueprint Anchors)

Verified against: `5fc0c29c6`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/tts/polly_backend.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/models.py` | MODIFY | `backend: Literal["google", "elevenlabs", "openai", "supertonic"] = Field(` | `models.py:47` | 1 |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py` | MODIFY | `elif backend_name in ("elevenlabs", "openai"):` | `synthesizer.py:96` | 1 |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/__init__.py` | MODIFY | `__all__ = [` | `__init__.py:22` | 1 |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py` | MODIFY | `self._ensure_session()` | `supertonic_backend.py:257` | 1 |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py` | MODIFY | `return SynthesisResult(audio=audio_bytes, mime_format=mime_format)` | `google_backend.py:186` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `def _convert_pcm_to_ogg(raw_pcm: bytes) -> bytes:` | `wrapper.py:3458` | 1 |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | `voice-supertonic = [` (extra) and `"ai-parrot-integrations[voice-supertonic]",` (in `voice = [` bundle) | `pyproject.toml:80`, `:116` | 1 / 1 |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | `num_speakers: int = 1  # Default number of speakers for the podcast` | `agent.py:60` | 1 |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | `async def speech_report(` | `agent.py:605` | 1 |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | `speech_result = await client.generate_speech(**speech_kwargs)` | `agent.py:686` | 1 |
| `packages/ai-parrot/tests/test_basic_agent_new.py` | MODIFY | (append new tests after `test_speech_report_omits_model_kwargs_by_default`, :267) | `:267` | 1 |
| `packages/ai-parrot-integrations/tests/voice/tts/test_polly_backend.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/voice/tts/test_shared_synthesizer.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/voice/tts/test_google_backend.py` | MODIFY | `async def test_google_backend_returns_correct_mime_format():` | `test_google_backend.py:51` | 1 |
| `packages/ai-parrot-integrations/tests/test_telegram_voice_reply.py` | MODIFY | `return_value=SynthesisResult(audio=audio, mime_format="audio/ogg")` | `test_telegram_voice_reply.py:97` | 1 |
| `docs/voice/speech-report-tts-backends.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `GoogleTTSBackend` / `SupertonicTTSBackend`: construction does no I/O,
  heavy dependencies are imported lazily, and the `ImportError` names the extra
  (`supertonic_backend.py:147-155`).
- Match the lazy-import style of `AgentVoiceTalk._synthesize` (`agent_voice.py:398`),
  so importing `ai-parrot` core never requires `ai-parrot-integrations`.
- Async-first: use `aioboto3` (`async with session.client("polly", region_name=...)`),
  `await resp["AudioStream"].read()`. Never call sync `boto3` in the event loop.
- Use `self.logger` everywhere, never `print`. Google-style docstrings and strict
  type hints.
- Keep the default `gemini`+`script` code path textually intact. Branch **before**
  it rather than refactoring it, so AC1 holds.

### Known Risks / Gotchas
- **Telegram converter + WAV**: `wrapper.py:3458` builds `AudioSegment(data=...)`
  from raw PCM. Without M3's converter change, Google WAV would be read as samples
  (the header becomes an audible click). M3 changes both sides together.
  Supertonic WAV at 44.1 kHz through the old converter is already wrong today; M3
  also fixes that.
- **Existing Google test**: `test_google_backend.py:51` requests `audio/wav` and
  still passes. Any test that requests `audio/ogg` and expects it echoed back must
  now expect `audio/wav`.
- **Telegram test fixture** `test_telegram_voice_reply.py:97` uses
  `mime_format="audio/ogg"` with fake bytes. The new converter decodes OGG through
  `from_file`, so the test must patch `AudioSegment` or supply real bytes.
- **Speaker labels**: `voice_prompt.prompt` from `create_conversation_script` uses
  `"Name: line"` lines, intended for Gemini's multi-speaker config. Single-narrator
  TTS must strip them, or the narrator reads the names aloud.
- **Polly long-form**: available only in some regions and voices. An invalid
  engine/voice/region combination surfaces the AWS error code unchanged; there is
  no automatic engine downgrade. Bedrock bearer tokens (`AWS_BEARER_TOKEN_BEDROCK`)
  do not authenticate Polly; it needs IAM keys, a profile or a role.
- **OGG concatenation**: joining `ogg_vorbis` chunks produces a chained Ogg
  stream. It is valid, and most players handle it. MP3 and PCM concatenate
  cleanly. This is documented in M5.
- **Shared cache lifetime**: callers must not `close()` a shared synthesizer.
  The cache is keyed by the full config, so different voices or engines get
  separate instances. `asyncio.Lock` is created lazily, so it is not bound to an
  import-time loop, and tests reset `_SHARED`.
- **Supertonic thread race**: `_ensure_session()` runs in `asyncio.to_thread`
  workers (`supertonic_backend.py:257`). Without M2's `threading.Lock`, two
  concurrent first calls load the model twice.
- **No fallback**: a misconfigured backend fails loudly. `_generate_report`
  swallows and logs the error (`agent.py:748-755`), so the report still ships
  without a podcast.
- **Cross-feature**:
  - `bots/agent.py` is a hot file; check in-flight FEAT-589 (Agent `__init__`) and
    FEAT-585 before starting M4.
  - `parrot/voice/tts/` is also read by FEAT-537 via `supertonic_inference` in
    `liveavatar/voice_provider.py`. That use is additive and does not touch
    `SupertonicPipeline`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aioboto3` | `>=13.2.0` | async Polly (new extra `voice-polly`; already pinned by `ai-parrot-client-amazon`) |
| `onnxruntime` | `>=1.17` | Supertonic (existing extra `voice-supertonic`) |
| `pydub` | `>=0.25` | Telegram OGG conversion (existing extra `voice-tts`) |

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-591-speech-report-models`. The
  `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1: both modify `voice/tts/synthesizer.py` and `get_shared_synthesizer`
    builds a `TTSConfig` that must accept `"polly"`.
  - M4 → M1, M2: M4 lazily imports `get_shared_synthesizer` and maps
    `aws_polly` → `"polly"`.
  - M4 → M3 (soft): M4's `google_tts` assumes WAV from `GoogleTTSBackend`. M4's
    tests mock the synth, so the edge exists for runtime correctness only.
  - M5 → M4.
  - M3 has no incoming edges and can run in parallel with M1 and M2.
- **Shared files**:
  - `voice/tts/synthesizer.py` (M1, M2), so those two tasks are serialized.
  - `voice/tts/__init__.py` (M2 exports).
- **Exclusive resources**: `packages/ai-parrot-integrations/pyproject.toml` (M1 —
  extras edit; lockfile untouched, `uv add --no-sync` not needed because this is
  an optional extra).
- **Cross-feature dependencies**: none must merge first. Coordinate with
  FEAT-589/FEAT-585 on `bots/agent.py`. Ledger `issue:0fe9c8221dfa` (Supertonic as
  the Telegram default) follows this feature.

---

## 8. Open Questions

- [x] Flow type / base branch — *Resolved in brainstorm*: feature on `dev`.
- [x] Fast-path content — *Resolved in brainstorm*: both `verbatim` and single-narrator `script`, selectable by a mode flag independent of the backend.
- [x] Meaning of "Google TTS" — *Resolved in brainstorm*: the existing Gemini TTS (`GoogleTTSBackend` / `generate_speech`, single voice), not Cloud Text-to-Speech.
- [x] AWS engine — *Resolved in brainstorm*: Amazon Polly instead of Nova 2 Sonic.
- [x] Flag scope — *Resolved in brainstorm*: agent attribute default + per-call kwarg override.
- [x] Dependency direction — *Resolved in brainstorm*: lazy import of `parrot.voice.tts` with a clear ImportError naming the extra.
- [x] Multi-voice on non-Gemini backends — *Resolved in brainstorm*: force a single narrator.
- [x] Output format — *Resolved in brainstorm*: backend-native (extension follows `mime_format`).
- [x] Flag value naming — *Resolved in brainstorm*: `aws_polly` (no `aws_nova` alias). Full set: `gemini` (default) | `google_tts` | `supertonic` | `aws_polly`.
- [x] Gemini raw PCM — *Resolved in brainstorm*: wrap PCM (24 kHz mono s16le) in a WAV header, the one documented exception to "backend-native"; `GoogleTTSBackend` is also fixed so `SynthesisResult.mime_format` is truthful.
- [x] `verbatim` mode `script_path` — *Resolved in brainstorm*: save the exact (normalised) text sent to TTS under `generated_scripts/`.
- [x] Synthesizer reuse — *Resolved in brainstorm*: process-wide cache keyed by the effective backend config, shared across agents, lazily built under an `asyncio.Lock`; best-effort close at process shutdown.
- [x] Polly long text — *Resolved in brainstorm*: chunk on sentence boundaries under the per-request limit, sequential `synthesize_speech`, concatenate frames; no S3 task.
- [x] Default Polly engine — *Resolved in brainstorm*: `long-form` (region-limited; default voice from the long-form set; region configurable).
- [x] Failure policy — *Resolved in brainstorm*: fail, no fallback to Gemini.
- [x] Markdown normalisation — *Resolved in brainstorm*: yes, in both modes for non-Gemini backends; the default Gemini multi-speaker path is unchanged.
- [x] GoogleTTSBackend WAV change vs the Telegram PCM assumption — *Resolved at spec time (Jesus, 2026-09-22)*: fix the backend **and** adapt the Telegram converter in this feature (M3). Making Supertonic the Telegram default stays in `issue:0fe9c8221dfa`.
- [x] Single-narrator instruction — *Decided at spec time*: an explicit caller `podcast_instructions` is used as-is; otherwise a built-in narration instruction (§3 M4).
- [x] Gemini + verbatim normalisation — *Decided at spec time*: normalised too. Only `gemini`+`script` is exempt (it is the unchanged legacy path).

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: skipped (exploration doc status is `exploration`, not `accepted` — §3b precondition) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-22 | Jesus (with Claude) | Initial draft from brainstorm Option A; FEAT-591 reserved |
