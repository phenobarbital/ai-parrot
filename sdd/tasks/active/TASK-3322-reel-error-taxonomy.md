# TASK-3322: Provider error taxonomy and classification

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3321
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

## Context

Implements M2 errors of spec §3 and contributes to AC07, AC17. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Implement ReelErrorCode, ReelError, ReelValidationError and classify_provider_error per §3 M2.
- Preserve code, stage, scene index, retryability and operation ID; add the validation codes explicitly used by the registry contract (wrong_api_surface, model_disabled, unsupported_option) alongside the listed enum values.
- Classify immediate APIError/ClientError using status/reason data, and provide normalization for operation errors and filtered output. Never infer safety from every 400/403 or solely a substring.
- Safety/auth/invalid configuration are terminal; rate limit/transient classification must not authorize generation resubmission. Redact credential/base64 values and preserve cancellation.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/__init__.py` | CREATE | Initialize reel package without eager exports |
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/errors.py` | CREATE | Stable structured errors and classification |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_errors.py` | CREATE | Safety and status classification tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google.generation import GoogleGeneration
```

### Existing Signatures to Use

- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:844`: async video_generation(self, prompt, output_directory=None, model=GoogleModel.VEO_3_1, aspect_ratio=AspectRatio.RATIO_16_9, negative_prompt=None, number_of_videos=1, reference_image=None, generate_image_first=False, image_prompt=None, duration=8, resolution=None, person_generation='allow_adult', include_audio=True, last_frame=None, reference_images=None, reference_type='asset', extend_video=None, seed=None, user_id=None, session_id=None, **kwargs) -> AIMessage.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.video_generation`.

### Dependency Interfaces

- Read the completed TASK-3321 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/src/parrot/clients/google/reel/__init__.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/src/parrot/clients/google/reel/errors.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_errors.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/errors.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_errors.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.video_generation"
  ]
}
```

## Implementation Notes

ClientError inherits APIError. Verify installed SDK structured fields before building fixtures; no live requests.

May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3322-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Implement ReelErrorCode, ReelError, ReelValidationError and classify_provider_error per §3 M2.
- [ ] Preserve code, stage, scene index, retryability and operation ID; add the validation codes explicitly used by the registry contract (wrong_api_surface, model_disabled, unsupported_option) alongside the listed enum values.
- [ ] Classify immediate APIError/ClientError using status/reason data, and provide normalization for operation errors and filtered output. Never infer safety from every 400/403 or solely a substring.
- [ ] Safety/auth/invalid configuration are terminal; rate limit/transient classification must not authorize generation resubmission. Redact credential/base64 values and preserve cancellation.
- [ ] AC07, AC17 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Immediate ClientError safety, operation safety and filtered-output normalization
- 403 access versus safety reason; invalid config; transient status and unknown exception
- Operation ID retained and sensitive error values redacted

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_errors.py -q
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
