---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot-client-google, ai-parrot-client-openai, ai-parrot-tools, ai-parrot-integrations, ai-parrot-server, ai-parrot]
tags: [model-deprecations, video-generation, computer-use, transcription, gemini, openai]
---

# Brainstorm: Model Deprecation Follow-ups (Veo → Omni, Computer Use, Whisper)

**Date**: 2026-10-22
**Author**: Jesus (with Claude)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

The 2026-10-22 deprecation sweep (branch `fix/model-deprecations-2026-10`) removed every
model with an announced shutdown from `OpenAIModel` / `GoogleModel` and moved defaults to
the providers' recommended replacements. Three migrations could not be done as a model-id
swap, because the replacement uses a different API or semantics, and were deferred here:

1. **Video generation.** Veo 3.1 preview models shut down on the Gemini Developer API on
   2026-10-22. The replacement, `gemini-omni-1.1-flash`, uses the Omni Interactions API.
   After the sweep, `GoogleGeneration.video_generation()` / `generate_videos()` have **no
   default model** and raise without one; the `/mediagen` handler, the `VideoGenerationPrompt`
   example, and the reel registry's `gemini_developer` default still point at dead
   `veo-3.1-*-preview` ids.
2. **Computer use.** `gemini-2.5-computer-use-preview-10-2025` shut down on 2026-07-28
   (replacement `gemini-3.8-flash`). `ComputerAgent` still defaults to the dead id, so it is
   broken today. The client detects computer-use mode **by model-name prefix**
   (`_is_computer_use_model`), so swapping in `gemini-3.8-flash` would force the
   `computer_use` tool onto *every* 3.8-flash call.
3. **OpenAI transcription.** `whisper-1` shuts down 2027-02-26 (replacement
   `gpt-transcribe` / `gpt-live-transcribe`). `OpenAIWhisperBackend` requests
   `response_format=verbose_json`, which historically only whisper supports.

Plus two small OpenAI clean-ups that become dead code after the 2026-12-11 snapshot
shutdowns: the `gpt-5-nano` `max_tokens` exception and `o3`/`o3-pro` in
`RESPONSES_ONLY_MODELS`.

**Who is affected:** anyone calling Google video generation (`/mediagen`, agents), the
`ComputerAgent` browser-automation flow, and MS Teams / voice transcription users.

## Constraints & Requirements

- Video model choice is **surface-driven via the reel profile registry** (user decision):
  `VideoProfileRegistry` (FEAT-564) is the single source of truth; no substring matching.
- Parameters the resolved profile cannot honour (starting frame, reference images, last
  frame, extension, duration, resolution on Omni) are **rejected before any paid call**
  with `ReelValidationError`, never silently dropped (same contract as `validate_scene`).
- The Vertex Veo GA profiles stay `enabled=False` — the spec §8 Q5 enablement gate is out
  of scope.
- Dead Developer-API Veo profiles are **removed**; `gemini-omni-1.1-flash` becomes the
  `gemini_developer` default.
- Computer use becomes an **explicit opt-in on the client** (driven by `ComputerAgent`),
  not inferred from the model name; legacy-id prefix detection may remain only as a
  backward-compatible signal.
- Transcription keeps segments/timestamps **when the model provides them**; otherwise it
  degrades to text-only and logs it. `TranscriptionResult` shape does not change.
- Hard cuts are acceptable (no external consumers); no deprecation shims.
- aiohttp only; no new third-party dependencies expected.

---

## Options Explored

### Option A: Point-fix each call site

Replace the dead ids at each site and add the minimum code per site: `video_generation`
gets an `if model.startswith("gemini-omni")` branch that calls the Interactions API
inline; `ComputerAgent` passes a new boolean to the client; the transcriber switches its
model and response format.

✅ **Pros:**
- Smallest diff; fast to land.
- No refactor of `video_generation`'s 200-line body.

❌ **Cons:**
- Duplicates the Omni call logic already in `reel/omni.py`.
- Brings back name-based branching that FEAT-564 explicitly replaced with the registry.
- `video_generation`'s Veo-only knobs keep being dropped with warnings instead of rejected.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `google-genai` | Interactions / generate_videos | already pinned |

🔗 **Existing Code to Reuse:**
- `parrot/clients/google/generation.py` — `video_generation`, `generate_videos`

---

### Option B: Route single-video generation through `generate_video_clip` (registry-driven)

Make `video_generation()` and `generate_videos()` thin façades over the existing
`generate_video_clip()` (FEAT-564 TASK-3330), which already resolves a model against
`VideoProfileRegistry`, runs `validate_scene`, and dispatches to `VeoClipAdapter` or
`OmniClipAdapter`. The registry drops the dead Developer-API Veo profiles and defaults
`gemini_developer` to Omni. `validate_scene` (or a sibling `validate_request`) is extended
to cover the extra knobs `video_generation` exposes (last frame, reference images,
extension, negative prompt, seed, number of videos), so unsupported options fail closed.
`/mediagen` and `VideoGenerationPrompt` stop hard-coding a model and take the registry
default for the client's surface.

Computer use: add an explicit client-level opt-in (`computer_use: bool` / presence of the
existing `_computer_use_config`) that `ComputerAgent` sets in `configure()`;
`_is_computer_use_model()` becomes `_computer_use_enabled(model)`, which returns true when
the opt-in is set *or* the model is a legacy computer-use id. `ComputerAgent`'s default
moves to `gemini-3.8-flash`.

Transcription: `OpenAIWhisperBackend` is renamed or generalised to an OpenAI transcription
backend. It picks `response_format` per model (`verbose_json` for whisper,
`json` (or whatever the model supports) for `gpt-transcribe`), and maps whichever fields
come back into `TranscriptionResult`, measuring the duration locally when the response
lacks it.

✅ **Pros:**
- One video code path; the registry (verified, contract-tested) decides capabilities.
- Fail-closed validation is already implemented and tested for reels.
- Adding the next video model is one profile entry, as designed in FEAT-564.
- Computer use no longer depends on guessing from model names.

❌ **Cons:**
- `video_generation` loses Developer-API features Omni lacks (image-to-video, reference
  images, interpolation, extension, 1080p/4k, duration choice). These return only once the
  Vertex Veo profiles are enabled (Q5).
- `generate_video_clip` returns `GeneratedReelClip`, not `AIMessage`; the façade must adapt
  the result (and `number_of_videos > 1` must loop or be rejected).
- Touches the FEAT-564 registry contract tests.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `google-genai` | Omni Interactions API, Veo generate_videos | already used by `reel/omni.py`, `reel/veo.py` |
| `aiohttp` | OpenAI transcription multipart POST | already used by the backend |

🔗 **Existing Code to Reuse:**
- `parrot/clients/google/generation.py` — `generate_video_clip()` (registry resolve → adapter)
- `parrot/clients/google/reel/profiles.py` — `VideoProfileRegistry`, `VideoModelProfile`, `validate_scene`
- `parrot/clients/google/reel/omni.py` — `OmniClipAdapter`
- `parrot/clients/google/reel/veo.py` — `VeoClipAdapter`
- `parrot/clients/google/client.py` — `_build_tools("computer_use")`, `_computer_use_config`

---

### Option C: Generic "media capability registry" for all generators

Generalise `VideoProfileRegistry` into a provider-agnostic `MediaModelRegistry` that
covers video, image (Imagen vs Nano Banana), TTS, live and transcription models across
Google, OpenAI and Amazon Nova, with one validate-then-dispatch façade per modality.

✅ **Pros:**
- Future deprecations become data changes in one place for every modality.
- Would also absorb the Imagen → Nano Banana delegation added in the sweep.

❌ **Cons:**
- Large redesign, far beyond the deferred items; touches Nova and OpenAI generation.
- Delays the urgent fixes (`ComputerAgent` is broken now; Developer-API video has no default).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | — | no new deps |

🔗 **Existing Code to Reuse:**
- `parrot/clients/google/reel/profiles.py` — template for the generic registry
- `parrot/clients/amazon/nova/generation.py` — `_default_video_model` pattern

---

## Recommendation

**Option B** is recommended because:

- It matches the decisions already made: route by profile, reject unsupported parameters,
  remove the dead Veo profiles, opt into computer use explicitly, keep segments when available.
- The hard part (registry, validation, Omni adapter) already exists and is tested; this
  feature mostly *connects* `video_generation` to it instead of building a parallel path
  (Option A).
- Option C is a valid long-term direction, but it bundles unrelated modalities and would
  leave `ComputerAgent` broken for longer.

The accepted tradeoff: on the Developer API, `video_generation` loses the Veo-only features
until the Vertex Veo profiles are enabled. Callers who need them get a precise
`ReelValidationError` instead of a silently degraded clip.

---

## Feature Description

### User-Facing Behavior

- **Video.** `client.video_generation(prompt)` / `generate_videos(prompt)` with no model use
  the registry default for the client's surface (`gemini-omni-1.1-flash` on the Developer
  API). An explicit model is resolved against the registry. Passing a Veo-only option
  (`reference_image`, `last_frame`, `reference_images`, `extend_video`, `resolution`,
  `duration`) with Omni raises `ReelValidationError` with a capability error code before
  any provider call. `/mediagen` with `action=video` and no `model` uses the same default.
  Return type stays `AIMessage` (videos as media paths).
- **Computer use.** `ComputerAgent()` works again, defaulting to `gemini-3.8-flash`. Plain
  `GoogleGenAIClient` calls on `gemini-3.8-flash` are unaffected (no computer-use tool).
- **Transcription.** The OpenAI backend defaults to `gpt-transcribe`. `TranscriptionResult`
  keeps `text`/`language`/`duration_seconds`. When the model returns no language or duration,
  they come from the request hint or a local audio measurement, and a debug log notes the
  degradation. `model="whisper-1"` keeps working until its shutdown.
- **OpenAI clean-ups.** After 2026-12-11, `o3`/`o3-pro` are no longer special-cased as
  Responses-only, and the `gpt-5-nano` `max_tokens` exception is removed.

### Internal Behavior

1. `VideoProfileRegistry.default()` drops the three `veo-3.1-*-preview` Developer-API
   profiles; `default_video_model("gemini_developer")` returns `gemini-omni-1.1-flash`.
   Vertex entries are unchanged (disabled).
2. `video_generation` normalises its inputs (including `VideoGenInput` unpacking), resolves
   `model or registry.default_video_model(surface)`, validates every requested option
   against the profile, then delegates each clip to `generate_video_clip()`, wrapping the
   `GeneratedReelClip`(s) into an `AIMessage`. The Veo-specific
   `personGeneration`/resolution/duration logic moves behind `VeoClipAdapter`
   (it already lives there for reels) instead of being duplicated.
3. `generate_videos` keeps its signature, drops its `veo-` prefix check, and relies on
   registry resolution (`UNKNOWN_MODEL` / `WRONG_API_SURFACE` / `MODEL_DISABLED`).
4. The client gains an explicit computer-use switch. `ComputerAgent.configure()` sets it
   alongside the existing `_computer_use_safety_handler`. All four call sites of
   `_is_computer_use_model` (thinking requirement, tool building, function-response parts,
   safety execution) consult the new predicate.
5. The transcription backend chooses its `response_format` from a small per-model table
   and parses either shape.

### Edge Cases & Error Handling

- `number_of_videos > 1`: loop `generate_video_clip` per video, or reject on profiles
  without multi-output. Decided in the spec (open question).
- `VideoGenerationPrompt.resolution` defaults to `"720p"`, which Omni would reject; the
  default must become `None` (or be ignored when the profile has no resolutions).
- `include_audio=False` on Omni (`native_audio="always"`): maps to the existing
  `audio_mode` handling (separate-track stripping), not a provider flag.
- Vertex client with no explicit model: `default_video_model("vertex")` returns a disabled
  profile, so the call fails with `MODEL_DISABLED`. That is correct while the Q5 gate holds.
- Computer-use opt-in set but no `_computer_use_config`: the existing `_build_tools` error
  path (logged, no tool) stays; the spec should decide whether to raise instead.
- Transcription model that rejects `verbose_json`: never send it to that model (table-driven),
  so there is no 400-and-retry loop.

---

## Capabilities

### New Capabilities
- `registry-routed-video-generation`: `video_generation`/`generate_videos` delegate to the FEAT-564 profile registry and adapters.
- `explicit-computer-use-mode`: client-level computer-use opt-in decoupled from model names.
- `openai-transcription-model-formats`: per-model response-format handling for OpenAI transcription.

### Modified Capabilities
- FEAT-564 video-reel profile registry (Developer-API default and profile set change).
- FEAT-227 `ComputerAgent` (default model, opt-in wiring).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/clients/google/generation.py` | modifies | `video_generation`, `generate_videos` become registry façades |
| `parrot/clients/google/reel/profiles.py` | modifies | remove dead dev Veo profiles; Omni default |
| `parrot/clients/google/client.py` | modifies | computer-use predicate + opt-in attribute |
| `parrot_tools/computer/agent.py` | modifies | default `gemini-3.8-flash`; sets opt-in in `configure()` |
| `parrot/handlers/mediagen.py` | modifies | drop hard-coded Veo default |
| `parrot/models/generation.py` | modifies | `VideoGenerationPrompt` example / `resolution` default |
| `parrot/voice/transcriber/openai_backend.py` | modifies | model default + format table |
| `parrot/clients/openai/client.py` | modifies | drop `RESPONSES_ONLY_MODELS` o3*, `gpt-5-nano` max_tokens quirk |
| reel contract tests (FEAT-564) | modifies | registry set/default assertions |

Breaking: `video_generation` on the Developer API now rejects Veo-only options (hard cut,
acceptable). No new dependencies.

---

## Code Context

> References verified on branch `fix/model-deprecations-2026-10` (the deprecation sweep
> this feature follows). Line numbers may shift slightly on `dev` until that branch merges.

### User-Provided Code
None.

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:954
async def video_generation(self, prompt: Union[str, VideoGenInput], output_directory=None,
                           model: Optional[str] = None, aspect_ratio=AspectRatio.RATIO_16_9,
                           negative_prompt=None, number_of_videos: int = 1, reference_image=None,
                           generate_image_first: bool = False, image_prompt=None, duration: int = 8,
                           resolution=None, person_generation: str = "allow_adult",
                           include_audio: bool = True, last_frame=None, reference_images=None,
                           reference_type: str = "asset", extend_video=None, seed=None,
                           user_id=None, session_id=None, **kwargs) -> AIMessage

# generation.py:2005
async def generate_videos(self, prompt: Union[str, VideoGenerationPrompt], reference_image=None,
                          output_directory=None, mime_format: str = "video/mp4",
                          model: Optional[str] = None) -> AIMessage

# generation.py:2050 — FEAT-564 TASK-3330: registry resolve -> VeoClipAdapter | OmniClipAdapter
async def generate_video_clip(self, *, prompt: str, model: str, output_directory: Path,
                              aspect_ratio: str, resolution: str, target_duration_seconds: float,
                              starting_frame: Optional[Path] = None, audio_mode: str = "separate",
                              timeout_seconds: float = 600.0) -> "GeneratedReelClip"

# From packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py
class VideoModelProfile(BaseModel): ...            # line 34
class VideoProfileRegistry:                         # line 89
    @classmethod
    def default(cls) -> "VideoProfileRegistry"      # line 104 — dev: 3 veo-3.1-*-preview + gemini-omni-1.1-flash (enabled); vertex: veo-3.1-*-001 (enabled=False)
    def default_video_model(self, surface: ApiSurface) -> str   # line 183 — {"gemini_developer": "veo-3.1-generate-preview", "vertex": "veo-3.1-generate-001"}
    def resolve(self, model_id: str, surface: ApiSurface) -> VideoModelProfile  # line 206
    def validate_scene(self, profile, *, resolution: str, audio_mode: str, has_starting_frame: bool) -> None  # line 239
ApiSurface = Literal["gemini_developer", "vertex"]  # line 24

# From packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py:75
class OmniClipAdapter:
    def __init__(self, owner: "GoogleGenAIClient", downloader: ProviderMediaDownloader, *, max_download_bytes=...)  # line 86
    async def generate(self, *, profile, prompt, output_directory, aspect_ratio, resolution,
                       target_duration_seconds, starting_frame, deadline) -> GeneratedReelClip   # line 97

# From packages/ai-parrot-client-google/src/parrot/clients/google/reel/veo.py:62
class VeoClipAdapter: ...

# From packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):   # line 103
    @staticmethod
    def _requires_thinking(model: str) -> bool        # line 271 — includes _is_computer_use_model
    @staticmethod
    def _is_computer_use_model(model: str) -> bool    # line 374 — startswith("gemini-2.5-computer-use") or startswith("gemini-3-flash-preview")
# _is_computer_use_model call sites: lines 284, 2113, 2213, 3304, 3414
# _build_tools("computer_use") reads getattr(self, "_computer_use_config", None) at line 1281

# From packages/ai-parrot-tools/src/parrot_tools/computer/agent.py
class ComputerAgent(Agent):                         # line 25
    def __init__(self, *, model: str = "gemini-2.5-computer-use-preview-10-2025", ...)  # line 72-75
    async def configure(self, app: Any = None) -> None   # line 131 — sets client._computer_use_safety_handler (line 142)

# From packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py
class OpenAIWhisperBackend(AbstractTranscriberBackend):   # line 23
    API_URL = "https://api.openai.com/v1/audio/transcriptions"
    def __init__(self, api_key: str, model: str = "whisper-1", max_retries: int = 3, timeout_seconds: int = 60)  # line 52
    async def transcribe(self, audio_path, language: Optional[str] = None, ...)   # line 101
# line 208: data.add_field("response_format", "verbose_json")
# lines 238-243: TranscriptionResult(text=..., language=result_json.get("language", "en"),
#                duration_seconds=result_json.get("duration", 0.0), confidence=None, processing_time_ms=...)

# From packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py
RESPONSES_ONLY_MODELS = {"o3", "o3-pro"}   # line 54
# line 867: if model_str != "gpt-5-nano": args["max_tokens"] = ...

# From packages/ai-parrot-server/src/parrot/handlers/mediagen.py
# default_model = "gemini-nano-banana-2.1" if action == "image" else "veo-3.1-generate-preview"

# From packages/ai-parrot/src/parrot/models/generation.py
class VideoGenerationPrompt(BaseModel):  # model: str = Field(...), resolution default "720p", example model "veo-3.1-generate-preview"
```

#### Verified Imports
```python
from parrot.clients.google import GoogleGenAIClient
from parrot.clients.google.reel.profiles import VideoProfileRegistry, VideoModelProfile
from parrot.clients.google.reel.errors import ReelErrorCode, ReelValidationError
from parrot.voice.transcriber import OpenAIWhisperBackend
# reel/__init__.py has NO eager exports — import submodules explicitly.
```

#### Key Attributes & Constants
- `GoogleModel.GEMINI_OMNI_1_1_FLASH` → `"gemini-omni-1.1-flash"` (clients/google/models.py, added in the sweep)
- `GoogleModel.GEMINI_3_8_FLASH` → `"gemini-3.8-flash"`
- `OpenAIWhisperBackend` is re-exported by `parrot/integrations/msteams/voice/__init__.py` and used by `voice/transcriber/transcriber.py:98`

### Does NOT Exist (Anti-Hallucination)
- ~~`GoogleModel.VEO_3_1` / `VEO_3_1_FAST` / `VEO_3_1_LITE` / `IMAGEN_4`~~ — removed in the sweep
- ~~`GoogleGenAIClient.computer_use` attribute / `_computer_use_enabled`~~ — not yet; only `_computer_use_config` and `_computer_use_safety_handler` exist
- ~~`VideoProfileRegistry.validate_request`~~ — only `validate_scene` exists
- ~~an OpenAI `gpt-transcribe` backend class~~ — only `OpenAIWhisperBackend`
- ~~eager exports in `parrot.clients.google.reel`~~ — the package `__init__` exports nothing

---

## Parallelism Assessment

- **Internal parallelism**: three independent tracks with disjoint files: (1) video —
  generation.py, reel/profiles.py, mediagen.py, models/generation.py; (2) computer use —
  google/client.py, computer/agent.py; (3) transcription + OpenAI clean-ups —
  openai_backend.py, openai/client.py.
- **Cross-feature independence**: depends on `fix/model-deprecations-2026-10` merging
  first (same files). FEAT-564 (reel) owns the registry contract tests. Check for in-flight
  edits to `google/client.py` (FEAT-688-style gate work) before starting track 2.
- **Recommended isolation**: `mixed`
- **Rationale**: the tracks touch disjoint files and can run in sub-worktrees in parallel.
  Within the video track, tasks are sequential (registry → façade → handler/model).

---

## Open Questions

- [ ] Does `gemini-omni-1.1-flash` support more than one output per request, or must `number_of_videos > 1` loop / be rejected? — *Owner: Jesus*
- [ ] Which `response_format` values and response fields (language, duration, segments) does `gpt-transcribe` return? Needs a live probe before the spec freezes the format table. — *Owner: Jesus*
- [ ] Does `gemini-3.8-flash` honour `types.ComputerUse` with the same predefined function set (`click_at`, `type_text_at`, …) as the 2.5 preview? Needs a live probe. — *Owner: Jesus*
- [ ] If computer-use opt-in is set but `_computer_use_config` is missing, should the client raise instead of logging? — *Owner: Jesus*
- [x] Vertex Veo GA profiles — *Owner: Jesus*: leave the §8 Q5 gate closed; out of scope.
- [x] Dead Developer-API Veo profiles — *Owner: Jesus*: remove them; Omni becomes the `gemini_developer` default.
- [x] Unsupported options on Omni — *Owner: Jesus*: reject via validation before any paid call.
- [x] Include OpenAI `o3`/`gpt-5-nano` clean-ups — *Owner: Jesus*: yes.
