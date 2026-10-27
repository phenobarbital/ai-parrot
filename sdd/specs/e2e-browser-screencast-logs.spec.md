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
**Implementation gate**: M0 PASSED for an in-connection recorder (Playwright `CDPSession` on the automation connection) — see `sdd/state/FEAT-762/screencast-spike.md`. The detached-process recorder is infeasible on Obscura 0.2.2 (per-connection page isolation). M2/M3 text below is superseded and must be revised (`/sdd-spec`) before `/sdd-task` decomposes M1–M3.

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

`parrot.e2e.screencast` attaches to the exact existing CDP page target
identified by the caller's `page_target_id`. It neither creates a replacement
context nor changes browser ownership. `record_video_dir` and the driver's
`_owns_context` flag are not the recording mechanism.

> **Design revision (M0 outcome, decision (a), 2026-10-27).** Obscura 0.2.2 isolates
> pages per CDP connection: a second connection sees no targets (`Target.getTargets`
> is empty; `attachToTarget` → "Target not found"). A detached recorder process
> (`parrot e2e screencast start/stop`, daemon, tickets, `page_target_id`) therefore
> cannot work. The recorder must run **inside the process that owns the Playwright
> connection**, using a `CDPSession` of the exact `Page` object. The Bash-only
> `e2e-ui-tester` CLI-daemon flow (M2/M3 below) is superseded and needs a revised
> design before decomposition.

M0 had to select and prove a capture/encoding backend before M1–M3 proceed.
The first candidate is page-scoped CDP `Page.startScreencast`, receiving
`Page.screencastFrame` events, acknowledging frames with
`Page.screencastFrameAck`, and stopping with `Page.stopScreencast`.
These protocol commands describe a candidate, not verified Obscura support.
They deliver image frames, not a WebM file; M0 must also prove encoding,
flush, and decoding of the resulting WebM with available dependencies.
If this candidate fails, revise and validate the backend before continuing;
never fall back to a different page or the rejected context-creation path.

(Superseded by the revision above: in the in-process design the recorder owns only its recording connection, bounded frame queue,
encoder resources, and ticket — read "ticket" as dropped.) CPU-bound encoding runs in a process, with
async I/O and bounded startup/stop waits. Startup reports ready only after
capture and the encoder are initialized. Stop ends capture, drains and flushes
encoding, verifies a playable non-empty file, atomically publishes
`screencast.webm`, and releases recorder-owned resources. Failure and signal
paths release those resources without closing the page, context, or browser.
No success path is reported for a partial or invalid artifact.

The agent supplies both the endpoint and exact page target ID from its
exploration configuration/automation session. `up` currently does not
populate `RunState.endpoint`; do not infer it from the returned state or use
the adapter's in-memory table across processes. Configure a known browser
port and pass its endpoint explicitly. If the endpoint or page identity is
unavailable, report recording unavailable rather than guess. Multiple tabs
must never cause selection of the first page or a match by ambiguous URL.

On the first anomaly the agent starts recording, continues investigation,
then stops recording on every exit path **before** `parrot e2e down`.
Only a successful stop adds the returned path to `evidence_refs`.
Capture failure must not prevent target teardown or the exploration report.

### Component Diagram

```text
e2e-ui-tester (existing page + CDP endpoint + page target ID)
  → parrot e2e screencast start/stop
  → detached recorder daemon and ticket
  → M0-verified page capture backend → encoder → screencast.webm
```

### Integration Points

| Existing component | Contract |
|---|---|
| `parrot.e2e.cli` | Add detached start/stop commands using the existing ticket lifecycle pattern. |
| `parrot.e2e.targets.browser` | Read-only; continue supervising the browser independently. |
| `.claude/agents/e2e-ui-tester.md` | Supply exact page identity, start on anomaly, stop before browser teardown. |
| `PlaywrightDriver` / `PlaywrightConfig` | Existing code explains why `record_video_dir` is unsuitable; no production modifications. |

### Public contract

```python
async def start_screencast(
    cdp_endpoint: str, out_dir: Path, *, page_target_id: str
) -> ScreencastSession:
    """Begin capture of the selected existing page; retain its context and state."""

async def stop_screencast(session: ScreencastSession) -> Path:
    """Finalize recorder-owned resources and return a validated WebM path."""
```

`ScreencastSession` is a new internal runtime handle. M0 must document its
concrete resource types and ownership before M1 task decomposition; it is
not persisted or added to gate evidence. Serializable ticket data uses
Pydantic v2. Capture/setup/finalization failures use a new
`E2EScreencastError(E2EError)` with actionable reasons. Existing contexts
are valid; `E2EScreencastContextReusedError` is removed from the design.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Reason |
|---|---|---|
| M0: Active-page recording spike | no | Must prove Obscura capture and encoding, then freeze the backend contract. |
| M1: Recorder | no | Resource ownership and error cleanup need judgment. |
| M2: CLI | no | Detached process lifecycle and finalization need judgment. |
| M3: Agent protocol | yes, after M2 | Uses the verified CLI and lifecycle contract. |

### Module 0: Real-Obscura active-page recording spike (gate)

- **Path**: `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py`.
- **Test**: `TestObscuraScreencastRecording.test_existing_page_produces_playable_webm`.
- Start an isolated real Obscura process and use `local_fixture_site` to
  create/navigate a page before capture. Observe a controlled anomaly, then
  attach a separate recorder to that same page target ID. Make a visible,
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

### Module 1: `parrot.e2e.screencast`

- **Path**: `packages/ai-parrot-server/src/parrot/e2e/screencast.py` (new).
- **Depends on**: successful M0 evidence and its finalized backend contract.
- Implement the public start/stop contract from §2 using the proven backend.
  Reject missing/closed page targets without creating or selecting another
  page. Do not reject an existing context.
- Bound frame buffering and make overflow an explicit recording failure;
  never silently publish an incomplete capture as success. Timestamp frames
  consistently with the M0-proven encoder. Flush and validate before final
  publication; refuse to overwrite an existing final artifact.
- Stop and startup-failure cleanup must preserve the selected page/context
  and remote browser. Repeated stop must return the previously finalized
  path or recorded error without signaling unrelated processes.

### Module 2: `parrot.e2e.cli` screencast subcommands

- **Path**: `packages/ai-parrot-server/src/parrot/e2e/cli.py` (modifies)
- **Responsibility**: Expose `parrot e2e screencast start`/`screencast
  stop` so `e2e-ui-tester` (Bash-only) can drive Module 1 across
  separate tool calls, using the exact detached-daemon/ticket-file
  pattern `up_command`/`_spawn_detached_target`/`_daemon_log_path`
  already implement (verified: cli.py:460-465, 485+).
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # parrot/e2e/cli.py (modifies cli.py:913 — inserted immediately before
  # `if __name__ == "__main__":`, verified: cli.py:913)

  @e2e.group("screencast")
  def screencast_group() -> None:
      """Operational screencast recording for exploration (FEAT-762) — never gate evidence."""

  @screencast_group.command("start")
  @click.option("--cdp-endpoint", required=True, help="Explicit CDP endpoint from the exploration configuration.")
  @click.option("--page-target-id", required=True, help="Exact existing CDP page target ID.")
  @click.option("--out", "out_dir", required=True, type=click.Path(path_type=Path))
  @click.option("--owner-id", default=None)
  @click.option("--run-id", "invocation_id", default=None, help="Ticket id, same convention as `up --run-id` (cli.py's own reinterpretation, verified: cli.py:21-35).")
  def screencast_start_command(cdp_endpoint: str, page_target_id: str, out_dir: Path, owner_id: Optional[str], invocation_id: Optional[str]) -> None:
      """Spawn a detached daemon holding the recording session open; prints a ticket JSON line once ready."""

  @screencast_group.command("stop")
  @click.option("--run-id", required=True)
  def screencast_stop_command(run_id: str) -> None:
      """Signal the daemon to finalize capture and print the validated .webm path."""
  ```

Tickets must include validated owner/run IDs, endpoint/page identity, daemon
identity, readiness/finalization state, and terminal error or artifact path.
Use recorder-specific ticket/log paths; reject duplicate live run IDs and
verify daemon identity before signaling. Wait for terminal finalization,
not just signal delivery. Bound waits and preserve typed failure output.

### Module 3: `.claude/agents/e2e-ui-tester.md` protocol edit

- **Path**: `.claude/agents/e2e-ui-tester.md` (modifies)
- **Responsibility**: Add the on-anomaly screencast step to the
  exploration process and the `evidence_refs` entry to the report
  contract — prose only, no new top-level JSON field.
- **Depends on**: Module 2.
- **Interface Skeleton** *(prose edit, not code — both anchors verified unique)*:
  ```
  # .claude/agents/e2e-ui-tester.md (modifies e2e-ui-tester.md:116 —
  # "Capture a screenshot on any unexpected finding." gains a sibling
  # sentence: "The first time this happens in a run, also run `parrot e2e
  # screencast start --cdp-endpoint <endpoint> --page-target-id <page-target-id>
  # --out artifacts/logs/e2e/<run-id>/
  # --owner-id explore-e2e-ui-tester --run-id <run-id>-screencast`; at the
  # end of exploration, before browser teardown, always run `parrot e2e screencast stop
  # --run-id <run-id>-screencast` if one was started, and add its reported
  # path to this observation's evidence_refs only on success."
  # verified: e2e-ui-tester.md:116)
  #
  # (modifies e2e-ui-tester.md:148 — the example `evidence_refs` array
  # gains a second, conditional entry documenting the screencast path
  # shape: "artifacts/logs/e2e/<run-id>/screencast.webm"
  # verified: e2e-ui-tester.md:148)
  ```

---

M3 also corrects the existing instruction to read `RunState.endpoint`:
require an explicitly configured endpoint and obtain the exact page target
ID from the automation session. Record an unavailable observation if these
are missing. Keep screenshot evidence, label recordings as post-detection,
and finalize the recorder before stopping browser targets on every path.

## 4. Test Specification

### Unit Tests

| Test | Module | Required assertion |
|---|---|---|
| `test_start_screencast_existing_page_succeeds` | M1 | Attach to the exact existing page without replacing its context. |
| `test_start_screencast_missing_page_raises` | M1 | Typed failure; no fallback to another page. |
| `test_start_screencast_failure_releases_resources` | M1 | Capture/encoder failure cleans owned resources and preserves the browser. |
| `test_stop_screencast_finalizes_and_preserves_page` | M1 | Flush/validate/publish then detach; do not close page or context. |
| `test_stop_screencast_invalid_output_raises` | M1 | Empty/corrupt output never yields a success path. |
| `test_screencast_start_command_spawns_ticketed_daemon` | M2 | Exact documented flags, including page target ID, reach the daemon. |
| `test_screencast_stop_command_signals_and_reports_path` | M2 | Invoke `screencast stop --run-id ID`; wait for successful finalization. |
| `test_screencast_daemon_lifecycle` | M2 | Duplicate run, stale PID, timeout, error, repeated stop, and signal cleanup. |
| `test_exploration_screencast_protocol` | M3 | Zero anomalies means no recording; first anomaly starts once; stop precedes browser teardown even on error. |

### Integration Tests

| Test | Description |
|---|---|
| `test_existing_page_produces_playable_webm` | M0: real existing-page capture with visible post-start changes, decoded output, and ownership checks. |
| `test_screencast_cli_round_trip` | M2: real detached start/stop across separate invocations, launcher-exit survival, playable artifact, and preserved page. |

### Validation Contract

tests:
- packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py::TestObscuraScreencastRecording::test_existing_page_produces_playable_webm
- packages/ai-parrot-server/tests/unit/e2e/test_screencast.py
- packages/ai-parrot-server/tests/unit/e2e/test_cli.py::test_screencast_start_command_spawns_ticketed_daemon
- packages/ai-parrot-server/tests/unit/e2e/test_cli.py::test_screencast_stop_command_signals_and_reports_path
- packages/ai-parrot-server/tests/unit/e2e/test_cli.py::test_screencast_daemon_lifecycle
- packages/ai-parrot-server/tests/unit/e2e/test_cli.py::test_exploration_screencast_protocol
- packages/ai-parrot-server/tests/integration/e2e/test_screencast_cli.py::test_screencast_cli_round_trip
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
- [ ] Recording starts on the exact existing page after navigation and
  anomaly detection, preserving context, state, and browser ownership.
- [ ] Missing target, unsupported capture, encoder failure, and invalid
  output produce typed errors without claiming a finalized artifact.

- [ ] `parrot e2e screencast start` + `parrot e2e screencast stop`
  round-trip produces a `.webm` at a stable, predictable path under
  `artifacts/logs/e2e/<run-id>/`; the real CLI round-trip test passes.
- [ ] `e2e-ui-tester` starts a screencast only after the first observed
  anomaly in a run — a clean run (zero anomalies) never produces a
  `.webm`.
- [ ] `e2e-exploration.json`'s schema is unchanged except for the
  additive `evidence_refs` entry — still no `passed`/`status`/
  `gate_satisfied` field of any kind.
- [ ] No existing `parrot e2e run`/`parrot e2e verify` test needs to
  change; `E2EVerdict`'s evidence schema is untouched.
- [ ] All new/modified unit tests pass (`pytest packages/ai-parrot-server/tests/unit/e2e/ -v`).
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
- `cli.py` supplies `_daemon_log_path`, `_spawn_detached_target`, safe ID
  validation, JSON output, and ticket lifecycle patterns. Mirror the pattern,
  but use a distinct recorder daemon and ticket namespace.
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
  override (`av>=13,<14`); declaring it for the hosting package REQUIRES user approval (open).
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
| `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py` | MODIFY | `class TestFakeBroker:` | `test_fixture_site_integration.py:133` | 1 |
| `packages/ai-parrot-server/src/parrot/e2e/screencast.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/e2e/cli.py` | MODIFY | `if __name__ == "__main__":` | `cli.py:913` | 1 |
| `.claude/agents/e2e-ui-tester.md` | MODIFY | `Capture a screenshot on any unexpected finding.` | `e2e-ui-tester.md:116` | 1 |
| `.claude/agents/e2e-ui-tester.md` | MODIFY | `"evidence_refs": ["artifacts/logs/e2e/browser-explore/screenshot.png"]` | `e2e-ui-tester.md:148` | 1 |
| `packages/ai-parrot-server/tests/unit/e2e/test_screencast.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/integration/e2e/test_screencast_cli.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/unit/e2e/test_cli.py` | MODIFY | `def test_resolve_worktree_falls_back_to_start_without_a_git_ancestor(tmp_path: Path) -> None:` | `test_cli.py:740` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use the real fixture's isolated bootstrap/cleanup pattern, but skip only
  when no binary is available. Configured failures are failures. A skip is
  never feasibility evidence or authorization to implement M1–M3.

- The `up`/`down` detached-daemon/ticket-file lifecycle already in
  `cli.py` (`_spawn_detached_target`, `_daemon_log_path`,
  `artifacts/logs/e2e/_up_tickets/` convention) — Module 2 mirrors this
  rather than inventing a new subprocess-lifecycle mechanism.
- `artifacts/logs/e2e/<run-id>/<target-id>`-shaped file placement
  (`E2ESupervisor._log_path`, `cli.py:889-903`) — the screencast file is
  a sibling in the same per-run directory, not a new top-level location.

### Known Risks / Gotchas

- **Active-page capture and encoding are unproven.** M0 must prove both
  against real Obscura; absent/failed evidence blocks dependent modules.
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
- **Detached-daemon lifecycle correctness.** `up`'s own detached daemon
  has a known, still-open ledger issue around launcher-exit survival
  (`issue:0a04d048dab5`) — Module 2 must not blindly assume `up`'s
  pattern is bug-free; verify the specific signal/exit behavior needed
  for a short-lived screencast daemon (which, unlike `up`, is expected
  to be stopped deliberately by `e2e-ui-tester` itself, not to survive
  indefinitely).

### External Dependencies

M0 identified `av` (libvpx VP8 WebM) and Pillow as the working encoder path; declaring `av`
as a dependency of the hosting package needs user approval. No dependency is added by this spec revision. The existing Playwright extra
is not proof of a frame-to-WebM encoder. M0 must identify usable installed
capture/codec dependencies and their supported package install path. If a
new dependency is required, approval and an updated dependency contract
are prerequisites to implementation.

---

## 8. Open Questions

Requirements for triggering and evidence placement are settled. One
technical gate remains unresolved:

- [x] Which active-page transport and WebM encoder work against Obscura
  v0.2.2? — *Resolved by M0*: in-connection Playwright `CDPSession` screencast + PyAV VP8/WebM
  (Backend Contract Gate). A detached process cannot attach.
- [ ] Revise M2/M3: how does the exploration agent drive an in-process recorder (not a
  Bash-only CLI daemon)? And is declaring `av` as a dependency approved?

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
  (`feat-FEAT-762-e2e-browser-screencast-logs`); task decomposition
  (`/sdd-task`) may give the `sdd-coder` pool its own sub-worktrees per
  task inside it.
- **Module dependency graph**:
  - M0 (spike test) → no dependencies; gates M1.
  - M1 (`screencast.py`) depends on M0 passing and its backend contract update.
  - M2 (`cli.py` subcommands) depends on M1 (imports `start_screencast`/`stop_screencast`).
  - M3 (`e2e-ui-tester.md` prose edit) depends on M2 (needs the final CLI invocation shape).
  - This is a strictly linear chain (M0 → M1 → M2 → M3) — no two modules
    are independent enough to run concurrently; task decomposition
    should reflect that with `depends_on`, not parallel lanes.
- **Shared files**: M2 and M3 add tests to `test_cli.py`; keep their tasks sequential.
- **Exclusive resources**: no migration or extension rebuild is planned.
  Any dependency/lockfile changes discovered by M0 require approval and
  an updated task scope before proceeding.
- **Cross-feature dependencies**: none. (FEAT-763,
  `browsing-playwright-default-and-screencast`, is a related but
  separate feature using `PlaywrightConfig.record_video_dir`
  from the `WebScrapingToolkit`/browsing-DSL side — no file
  overlap with this spec's Edit Sites, no merge-order dependency.)
