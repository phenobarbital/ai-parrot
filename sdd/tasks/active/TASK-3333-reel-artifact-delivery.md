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

Pending implementation. The executor must record completed-by, date, test results, evidence-gate resolution and deviations before marking done.
