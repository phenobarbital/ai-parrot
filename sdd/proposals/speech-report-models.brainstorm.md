---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-integrations]
tags: [tts, speech-report, supertonic, polly, voice]
---

# Brainstorm: speech_report pluggable TTS backends (fast-path)

**Date**: 2026-09-22
**Author**: Jesus (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`BasicAgent.speech_report()` (`packages/ai-parrot/src/parrot/bots/agent.py:595`) is
hard-wired to Google. It makes two Gemini calls on `self.client`:
`create_conversation_script()` writes a multi-speaker podcast script, then
`generate_speech()` (Gemini TTS through `generate_content` with
`response_modalities=["AUDIO"]`) turns it into audio. So every report podcast
costs one LLM script call plus one Gemini TTS call. It also requires
`self.client` to be a `GoogleGenAIClient`, or at least a client that exposes
those two methods.

Agent owners want a **fast path**:
1. Read the report text **verbatim**, with no script-generation LLM call, **or**
   keep the script step but voice it with a single narrator.
2. Pick the TTS engine: **Supertonic** (local ONNX, sub-second, free), **Google
   Gemini TTS** (single voice, the existing `GoogleTTSBackend`), or **AWS**. For
   AWS we use **Amazon Polly**, not Nova 2 Sonic, because Sonic is a
   bidirectional speech-to-speech model with no one-shot "text in, audio out"
   endpoint.

The people affected are agent authors using `_generate_report(with_speech=True)`
(`agent.py:714`) and `ProductBot` (`bots/product.py:160`), plus ops teams paying
for the Gemini calls.

## Constraints & Requirements

- **Backward compatible default**: when no flag is set, behaviour stays
  byte-for-byte what it is today (Gemini script plus multi-speaker
  `generate_speech`). The existing tests `test_speech_report*`
  (`packages/ai-parrot/tests/test_basic_agent_new.py:197-293`) must keep passing
  unchanged.
- **Flag scope** (decided): an agent attribute sets the default and a per-call
  `speech_report(...)` kwarg overrides it.
- **Two independent axes** (decided): the *mode* (`script` | `verbatim`) and the
  *backend* (`gemini`-default | `google_tts` | `supertonic` | `aws_polly`).
- **Multi-voice** (decided): only the default Gemini path does multi-speaker.
  Non-default backends in `script` mode **force a single narrator** (the script
  is requested with 1 speaker).
- **Output format** (decided): **backend-native**. Supertonic gives WAV, Polly
  gives MP3 (or OGG), Gemini gives WAV (raw PCM wrapped in a WAV header, the one
  exception). The file extension follows the actual
  format. The return dict keeps its shape (`script_path`, `podcast_path`).
- **Dependency direction** (decided): core `ai-parrot` must not hard-depend on
  `ai-parrot-integrations`. `parrot.voice.tts` is **imported lazily** only when a
  non-default backend is chosen. A missing install raises an `ImportError` that
  names the extra to install.
- Async-first: Supertonic inference already runs in `asyncio.to_thread`. Polly
  uses `aioboto3` (never sync `boto3` in the event loop).
- No secrets in code. Polly uses the standard AWS credential chain.

---

## Options Explored

### Option A: Route `speech_report` through `parrot.voice.tts.VoiceSynthesizer` and add a Polly backend

Reuse the existing TTS abstraction from FEAT-213/FEAT-231: `AbstractTTSBackend`,
`TTSConfig` and `VoiceSynthesizer` in
`ai-parrot-integrations/src/parrot/voice/tts/`. It already ships
`GoogleTTSBackend` and `SupertonicONNXBackend`. The work is:

- Add an **`AmazonPollyTTSBackend`** (`polly_backend.py`) next to them. Register
  it as `"polly"` in `TTSConfig.backend` and in `VoiceSynthesizer._get_backend()`,
  and add a `voice-polly` extra (`aioboto3`).
- `speech_report` gains `tts_backend` / `speech_mode` kwargs, backed by new agent
  attributes. The default backend keeps the current code path exactly. Any other
  backend:
  1. gets its text either verbatim (the report) or from
     `create_conversation_script` with a single speaker;
  2. lazily imports `parrot.voice.tts` and builds a `TTSConfig` from the agent's
     speech settings (voice, language, format, Supertonic speed/steps);
  3. calls `synthesize()` and writes `result.audio` to
     `STATIC_DIR/<agent_id>/podcasts/` with the extension that matches
     `result.mime_format`.

✅ **Pros:**
- Maximum reuse: two of the three backends already exist and are tested.
- One TTS abstraction for the whole framework. Telegram voice replies get Polly
  for free.
- The default path is untouched, so the regression risk is near zero.
- `verbatim` + `supertonic` needs no network and no LLM at all, which makes it
  the true fast path.

❌ **Cons:**
- Core code reaches into a satellite package through a lazy import (a soft
  coupling, but only at runtime).
- `GoogleTTSBackend` returns **raw PCM** labelled with whatever `mime_format` was
  requested. The WAV header has to be added (or the default Gemini
  `generate_speech(output_directory=...)` file-writer reused) to get a playable
  file.
- Polly's per-request text limit (~3000 billed chars) needs chunking or the
  `long-form` engine / `StartSpeechSynthesisTask`.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Async Polly `synthesize_speech` | `>=13.2.0`, already pinned by `ai-parrot-client-amazon`; new extra `voice-polly` |
| `onnxruntime` | Supertonic inference | existing extra `voice-supertonic` (`>=1.17`) |
| `google-genai` | Gemini TTS | already a core Google-client dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py` — `VoiceSynthesizer` backend factory
- `packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py:689` — `SupertonicONNXBackend` (WAV output, text chunking, `to_thread`)
- `packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py:31` — `GoogleTTSBackend` (single voice)
- `packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py:279` — `_pcm_to_wav` pattern for wrapping Gemini PCM
- `packages/ai-parrot/src/parrot/bots/agent.py:595` — current `speech_report` (script step reused in `script` mode)

---

### Option B: Push TTS into the LLM clients (a `generate_speech` per provider)

Give each client family its own `generate_speech(prompt_data=SpeechGenerationPrompt, ...)`
that matches the Google one. The Amazon client (`ai-parrot-client-amazon`) would
wrap Polly. `speech_report` would then pick a client by flag instead of a TTS
backend.

✅ **Pros:**
- `speech_report` stays client-polymorphic (`async with client: client.generate_speech(...)`).
- AWS credentials and session handling are already solved in the Amazon client.

❌ **Cons:**
- **Supertonic is not an LLM client.** It has no home in this model, so we would
  need a fake "client" or a second mechanism anyway.
- Polly (a speech service) would sit on an LLM client that is memory-less by
  design (FEAT-524), which widens the `AbstractClient` surface.
- It duplicates the TTS abstraction that already exists in `parrot.voice.tts`.

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Polly inside the Amazon client | already a dependency there |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:569` — `generate_speech` signature to mirror
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py` — AWS session/credentials

---

### Option C: `speech_report` as a pipeline of pluggable "renderers" behind a core registry (unconventional)

Split podcast generation into two swappable stages: a **ScriptRenderer**
(`llm-dialogue` | `llm-narration` | `passthrough`) and an **AudioRenderer**
(`gemini-multi` | `tts:<backend>`). Core `ai-parrot` defines a tiny protocol and
a name registry. Satellites register renderers when they are imported, and a
single `speech_pipeline="passthrough+tts:supertonic"` string picks the pair.

✅ **Pros:**
- The most extensible option: ElevenLabs/OpenAI TTS, SSML pre-processing,
  translation and similar stages drop in without touching `speech_report`.
- It cleanly removes core's knowledge of satellite module paths.

❌ **Cons:**
- Over-engineered for three backends. The user explicitly chose a lazy import
  over a registry.
- Registration by import side effect is fragile: the renderer "disappears" if
  the satellite is never imported.
- It adds a concept and a string mini-language that agent authors must learn.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | pure refactor + Option A backends |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/voice/tts/` — would become the `tts:*` audio renderers

---

## Recommendation

**Option A** is recommended because:

- Two of the three requested engines (Supertonic and Gemini single-voice) already
  exist as `AbstractTTSBackend` implementations with tests. Only Polly is new,
  and it follows the same ~150-line pattern.
- It matches every decision taken in discovery (attribute + kwarg, lazy import,
  single narrator for non-Gemini, backend-native format). Option C contradicts
  the lazy-import decision, and Option B has no place for Supertonic.
- What we trade away: core carries a soft runtime import of `parrot.voice.tts`.
  This is acceptable because it only fires on opt-in, and the error message names
  the extra to install.

---

## Feature Description

### User-Facing Behavior

Agent authors configure this with class or config attributes on `BasicAgent`
(names to be finalised in the spec):

- `speech_backend` — `"gemini"` (default, today's behaviour) | `"google_tts"` |
  `"supertonic"` | `"aws_polly"`
- `speech_mode` — `"script"` (default) | `"verbatim"`
- `speech_voice`, `speech_language`, `speech_format`, plus the Supertonic knobs
  (`speed`, `total_step`), all optional

Per call:
`await agent.speech_report(report, tts_backend="supertonic", speech_mode="verbatim")`.

The result is the same dict as today:
`{"script_path": Path | None, "podcast_path": Path | None}`. In `verbatim` mode
`script_path` points at the saved report text (see Open Questions).

| mode \ backend | `gemini` (default) | `google_tts` / `supertonic` / `aws_polly` |
|---|---|---|
| `script` | **unchanged**: multi-speaker script + multi-voice `generate_speech` | script requested with 1 speaker → single-narrator TTS |
| `verbatim` | report → single-voice `generate_speech` | report → TTS directly (**zero LLM calls**) |

### Internal Behavior

1. Resolve the effective backend and mode (kwarg > attribute > default).
2. **Text stage**
   - `script` mode: build `ConversationalScriptConfig` as today. For non-Gemini
     backends, pass `num_speakers=1`. Call `client.create_conversation_script`
     and save the script.
   - `verbatim` mode: use the report text, normalised (markdown stripped), and
     save it to `generated_scripts/` as the `script_path`. Skip `self.client`
     entirely.
   - For non-Gemini backends, markdown normalisation applies in both modes.
3. **Audio stage**
   - `gemini`: the existing `client.generate_speech(prompt_data, output_directory)`.
   - Any other backend: lazily import `parrot.voice.tts`, build a `TTSConfig`,
     fetch the synthesizer from a **process-wide cache** keyed by that config
     (built lazily under an `asyncio.Lock`, so the Supertonic ONNX model loads
     once per process), `await synth.synthesize(text, language=...)`, and write
     the bytes to `podcasts/<name>.<ext>`, where `ext` comes from `mime_format`.
4. **Polly backend**: `aioboto3` session → `polly.synthesize_speech(Text=...,
   OutputFormat="mp3"|"ogg_vorbis"|"pcm", VoiceId=..., Engine="long-form"
   (default) | "generative" | "neural", LanguageCode=...)`, then
   `await AudioStream.read()`. The region is configurable and defaults to one
   where long-form exists (us-east-1). The default voice comes from the
   long-form set.
   Text longer than the per-request limit is chunked on sentence boundaries and
   the MP3/OGG frames are concatenated in order.
5. Replace the stray `print("✅ Multi-voice ...")` at `agent.py:678` with
   `self.logger.info`.

### Edge Cases & Error Handling

- **No fallback**: any non-default backend failure raises; it never silently
  falls back to Gemini.
- **`parrot.voice.tts` not installed**: raise an `ImportError` naming
  `ai-parrot-integrations[voice-supertonic]` / `[voice-polly]`. `_generate_report`
  already catches and logs podcast failures (`agent.py:744`).
- **Supertonic weights missing** (`SUPERTONIC_MODEL_PATH` unset or the directory
  is absent): surface the backend's error. There is no fallback to Gemini.
- **Gemini PCM**: `GoogleTTSBackend` returns raw PCM (24 kHz mono s16le) under the
  requested `mime_format`. It is wrapped in a WAV header (decided), and the
  backend reports `audio/wav` truthfully.
- **Polly credentials**: Polly cannot use a Bedrock bearer token
  (`AWS_BEARER_TOKEN_BEDROCK`). It needs IAM keys, a profile or a role. Fail
  with a clear message.
- **Polly long-form engine** (the default) exists only in some regions and
  voices. If the engine/voice/region combination is invalid, report the AWS
  error unchanged. Chunks are synthesised sequentially and joined in order, and
  a failed chunk fails the whole report.
- **Empty report**: `ValueError` from the backend, the same contract as today.
- **Supertonic first-call latency**: the ONNX load is heavy. The process-wide
  cache means it happens once per process, and concurrent first calls wait on
  the same lock instead of loading the model twice.
- **Language**: pass `speech_language` through. Supertonic and Polly voices are
  language-specific, and a mismatched voice/language pair is a configuration
  error.

---

## Capabilities

### New Capabilities
- `speech-report-tts-backends`: backend + mode selection for `BasicAgent.speech_report`.
- `polly-tts-backend`: `AmazonPollyTTSBackend` in `parrot.voice.tts`.

### Modified Capabilities
- `telegram-voice-reply-tts` (FEAT-213) / Supertonic backend (FEAT-231):
  `TTSConfig.backend` and `VoiceSynthesizer` gain `"polly"`. This is additive.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/agent.py` `BasicAgent.speech_report` | modifies | new kwargs/attrs; default path unchanged |
| `parrot/bots/agent.py` `_generate_report` (L714) | depends on | inherits attribute defaults, no signature change |
| `parrot/bots/product.py` (L160) | depends on | same as above |
| `parrot/voice/tts/models.py` `TTSConfig` | extends | `backend` Literal += `"polly"`; Polly `engine` (default `long-form`) / `region` fields |
| `parrot/voice/tts/google_backend.py` | modifies | wrap raw PCM in WAV; truthful `mime_format` (check Telegram caller expectations) |
| `parrot/voice/tts/synthesizer.py` | extends | `_get_backend` branch for `"polly"` |
| `parrot/voice/tts/polly_backend.py` | new | `AmazonPollyTTSBackend(AbstractTTSBackend)` |
| `ai-parrot-integrations/pyproject.toml` | extends | new extra `voice-polly = ["aioboto3>=13.2.0"]`, added to `all` |
| `packages/ai-parrot/tests/test_basic_agent_new.py` | extends | new mode/backend tests; existing 3 unchanged |
| `packages/ai-parrot-integrations/tests/voice/` | extends | Polly backend tests (mock aioboto3) |

---

## Code Context

### User-Provided Code
None. The user described intent only: "current `speech_report` method of
BaseAgent uses only `generate_speech` from GoogleGenAIClient … fast-path for
using Supertonic TTS for only reading the report text or Google TTS or AWS
bedrock nova 2 audio, a flag can define … supertonic, google_tts or aws_nova".

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):                       # L29
    speech_context: str = ""                                        # L56
    speech_system_prompt: str = ""                                  # L57
    podcast_system_instruction: str = None                          # L58
    speech_length: int = 20                                         # L59
    num_speakers: int = 1                                           # L60
    speakers: Dict[str, str] = {"interviewer": {...}, "interviewee": {...}}  # L61
    async def speech_report(                                        # L595-683
        self, report: str, max_lines: int = 15, num_speakers: int = 2,
        podcast_instructions: Optional[str] = "for_podcast.txt",
        directory: Optional[Path] = None, output_directory: Optional[Path] = None,
        script_model: Optional[str] = None, tts_model: Optional[str] = None, **kwargs,
    ) -> Dict[str, Any]: ...
        # L649-658: async with self.client as client: client.create_conversation_script(
        #     report_data=script_config, max_lines=..., use_structured_output=True[, model=])
        # L660-663: script saved to STATIC_DIR/<agent_id>/generated_scripts/
        # L666-676: client.generate_speech(prompt_data=voice_prompt, output_directory=...[, model=])
        # L678: print(...)  <-- convention violation, replace with logger
        # returns {"script_path": ..., "podcast_path": speech_result.files[0] | None}
    async def _generate_report(self, response: AgentResponse, with_speech: bool = True) -> AgentResponse:  # L714
        # L738: self.speech_report(report=..., max_lines=self.speech_length, num_speakers=self.num_speakers)
class Agent(BasicAgent): ...                                        # L1325

# From packages/ai-parrot-client-google/src/parrot/clients/google/generation.py
async def create_conversation_script(...)                           # L402
async def generate_speech(self, prompt_data: SpeechGenerationPrompt,
    model=GoogleModel.GEMINI_2_5_FLASH_TTS, output_directory: Optional[Path] = None,
    system_prompt=None, temperature=0.7, mime_format="audio/wav", user_id=None,
    session_id=None, max_retries=3, retry_delay=1.0) -> AIMessage   # L569
    # uses generate_content + response_modalities=["AUDIO"]; single vs multi-speaker SpeechConfig

# From packages/ai-parrot/src/parrot/models/outputs.py
class SpeakerConfig(BaseModel): name: str; voice: str; gender: Optional[str]  # L235
class SpeechGenerationPrompt(BaseModel):                            # L244
    prompt: str; speakers: List[SpeakerConfig]; model: Optional[str] = None
    language: Optional[str] = "en-US"

# From packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py
class AbstractTTSBackend(ABC):                                      # L17
    async def synthesize(self, text: str, *, voice: Optional[str] = None,
        mime_format: str = "audio/ogg", language: Optional[str] = None) -> SynthesisResult  # L38
    async def close(self) -> None                                   # L80

# From packages/ai-parrot-integrations/src/parrot/voice/tts/models.py
class TTSConfig(BaseModel):                                         # L17
    backend: Literal["google", "elevenlabs", "openai", "supertonic"] = "google"  # L47
    voice: Optional[str]; language: Optional[str]; mime_format: str = "audio/ogg"
    total_step: int = 8  (1..50, Supertonic only); speed: float = 1.05 (Supertonic only)
class SynthesisResult(BaseModel):                                   # L107
    audio: bytes; mime_format: str; duration_s: Optional[float]

# From packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py
class VoiceSynthesizer:                                             # L22
    def __init__(self, config: Optional[TTSConfig] = None) -> None  # L47
    def _get_backend(self) -> AbstractTTSBackend                    # L53 (google / supertonic branches; elevenlabs/openai raise)
    async def synthesize(self, text: str, *, language: Optional[str] = None) -> SynthesisResult  # L109
    async def close(self) -> None                                   # L154

# From packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py
class GoogleTTSBackend(AbstractTTSBackend):                         # L31
    def __init__(self, client: Optional["GoogleGenAIClient"] = None, *, voice: Optional[str] = None, **kwargs)  # L57
    async def synthesize(...)                                       # L97 — returns RAW PCM in .audio, labelled with requested mime_format

# From packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py
_SAMPLE_RATE = 44100                                                # L42
class SupertonicTTSBackend(AbstractTTSBackend):                     # L51
    def __init__(self, voice=None, *, model_path=None, sample_rate=_SAMPLE_RATE, inference_fn=None, **kwargs)  # L80
    async def synthesize(...)                                       # L164 — WAV output, truthful mime_format (L228)
    def _pcm_to_wav(self, pcm_bytes: bytes) -> bytes                # L279

# From packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py
def chunk_text(text: str, max_len: int = 300) -> list[str]          # L205
class SupertonicONNXBackend(SupertonicTTSBackend):                  # L689
    def __init__(self, *, model_dir=None, voice=None, onnx_subdir="onnx",
        voice_styles_subdir="voice_styles", default_voice="M1", total_step=8,
        speed=1.05, use_gpu=False, **kwargs)                        # L713 — voices M1..F5; SUPERTONIC_MODEL_PATH
```

#### Verified Imports
```python
from ..models.google import ConversationalScriptConfig, FictionalSpeaker  # agent.py:19 (models/google.py:245,260)
from ..conf import STATIC_DIR, AGENTS_DIR                                  # agent.py:24
from parrot.models.outputs import SpeakerConfig, SpeechGenerationPrompt    # used by google_backend.py
# parrot/voice/tts/__init__.py exports: VoiceSynthesizer, AbstractTTSBackend,
#   GoogleTTSBackend, TTSConfig, SynthesisResult  (NOT the Supertonic backends —
#   VoiceSynthesizer imports SupertonicONNXBackend lazily from .supertonic_inference)
```

#### Key Attributes & Constants
- Extras in `packages/ai-parrot-integrations/pyproject.toml`: `voice-tts = ["pydub>=0.25"]`, `voice-supertonic = ["onnxruntime>=1.17"]` (≈L76-81)
- `aioboto3>=13.2.0` is already a dependency of `packages/ai-parrot-client-amazon/pyproject.toml:17`
- Existing tests: `packages/ai-parrot/tests/test_basic_agent_new.py:197` (`test_speech_report`), `:232` (`..._forwards_script_and_tts_model`), `:267` (`..._omits_model_kwargs_by_default`)
- Callers: `agent.py:738` (`_generate_report`), `bots/product.py:160` (`podcast_instructions='product_conversation.txt'`)

### Does NOT Exist (Anti-Hallucination)
- ~~`BaseAgent`~~: the class is **`BasicAgent`** (`agent.py:29`); `Agent` subclasses it.
- ~~Google Live in `speech_report`~~: the current path is Gemini TTS via
  `generate_content` (`generate_speech`), **not** the Live API.
- ~~Amazon Polly anywhere in the repo~~: there are no Polly imports or backend.
- ~~Nova Sonic one-shot TTS~~: `NovaAudio.stream_voice`
  (`ai-parrot-client-amazon/.../nova/audio.py:1293`) is a bidirectional duplex
  stream only, and it cannot use a Bedrock bearer token.
- ~~`TTSConfig.backend == "polly"` / `"aws"`~~: not in the Literal yet.
- ~~`BasicAgent.speech_backend` / `speech_mode`~~: new attributes, not present today.
- ~~`parrot.voice.tts.PollyTTSBackend`~~ / ~~`voice-polly` extra~~: to be created.
- ~~Google Cloud Text-to-Speech (`google-cloud-texttospeech`)~~: not used; "google_tts" here means Gemini TTS via `GoogleTTSBackend`.

---

## Parallelism Assessment

- **Internal parallelism**: there are two separable halves. (1) Satellite: the
  Polly backend, `TTSConfig`/`VoiceSynthesizer` wiring, the extra, and tests
  under `ai-parrot-integrations`. (2) Core: the `speech_report` routing,
  attributes and tests in `ai-parrot`. (2) depends only on the *existing*
  `VoiceSynthesizer` interface, so it can proceed in parallel with (1) as long as
  the `"polly"` literal name is fixed in the spec.
- **Cross-feature independence**: `bots/agent.py` is a hot file. Check in-flight
  FEAT-589 (laya-adoption, touches `Agent.__init__` tests) and FEAT-585
  (plan-then-execute) for overlap at spec time. `parrot/voice/tts/` overlaps
  with FEAT-537 (multiroom/HeyGen), which uses `supertonic_inference` through
  `liveavatar/voice_provider.py`. The changes here are additive and do not
  touch `SupertonicPipeline`.
- **Recommended isolation**: `per-spec`
- **Rationale**: the feature is small (~4-6 tasks). A single worktree avoids
  merge churn on `agent.py`, and the two halves are small enough that
  sequential execution costs little.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus*: feature on `dev`.
- [x] Fast-path content — *Owner: Jesus*: both `verbatim` and single-narrator `script`, selectable by a mode flag independent of the backend.
- [x] Meaning of "Google TTS" — *Owner: Jesus*: the existing Gemini TTS (`GoogleTTSBackend` / `generate_speech`, single voice), not Cloud Text-to-Speech.
- [x] AWS engine — *Owner: Jesus*: Amazon Polly instead of Nova 2 Sonic.
- [x] Flag scope — *Owner: Jesus*: agent attribute default + per-call kwarg override.
- [x] Dependency direction — *Owner: Jesus*: lazy import of `parrot.voice.tts` with a clear ImportError naming the extra.
- [x] Multi-voice on non-Gemini backends — *Owner: Jesus*: force a single narrator.
- [x] Output format — *Owner: Jesus*: backend-native (extension follows `mime_format`).
- [x] Flag value naming — *Owner: Jesus*: `aws_polly` (no `aws_nova` alias). Full set: `gemini` (default) | `google_tts` | `supertonic` | `aws_polly`.
- [x] Gemini raw PCM — *Owner: Jesus*: wrap the PCM (24 kHz mono s16le) in a WAV header. This is the one documented exception to "backend-native". `GoogleTTSBackend` is also fixed so `SynthesisResult.mime_format` reports what it actually returns.
- [x] `verbatim` mode `script_path` — *Owner: Jesus*: save the exact (normalised) text sent to TTS under `generated_scripts/`, so the audio stays auditable.
- [x] Synthesizer reuse — *Owner: Jesus*: a **process-wide cache** keyed by the effective backend config (backend, voice, language, format and backend knobs), shared across agents and built lazily under an `asyncio.Lock`. This is the same idea as the shared pipeline in `liveavatar/voice_provider.py`. Closing at process shutdown is best-effort.
- [x] Polly long text — *Owner: Jesus*: chunk on sentence boundaries under the per-request limit, call `synthesize_speech` once per chunk in order, and join the MP3/OGG frames. No S3 task and no bucket.
- [x] Default Polly engine — *Owner: Jesus*: `long-form`. Caveat: it is only available in some regions (us-east-1) and supports only a few voices (e.g. Danielle, Gregory, Ruth, Patrick). The default voice must come from that set and the region must be configurable. Other engines (`generative`/`neural`) remain selectable.
- [x] Failure policy — *Owner: Jesus*: fail and never fall back to Gemini. `_generate_report` already logs the error and continues without a podcast.
- [x] Markdown normalisation — *Owner: Jesus*: yes, in **both** modes, for the non-Gemini backends: strip headings, emphasis, links (keep the text), code fences and inline code; drop or flatten tables. The default Gemini multi-speaker path is unchanged.
