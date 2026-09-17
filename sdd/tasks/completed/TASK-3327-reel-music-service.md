# TASK-3327: Music policies, isolated Lyria session and PCM encoding

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3324
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

## Context

Implements M5 of spec §3 and contributes to AC06, AC09, AC12. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Implement MusicOutcome, ReelMusicService.generate and write_pcm_wav per §3 M5.
- Resolve Q6 API version and PCM metadata from verified contract/stream evidence before encoding; do not guess 44.1 versus 48 kHz. Preserve public stream defaults for existing callers while supporting an injected owned client/version for reels.
- off makes no call; optional returns warning and structured failure; required raises. Native/muted skip Lyria. Preserve synthesized music prompt in optional separate mode.
- Bound connection/receive time and bytes, join receiver tasks on cancellation, and close exactly the clients owned by this service.
- Write WAV with matching sample width/channels/rate and .wav path; keep speech encoder unchanged.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/music.py` | CREATE | MusicOutcome, service and PCM WAV writer |
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | MODIFY | Add injected client/API version support to generate_music_stream |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_music.py` | CREATE | Music policy and PCM tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google.generation import GoogleGeneration
from parrot.clients.google import GoogleGenAIClient
from parrot.models.google import VideoReelRequest, VideoReelScene
```

### Existing Signatures to Use

- `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1162`: async generate_music_stream(self, prompt, genre=None, mood=None, bpm=90, temperature=1.0, density=0.5, brightness=0.5, timeout=300) -> AsyncIterator[bytes]; _generate_reel_music(self, request, output_dir, file_manager=None, job_prefix=None) -> Optional[str]. Stream forces v1alpha at line 1196.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_music_stream`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._generate_reel_music`.
- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:630`: async get_client(self, model: str = None, **kwargs) -> genai.Client constructs a fresh client; async close(self) -> None delegates to close_all. Directly created clients require explicit ownership.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close`.
- `packages/ai-parrot/src/parrot/models/google.py:376`: VideoReelScene.duration: float = 5.0; VideoReelRequest._parse_json_strings(cls, v) is a before validator for scenes/speech.
  Symbols: `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene`, `sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest`.

### Dependency Interfaces

- Read the completed TASK-3324 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/src/parrot/clients/google/reel/music.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_music.py` does not exist at task creation; create it within this task.
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
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/music.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/generation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_music.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_music_stream",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration._generate_reel_music",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelScene",
    "sym:packages/ai-parrot/src/parrot/models/google.py#VideoReelRequest"
  ]
}
```

## Implementation Notes

Q6 must be closed with evidence or reported as a precise blocker. No private-allowlist assumption or new music dependency.

generation.py is serialized by dependencies: TASK-3324 -> TASK-3327 -> TASK-3329 -> TASK-3330 -> TASK-3331. Other ready tasks with disjoint files may run.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3327-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Implement MusicOutcome, ReelMusicService.generate and write_pcm_wav per §3 M5.
- [ ] Resolve Q6 API version and PCM metadata from verified contract/stream evidence before encoding; do not guess 44.1 versus 48 kHz. Preserve public stream defaults for existing callers while supporting an injected owned client/version for reels.
- [ ] off makes no call; optional returns warning and structured failure; required raises. Native/muted skip Lyria. Preserve synthesized music prompt in optional separate mode.
- [ ] Bound connection/receive time and bytes, join receiver tasks on cancellation, and close exactly the clients owned by this service.
- [ ] Write WAV with matching sample width/channels/rate and .wav path; keep speech encoder unchanged.
- [ ] AC06, AC09, AC12 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Off/native/muted no connection; optional unavailable/timeout/empty; required raises
- PCM sample-count/channel/rate round trip and WAV suffix
- Injected client ownership, receiver cancellation and version isolation

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_music.py -q
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

- `MusicOutcome`, `ReelMusicService(owner, *, api_version, connect_timeout_seconds=10.0,
  max_bytes=20MiB).generate(request, *, duration_seconds, output_directory, deadline) ->
  MusicOutcome`, and `write_pcm_wav(pcm, dest, sample_rate, channels, sample_width) -> Path` — all
  per §3 M5. `generate_music_stream` gained optional `client=`/`api_version=` kwargs (19-line diff,
  confirmed via `git diff --stat`); existing callers are byte-for-byte unaffected (both default to
  `None`, preserving the hardcoded `"v1alpha"` build path).
- **Q6 resolution ("do not guess 44.1 vs 48 kHz")**: F011's finding is that the repo's own docs say
  48kHz while Google's public Lyria guide's player example uses 44.1kHz — genuinely conflicting, no
  live call possible to settle it directly. Resolved differently: `google.genai.types.AudioChunk` has
  a REAL wire field `mime_type: Optional[str]` (verified via `inspect.getsource` on the installed
  SDK) using Google's `"audio/pcm;rate=<hz>"` convention. `ReelMusicService` implements its OWN
  receive loop (does NOT reuse `generate_music_stream`, which only yields bytes and discards
  `mime_type`) specifically to read the ACTUAL declared rate from each chunk at runtime — never
  hardcoded. If no chunk ever declares a parseable rate, or declared rates disagree mid-stream,
  generation fails closed (`status="unavailable"`) rather than guessing — this is the load-bearing
  behavior verified by `test_missing_mime_type_rate_never_guessed` and
  `test_inconsistent_declared_rates_returns_unavailable`.
- **NOT wire-verified, flagged distinctly from the rate**: channel count (stereo) and sample width
  (16-bit). No `mime_type` sub-field carries these. Stereo comes from `generate_music_stream`'s own
  docstring; 16-bit is the universal PCM convention across this SDK family (matches
  `AbstractClient._save_audio_file`'s speech encoder at `2697`, which is mono/16-bit/24kHz — music
  deliberately does NOT reuse that encoder, satisfying the spec's Integration Points table:
  "Speech keeps using it; music gets its own PCM→WAV writer so speech assumptions do not leak").
  `_MUSIC_CHANNELS`/`_MUSIC_SAMPLE_WIDTH` module constants are named/commented to make this
  distinction explicit for whoever verifies Q6 with a live call later.
- Policy/mode behavior: `audio_mode in {"native","muted"}` skips Lyria entirely, checked BEFORE
  `music_policy` (no connection, regardless of policy). `music_policy="off"` also makes no
  connection. `"optional"` (default) returns a structured `MusicOutcome` with a `warning` on any
  failure — never raises. `"required"` raises `ReelError(PROVIDER_FAILURE)` on any failure.
  Synthesized prompt (`music_prompt` absent → `f"Background music for {request.prompt}"` +
  genre/mood) matches the existing `_generate_reel_music`'s own convention verbatim (including its
  enum-repr-not-value quirk in the f-string — not "fixed" here since it's pre-existing, unrelated
  behavior this task doesn't own).
- Isolated ownership: builds its own client via `owner.get_client(http_options={"api_version":
  self._api_version})` — never shared with director/video clients — and closes it
  (`await client.aio.aclose()`) in a `finally` on every exit (learned from the TASK-3324 self-caught
  defect; applied correctly from the start here, no separate fix needed).
- Bounds: connect handshake wrapped in `asyncio.wait_for(..., timeout=min(connect_timeout_seconds,
  remaining))`; total received bytes tracked and aborted past `max_bytes`; the overall receive loop
  is bounded by `min(duration_seconds + 5.0, deadline - now)`. The receiver task is always
  cancelled-and-joined (`receiver_task.cancel()` + `await` inside `contextlib.suppress
  (CancelledError)`) in a `finally`, verified by `test_receiver_task_joined_on_cancellation`
  (external cancellation of `generate()` mid-stream still closes the owned client).
- `_generate_reel_music` (generation.py:2249, the CURRENT caller with the `bg_music.mp3`-for-a-WAV-
  file naming bug from spec §1/F003) was deliberately NOT touched — spec Module 7's own interface
  skeleton lists `:2249 (_generate_reel_music → M5)` as **TASK-3330's** responsibility (rewiring
  orchestration to call `ReelMusicService` instead). Confirmed via `git diff --stat` that only
  `generate_music_stream`'s signature/docstring changed.
- AC06, AC09, AC12 (owned by this task): covered by the 18 tests in `test_reel_music.py` (off/
  native/muted no-connection short-circuits, successful WAV write with verified-rate/documented-
  stereo-16bit round-trip, injected api_version, synthesized-prompt preservation, connection-
  failure/handshake-timeout/empty-stream/missing-rate/inconsistent-rate/byte-limit → all
  `"unavailable"`/`"timeout"` outcomes for `optional`, `required` raising on failure and succeeding
  normally when available, receiver-task-joined-on-cancellation, `write_pcm_wav` round-trip +
  `.wav`-suffix enforcement + invalid-metadata rejection).
- **Test speed self-fix before commit**: my first fake `_FakeSession.receive()` unconditionally hung
  (`asyncio.sleep(3600)`) after exhausting its chunk list — meaning every test without an explicit
  terminal error waited out its full ~5s receive budget before the loop naturally exited, making the
  18-test file take 31s. Fixed by making the fake stream end normally by default (`hang=False`),
  reserving the hang behavior for the one test that actually needs an externally-cancellable
  connection — cut runtime to ~1s with identical assertions/coverage.
- Tests: `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_music.py -q` — 18
  passed (~1s). Full `tests/unit/reel/` directory — 141 passed. `test_lyria_batch.py` (existing,
  unrelated `generate_music_batch` tests) — 19 passed, 3 pre-existing failures confirmed unrelated:
  `TestLyriaBatchIntegration::test_*` are `@pytest.mark.integration` tests making REAL live calls to
  `https://global-aiplatform.googleapis.com/...` (no network/credentials in this sandbox; a
  different method, `generate_music_batch`, that this task never touched). Same temporary
  main-checkout `.so` copy-then-remove as prior tasks; nothing committed.
- Lint: `ruff check` found one real issue in my new file (`F401` unused `pydantic.Field` import —
  fixed) plus pre-existing, far-removed `generation.py` findings (`ASYNC240`/`F821` at lines
  1746/1968/2473/2514, confirmed outside this task's 19-line diff via `git diff --stat`) left for
  `/sdd-done`'s feature-wide pass. `black --line-length 120` reformatted `music.py`/
  `test_reel_music.py` (wrapping only); re-ran the full suite after reformatting — still 141 passed.
- No live-service claims inferred from mocks; no default test performs a paid provider call or a
  real network call. No files outside the task's three listed targets were created or modified.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a (fallback, not MCP/native-agent timed) · Tokens: n/a
