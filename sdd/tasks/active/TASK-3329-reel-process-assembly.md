# TASK-3329: Managed media assembly with trim and audio modes

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3327, TASK-3328
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

## Context

Implements M6 assembly of spec §3 and contributes to AC04, AC05, AC06, AC12. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Implement assemble_reel(plan, *, music_path, audio_mode, output_format, work_dir, deadline) -> Path using a managed process.
- Trim real media to planned edits and perform actual overlap. Preserve native audio, replace it with narration/music in separate mode, and emit no track in muted mode.
- Pad shorter narration with silence and align music to the retained timeline; preserve original indices. Encode MP4/AAC and WebM/Opus using installed codecs.
- On timeout/cancellation terminate and await the worker and encoder resources before cleaning owned working files. Close all MoviePy resources on success and errors.
- Keep storage download/upload in the wrapper; keep per-job directories isolated and do not delete durable final artifacts.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/assembly.py` | CREATE | Managed process media assembly |
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | MODIFY | Delegate _create_reel_assembly media execution |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_assembly.py` | CREATE | Real small media and cancellation tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google.generation import GoogleGeneration
from parrot.tools.filemanager import FileManagerFactory
from parrot.interfaces.file import FileManagerInterface
```

### Existing Signatures to Use

- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:2308`: async _create_reel_assembly(self, scene_outputs: List[tuple[str, Optional[str]]], music_key: Optional[str], output_dir: Path, transition: str, output_format: str, file_manager=None, job_prefix=None) -> str. It downloads, assembles and uploads, currently using a thread executor.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._create_reel_assembly`.
- `packages/ai-parrot/src/parrot/tools/filemanager.py:23`: FileManagerFactory.create(manager_type: Literal['fs', 'temp', 's3', 'gcs'], **kwargs) -> FileManagerInterface delegates to navigator; parrot.interfaces.file/__init__.py re-exports navigator.utils.file types.
  Symbols: `sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create`.

### Dependency Interfaces

- Read the completed TASK-3327 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.
- Read the completed TASK-3328 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/src/parrot/clients/google/reel/assembly.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_assembly.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/assembly.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/generation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_assembly.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._create_reel_assembly",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create"
  ]
}
```

## Implementation Notes

Use multiprocessing for new CPU media work, per project conventions. No new dependencies; report missing codecs distinctly.

generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3329-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Implement assemble_reel(plan, *, music_path, audio_mode, output_format, work_dir, deadline) -> Path using a managed process.
- [ ] Trim real media to planned edits and perform actual overlap. Preserve native audio, replace it with narration/music in separate mode, and emit no track in muted mode.
- [ ] Pad shorter narration with silence and align music to the retained timeline; preserve original indices. Encode MP4/AAC and WebM/Opus using installed codecs.
- [ ] On timeout/cancellation terminate and await the worker and encoder resources before cleaning owned working files. Close all MoviePy resources on success and errors.
- [ ] Keep storage download/upload in the wrapper; keep per-job directories isolated and do not delete durable final artifacts.
- [ ] AC04, AC05, AC06, AC12 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Real generated tiny clips, playable MP4/AAC and WebM/Opus
- 20/18.5 planned duration behavior within one frame and narration fit
- Cancel active worker, encoder failure and concurrent jobs never overwrite

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_assembly.py -q
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
