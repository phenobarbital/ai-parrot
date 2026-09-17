# TASK-3326: Omni async Interactions clip adapter

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3323, TASK-3325
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

## Context

Implements M4 generation of spec §3 and contributes to AC01, AC04, AC06, AC12, AC17. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Implement OmniClipAdapter(owner, downloader) and the spec generate signature.
- Use public sdk.aio.interactions.create with background=False, store=False, stream=False and an absolute deadline. No Veo config, temperature or negative_prompt.
- Verify Q3 public response shape, MIME and URI handling against installed SDK/docs; decode inline data or use ProviderMediaDownloader. Do not copy synchronous deep research.
- Omit provider duration until supported values are verified; measure output and fail insufficient_duration beyond one frame. Normalize blocked/empty/invalid output and preserve native audio metadata.
- Own and close the SDK client on all exits; do not retry ambiguous creation failures.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py` | CREATE | Omni adapter and media normalization |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_omni.py` | CREATE | Public Interactions contract tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google import GoogleGenAIClient
from parrot.clients.google.generation import GoogleGeneration
```

### Existing Signatures to Use

- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:630`: async get_client(self, model: str = None, **kwargs) -> genai.Client constructs a fresh client; async close(self) -> None delegates to close_all. Directly created clients require explicit ownership.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close`.
- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1524`: async generate_image(self, prompt, model=None, reference_images=None, google_search=False, aspect_ratio=None, resolution=None, number_of_images=None, negative_prompt=None, person_generation=None, safety_filter_level=None, seed=None, add_watermark=None, output_mime_type=None, service_tier=None, temperature=None, prompt_instruction=None, output_directory=None, as_base64=False, user_id=None, session_id=None, stateless=True, history=None, **kwargs) -> AIMessage; async _breakdown_prompt_to_scenes(self, prompt: str) -> List[VideoReelScene].
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_image`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._breakdown_prompt_to_scenes`.

### Dependency Interfaces

- Read the completed TASK-3323 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.
- Read the completed TASK-3325 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_omni.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/omni.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_omni.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_image",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._breakdown_prompt_to_scenes"
  ]
}
```

## Implementation Notes

Q3 unresolved facts require evidence before implementation completion; default tests mock the provider, and do not assert live access.

May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3326-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Implement OmniClipAdapter(owner, downloader) and the spec generate signature.
- [ ] Use public sdk.aio.interactions.create with background=False, store=False, stream=False and an absolute deadline. No Veo config, temperature or negative_prompt.
- [ ] Verify Q3 public response shape, MIME and URI handling against installed SDK/docs; decode inline data or use ProviderMediaDownloader. Do not copy synchronous deep research.
- [ ] Omit provider duration until supported values are verified; measure output and fail insufficient_duration beyond one frame. Normalize blocked/empty/invalid output and preserve native audio metadata.
- [ ] Own and close the SDK client on all exits; do not retry ambiguous creation failures.
- [ ] AC01, AC04, AC06, AC12, AC17 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Inline and URI success, native audio and measured duration
- Malformed base64/MIME/empty/blocked/too-short outputs
- Create kwargs and no Veo fields; deadline/cancellation/session closure

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_omni.py -q
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
