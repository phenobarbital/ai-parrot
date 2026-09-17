# TASK-3321: Core reel request and result contracts

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

## Context

Implements M1 of spec §3 and contributes to AC01, AC02, AC04, AC06, AC10. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Add the spec §2 request fields, AudioMode/MusicPolicy/PartialFailurePolicy/VideoResolution literals, ReelArtifact, ReelSceneResult and ReelResult without provider imports.
- Distinguish omitted defaults from explicit null/blank model values; only scene video_model permits null inheritance. Implement effective_director_model and deprecation_warnings. Different legacy model/director_model values fail; identical values warn.
- Validate finite 0 < duration <= 8, format/transition choices and audio-control conflicts. Preserve existing request fields and speech precedence. Decode storage_config JSON to an object for multipart use.
- Define a lossless sparse-image representation shared with the HTTP task; preserve slot indices through supplied or director-produced scenes without changing image paths into provider asset guidance.
- Result URLs remain strings; serialized artifacts are dictionaries compatible with AIMessage.artifacts.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/google.py` | MODIFY | Add request validation and typed results |
| `packages/ai-parrot/tests/test_reel_contracts.py` | CREATE | Core-only schema and serialization tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.models.google import VideoReelRequest, VideoReelScene
from parrot.models.responses import AIMessage, AIMessageFactory
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/models/google.py:376`: VideoReelScene.duration: float = 5.0; VideoReelRequest._parse_json_strings(cls, v) is a before validator for scenes/speech.
  Symbols: `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene`, `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest`.
- `packages/ai-parrot/src/parrot/models/responses.py:75`: AIMessage.files: Optional[List[Path]]; metadata: Dict[str, Any]; artifacts: List[Dict[str, Any]]. AIMessageFactory.from_video(**kwargs) returns AIMessage(**kwargs).
  Symbols: `sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage`, `sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_video`.

### Dependency Interfaces

- No prerequisite implementation symbols are assumed.

### Does NOT Exist

- `packages/ai-parrot/tests/test_reel_contracts.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot/src/parrot/models/google.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_reel_contracts.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_video"
  ]
}
```

## Implementation Notes

Do not mark the spec approved or rewrite provider model catalogs. Confirm new literal names do not shadow existing exports.

May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3321-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Add the spec §2 request fields, AudioMode/MusicPolicy/PartialFailurePolicy/VideoResolution literals, ReelArtifact, ReelSceneResult and ReelResult without provider imports.
- [ ] Distinguish omitted defaults from explicit null/blank model values; only scene video_model permits null inheritance. Implement effective_director_model and deprecation_warnings. Different legacy model/director_model values fail; identical values warn.
- [ ] Validate finite 0 < duration <= 8, format/transition choices and audio-control conflicts. Preserve existing request fields and speech precedence. Decode storage_config JSON to an object for multipart use.
- [ ] Define a lossless sparse-image representation shared with the HTTP task; preserve slot indices through supplied or director-produced scenes without changing image paths into provider asset guidance.
- [ ] Result URLs remain strings; serialized artifacts are dictionaries compatible with AIMessage.artifacts.
- [ ] AC01, AC02, AC04, AC06, AC10 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Alias absent/equal/conflicting/null/blank inputs, director default and scene inheritance
- NaN/inf/zero/negative/>8 rejection and five-second default
- Native/muted control conflicts and off/optional/required validation
- URL query preservation and JSON-mode result round trip

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot/tests/test_reel_contracts.py -q
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
