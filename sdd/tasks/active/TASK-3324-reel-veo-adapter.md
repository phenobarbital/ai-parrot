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

Pending implementation. The executor must record completed-by, date, test results, evidence-gate resolution and deviations before marking done.
