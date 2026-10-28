---
type: feature
base_branch: dev
projects: [ai-parrot-server, ai-parrot-tools]
tags: [e2e, playwright, obscura, observability, exploration]
---

# Feature Specification: Operational screencast logs for the E2E `browser` exploration flow

**Feature ID**: FEAT-762
**Date**: 2026-10-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor
**Implementation gate**: M0 PASSED for an in-connection recorder (Playwright `CDPSession` on the automation connection) — see `sdd/state/FEAT-762/screencast-spike.md`. Spec revised 2026-10-28 for the in-process design; M1–M3 are ready for `/sdd-task`.

---

## 1. Motivation & Business Requirements

### Problem Statement

`e2e-ui-tester` — the optional exploratory subagent for FEAT-581's E2E
`browser`/`ui` fixture targets — attaches to a supervised Obscura CDP
endpoint and today only captures a single PNG screenshot "on any
unexpected finding." When an exploration run surfaces a real anomaly
(an unexpected console error, a 5xx network response), that one still
frame is the only visual evidence available. Recording after detection can
capture follow-up investigation or an explicit reproduction, not recover the
interaction history before recording began.

The existing `PlaywrightConfig.record_video_dir` path cannot satisfy this
trigger: `_start_obscura_cdp()` reuses an existing context and does not apply
context-creation options to it. By the time an anomaly is observed, a page
and context already exist. The recorder must attach to that exact existing
page without replacing or closing it. This revision supersedes the proposal's
fresh-context mechanism; its on-anomaly trigger and operational-log scope remain.

### Goals

- Record the existing exploration page after its first anomaly, producing
  `artifacts/logs/e2e/<run-id>/screencast.webm` as an operational log.
- Start capture only on anomaly. A clean run creates no recording session
  or video. Label the video as post-detection evidence; reproduce the issue
  while recording when practical, without claiming retrospective capture.
- Prove the complete active-page capture and WebM encoding path against
  real Obscura v0.2.2 before implementing M1–M3.
- Fail with a typed error for an unavailable page, unsupported capture,
  missing encoder, or empty/invalid output. Existing contexts are expected
  and must not themselves cause rejection.

### Non-Goals (explicitly out of scope)

- **Always-on recording for a future, bounded deterministic UI
  scenario.** The hybrid trigger decided during the proposal phase
  (`sdd/proposals/e2e-browser-screencast-logs.proposal.md` §5) applies
  that always-on half only once such a deterministic scenario exists in
  FEAT-581's plan — it does not exist today, so it is deferred to a
  follow-up feature, not built speculatively here.
- **Retention / rotation / size-cap for `artifacts/logs/e2e/`.** Decided
  out of scope in the proposal (U3); documented as an accepted,
  deferred risk in §7 Known Risks.
- **Any change to the deterministic gate's evidence schema.**
  `parrot.e2e.models.E2EVerdict`, `parrot.e2e.runner.run_plan`, and the
  before/after source-identity hash are untouched. A screencast is never
  wired into `sdd/state/<FEAT-ID>/e2e/runs/<run-id>/`.
- **Any change to `parrot.e2e.targets.browser._BrowserAdapter`.** It
  keeps spawning `obscura serve` and checking readiness; it never becomes Playwright-aware itself.
- **`e2e-api-tester`** — no browser surface, out of scope.

---

## 2. Architectural Design

### Overview

> **Design revision (M0 outcome, decision (a), 2026-10-27/28).** Obscura 0.2.2
> isolates pages per CDP connection (spike evidence:
> `sdd/state/FEAT-762/screencast-spike.md`): a second connection sees no
> targets, so a detached recorder process cannot attach to a page. Recording
> therefore runs **inside the process that owns the Playwright connection**,
> through a `CDPSession` of the exact `Page` object. The CLI daemon, tickets
> and `page_target_id` of the previous revision are dropped. A DevTools MCP
> tool the agent may use for driving the page holds a *different* connection and
> cannot be recorded; recording is available only to Playwright scripts.

`parrot.e2e.screencast` provides (1) a recorder bound to a caller-supplied
Playwright `Page` and (2) an anomaly-triggered async context manager,
`record_on_anomaly`, that watches that page for the anomalies the exploration
already cares about (console `error` messages and HTTP 5xx responses) and
starts the recorder only on the first one. A clean run creates no session or
video. The output `artifacts/logs/e2e/<run-id>/screencast.webm` is labelled
post-detection operational evidence: it captures follow-up investigation or
reproduction, never the history before detection.

`e2e-ui-tester` (Bash + Write) drives exploration by writing and running a
short Python/Playwright script that connects to the owned Obscura endpoint
(`parrot e2e up` reports it; the script uses `connect_over_cdp`) and wraps its
investigation in `async with record_on_anomaly(page, out_dir, run_id=...)`.
The context manager stops capture on every exit path (normal, exception,
cancellation) **before** the script returns, hence before `parrot e2e down`.
Only a successful stop yields a path for `evidence_refs`; a recorder failure
is logged and reported as an `unavailable` observation, never raised into the
script, and never prevents target teardown or the exploration report.

Recorder contract: capture via Playwright `BrowserContext.new_cdp_session(page)`;
frames are acknowledged immediately; the bounded frame buffer overflows to an
explicit `E2EScreencastError` (never a silently truncated success); on stop the
recorder calls `Page.stopScreencast`, detaches, drains acks, encodes in a
process (`ProcessPoolExecutor`), decode-validates the file, then atomically
publishes `screencast.webm` (refusing to overwrite an existing one). It never
closes the page, context or browser. The encoder is the optional
`ai-parrot-server[screencast]` extra (`av`, `pillow`); when it is missing the
failure is a typed `E2EScreencastError` naming the extra.

### Component Diagram

```text
e2e-ui-tester ── writes/runs ──> exploration script (Playwright, connect_over_cdp)
                                   └─ async with record_on_anomaly(page, out_dir)
                                        ├─ page.on("console"/"response") anomaly detection
                                        └─ ScreencastSession: CDPSession → bounded frames
                                             → ProcessPool(av VP8) → decode-validate → screencast.webm
```

### Integration Points

| Existing component | Contract |
|---|---|
| `parrot.e2e.errors` | Add `E2EScreencastError(E2EError)`; no other change. |
| `parrot.e2e.targets.browser` | Read-only; continues supervising the browser independently. |
| `.claude/agents/e2e-ui-tester.md` | Prose: record via the script helper on first anomaly; reduced/no recording when only a DevTools MCP is available. |
| `PlaywrightDriver` / `PlaywrightConfig` | No production modifications; `record_video_dir` stays unsuitable. |
| `ai-parrot-server` `pyproject.toml` | `screencast` extra (done: `av>=13,<14`, `pillow>=13`). |

### Public contract

```python
class ScreencastSession:
    """Runtime handle: CDPSession, bounded frame list, ack tasks, output path. Not persisted."""
    out_path: Path

async def start_screencast(page: "Page", out_dir: Path, *, max_frames: int = 600) -> ScreencastSession:
    """Begin capture of the caller's existing page; retain its context and state."""

async def stop_screencast(session: ScreencastSession) -> Path:
    """Stop, detach, encode, decode-validate, publish; return the validated WebM path."""

def record_on_anomaly(
    page: "Page", out_dir: Path, *, run_id: str, max_frames: int = 600
) -> "AnomalyRecorder":
    """Async context manager; starts capture at the first console error / HTTP 5xx on ``page``."""

class AnomalyRecorder:
    triggered: bool          # an anomaly was observed and capture started
    path: Optional[Path]     # validated WebM after a successful exit, else None
    error: Optional[E2EScreencastError]  # recorder failure, recorded not raised
```

Serializable data (if any) uses Pydantic v2. Existing contexts are valid;
`E2EScreencastContextReusedError` is not part of the design.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Reason |
|---|---|---|
| M0: Active-page recording spike (done) | no | Proved Obscura capture and encoding, then freeze the backend contract. |
| M1: Recorder | no | Resource ownership and error cleanup need judgment. |
| M2: Anomaly-triggered recorder | no | Concurrent event callbacks and exit-path cleanup need judgment. |
| M3: Agent protocol | yes, after M2 | Prose over the final `record_on_anomaly` signature. |

### Module 0: Real-Obscura active-page recording spike (gate)

- **Path**: `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py`.
- **Test**: `TestObscuraScreencastRecording.test_existing_page_produces_playable_webm`.
- Start an isolated real Obscura process and use `local_fixture_site` to
  create/navigate a page before capture. Observe a controlled anomaly, then
  start a recorder on that same existing page (an in-connection `CDPSession`; a separate connection cannot attach — see the spike report). Make a visible,
  deterministic post-start change, stop capture, encode, and decode WebM
  frames to verify that change is present. Size alone is insufficient.
- Assert page target identity, context, and navigated state survive recorder
  start and stop. Include another page with distinguishable content so
  recording the wrong page cannot pass.
- Use a test-local capture/encoding prototype. M1 may extract the proven
  logic later; M0 must not import the not-yet-implemented server recorder.
- If no binary is configured or discoverable, skip in ordinary suites.
  An explicitly configured but invalid binary, startup/connection failure,
  unsupported protocol command, absent codec, or invalid video is a failure,
  never a skip. Always clean up owned resources.
- **Gate evidence**: save command, tested commit, binary version, dependency
  and codec versions, test result, and decoded-video assertions under
  `artifacts/logs/`; persist an evidence summary and selected backend contract
  in `sdd/state/FEAT-762/`. A skip, xfail, unavailable environment, or mocked
  success does not unblock M1–M3 or satisfy feature completion.
- Before M1 task decomposition, update this spec with the proven transport,
  page-selection API, encoder dependency availability, concrete session
  resource types, error mapping, and cleanup ordering. If a new dependency
  is needed, obtain approval before adding it. Until this real pass and
  contract update exist, only M0 may proceed.

### Module 1: `parrot.e2e.screencast` — recorder

- **Path**: `packages/ai-parrot-server/src/parrot/e2e/screencast.py` (new);
  `packages/ai-parrot-server/src/parrot/e2e/errors.py` (modifies: add `E2EScreencastError`).
- **Depends on**: M0 (passed) and its Backend Contract Gate.
- Implement `ScreencastSession`, `start_screencast`, `stop_screencast` per §2 and the
  frozen backend contract. Reject a closed page with `E2EScreencastError`; never create or
  select another page. Import `av`/`PIL` lazily inside the encoder worker so that importing
  `parrot.e2e` never requires the extra. Place frames by `metadata.timestamp` (1/1000 time
  base). Stop and startup-failure cleanup order: `Page.stopScreencast` → `detach()` → await
  ack tasks → encode/flush → decode-validate → atomic publish; refuse to overwrite; a repeated
  `stop_screencast` returns the previously finalized path or the recorded error.
- Interface Skeleton: as in §2 Public contract
  (`# verified: errors.py:51 (E2EError)`; Playwright `new_cdp_session` verified by M0).

### Module 2: `record_on_anomaly` — anomaly-triggered recorder

- **Path**: `packages/ai-parrot-server/src/parrot/e2e/screencast.py` (same file as M1).
- **Depends on**: Module 1.
- `AnomalyRecorder.__aenter__` registers `page.on("console")` (type `error`) and
  `page.on("response")` (status ≥ 500) handlers; the first hit calls `start_screencast`
  exactly once (guarded against concurrent callbacks). `__aexit__` removes the handlers and,
  if triggered, calls `stop_screencast` on every exit path including exceptions and
  `asyncio.CancelledError`; recorder errors are stored in `.error` and logged with
  `self.logger`/module logger, never raised from `__aexit__`; the body's own exception
  propagates unchanged. Zero anomalies ⇒ no session, no file, `path is None`.

### Module 3: `.claude/agents/e2e-ui-tester.md` protocol edit

- **Path**: `.claude/agents/e2e-ui-tester.md` (modifies)
- **Depends on**: Module 2.
- **Responsibility**: Teach the agent to write and run a Playwright exploration script wrapped in
  `record_on_anomaly(page, Path("artifacts/logs/e2e/<run-id>"), run_id=<run-id>)`, add the
  returned path to the observation's `evidence_refs` only when `recorder.path` is not `None`,
  and report `recorder.error` as an `unavailable` observation. Replace the instruction to read
  `RunState.endpoint` (it is not populated): require an explicitly configured CDP endpoint
  (known port) or report recording unavailable. State that a DevTools MCP connection cannot be
  recorded and that recordings are post-detection only. Prose only — no new top-level JSON field.
- Anchors (see §6 Edit Sites): the screenshot sentence and the example `evidence_refs` array.

## 4. Test Specification

### Unit Tests

| Test | Module | Required assertion |
|---|---|---|
| `test_start_screencast_existing_page_succeeds` | M1 | Opens a CDPSession on the given page (fake Playwright objects) without replacing its context. |
| `test_start_screencast_closed_page_raises` | M1 | `E2EScreencastError`; no fallback to another page. |
| `test_start_screencast_failure_releases_resources` | M1 | CDP/encoder failure detaches the session, preserves page/context/browser. |
| `test_stop_screencast_finalizes_and_preserves_page` | M1 | stopScreencast → detach → encode → validate → publish; page/context not closed. |
| `test_stop_screencast_invalid_output_raises` | M1 | Empty/corrupt output never yields a success path. |
| `test_stop_screencast_refuses_overwrite_and_is_idempotent` | M1 | Existing final file kept; repeated stop returns prior result. |
| `test_frame_buffer_overflow_is_explicit_failure` | M1 | Overflow raises `E2EScreencastError`, never a truncated success. |
| `test_missing_encoder_extra_is_typed_error` | M1 | Absent `av` ⇒ `E2EScreencastError` naming `ai-parrot-server[screencast]`; importing `parrot.e2e` still works. |
| `test_record_on_anomaly_clean_run_creates_nothing` | M2 | Zero anomalies ⇒ no session, no file, `path is None`. |
| `test_record_on_anomaly_starts_once_on_first_anomaly` | M2 | Console error or 5xx starts capture exactly once, even with concurrent events. |
| `test_record_on_anomaly_stops_on_exception_and_cancel` | M2 | Body exception propagates unchanged; capture stopped; recorder error recorded, not raised. |
| `test_exploration_screencast_protocol` | M3 | Agent prose references `record_on_anomaly`, post-detection wording, explicit endpoint, `evidence_refs` only on success, no daemon/`screencast start` text. |

### Integration Tests

| Test | Description |
|---|---|
| `test_existing_page_produces_playable_webm` | M0 (done): real existing-page capture, decoded output, ownership checks. |
| `test_record_on_anomaly_real_obscura` | M2: real Obscura; page triggers a console error, `record_on_anomaly` yields a playable WebM showing the post-trigger change, page/browser intact; a clean page yields no file. |

### Validation Contract

tests:
- packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py::TestObscuraScreencastRecording::test_existing_page_produces_playable_webm
- packages/ai-parrot-server/tests/unit/e2e/test_screencast.py
- packages/ai-parrot-server/tests/unit/e2e/test_screencast_agent_protocol.py
- packages/ai-parrot-server/tests/integration/e2e/test_screencast_integration.py::test_record_on_anomaly_real_obscura
markers: none

### Test Data / Fixtures

Reuse `local_fixture_site` and an isolated `ObscuraProcessManager` bootstrap.
Do not reuse `real_obscura_driver`'s broad connection-error skip behavior.
M0 uses a test-local prototype; M2 integration tests use production CLI code.
Ordinary-suite skips without a binary are allowed for both real-browser
tests, but neither skip counts as acceptance evidence.

### E2E Scenarios

Not applicable — this feature adds no deterministic `parrot e2e run`
scenario of its own; its tests run as plain `pytest` (opt-in
real-binary integration tests and mocked unit tests). The `e2e:`
frontmatter key is intentionally omitted (§1 Non-Goals).

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] M0 has a successful real-Obscura run, decoded-video assertions, and
  persisted evidence; its proven backend contract is recorded before M1–M3.
  A skip never satisfies this gate.
- [ ] Ordinary suites skip only when no binary is available; configured
  startup/connection/capture/encoding failures fail the real tests.
- [ ] Recording starts on the caller's exact existing `Page` after an anomaly
  (console error / HTTP 5xx), preserving context, state, and browser ownership.
- [ ] Missing/closed page, unsupported capture, missing encoder, encoder failure,
  and invalid output produce `E2EScreencastError` without claiming a finalized artifact.
- [ ] `record_on_anomaly` yields a `.webm` under `artifacts/logs/e2e/<run-id>/` on a real
  Obscura run with an anomaly (`test_record_on_anomaly_real_obscura`), and none on a clean run.
- [ ] `e2e-ui-tester` documents the Playwright-script protocol: recording only after the first
  anomaly, stopped before `parrot e2e down`, labelled post-detection, no daemon/CLI.
- [ ] `e2e-exploration.json`'s schema is unchanged except for the
  additive `evidence_refs` entry — still no `passed`/`status`/
  `gate_satisfied` field of any kind.
- [ ] No existing `parrot e2e run`/`parrot e2e verify` test needs to
  change; `E2EVerdict`'s evidence schema is untouched.
- [ ] All new/modified unit tests pass (`pytest packages/ai-parrot-server/tests/unit/e2e/ -v`); `av` is declared only as the `screencast` extra.
- [ ] `ruff check` clean on all new/modified files.

---

## 6. Codebase Contract

### Verified Existing Contracts

- `PlaywrightDriver._start_obscura_cdp()` in
  `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  reuses `browser.contexts[0]` when present; only new contexts receive
  `_build_context_kwargs()` including `record_video_dir`. This is the reason
  the old recording approach is excluded, not an integration to copy.
- `parrot.e2e.errors` supplies `E2EError`, `E2EConfigError`, and
  `E2EPrerequisiteError`. New recording errors follow this hierarchy.
- `cli.py` daemon/ticket machinery is NOT used by this feature (see §2 Design revision).
- `_BrowserAdapter.ready()` returns a boolean. Its endpoint table is private
  process-local state; persisted `RunState.endpoint` is not populated.
  The caller must supply an endpoint from explicit exploration configuration.
- `E2ESupervisor._log_path()` uses `artifacts/logs/e2e/<run-id>/`.
- No existing `PlaywrightDriver.start_screencast()` or `.record_video()`
  method exists. No recording field is added to `E2EVerdict`.

### Backend Contract Gate

**Frozen from M0 evidence** (`sdd/state/FEAT-762/screencast-spike.md`; real
Obscura 0.2.2; test `TestObscuraScreencastRecording`):

- **Target selection**: the caller's own Playwright `Page`; no target ID. A separate
  CDP connection cannot see the page (verified), so cross-process attach is unsupported.
- **Transport**: `cdp = await page.context.new_cdp_session(page)`; commands
  `Page.startScreencast {format:"jpeg", quality, everyNthFrame:1}`,
  `Page.screencastFrameAck {sessionId}` per frame, `Page.stopScreencast`, then `await cdp.detach()`.
  Event `Page.screencastFrame`: `data` (base64 JPEG 1280x720), `metadata.timestamp` (s), `sessionId`.
- **Frame cadence**: activity-driven (`obscuraFrameSource`); frames only on page change,
  so place frames by timestamp (time base 1/1000), not a fixed frame index.
- **Encoder**: PyAV `av` (libvpx VP8, `format="webm"`, yuv420p) run in a `ProcessPoolExecutor`;
  flush with `stream.encode(None)`; verify by decoding with `av`. Bounded frame list (600 in the spike).
- **Session resources**: `ScreencastSession` = {`CDPSession`, bounded `list[(ts_ms, jpeg)]`,
  ack tasks, output path}. Cleanup order: stopScreencast → detach → await acks → encode/flush →
  decode-validate → publish; never close page/context/browser.
- **Dependency**: `av` and `Pillow` are importable in the shared venv, but `av` is only a root
  override (`av>=13,<14`); declared 2026-10-28 (user-approved) as the `screencast` extra of `ai-parrot-server` (`av>=13,<14`, `pillow>=13`).
- **Errors**: map missing/closed page, CDP command failure, empty frames, encode/decode failure to `E2EScreencastError`.

The candidate CDP frame lifecycle is documented in the official
[Page domain](https://chromedevtools.github.io/devtools-protocol/tot/Page/).
Frames require a separate encoder; [PyAV's encoding example](https://pyav.org/docs/stable/cookbook/numpy.html)
illustrates encoding and flushing, not proof of WebM codec availability here.
The root `pyproject.toml` has an `av` override, which is not an installation
or a server runtime dependency declaration. Do not import it solely on that
basis or introduce a new encoder dependency without approval.

### Edit Sites (Blueprint Anchors)

> Verified against: `5140479a9` (dev, 2026-10-27)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py` | MODIFY (done, M0) | `class TestObscuraScreencastRecording:` | — | 1 |
| `packages/ai-parrot-server/src/parrot/e2e/screencast.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/e2e/errors.py` | MODIFY | `class E2EEvidenceError(E2EError):` | `errors.py:117` | 1 |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY (done) | `screencast = [` | — | 1 |
| `.claude/agents/e2e-ui-tester.md` | MODIFY | `Capture a screenshot on any unexpected finding.` | `e2e-ui-tester.md:116` | 1 |
| `.claude/agents/e2e-ui-tester.md` | MODIFY | `"evidence_refs": ["artifacts/logs/e2e/browser-explore/screenshot.png"]` | `e2e-ui-tester.md:148` | 1 |
| `packages/ai-parrot-server/tests/unit/e2e/test_screencast.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/unit/e2e/test_screencast_agent_protocol.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/integration/e2e/test_screencast_integration.py` | CREATE | — | — | — |

`parrot.e2e.cli` is no longer touched. Verified against `4b72a57eb` (feature branch, 2026-10-28).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use the real fixture's isolated bootstrap/cleanup pattern, but skip only
  when no binary is available. Configured failures are failures. A skip is
  never feasibility evidence or authorization to implement M1–M3.

- `artifacts/logs/e2e/<run-id>/<target-id>`-shaped file placement
  (`E2ESupervisor._log_path`) — the screencast file is a sibling in the
  same per-run directory, not a new top-level location.
- Async-first: bounded waits, ack frames immediately, CPU-bound encoding in a
  `ProcessPoolExecutor`; Obscura only lets the most recently created page run JS,
  so exploration scripts should create the investigated page last.

### Known Risks / Gotchas

- **Version coupling.** Capture/encoding were proven on Obscura 0.2.2 only (M0);
  the real-binary integration test is the regression guard for upgrades.
- **Existing page ownership.** Do not create/close a context, navigate away,
  clear cookies, or close the remote browser as a recording side effect.
  Verify cleanup with the original automation client still attached.
- **No pre-anomaly footage.** Capture begins after detection. Reports must
  distinguish subsequent investigation/reproduction from the original event.

- **No retention policy for `artifacts/logs/e2e/`.** Accepted, deferred
  risk (§1 Non-Goals, proposal U3) — the on-anomaly-only trigger bounds
  how often a `.webm` is produced, but no automatic cleanup exists.
  Document this for the person running `e2e-ui-tester` repeatedly on a
  dev machine.
- **Recorder only covers Playwright-owned connections.** Obscura isolates pages per
  CDP connection; a DevTools MCP tool or any other client cannot be recorded, and
  attaching from another process is impossible (M0 evidence).
- **Frames are activity-driven.** Obscura emits a frame only when the page changes;
  encoding must use frame timestamps, so an idle page yields a short or single-frame video.

### External Dependencies

M0 identified `av` (libvpx VP8 WebM) and Pillow as the working encoder path; declaring `av`
as a dependency of the hosting package was user-approved 2026-10-28 and declared as the `screencast` extra of `ai-parrot-server`. The existing Playwright extra
is not proof of a frame-to-WebM encoder. M0 must identify usable installed
capture/codec dependencies and their supported package install path. If a
new dependency is required, approval and an updated dependency contract
are prerequisites to implementation.

---

## 8. Open Questions

Requirements for triggering and evidence placement are settled; the technical gate is resolved.

- [x] Which active-page transport and WebM encoder work against Obscura
  v0.2.2? — *Resolved by M0*: in-connection Playwright `CDPSession` screencast + PyAV VP8/WebM
  (Backend Contract Gate). A detached process cannot attach.
- [x] How does the exploration agent drive an in-process recorder? — *Resolved 2026-10-28*:
  the agent writes/runs a short Playwright script wrapped in `record_on_anomaly` (option i);
  a DevTools MCP connection cannot be recorded. *Assumed by the spec author; the user was
  asked and did not object — confirm at spec review.*
- [x] Is declaring `av` approved? — *Resolved 2026-10-28 (user)*: yes, as the
  `screencast` extra of `ai-parrot-server`.

- [x] Should the implementation be gated behind a real-Obscura-binary
  spike before building the full feature? — *Resolved in proposal*: Yes
  — made Module 0, the spec's first module/task gate.
- [x] Always-on vs. on-anomaly-only screencast trigger? — *Resolved in
  proposal*: Hybrid — on-anomaly-only for `e2e-ui-tester`'s ad hoc
  exploration (this spec); always-on for a future bounded deterministic
  UI scenario is explicitly deferred (§1 Non-Goals).
- [x] Is retention/cleanup of `artifacts/logs/e2e/` in scope? —
  *Resolved in proposal*: No — out of scope; documented as an accepted
  risk (§7).

---

## 9. Design Research Cross-Check

The independent review on 2026-10-27 confirmed three findings: incompatible
fresh-context lifecycle (`issue:4953fd5ba7a1`), inconsistent stop syntax
(`issue:65ed88622c76`), and a skippable feasibility gate (`issue:f94f346dad94`).
This revision replaces the lifecycle with an active-page contract, uses
`stop --run-id` consistently, and requires successful real-binary evidence.
These are specification corrections, not proof that recording works.

---

## Worktree Strategy

- **Isolation**: one feature worktree for this spec
  (`feat-FEAT-762-e2e-browser-screencast-logs`); the `sdd-coder` pool may give
  each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M0 (spike test) — done.
  - M1 (`screencast.py` recorder + `errors.py`) depends on M0's frozen contract.
  - M2 (`record_on_anomaly`, same file) imports M1's `start_screencast`/`stop_screencast`.
  - M3 (`e2e-ui-tester.md` prose) depends on M2's final helper signature.
  - Strictly linear M1 → M2 → M3; `depends_on` must reflect that.
- **Shared files**: M1 and M2 both edit `screencast.py` (and its tests) — serialized.
- **Exclusive resources**: none; the `screencast` extra is already declared (lockfile
  refresh is a main-checkout operator step).
- **Cross-feature dependencies**: none. (FEAT-763,
  `browsing-playwright-default-and-screencast`, is a related but
  separate feature using `PlaywrightConfig.record_video_dir`
  from the `WebScrapingToolkit`/browsing-DSL side — no file
  overlap with this spec's Edit Sites, no merge-order dependency.)
