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

Completed 2026-09-17 by sdd-worker orchestrator (fallback sequential loop, sonnet).

- `assemble_reel(plan, *, music_path, audio_mode, output_format, work_dir, deadline) -> Path` per
  §3 M6, running the actual MoviePy encode in a `multiprocessing.get_context("spawn")` **process**
  (never a thread) so cancellation/timeout can genuinely `.terminate()`/`.kill()` an in-progress
  encode. `_terminate_and_join()` is the exact shared mechanism for both the timeout and
  cancellation paths — always called in `finally`, escalating to `kill()` if `terminate()` doesn't
  land within 10s. Result handoff uses a `multiprocessing.Queue`, polled in bounded 0.5s slices
  (not one giant blocking wait) specifically so a cancelled `assemble_reel()` call doesn't leave an
  executor thread blocked for the full remaining deadline.
- `_create_reel_assembly` (generation.py:2328) now delegates its media-execution step to
  `assemble_reel()` instead of its own inline `_moviepy_assemble`/`asyncio.to_thread` — its
  download/upload wrapper logic is UNCHANGED. Since this legacy signature carries no explicit
  per-scene edit-target duration, each clip's own MEASURED duration is used as `edit_seconds` (i.e.
  "keep the whole clip") via a new `_measure_clip_duration` helper + `plan_timeline()`. **TASK-3330
  (stage orchestration) is expected to replace this exact call site** with a real `TimelinePlan`
  built from `VideoReelScene.duration` targets, a genuine job deadline, and the request's actual
  `audio_mode` (this delegation hardcodes `audio_mode="separate"` and a flat 600s deadline as a
  reasonable stand-in, clearly commented as such in the diff).
- **Three real, verified environment bugs found and fixed while writing REAL encode tests (not
  guessed — each reproduced then root-caused via direct `ffmpeg`/MoviePy probes)**:
  1. **Frame-quantization on encode/decode round-trip**: a clip written with `duration=0.5` can
     decode back marginally SHORTER (e.g. 0.49s) due to container frame-boundary rounding, so
     blindly calling `subclipped(0, edit_seconds)` can raise `"end_time should be smaller or equal
     to the clip's duration"`. Fixed by clamping to `min(edit_seconds, raw_clip.duration)` —
     consistent with the one-frame tolerance philosophy already in `reel/timeline.py`.
  2. **`concatenate_videoclips` + `vfx.CrossFadeIn` alone does NOT shorten total duration** — the
     crossfade visual blend and the temporal overlap are two SEPARATE mechanisms in MoviePy 2.x.
     The actual overlap requires a matching NEGATIVE `padding` on `concatenate_videoclips` itself
     (verified via MoviePy's own docstring: "for negative padding, a clip will partly play at the
     same time as the clip it follows... cool for clips who fade in on one another"). Fixed by
     computing `padding=-overlap` from the plan's segments alongside the per-clip `CrossFadeIn` —
     confirmed empirically (isolated probe: 4×0.5s clips, 0.1s overlaps → exactly 1.7s, matching
     `plan_timeline`'s own math). **Limitation**: `padding` is one scalar for the whole
     concatenation, so this assumes a uniform overlap across the plan — true of every plan
     `plan_timeline` builds today (one `crossfade_seconds` for the whole timeline); a future
     per-pair-varying overlap would need a different concatenation strategy (flagged in the code).
  3. **WebM/Opus audio silently produces a ZERO-BYTE file** unless the audio sample rate is one
     Opus actually legal-izes (8000/12000/16000/24000/48000 Hz) — the AAC-typical 44100 Hz fails
     with NO error raised at all (`MoviePy - Done.` logged, 0-byte file). Fixed by forcing
     `audio_fps=48000` for WebM output. **Separately**, MoviePy's codec→extension lookup table
     (`moviepy.tools.extensions_dict`) has no `"libopus"` entry, so `write_videofile` raises
     `ValueError: The audio_codec you chose is unknown by MoviePy` unless an explicit
     `temp_audiofile` with a recognized extension (`.ogg`) is supplied, bypassing that lookup.
  4. **Bonus finding, same diagnostic session**: MoviePy's `temp_audiofile_path` defaults to `""`
     (an empty string), so the intermediate audio-mux temp file is written **CWD-relative**, not
     next to the real output — this silently works in a coincidentally-writable cwd and fails
     unpredictably otherwise (`"Error opening input file sceneTEMP_MPY_wvf_snd.mp4"`, "No such file
     or directory"). Fixed by always pinning `temp_audiofile_path=str(Path(output_path_str).parent)`
     for EVERY output format (not just the Opus branch) — this was silently broken in the ORIGINAL
     `_moviepy_assemble` too, just never exercised by a test that actually ran ffmpeg for real.
  All four are documented in `assembly.py`'s own module docstring and inline comments for the next
  engineer, not just here.
- Audio modes: `"native"` leaves each clip's own audio untouched; `"separate"` strips it and
  attaches narration via `CompositeAudioClip([narration]).with_duration(edit_seconds)` — verified
  empirically (isolated probe) that MoviePy correctly pads the composite with silence past the
  narration's own shorter extent rather than erroring or looping; `"muted"` strips all audio, no
  narration/music attached. Music (when `audio_mode="separate"` and `music_path` given) loops or
  trims to the final assembled duration and is volume-scaled, mirroring the ORIGINAL
  `_moviepy_assemble`'s own (verified, unchanged) approach.
- Cleanup: ALL MoviePy clip objects (`clips`, `music`, `final_video`) are closed in the worker
  process's own `finally` block, regardless of success or failure — verified via
  `TestCancellationAndTermination` that no child process/clip resource leaks past a cancelled call
  (`multiprocessing.active_children() == []` after settling).
- **Deviation — one file outside this task's list was touched**:
  `packages/ai-parrot/tests/test_video_reel_storage.py`. Its pre-existing
  `test_assembly_uploads_final` mocked the ENTIRE `parrot.clients.google.generation.asyncio` module
  and stubbed `asyncio.to_thread` to return the fake final path directly — a mocking strategy
  tightly coupled to the OLD implementation's exact single-`asyncio.to_thread()`-call shape. Since
  this task's own Scope explicitly mandates delegating to a managed PROCESS (not
  `asyncio.to_thread` for the encode at all, and `asyncio.to_thread` is now used only for the
  per-scene duration probe), that mock broke unconditionally regardless of how correctly the
  delegation was implemented — every `asyncio.to_thread` call, including the unrelated duration
  probes, was being intercepted uniformly and returned a `Path` where a `float` was expected
  (`ValidationError: edit_seconds ... Input should be a valid number`). Fixed the ONE affected test
  to mock `moviepy.VideoFileClip` (duration probe) and `reel.assembly.assemble_reel` (the actual
  encode) directly instead of blanket-mocking `asyncio` — this tests OBSERVABLE behavior
  (`file_manager.upload_file` called, `result` key shape) rather than a private implementation
  detail, matching this repo's own test-writing guidance. Confirmed via isolated runs that the
  OTHER 3 failures in that file (`TestFileManagerFactory::test_create_temp`/
  `test_create_invalid_raises`, `TestHandlerStorageConfig::test_temp_backend`) are PRE-EXISTING,
  unrelated `navigator-api`/`FileManagerFactory` environment drift (`FileManagerFactory.create`
  returns `LocalFileManager` instead of `TempFileManager` — nothing this task touches) — left as-is,
  not caused by and not fixed by this task.
- AC04, AC05, AC06, AC12 (owned by this task): covered by the 12 tests in `test_reel_assembly.py`
  using REAL tiny MoviePy-generated clips (ColorClip, no network — matching the spec's own
  `tiny_clip` fixture pattern): playable MP4/AAC and WebM/Opus output, cut/crossfade total-duration
  fidelity within one frame, narration padding never stretching the clip, muted/native audio-track
  presence, unsupported-format/encoder-failure error surfacing, concurrent jobs never overwriting
  each other's output, direct `_terminate_and_join` mechanism test, and cancellation-leaves-no-
  child-process.
- Tests: `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_assembly.py -q` — 12
  passed (~30s — real ffmpeg encoding, kept fast via 64x64/≤1s clips). Full `tests/unit/reel/`
  directory — 153 passed. `test_video_reel_storage.py` — 22 passed, 1 skipped, 3 pre-existing
  unrelated failures (see deviation note above). `test_google_reel.py` — 7 passed. Same temporary
  main-checkout `.so` copy-then-remove as prior tasks; nothing committed.
- Lint: `ruff check` found one real issue in my new file (`ASYNC240` blocking `Path.mkdir` in an
  async function — fixed via `run_in_executor`) plus pre-existing, far-removed `generation.py`
  findings (`ASYNC240`/`F821` at the same lines as before, just shifted by my insertion — confirmed
  via exact line-content inspection) left for `/sdd-done`'s feature-wide pass. `black --line-length
  120` reformatted 3 of the 4 touched files (wrapping only); re-ran the full regression sweep after
  reformatting — still 153/22/7 passed.
- No live-service claims inferred from mocks; no default test performs a paid provider call.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a (fallback, not MCP/native-agent timed) · Tokens: n/a
