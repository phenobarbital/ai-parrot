---
type: feature
base_branch: dev
projects: [ai-parrot-client-google, ai-parrot-client-openai, ai-parrot-tools, ai-parrot-integrations, ai-parrot-server, ai-parrot]
tags: [model-deprecations, video-generation, computer-use, transcription, gemini, openai]
---

# Feature Specification: Model Deprecation Follow-ups (Veo → Omni, Computer Use 3.8, gpt-transcribe)

**Feature ID**: FEAT-719
**Date**: 2026-10-22
**Author**: Jesus (with Claude)
**Status**: approved
**Target version**: next minor

Source: `sdd/proposals/model-deprecation-followups.brainstorm.md` (Recommended Option B).

---

## 1. Motivation & Business Requirements

### Problem Statement

The 2026-10-22 deprecation sweep (branch `fix/model-deprecations-2026-10`) removed every
model with an announced shutdown from `OpenAIModel` / `GoogleModel` and moved defaults to
the providers' recommended replacements. Three migrations could not be done as a model-id
swap, because the replacement uses a different API or semantics:

1. **Video generation.** Veo 3.1 preview models shut down on the Gemini Developer API on
   2026-10-22. The replacement, `gemini-omni-1.1-flash`, uses the Omni Interactions API.
   After the sweep, `GoogleGeneration.video_generation()` / `generate_videos()` have **no
   default model** and raise without one; `/mediagen`, the `VideoGenerationPrompt` example
   and the reel registry's `gemini_developer` default still point at dead
   `veo-3.1-*-preview` ids.
2. **Computer use.** `gemini-2.5-computer-use-preview-10-2025` shut down on 2026-07-28
   (replacement `gemini-3.8-flash`). `ComputerAgent` still defaults to the dead id. The client
   detects computer-use mode **by model-name prefix**, and — per a live probe —
   `gemini-3.8-flash` emits a **different action vocabulary** that the current translation
   table does not know.
3. **OpenAI transcription.** `whisper-1` shuts down 2027-02-26 (replacement
   `gpt-transcribe`). `OpenAIWhisperBackend` requests `response_format=verbose_json`, which
   `gpt-transcribe` rejects (live probe).

Plus two OpenAI clean-ups that become dead code after the 2026-12-11 snapshot shutdowns.

### Goals
- G1. `video_generation()` / `generate_videos()` work again on the Gemini Developer API with no
  explicit model, routed through the FEAT-564 `VideoProfileRegistry` (default
  `gemini-omni-1.1-flash`).
- G2. Options a resolved video profile cannot honour fail closed with `ReelValidationError`
  **before any paid call**.
- G3. `number_of_videos > 1` on Omni is sent as **one** provider request (Omni returns
  several videos per request).
- G4. `ComputerAgent` works on `gemini-3.8-flash` via an **explicit client opt-in** and a
  per-model action vocabulary; plain `gemini-3.8-flash` calls are unaffected.
- G5. The OpenAI transcription backend defaults to `gpt-transcribe` using `json`, keeps the
  `TranscriptionResult` shape, and normalises `language` to ISO 639-1 for every model.
- G6. Remove the `o3`/`o3-pro` Responses-only special case and the `gpt-5-nano` `max_tokens`
  exception once those snapshots are shut off.

### Non-Goals (explicitly out of scope)
- Enabling the Vertex Veo GA profiles (FEAT-564 spec §8 Q5 gate stays closed).
- A provider-agnostic media-model registry across modalities. Rejected in the brainstorm (see
  `proposals/model-deprecation-followups.brainstorm.md`, Option C).
- Point-fixing with inline `if model.startswith("gemini-omni")` branches (rejected, Option A).
- Live/realtime transcription (`gpt-live-transcribe`).
- Changing the Imagen → Nano Banana delegation added in the sweep.

---

## 2. Architectural Design

### Overview

**Video (registry-routed).** `video_generation()` and `generate_videos()` become thin façades
over the FEAT-564 registry and adapters. The model is `model or
registry.default_video_model(surface)`; the registry resolves it to a `VideoModelProfile`,
a new `validate_request()` checks **every** option `video_generation` exposes, and the
request is dispatched to `VeoClipAdapter` / `OmniClipAdapter`. The Veo-specific knobs
(`personGeneration`, resolution, duration, last frame, reference images, extension) live
behind `VeoClipAdapter`, not in `video_generation`. Results are wrapped into the existing
`AIMessage` return.

- The three `veo-3.1-*-preview` Developer-API profiles are **removed**;
  `default_video_model("gemini_developer")` returns `gemini-omni-1.1-flash`.
- Vertex profiles are unchanged and stay `enabled=False`, so a Vertex client with no model
  raises `MODEL_DISABLED`. That is intended.
- `VideoModelProfile` gains `max_outputs_per_request`, which the Omni profile sets above 1.
  `number_of_videos > max_outputs_per_request` is rejected (`UNSUPPORTED_OPTION`).
- On Omni, `reference_image`, `last_frame`, `reference_images`, `extend_video`, `resolution`
  and an explicit `duration` are rejected with `UNSUPPORTED_OPTION` before any provider call.
- `include_audio=False` on Omni (`native_audio="always"`) maps to the existing `audio_mode`
  stripping path, not a provider flag.

**Computer use (explicit opt-in + vocabulary).** `GoogleGenAIClient` gains an explicit
`computer_use` switch. A new `_computer_use_enabled(model)` replaces
`_is_computer_use_model(model)` at its five call sites: true when the switch is on, *or* the
model is a legacy computer-use id (compatibility signal only). The predefined-action
translation becomes **per vocabulary**:
- *legacy* (2.5 preview / 3-flash-preview): today's `_COMPUTER_USE_PREDEFINED_MAP`.
- *v3_8*: `click`, `move`, `type`, `scroll`, `hotkey`, `wait`, `navigate`, `go_back`,
  `drag_and_drop`, translated (including argument renames) onto `ComputerInteractionToolkit`.

Every v3_8 call carries an `intent` string. The adapter strips it from the toolkit arguments
and forwards it to the log and the safety prompt. An action outside the active vocabulary is
answered to the model as an error function-response, never silently skipped. With the opt-in
set but no `_computer_use_config`, the client **raises** a configuration error (it currently
logs and continues). `ComputerAgent` defaults to `gemini-3.8-flash` and sets the opt-in in
`configure()`.

**Transcription.** `OpenAIWhisperBackend` defaults to `gpt-transcribe` and picks
`response_format` from a per-model table: `verbose_json` for `whisper-1`, `json` for
`gpt-transcribe`. It parses both response shapes into `TranscriptionResult`:
- `language` ← `languages[0].code`, or whisper's `language` name normalised to ISO 639-1,
  falling back to the request hint, then `"en"`.
- `duration_seconds` ← `duration` (whisper) or `usage.seconds` (gpt-transcribe).

**OpenAI clean-ups.** Remove `"o3"`/`"o3-pro"` from `RESPONSES_ONLY_MODELS` and the
`gpt-5-nano` `max_tokens` exception. These must not merge before 2026-12-11; see §7.

### Component Diagram
```
video_generation / generate_videos ──→ VideoProfileRegistry.resolve + validate_request
                                            │
                                            ├──→ VeoClipAdapter   (vertex, when enabled)
                                            └──→ OmniClipAdapter  (gemini_developer default; N outputs/request)
                                                       └──→ AIMessage (media paths)

ComputerAgent.configure ──→ client.computer_use = True
GoogleGenAIClient._computer_use_enabled ──→ _build_tools("computer_use") (raises if no config)
model functionCall ──→ vocabulary table (legacy | v3_8) ──→ ComputerInteractionToolkit.<method>

OpenAIWhisperBackend ──→ format table (whisper-1: verbose_json | gpt-transcribe: json) ──→ TranscriptionResult
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `VideoProfileRegistry` (reel/profiles.py) | modifies | drop dev Veo profiles, Omni default, `validate_request`, `max_outputs_per_request` |
| `OmniClipAdapter` (reel/omni.py) | modifies | multi-output generation |
| `GoogleGeneration.video_generation` / `generate_videos` | modifies | registry façade |
| `GoogleGeneration.generate_video_clip` | uses | single-clip path stays for reels |
| `GoogleGenAIClient` computer-use paths | modifies | opt-in predicate, vocabulary tables, raise on missing config |
| `ComputerInteractionToolkit` | extends | new `type_text` (focused element, no coordinates) |
| `ComputerAgent` | modifies | default `gemini-3.8-flash`, sets opt-in |
| `OpenAIWhisperBackend` | modifies | format table, parsing, default model |
| `/mediagen` handler, `VideoGenerationPrompt` | modifies | no hard-coded Veo default |
| `OpenAIClient` | modifies | clean-ups |

### Data Models
```python
# reel/profiles.py — field added to the existing model
class VideoModelProfile(BaseModel):
    ...
    max_outputs_per_request: int = Field(1, ge=1)  # Omni > 1 (multi-output per request)

# client.py — computer-use vocabulary key
ComputerUseVocabulary = Literal["legacy", "v3_8"]
```

### New Public Interfaces
```python
class GoogleGenAIClient:
    computer_use: bool  # explicit opt-in (default False)

class VideoProfileRegistry:
    def validate_request(self, profile: VideoModelProfile, *, request: "VideoRequestOptions") -> None: ...

class ComputerInteractionToolkit:
    async def type_text(self, text: str, press_enter: bool = False) -> dict: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: registry update | yes | field name, removals, default id, `validate_request` raises `UNSUPPORTED_OPTION` | — |
| M2: Omni multi-output | no | — | Interactions API multi-output request shape must be read from the SDK (`google-genai`) |
| M3: video façade | no | — | mapping of `VideoGenInput` fields onto the registry and adapters needs judgement |
| M4: mediagen + prompt model | yes | drop default; `resolution` default `None` | — |
| M5: computer-use opt-in + vocabularies | no | — | v3_8 vocabulary not fully enumerated (§8 Q1) |
| M6: toolkit `type_text` + ComputerAgent | yes | signature fixed below; default `gemini-3.8-flash` | — |
| M7: transcription formats | yes | format table + field mapping fixed by the live probe (§6) | — |
| M8: OpenAI clean-ups | yes | delete two literals; gated by date | — |

### Module 1: Video registry update
- **Path**: `packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py`
- **Responsibility**: Remove the three `veo-3.1-*-preview` `gemini_developer` profiles. Make
  `default_video_model("gemini_developer")` return `gemini-omni-1.1-flash`. Add
  `max_outputs_per_request` (Omni > 1). Add `validate_request()`, covering every option
  `video_generation` exposes.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # modifies reel/profiles.py:34
  class VideoModelProfile(BaseModel):  # verified: reel/profiles.py:34
      max_outputs_per_request: int = Field(1, ge=1)
      """Maximum videos one provider request may return (Omni > 1)."""

  class VideoRequestOptions(BaseModel):
      """Normalised single-request video options validated against a profile."""
      resolution: Optional[str] = None
      duration_seconds: Optional[int] = None
      number_of_videos: int = 1
      has_starting_frame: bool = False
      has_last_frame: bool = False
      reference_image_count: int = 0
      extends_video: bool = False
      audio_mode: str = "separate"

  class VideoProfileRegistry:  # verified: reel/profiles.py:89
      def validate_request(self, profile: VideoModelProfile, *, request: VideoRequestOptions) -> None:
          """Raise ReelValidationError(UNSUPPORTED_OPTION) for any option the profile cannot honour;
          never drops an option silently. Delegates resolution/starting-frame/audio checks to validate_scene."""
  ```

### Module 2: Omni multi-output
- **Path**: `packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py`
- **Responsibility**: let one Omni request return `n` videos, and materialise and measure each one.
- **Depends on**: Module 1 (`max_outputs_per_request`)
- **Interface Skeleton**:
  ```python
  class OmniClipAdapter:  # verified: reel/omni.py:75
      async def generate_many(
          self, *, profile: VideoModelProfile, prompt: str, output_directory: Path,
          aspect_ratio: str, number_of_videos: int, deadline: float,
      ) -> list[GeneratedReelClip]:
          """One Interactions request for `number_of_videos` outputs; raises ReelValidationError
          if number_of_videos > profile.max_outputs_per_request."""
  ```

### Module 3: Registry-routed video façade
- **Path**: `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py`
- **Responsibility**: rewrite `video_generation()` / `generate_videos()` as façades: resolve,
  `validate_request`, dispatch (Veo → `VeoClipAdapter` per clip; Omni → `generate_many`), then
  wrap the results into `AIMessage`. Remove the inline Veo-only logic from `video_generation`.
- **Depends on**: Module 1, Module 2
- **Interface Skeleton**:
  ```python
  async def video_generation(self, prompt: Union[str, VideoGenInput], output_directory=None,
                             model: Optional[str] = None, ...) -> AIMessage:  # verified: generation.py:954
      """model None → registry.default_video_model(surface). Unsupported options → ReelValidationError
      before any provider call. Signature unchanged."""
  async def generate_videos(self, prompt, reference_image=None, output_directory=None,
                            mime_format: str = "video/mp4", model: Optional[str] = None) -> AIMessage:
      """verified: generation.py:2005 — drops the 'veo-' prefix check; registry resolution decides."""
  ```

### Module 4: `/mediagen` + `VideoGenerationPrompt`
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/mediagen.py`,
  `packages/ai-parrot/src/parrot/models/generation.py`
- **Responsibility**: the video action stops hard-coding `veo-3.1-generate-preview`; with no
  model it passes `None`, so the façade's registry default applies. In `VideoGenerationPrompt`,
  `model` becomes optional (`None`), the `resolution` default becomes `None`, and the example
  and description use `gemini-omni-1.1-flash`.
- **Depends on**: Module 3 (default resolution behaviour)

### Module 5: Computer-use opt-in + vocabularies
- **Path**: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
- **Responsibility**: `computer_use` attribute; `_computer_use_enabled(model)` at the five call
  sites of `_is_computer_use_model`; vocabulary selection (`legacy` for legacy ids, `v3_8`
  otherwise); v3_8 translation table + argument adapter (strip `intent`, rename args);
  unknown action → error function-response; raise when opt-in is set without
  `_computer_use_config`.
- **Depends on**: Module 6 (`type_text` target for the v3_8 `type` action)
- **Interface Skeleton**:
  ```python
  class GoogleGenAIClient:  # verified: client.py:103
      computer_use: bool = False
      _COMPUTER_USE_V3_8_MAP: Dict[str, str]  # click→computer_click_at, move→computer_hover_at,
                                               # type→computer_type_text, scroll→computer_scroll_at,
                                               # hotkey→computer_key_combination, wait→computer_wait,
                                               # navigate→computer_navigate, go_back→computer_go_back,
                                               # drag_and_drop→computer_drag_and_drop
      def _computer_use_enabled(self, model: str) -> bool:
          """True when self.computer_use is set or model is a legacy computer-use id."""
      def _computer_use_vocabulary(self, model: str) -> Literal["legacy", "v3_8"]: ...
      @staticmethod
      def _adapt_computer_use_args(native_name: str, args: Dict[str, Any],
                                   vocabulary: str = "legacy") -> Dict[str, Any]:
          """verified: client.py:1802 — v3_8: pop 'intent'; scroll magnitude_in_pixels→magnitude;
          drag start_x/start_y/end_x/end_y → x/y/destination_x/destination_y; hotkey keys list→csv."""
  ```

### Module 6: Toolkit `type_text` + ComputerAgent default
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/computer/toolkit.py`,
  `.../computer/backend.py`, `.../computer/agent.py`
- **Responsibility**: add `type_text` (type into the focused element, with no coordinates) to
  the toolkit and backend. `ComputerAgent` defaults to `gemini-3.8-flash` and sets
  `client.computer_use = True` in `configure()`.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  class ComputerInteractionToolkit(AbstractToolkit):  # verified: toolkit.py:24
      async def type_text(self, text: str, press_enter: bool = False) -> dict:
          """Type text into the currently focused element (no click)."""
  class ComputerAgent(Agent):  # verified: agent.py:25
      def __init__(self, *, model: str = "gemini-3.8-flash", ...): ...  # verified: agent.py:75
  ```

### Module 7: OpenAI transcription formats
- **Path**: `packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py`
- **Responsibility**: default `gpt-transcribe`; per-model `response_format` table; parse both
  response shapes; ISO 639-1 language normalisation.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  _RESPONSE_FORMATS: Dict[str, str] = {"whisper-1": "verbose_json"}  # default "json"
  class OpenAIWhisperBackend(AbstractTranscriberBackend):  # verified: openai_backend.py:23
      def __init__(self, api_key: str, model: str = "gpt-transcribe", ...): ...  # verified: :55
      @staticmethod
      def _parse_result(model: str, payload: dict, language_hint: Optional[str]) -> tuple[str, str, float]:
          """Return (text, iso_language, duration_seconds) for either response shape."""
  ```

### Module 8: OpenAI clean-ups (date-gated)
- **Path**: `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py`
- **Responsibility**: remove `"o3"`, `"o3-pro"` from `RESPONSES_ONLY_MODELS` and the
  `if model_str != "gpt-5-nano"` exception.
- **Depends on**: — (merge not before 2026-12-11)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_registry_dev_default_is_omni` | M1 | `default_video_model("gemini_developer") == "gemini-omni-1.1-flash"` |
| `test_registry_dev_veo_preview_unknown` | M1 | `resolve("veo-3.1-generate-preview", "gemini_developer")` → `UNKNOWN_MODEL` |
| `test_validate_request_rejects_omni_only_gaps` | M1 | each of starting frame/last frame/reference images/extension/resolution/duration → `UNSUPPORTED_OPTION` |
| `test_validate_request_number_of_videos_cap` | M1 | `number_of_videos > max_outputs_per_request` → `UNSUPPORTED_OPTION` |
| `test_omni_generate_many_single_request` | M2 | one provider call for N videos; N clips materialised |
| `test_video_generation_default_routes_omni` | M3 | no model → Omni adapter; no Veo call |
| `test_video_generation_rejects_before_paid_call` | M3 | unsupported option raises with zero provider calls |
| `test_vertex_without_model_model_disabled` | M3 | vertex client, no model → `MODEL_DISABLED` |
| `test_mediagen_video_no_hardcoded_veo` | M4 | handler passes `model=None` when absent |
| `test_plain_38_flash_no_computer_use_tool` | M5 | `computer_use=False` + `gemini-3.8-flash` → no ComputerUse tool |
| `test_v38_vocabulary_translation` | M5 | each probed v3_8 action maps to the right toolkit method/args; `intent` stripped |
| `test_unknown_action_error_response` | M5 | unmapped action → error function-response |
| `test_opt_in_without_config_raises` | M5 | `computer_use=True`, no `_computer_use_config` → raises |
| `test_type_text_focused` | M6 | toolkit/backend type without coordinates |
| `test_computer_agent_defaults` | M6 | default model `gemini-3.8-flash`; `configure()` sets `computer_use` |
| `test_gpt_transcribe_json_parsing` | M7 | probe payload → text/`en`/5.0 |
| `test_whisper_verbose_json_language_iso` | M7 | `"english"` → `"en"` |
| `test_response_format_table` | M7 | whisper-1 sends `verbose_json`, gpt-transcribe sends `json` |
| `test_openai_cleanups` | M8 | `"o3"` not in `RESPONSES_ONLY_MODELS`; nano gets `max_tokens` |

### Integration Tests
| Test | Description |
|---|---|
| reel profile + Omni contract tests | updated FEAT-564 contract tests stay green |
| `test_integration.py` (computer) | ComputerAgent loop with a mocked 3.8 function-call sequence |

### Validation Contract

tests:
- packages/ai-parrot-client-google/tests/unit/reel/test_reel_profiles.py
- packages/ai-parrot-client-google/tests/unit/reel/test_reel_omni.py
- packages/ai-parrot-client-google/tests/unit/reel/test_reel_veo.py
- packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py
- packages/ai-parrot/tests/test_google_client.py
- packages/ai-parrot-tools/tests/computer/test_agent.py
- packages/ai-parrot-tools/tests/computer/test_backend.py
- packages/ai-parrot-tools/tests/computer/test_integration.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_openai_whisper_backend.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_voice_transcriber.py
- packages/ai-parrot-server/tests/handlers/test_video_reel_inputs.py
- packages/ai-parrot-client-openai/tests/unit/openai/test_deprecations.py
- packages/ai-parrot-client-google/tests/unit/test_video_generation_facade.py
- packages/ai-parrot-client-google/tests/unit/test_computer_use_vocabulary.py
- packages/ai-parrot-server/tests/handlers/test_mediagen_video_default.py
markers: none

### Test Data / Fixtures
```python
# Live-probe payloads (2026-10-22) reused verbatim as fixtures — see §6.
GPT_TRANSCRIBE_JSON = {"text": "Hello, welcome to the world of generative AI audio.",
                       "languages": [{"code": "en"}], "usage": {"type": "duration", "seconds": 5}}
V38_CLICK = {"name": "click", "args": {"intent": "...", "y": 445, "x": 500}}
```

---

## 5. Acceptance Criteria

- [ ] With no model on the Gemini Developer API, `video_generation` / `generate_videos` / `/mediagen` (video) use `gemini-omni-1.1-flash` via the registry.
- [ ] The three `veo-3.1-*-preview` `gemini_developer` profiles are gone; Vertex profiles unchanged and still `enabled=False`.
- [ ] Every option an Omni profile cannot honour raises `ReelValidationError(UNSUPPORTED_OPTION)` with **zero** provider calls.
- [ ] `number_of_videos > 1` on Omni issues exactly one provider request.
- [ ] Plain `gemini-3.8-flash` calls never receive the ComputerUse tool; `ComputerAgent` on `gemini-3.8-flash` does.
- [ ] Every v3_8 action observed in the live probe (§6) is translated; `intent` never reaches the toolkit.
- [ ] `computer_use=True` without `_computer_use_config` raises instead of logging.
- [ ] `OpenAIWhisperBackend` defaults to `gpt-transcribe`, never sends `verbose_json` to it, and returns ISO 639-1 `language` for both models.
- [ ] `TranscriptionResult` fields are unchanged.
- [ ] M8 is not merged before 2026-12-11.
- [ ] Validation Contract tests pass; `ruff check` introduces no new findings.
- [ ] No new third-party dependencies.

---

## 6. Codebase Contract

> Verified against: `origin/dev` 63442566b **plus** the uncommitted sweep in
> `.claude/worktrees/fix-model-deprecations-2026-10` (branch `fix/model-deprecations-2026-10`).
> This feature MUST start after that branch merges; `/sdd-task` re-runs every `grep -c`.

### Verified Imports
```python
from parrot.clients.google import GoogleGenAIClient
from parrot.clients.google.reel.profiles import VideoProfileRegistry, VideoModelProfile   # reel/profiles.py:34,89
from parrot.clients.google.reel.errors import ReelErrorCode, ReelValidationError          # reel/errors.py:32
from parrot.clients.google.reel.omni import OmniClipAdapter                                # reel/omni.py:75
from parrot.clients.google.reel.veo import VeoClipAdapter                                  # reel/veo.py:62
from parrot.clients.google.reel.clip import GeneratedReelClip                              # reel/clip.py:11
from parrot.voice.transcriber import OpenAIWhisperBackend                                  # voice/transcriber/__init__.py:21
# reel/__init__.py has NO eager exports — import submodules explicitly.
```

### Existing Class Signatures
```python
# generation.py (GoogleGeneration mixin)
async def video_generation(self, prompt: Union[str, VideoGenInput], output_directory=None,
    model: Optional[str] = None, aspect_ratio=AspectRatio.RATIO_16_9, negative_prompt=None,
    number_of_videos: int = 1, reference_image=None, generate_image_first: bool = False,
    image_prompt=None, duration: int = 8, resolution=None, person_generation: str = "allow_adult",
    include_audio: bool = True, last_frame=None, reference_images=None, reference_type: str = "asset",
    extend_video=None, seed=None, user_id=None, session_id=None, **kwargs) -> AIMessage   # line 954
async def generate_videos(self, prompt, reference_image=None, output_directory=None,
    mime_format: str = "video/mp4", model: Optional[str] = None) -> AIMessage           # line 2005
async def generate_video_clip(self, *, prompt: str, model: str, output_directory: Path,
    aspect_ratio: str, resolution: str, target_duration_seconds: float,
    starting_frame: Optional[Path] = None, audio_mode: str = "separate",
    timeout_seconds: float = 600.0) -> "GeneratedReelClip"                               # line 2050
# — dispatch: profile.backend == "veo" → VeoClipAdapter(self) else OmniClipAdapter(self, ProviderMediaDownloader())

# reel/profiles.py
ApiSurface = Literal["gemini_developer", "vertex"]                                      # line 24
class VideoModelProfile(BaseModel)                                                      # line 34
class VideoProfileRegistry:                                                             # line 89
    def default(cls) -> "VideoProfileRegistry"                                          # line 104
    def default_video_model(self, surface: ApiSurface) -> str                           # line 183
    def resolve(self, model_id: str, surface: ApiSurface) -> VideoModelProfile          # line 206
    def validate_scene(self, profile, *, resolution: str, audio_mode: str,
                       has_starting_frame: bool) -> None                                # line 239
# Omni profile: backend="omni", durations_seconds=None, resolutions=[], supports_starting_frame=False,
#               supports_reference_guidance=False, native_audio="always", person_generation_values=[]

# reel/errors.py:32 ReelErrorCode: UNKNOWN_MODEL, WRONG_API_SURFACE, MODEL_DISABLED, UNSUPPORTED_OPTION, …

# reel/omni.py:97
async def generate(self, *, profile, prompt, output_directory, aspect_ratio, resolution,
                   target_duration_seconds, starting_frame, deadline) -> GeneratedReelClip

# client.py
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis)               # line 103
_COMPUTER_USE_PREDEFINED_MAP = {...}                                                    # line 254
def _is_computer_use_model(model: str) -> bool  # staticmethod                          # line 374
# call sites: 284 (_requires_thinking), 2113, 2213, 3304, 3414
config = getattr(self, "_computer_use_config", None)                                   # line 1281
def _adapt_computer_use_args(native_name: str, args: Dict[str, Any]) -> Dict[str, Any] # line 1802

# parrot_tools/computer/toolkit.py
class ComputerInteractionToolkit(AbstractToolkit)                                       # line 24
async def click_at(self, x: int, y: int) -> dict                                        # line 120
async def hover_at(self, x: int, y: int) -> dict                                        # line 136
async def type_text_at(self, x: int, y: int, text: str, press_enter: bool = False,
                       clear_before_typing: bool = True) -> dict                        # line 149
async def scroll_at(self, x: int, y: int, direction: str, magnitude: int = 800) -> dict # line 190
async def wait(self, seconds: int = 5) -> dict                                          # line 216
async def go_back(self) -> dict                                                         # line 228
async def go_forward(self) -> dict                                                      # line 237
async def search(self) -> dict                                                          # line 246
async def navigate(self, url: str) -> dict                                              # line 255
async def key_combination(self, keys: str) -> dict                                      # line 267
async def drag_and_drop(self, x: int, y: int, destination_x: int, destination_y: int) -> dict  # line 283
async def open_browser(self) -> dict                                                    # line 311
# backend.py: click_at:261, hover_at:278, type_text_at:291, scroll_at:337, navigate:414,
#             key_combination(keys: list[str]):430, drag_and_drop(x, y, dest_x, dest_y):446

# parrot_tools/computer/agent.py
class ComputerAgent(Agent)                                                              # line 25
def __init__(self, *, model: str = "gemini-2.5-computer-use-preview-10-2025", ...)     # line 72-75
async def configure(self, app: Any = None) -> None                                      # line 131
client._computer_use_safety_handler = self._safety_handler                              # line 142

# voice/transcriber/openai_backend.py
class OpenAIWhisperBackend(AbstractTranscriberBackend)                                  # line 23
def __init__(self, api_key: str, model: str = "whisper-1", max_retries: int = 3,
             timeout_seconds: int = 60)                                                 # line 52-55
data.add_field("response_format", "verbose_json")                                       # line 208
TranscriptionResult(text=..., language=result_json.get("language", "en"),
                    duration_seconds=result_json.get("duration", 0.0), confidence=None, ...)  # line 238-243
# voice/transcriber/models.py:90 class TranscriptionResult(BaseModel) — text, language, duration_seconds, confidence, processing_time_ms

# openai/client.py
RESPONSES_ONLY_MODELS = {"o3", "o3-pro"}                                                # line 54
if model_str != "gpt-5-nano":                                                           # line 867
```

### Live Probe Evidence (2026-10-22)
```text
# gemini-3.8-flash, REST tools=[{computerUse:{environment:ENVIRONMENT_BROWSER}}]
navigate      {"url", "intent"}
click         {"x", "y", "intent"}
type          {"text", "press_enter", "intent"}           # no coordinates
scroll        {"x", "y", "direction", "magnitude_in_pixels", "intent"}
hotkey        {"keys": ["Control", "c"], "intent"}
move          {"x", "y", "intent"}
go_back       {"intent"}
wait          {"seconds", "intent"}
drag_and_drop {"start_x", "start_y", "end_x", "end_y", "intent"}
# computerUse + functionDeclarations combined: accepted. Plain 3.8-flash call (no tool): normal text.
# gemini-3-flash-preview still emits legacy open_web_browser. gemini-2.5-computer-use-preview → 503.

# OpenAI /v1/audio/transcriptions
gpt-transcribe verbose_json → 400 unsupported_value ("Use 'json' or 'text'"); srt → 400
gpt-transcribe json → {"text", "languages": [{"code": "en"}], "usage": {"type": "duration", "seconds": 5}}
gpt-transcribe: timestamp_granularities[] silently ignored; no segments
whisper-1 verbose_json → {"task", "language": "english", "duration": 4.97, "text", "segments", "usage"}
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `validate_request` | `validate_scene` | delegation | `reel/profiles.py:239` |
| `OmniClipAdapter.generate_many` | `generate()` materialise/measure helpers | reuse | `reel/omni.py:97,199,294` |
| façade | `generate_video_clip` dispatch pattern | same resolve→adapter flow | `generation.py:2050` |
| `_computer_use_enabled` | 5 former `_is_computer_use_model` sites | call | `client.py:284,2113,2213,3304,3414` |
| v3_8 `type` | `ComputerInteractionToolkit.type_text` | new tool | `toolkit.py:149` (sibling) |

### Does NOT Exist (Anti-Hallucination)
- ~~`GoogleModel.VEO_3_1` / `VEO_3_1_FAST` / `VEO_3_1_LITE` / `IMAGEN_4`~~ — removed in the sweep
- ~~`GoogleGenAIClient.computer_use`~~ / ~~`_computer_use_enabled`~~ — introduced by M5
- ~~`VideoProfileRegistry.validate_request`~~ / ~~`VideoRequestOptions`~~ — introduced by M1
- ~~`VideoModelProfile.max_outputs_per_request`~~ — introduced by M1
- ~~`OmniClipAdapter.generate_many`~~ — introduced by M2
- ~~`ComputerInteractionToolkit.type_text`~~ — introduced by M6 (only `type_text_at` exists)
- ~~a `gpt-transcribe`-specific backend class~~ — `OpenAIWhisperBackend` is extended, not forked
- ~~eager exports in `parrot.clients.google.reel`~~

### Edit Sites (Blueprint Anchors)

Verified against: origin/dev `63442566b` + uncommitted `fix/model-deprecations-2026-10` worktree.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py` | MODIFY | `class VideoModelProfile(BaseModel):` | `profiles.py:34` | 1 |
| ″ | MODIFY | `                model_id="veo-3.1-generate-preview",` | `profiles.py:131` | 1 |
| ″ | MODIFY | `            "gemini_developer": "veo-3.1-generate-preview",` | `profiles.py:196` | 1 |
| ″ | MODIFY | `    def validate_scene(` | `profiles.py:239` | 1 |
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py` | MODIFY | `class OmniClipAdapter:` | `omni.py:75` | 1 |
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | MODIFY | `    async def video_generation(` | `generation.py:954` | 1 |
| ″ | MODIFY | `    async def generate_videos(` | `generation.py:2005` | 1 |
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | MODIFY | `    _COMPUTER_USE_PREDEFINED_MAP = {` | `client.py:254` | 1 |
| ″ | MODIFY | `    def _is_computer_use_model(model: str) -> bool:` | `client.py:374` | 1 |
| ″ | MODIFY | `            config = getattr(self, "_computer_use_config", None)` | `client.py:1281` | 1 |
| ″ | MODIFY | `    def _adapt_computer_use_args(native_name: str, args: Dict[str, Any]) -> Dict[str, Any]:` | `client.py:1802` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/computer/toolkit.py` | MODIFY | `    async def type_text_at(` | `toolkit.py:149` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/computer/backend.py` | MODIFY | `    async def type_text_at(` | `backend.py:291` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/computer/agent.py` | MODIFY | `        model: str = "gemini-2.5-computer-use-preview-10-2025",` | `agent.py:75` | 1 |
| ″ | MODIFY | `                client._computer_use_safety_handler = self._safety_handler` | `agent.py:142` | 1 |
| `packages/ai-parrot-integrations/src/parrot/voice/transcriber/openai_backend.py` | MODIFY | `        model: str = "whisper-1",` | `openai_backend.py:55` | 1 |
| ″ | MODIFY | `        data.add_field("response_format", "verbose_json")` | `openai_backend.py:208` | 1 |
| ″ | MODIFY | `                    language=result_json.get("language", "en"),` | `openai_backend.py:239` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/mediagen.py` | MODIFY | `        default_model = "gemini-nano-banana-2.1" if action == "image" else "veo-3.1-generate-preview"` | `mediagen.py:82` | 1 |
| `packages/ai-parrot/src/parrot/models/generation.py` | MODIFY | `        description="The video generation model to use (e.g., 'veo-3.1-generate-preview')."` | `generation.py:148` | 1 |
| ″ | MODIFY | `                "model": "veo-3.1-generate-preview",` | `generation.py:190` | 1 |
| `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py` | MODIFY | `RESPONSES_ONLY_MODELS = {` | `client.py:54` | 1 |
| ″ | MODIFY | `        if model_str != "gpt-5-nano":` | `client.py:867` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- FEAT-564 registry contract: exact `(surface, model_id)` lookup, never substring matching;
  every capability claim carries `source` / `checked_on`.
- Fail closed: validate before any paid provider call; never drop an option silently.
- aiohttp only; `self.logger`; Pydantic v2; async throughout.
- Hard cuts are fine (no external consumers); no deprecation shims.

### Known Risks / Gotchas
- **Feature loss on the Developer API:** `video_generation` loses image-to-video, reference
  images, interpolation, extension, 1080p/4k and duration choice until the Vertex Veo profiles
  are enabled. Callers get a precise `UNSUPPORTED_OPTION` error instead of a degraded clip.
- **Vertex with no model** fails with `MODEL_DISABLED`. This is intended while the Q5 gate holds.
- `VideoGenerationPrompt.resolution` currently defaults to `"720p"`, which Omni rejects, so M4
  must change the default to `None` or every structured request fails.
- **v3_8 vocabulary may be incomplete:** the probe saw 9 actions. Unknown actions must return
  an error function-response (never silent), and §8 Q1 tracks the full enumeration.
- **Argument renames are easy to get wrong:**
  - `scroll.magnitude_in_pixels` → `scroll_at.magnitude`
  - `drag_and_drop.start_x/start_y/end_x/end_y` → toolkit `x/y/destination_x/destination_y`
    (the backend uses `dest_x/dest_y`)
  - `hotkey.keys` is a list, but toolkit `key_combination` expects a comma-separated string
    (the existing fixup)
- `gemini-2.5-computer-use-preview-10-2025` answered 503, not 404. Do not treat it as alive;
  legacy-name detection is a compatibility signal only.
- **whisper's `language` is a name** (`"english"`), not a code, so M7 needs a name→ISO
  mapping. `gpt-transcribe`'s `usage.seconds` is integer billed time, not an exact duration.
- **M8 timing:** `o3`/`o3-pro` still work until 2026-12-11. Merging M8 earlier would route them
  through Chat Completions and break them.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `google-genai` | as pinned | Omni Interactions API (already used by `reel/omni.py`) |
| `aiohttp` | as pinned | transcription multipart POST (already used) |

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-719; the `sdd-coder` engine gives each task its
  own sub-worktree.
- **Module dependency graph**:
  - M2 → M1 (`max_outputs_per_request`, `VideoRequestOptions`)
  - M3 → M1, M2 (`validate_request`, `generate_many`)
  - M4 → M3 (relies on the façade's registry default when `model=None`)
  - M5 → M6 (v3_8 `type` maps to `computer_type_text`)
  - M7, M8 independent.

  Three concurrent lanes: {M1→M2→M3→M4}, {M6→M5}, {M7}, plus M8 (date-gated).
- **Shared files**: none across lanes. Within lanes, M2 and M3 both touch reel helpers only
  through public interfaces. M5 is the only module editing `google/client.py`; M3 is the only
  one editing `generation.py`.
- **Exclusive resources**: none (no lockfile, migration or extension rebuild).
- **Cross-feature dependencies**: `fix/model-deprecations-2026-10` must merge into `dev` first
  (same files; the contract is verified against it). Check FEAT-564 (reel) for in-flight edits
  to `reel/profiles.py` / `reel/omni.py`.

---

## 8. Open Questions

- [ ] Q1. Does the `gemini-3.8-flash` computer-use vocabulary include actions not seen in the probe (`go_forward`, `search`, `open_web_browser`, key-down/up, …)? Enumerate from the SDK/docs or more probes before M5 freezes the table. — *Owner: M5 implementer*
- [ ] Q2. Exact Omni Interactions request field for multi-output and the per-request maximum (value for `max_outputs_per_request`). Read from `google-genai` before M2. — *Owner: M2 implementer*
- [x] Does `gemini-omni-1.1-flash` support more than one output per request? — *Resolved in brainstorm*: yes; forward `number_of_videos` in one request.
- [x] Which `response_format` values / fields does `gpt-transcribe` return? — *Resolved in brainstorm*: live probe 2026-10-22: only `json`/`text`; json = `text`, `languages[].code`, `usage.seconds`; no segments; `timestamp_granularities` ignored.
- [x] Does `gemini-3.8-flash` use the 2.5-preview predefined action set? — *Resolved in brainstorm*: no — new vocabulary `click`/`move`/`type`/`scroll`/`hotkey`/`wait`/`navigate`/`go_back`/`drag_and_drop`, each with an `intent` arg.
- [x] Opt-in set but `_computer_use_config` missing — *Resolved in brainstorm*: raise.
- [x] Vertex Veo GA profiles — *Resolved in brainstorm*: leave the §8 Q5 gate closed; out of scope.
- [x] Dead Developer-API Veo profiles — *Resolved in brainstorm*: remove them; Omni becomes the `gemini_developer` default.
- [x] Unsupported options on Omni — *Resolved in brainstorm*: reject via validation before any paid call.
- [x] Include OpenAI `o3`/`gpt-5-nano` clean-ups — *Resolved in brainstorm*: yes.
- [x] Video model choice — *Resolved in brainstorm*: route by profile (registry-driven).
- [x] Computer-use opt-in mechanism — *Resolved in brainstorm*: explicit flag on the client, set by `ComputerAgent`.
- [x] Transcription priority — *Resolved in brainstorm*: keep segments if possible, else text-only with a log (probe: gpt-transcribe has none; `TranscriptionResult` never carried them).

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (brainstorm status is `exploration`, not `accepted`) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | Jesus (with Claude) | Initial draft from brainstorm + live probes |
