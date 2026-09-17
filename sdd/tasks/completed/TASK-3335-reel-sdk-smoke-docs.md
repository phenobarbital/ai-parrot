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

Completed-by: sdd-worker (fallback sequential loop, orchestrator-implemented) · Date: 2026-09-17

### ⚠️ Safety incident disclosed in full — read before running this suite

While manually verifying the opt-in smoke suite's skip guard (a deliberate,
supervised check — running `PARROT_TEST_LIVE_GOOGLE=1 pytest
packages/ai-parrot-client-google/tests/live/test_reel_smoke.py` **without**
`GOOGLE_API_KEY` in this shell's raw environment, expecting a skip), all 5
tests instead **executed** and attempted real network calls (one traceback
frame reached `reel/music.py`'s `client.aio.live.music.connect(...)`),
failing after ~14s each (71s total) — almost certainly connection
timeouts/auth rejections, not successes. **Root cause**:
`GoogleGenAIClient.__init__` resolves `api_key` via
`config.get("GOOGLE_API_KEY")` (`navconfig`'s config, e.g. a `.env` file
under this repo's `settings/` directory), **not** `os.environ` — confirmed
by reading `client.py:189`. This environment apparently has a real
`GOOGLE_API_KEY` configured via `navconfig` for unrelated dev/testing
purposes, invisible to a raw `os.environ` check (confirmed empty via three
independent methods: shell `env | grep`, a standalone Python script, and a
subprocess-matching diagnostic). My original skip condition checked only
`os.environ`, so it incorrectly evaluated "no credentials" while the
CLIENT itself found one anyway via a different path. **No evidence any
call actually completed successfully** (all 5 failed) and no billable
resource is believed to have been created, but this is a genuine, if
narrowly-averted, safety gap — reported honestly rather than glossed over.

**Fix — three independent, redundant layers**, so a flaw in any one does
not silently let a real call through:
1. Kept the original `@pytest.mark.skipif` decorator (checks raw
   `os.environ` for both `PARROT_TEST_LIVE_GOOGLE=1` and a credential var).
2. Added `tests/live/conftest.py`'s `pytest_collection_modifyitems` hook —
   independently re-checks the SAME raw-`os.environ` condition and
   force-applies a skip marker to every item collected under `tests/live/`
   regardless of what the test module declared. This is the EXACT pattern
   already proven in `packages/ai-parrot/tests/conftest.py` for its own
   `real_llm` marker — not a novel mechanism.
3. Every test now constructs its client as
   `GoogleGenAIClient(api_key=os.environ["GOOGLE_API_KEY"])` explicitly —
   never a bare `GoogleGenAIClient()` that could silently resolve a
   navconfig-configured key. If somehow reached without `GOOGLE_API_KEY`
   in raw `os.environ`, this now raises `KeyError` immediately.

Re-verified the DEFAULT (no env vars set) case after the fix: 5 skipped,
0.26s, `--collect-only` and a full-suite run both confirm no network
activity. **Did NOT re-run the "opted in without a real key" case again**
after the fix — doing so was the exact action that caused the incident,
and re-attempting it (even to "prove" the fix) would reintroduce the same
risk if my fix has any remaining gap I haven't found. The fix is a
well-established, already-proven pattern (item 2) plus two additional
independent hardening layers, verified by careful code reading rather
than by repeating the dangerous experiment.

### Dependency floor evidence (AC15)

Verified via direct introspection of the INSTALLED SDK (2.23.0; this
workspace's `uv.lock` currently resolves 2.24.0, not separately verified
and not claimed) — `google.genai.Client(...).aio.models.generate_videos`,
`.operations.get`, `.files.download`, `.interactions.create`,
`.live.music.connect`, `.aclose` all present with signatures matching how
the reel adapters actually call them (parameter names checked via
`inspect.signature`, not guessed). `packages/ai-parrot-client-google/pyproject.toml`'s
floor raised `>=2.18.1` → `>=2.23.0`; `uv.lock`'s mirrored
`requires-dist` entry for `ai-parrot-client-google` updated to match
(the resolved `2.24.0` entry itself is untouched — it already satisfies
the new, tighter floor, so no re-resolution was needed or attempted; `uv
sync`/`uv lock` were never run, per this task's explicit instruction).

### Marker registration (AC16)

`live_google` registered in both `pytest.ini` (root, the config that
actually governs plain `pytest ...` invocations from the repo root per
pytest's file-priority rules) and `pyproject.toml`'s
`[tool.pytest.ini_options]` (the alternate config, which additionally
enforces `--strict-markers`) — confirmed via `pytest --markers` showing
the registered description, and via a full-suite run showing zero
"unknown marker" warnings/errors anywhere in either `ai-parrot-server`
(583 passed) or `ai-parrot` (184 passed) regression sweeps.

### `test_reel_sdk_contract.py` (AC15, AC18)

10 tests, all introspection-only (verified: constructing
`genai.Client(api_key="fake...")` is lazy and makes no request — confirmed
by reading the SDK source, not assumed). Covers the version-floor
assertion, all 5 async surfaces above, and two lazy-import checks
(`ast`-parses `video_reel.py` to confirm no module-level `google.genai`
import, and confirms the `GoogleGenAIClient` import inside `run_logic()`
is indented/function-local — a static, structural check rather than a
`sys.modules`-manipulation trick).

### Migration doc (AC16, AC18)

`docs/migration/video-reel-omni-veo-reliability.md` covers every item
this task's scope demands: legacy `model` alias behavior, stage models
(director/image/video + mixed Veo/Omni), duration/edit policy (covering
duration selection + `insufficient_duration`), audio/music policy
(`audio_mode` × `music_policy` matrix), result URLs and job ownership
(§8 Q7 — closed by TASK-3333, full cross-reference), tested SDK versions
(the table above), disabled Vertex entries (`enabled=False` on both
GA profiles, rationale), and the four still-**open** evidence gates
(Q3/Q4/Q5/Q6) — explicitly NOT claimed resolved anywhere, including by
this task's own smoke suite (a successful smoke run, if one were ever
performed, would only confirm the specific scenario it exercised — never
a blanket "live-ready" claim).

### Deviation — `tests/live/conftest.py` not in the declared Files list

Not itemized in this task's "Files to Create / Modify" table, but created
as a direct, necessary structural + safety companion to
`test_reel_smoke.py` (the ONE file the table DOES list) — the redundant
collection-time skip gate described above. Same category as
`tests/live/__init__.py` (a bare package marker, matching every sibling
test directory's convention): a structural necessity of the CREATE'd
file, not independent new scope.

### Tests

`test_reel_sdk_contract.py` — 10 passed. `test_reel_smoke.py` (default,
no opt-in) — 5 skipped, 0.26s, no network. Full regression:
`ai-parrot-client-google` — 216 passed, 5 skipped (57.71s). `ai-parrot-server/
tests/handlers/` — 583 passed, 4 skipped, 2 failed (`test_agent_a2ui_stream.py`,
confirmed unrelated — zero A2UI files in this feature's diff). `ai-parrot`
reel-related files + `test_google_client.py` — 184 passed.

`black --check`/`ruff check`: clean on all 9 touched/created files. Full
feature-diff sweep (34 Python files across all 5 completed TASK-332x/333x
tasks): same 6 pre-existing, untouched-line residual findings documented
since TASK-3331/3334 (2× `PIE796` in an unrelated `GoogleVoiceModel` enum,
4× `E402` in a 1170-line shared test file's per-feature-section imports) —
nothing new.

### No live-service readiness claim

Explicitly documented in the migration doc's own closing section: Q3
(Omni URI auth), Q4 (image model id), Q5 (Vertex Veo 3.1 GA), and Q6
(Lyria api_version/PCM) all remain open. This task's test evidence is
mock-only (`test_reel_sdk_contract.py`) or opt-in-and-skipped-by-default
(`test_reel_smoke.py`) — no claim of live-service readiness is inferred
from either.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a · Tokens: n/a
