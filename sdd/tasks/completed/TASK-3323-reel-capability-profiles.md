# TASK-3323: API-specific video profiles and generated clip record

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3321, TASK-3322
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

## Context

Implements M2 profiles of spec §3 and contributes to AC03, AC04, AC06, AC17. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Implement spec VideoModelProfile, VideoProfileRegistry.default/resolve/default_video_model/validate_scene and select_generation_duration; use exact API/model keys.
- Developer entries: Veo standard/Fast/Lite preview and gemini-omni-1.1-flash. Vertex GA entries remain disabled pending Q5. Unknown/wrong-surface/disabled models fail explicitly.
- Keep starting-frame and asset-reference capabilities distinct; Lite never gains 4k/reference guidance. Apply deployment person-generation constraints without inferring region from the caller.
- Select smallest legal duration covering 4/5/6/8 targets after resolution constraints; Omni returns None. Create GeneratedReelClip with local path, model, backend, submitted/measured duration, audio flag and operation ID.
- Treat adding a future model as a verified entry plus tests, not substring matching.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py` | CREATE | Exact API/model profiles and duration selection |
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/clip.py` | CREATE | GeneratedReelClip model |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_profiles.py` | CREATE | Capability and covering-duration tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.models.google import VideoReelRequest, VideoReelScene
from parrot.clients.google.generation import GoogleGeneration
from parrot.clients.google import GoogleGenAIClient
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/models/google.py:376`: VideoReelScene.duration: float = 5.0; VideoReelRequest._parse_json_strings(cls, v) is a before validator for scenes/speech.
  Symbols: `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene`, `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest`.
- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:844`: async video_generation(self, prompt, output_directory=None, model=GoogleModel.VEO_3_1, aspect_ratio=AspectRatio.RATIO_16_9, negative_prompt=None, number_of_videos=1, reference_image=None, generate_image_first=False, image_prompt=None, duration=8, resolution=None, person_generation='allow_adult', include_audio=True, last_frame=None, reference_images=None, reference_type='asset', extend_video=None, seed=None, user_id=None, session_id=None, **kwargs) -> AIMessage.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.video_generation`.
- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:630`: async get_client(self, model: str = None, **kwargs) -> genai.Client constructs a fresh client; async close(self) -> None delegates to close_all. Directly created clients require explicit ownership.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close`.

### Dependency Interfaces

- Read the completed TASK-3321 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.
- Read the completed TASK-3322 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/src/parrot/clients/google/reel/clip.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_profiles.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/profiles.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/clip.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_profiles.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.video_generation",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close"
  ]
}
```

## Implementation Notes

Q5 remains an enablement gate. No Vertex live calls or blanket claims of Developer/Vertex equivalence.

May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3323-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Implement spec VideoModelProfile, VideoProfileRegistry.default/resolve/default_video_model/validate_scene and select_generation_duration; use exact API/model keys.
- [ ] Developer entries: Veo standard/Fast/Lite preview and gemini-omni-1.1-flash. Vertex GA entries remain disabled pending Q5. Unknown/wrong-surface/disabled models fail explicitly.
- [ ] Keep starting-frame and asset-reference capabilities distinct; Lite never gains 4k/reference guidance. Apply deployment person-generation constraints without inferring region from the caller.
- [ ] Select smallest legal duration covering 4/5/6/8 targets after resolution constraints; Omni returns None. Create GeneratedReelClip with local path, model, backend, submitted/measured duration, audio flag and operation ID.
- [ ] Treat adding a future model as a verified entry plus tests, not substring matching.
- [ ] AC03, AC04, AC06, AC17 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- All initial IDs and wrong-surface/disabled/unknown rejection
- 5 -> 6 at permitted 720p; high resolution -> 8; Omni None
- Lite option exclusions, lowercase person constraints and actual clip serialization

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_profiles.py -q
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

Completed 2026-09-17 by sdd-worker orchestrator (fallback sequential loop, sonnet).

- `VideoModelProfile` (Pydantic v2) with all spec-listed fields.
  `VideoProfileRegistry.default()` registers exactly: Developer API
  `veo-3.1-generate-preview`/`veo-3.1-fast-generate-preview`/`veo-3.1-lite-generate-preview`
  (enabled) + `gemini-omni-1.1-flash` (enabled, backend=omni), and Vertex GA
  `veo-3.1-generate-001`/`veo-3.1-fast-generate-001` (`enabled=False`, pending spec §8 Q5).
  `resolve()` distinguishes `unknown_model` (no entry on any surface) from `wrong_api_surface`
  (entry exists, wrong surface) from `model_disabled` (entry exists, this surface, not enabled) —
  keyed by exact `(surface, model_id)`, never `"veo-3" in model_id`-style substring matching
  (explicit test `test_no_substring_matching`). `validate_scene()` checks resolution membership,
  starting-frame support and native-audio support, always raising `ReelValidationError` rather than
  silently dropping an option. `default_video_model()` returns the standard Veo 3.1 id per surface.
- `select_generation_duration()`: smallest legal duration ≥ target after applying the profile's
  `resolution_min_duration` floor; `None` for Omni (no user-selectable duration — never an invented
  enum). Standard/Fast: `durations_seconds=[4,6,8]`, `resolution_min_duration={"1080p":8,"4k":8}`.
  Lite: same durations, `resolutions=["720p","1080p"]` (no 4k), same 1080p floor,
  `supports_reference_guidance=False` — the two capabilities the task scope explicitly excludes for
  Lite. 720p 4/5/6/8s targets → 4/6/6/8 (AC04's four cases); 1080p/4k always → 8 regardless of a
  lower target.
- **Design decisions needing reviewer attention (no exact capability data in spec/task, only the
  interface skeleton + example)**:
  1. Concrete `durations_seconds=[4,6,8]` for Veo 3.1 — inferred from the spec's own worked example
     ("a 5 s target ... submits 6 s; a profile that requires 8 s submits 8 s") and the test names
     `test_select_duration_4_5_6_8`; not independently re-verified against live Veo docs beyond
     F008's citation (`https://ai.google.dev/gemini-api/docs/veo`, model-ID level only).
  2. `native_audio`: Standard/Fast/Lite = `"controllable"`, Omni = `"always"`. Not directly cited by
     any F00x finding; Omni's "always" follows from M4 scope's "No Veo config" (no audio toggle
     exposed) plus the Interactions API always returning `VideoContent`.
  3. `person_generation_values=["allow_adult","allow_all","dont_allow"]` for Veo, `[]` for Omni
     (M4 scope: "No Veo config ... for Omni").
  4. Omni's `resolutions=[]`/`resolution_min_duration={}` signal "not user-selectable"; `validate_scene`
     skips the resolution-membership check when `profile.resolutions` is empty (Omni's case), since
     the spec explicitly says not to invent a resolution enum for it either.
  **These four should be independently verified against live Veo/Omni docs before any of this
  becomes a paid-call default** — flagging per "No live-service readiness claim is inferred from
  mocks; unresolved deployment gates are documented."
- `GeneratedReelClip` (`reel/clip.py`): local_path/model/backend/submitted+measured
  duration/has_audio/provider_operation_id exactly per spec §2 Data Models skeleton; JSON-mode
  serialization verified (Path → str).
- AC03, AC04, AC06, AC17 (owned by this task): covered by the 30 tests in `test_reel_profiles.py`
  (developer preview IDs, disabled Vertex, unknown/wrong-surface/disabled rejection, no-substring
  matching, Lite 4k/reference-guidance exclusion, lowercase person_generation values, 4/5/6/8s
  duration selection, high-resolution-forces-8, Omni-always-None, pathological
  no-legal-duration/no-native-audio rejection paths, `GeneratedReelClip` round-trip).
- Tests: `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_profiles.py -q` — 30
  passed. Full `tests/unit/reel/` directory (TASK-3322 + TASK-3323 together) — 55 passed. Same
  temporary main-checkout `.so` copy-then-remove as prior tasks; nothing committed.
- Lint: `ruff check` — all checks passed. `black --line-length 120` — no changes needed.
- No live-service claims inferred from mocks; no default test performs a paid provider call. No
  files outside the task's three listed targets were created or modified.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a (fallback, not MCP/native-agent timed) · Tokens: n/a
