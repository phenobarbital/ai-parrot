# TASK-3332: HTTP request validation, indexed uploads and fixture repair

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3321
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Handler edits are serialized TASK-3332 -> TASK-3333. May run with ready provider tasks only when files do not overlap.

## Context

Implements M8 inputs of spec §3 and contributes to AC01, AC02, AC08, AC11. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Keep POST 202 job behavior and lazy provider import; stop popping model before core alias validation. Construct the client using effective director selection and pass full request onward.
- Validate JSON body is an object; decode request/scenes/speech/storage_config multipart fields and validate shapes. Enforce server-configurable 20-scene, 10MiB/image and 100MiB total bounds while streaming.
- Return explicit index->path from _parse_multipart; accept either image_<index> or ordered slots, reject mixed addressing, duplicate/invalid indices and out-of-range slots. Use unique filenames and preserve holes.
- Keep upload ownership through parser/validation/setup/job exits, including failures before job creation. Reject caller-controlled storage escapes and unauthorized local image paths.
- Repair historical handler fixture with real BaseView-compatible request construction; retain assertions and add real HTTP parsing tests.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/video_reel.py` | MODIFY | Request parsing, uploads, quotas and control forwarding |
| `packages/ai-parrot/tests/test_video_reel_handler.py` | MODIFY | Repair view fixture without weakening assertions |
| `packages/ai-parrot-server/tests/handlers/test_video_reel_inputs.py` | CREATE | Real handler input boundary tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.handlers.video_reel import VideoReelHandler
from parrot.models.google import VideoReelRequest, VideoReelScene
from parrot.handlers.jobs.job import JobManager
```

### Existing Signatures to Use

- `packages/ai-parrot-server/src/parrot/handlers/video_reel.py:31`: VideoReelHandler(BaseView); setup(cls, app, route='/api/v1/google/generation/video_reel'); async _parse_multipart(self) -> tuple[dict, list[Path]]; async post(self) -> web.Response; async get(self) -> web.Response.
  Symbols: `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler._parse_multipart`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.post`, `sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.get`.
- `packages/ai-parrot/src/parrot/models/google.py:376`: VideoReelScene.duration: float = 5.0; VideoReelRequest._parse_json_strings(cls, v) is a before validator for scenes/speech.
  Symbols: `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene`, `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest`.
- `packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:209`: async execute_job(self, job_id: str, execution_func: Callable[[], Awaitable[Any]]) -> None schedules _run_job; async get_job_async(self, job_id: str) -> Optional[Job]. _run_job awaits the callback before publishing completion/cancellation.
  Symbols: `sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.execute_job`, `sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.get_job_async`.

### Dependency Interfaces

- Read the completed TASK-3321 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-server/tests/handlers/test_video_reel_inputs.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot/tests/test_video_reel_handler.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_video_reel_inputs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler._parse_multipart",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/video_reel.py#VideoReelHandler.get",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.execute_job",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.get_job_async"
  ]
}
```

## Implementation Notes

Do not invent authentication helpers; artifact authorization is owned by the delivery task. Keep sparse representation consistent with core contracts.

Handler edits are serialized TASK-3332 -> TASK-3333. May run with ready provider tasks only when files do not overlap.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3332-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Keep POST 202 job behavior and lazy provider import; stop popping model before core alias validation. Construct the client using effective director selection and pass full request onward.
- [ ] Validate JSON body is an object; decode request/scenes/speech/storage_config multipart fields and validate shapes. Enforce server-configurable 20-scene, 10MiB/image and 100MiB total bounds while streaming.
- [ ] Return explicit index->path from _parse_multipart; accept either image_<index> or ordered slots, reject mixed addressing, duplicate/invalid indices and out-of-range slots. Use unique filenames and preserve holes.
- [ ] Keep upload ownership through parser/validation/setup/job exits, including failures before job creation. Reject caller-controlled storage escapes and unauthorized local image paths.
- [ ] Repair historical handler fixture with real BaseView-compatible request construction; retain assertions and add real HTTP parsing tests.
- [ ] AC01, AC02, AC08, AC11 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- JSON nonobject/malformed and model alias errors ->400; limits ->413
- Sparse first/middle slots, reordered indices, duplicate filenames and mixed-address rejection
- Parser/validation/setup failure cleanup and POST callback forwards request

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot/tests/test_video_reel_handler.py -q
pytest packages/ai-parrot-server/tests/handlers/test_video_reel_inputs.py -q
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

Completed 2026-09-17 by sdd-worker orchestrator (fallback sequential loop, sonnet — `parrot-sdd-coder`
was wedged, see TASK-3322's Completion Note for the infra timeline).

- `model` is no longer popped before validation: it flows into `VideoReelRequest(**data)` so
  TASK-3321's legacy-alias validator (conflict/blank/null) actually runs. The background job now
  builds `GoogleGenAIClient(model=req.effective_director_model())` instead of a locally-hardcoded
  `"gemini-3.5-flash"` default (now correctly `"gemini-2.5-flash"` via TASK-3321, when unset), and
  `generate_video_reel(request=req, ...)` receives the full validated request object.
- JSON body: rejects non-object bodies (`Request body must be a JSON object.`, 400) before
  `VideoReelRequest(**data)` would otherwise raise an unhandled `TypeError`.
- `storage_config`/`scenes`/`speech` multipart JSON-string decoding stays on `VideoReelRequest`'s
  own `_parse_json_strings` validator (TASK-3321) — the handler does not duplicate that decoding.
- New server-configurable bounds (`VIDEO_REEL_MAX_SCENES`=20, `VIDEO_REEL_MAX_IMAGE_BYTES`=10MiB,
  `VIDEO_REEL_MAX_TOTAL_UPLOAD_BYTES`=100MiB), enforced per-part as the multipart body streams in
  (not after full buffering), plus a `scenes` list-length check for JSON bodies.
- `_parse_multipart` now returns `(dict, dict[int, Path])` — an explicit index→path mapping — instead
  of an ordered list, matching TASK-3321's sparse `reference_images: Optional[List[Optional[str]]]`
  exactly as its Completion Note asked this task to. Accepts either `image_<n>` (explicit index) or
  `reference_images`/`image` (ordered, arrival-order index) addressing; rejects mixing both styles,
  duplicate/out-of-range explicit indices, and enforces unique on-disk filenames
  (`{index:04d}_{uuid8}_{original name}`) so same-named uploads never collide. Holes (missing
  indices) are preserved as `None` in the padded list built before `VideoReelRequest(**data)`.
- **Design decision (no interface skeleton in spec/task for this)**: `reference_images` supplied
  directly in the request body (JSON or multipart scalar) is now rejected with 400 — the model's own
  docstring says it is "populated by VideoReelHandler from multipart uploads", so a caller-supplied
  value (e.g. `/etc/passwd`) would be an unauthorized local-path / storage-escape vector. This is the
  scoped fix for the Scope bullet "Reject caller-controlled storage escapes and unauthorized local
  image paths" — no tenant/owner helper was invented (explicitly out of contract).
- `output_directory` is validated (`_resolve_output_directory`): `..` segments always rejected; when
  `VIDEO_REEL_OUTPUT_ROOT` is configured, the resolved path must stay under it.
- Upload ownership: tmp_dir cleanup now happens on every exit path — parse failure (already true),
  the new `_parse_multipart`-internal rejections (mixed addressing/duplicate/out-of-range/size,
  cleans its own lazily-created tmp_dir before re-raising), post-parse-but-pre-validation checks
  (non-object body, `reference_images` direct-supply, scenes-bound), `ValidationError`, and any
  failure during `_resolve_output_directory`/`_create_file_manager`/`job_manager.create_job` (new
  try/except wrapping that block). Previously only the parse-exception and success paths cleaned up.
- **Bug found and fixed at the HTTP boundary**: the real (non-mocked) `navigator.views.BaseView.error()`
  only maps status ∈ {400,401,403,404,406,412,428} to a matching `HTTPException` subclass — any other
  status, including 413, silently falls through to `HTTPBadRequest` (still 400!). All `_RequestError`
  conversions now go through a new `_raise_request_error()` that raises `web.HTTPRequestEntityTooLarge`
  directly for 413s (with real `max_size`/`actual_size`) and `web.HTTPBadRequest` otherwise. Caught via
  a live `MultipartWriter`/`make_mocked_request`-constructed request in the new test file — a fully
  mocked `handler.error()` (the old fixture's approach) would never have surfaced this.
- **Repaired historical fixture** (`packages/ai-parrot/tests/test_video_reel_handler.py`): the
  `handler` fixture did `h.request = MagicMock()`, but `request` is a read-only `BaseView` property
  (`self._request`, no setter) against the currently-installed `navigator-api` — every test using it
  errored at setup (20 setup errors, matching spec F012 exactly). Fixed by setting the backing
  `h._request = MagicMock()` instead (mirrors `test_infographic_render_route.py`'s `_handler()`
  helper) — zero other changes to the fixture, so every existing assertion is retained unchanged.
  Also updated `test_model_json_schema`'s expected property set (TASK-3321 added 8 new fields) and
  the two multipart tests whose mocks returned the old `list[Path]` shape (`_parse_multipart` now
  returns `dict[int, Path]`). Result: 1 failed + 12 passed + 20 errors → 33 passed.
- **New file** `packages/ai-parrot-server/tests/handlers/test_video_reel_inputs.py`: real HTTP
  boundary tests built with `aiohttp.MultipartWriter` + `make_mocked_request` (mirrors
  `test_infographic_render_models.py`/`test_infographic_render_route.py`), not hand-mocked readers —
  19 tests covering JSON-object validation, the legacy-alias conflict now reaching validation,
  scene/image/total-size bounds (413), sparse/reordered/duplicate-filename/mixed-address multipart
  addressing, `reference_images` direct-supply rejection, tmp_dir cleanup across parse/validation/
  setup failures (verified via a `tempfile.mkdtemp` spy — a global `/tmp` glob is unsafe in a shared
  test session), and that the background job callback forwards the full validated `VideoReelRequest`
  with `effective_director_model()`.
- AC01, AC02, AC08, AC11 (owned by this task): covered by the new boundary-test file plus the
  repaired fixture's existing assertions.
- Tests: `pytest packages/ai-parrot/tests/test_video_reel_handler.py -q` — 33 passed.
  `pytest packages/ai-parrot-server/tests/handlers/test_video_reel_inputs.py -q` — 19 passed. Both
  ai-parrot-server's own `conftest.py` stubs the missing compiled Cython artifacts
  (`parrot.utils.types`/`parrot.utils.parsers.toml`) for its own test root, so no temporary `.so`
  copy was needed for the server-side suite; the ai-parrot-side suite needed the same temporary
  main-checkout `.so` copy-then-remove as TASK-3321/3322 (nothing committed).
- Lint: `ruff check` — all checks passed on all three touched files. `black --line-length 120`
  reformatted all three (whitespace only); re-ran both suites after reformatting — still 33 + 19
  passed.
- Not in scope, confirmed left alone: `?job_id=` query-param polling (spec §2 item 9 — not in this
  task's Scope bullets), artifact-delivery route/ownership check (TASK-3333), Veo/Omni provider
  call itself (TASK-3324/3326).
- No live-service claims inferred from mocks; no default test performs a paid provider call. No
  files outside the task's three listed targets were created or modified.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a (fallback, not MCP/native-agent timed) · Tokens: n/a
