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

Completed 2026-09-17 by sdd-worker orchestrator (fallback sequential loop, sonnet — the
`parrot-sdd-coder` MCP server became wedged: `coder_prepare_native` timed out after 1800s and a
subsequent `coder_plan` also hung >120s, so this task and all remaining FEAT-564 tasks were
implemented directly by the orchestrator per the documented fallback path).

- Implemented `ReelErrorCode` (spec's 11 values plus the 3 registry-contract validation codes:
  `wrong_api_surface`, `model_disabled`, `unsupported_option`), `ReelError`/`ReelValidationError`
  (code/stage/scene_index/retryable/operation_id preserved), and `classify_provider_error()`.
- Classification uses only structured `status`/`code` fields from `google.genai.errors.APIError`
  plus a structured `reason` extracted from `ErrorInfo`-style `details`/nested `error.details`
  entries — never message substrings. A bare 400/403 is never inferred as a safety block; only an
  explicit structured `reason` in `_SAFETY_REASONS` (`SAFETY`, `PROHIBITED_CONTENT`, `RECITATION`,
  `BLOCKLIST`) does.
- **Design decision (no interface skeleton in spec/task for these)**: added local normalization
  exception types `OperationFailure`, `FilteredOutputError`, `DownloadFailure`,
  `MediaValidationFailure` so terminal-operation, filtered/empty-output, download and local-media
  failures can all flow through the single `classify_provider_error(exc, ...)` entry point the spec
  names, matching its `BaseException` signature. TASK-3323/3324/3325 (Veo/Omni adapters) are
  expected to raise these when normalizing their own failure paths — confirm before those tasks
  start.
  - Added `MediaValidationFailure` docstring and normalization but left construction of "download"
  vs "media invalid" boundary to the adapters (this task only defines the taxonomy).
- `asyncio.CancelledError` always re-raised unchanged (never reclassified/swallowed).
- Redaction (`_redact`): Bearer tokens, Google API-key-shaped strings, `key=value` credential
  pairs and long base64 blobs are stripped from every `ReelError` message at construction time.
- AC07/AC17 (owned by this task): covered by the 25 tests in `test_reel_errors.py` (structured
  status/reason mapping for 400/401/403/404/408/429/5xx, safety-reason vs bare-400/403 non-inference,
  operation/filtered-output/download/media normalization, cancellation pass-through, redaction of
  bearer/API-key/base64/key-value secrets).
- **Deviation flagged**: created `tests/unit/reel/__init__.py` (not in the task's Files to
  Create/Modify list) — required to match this repo's established nested-test-package convention
  (every sibling `tests/unit/<subdir>/` has one; `pytest` "prepend" import mode risks module-name
  collisions without it). No other files outside the task's list were touched.
- Tests: `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_errors.py -q` — 25
  passed (compiled Cython artifacts `parrot.utils.types`/`parrot.utils.parsers.toml`, absent from
  every worktree's source tree, copied in from the main checkout temporarily to run pytest, then
  removed — nothing committed; same documented shared-venv/worktree limitation as TASK-3321).
- Lint: `ruff check` — all checks passed, no findings. `black --line-length 120` reformatted
  `errors.py` (whitespace/wrapping only); re-ran the focused suite after reformatting — still 25
  passed.
- No live-service claims inferred from mocks; no default test performs a paid provider call.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 (native `sdd-coder` dispatch correctly stopped without writing code after finding its
assigned pool sub-worktree read-only — see infra note below) · Duration: n/a (fallback, not
MCP/native-agent timed) · Tokens: n/a

**Infra note for the record**: before falling back, the orchestrator dispatched this task to the
native `sonnet` seat via `coder_prepare_native`/`Agent` exactly as for TASK-3321. That dispatched
agent correctly identified its assigned pool sub-worktree
(`.claude/worktrees/feat-FEAT-564-video-reel-omni-veo-reliability--pool/TASK-3322-a1-...`) as
mounted read-only (confirmed independently by the orchestrator's own `touch`/`rm` probes on the
same path) and stopped without writing anything or bypassing the sandbox — correct behavior per
the shared-environment policy. The orchestrator then could not free that path (git's physical
worktree-file removal also hit the same read-only boundary) and, after retries, hit a wedged
`parrot-sdd-coder` MCP server (`coder_prepare_native` timeout after 1800s, subsequent `coder_plan`
hung >120s), so it switched to the documented sequential fallback for this task and all remaining
FEAT-564 tasks.
