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
**Author**: Jesus Lara / Codex
**Status**: draft
**Target version**: next
**Research**: sdd/state/FEAT-564/ (finding references F001–F008)
**Approval**: requested scope is authorized for documentation; design choices below remain proposals pending review.

## 1. Motivation & Business Requirements

Repair the complete VideoReelHandler pipeline and add gemini-omni-1.1-flash alongside Veo 3.1. Preserve background jobs and shared assembly, while exposing model selection and returning usable artifacts [F001–F006].

Goals: correct provider requests, reliable artifact delivery, accurate audio/timing, bounded resource ownership, mixed-model reels, regression coverage, and clear failure reporting.

Non-goals: conversational Omni editing, video extension, automatic model fallback, a new queue system, a frontend redesign, broad AbstractClient changes, and changing shared AIMessage.files semantics.

## 2. Architectural Design

### Overview

Proposed components marked NEW below do not exist yet [F002,F006].

VideoReelHandler → validated VideoReelRequest → generate_video_reel
→ per-scene effective model → Veo adapter OR Omni adapter
→ normalized local clip → shared narration/music + assembly
→ FileManager storage → typed artifact metadata → job polling/download.

Both adapters run inside GoogleGenAIClient's generation layer. The handler must not call Google SDK APIs itself. Core models remain independent of satellite provider enums [F007].

### Data contract (proposed additions)

| Field | Location | Contract |
|---|---|---|
| video_model | reel | Default veo-3.1-generate-preview; exact allowlisted IDs |
| video_model | scene | Nullable override; precedence scene > reel |
| video_resolution | reel | Default 720p; backend capability validation before submission |
| audio_mode | reel | separate (default), native, muted |
| partial_failure_policy | reel | fail (default), skip |
| generation_timeout_seconds | server config | Positive bounded per-scene deadline, proposed 600 seconds |
| job_timeout_seconds | server config | Total deadline, proposed 3600 seconds |
| duration | scene | Positive edit target, proposed 0 < duration <= 8 for common initial contract |
| output_format | reel | mp4 or webm only |
| transition_type | reel | cut or crossfade only |

Supported video IDs: veo-3.1-generate-preview, veo-3.1-fast-generate-preview, veo-3.1-lite-generate-preview, gemini-omni-1.1-flash [F002,F005,F008].

Legacy top-level model retains client/text-model meaning. It is not silently reinterpreted as video_model. Existing payloads continue defaulting to Veo. The existing five-second scene default remains valid as an edit target; Veo generates six seconds when capabilities permit, then trims to five. High-resolution constraints may require eight seconds [F002,F008].

Omni duration: initial implementation omits response_format.duration because installed typing is a free-form string without verified supported values [F006]. Generate using the provider default, inspect actual media duration, then trim. If shorter than requested, raise insufficient_duration; do not repeat billable generation or stretch silently. Adding explicit Omni generation durations requires documented values and a contract test.

Resolution is common per reel. Allow only the intersection supported by all effective models; reject unsupported requests before any provider call. Veo Lite does not inherit every standard-model capability. Aspect ratio is restricted to 16:9 or 9:16 for this endpoint.

Audio:
- separate preserves current narration/music behavior and removes provider audio.
- native preserves generated sound; reject explicit speech/narration and music controls.
- muted removes all audio and skips music/speech.
- Narration longer than the edit target fails with narration_too_long; do not silently truncate.
- Music format is explicit, sourced from negotiated/verified stream metadata; WAV headers match PCM and storage suffix is .wav.

### Backend contracts

NEW normalized Pydantic record GeneratedReelClip: local_path: Path, model: str, backend: Literal[veo,omni], actual_duration_seconds: float, has_audio: bool, provider_operation_id: str | None. Proposed module: packages/ai-parrot-client-google/src/parrot/clients/google/video.py.

NEW adapter entry point on the generation mixin:

    async def generate_video_clip(
        self, *, prompt: str, model: str, output_directory: Path,
        aspect_ratio: str, resolution: str, target_duration_seconds: float,
        reference_image: Path | None = None, timeout_seconds: float = 600,
    ) -> GeneratedReelClip

Public generate_video_reel retains its existing signature. Existing video_generation remains a Veo-compatible public method; the new dispatcher enables Omni without passing an Omni ID to generate_videos [F002].

Veo: lowercase person-generation strings; modality/region validation; supported duration selection; bounded operation polling; download and validate MP4. Remove automatic retry as text-to-video after a safety block. Unsupported feature combinations are validation errors, not warnings followed by silently dropped options [F008].

Omni: use await sdk.aio.interactions.create with model, typed image/text input, response_format video/aspect/resolution/delivery, background=False, store=False, stream=False. Use a deadline around the async call. Normalize output_video.data or output_video.uri. Verify completion status, MIME, bytes and media readability; empty/blocked output is failure. Do not pass Veo configuration, temperature or negative_prompt fields [F005,F006].

URI retrieval requires a verified adapter contract: check the installed public download API or use aiohttp with Google-origin credential restrictions. Bound redirects, bytes and time; never attach API keys to arbitrary hosts or logs. Prefer URI delivery for large outputs; support inline base64 responses in the decoder. URI authentication is a mandatory implementation research gate, not an invented files.download equivalence.

### Artifact contract

Use existing AIMessage.metadata and artifacts [F003], validated through NEW ReelArtifact and ReelResult models in core models/google.py:
- ReelArtifact: artifact_id, storage_backend, storage_key, mime_type, size_bytes, download_url: str | None, expires_at: datetime | None.
- ReelResult: final_artifact, effective_models, scenes, partial, warnings, actual_duration_seconds.
- Per-scene result: index, model, status, requested_duration_seconds, generated_duration_seconds, final_duration_seconds, error_code/message where relevant.

Store the typed result using model_dump(mode="json") inside metadata["video_reel"]. AIMessage.files contains only durable local filesystem paths, or is empty for cloud-only output. Never pass remote URIs into a Path field. Existing fields remain; consumers migrate to the additive artifact descriptor for downloads.

Local delivery: proposed GET /api/v1/google/generation/video_reel/{job_id}/artifacts/{artifact_id}. Resolve an artifact ID through the job manifest, never accept a raw path. Enforce owner/tenant authorization before loading metadata or serving bytes. For cloud output, retain storage keys and refresh expiring signed URLs when polling. Do not persist provider base64 bytes or short-lived provider links as the durable artifact.

## 3. Module Breakdown

| Module | Files / responsibility | Dependencies |
|---|---|---|
| M1 Contracts | Modify core models/google.py; provider models.py; NEW provider video.py records/capabilities | None |
| M2 Provider generation | Modify provider generation.py and client.py; separate adapters, lifecycle, bounded calls | M1 |
| M3 Orchestration/media | Modify generation.py; timing, PCM, errors, cancellation, MoviePy cleanup | M1,M2 |
| M4 HTTP/storage | Modify server handlers/video_reel.py; indexed uploads, validation, authorized delivery, polling | M1,M3 |
| M5 Tests/docs | NEW tests under ai-parrot-client-google/tests and ai-parrot-server/tests; repair/migrate existing reel tests; document payload migration | M1–M4 |

All paths in M1–M4 are grounded in §6; video.py and new tests are proposed files.

Delegation-eligible modules:

| Module | Eligible? | Decided contract / remaining design |
|---|---|---|
| M1 | Yes after approval | Field names, defaults, model precedence, artifacts |
| M2 | No yet | Verify URI download auth and deployment region policy |
| M3 | Yes after approval | Edit targets, three audio modes, explicit failures |
| M4 | No yet | Verify deployed owner/tenant APIs and safe artifact delivery integration |
| M5 | Yes after dependencies | Matrix below; no mocked-away HTTP/storage contracts |

No delegates are launched by this documentation task.

## 4. Test Specification

| Group | Required cases |
|---|---|
| Routing | Legacy Veo default; reel Omni; scene override; alternating Omni/Veo reel preserves order; unknown model rejected |
| Veo wire | Lowercase person_generation; 4/6/8 selection; Lite capability matrix; resolution constraints; safety blocks not retried with altered input |
| Omni wire | Async create; no Veo-only args; text and image input; completed/failed output; inline and URI media; malformed base64/MIME/empty response |
| Downloads | Authenticated Google URI; signed URI; redirect credential isolation; timeout; oversized output |
| Timing/media | Five-second target trimmed from six; short output error; actual durations; narration overflow; true crossfade overlap |
| Audio | Stereo PCM round trip preserves sample count/duration; correct WAV extension; separate/native/muted; no conflicting audio options |
| Formats | Small real MP4/AAC and WebM/Opus assets through available encoders; verify playable output with audio |
| Uploads | Repeated filenames; empty middle/first slots; explicit indices; reordered parts; invalid indices; malformed JSON; non-object JSON; unsupported file; quotas |
| Cleanup | Parser failure, validation failure, setup failure, provider failure, cancellation, timeout and successful completion |
| Storage | Real local/temp managers; mocked cloud transport with real descriptor serialization; exact URL query preservation; expired URL refresh |
| HTTP auth | Requester identity used rather than supplied user_id; owner/tenant access; forbidden path and artifact traversal |
| Jobs | Query and path polling; conflicting IDs; cancellation status; deadline failure; skip policy reports errors; all scenes failed |
| Concurrency | Two jobs cannot overwrite intermediate paths; cancellation waits for media worker before deleting workdir |
| SDK ownership | Every created provider transport closes once on success/failure/cancellation; music client isolated by API options |

Move or repair historical tests without relying on broad conftest replacements for the classes being tested. Use the real BaseView request construction. Keep cloud/provider network mocked in default CI. Save logs under artifacts/logs.

Opt-in paid smoke suite: Veo scene, Omni scene, mixed two-scene reel, separate narration/music, native audio and configured cloud artifact download. Record SDK/model/region and redact credentials. No live smoke run is part of spec creation.

## 5. Acceptance Criteria

- [ ] AC01 Default payload uses supported Veo 3.1; explicit Omni and mixed-scene selection route correctly.
- [ ] AC02 SDK requests conform to each backend; unsupported model/option combinations fail before spending.
- [ ] AC03 Result URLs round-trip exactly through Pydantic, job persistence and HTTP JSON.
- [ ] AC04 Final artifacts are downloadable through authorized local delivery or valid refreshed cloud URLs.
- [ ] AC05 Music WAV duration/channels/rate match the input stream; storage MIME and extension agree.
- [ ] AC06 Target durations are honored by supported generation plus local trimming; actual duration is recorded.
- [ ] AC07 Upload positions survive gaps and reordering; duplicate names never overwrite; every temp directory is cleaned.
- [ ] AC08 Invalid JSON shapes, unsafe filesystem paths and unsupported output values return actionable 4xx responses.
- [ ] AC09 SDK sessions and child tasks close on every termination path; scene/job deadlines are enforced.
- [ ] AC10 No silent scene omissions: fail by default; skip explicitly reports partial status and indexed errors.
- [ ] AC11 MP4 and WebM play with valid audio; crossfades overlap; narration overflow is explicit.
- [ ] AC12 Job polling supports route/query IDs; differing simultaneous IDs return 400; cancellation is visible.
- [ ] AC13 Owner/tenant checks protect jobs and artifacts; client-supplied identity cannot grant access.
- [ ] AC14 All historical review findings have regression coverage or an explicit reviewed deployment-policy disposition.
- [ ] AC15 Dependency floor is tested for Omni support; lazy import behavior remains valid without Google installed.
- [ ] AC16 Offline focused suites, black and ruff pass; opt-in live evidence is documented before production enablement.
- [ ] AC17 No unrequested cross-model generation retries; uncertain remote completion is surfaced and may be reconciled by operation ID.

## 6. Codebase Contract

Verified imports (source-grounded; no production module import/network execution required):
- from parrot.clients.google import GoogleGenAIClient — provider __init__.py:1 [F007].
- from parrot.models.google import VideoReelRequest, VideoReelScene, AspectRatio — core models/google.py:376–453 and handler:19–25 [F001].
- from parrot.models.responses import AIMessage, AIMessageFactory — responses.py:75,1077 [F003].
- from google import genai — installed 2.23.0 offline introspection [F006].
- Use public SDK entry points; never import google.genai._gaos in application code.

Existing signatures:
- generation.py:1905: generate_video_reel(self, request: VideoReelRequest, output_directory: Optional[Path] = None, file_manager: Optional[FileManagerInterface] = None, user_id: Optional[str] = None, session_id: Optional[str] = None) -> AIMessage [F002].
- generation.py:2084: _process_scene(self, scene, index, output_dir, aspect_ratio, file_manager=None, job_prefix=None) -> tuple[Optional[str], Optional[str]] [F002]. Proposed normalized record replaces this internal tuple only.
- generation.py:2249: _generate_reel_music; :2308: _create_reel_assembly [F002].
- client.py:630: async get_client(self, model: str = None, **kwargs) -> genai.Client; :693: async close(self) -> None [F004].
- responses.py:91: files is Optional[List[Path]]; :152 metadata and :155 artifacts are additive extension points [F003].
- jobs/job.py:209: execute_job schedules _run_job; it does not await generation inline [F004].

Does not exist yet: Omni video adapter, GeneratedReelClip, ReelArtifact, ReelResult, per-scene video_model and the artifact download route. The provider's existing synchronous deep-research Interactions code is not an async generation implementation [F006].

## 7. Implementation Notes & Constraints

Use per-job temporary working directories with UUID filenames. Own all generated images/videos locally until persisted. Keep foreground compositing and background generation behavior; provide the resulting image as the scene's starting reference to either backend. Clearly describe that input role in Omni's prompt.

Uploads: support existing ordered reference_images including placeholders and explicit image_<index> parts. Reject mixed ambiguous addressing, duplicate indices, invalid MIME or out-of-range indices. Decode storage_config JSON in multipart. Proposed limits: 20 scenes, 10 MiB/image and 100 MiB total, server-configurable. HTTP accepts only server-configured storage destinations and allowlisted local roots; direct Python callers retain explicit FileManager injection.

Error contract: validation errors → 400 (upload limits → 413); forbidden access → 403 or non-disclosing 404 per server convention; admitted jobs report stable error codes in status results. Record provider operation IDs and redacted diagnostics; do not store keys or raw base64 in errors.

Lifecycle: explicit async context ownership for every fresh SDK transport; use Google-scoped helpers rather than modifying base.py. Ensure synchronous SDK resources also close. Deadlines cancel awaited tasks; cancellation does not imply remote generation cancellation. CPU-heavy assembly uses a managed process boundary per repository conventions; do not assume cancelling an await stops an encoder. Cleanup waits for worker termination. Establish this implementation in the task blueprint rather than adding an unbounded global executor.

Retry policy: at most three bounded transient polling/download attempts within the original deadline. Do not blindly retry generation submission after an ambiguous timeout or safety block. Keep SDK automatic submission retries configured consistently with this rule.

Dependencies: google-genai installed 2.23.0; require a tested floor (proposed >=2.23.0) in the Google satellite and synchronize the lockfile during implementation. Existing MoviePy 2.2.1 and aiohttp are used. No new dependency is authorized by this spec without normal dependency review.

Worktree strategy: one feature worktree based on dev; shared generation.py changes require sequential tasks. Contracts precede adapters; adapters precede orchestration; HTTP integration follows stable contracts. Tests can be authored independently only after contracts are approved.

## 8. Open Questions

- [ ] Confirm default-plus-per-scene model selection; draft recommendation supports both.
- [ ] Confirm scope and proposed stricter failure/audio/path policies before task decomposition.
- [ ] Implementation research gate: verify Omni URI auth and actual output duration on SDK 2.23.0.
- [ ] Implementation research gate: locate deployed owner/tenant access helpers and local artifact serving conventions.

No unanswered question is interpreted as approval. Next version must carry explicit user answers into the proposal and this section.

## 9. Design Research Cross-Check

Status: skipped — exploration remains under review and no independent-agent review was requested. No independent acceptance is claimed. SDK/doc contract checks are recorded in F005/F006. Review this draft before approval.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-17 | Codex | Draft from review and researched Omni/Veo proposal |
