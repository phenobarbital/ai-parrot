---
type: feature
base_branch: dev
id: FEAT-564
status: draft
proposal: sdd/proposals/video-reel-omni-veo-reliability.proposal.md
---

# Feature Specification: Reliable video reels with Gemini Omni and Veo 3.1

**Feature ID**: FEAT-564
**Date**: 2026-09-17
**Author**: Jesus Lara / Claude
**Status**: draft
**Target version**: next
**Research**: `sdd/state/FEAT-564/` (findings F001–F012)

---

## 1. Motivation & Business Requirements

### Problem Statement

`VideoReelHandler` → `GoogleGenAIClient.generate_video_reel` produces unreliable reels.
A code review, then a Gemini review verified in the proposal (§2.4), found these problems:

- **Stage models are hardcoded.** The HTTP `model` field (default `gemini-3.5-flash`) only builds the client. Scene breakdown always uses `gemini-2.5-flash`. Image generation uses its own default. Every scene uses `GoogleModel.VEO_3_1`. Only two enum IDs get Veo 3.1 options [F009].
- **Durations are ignored.** `scene.duration` is never passed to Veo, which gets 8 s by default, and assembly never trims [F009].
- **Veo requests are malformed and safety retries are unsafe.** `person_generation` is upper-cased. After a safety block, the scene is resubmitted as text-to-video with the reference image dropped. Immediate SDK safety errors bypass the `RuntimeError` substring check [F002,F009,F010].
- **Artifacts are corrupt.** Result URLs go into `AIMessage.files: List[Path]`, and WAV music is stored as `bg_music.mp3` [F003].
- **Uploads, validation and cleanup have gaps.** Sparse upload slots collapse, `storage_config` JSON is not decoded, and temporary directories leak on early-exit paths [F001,F003].
- **Lifecycle problems.** The music client is forced onto `v1alpha` and shares the client instance. Scenes have no deadlines, and cancellation does not wait for workers [F004,F011].
- **Tests are broken.** The handler test fixture hits 20 setup errors, and 13 tests pass [F012].

There is also no way to use **Gemini Omni** (`gemini-omni-1.1-flash`, async Interactions API) next to Veo 3.1.

### Goals
- **G1**: Select the director, image and video models independently. Reels get a `video_model` default, and each scene can override it, so one reel can mix Veo and Omni clips.
- **G2**: Validate video models against a capability registry keyed by (API surface, exact model ID). Invalid combinations fail before any paid call.
- **G3**: Honor scene edit durations. Request a legal covering duration, measure the output, trim it, and record requested/submitted/measured/final durations.
- **G4**: Support explicit audio modes (`separate` | `native` | `muted`) and a music policy (`off` | `optional` | `required`, default `optional`).
- **G5**: Normalize errors into stable codes. Safety blocks never trigger a retry. Only safe reads and downloads are retried, within bounds.
- **G6**: Return typed, URL-faithful artifacts, delivered with an ownership check.
- **G7**: Give every SDK client, child task and temporary directory a clear owner, a deadline, and cleanup on every exit path.
- **G8**: Restore meaningful handler coverage. Add media, registry and transport tests, plus an opt-in live smoke suite.

### Non-Goals (explicitly out of scope)
- Automatic cross-model fallback, safety-block resubmission with altered input, conversational or multi-turn Omni editing, and video extension (proposal §3 and the 2026-09-17 decisions).
- Uploading a Veo clip to Omni for editing. Mixed reels combine clips locally.
- Veo 2 in reels. The public `video_generation` Veo 2 behavior stays as it is, and reel admission waits for its own verified profile.
- Vertex GA profiles enabled by default. Registry entries exist but stay disabled until verified (§8 Q5).
- A new queue system, a frontend redesign, changes to `AbstractClient`/`clients/base.py`, changes to the meaning of `AIMessage.files`, and a new music provider.

---

## 2. Architectural Design

### Overview

Keep the current HTTP job surface (POST → 202 + `job_id`, then GET polling) and the shared MoviePy assembly. Add these pieces, all inside the Google satellite except the core request/result models:

1. **Stage routing** (decided 2026-09-17):
   - `director_model` defaults to `gemini-2.5-flash`.
   - `image_model` defaults to `gemini-3.1-flash-image-preview` and is passed to both background and foreground image calls.
   - `video_model` defaults to Veo 3.1 standard for the configured API surface.
   - `scenes[].video_model` (nullable) overrides the reel value. Resolution order: scene override → reel `video_model` → surface default.
   - The **legacy top-level `model` is a deprecated alias for `director_model`**. It never becomes the video model. If `model` and `director_model` differ, the request fails validation (HTTP 400). If they match, it is accepted with a deprecation warning. An explicit invalid, empty or `null` model value is rejected; only `scenes[].video_model = null` means "inherit".
2. **Capability registry** (`parrot.clients.google.reel.profiles`): one `VideoModelProfile` per (API surface, exact model ID). Each profile lists backend, input modes, legal generation durations, resolutions and duration constraints, native-audio control, person-generation values, reference-image semantics, source and check date. Unknown or wrong-surface IDs raise `ReelValidationError`. Lite does not inherit reference guidance or 4k. The registry never uses `"veo-3" in model` style matching.
3. **Backend adapters** behind one entry point (`generate_video_clip`), both returning `GeneratedReelClip`:
   - **Veo** (`reel.veo.VeoClipAdapter`) wraps `aio.models.generate_videos` + `aio.operations.get` + `aio.files.download`. It sends lowercase `person_generation`, submits the covering duration explicitly, and never retries a safety block.
   - **Omni** (`reel.omni.OmniClipAdapter`) calls `sdk.aio.interactions.create(... background=False, store=False, stream=False)` with a deadline. It decodes inline `data` or downloads the URI through a Google-origin-restricted downloader, validates MIME/bytes/readability, and uses the provider's default duration (no invented duration enum).
4. **Timeline** (`reel.timeline`): pure functions.
   - Pick the covering duration. Example: a 5 s target at 720p with a starting frame submits 6 s; a profile that requires 8 s submits 8 s.
   - Validate edit targets: finite, `0 < d ≤ 8`, 5 s default.
   - Compute the final timeline. Cuts: sum of targets. Crossfades: subtract the actual overlaps. Example: four 5 s scenes give 20 s with cuts, or 18.5 s with three 0.5 s crossfades, within one output frame.
   - Measured media shorter than the target by more than one frame fails with `insufficient_duration`. Nothing is looped, stretched or regenerated.
5. **Audio**: `audio_mode` defaults to `separate`.
   - `separate` strips provider audio, then attaches the user's narration and optional music.
   - `native` keeps model sound. It requires a profile that supports native audio and rejects `speech`/narration/music controls.
   - `muted` has no soundtrack and skips TTS and Lyria.
   - `generate_audio` is **never** sent to the Developer API [F010].
   - Narration longer than the scene's edit target fails with `narration_too_long`. Shorter narration is padded with silence, never time-stretched.
6. **Music** (`reel.music.ReelMusicService`): `music_policy` defaults to `optional` (decided 2026-09-17).
   - `off` makes no Lyria connection.
   - `optional` keeps today's best-effort behavior, including the synthesized prompt when `music_prompt` is missing. On failure it returns a structured `MusicStatus` (`unavailable` | `timeout` | `failed`) and a warning.
   - `required` fails the job.
   - Music uses an isolated, owned client with a configurable, tested `api_version` instead of a hardcoded `v1alpha` (§8 Q6). Connect, receive and byte limits are bounded, and cancellation propagates.
   - PCM → WAV uses verified rate, channel and width metadata. Stored with a `.wav` suffix and `audio/wav` MIME, aligned to the final retained timeline.
7. **Errors** (`reel.errors`): `classify_provider_error()` maps `APIError` (including `ClientError`), terminal operation errors, filtered/empty output, download failures and local media failures to `ReelErrorCode`. It uses status/reason fields, not only exception text. `partial_failure_policy` defaults to `fail`. With `skip`, failed scenes are dropped but results keep original indices and per-scene errors and set `partial=True`. If every scene fails, the job always fails.
8. **Result**: `ReelResult` is stored as `AIMessage.metadata["video_reel"] = result.model_dump(mode="json")`. It holds requested and effective models per stage, API surface, SDK version, scenes, durations, music status and warnings. The final `ReelArtifact` goes in `AIMessage.artifacts`. `AIMessage.files` holds only real local paths, or stays empty for cloud-only output.
9. **HTTP**:
   - Multipart supports explicit `image_<index>` parts or ordered slots, keeping sparse slots, with unique on-disk names. `storage_config` is JSON-decoded and must be an object.
   - Uploads are bounded: 20 scenes, 10 MiB per image, 100 MiB total; all server-configurable.
   - The temporary directory is cleaned on every exit path.
   - Polling accepts `?job_id=` or `/{job_id}`. Supplying both with different values returns 400.
   - New artifact route: `GET …/video_reel/{job_id}/artifacts/{artifact_id}`. It resolves the artifact through the job's `ReelResult`, never from a raw path, and checks ownership first.
   - The caller's identity comes from the authenticated session, not the body's `user_id` (§8 Q7).
10. **Deadlines and retries**:
    - Per-scene generation deadline (default 600 s) and job deadline (default 3600 s), both server config.
    - At most 3 bounded retries for transient polling/download failures, within the original deadline.
    - Never resubmit generation after an ambiguous timeout. Record the operation ID instead.
    - Cancelling the job cancels and awaits child tasks and the media worker before cleanup, and before the terminal job state is published.

### Component Diagram
```
VideoReelHandler (server) ──validate──▶ VideoReelRequest (core, M1)
        │ 202 + job_id                        │
        ▼                                     ▼
   JobManager.execute_job ──▶ GoogleGenAIClient.generate_video_reel (M7)
                                   │
       ┌───────────────┬───────────┼─────────────────┬──────────────────┐
       ▼               ▼           ▼                 ▼                  ▼
 director (Gemini)  images   generate_video_clip   ReelMusicService   timeline+assembly
 director_model    image_model     │ (M3/M4)        (M5, Lyria)        (M6, MoviePy in
                                   ▼                                   process worker)
                  VideoProfileRegistry (M2) ──▶ VeoClipAdapter | OmniClipAdapter
                                   │
                                   ▼
                        GeneratedReelClip ──▶ FileManager ──▶ ReelResult/ReelArtifact
                                                                  │
   GET …/video_reel/{job_id}[/artifacts/{artifact_id}] ◀──────────┘ (M8, owner-checked)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `VideoReelRequest` / `VideoReelScene` (core `models/google.py:376,398`) | extends | Additive fields and validators, strings/literals only. Core never imports provider enums [F007]. |
| `GoogleGeneration.generate_video_reel` (`generation.py:1905`) | modifies | Signature kept. Body becomes stage routing, policies and deadlines, and returns `ReelResult` metadata. |
| `GoogleGeneration._process_scene` (`generation.py:2084`) | modifies | Internal tuple replaced by `GeneratedReelClip` / `ReelSceneResult`. Safety retry removed. |
| `GoogleGeneration.video_generation` (`generation.py:844`) | preserves | Public Veo method stays compatible. The lowercase `person_generation` fix is shared with the adapter. |
| `GoogleGeneration.generate_image` (`generation.py:1524`) | uses | `model=` passed explicitly from `image_model`. |
| `GoogleGeneration.generate_music_stream` (`generation.py:1162`) | modifies | Accepts an injected client/`api_version` instead of the hardcoded `v1alpha` at `:1196`. |
| `GoogleGenAIClient.get_client` / `close` (`client.py:630,693`) | uses | Adapters get owned, per-model clients. `base.py` is not modified. |
| `AbstractClient._save_audio_file` (`clients/base.py:2697`) | not used for music | Speech keeps using it; music gets its own PCM→WAV writer so speech assumptions do not leak. |
| `AIMessageFactory.from_video` (`responses.py:1077`) | uses | Called with `files` = local paths only, plus `metadata`/`artifacts`. |
| `JobManager.execute_job` / `get_job_async` (`jobs/job.py:209,288`) | uses | Unchanged. Result serialized with `model_dump(mode="json")`. |
| `FileManagerInterface` / `FileManagerFactory` | uses | Storage keys stay in `ReelArtifact`; signed URLs are refreshed on poll. |

### Data Models
```python
# core: packages/ai-parrot/src/parrot/models/google.py  (additive)
AudioMode = Literal["separate", "native", "muted"]
MusicPolicy = Literal["off", "optional", "required"]
PartialFailurePolicy = Literal["fail", "skip"]
VideoResolution = Literal["720p", "1080p", "4k"]

class VideoReelScene(BaseModel):          # existing, line 376
    video_model: Optional[str] = None     # NEW — None ⇒ inherit reel video_model
    duration: float = 5.0                 # existing field; NEW validator: finite, 0 < d <= 8

class VideoReelRequest(BaseModel):        # existing, line 398
    director_model: Optional[str] = None  # NEW — resolved default "gemini-2.5-flash"
    model: Optional[str] = None           # NEW (was a handler control key) — deprecated alias of director_model
    image_model: str = "gemini-3.1-flash-image-preview"
    video_model: Optional[str] = None     # NEW — None ⇒ API-surface Veo 3.1 standard default
    resolution: VideoResolution = "720p"
    audio_mode: AudioMode = "separate"
    music_policy: MusicPolicy = "optional"
    partial_failure_policy: PartialFailurePolicy = "fail"
    transition_type: Literal["cut", "crossfade"] = "crossfade"   # tightened from str
    output_format: Literal["mp4", "webm"] = "mp4"                # tightened from str

class ReelArtifact(BaseModel):
    artifact_id: str
    storage_backend: Literal["fs", "temp", "s3", "gcs"]
    storage_key: str
    mime_type: str
    size_bytes: int
    download_url: Optional[str] = None        # str, never Path — query strings preserved exactly
    expires_at: Optional[datetime] = None

class ReelSceneResult(BaseModel):
    index: int                                # original scene index (preserved under skip)
    video_model: str
    backend: Literal["veo", "omni"]
    status: Literal["succeeded", "failed", "skipped"]
    requested_duration_seconds: float
    submitted_duration_seconds: Optional[float] = None
    measured_duration_seconds: Optional[float] = None
    final_duration_seconds: Optional[float] = None
    provider_operation_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None       # redacted; no keys, no base64

class ReelResult(BaseModel):
    final_artifact: Optional[ReelArtifact]
    requested_models: Dict[str, Optional[str]]   # director/image/video
    effective_models: Dict[str, Optional[str]]   # director=None + director_unused=True when scenes supplied
    director_unused: bool
    api_surface: str
    sdk_version: str
    audio_mode: AudioMode
    music_status: Literal["off", "succeeded", "unavailable", "timeout", "failed", "skipped"]
    scenes: List[ReelSceneResult]
    partial: bool
    warnings: List[str]
    final_duration_seconds: Optional[float]
```

### New Public Interfaces
```python
# provider: GoogleGeneration (generation.py)
async def generate_video_clip(
    self, *, prompt: str, model: str, output_directory: Path, aspect_ratio: str,
    resolution: str, target_duration_seconds: float, starting_frame: Optional[Path] = None,
    audio_mode: AudioMode = "separate", timeout_seconds: float = 600.0,
) -> GeneratedReelClip: ...
```
HTTP: `GET /api/v1/google/generation/video_reel/{job_id}/artifacts/{artifact_id}` (NEW). The POST JSON schema gains the §2 Data Models fields.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Core reel contracts | yes | Field names, defaults, alias/conflict rules, validators, result models (§2 Data Models) | — |
| M2: Profile registry & errors | yes | `VideoModelProfile` fields, surface keys, `select_generation_duration`, `ReelErrorCode` values | — |
| M3: Veo adapter | yes | Lowercase person_generation, explicit duration, no safety retry, error mapping | — |
| M4: Omni adapter | no | — | Omni URI download authentication and actual output duration/MIME are unverified (§8 Q3) |
| M5: Music service | no | — | Lyria `api_version` and PCM stream metadata must be verified (§8 Q6) |
| M6: Timeline & assembly | yes | Pure timeline math, one-frame tolerance, MoviePy 2.2.1 subclip/crossfade in a process worker | — |
| M7: Reel orchestration | yes (after M1–M6) | Stage routing precedence, policies, deadlines, cancellation order (§2 items 1, 5–10) | — |
| M8: HTTP handler & delivery | no | — | Deployed owner/tenant helper and artifact-serving convention not located (§8 Q7) |
| M9: Tests, dependency floor, docs | yes (after M7, M8) | Fixture repair via real `BaseView` construction; SDK floor `>=2.23.0`; opt-in smoke marker | — |

### Module 1: Core reel contracts
- **Path**: `packages/ai-parrot/src/parrot/models/google.py` (modifies `:376–453`)
- **Responsibility**: Additive request fields; validators for the legacy alias, empty or explicit-null models, and duration bounds; `ReelArtifact`, `ReelSceneResult`, `ReelResult`. No provider imports.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/models/google.py
  class VideoReelScene(BaseModel):  # verified: models/google.py:376
      video_model: Optional[str] = Field(None, description="Scene video model override; None inherits.")
      @field_validator("duration")
      @classmethod
      def _validate_duration(cls, v: float) -> float:
          """Reject non-finite, <= 0 or > 8 second edit targets."""
      @field_validator("video_model")
      @classmethod
      def _reject_blank_model(cls, v: Optional[str]) -> Optional[str]:
          """None allowed (inherit); empty/whitespace raises."""

  class VideoReelRequest(BaseModel):  # verified: models/google.py:398
      @model_validator(mode="before")
      @classmethod
      def _resolve_legacy_model_alias(cls, data: Any) -> Any:
          """model → director_model. Differing values raise ValueError; identical values record a deprecation
          warning in ``_warnings``; explicit null/empty for model/director_model/image_model/video_model raises."""
      def effective_director_model(self) -> str:
          """director_model or 'gemini-2.5-flash'."""
      def deprecation_warnings(self) -> List[str]:
          """Warnings collected during validation (legacy alias use)."""
      @model_validator(mode="after")
      def _validate_audio_controls(self) -> "VideoReelRequest":
          """native/muted reject speech, music_prompt/genre/mood and music_policy='required'."""

  class ReelArtifact(BaseModel): ...      # §2 Data Models
  class ReelSceneResult(BaseModel): ...
  class ReelResult(BaseModel): ...
  ```

### Module 2: Profile registry & error taxonomy
- **Path**: NEW `packages/ai-parrot-client-google/src/parrot/clients/google/reel/__init__.py`, `reel/profiles.py`, `reel/errors.py`, `reel/clip.py`
- **Responsibility**: Exact (surface, model) profiles, validation that fails before any spend, covering-duration selection, `GeneratedReelClip`, error codes and provider-error classification.
- **Depends on**: M1 (literal types)
- **Interface Skeleton**:
  ```python
  # reel/profiles.py (new)
  ApiSurface = Literal["gemini_developer", "vertex"]
  class VideoModelProfile(BaseModel):
      """Verified capability record for one model on one API surface."""
      model_id: str
      surface: ApiSurface
      backend: Literal["veo", "omni"]
      enabled: bool
      durations_seconds: Optional[List[int]]          # None ⇒ provider default (Omni)
      resolutions: List[str]
      resolution_min_duration: Dict[str, int]         # e.g. {"1080p": 8, "4k": 8}
      supports_starting_frame: bool
      supports_reference_guidance: bool               # provider reference_images (asset guidance)
      native_audio: Literal["always", "controllable", "none"]
      person_generation_values: List[str]             # lowercase
      source: str
      checked_on: date

  class VideoProfileRegistry:
      """Central registry; adding a GA ID is one entry + contract test."""
      def __init__(self, profiles: Iterable[VideoModelProfile]) -> None: ...
      @classmethod
      def default(cls) -> "VideoProfileRegistry":
          """Developer API: veo-3.1-generate-preview, veo-3.1-fast-generate-preview, veo-3.1-lite-generate-preview,
          gemini-omni-1.1-flash (enabled). Vertex: veo-3.1-generate-001, veo-3.1-fast-generate-001 (enabled=False)."""
      def default_video_model(self, surface: ApiSurface) -> str: ...
      def resolve(self, model_id: str, surface: ApiSurface) -> VideoModelProfile:
          """Raises ReelValidationError(code='unknown_model'|'wrong_api_surface'|'model_disabled')."""
      def validate_scene(self, profile: VideoModelProfile, *, resolution: str, audio_mode: str,
                         has_starting_frame: bool) -> None:
          """Raises ReelValidationError(code='unsupported_option') — never silently drops an option."""

  def select_generation_duration(profile: VideoModelProfile, target_seconds: float, resolution: str,
                                 has_starting_frame: bool) -> Optional[int]:
      """Smallest legal duration ≥ target after profile constraints; None for provider-default backends."""

  # reel/errors.py (new)
  class ReelErrorCode(str, Enum):
      SAFETY_BLOCKED = "safety_blocked"; AUTH_OR_ACCESS = "auth_or_access"
      INVALID_CONFIGURATION = "invalid_configuration"; QUOTA_OR_RATE_LIMIT = "quota_or_rate_limit"
      TIMEOUT = "timeout"; INSUFFICIENT_DURATION = "insufficient_duration"
      NARRATION_TOO_LONG = "narration_too_long"; DOWNLOAD_FAILED = "download_failed"
      MEDIA_INVALID = "media_invalid"; PROVIDER_FAILURE = "provider_failure"; UNKNOWN_MODEL = "unknown_model"
  class ReelError(Exception):
      """code: ReelErrorCode; stage: str; scene_index: Optional[int]; retryable: bool; operation_id: Optional[str]."""
  class ReelValidationError(ReelError): """Raised before any paid provider call."""
  def classify_provider_error(exc: BaseException, *, stage: str, scene_index: Optional[int]) -> ReelError:
      """Maps google.genai.errors.APIError (incl. ClientError) by status/reason; safety/auth/validation → retryable=False."""

  # reel/clip.py (new)
  class GeneratedReelClip(BaseModel):
      local_path: Path; model: str; backend: Literal["veo", "omni"]; submitted_duration_seconds: Optional[float]
      measured_duration_seconds: float; has_audio: bool; provider_operation_id: Optional[str]
  ```

### Module 3: Veo clip adapter
- **Path**: NEW `reel/veo.py`; modifies `generation.py:965` (`person_generation.upper()` → lowercase) for the public method.
- **Responsibility**: Veo submit, bounded poll and download for one scene. Explicit covering duration, `generate_audio` not serialized on the Developer API, safety block terminal, operation ID recorded.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # reel/veo.py (new)
  class VeoClipAdapter:
      """Generates one Veo clip for a reel scene."""
      def __init__(self, owner: "GoogleGenAIClient", *, poll_interval_seconds: float = 10.0,
                   max_read_retries: int = 3) -> None: ...   # owner.get_client verified: client.py:630
      async def generate(self, *, profile: VideoModelProfile, prompt: str, output_directory: Path,
                         aspect_ratio: str, resolution: str, target_duration_seconds: float,
                         starting_frame: Optional[Path], deadline: float) -> GeneratedReelClip:
          """Raises ReelError; never resubmits after safety block or ambiguous timeout."""
  ```

### Module 4: Omni clip adapter
- **Path**: NEW `reel/omni.py`, `reel/download.py`
- **Responsibility**: Async Interactions generation, decoding inline data or downloading a URI, and media validation. No Veo config, temperature or negative_prompt. Does not reuse the synchronous deep-research loop (`client.py:5162`).
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # reel/omni.py (new)
  class OmniClipAdapter:
      """Generates one clip through sdk.aio.interactions.create (google-genai 2.23.0 exposes aio.interactions)."""
      def __init__(self, owner: "GoogleGenAIClient", downloader: "ProviderMediaDownloader") -> None: ...
      async def generate(self, *, profile: VideoModelProfile, prompt: str, output_directory: Path,
                         aspect_ratio: str, resolution: str, target_duration_seconds: float,
                         starting_frame: Optional[Path], deadline: float) -> GeneratedReelClip:
          """Omits response_format.duration; empty/blocked/non-video output → ReelError."""

  # reel/download.py (new)
  class ProviderMediaDownloader:
      """aiohttp downloader; credentials only for allowlisted Google origins; bounded redirects/bytes/time."""
      async def fetch(self, uri: str, dest: Path, *, max_bytes: int, deadline: float) -> Path: ...
  ```

### Module 5: Reel music service
- **Path**: NEW `reel/music.py`; modifies `generation.py:1162` (`generate_music_stream` accepts an injected client/api version, default preserved)
- **Responsibility**: Applies the music policy, runs an isolated owned Lyria session, bounds it, propagates cancellation, and writes verified PCM→WAV (`.wav` / `audio/wav`).
- **Depends on**: M2 (errors)
- **Interface Skeleton**:
  ```python
  class MusicOutcome(BaseModel):
      status: Literal["off", "succeeded", "unavailable", "timeout", "failed", "skipped"]
      local_path: Optional[Path]; warning: Optional[str]
  class ReelMusicService:
      def __init__(self, owner: "GoogleGenAIClient", *, api_version: str, connect_timeout_seconds: float,
                   max_bytes: int) -> None: ...
      async def generate(self, request: VideoReelRequest, *, duration_seconds: float, output_directory: Path,
                         deadline: float) -> MusicOutcome:
          """off/native/muted → status off/skipped with no connection; required + failure → raises ReelError."""
  def write_pcm_wav(pcm: bytes, dest: Path, *, sample_rate: int, channels: int, sample_width: int) -> Path: ...
  ```

### Module 6: Timeline & assembly
- **Path**: NEW `reel/timeline.py` (pure), NEW `reel/assembly.py` (MoviePy in a process worker); `generation.py:2308` `_create_reel_assembly` delegates to it
- **Responsibility**: Covering-duration verification, trim, cut/crossfade timeline with real overlap, narration fit, music alignment, WebM (Opus) and MP4 (AAC) codecs, per-job working directory.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # reel/timeline.py (new)
  class TimelineEntry(BaseModel):
      scene_index: int; clip_path: Path; edit_seconds: float; narration_path: Optional[Path]
  def plan_timeline(entries: Sequence[TimelineEntry], *, transition: Literal["cut", "crossfade"],
                    crossfade_seconds: float = 0.5, fps: float) -> "TimelinePlan":
      """Validates overlap ≤ neighbours; final = Σ edit − Σ overlaps."""
  def check_measured_duration(target: float, measured: float, fps: float) -> None:
      """Raises ReelError(INSUFFICIENT_DURATION) when measured < target − 1/fps."""
  def check_narration_fits(target: float, narration_seconds: float) -> None:
      """Raises ReelError(NARRATION_TOO_LONG)."""

  # reel/assembly.py (new)
  async def assemble_reel(plan: "TimelinePlan", *, music_path: Optional[Path], audio_mode: AudioMode,
                          output_format: Literal["mp4", "webm"], work_dir: Path, deadline: float) -> Path:
      """Runs MoviePy in a managed process; cancellation terminates and awaits the worker before returning."""
  ```

### Module 7: Reel orchestration
- **Path**: modifies `generation.py:1905` (`generate_video_reel`), `:2034` (`_breakdown_prompt_to_scenes` gains `model`), `:2084` (`_process_scene`), `:2249` (`_generate_reel_music` → M5); adds `generate_video_clip`
- **Responsibility**: Resolve stage models, validate all effective profiles before any paid call (also for scenes the director produced), per-job UUID working directory, apply policies, deadlines and cancellation, persist through the FileManager, build `ReelResult`.
- **Depends on**: M1, M2, M3, M4, M5, M6
- **Interface Skeleton**:
  ```python
  async def generate_video_reel(self, request: VideoReelRequest, output_directory: Optional[Path] = None,
                                file_manager: Optional[FileManagerInterface] = None, user_id: Optional[str] = None,
                                session_id: Optional[str] = None) -> AIMessage:  # verified signature: generation.py:1905
      """Unchanged signature. metadata['video_reel'] = ReelResult JSON; files = local paths only."""
  async def generate_video_clip(self, *, prompt: str, model: str, output_directory: Path, aspect_ratio: str,
                                resolution: str, target_duration_seconds: float,
                                starting_frame: Optional[Path] = None, audio_mode: AudioMode = "separate",
                                timeout_seconds: float = 600.0) -> GeneratedReelClip:
      """Registry resolve → VeoClipAdapter | OmniClipAdapter."""
  async def _breakdown_prompt_to_scenes(self, prompt: str, model: str) -> List[VideoReelScene]:  # verified: :2034
      """Uses the given director model; scenes validated before image/video work."""
  async def _process_scene(self, scene: VideoReelScene, index: int, *, context: "ReelRunContext"
                           ) -> ReelSceneResult:  # replaces tuple return, verified: :2084
      """Raises ReelError under fail policy; returns failed result under skip."""
  ```

### Module 8: HTTP handler & artifact delivery
- **Path**: modifies `packages/ai-parrot-server/src/parrot/handlers/video_reel.py` (`post:179`, `_parse_multipart:119`, `get:271`, `_get_job_status:292`, `setup:52`)
- **Responsibility**: Stop popping `model` as a client control key and let M1 handle the alias. Indexed uploads, JSON field decoding, quotas, cleanup on every exit, query/route ID conflict (400), owner check, artifact route, signed-URL refresh, 400/403/404/413 mapping, `model_dump(mode="json")`.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  class VideoReelHandler(BaseView):  # verified: handlers/video_reel.py:31
      async def _parse_multipart(self) -> tuple[dict, dict[int, Path]]:
          """Index → path; accepts image_<index> parts or ordered slots (not both); sparse slots preserved."""
      def _resolve_job_id(self) -> Optional[str]:
          """Route match_info vs ?job_id=; differing → HTTPBadRequest."""
      async def _authorize_job(self, job: "Job") -> None:
          """Session identity must own the job (§8 Q7); non-disclosing 404 otherwise."""
      async def _get_artifact(self, job_id: str, artifact_id: str) -> web.StreamResponse:
          """Resolves ReelResult.final_artifact by id; never a raw path."""
  ```

### Module 9: Tests, dependency floor, docs
- **Path**: repairs `packages/ai-parrot/tests/test_video_reel_handler.py` (fixture: real `BaseView` request construction) or migrates it to `packages/ai-parrot-server/tests/handlers/`; NEW `packages/ai-parrot-client-google/tests/unit/reel/`; NEW opt-in `tests/live/test_reel_smoke.py` (marker `live_google`); `packages/ai-parrot-client-google/pyproject.toml:17` floor; `docs/` payload migration note
- **Responsibility**: Integration coverage across modules (§4), the SDK floor, and migration docs.
- **Depends on**: M7, M8
- **Interface Skeleton**: n/a (tests/config/docs)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_legacy_model_alias_identical_warns` / `_conflict_rejected` / `_explicit_null_rejected` | M1 | R01 alias rules |
| `test_scene_duration_bounds` | M1 | NaN, inf, 0, negative, >8 rejected; 5.0 default |
| `test_native_mode_rejects_music_and_speech` | M1 | Audio control conflicts |
| `test_registry_developer_preview_ids` / `_vertex_disabled` / `_lite_no_4k_no_reference_guidance` / `_unknown_id` / `_wrong_surface` | M2 | R02 |
| `test_select_duration_4_5_6_8` / `_high_resolution_forces_8` / `_omni_none` | M2 | R03 |
| `test_classify_immediate_client_error_safety` / `_operation_error` / `_filtered_output` / `_auth_not_retryable` | M2 | R06 |
| `test_veo_person_generation_lowercase` / `_duration_submitted` / `_no_generate_audio_on_developer_api` | M3 | Transport conversion through real SDK `types` serialization (R05) |
| `test_veo_safety_block_single_attempt` | M3 | Exactly one generate call; no text-to-video retry (R06) |
| `test_omni_inline_data` / `_uri_download` / `_empty_output` / `_bad_mime` / `_no_veo_fields` | M4 | Mocked `aio.interactions.create` |
| `test_downloader_credentials_not_forwarded_on_redirect` / `_max_bytes` / `_timeout` | M4 | |
| `test_music_off_no_connection` / `_optional_warns` / `_required_fails` / `_timeout` / `_cancellation_closes_session` / `_empty_stream` | M5 | R05, R08 |
| `test_pcm_wav_roundtrip_sample_count` / `_suffix_and_mime` | M5 | AC05 |
| `test_timeline_cut_20s` / `_crossfade_18_5s` / `_overlap_exceeds_neighbour` / `_insufficient_duration` / `_narration_too_long` | M6 | R04 |
| `test_stage_models_forwarded` / `_director_unused_metadata` / `_scene_override` / `_mixed_reel_order` | M7 | R01 — assert actual adapter call args |
| `test_fail_policy_default` / `_skip_preserves_indices` / `_all_failed_is_failure` | M7 | AC10 |
| `test_cancellation_awaits_children_then_cleans` / `_scene_deadline` / `_job_deadline` | M7 | AC09 |
| `test_sparse_and_indexed_uploads` / `_duplicate_names` / `_mixed_addressing_rejected` / `_quota_413` | M8 | AC07, AC08 |
| `test_storage_config_json_object_only` / `_tmp_cleanup_every_exit` | M8 | |
| `test_poll_route_and_query` / `_conflicting_ids_400` / `_artifact_route_owner_only` / `_url_query_preserved` | M8 | AC03, AC12, AC13 |

### Integration Tests
| Test | Description |
|---|---|
| `test_handler_post_to_job_callback_forwards_effective_models` | Real handler + JobManager + mocked provider adapters; the 20 former fixture errors are gone (R07) |
| `test_small_media_mp4_aac_and_webm_opus_assembly` | Real 1-second fixture clips through MoviePy; playable output with audio; crossfade overlap within one frame (AC11) |
| `test_cloud_artifact_descriptor_roundtrip` | Mocked cloud transport, real descriptor serialization, signed URL refresh (AC04) |
| `test_sdk_floor_async_surfaces` | Introspects `aio.interactions`, `aio.models.generate_videos`, `aio.operations.get` on the locked and floor SDK (R10) |
| `live_google::test_veo_scene` / `_omni_scene` / `_mixed_reel` / `_native_audio` / `_optional_music` | Opt-in, paid; records model/API/SDK/region; access failures reported separately (R11) |

### Test Data / Fixtures
```python
@pytest.fixture
def tiny_clip(tmp_path) -> Path:
    """1 s 720p 24 fps MP4 generated locally with MoviePy ColorClip (no network)."""

@pytest.fixture
def registry() -> VideoProfileRegistry:
    return VideoProfileRegistry.default()

@pytest.fixture
async def reel_handler_client(aiohttp_client):
    """Real VideoReelHandler.setup(app) with an in-memory JobManager; no conftest class replacement."""
```

---

## 5. Acceptance Criteria

- [ ] **AC01 (R01)**: HTTP and direct callers pick director, image (background + foreground), reel video and scene video models independently. Tests assert the actual adapter arguments.
- [ ] **AC02 (R01)**: Legacy `model` maps to `director_model`. Differing values → 400. Identical values → accepted with a deprecation warning in `ReelResult.warnings`. `model` never selects the video model.
- [ ] **AC03 (R02)**: Registry tests cover the Developer API preview IDs, disabled Vertex GA profiles, Lite exclusions, unknown IDs and wrong-surface IDs. Invalid combinations fail before any paid call, including for scenes the director produced.
- [ ] **AC04 (R03)**: A default 5 s scene submits a legal covering duration and is trimmed to 5 s. The 4/5/6/8 s and high-resolution cases pass. Output too short by more than one frame fails with `insufficient_duration`, with no regeneration.
- [ ] **AC05 (R04)**: Four 5 s scenes give 20 s with cuts, or 18.5 s with 0.5 s crossfades, within one frame. Skipped scenes keep their indices. Music follows the final duration.
- [ ] **AC06 (R05)**: `separate`, `native` and `muted` produce the specified soundtracks. `generate_audio` is absent from Developer API serialization. Music `off` makes no connection, `optional` warns with a structured status, `required` fails the job. `native`/`muted` make no TTS or Lyria calls.
- [ ] **AC07 (R06)**: An immediate SDK safety error, an operation safety failure and filtered output each make exactly one generation attempt and keep `safety_blocked`. Auth and validation errors never enter a retry path.
- [ ] **AC08 (R07)**: The handler fixture builds the view the real way, all 20 setup errors are gone, and the queued job callback is tested end to end with mocked adapters.
- [ ] **AC09 (R08)**: Lyria handshake/access failure, timeout, empty stream and cancellation are covered. WAV duration, channels and rate match the stream. Stored as `.wav` / `audio/wav`. The music client is separate from the director and video clients.
- [ ] **AC10 (R09)**: Result URLs round-trip byte-exact through Pydantic, job storage and HTTP JSON. Artifacts download only through the owner-checked route or refreshed signed URLs.
- [ ] **AC11 (R09)**: Upload positions survive gaps and reordering. Duplicate names never overwrite. Every temporary directory is removed on every exit path. Invalid JSON shapes and unsupported values → 400; limits → 413.
- [ ] **AC12 (R09)**: SDK sessions, child tasks and the media worker close on success, failure, timeout and cancellation. Scene and job deadlines are enforced.
- [ ] **AC13**: Default `partial_failure_policy=fail`. `skip` reports `partial=True` and per-scene errors. All scenes failing always fails the job.
- [ ] **AC14**: Polling accepts route or query IDs. Differing IDs → 400. Cancellation shows in the job status.
- [ ] **AC15 (R10)**: `google-genai` floor raised to a tested version (`>=2.23.0`) with the lockfile synced. Async submit, poll and download plus Omni output contracts are tested. Docs state the tested versions. Lazy import without Google installed still works.
- [ ] **AC16 (R11)**: The opt-in `live_google` smoke suite exists and records model, API, SDK version and region. Evidence is documented before production enablement; default CI does not run it.
- [ ] **AC17**: No cross-model fallback, no safety resubmission, no generation resubmission after an ambiguous timeout. Operation IDs are recorded for reconciliation.
- [ ] **AC18**: `pytest packages/ai-parrot-client-google/tests/unit/reel packages/ai-parrot-server/tests/handlers -k reel` passes. `ruff check` and `black --check` pass on the touched files.

---

## 6. Codebase Contract

> Re-verified 2026-09-17 on `dev@9c750d577`. Line numbers are from this commit.

### Verified Imports
```python
from parrot.clients.google import GoogleGenAIClient, GoogleModel      # verified: clients/google/__init__.py:1,3
from parrot.models.google import VideoReelRequest, VideoReelScene, AspectRatio  # verified: models/google.py:398,376,215
from parrot.models.responses import AIMessage, AIMessageFactory        # verified: models/responses.py:75,369
from parrot.interfaces.file import FileManagerInterface                # verified: handlers/video_reel.py:26
from parrot.tools.filemanager import FileManagerFactory                # verified: handlers/video_reel.py:27
from google import genai                                               # google-genai 2.23.0 installed
# genai.client.AsyncClient has `interactions` (verified by introspection 2026-09-17)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/models/google.py  (imports: typing Any/Literal/List/Dict/Optional, Enum, json, pydantic BaseModel/Field/field_validator — lines 5–8; no model_validator yet)
class AspectRatio(str, Enum): ...                                      # line 215
class VideoReelScene(BaseModel):                                       # line 376
    background_prompt: str; foreground_prompt: Optional[str]; video_prompt: str
    narration_text: Optional[str]; duration: float = 5.0  # line 387; reference_image: Optional[str]
class VideoReelRequest(BaseModel):                                     # line 398
    prompt: str; scenes: Optional[List[VideoReelScene]]; speech: Optional[List[str]]
    music_prompt; music_genre: Optional[MusicGenre]; music_mood: Optional[MusicMood]
    aspect_ratio: AspectRatio = RATIO_9_16; transition_type: str = "crossfade"; output_format: str = "mp4"
    reference_images: Optional[List[str]]; storage_backend: Literal["fs","temp","s3","gcs"] = "fs"
    storage_config: Optional[Dict[str, Any]]
    @field_validator("scenes", "speech", mode="before") def _parse_json_strings(cls, v)  # line 446

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                            # line 75
    media: Optional[List[Path]]                                        # line 90
    files: Optional[List[Path]]                                        # line 91
    metadata: Dict[str, Any]                                           # line 152
    artifacts: List[Dict[str, Any]]                                    # line 155
    def add_artifact(self, artifact_type: str, content: Any, **metadata) -> None  # line 247
class AIMessageFactory:                                                # line 369
    @staticmethod def from_video(**kwargs)                             # line 1077

# packages/ai-parrot/src/parrot/clients/base.py  (DO NOT MODIFY)
    async def __aenter__(self) / __aexit__(...)                        # lines 1155, 1167
    def _save_audio_file(self, audio_data: bytes, output_path: Path, mime_format: str)  # line 2697

# packages/ai-parrot-client-google/src/parrot/clients/google/models.py
class GoogleModel(Enum):                                               # line 11
    GEMINI_2_5_FLASH = "gemini-2.5-flash"                              # line 42
    GEMINI_3_1_FLASH_IMAGE_PREVIEW = "gemini-3.1-flash-image"          # line 60 (value has NO "-preview")
    VEO_3_1 = "veo-3.1-generate-preview"                               # line 65
    VEO_3_1_FAST = "veo-3.1-fast-generate-preview"                     # line 66
    VEO_3_1_LITE = "veo-3.1-lite-generate-preview"                     # line 67
class VertexAIModel(Enum): ...                                         # line 76

# packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):  # line 101
    async def get_client(self, model: str = None, **kwargs) -> genai.Client  # line 630
    async def close(self) -> None                                      # line 693
    # deep research: synchronous self.client.interactions.create(...)   # line 5183 — NOT reusable for Omni

# packages/ai-parrot-client-google/src/parrot/clients/google/generation.py
class GoogleGeneration:                                                # line 73
    async def create_speech / generate_speech(...)                     # lines 728, 487
    async def video_generation(self, prompt, output_directory=None, model=GoogleModel.VEO_3_1,
        aspect_ratio=RATIO_16_9, negative_prompt=None, number_of_videos=1, reference_image=None,
        generate_image_first=False, image_prompt=None, duration: int = 8, resolution=None,
        person_generation: str = "allow_adult", include_audio: bool = True, last_frame=None,
        reference_images=None, reference_type="asset", extend_video=None, seed=None,
        user_id=None, session_id=None, **kwargs) -> AIMessage          # line 844
        #  :965 pg_val = person_generation.upper()   ← bug
        #  :987 "duration_seconds": duration; :997/:1028/:1056 force 8
        #  :1078 await client.aio.operations.get(operation)
        #  :1092 RuntimeError("Video blocked by content safety filter: ...")
        #  :1100 await client.aio.files.download(file=vid.video)
    async def _async_save_video_file(self, video_bytes, output_directory, video_number=0, mime_format="video/mp4") -> Path  # line 1124
    async def _strip_audio(self, video_path: Path) -> Path             # line 1138
    async def generate_music_stream(self, prompt, genre=None, mood=None, bpm=90, temperature=1.0,
        density=0.5, brightness=0.5, timeout: int = 300) -> AsyncIterator[bytes]  # line 1162
        #  :1196 music_client = await self.get_client(http_options={"api_version": "v1alpha"})
    async def generate_image(self, prompt, model: Optional[Union[str, GoogleModel]] = None,
        reference_images=None, google_search=False, aspect_ratio=None, ..., output_directory=None, ...)  # line 1524
    async def generate_video_reel(self, request, output_directory=None, file_manager=None,
        user_id=None, session_id=None) -> AIMessage                    # line 1905
        #  scenes processed sequentially; failures appended as None then filtered as result[0] (bug)
        #  returns AIMessageFactory.from_video(files=[final_url], model="google-reel-pipeline", ...)
    async def _breakdown_prompt_to_scenes(self, prompt: str) -> List[VideoReelScene]  # line 2034 (hardcodes GEMINI_2_5_FLASH)
    async def _process_scene(self, scene, index, output_dir, aspect_ratio, file_manager=None,
        job_prefix=None) -> tuple[Optional[str], Optional[str]]        # line 2084 (hardcodes VEO_3_1; safety retry)
    def _merge_video_audio(self, video_path, audio_path, output_path)  # line 2201
    async def _composite_images(self, bg_path, fg_path, output_dir, index) -> Path  # line 2220
    async def _generate_reel_music(self, request, output_dir, file_manager=None, job_prefix=None) -> Optional[str]  # line 2249 (stores bg_music.mp3)
    async def _create_reel_assembly(self, scene_outputs, music_key, output_dir, transition, output_format,
        file_manager=None, job_prefix=None) -> str                     # line 2308

# packages/ai-parrot-server/src/parrot/handlers/video_reel.py
class VideoReelHandler(BaseView):                                      # line 31
    def setup(cls, app, route="/api/v1/google/generation/video_reel")  # line 52 (also adds f"{route}/{{job_id}}" at :56)
    def job_manager(self) -> JobManager                                # line 63
    def _create_file_manager(self, output_directory=None)              # line 74
    async def _parse_multipart(self) -> tuple[dict, list[Path]]        # line 119
    async def post(self) -> web.Response                               # line 179
        #  :199 model = data.pop("model", "gemini-3.5-flash"); :238 GoogleGenAIClient(model=model)
        #  :248 result.model_dump()  (not mode="json")
    async def get(self) -> web.Response                                # line 271 (route job_id only)
    async def _get_job_status(self, job_id: str) -> web.Response       # line 292

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py
class JobManager:                                                      # line 22
    def create_job(...)                                                # line 171
    async def execute_job(self, job_id, execution_func) -> None        # line 209 (create_task, not awaited)
    async def _run_job(self, job_id, execution_func) -> None           # line 228
    async def get_job_async(self, job_id) -> Optional[Job]             # line 288
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VeoClipAdapter` | `owner.get_client(model=...)` → `aio.models.generate_videos`, `aio.operations.get`, `aio.files.download` | method call | `client.py:630`, `generation.py:1078,1100` |
| `OmniClipAdapter` | `sdk.aio.interactions.create` | method call | SDK 2.23.0 introspection |
| `ReelMusicService` | `generate_music_stream` (client injected) | method call | `generation.py:1162,1196` |
| `generate_video_reel` (M7) | `generate_image(model=image_model)` | kwarg | `generation.py:1524` |
| `generate_video_reel` (M7) | `AIMessageFactory.from_video(files=…, metadata=…, artifacts=…)` | factory | `responses.py:1077` |
| `VideoReelHandler.post` (M8) | `JobManager.execute_job` | method call | `jobs/job.py:209` |
| `VideoReelHandler` artifact route | `VideoReelHandler.setup` router | `add_view` | `video_reel.py:52–56` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.clients.google.reel`~~ package, ~~`VideoModelProfile`~~, ~~`VideoProfileRegistry`~~, ~~`GeneratedReelClip`~~, ~~`ReelError`/`ReelErrorCode`~~, ~~`VeoClipAdapter`~~, ~~`OmniClipAdapter`~~, ~~`ReelMusicService`~~: all NEW in this spec.
- ~~`ReelArtifact`~~, ~~`ReelResult`~~, ~~`VideoReelScene.video_model`~~, ~~`VideoReelRequest.director_model/image_model/video_model/audio_mode/music_policy/partial_failure_policy/resolution`~~: NEW.
- ~~`GoogleGeneration.generate_video_clip`~~: NEW.
- ~~`GoogleModel.GEMINI_OMNI_*`~~: no Omni enum member exists. The registry uses string IDs; do not add an enum as a routing key.
- ~~`GoogleModel.GEMINI_3_5_FLASH`~~ is not the reel director default. The handler's `"gemini-3.5-flash"` string (`video_reel.py:199`) was never used for scene breakdown.
- ~~`from google.genai import _interactions`~~ and `google.genai._gaos`: private and not importable. Use public `client.aio.interactions`.
- ~~An async deep-research Interactions helper~~: `client.py:5183` is synchronous streaming and must not be reused.
- ~~Artifact download route~~ `…/video_reel/{job_id}/artifacts/{artifact_id}`: does not exist.
- ~~`packages/ai-parrot-client-google/tests/unit/reel/`~~: does not exist (unit dir has only `test_entry_points.py`, `test_gemini_multiround_usage.py`, `test_google_format_history.py`, `test_openai_compat_client.py`).
- ~~Reel/video handler tests in `packages/ai-parrot-server/tests/handlers/`~~: none. Current tests are `packages/ai-parrot/tests/test_video_reel_handler.py`, `test_google_reel.py`, `test_video_reel_storage.py`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async throughout. MoviePy/PIL CPU work runs in a managed process boundary (assembly) or `asyncio.to_thread` for small ops (existing `_composite_images`). Cancelling an await does not stop an encoder, so terminate and await the worker.
- Pydantic v2 everywhere. Core models use strings/literals; the provider satellite owns capability resolution [F007].
- `self.logger`, never `print`. Redact keys and base64 from logs and error messages.
- Lazy provider imports in the handler (`video_reel.py:234–236`, FEAT-523) stay.
- Clients: per-stage owned clients via `get_client(model=effective_model)`. Never let `self.model` implicitly pick location or API version. No `base.py` changes.
- Stored results: `model_dump(mode="json")`. URLs stay `str`.
- The existing `reference_image` is a **starting frame**. Provider `reference_images` is **asset guidance**, with different constraints; never conflate them. Foreground-composited images become the starting frame for either backend, and Omni's prompt describes that input role.
- Region/person-generation policy comes from deployment configuration, never inferred from model strings or caller timezone.

### Known Risks / Gotchas
- **Omni is unverified live** (duration, URI auth, MIME). M4 is not delegation-eligible until §8 Q3 is answered with evidence. Default CI mocks it.
- **`GEMINI_3_1_FLASH_IMAGE_PREVIEW` enum value is `"gemini-3.1-flash-image"`** (`models.py:60`). The spec default string is `gemini-3.1-flash-image-preview`. Registry and image-model validation must accept the deployed ID; confirm at implementation (§8 Q4).
- **The `speech` list overrides scene `narration_text`** (`generation.py:1960–1969`, existing precedence). Keep it and document it.
- **Existing scene-failure filtering bug**: `_process_scene` returns `(None, None)` but the loop appends `None` on exception, then indexes `result[0]`. It goes away with `ReelSceneResult`.
- **Music key stored as `bg_music.mp3` holding WAV bytes** (`generation.py:2297`). Fixed by M5.
- **Behavior change**: legacy `model` used to build the client and now selects the director. Document it in the migration note (M9).
- **Ambiguous timeouts**: a timed-out generation may still complete remotely and bill. Record the operation ID and surface `timeout`; never resubmit.
- **Shared venv / worktree**: run tests with `PYTHONPATH` covering `packages/ai-parrot/src`, `packages/ai-parrot-client-google/src`, `packages/ai-parrot-server/src`. Never `uv sync` inside the worktree.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `google-genai` | `>=2.23.0` (raise from `>=2.18.1`, `pyproject.toml:17`) | `aio.interactions` for Omni; version tested here. 2.24.0 is not claimed until verified |
| `moviepy` | `2.2.1` (existing) | Trim, crossfade, codecs |
| `aiohttp` | existing | Provider URI downloader, artifact route |

No new dependency is authorized.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-564-video-reel-omni-veo-reliability` from `origin/dev`. The `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph** (evidence = imported symbol):
  - M2 → M1 (`AudioMode`, `VideoResolution` literals)
  - M3 → M2, M4 → M2 (`VideoModelProfile`, `GeneratedReelClip`, `ReelError`)
  - M5 → M2 (`ReelError`); M5 → M1 (`VideoReelRequest`)
  - M6 → M2 (`ReelError`); M6 → M1 (`AudioMode`)
  - M7 → M1, M2, M3, M4, M5, M6 (orchestrates all)
  - M8 → M1 (`VideoReelRequest`, `ReelResult`)
  - M9 → M7, M8
  - After M1+M2: **M3, M4, M5, M6 and M8 can run concurrently.**
- **Shared files**:
  - `generation.py`: M3 (`:965` lowercase fix), M5 (`:1162/1196`), M6 (`:2308` delegation), M7 (`:1905–2330`). Serialize M3 → M5 → M6 → M7 edits to this file, or keep M3/M5/M6 edits limited to the listed lines with M7 last.
  - `reel/__init__.py`: created in M2; later modules only append exports, and M7 finalizes.
- **Exclusive resources**: M9's `pyproject.toml` floor + `uv.lock` sync → `parallel: false`.
- **Cross-feature dependencies**: none. FEAT-563 (scoped-test-selection) is unrelated.

---

## 8. Open Questions

- [x] Model selection granularity — *Resolved 2026-09-17 (user)*: reel-level `video_model` default plus nullable per-scene overrides (mixed Veo/Omni reels); no automatic cross-model fallback, no conversational Omni editing.
- [x] Legacy top-level `model` — *Resolved 2026-09-17 (user)*: deprecated alias for `director_model`; differing values rejected (400), identical accepted with a deprecation warning; stage defaults director `gemini-2.5-flash`, image `gemini-3.1-flash-image-preview`, video Veo 3.1 standard.
- [x] Music policy in `separate` mode — *Resolved 2026-09-17 (user)*: `optional` by default (best-effort + structured status/warning); `off` and `required` available explicitly.
- [x] Omni integration shape — *Resolved in proposal research [F005,F006]*: separate async Interactions adapter; Veo remains the compatibility default.
- [ ] **Q3** Implementation evidence gate: Omni URI authentication, actual output duration and MIME on SDK 2.23.0 (blocks M4 delegation). — *Owner: implementer (engineering verification)*
- [ ] **Q4** Implementation evidence gate: which image model ID the deployment enables (`gemini-3.1-flash-image-preview` vs enum value `gemini-3.1-flash-image`). — *Owner: implementer*
- [ ] **Q5** Implementation evidence gate: verified Vertex Veo 3.1 GA capabilities and credentials before setting `enabled=True`. — *Owner: implementer*
- [ ] **Q6** Implementation evidence gate: Lyria `api_version` (code `v1alpha` vs public example `v1beta`) and PCM rate/channels/width. — *Owner: implementer*
- [ ] **Q7** Implementation evidence gate: deployed owner/tenant helper for job and artifact authorization, and the local artifact-serving convention (blocks M8 delegation). — *Owner: implementer*

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: skipped (exploration doc status is `review`, not `accepted`; §3b precondition not met) · Transcript: none

The proposal's own revision verified an external Gemini review (proposal §2.4, findings F009–F012). That is recorded in the proposal and is not an independent design cross-check of this spec.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-17 | Codex | Draft from review and researched Omni/Veo proposal |
| 0.2 | 2026-09-17 | Claude | Reconciled with revised proposal (F009–F012): stage routing + legacy alias, API-surface registry, music policy, audio transport constraints, error taxonomy, R01–R11 → AC01–AC18; user decisions on model granularity/alias/music folded in; codebase contract re-verified with line anchors; module skeletons, delegation table and worktree graph added |
