# TASK-3335: SDK floor, opt-in smoke suite and migration documentation

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3334
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Exclusive dependency/lock/config edits after integration; do not run with other shared-config writers.

## Context

Implements M9 release of spec §3 and contributes to AC15, AC16, AC18. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Verify public async submit/poll/download and Interactions output contract with installed/isolated floor SDK; set minimum >=2.23.0 only with evidence and sync uv.lock from main environment as allowed.
- Register live_google consistently with pytest.ini and pyproject.toml. Smoke tests must skip unless explicitly opted in with credentials and must not make network calls at collection.
- Add opt-in Veo, Omni, mixed reel, native audio and optional music smoke cases recording model/API/version/region with redacted diagnostics.
- Document legacy alias behavior, stage models, duration/edit policy, audio/music policy, URLs and ownership, tested SDKs, disabled Vertex entries and all outstanding deployment gates.
- Verify lazy handler import without Google installed; run lint/format/focused test gates. Do not run paid smoke tests as a default completion step.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/pyproject.toml` | MODIFY | Raise tested google-genai minimum |
| `uv.lock` | MODIFY | Sync dependency floor without unrelated upgrades |
| `pytest.ini` | MODIFY | Register live_google marker for default pytest config |
| `pyproject.toml` | MODIFY | Register live_google marker in alternate pytest configuration |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py` | CREATE | Public SDK surface compatibility checks |
| `packages/ai-parrot-client-google/tests/live/test_reel_smoke.py` | CREATE | Explicitly gated paid smoke tests |
| `docs/migration/video-reel-omni-veo-reliability.md` | CREATE | Payload migration, tested versions and deployment gates |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google import GoogleGenAIClient
from parrot.clients.google.generation import GoogleGeneration
from parrot.handlers.video_reel import VideoReelHandler
```

### Existing Signatures to Use

- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:630`: async get_client(self, model: str = None, **kwargs) -> genai.Client constructs a fresh client; async close(self) -> None delegates to close_all. Directly created clients require explicit ownership.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close`.
- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:844`: async video_generation(self, prompt, output_directory=None, model=GoogleModel.VEO_3_1, aspect_ratio=AspectRatio.RATIO_16_9, negative_prompt=None, number_of_videos=1, reference_image=None, generate_image_first=False, image_prompt=None, duration=8, resolution=None, person_generation='allow_adult', include_audio=True, last_frame=None, reference_images=None, reference_type='asset', extend_video=None, seed=None, user_id=None, session_id=None, **kwargs) -> AIMessage.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.video_generation`.
- `packages/ai-parrot-server/src/parrot/handlers/video_reel.py:31`: VideoReelHandler(BaseView); setup(cls, app, route='/api/v1/google/generation/video_reel'); async _parse_multipart(self) -> tuple[dict, list[Path]]; async post(self) -> web.Response; async get(self) -> web.Response.
  Symbols: `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler._parse_multipart`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.post`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.get`.

### Dependency Interfaces

- Read the completed TASK-3334 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/tests/live/test_reel_smoke.py` does not exist at task creation; create it within this task.
- `docs/migration/video-reel-omni-veo-reliability.md` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-client-google/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "uv.lock",
      "action": "MODIFY"
    },
    {
      "path": "pytest.ini",
      "action": "MODIFY"
    },
    {
      "path": "pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/live/test_reel_smoke.py",
      "action": "CREATE"
    },
    {
      "path": "docs/migration/video-reel-omni-veo-reliability.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.video_generation",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler._parse_multipart",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.get"
  ]
}
```

## Implementation Notes

Exclusive dependency/config task; refresh shared config after other feature work. Never uv sync inside the worktree or claim 2.24.0/live support without tests.

Exclusive dependency/lock/config edits after integration; do not run with other shared-config writers.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3335-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Verify public async submit/poll/download and Interactions output contract with installed/isolated floor SDK; set minimum >=2.23.0 only with evidence and sync uv.lock from main environment as allowed.
- [ ] Register live_google consistently with pytest.ini and pyproject.toml. Smoke tests must skip unless explicitly opted in with credentials and must not make network calls at collection.
- [ ] Add opt-in Veo, Omni, mixed reel, native audio and optional music smoke cases recording model/API/version/region with redacted diagnostics.
- [ ] Document legacy alias behavior, stage models, duration/edit policy, audio/music policy, URLs and ownership, tested SDKs, disabled Vertex entries and all outstanding deployment gates.
- [ ] Verify lazy handler import without Google installed; run lint/format/focused test gates. Do not run paid smoke tests as a default completion step.
- [ ] AC15, AC16, AC18 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Floor/locked public surfaces and serializer behavior with provider network mocked
- Default smoke collection is skipped with no side effects
- Provider-absent lazy import and marker registration under actual pytest config

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py -q
```

Test names and assertions must describe observable behavior, not mirror private implementation branches. No default test may consume paid provider calls. The live suite must remain skipped unless explicitly enabled.

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
