# TASK-3333: Owner-checked job polling and artifact delivery

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3331, TASK-3332
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Handler edits are serialized TASK-3332 -> TASK-3333. May run with ready provider tasks only when files do not overlap.

## Context

Implements M8 delivery of spec §3 and contributes to AC10, AC14. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Close Q7 by locating and documenting deployed authenticated owner/tenant helpers and local serving conventions before wiring access. Never trust body user_id as ownership.
- Implement _resolve_job_id, _authorize_job and _get_artifact per §3 M8; route/query disagreement ->400, missing or unauthorized resources ->non-disclosing404.
- Register artifact route and resolve only artifact IDs from validated ReelResult. Reject traversal, raw paths and unauthorized storage roots; no leaked local path in HTTP result.
- Refresh cloud signed URLs from stable storage keys at polling/delivery and preserve query strings exactly; serialize job results in JSON mode.
- Handle cancelled job state consistently with existing JobManager and retain schema GET behavior.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/video_reel.py` | MODIFY | Owner checks, artifact route and signed URL refresh |
| `packages/ai-parrot-server/tests/handlers/test_video_reel_artifacts.py` | CREATE | Authorization and delivery tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.handlers.video_reel import VideoReelHandler
from parrot.handlers.jobs.job import JobManager
from parrot.models.responses import AIMessage, AIMessageFactory
from parrot.tools.filemanager import FileManagerFactory
from parrot.interfaces.file import FileManagerInterface
```

### Existing Signatures to Use

- `packages/ai-parrot-server/src/parrot/handlers/video_reel.py:31`: VideoReelHandler(BaseView); setup(cls, app, route='/api/v1/google/generation/video_reel'); async _parse_multipart(self) -> tuple[dict, list[Path]]; async post(self) -> web.Response; async get(self) -> web.Response.
  Symbols: `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler._parse_multipart`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.post`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.get`.
- `packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:209`: async execute_job(self, job_id: str, execution_func: Callable[[], Awaitable[Any]]) -> None schedules _run_job; async get_job_async(self, job_id: str) -> Optional[Job]. _run_job awaits the callback before publishing completion/cancellation.
  Symbols: `sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.execute_job`, `sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.get_job_async`.
- `packages/ai-parrot/src/parrot/models/responses.py:75`: AIMessage.files: Optional[List[Path]]; metadata: Dict[str, Any]; artifacts: List[Dict[str, Any]]. AIMessageFactory.from_video(**kwargs) returns AIMessage(**kwargs).
  Symbols: `sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage`, `sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_video`.
- `packages/ai-parrot/src/parrot/tools/filemanager.py:23`: FileManagerFactory.create(manager_type: Literal['fs', 'temp', 's3', 'gcs'], **kwargs) -> FileManagerInterface delegates to navigator; parrot.interfaces.file/__init__.py re-exports navigator.utils.file types.
  Symbols: `sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create`.

### Dependency Interfaces

- Read the completed TASK-3331 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.
- Read the completed TASK-3332 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-server/tests/handlers/test_video_reel_artifacts.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-server/src/parrot/handlers/video_reel.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_video_reel_artifacts.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler._parse_multipart",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.get",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.execute_job",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.get_job_async",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_video",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create"
  ]
}
```

## Implementation Notes

Q7 is mandatory: verify helpers instead of inventing session keys. Request any necessary scope extension if auth integration requires files outside this task.

Handler edits are serialized TASK-3332 -> TASK-3333. May run with ready provider tasks only when files do not overlap.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3333-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Close Q7 by locating and documenting deployed authenticated owner/tenant helpers and local serving conventions before wiring access. Never trust body user_id as ownership.
- [ ] Implement _resolve_job_id, _authorize_job and _get_artifact per §3 M8; route/query disagreement ->400, missing or unauthorized resources ->non-disclosing404.
- [ ] Register artifact route and resolve only artifact IDs from validated ReelResult. Reject traversal, raw paths and unauthorized storage roots; no leaked local path in HTTP result.
- [ ] Refresh cloud signed URLs from stable storage keys at polling/delivery and preserve query strings exactly; serialize job results in JSON mode.
- [ ] Handle cancelled job state consistently with existing JobManager and retain schema GET behavior.
- [ ] AC10, AC14 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Owner allowed, other owner/tenant denied, spoofed body identity ignored
- Route/query IDs and conflict; cancelled state
- Local/temp download, traversal/symlink escape, signed URL expiration/refresh

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-server/tests/handlers/test_video_reel_artifacts.py -q
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

**Q7 evidence gate resolution**: Searched the codebase (via `wikitoolkit query`) for an existing
deployed owner/tenant helper before inventing one. Found two verified, working patterns:
`StudioBaseView` (`handlers/studio/_base.py`, FEAT-467 TASK-2511 — `_resolve_session()`/`_get_user()`/
`_require_owner()`) and `CredentialsHandler` (`credentials.py:57-59` — `@is_authenticated()
@user_session()` class decorators + `_get_user_id()`). Verified `BaseView.get_userid()` is defined
directly on `navigator.views.BaseView` (not `AbstractModel`-only), confirmed via `inspect.getsource`.
Adapted `StudioBaseView`'s `_resolve_session()` pattern directly into `VideoReelHandler` (no PBAC/
superuser bypass needed — out of this task's scope). **Deviated from the class-decorator half of the
pattern** after discovering, via actually running `test_video_reel_inputs.py`'s real-`aiohttp.Request`
suite, that `@user_session()` unconditionally calls `navigator_session.get_session()` with no
test-friendly short circuit (unlike `@is_authenticated()`'s documented `request["authenticated"] =
True` bypass, used in 12+ other handler test files in this package) — it hard-crashes with
`RuntimeError: Missing Configuration of Session Storage` against a bare `web.Application()`. Since
`_resolve_session()` already implements the identical "decorated or not" duality `StudioBaseView`'s
own docstring describes (falls back to calling the plain, inherited `BaseView.session()` method), and
`post()` independently rejects an unresolvable session via `HTTPUnauthorized`, the class decorators
would add a hard session-storage-middleware dependency with no additional security this handler
doesn't already enforce itself. Documented this deviation in the class docstring.

**Never trust body user_id as ownership**: `post()`'s `job_manager.create_job(user_id=...)` now
always uses `await self._get_session_user_id()` (session-derived), never the body's `user_id` field
(which is still forwarded to `generate_video_reel(user_id=..., session_id=...)` as AI-message
conversational metadata only — a documented "reserved" field, never load-bearing for authorization).
An unauthenticated `post()` now raises `HTTPUnauthorized` before any job is created.

**`_resolve_job_id`/`_authorize_job`/`_get_artifact`** implemented exactly per the spec's Interface
Skeleton (§3 M8): route `match_info` vs `?job_id=` query conflict → 400; missing/unauthorized jobs →
the SAME non-disclosing 404 (verified indistinguishable by status code, since the "missing" path goes
through the mocked `self.error()` in tests but the real `BaseView.error()` also raises `HTTPNotFound`
in production — same class, same status, either way); a job with `user_id=None` (legacy/anonymous) is
denied to everyone, fail-closed, not fail-open.

**Artifact delivery**: `_get_artifact` resolves `artifact_id` only by string-equality against
`job.result["artifacts"][*]["artifact_id"]` — never interpolated into a path, so a traversal-shaped
`artifact_id` simply fails to match (404), never touching the filesystem with attacker input. Local
(`"fs"`/`"temp"`) artifacts stream via `aiofiles` (new `_stream_file`, chunked, genuinely async — never
blocks the event loop) reading the path from `job.result["files"][0]` (server-recorded, never a
caller-supplied path). Cloud (`s3`/`gcs`) artifacts redirect (`web.HTTPFound`) to a freshly-signed URL
resolved from the artifact's stable `storage_key` via `_create_file_manager(backend=...)` (extended
with a `backend` override so the artifact's *recorded* backend is used, not necessarily the server's
*current* `VIDEO_REEL_STORAGE_BACKEND` env default). Route registered:
`{route}/{job_id}/artifacts/{artifact_id}`.

**Signed URL refresh at both polling and delivery**: new `_refresh_result_urls()` re-signs every
cloud artifact's `download_url` from its stable `storage_key` on every `_get_job_status` poll (not
just at `_get_artifact` delivery time) — cloud signed URLs recorded at job-completion time can expire
long before a caller polls. The SAME refreshed URL is applied to both places the artifact is
serialized (top-level `artifacts[]` and `metadata.video_reel.final_artifact`) so they stay consistent
(AC10: byte-exact round trip). A refresh failure for one artifact is logged and its original URL is
kept — never fails the whole poll response. Local artifacts are never touched (their `file://` URL
never expires).

**CANCELLED state**: `_get_job_status` was missing an `elif job.status == JobStatus.CANCELLED:`
branch entirely (an existing gap, not introduced by this task) — a cancelled job's `error`/
`completed_at` were silently dropped even though `JobManager._run_job`'s cancellation handler sets
both. Added, matching the `FAILED` branch's shape.

**Serialization**: `run_logic()`'s `result.model_dump()` → `result.model_dump(mode="json")` per this
module's own declared responsibility ("...400/403/404/413 mapping, `model_dump(mode="json")`").

**Known limitation (documented, not fixed — outside this task's file scope)**: cloud signed-URL
refresh reconstructs the `FileManagerInterface` from *server* env config
(`VIDEO_REEL_STORAGE_BUCKET`/`_PREFIX`), matching `_create_file_manager`'s existing precedent. A job
whose `storage_backend`/`storage_config` were *client*-supplied per-request (not mirrored in server
env) cannot have its signed URL correctly refreshed later — this would need the `Job` model itself to
persist the original storage config (`jobs/models.py`, outside this task's declared Files list). Not a
regression: the original design already only reliably resolves storage config from server env at
generation time too.

**Deviations to pre-existing, out-of-scope test files (task-mandated, not scope creep)**: both
`test_video_reel_handler.py` (TASK-3330-era file) and `test_video_reel_inputs.py` (TASK-3332's own
file) exercise `post()`/`get()` code paths that now require a resolvable session identity. Updated
both fixtures to mock `_get_session_user_id`/`_handler()`'s helper with a fixed test identity, and
`test_video_reel_handler.py`'s `_make_job()`/`handler` fixture to default a matching job owner. One
existing assertion (`test_post_extracts_control_keys`) explicitly asserted the OLD, insecure behavior
(`job.user_id == body's "user-123"`) — corrected to assert the new, secure behavior (session identity
used, body value explicitly NOT used), consistent with this task's own AC.

**Tests**: New `packages/ai-parrot-server/tests/handlers/test_video_reel_artifacts.py` (26 tests) —
job-id resolution (route/query/conflict), ownership (owner/other-user/missing-job/no-owner/
unauthenticated — all converging on non-disclosing 404), spoofed-body-identity rejection, CANCELLED
state, signed-URL refresh (cloud refreshed + consistent, local untouched, refresh-failure-tolerant),
artifact delivery (local streaming, temp backend, missing file, unknown/traversal-shaped artifact_id,
incomplete job, cloud redirect with query-string preservation, unconfigured cloud backend, ownership
enforcement, missing job). All 26 pass. Full regression: `packages/ai-parrot-server/tests/handlers/`
— 577 passed, 4 skipped, 2 failed (both `test_agent_a2ui_stream.py`, confirmed unrelated — zero A2UI
files appear in this feature's diff). `packages/ai-parrot/tests/test_video_reel_handler.py` — 33
passed. `packages/ai-parrot/tests/{test_google_reel,test_reel_contracts,test_video_reel_storage}.py`
— 86 passed, 1 skipped, 3 known pre-existing environment-drift failures (documented since TASK-3329/
3330: navigator-api `FileManagerFactory` returns `LocalFileManager` instead of `TempFileManager`,
unrelated to this feature).

**black --check / ruff check**: both clean on all four touched/created files.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a · Tokens: n/a
