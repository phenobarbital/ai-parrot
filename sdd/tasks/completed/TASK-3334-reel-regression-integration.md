# TASK-3334: Cross-module reel regression and storage coverage

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3333
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

## Context

Implements M9 integration of spec §3 and contributes to AC01, AC08, AC10, AC11, AC12, AC13, AC14, AC18. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Exercise real handler+JobManager queued execution with mocked provider adapters, through result polling and artifact retrieval.
- Repair stale historical reel/storage fixtures without replacing the production classes under test or weakening success/error assertions.
- Use actual local/temp storage and real descriptor serialization; mock only cloud transport/provider generation. Check durable paths versus URL strings.
- Run spec §4 and AC18 focused suites plus historical handler suite; confirm former 20 fixture errors are gone and map coverage to AC01-AC18.
- Record logs and remaining external-evidence gaps; do not report live readiness from mocked coverage.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_google_reel.py` | MODIFY | Align historical reel tests with real contracts |
| `packages/ai-parrot/tests/test_video_reel_storage.py` | MODIFY | Repair storage stubs and assert durable artifacts |
| `packages/ai-parrot-server/tests/handlers/test_video_reel_integration.py` | CREATE | POST to queued callback and polling integration |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_storage.py` | CREATE | Real local/temp and mocked cloud storage boundary |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google.generation import GoogleGeneration
from parrot.handlers.video_reel import VideoReelHandler
from parrot.handlers.jobs.job import JobManager
from parrot.tools.filemanager import FileManagerFactory
from parrot.interfaces.file import FileManagerInterface
from parrot.models.responses import AIMessage, AIMessageFactory
```

### Existing Signatures to Use

- **[STALE — corrected 2026-09-17 at TASK-3334 start]** `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:2107`: `async generate_video_reel(self, request: VideoReelRequest, output_directory: Optional[Path] = None, file_manager: Optional[FileManagerInterface] = None, user_id: Optional[str] = None, session_id: Optional[str] = None) -> AIMessage` — unchanged, still accurate. `_process_scene` is NOT the stale tuple-returning form this contract originally described (that predates TASK-3330's rewrite) — its VERIFIED current signature is `async def _process_scene(self, scene: VideoReelScene, index: int, *, context: "_ReelRunContext") -> "ReelSceneResult"` (generation.py:2493), a keyword-only `context` object, returning a typed `ReelSceneResult` (see `packages/ai-parrot/src/parrot/models/google.py`), never a tuple.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_video_reel`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._process_scene`.
- **[STALE `_parse_multipart` return type — corrected 2026-09-17]** `packages/ai-parrot-server/src/parrot/handlers/video_reel.py:62`: `VideoReelHandler(BaseView)`; `setup(cls, app, route='/api/v1/google/generation/video_reel')` now also registers `{route}/{job_id}/artifacts/{artifact_id}` (TASK-3333); `async _parse_multipart(self) -> tuple[dict, dict[int, Path]]` (index→path mapping, NOT a list — sparse indices preserved); `async post(self) -> web.Response`; `async get(self) -> web.Response` (dispatches to `_get_job_status` or, when an `artifact_id` route param is present, `_get_artifact`). New since TASK-3333: `_resolve_job_id`, `_authorize_job`, `_get_artifact`, `_get_session_user_id`, `_refresh_result_urls`, `_stream_file` — all owner-checked (§8 Q7); `job_manager.create_job(user_id=...)` uses the session identity, never a body-supplied `user_id`.
  Symbols: `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler._parse_multipart`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.post`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.get`.
- `packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:209`: async execute_job(self, job_id: str, execution_func: Callable[[], Awaitable[Any]]) -> None schedules _run_job; async get_job_async(self, job_id: str) -> Optional[Job]. _run_job awaits the callback before publishing completion/cancellation.
  Symbols: `sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.execute_job`, `sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.get_job_async`.
- `packages/ai-parrot/src/parrot/tools/filemanager.py:23`: FileManagerFactory.create(manager_type: Literal['fs', 'temp', 's3', 'gcs'], **kwargs) -> FileManagerInterface delegates to navigator; parrot.interfaces.file/__init__.py re-exports navigator.utils.file types.
  Symbols: `sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create`.
- `packages/ai-parrot/src/parrot/models/responses.py:75`: AIMessage.files: Optional[List[Path]]; metadata: Dict[str, Any]; artifacts: List[Dict[str, Any]]. AIMessageFactory.from_video(**kwargs) returns AIMessage(**kwargs).
  Symbols: `sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage`, `sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_video`.

### Dependency Interfaces

- Read the completed TASK-3333 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-server/tests/handlers/test_video_reel_integration.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_storage.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot/tests/test_google_reel.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_video_reel_storage.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_video_reel_integration.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_storage.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_video_reel",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._process_scene",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler._parse_multipart",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.get",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.execute_job",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.get_job_async",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_video"
  ]
}
```

## Implementation Notes

No application refactoring in this testing task. Report implementation defects to their owners with failing reproduction rather than expanding target scope.

May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3334-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Exercise real handler+JobManager queued execution with mocked provider adapters, through result polling and artifact retrieval.
- [ ] Repair stale historical reel/storage fixtures without replacing the production classes under test or weakening success/error assertions.
- [ ] Use actual local/temp storage and real descriptor serialization; mock only cloud transport/provider generation. Check durable paths versus URL strings.
- [ ] Run spec §4 and AC18 focused suites plus historical handler suite; confirm former 20 fixture errors are gone and map coverage to AC01-AC18.
- [ ] Record logs and remaining external-evidence gaps; do not report live readiness from mocked coverage.
- [ ] AC01, AC08, AC10, AC11, AC12, AC13, AC14, AC18 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Queued callback independently verifies effective models
- Successful/partial/failed/cancelled jobs with exact result JSON
- Local/temp and signed cloud artifact lifecycle; regressions retain existing behaviors

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot/tests/test_google_reel.py -q
pytest packages/ai-parrot/tests/test_video_reel_storage.py -q
pytest packages/ai-parrot-server/tests/handlers/test_video_reel_integration.py -q
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_storage.py -q
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

**Codebase Contract corrections (stale entries fixed before implementing)**: `_process_scene`'s
documented signature (`(self, scene, index, output_dir, aspect_ratio, file_manager=None,
job_prefix=None)` returning a `tuple`) predated TASK-3330's rewrite — verified and corrected in this
task file to the real, current `async def _process_scene(self, scene, index, *, context:
"_ReelRunContext") -> "ReelSceneResult"`. `_parse_multipart`'s documented return type
(`tuple[dict, list[Path]]`) was also stale — corrected to `tuple[dict, dict[int, Path]]` (sparse index
→ path mapping), and the `VideoReelHandler` entry was extended to note TASK-3333's new owner-checked
surface (`_resolve_job_id`/`_authorize_job`/`_get_artifact`/artifact route).

**Real handler+JobManager queued execution through polling and artifact retrieval**
(`test_video_reel_integration.py`, 6 tests): built a REAL `JobManager` (in-memory, no Redis) bound to a
real `web.Application`; `VideoReelHandler.post()` schedules a genuine `JobManager.execute_job()`
background `asyncio.Task`, awaited directly to completion in every test (never a sleep/poll loop) —
only `GoogleGenAIClient.generate_video_reel` (the provider call) is mocked, returning REAL
`AIMessage`/`ReelResult`/`ReelArtifact` Pydantic objects backed by a REAL local file on disk. Covers
all 4 terminal job states (successful, partial, failed, cancelled — Test Specification's explicit
list) with exact result-JSON assertions, real `job.result["metadata"]["video_reel"]`/`artifacts[]`
round-tripped through `model_dump(mode="json")` exactly as production stores it, real artifact-bytes
verification (`_stream_file`'s call args resolve to the actual on-disk file with the actual bytes),
the owner-boundary enforced end-to-end through the REAL queued path (not just a unit-level
`_authorize_job` call, which TASK-3333 already covers), and independent verification that the queued
callback's `generate_video_reel` call args (not the HTTP request echoed back) determine effective
models.

**Real local/temp storage boundary + mocked cloud transport** (`test_reel_storage.py`, 7 tests):
exercises `generate_video_reel`'s own `FileManagerFactory` dispatch (`file_manager=None` →
`request.storage_backend`) with REAL disk I/O for `"fs"`/`"temp"` — actual bytes written by a REAL
`LocalFileManager`/`TempFileManager`, read back and compared byte-for-byte, both the raw working-copy
(`AIMessage.files`) and the separately-persisted FileManager copy (at `storage_key`) verified as
distinct REAL files. `"s3"`/`"gcs"` dispatch through a MOCKED `FileManagerFactory.create` (verified
called with the request's own backend/config — the real DECISION logic — never a real network call or
cloud credential). Confirms `files == []` for cloud vs a real `Path` for local (AC10/AC18: "durable
paths versus URL strings"). Also covers the `file_manager=` explicit-override path (bypasses
`FileManagerFactory` entirely, regardless of `storage_backend`) and the no-`output_directory` default
path (`BASE_DIR/static/generated_reels` fallback — `BASE_DIR` patched to `tmp_path` for this one test
only, since the real repo-root `static/` directory is correctly read-only in this sandboxed worktree;
verified via `assemble_reel`'s captured `work_dir=` call arg rather than the mocked return path).

**Stale historical fixture repair — root-caused, not just patched around**: `test_video_reel_storage.py`'s
3 previously-failing tests (`TestFileManagerFactory::test_create_temp`/`test_create_invalid_raises`,
`TestHandlerStorageConfig::test_temp_backend`) were documented in earlier tasks' Completion Notes as
vague "navigator-api environment drift: FileManagerFactory returns LocalFileManager instead of
TempFileManager." Investigated properly this time (per this task's explicit scope) and found the REAL
root cause: this repo's ROOT `conftest.py` (and `packages/ai-parrot/tests/conftest.py`, redundantly)
unconditionally `sys.modules.setdefault("parrot.tools.filemanager", <fake module>)` at collection time
for EVERY test run in this repo, regardless of package — a compatibility shim for "navigator-api <
3.0.3" with no actual version/capability check. This environment's real navigator-api (confirmed via
direct, outside-pytest reproduction) fully supports `FileManagerFactory.create("temp")` →
`TempFileManager` correctly; the fake stub (whichever conftest.py's `setdefault` wins the race — always
the repo-root one) silently substitutes a synthetic `LocalFileManager`-shaped object for EVERY backend
request, masking the real behavior for any test asserting on the returned type. Root-caused via direct
reproduction (`hasattr(cached_module, "__file__")` distinguishes the synthetic `types.ModuleType` stub
from a real, file-backed module) — NOT fixed at its source (`conftest.py` is a shared, repo-wide file
outside this task's declared Files list; "Report implementation defects to their owners... rather than
expanding target scope" per this task's own Implementation Notes). Worked around, transparently
documented, entirely within the two owned test files: evict the poisoned `sys.modules` entry and
re-import the real module at file-import time, AND (for `generation.py`'s already-possibly-bound
reference, when another test file imported it first in the same pytest session) `patch(
"parrot.clients.google.generation.FileManagerFactory", <real class>)` directly for the affected
assertions. Neither production code nor the test's actual assertions were weakened — the REAL
`TempFileManager`/`LocalFileManager` classes are what's now genuinely exercised and asserted against
(AC: "without replacing the production classes under test or weakening success/error assertions").

**`test_google_reel.py`**: already correct (no changes needed) — confirmed via a fresh isolated run at
the start of this task; all 7 tests pass.

**Tests**: `test_video_reel_integration.py` — 6 passed. `test_reel_storage.py` — 7 passed.
`test_video_reel_storage.py` — 26 passed (0 pre-existing failures remain — the "former 20 fixture
errors are gone" and 3 MORE, previously mis-attributed-to-environment failures are now genuinely
fixed). `test_google_reel.py` — 7 passed. Full regression: `ai-parrot-client-google` — 206 passed.
`ai-parrot-server/tests/handlers/` — 583 passed, 4 skipped, 2 failed (`test_agent_a2ui_stream.py`,
confirmed unrelated — zero A2UI files in this feature's diff). `ai-parrot` reel-related files
(`test_google_reel`/`test_video_reel_storage`/`test_reel_contracts`/`test_video_reel_handler`) — 123
passed together.

**AC coverage mapping**: AC01 (model selection) — `test_video_reel_integration.py`'s
`test_queued_job_independently_reflects_effective_models`. AC08 (handler fixture repair) — already
satisfied by TASK-3332; this task's integration tests build on the SAME real-construction pattern.
AC10 (URL/path round-trip) — `test_reel_storage.py`'s durable-Path-vs-URL-string assertions +
`test_video_reel_integration.py`'s `model_dump(mode="json")` round-trip checks. AC11 (upload cleanup)
— unchanged, already covered by TASK-3332's `test_video_reel_inputs.py`. AC12 (resource cleanup /
deadlines) — unchanged, already covered by TASK-3331. AC13 (fail/skip policy) — unchanged, already
covered by TASK-3330's `test_reel_orchestration.py`. AC14 (owner-checked polling) —
`test_video_reel_integration.py`'s `test_second_owner_cannot_poll_first_owners_job`, exercising
TASK-3333's ownership boundary through the REAL queued-execution path end to end. AC18 (focused suites
+ lint) — all four commands from this task's Test Specification pass; `black`/`ruff` clean on all
touched/created files (only 6 pre-existing, untouched-line residual findings remain repo-wide, unchanged
from prior tasks).

**No live-service readiness claim**: all provider/cloud-transport calls are mocked throughout; Q3/Q4/
Q5/Q6 evidence gates (Omni URI auth, image model ID, Vertex Veo GA, Lyria api_version) remain open,
unresolved by this testing-only task, and are not claimed resolved.

`black --check`/`ruff check`: clean on all four touched/created files.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a · Tokens: n/a
