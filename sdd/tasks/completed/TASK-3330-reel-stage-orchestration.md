# TASK-3330: Stage routing, scene policies and typed reel output

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3326, TASK-3329
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

## Context

Implements M7 routing of spec §3 and contributes to AC01, AC02, AC03, AC04, AC06, AC10, AC13, AC17. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Preserve generate_video_reel's public signature; add generate_video_clip dispatcher and model parameter to _breakdown_prompt_to_scenes.
- Resolve Q4 image-model ID against deployment support without silently substituting a different ID. Forward director/image/video choices and report unused director when scenes are supplied.
- Validate request-known profiles before director work; validate director-produced scenes before image/video generation. Keep the director cost boundary explicit rather than promising impossible validation of nonexistent scenes.
- Build stage/run context and per-scene generated data; preserve speech precedence and sparse upload correspondence. Replace tuple/None failure handling with typed results and remove the text-to-video safety retry.
- Apply fail/skip with original scene indices, all-failed error and music off/optional/required semantics. Persist through FileManager and emit JSON ReelResult metadata and dict artifacts; files contains durable local paths only.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | MODIFY | Route all reel stages through resolved contracts |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py` | CREATE | Routing, policies and output tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google.generation import GoogleGeneration
from parrot.models.google import VideoReelRequest, VideoReelScene
from parrot.models.responses import AIMessage, AIMessageFactory
from parrot.tools.filemanager import FileManagerFactory
from parrot.interfaces.file import FileManagerInterface
```

### Existing Signatures to Use

- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1905`: async generate_video_reel(self, request: VideoReelRequest, output_directory: Optional[Path] = None, file_manager: Optional[FileManagerInterface] = None, user_id: Optional[str] = None, session_id: Optional[str] = None) -> AIMessage; current _process_scene(self, scene, index, output_dir, aspect_ratio, file_manager=None, job_prefix=None) returns tuple[Optional[str], Optional[str]].
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_video_reel`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._process_scene`.
- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1524`: async generate_image(self, prompt, model=None, reference_images=None, google_search=False, aspect_ratio=None, resolution=None, number_of_images=None, negative_prompt=None, person_generation=None, safety_filter_level=None, seed=None, add_watermark=None, output_mime_type=None, service_tier=None, temperature=None, prompt_instruction=None, output_directory=None, as_base64=False, user_id=None, session_id=None, stateless=True, history=None, **kwargs) -> AIMessage; async _breakdown_prompt_to_scenes(self, prompt: str) -> List[VideoReelScene].
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_image`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._breakdown_prompt_to_scenes`.
- `packages/ai-parrot/src/parrot/models/google.py:376`: VideoReelScene.duration: float = 5.0; VideoReelRequest._parse_json_strings(cls, v) is a before validator for scenes/speech.
  Symbols: `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene`, `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest`.
- `packages/ai-parrot/src/parrot/models/responses.py:75`: AIMessage.files: Optional[List[Path]]; metadata: Dict[str, Any]; artifacts: List[Dict[str, Any]]. AIMessageFactory.from_video(**kwargs) returns AIMessage(**kwargs).
  Symbols: `sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage`, `sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_video`.
- `packages/ai-parrot/src/parrot/tools/filemanager.py:23`: FileManagerFactory.create(manager_type: Literal['fs', 'temp', 's3', 'gcs'], **kwargs) -> FileManagerInterface delegates to navigator; parrot.interfaces.file/__init__.py re-exports navigator.utils.file types.
  Symbols: `sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create`.

### Dependency Interfaces

- Read the completed TASK-3326 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.
- Read the completed TASK-3329 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py` does not exist at task creation; create it within this task.
- The new reel adapters/registry/results are proposed interfaces; import them only after their owning dependencies complete.
- No verified owner/tenant helper or Omni authenticated-download shortcut is supplied by this contract. Resolve the spec's evidence gates before relying on such interfaces.
- No public Omni enum member is required; the registry uses exact strings.
- `parrot/interfaces/file.py` is not a file. Existing file-manager imports are re-exported through `packages/ai-parrot/src/parrot/interfaces/file/__init__.py`.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/generation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_video_reel",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._process_scene",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_image",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._breakdown_prompt_to_scenes",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_video",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create"
  ]
}
```

## Implementation Notes

Q4 requires verification; do not alter provider enum values or AbstractClient. Do not modify adapter internals owned by prerequisite tasks.

generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3330-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Preserve generate_video_reel's public signature; add generate_video_clip dispatcher and model parameter to _breakdown_prompt_to_scenes.
- [ ] Resolve Q4 image-model ID against deployment support without silently substituting a different ID. Forward director/image/video choices and report unused director when scenes are supplied.
- [ ] Validate request-known profiles before director work; validate director-produced scenes before image/video generation. Keep the director cost boundary explicit rather than promising impossible validation of nonexistent scenes.
- [ ] Build stage/run context and per-scene generated data; preserve speech precedence and sparse upload correspondence. Replace tuple/None failure handling with typed results and remove the text-to-video safety retry.
- [ ] Apply fail/skip with original scene indices, all-failed error and music off/optional/required semantics. Persist through FileManager and emit JSON ReelResult metadata and dict artifacts; files contains durable local paths only.
- [ ] AC01, AC02, AC03, AC04, AC06, AC10, AC13, AC17 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Actual arguments for director and both image calls; mixed Veo/Omni dispatch
- Legacy alias warnings, director unused and explicit per-scene precedence
- Fail/skip/all-failed, sparse slots, exact URL serialization and local/cloud files

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py -q
```

Test names and assertions must describe observable behavior, not mirror private implementation branches. No default test may consume paid provider calls.

## Agent Instructions

1. Read `sdd/specs/video-reel-omni-veo-reliability.spec.md`, this contract, and repository instructions.
2. Confirm Depends-on tasks are done in `sdd/tasks/index/video-reel-omni-veo-reliability.json`; refresh contracts after dependency changes.
3. Mark this task in-progress in that per-spec index and assign the current session.
4. Implement scoped targets only, resolving evidence gates before dependent work.
5. Verify criteria and record tests/logs plus any deviations.
6. Move the task to sdd/tasks/completed and update its per-spec index entry to done with completion metadata.
7. Commit code and task state according to sdd-start. Do not edit the historical monolithic index.

## Completion Note

Completed 2026-09-17 by sdd-worker orchestrator (fallback sequential loop, sonnet). The largest
task in this feature — a full rewrite of `generate_video_reel`/`_process_scene`/
`_breakdown_prompt_to_scenes` plus two new methods.

- `generate_video_reel`'s public signature is byte-for-byte unchanged (verified: same 5 params,
  same `-> AIMessage` return). New `generate_video_clip(*, prompt, model, output_directory,
  aspect_ratio, resolution, target_duration_seconds, starting_frame=None, audio_mode="separate",
  timeout_seconds=600.0) -> GeneratedReelClip` dispatcher: resolves `model` via
  `VideoProfileRegistry.resolve()`+`validate_scene()`, then routes to `VeoClipAdapter` or
  `OmniClipAdapter` by `profile.backend` — exactly per spec §3 M7. `_breakdown_prompt_to_scenes`
  gained a required `model` parameter (was hardcoded `GoogleModel.GEMINI_2_5_FLASH`); called with
  `request.effective_director_model()`.
- **Q4 resolution ("image-model ID against deployment support without silently substituting")**:
  `request.image_model` is now passed EXPLICITLY as `model=` to BOTH `generate_image()` calls
  (background AND foreground) in `_process_scene` — the legacy code never passed `model=` at all,
  relying on `generate_image`'s own internal default. An invalid/unsupported id now surfaces as a
  genuine provider error from the real call, never silently remapped to a different id — there is
  no image-model registry in this feature (only video), so "no silent substitution" is satisfied by
  simple explicit passthrough, not a new validation layer.
- **Profile validation timing** (`_validate_known_video_profiles`, called twice): once BEFORE any
  director work (validates `request.video_model` + any caller-SUPPLIED `scenes[].video_model` —
  these are "known" upfront), and again immediately after the director produces scenes (now THEIR
  overrides are "known" too) — but never for scenes that don't exist yet. This is "the director
  cost boundary explicit": the director call itself is unavoidable, but nothing downstream (image/
  video generation) runs before its OUTPUT is validated. Verified by
  `test_unknown_reel_video_model_rejected_before_director_work` (director never called) and
  `test_unknown_known_scene_video_model_rejected_before_director_work`.
- `_process_scene(scene, index, *, context: _ReelRunContext) -> ReelSceneResult` — the legacy
  `tuple[Optional[str], Optional[str]]` return and `file_manager=`/`job_prefix=` params are GONE
  (replaced by one `context` object — a new internal, non-public `_ReelRunContext` class bundling
  request/registry/api_surface/output_directory/scene_deadline_seconds plus mutable
  `clips`/`narration_paths`/`narration_durations` dicts the caller reads back for timeline
  planning, since `ReelSceneResult`'s typed shape has no room for a local `Path`). The legacy
  text-to-video safety-block retry (catching `RuntimeError` on `"content safety filter"` and
  resubmitting without the reference image) is REMOVED ENTIRELY — `generate_video_clip`'s adapters
  never resubmit after a safety block (TASK-3324/3326's own guarantee).
- **Policy semantics**: `_process_scene` ALWAYS raises `ReelError` on failure (never catches
  internally) — `generate_video_reel`'s per-scene loop applies fail/skip: `"fail"` re-raises
  immediately (after cancelling+joining the in-flight music task); `"skip"` catches it, builds a
  synthetic failed `ReelSceneResult` via `_failed_scene_result` (preserving the ORIGINAL index,
  `error_code`/`error_message` from the exception), and continues. If every scene ends up
  `status="failed"`, the job ALWAYS fails regardless of policy (spec AC13). Verified: original
  indices preserved under skip (`{0: succeeded, 1: failed, 2: succeeded}`), fail-policy aborts on
  scene 0's failure, all-failed raises even under skip.
- Sparse reference-image correspondence now goes through `request.image_for_scene(i)` (TASK-3321's
  accessor) instead of a raw `reference_images[i]` list-index loop — functionally equivalent for
  the existing test cases (a hole still yields `None`), but now uses the properly-encapsulated,
  index-preserving accessor the model provides specifically for this purpose.
- Speech precedence (request.speech overrides scene.narration_text, or clears it) is UNCHANGED
  logic, just re-verified against the new pipeline.
- Timeline/assembly: builds ONE explicit `TimelinePlan` (TASK-3328) from SUCCEEDED scenes only
  (original indices preserved via `TimelineEntry.scene_index`), calling
  `check_measured_duration(scene.duration, clip.measured_duration_seconds, fps=24.0)` per scene
  (AC04's "insufficient_duration" gate) and `check_narration_fits` when a narration clip's own
  measured duration (via a new `_measure_audio_duration` helper, moviepy-based, never trusted from
  the request) is available. `assemble_reel()` (TASK-3329) is called DIRECTLY with
  `request.audio_mode` and `request.output_format` forwarded exactly — bypassing the legacy
  `_create_reel_assembly`/`_generate_reel_music` wrappers entirely for this NEW orchestration path
  (those two methods are left UNTOUCHED, still used by the old call site TASK-3329 delegated
  internally, but `generate_video_reel` no longer calls them). Music is generated via
  `ReelMusicService` (TASK-3327), an isolated owned client, per `music_policy`/`audio_mode`.
- Output: `AIMessage.metadata["video_reel"] = ReelResult.model_dump(mode="json")`,
  `AIMessage.artifacts = [ReelArtifact.model_dump(mode="json")]` (single final artifact, uploaded
  via FileManager — the ONLY artifact persisted through FileManager in the new flow; intermediates
  stay local-only, matching TASK-3329's design), `AIMessage.files` holds the real local assembled
  path for `fs`/`temp` backends, empty list for `s3`/`gcs` (spec §2 item 8, verified by
  `test_local_backend_files_contains_local_path...`/`test_cloud_backend_files_is_empty`).
  `sdk_version` reads `google.genai.__version__` (installed-package fact, not a live-surface claim).
- **Deviations — two files outside this task's list were touched**, for the SAME underlying reason
  as TASK-3329's deviation (a task-MANDATED architecture change breaking tests that hard-coded the
  REMOVED internal shape, not this task choosing to touch unrelated code):
  1. `packages/ai-parrot/tests/test_google_reel.py` (7 tests) — **rewritten, not deleted**. Every
     test mocked `video_generation`/`_create_reel_assembly`/`_generate_reel_music` directly and
     asserted the legacy tuple-return/single-arg-breakdown shape; since ALL of that is explicitly
     REMOVED by this task's own Acceptance Criteria, every test failed unconditionally regardless
     of implementation quality. Rewrote each test to mock the NEW surface
     (`generate_video_clip`/`ReelMusicService.generate`/`reel.assembly.assemble_reel`) while
     preserving each test's ORIGINAL INTENT exactly (reference-image assignment incl. sparse
     holes, narration-absent-clears-text, `_process_scene`'s reference-image passthrough) — same
     philosophy as testing observable behavior, not private implementation, per this repo's own
     test-writing guidance.
  2. `packages/ai-parrot/tests/test_video_reel_storage.py` — 2 of its tests
     (`TestPipelineFileManagerInit::test_process_scene_signature`/`test_process_scene_returns_strings`)
     literally asserted `_process_scene`'s OLD parameter names (`file_manager`/`job_prefix`) and OLD
     return-annotation shape (`"str" in str(ret)`) via `inspect.signature`. Updated both to assert
     the NEW contract (`context` param present, `file_manager`/`job_prefix` ABSENT; return
     annotation contains `"ReelSceneResult"`) — same fix pattern as this task's TASK-3329
     predecessor. Confirmed the file's OTHER 3 failures
     (`TestFileManagerFactory::test_create_temp`/`test_create_invalid_raises`,
     `TestHandlerStorageConfig::test_temp_backend`) are the SAME pre-existing, unrelated
     `navigator-api`/`FileManagerFactory` environment drift already documented in TASK-3329's
     Completion Note — left as-is.
- AC01, AC02, AC03, AC04, AC06, AC10, AC13, AC17 (owned by this task): covered by the 13 tests in
  the new `test_reel_orchestration.py` (director-unused/used + model-forwarding, legacy-alias
  deprecation-warning propagation into `ReelResult.warnings`, image_model explicit passthrough to
  both image calls, mixed Veo/Omni dispatch by scene override, profile validation BEFORE director
  work for both reel-level and caller-supplied-scene overrides, fail/skip/all-failed policies with
  original-index preservation, local-vs-cloud `files` handling, exact `download_url`
  string-preservation through JSON-mode serialization) plus the 7 rewritten tests in
  `test_google_reel.py` (reference-image sparse-slot assignment, `_process_scene`'s direct
  reference-image passthrough, narration-precedence clearing).
- Tests: `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py -q` —
  13 passed. Full `tests/unit/reel/` directory — 166 passed. `test_google_reel.py` — 7 passed.
  `test_video_reel_storage.py` — 22 passed, 1 skipped, 3 pre-existing unrelated failures (see
  deviation note). `test_video_reel_handler.py` — 33 passed (unaffected, confirms no cross-module
  regression). Same temporary main-checkout `.so` copy-then-remove as prior tasks; nothing
  committed.
- Lint: `ruff check` found two real issues in my diff — both `F821` (undefined name) on
  `GeneratedReelClip`/`ReelError` used as forward-ref type-hint strings without ever being
  imported — fixed via a new `if TYPE_CHECKING:` guarded import block (never imported at runtime,
  matching the lazy-provider-import convention). All other findings (`ASYNC240` at 7 pre-existing
  unrelated call sites, `F821 Dict` ×2, `F841 execution_time` in the unrelated `generate_image`
  method) confirmed pre-existing via direct line-content inspection before/after my diff — left for
  `/sdd-done`'s feature-wide pass. `black --line-length 120` reformatted `generation.py`/
  `test_reel_orchestration.py` (wrapping only); re-ran the full regression sweep after
  reformatting — still 166/7/22/33 passed.
- No live-service claims inferred from mocks; no default test performs a paid provider call.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a (fallback, not MCP/native-agent timed) · Tokens: n/a
