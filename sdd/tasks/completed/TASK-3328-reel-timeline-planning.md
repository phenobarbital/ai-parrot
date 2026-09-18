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

Completed 2026-09-17 by sdd-worker orchestrator (fallback sequential loop, sonnet).

- `TimelineEntry`/`TimelineSegment`/`TimelinePlan` (Pydantic v2) and `plan_timeline()`,
  `check_measured_duration()`, `check_narration_fits()` — pure functions, no MoviePy/provider
  calls/I/O (verified: only stdlib `math` + Pydantic imports).
- **`TimelinePlan` dependency interface for the assembly task (documented per Scope bullet 2)**:
  `TimelinePlan.segments: List[TimelineSegment]`, each carrying `scene_index` (original index,
  preserved even with gaps — e.g. only scenes 0 and 3 survived), `clip_path`, `start_seconds`
  (absolute position in the final timeline), `edit_seconds` (this segment's own duration,
  unchanged from the entry), `narration_path`, and `overlap_with_next_seconds` (crossfade overlap
  consumed with the NEXT segment; `0.0` for cut or the last segment). `TimelinePlan.fps` and
  `.final_duration_seconds` are top-level. The assembly task should read `start_seconds` +
  `overlap_with_next_seconds` directly rather than recomputing placement — this IS the one
  explicit plan the spec's M6 responsibility names.
- Cuts: `final_duration_seconds` = Σ `edit_seconds`. Crossfades: subtracts Σ actual consumed
  overlaps (`crossfade_seconds` between each adjacent pair, `0.0` after the last segment). Four 5s
  scenes → 20s cut / 18.5s crossfade (three 0.5s overlaps), matching AC05 exactly.
- Validation: `fps` must be finite and > 0; every `edit_seconds` must be finite and > 0; a
  crossfade's `crossfade_seconds` must be finite, non-negative, and **strictly shorter than BOTH**
  neighboring scenes' durations (`>=` rejected, not just `>`) — an overlap consuming an entire
  scene leaves nothing of that scene to show. Empty `entries` rejected.
- `check_measured_duration(target, measured, fps)`: one-frame tolerance = `1.0/fps`; raises
  `ReelError(INSUFFICIENT_DURATION)` only when `measured < target - tolerance` — exactly at the
  tolerance boundary passes (tested), longer-than-target never raises. Never loops/stretches/
  regenerates — the function only ever raises or returns.
- `check_narration_fits(target, narration_seconds)`: raises `ReelError(NARRATION_TOO_LONG)` only
  when narration EXCEEDS target (`==` passes); shorter narration is left untouched (padding with
  silence is a later assembly-stage concern, not this function's).
- Both duration-check functions raise `ReelError` (not `ReelValidationError`) since they run
  AFTER generation/measurement, not before a paid call — consistent with `ReelValidationError`
  being reserved for pre-paid-call registry/config validation (TASK-3322's distinction).
- **Lint finding during self-review, fixed before commit**: `ruff` B905 (`zip()` without explicit
  `strict=`) on the offset-by-one neighbor-pairing loop — added `strict=False` explicitly (the two
  slices are deliberately unequal length by one).
- AC04, AC05 (owned by this task): covered by the 20 tests in `test_reel_timeline.py` (cut/
  crossfade totals, original-index preservation under skip, single-entry plan, empty-entries/
  invalid-fps/invalid-edit-seconds/negative-crossfade rejection, overlap-equal-to-and-longer-than-
  neighbor rejection, zero-crossfade degenerate case, measured-duration exact/boundary/short/long
  cases, narration exact/within/overflow/shorter cases).
- Tests: `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_timeline.py -q` — 20
  passed. Full `tests/unit/reel/` directory — 107 passed. Same temporary main-checkout `.so`
  copy-then-remove as prior tasks; nothing committed.
- Lint: `ruff check` — all checks passed (after the B905 fix). `black --line-length 120`
  reformatted `timeline.py` (wrapping only); re-ran both suites after reformatting — still 107/20
  passed.
- No live-service claims inferred from mocks; no default test performs a paid provider call. No
  files outside the task's two listed targets were created or modified. `generation.py` was NOT
  touched (Implementation Notes: "no generation.py changes" — confirmed).

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a (fallback, not MCP/native-agent timed) · Tokens: n/a
