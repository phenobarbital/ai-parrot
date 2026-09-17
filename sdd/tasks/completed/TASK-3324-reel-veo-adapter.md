# TASK-3324: Bounded Veo clip adapter and wire compatibility

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3323
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

## Context

Implements M3 of spec §3 and contributes to AC03, AC04, AC07, AC12, AC17. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Implement VeoClipAdapter(owner, poll_interval_seconds=10.0, max_read_retries=3) and the spec generate signature returning GeneratedReelClip.
- Create/close the stage client using the effective model. Submit once, poll/download under the original absolute deadline, and apply at most three bounded read retries.
- Use the resolved covering duration and lowercase person_generation including required constants. Omit generate_audio entirely for Developer API. Validate starting-frame media and generated video readability.
- Normalize immediate, operation and filtered-output failures. Keep operation ID on timeouts; never remove input or change models.
- Limit generation.py edits to the lowercase public-method fix, preserving its public signature and Veo 2 behavior.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/veo.py` | CREATE | Owned async Veo adapter |
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | MODIFY | Public video_generation lowercase wire fix only |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_veo.py` | CREATE | Submit/poll/download and wire tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google.generation import GoogleGeneration
from parrot.clients.google import GoogleGenAIClient
```

### Existing Signatures to Use

- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:844`: async video_generation(self, prompt, output_directory=None, model=GoogleModel.VEO_3_1, aspect_ratio=AspectRatio.RATIO_16_9, negative_prompt=None, number_of_videos=1, reference_image=None, generate_image_first=False, image_prompt=None, duration=8, resolution=None, person_generation='allow_adult', include_audio=True, last_frame=None, reference_images=None, reference_type='asset', extend_video=None, seed=None, user_id=None, session_id=None, **kwargs) -> AIMessage.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.video_generation`.
- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:630`: async get_client(self, model: str = None, **kwargs) -> genai.Client constructs a fresh client; async close(self) -> None delegates to close_all. Directly created clients require explicit ownership.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close`.

### Dependency Interfaces

- Read the completed TASK-3323 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/src/parrot/clients/google/reel/veo.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_veo.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/veo.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/generation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_veo.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.video_generation",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close"
  ]
}
```

## Implementation Notes

Do not modify the shared AbstractClient or import private SDK transport helpers into production. Verify SDK closing contract locally.

generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3324-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Implement VeoClipAdapter(owner, poll_interval_seconds=10.0, max_read_retries=3) and the spec generate signature returning GeneratedReelClip.
- [ ] Create/close the stage client using the effective model. Submit once, poll/download under the original absolute deadline, and apply at most three bounded read retries.
- [ ] Use the resolved covering duration and lowercase person_generation including required constants. Omit generate_audio entirely for Developer API. Validate starting-frame media and generated video readability.
- [ ] Normalize immediate, operation and filtered-output failures. Keep operation ID on timeouts; never remove input or change models.
- [ ] Limit generation.py edits to the lowercase public-method fix, preserving its public signature and Veo 2 behavior.
- [ ] AC03, AC04, AC07, AC12, AC17 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Actual SDK config serialization; lowercase modality values; explicit duration
- One submit on safety and ambiguous timeout; bounded read retries
- Empty output, operation error, download failure, close-on-cancel

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_veo.py -q
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

- `VeoClipAdapter(owner, poll_interval_seconds=10.0, max_read_retries=3)` with
  `generate(*, profile, prompt, output_directory, aspect_ratio, resolution, target_duration_seconds,
  starting_frame, deadline) -> GeneratedReelClip` exactly per §3 M3. Owns a fresh provider client via
  `owner.get_client(model=profile.model_id)` (no shared-client reuse across scenes).
- **Root cause of the documented F002/F009/F010 bug found and fixed**: `generation.py`'s
  `video_generation()` (the shared public method) did `person_generation.upper()` and forced
  `"ALLOW_ADULT"`/`"ALLOW_ALL"` — uppercase survives SDK serialization (per F008's probe log), which
  the API silently accepts differently than documented lowercase. Fixed to `.lower()` /
  `"allow_adult"`/`"allow_all"` — a 4-line diff, nothing else touched (verified via `git diff`);
  Veo 2 behavior and the public signature are unchanged. `test_google_reel.py` (pre-existing, not
  in this task's file list) re-run for regression — still 7 passed.
- Submit once: `generate_videos()` is called exactly once per `generate()` invocation, even on an
  immediate safety error or an ambiguous timeout (verified via `assert_awaited_once()` in every
  failure-path test) — the adapter never resubmits generation.
- Poll/download share the caller's original absolute `deadline`; at most `max_read_retries` bounded
  retries apply ONLY to transient `operations.get`/`files.download` reads (`_read_with_retries`),
  never to submission. `asyncio.CancelledError` during a read is never retried or converted — it
  propagates on the first occurrence.
- Duration/person_generation: uses `select_generation_duration()` (TASK-3323) for the covering
  duration and a lowercase `_resolve_person_generation()` (`"allow_adult"` with a starting frame,
  `"allow_all"` without, falling back to the profile's first legal value if neither is registered).
  `generate_audio` is never set on `GenerateVideosConfig` — verified via
  `config.generate_audio is None` against the REAL `google.genai.types.GenerateVideosConfig`.
- Failure normalization: immediate SDK errors, `operation.error`, and empty/RAI-filtered output all
  go through `classify_provider_error()`; a structured RAI signal maps to `SAFETY_BLOCKED`, empty
  output without one maps to `PROVIDER_FAILURE`. `operation_id` (the LRO's `.name`) is preserved on
  every raised error once an operation exists — verified for the operation-error and ambiguous-
  timeout paths specifically (AC17: reconciliation, never resubmission).
- Media validation: starting-frame image is verified readable (`PIL.Image.verify()`) BEFORE any
  submission (an unreadable frame never reaches `generate_videos` — verified via
  `gen.assert_not_awaited()`); the downloaded clip's real duration/audio-track presence is measured
  via `moviepy.VideoFileClip` in an executor (never trusted from the request/config), an unreadable
  downloaded clip raises `MEDIA_INVALID`.
- **Lint findings during self-review, fixed before commit**: `ASYNC240` (blocking `Path.mkdir`/
  `write_bytes` in an async function — moved into a `_write_clip` static helper run via
  `run_in_executor`) and `B023` (a polling closure captured the loop variable `operation` by
  reference — fixed with an explicit `op=operation` default-argument binding). Both caught by
  `ruff check`, not by the tests (tests use mocks that don't exercise real blocking I/O timing or
  closure staleness) — flagging since this is exactly the kind of defect these two rules exist to
  catch and is worth remembering for the remaining reel modules.
- AC03, AC04, AC07, AC12, AC17 (owned by this task): covered by the 14 tests in
  `test_reel_veo.py` (wire config serialization incl. real `GenerateVideosConfig`, single-submit on
  safety/timeout, operation-id preservation, bounded read retries succeeding/exhausting,
  cancellation non-retry, media measurement/validation for both starting frame and output).
- Tests: `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_veo.py -q` — 14 passed
  (7.2s — includes real `asyncio.sleep` calls in retry/poll tests with small intervals, not mocked
  out, since verifying actual bounded-retry *timing* was in scope). Full `tests/unit/reel/`
  directory — 87 passed. `test_google_reel.py` regression — 7 passed. Same temporary main-checkout
  `.so` copy-then-remove as prior tasks; nothing committed.
- Lint: `ruff check` — all checks passed on all three touched files (pre-existing, unrelated
  findings at `generation.py:1951/2456/2497`, `ASYNC240`/`F821`, are far outside this task's 4-line
  diff — confirmed via `git diff` — and left for `/sdd-done`'s feature-wide style pass). `black
  --line-length 120` reformatted `veo.py`/`test_reel_veo.py` (wrapping only); re-ran both suites
  after reformatting — still 87/7 passed.
- No live-service claims inferred from mocks; no default test performs a paid provider call. No
  files outside the task's three listed targets were created or modified.

### Addendum (2026-09-17, same session, discovered while implementing TASK-3326)

**Self-caught defect, fixed via `fix(video-reel-omni-veo-reliability): TASK-3324 review fix —
close the owned async Veo client on every exit`**: the initial delivery above called
`await self._owner.get_client(model=profile.model_id)` but never closed the returned client.
`GoogleGenAIClient.get_client()`'s own docstring says "Directly created clients require explicit
ownership" — confirmed via source inspection that `get_client()` builds a genuinely fresh
`genai.Client` on every call (no caching), and that `genai.Client.close()` is sync and only closes
the SYNC surface — the async surface this adapter actually uses (`client.aio.*`) requires
`await client.aio.aclose()` instead (verified via `inspect.getsource`/`inspect.signature` on the
installed `google-genai` package). Fixed by wrapping submit→poll→download in a
`try/finally: await client.aio.aclose()`, so the client closes on success, every classified
failure, AND cancellation. Added `client.aio.aclose.assert_awaited_once()` to the success,
immediate-safety-block, and cancellation tests (3 of the 14) — re-ran the full `test_reel_veo.py`
(14 passed) and `tests/unit/reel/` (107 passed) after the fix. This directly satisfies this task's
own Acceptance Criterion "Create/close the stage client using the effective model" (§2), which the
original delivery missed for the "close" half.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a (fallback, not MCP/native-agent timed) · Tokens: n/a
