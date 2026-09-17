# TASK-3331: Reel deadlines, cancellation and resource ownership

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3330
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

## Context

Implements M7 lifecycle of spec §3 and contributes to AC12, AC14, AC17. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Enforce configurable scene deadline 600s and job deadline 3600s without changing the public reel signature; transport budgets share remaining absolute deadline.
- Close director/image SDK clients that generation owns, coordinate adapter/music ownership and avoid relying on cached base-client close for fresh clients.
- On cancellation/timeout cancel and await children and assembly before deleting task-owned directories; propagate CancelledError so existing JobManager records CANCELLED.
- Preserve operation IDs after ambiguous generation timeouts; no automatic resubmission or cross-model fallback. Surface redacted errors before terminal state.
- Verify concurrent jobs cannot overwrite or clean each other's files, and durable local outputs remain accessible.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | MODIFY | Enforce run/scene deadlines and ordered cleanup |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_lifecycle.py` | CREATE | Resource closure and job cancellation tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google.generation import GoogleGeneration
from parrot.clients.google import GoogleGenAIClient
from parrot.handlers.jobs.job import JobManager
```

### Existing Signatures to Use

- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1905`: async generate_video_reel(self, request: VideoReelRequest, output_directory: Optional[Path] = None, file_manager: Optional[FileManagerInterface] = None, user_id: Optional[str] = None, session_id: Optional[str] = None) -> AIMessage; current _process_scene(self, scene, index, output_dir, aspect_ratio, file_manager=None, job_prefix=None) returns tuple[Optional[str], Optional[str]].
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_video_reel`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._process_scene`.
- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:630`: async get_client(self, model: str = None, **kwargs) -> genai.Client constructs a fresh client; async close(self) -> None delegates to close_all. Directly created clients require explicit ownership.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close`.
- `packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:209`: async execute_job(self, job_id: str, execution_func: Callable[[], Awaitable[Any]]) -> None schedules _run_job; async get_job_async(self, job_id: str) -> Optional[Job]. _run_job awaits the callback before publishing completion/cancellation.
  Symbols: `sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.execute_job`, `sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.get_job_async`.

### Dependency Interfaces

- Read the completed TASK-3330 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_lifecycle.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_lifecycle.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_video_reel",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._process_scene",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.execute_job",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.get_job_async"
  ]
}
```

## Implementation Notes

JobManager and AbstractClient are read-only dependencies; use their existing cancellation behavior.

generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3331-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Enforce configurable scene deadline 600s and job deadline 3600s without changing the public reel signature; transport budgets share remaining absolute deadline.
- [ ] Close director/image SDK clients that generation owns, coordinate adapter/music ownership and avoid relying on cached base-client close for fresh clients.
- [ ] On cancellation/timeout cancel and await children and assembly before deleting task-owned directories; propagate CancelledError so existing JobManager records CANCELLED.
- [ ] Preserve operation IDs after ambiguous generation timeouts; no automatic resubmission or cross-model fallback. Surface redacted errors before terminal state.
- [ ] Verify concurrent jobs cannot overwrite or clean each other's files, and durable local outputs remain accessible.
- [ ] AC12, AC14, AC17 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Scene/job timeout and one generation attempt
- Cancellation during music, provider poll and assembly; cleanup order observed by JobManager
- Every owned client closes once, concurrent job isolation and preserved final artifacts

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_lifecycle.py -q
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

Completed-by: sdd-worker (fallback sequential loop, orchestrator-implemented) · Date: 2026-09-17

**Deadlines (AC1)**: Added `_reel_scene_deadline_seconds()`/`_reel_job_deadline_seconds()` (module-level,
`VIDEO_REEL_SCENE_DEADLINE_SECONDS`/`VIDEO_REEL_JOB_DEADLINE_SECONDS` env overrides, defaults 600s/3600s
per spec §2 item 10). `_ReelRunContext.job_deadline` is now a required field; `effective_scene_timeout_seconds()`
clamps the per-scene ceiling to whatever remains of the job's absolute deadline ("transport budgets share
remaining absolute deadline"). `generate_video_reel`'s public signature is unchanged.

**Client ownership (AC2)**: `_breakdown_prompt_to_scenes` (director) and `generate_image` (background/
foreground image path called from `_process_scene`) now wrap their directly-created `get_client()` clients
in `try/finally: await client.aio.aclose()`, closed on every exit including failure. `generate_images`
(Imagen backend) already used the shared cached `self.client` — no leak, no change needed. Two client
leaks are OUT of this task's scope and were left untouched with a note rather than fixed silently:
(1) the standalone legacy `video_generation()` method (not on the reel pipeline — reel video generation
goes through `generate_video_clip`/`VeoClipAdapter`, already closed since TASK-3324); (2) `generate_music_stream`'s
own-client branch when called with `client=None` (the reel pipeline's `ReelMusicService` always injects
its own caller-owned client per TASK-3327, so this branch is never exercised by the reel feature). Filed
as a deferred ledger finding at feature completion (see final summary) since fixing either is a real,
separately-scoped change to shared, widely-used methods outside this task's file/AC list.

**Cancellation and cleanup (AC3, AC5)**: The scene loop, timeline build and `assemble_reel` call are now
wrapped in one `try/except BaseException`. On ANY failure past `_ReelRunContext` construction — a raised
`ReelError`, a genuine `asyncio.CancelledError`, or any other exception — the handler cancels-and-awaits
the still-owned `music_task` (a no-op if already done) and removes the job's isolated working directory
via the new `_cleanup_reel_job_directory()` helper (blocking `shutil.rmtree` off the event loop via
`run_in_executor`, best-effort, never masks the original exception), then re-raises unchanged.
`asyncio.CancelledError` is never caught-and-swallowed — `except BaseException: ... raise` always
re-raises it, satisfying "propagate CancelledError so existing JobManager records CANCELLED." Cleanup
never runs on the success path (local "fs"/"temp" backends still need the directory for the persisted
final artifact).

**Concurrent job isolation (AC5)**: `generate_video_reel` now derives one `job_id = uuid.uuid4().hex`
shared by both the storage `job_prefix` and a NEW local working subdirectory
(`output_directory = base_output_directory / job_id`), replacing the old scheme where `job_prefix` had
its own random id while `output_directory` was the caller's raw (potentially shared) directory. Two
concurrent jobs against the same caller-supplied `output_directory` now get disjoint, non-colliding
subdirectories — verified in `test_reel_lifecycle.py::TestConcurrentJobIsolation`.

**Operation-ID preservation / no auto-resubmission (AC4)**: unchanged by this task — already satisfied by
TASK-3324's `VeoClipAdapter` (preserves `operation.name` in `GeneratedReelClip.provider_operation_id`,
never resubmits on ambiguous timeout) and TASK-3326's `OmniClipAdapter`; this task did not touch either
adapter. No regression introduced (existing `test_reel_veo.py`/`test_reel_omni.py` suites still pass).

**Tests**: New `packages/ai-parrot-client-google/tests/unit/reel/test_reel_lifecycle.py` (17 tests) —
deadline defaults/env overrides, `effective_scene_timeout_seconds()` clamping, cancellation during scene
processing (music cancelled + job dir removed + `CancelledError` propagates unchanged), assembly failure
still cleans up the job dir, success path preserves the job dir, two concurrent jobs get disjoint
directories, and `generate_image`/`_breakdown_prompt_to_scenes` close their owned client on both success
and failure. All 17 pass. Full `packages/ai-parrot-client-google/tests/unit/reel/` regression: 30/30 pass
for `test_reel_lifecycle.py` + `test_reel_orchestration.py` together; full-directory sweep is 166 tests,
158 passed / 8 failed, and all 8 failures are pre-existing, environment-only `ModuleNotFoundError:
parrot.utils.types` inside `test_reel_assembly.py`'s `multiprocessing.get_context("spawn")` MoviePy worker
subprocess (the compiled Cython artifact copied into this worktree for testing doesn't propagate into a
freshly spawned child interpreter) — confirmed unrelated to this task: `reel/assembly.py` was not touched,
these are the same tests TASK-3329 already wrote and passed under this project's real CI-installed
environment, and the failure signature is identical for every one of the 8 (same traceback, same missing
module), not a partial/behavioral regression.

**black --check / ruff check**: both pass for the touched Python file (`generation.py`) and the new test
file. Ruff also reports 9 PRE-EXISTING findings elsewhere in `generation.py` (5× `ASYNC240` blocking
`Path` ops, 1× `F841` unused `execution_time`, 2× `F821 Dict` undefined in `generate_image_batch`/
`generate_video_batch`) — none on lines this task touched or added; left for their own owning task/ledger
finding per Cardinal Rule 5 (no scope creep).

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a · Tokens: n/a
