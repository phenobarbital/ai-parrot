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

Completed 2026-09-17 by sdd-worker orchestrator (fallback sequential loop, sonnet).

- `OmniClipAdapter(owner, downloader, *, max_download_bytes=200MiB)` with the spec's
  `generate(*, profile, prompt, output_directory, aspect_ratio, resolution, target_duration_seconds,
  starting_frame, deadline) -> GeneratedReelClip` signature (matches VeoClipAdapter's shape exactly,
  though `resolution`/`starting_frame` are not applicable to Omni — documented in the docstring).
  Calls `client.aio.interactions.create(agent=<model>, input=<prompt>, background=False,
  store=False, stream=False, response_format={"type":"video","aspect_ratio":...}, timeout=<remaining
  deadline seconds>)` — the public async surface, never `GoogleGenAIClient._deep_research_ask`'s
  synchronous `client.interactions.create(..., stream=True)` streaming pattern (client.py:5153,
  confirmed via read, not copied). No `duration` key in `response_format` (unverified legal values
  — spec explicitly forbids inventing one), no `temperature`/`negative_prompt` (verified absent from
  the built kwargs in tests).
- **Q3 evidence gate (response SHAPE only, not the download-auth question — see TASK-3325's note for
  that half)**: `Interaction.status`/`.errors`/`.output_video` → `VideoContent.data`/`.uri`/
  `.mime_type`, and the legal `InteractionStatus` values (`in_progress`, `requires_action`,
  `completed`, `failed`, `cancelled`, `incomplete`, `budget_exceeded`, `queued`) were verified via
  **offline `inspect.getsource`/enum-introspection of the installed `google-genai` 2.23.0 package**
  (`google.genai._gaos.types.interactions.{interaction,videocontent,videoresponseformat}` — evidence
  only, never imported in `omni.py` itself, per the Codebase Contract's "internal SDK files are
  evidence, not import paths"). **Not verified**: an actual live Omni response was never observed: no
  concrete duration values, no confirmed safety-block signal/reason string (Omni's `Error.code`/
  `.message` shape is generic; my classifier does not infer `SAFETY_BLOCKED` for Omni failures —
  every terminal-status failure maps to `PROVIDER_FAILURE` via `OperationFailure`, which is the
  conservative, evidence-honest choice given "never infer safety... solely from" a generic error).
  `Interaction.output_audio`/`.output_image` exist on the same model but no separate-audio-track
  signal was found — audio presence is verified from the DOWNLOADED FILE itself via moviepy, not
  from any Omni response field.
- **Design decision — public `google.genai.types.VideoResponseFormat` is NOT the same class**: the
  top-level `google.genai.types` module re-exports a DIFFERENT `VideoResponseFormat` belonging to the
  Veo/`GenerateVideosConfig` world (confirmed: constructing it with `aspect_ratio="16:9"` emits a
  `UserWarning: 16:9 is not a valid AspectRatio` and produces `Delivery.INLINE`-style uppercase
  enums, inconsistent with the Interactions-side field shape verified above). To avoid importing the
  private `_gaos` path, `response_format` is built as a **plain dict** — `create()`'s own signature
  is `(self, *, request=None, ..., **body: Any)`, so the SDK's internal validation (not this
  adapter's) discriminates the dict against its own `InteractionResponseFormat` union. This is
  unverified against a live call; flagging for reviewer attention alongside Q3.
- Base64 inline decoding: `is not None` (not truthiness) gates the data/URI branch — an
  explicitly-empty `data=""` field (valid, zero-length base64) must reach the "decoded to zero
  bytes" check, not be misclassified as "no output at all" (a real bug caught by my own test:
  `base64.b64encode(b"")` legitimately produces `""`, which is falsy in Python — fixed before
  commit, both code and the test's own assumption were wrong the first time).
- URI delivery goes through TASK-3325's `ProviderMediaDownloader.fetch()` (its
  `DEFAULT_CREDENTIAL_ORIGINS` allowlist decision for Omni is still unverified — see that task's own
  Completion Note); its `DownloadFailure` is normalized via `classify_provider_error`.
- `submitted_duration_seconds` is always `None` (never sent, matches `profile.durations_seconds is
  None`); the measured output is checked against `target_duration_seconds` with a documented
  ASSUMED one-frame tolerance at 24fps (`_ASSUMED_FPS_FOR_TOLERANCE` — Omni's actual output fps is
  itself unverified; flagged, not silently assumed correct).
- Ambiguous creation failures are never retried (one `interactions.create` call; any exception
  classifies and raises immediately — verified via `create.assert_awaited_once()` implicitly by
  every failure-path test only calling it once). The client is owned and closed
  (`await client.aio.aclose()`) on every exit via `try/finally` — applied `_pattern learned from the
  TASK-3324 self-caught defect` from the start this time (no separate fix needed here).
- `starting_frame` is rejected BEFORE any client call at all (`owner.get_client` never invoked) since
  `profile.supports_starting_frame=False` — defensive validation independent of upstream
  orchestration's own checks.
- AC01, AC04, AC06, AC12, AC17 (owned by this task): covered by the 16 tests in `test_reel_omni.py`
  (create-kwargs shape/no-Veo-fields, inline+URI delivery, MIME→extension mapping, malformed
  base64/empty-decoded/no-output/neither-data-nor-uri, terminal-status + operation-id preservation,
  unexpected in-progress status, insufficient-duration, download-failure normalization,
  starting-frame/expired-deadline rejection before submission, cancellation + client-close).
- Tests: `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_omni.py -q` — 16 passed.
  Full `tests/unit/reel/` directory — 123 passed. Same temporary main-checkout `.so` copy-then-remove
  as prior tasks; nothing committed.
- Lint: `ruff check` — all checks passed on first run (no findings this time). `black --line-length
  120` — no changes needed.
- No live-service claims inferred from mocks; no default test performs a paid provider call. No
  files outside the task's two listed targets were created or modified.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a (fallback, not MCP/native-agent timed) · Tokens: n/a
