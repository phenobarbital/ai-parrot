# TASK-3328: Scene timeline planning and duration checks

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3323
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

## Context

Implements M6 timeline of spec §3 and contributes to AC04, AC05. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Implement TimelineEntry, TimelinePlan, plan_timeline, check_measured_duration and check_narration_fits per §3 M6.
- Define TimelinePlan's start positions, retained original indices, overlaps, fps and final duration so assembly consumes one explicit plan; document this dependency interface in the task completion note.
- Cuts sum edit targets; crossfades subtract actual valid overlaps. Reject overlap longer than either neighbor and invalid fps/durations.
- Allow one-frame measurement tolerance; never stretch, repeat or regenerate short video. Narration longer than target raises narration_too_long; shorter narration leaves intended scene time intact.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/timeline.py` | CREATE | TimelineEntry, TimelinePlan and pure duration checks |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_timeline.py` | CREATE | Deterministic timeline tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.models.google import VideoReelRequest, VideoReelScene
from parrot.clients.google.generation import GoogleGeneration
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/models/google.py:376`: VideoReelScene.duration: float = 5.0; VideoReelRequest._parse_json_strings(cls, v) is a before validator for scenes/speech.
  Symbols: `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene`, `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest`.
- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:2308`: async _create_reel_assembly(self, scene_outputs: List[tuple[str, Optional[str]]], music_key: Optional[str], output_dir: Path, transition: str, output_format: str, file_manager=None, job_prefix=None) -> str. It downloads, assembles and uploads, currently using a thread executor.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._create_reel_assembly`.

### Dependency Interfaces

- Read the completed TASK-3323 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/src/parrot/clients/google/reel/timeline.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_timeline.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/timeline.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_timeline.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._create_reel_assembly"
  ]
}
```

## Implementation Notes

Pure computation only; no MoviePy, provider calls or generation.py changes.

May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3328-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Implement TimelineEntry, TimelinePlan, plan_timeline, check_measured_duration and check_narration_fits per §3 M6.
- [ ] Define TimelinePlan's start positions, retained original indices, overlaps, fps and final duration so assembly consumes one explicit plan; document this dependency interface in the task completion note.
- [ ] Cuts sum edit targets; crossfades subtract actual valid overlaps. Reject overlap longer than either neighbor and invalid fps/durations.
- [ ] Allow one-frame measurement tolerance; never stretch, repeat or regenerate short video. Narration longer than target raises narration_too_long; shorter narration leaves intended scene time intact.
- [ ] AC04, AC05 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Four 5-second scenes: cut 20 and overlap 18.5
- Skipped indices, one clip, no clips, invalid overlap/fps
- Short media tolerance boundaries and narration overflow

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_timeline.py -q
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
