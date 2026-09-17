# TASK-3330: Stage routing, scene policies and typed reel output

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3326, TASK-3329
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

## Context

Implements M7 routing of spec §3 and contributes to AC01, AC02, AC03, AC04, AC06, AC10, AC13, AC17. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Preserve generate_video_reel's public signature; add generate_video_clip dispatcher and model parameter to _breakdown_prompt_to_scenes.
- Resolve Q4 image-model ID against deployment support without silently substituting a different ID. Forward director/image/video choices and report unused director when scenes are supplied.
- Validate request-known profiles before director work; validate director-produced scenes before image/video generation. Keep the director cost boundary explicit rather than promising impossible validation of nonexistent scenes.
- Build stage/run context and per-scene generated data; preserve speech precedence and sparse upload correspondence. Replace tuple/None failure handling with typed results and remove the text-to-video safety retry.
- Apply fail/skip with original scene indices, all-failed error and music off/optional/required semantics. Persist through FileManager and emit JSON ReelResult metadata and dict artifacts; files contains durable local paths only.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | MODIFY | Route all reel stages through resolved contracts |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py` | CREATE | Routing, policies and output tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google.generation import GoogleGeneration
from parrot.models.google import VideoReelRequest, VideoReelScene
from parrot.models.responses import AIMessage, AIMessageFactory
from parrot.tools.filemanager import FileManagerFactory
from parrot.interfaces.file import FileManagerInterface
```

### Existing Signatures to Use

- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1905`: async generate_video_reel(self, request: VideoReelRequest, output_directory: Optional[Path] = None, file_manager: Optional[FileManagerInterface] = None, user_id: Optional[str] = None, session_id: Optional[str] = None) -> AIMessage; current _process_scene(self, scene, index, output_dir, aspect_ratio, file_manager=None, job_prefix=None) returns tuple[Optional[str], Optional[str]].
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_video_reel`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._process_scene`.
- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1524`: async generate_image(self, prompt, model=None, reference_images=None, google_search=False, aspect_ratio=None, resolution=None, number_of_images=None, negative_prompt=None, person_generation=None, safety_filter_level=None, seed=None, add_watermark=None, output_mime_type=None, service_tier=None, temperature=None, prompt_instruction=None, output_directory=None, as_base64=False, user_id=None, session_id=None, stateless=True, history=None, **kwargs) -> AIMessage; async _breakdown_prompt_to_scenes(self, prompt: str) -> List[VideoReelScene].
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_image`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._breakdown_prompt_to_scenes`.
- `packages/ai-parrot/src/parrot/models/google.py:376`: VideoReelScene.duration: float = 5.0; VideoReelRequest._parse_json_strings(cls, v) is a before validator for scenes/speech.
  Symbols: `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene`, `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest`.
- `packages/ai-parrot/src/parrot/models/responses.py:75`: AIMessage.files: Optional[List[Path]]; metadata: Dict[str, Any]; artifacts: List[Dict[str, Any]]. AIMessageFactory.from_video(**kwargs) returns AIMessage(**kwargs).
  Symbols: `sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage`, `sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_video`.
- `packages/ai-parrot/src/parrot/tools/filemanager.py:23`: FileManagerFactory.create(manager_type: Literal['fs', 'temp', 's3', 'gcs'], **kwargs) -> FileManagerInterface delegates to navigator; parrot.interfaces.file/__init__.py re-exports navigator.utils.file types.
  Symbols: `sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create`.

### Dependency Interfaces

- Read the completed TASK-3326 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.
- Read the completed TASK-3329 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/generation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_video_reel",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._process_scene",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_image",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._breakdown_prompt_to_scenes",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessageFactory.from_video",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create"
  ]
}
```

## Implementation Notes

Q4 requires verification; do not alter provider enum values or AbstractClient. Do not modify adapter internals owned by prerequisite tasks.

generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3330-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Preserve generate_video_reel's public signature; add generate_video_clip dispatcher and model parameter to _breakdown_prompt_to_scenes.
- [ ] Resolve Q4 image-model ID against deployment support without silently substituting a different ID. Forward director/image/video choices and report unused director when scenes are supplied.
- [ ] Validate request-known profiles before director work; validate director-produced scenes before image/video generation. Keep the director cost boundary explicit rather than promising impossible validation of nonexistent scenes.
- [ ] Build stage/run context and per-scene generated data; preserve speech precedence and sparse upload correspondence. Replace tuple/None failure handling with typed results and remove the text-to-video safety retry.
- [ ] Apply fail/skip with original scene indices, all-failed error and music off/optional/required semantics. Persist through FileManager and emit JSON ReelResult metadata and dict artifacts; files contains durable local paths only.
- [ ] AC01, AC02, AC03, AC04, AC06, AC10, AC13, AC17 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Actual arguments for director and both image calls; mixed Veo/Omni dispatch
- Legacy alias warnings, director unused and explicit per-scene precedence
- Fail/skip/all-failed, sparse slots, exact URL serialization and local/cloud files

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_orchestration.py -q
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
