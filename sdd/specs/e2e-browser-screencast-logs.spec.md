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

---

## 1. Motivation & Business Requirements

### Problem Statement

`e2e-ui-tester` — the optional exploratory subagent for FEAT-581's E2E
`browser`/`ui` fixture targets — attaches to a supervised Obscura CDP
endpoint and today only captures a single PNG screenshot "on any
unexpected finding." When an exploration run surfaces a real anomaly
(an unexpected console error, a 5xx network response), that one still
frame is the only visual evidence available; there is no way to see the
sequence of navigation/interaction steps that led up to it. Separately,
`PlaywrightDriver` (the project's own Playwright backend,
`parrot_tools.scraping.drivers`) already has a `record_video_dir` config
field and an `engine="obscura"` CDP-attach mode — the mechanism this
proposal needs already exists one layer away, but nothing in the E2E
module connects to it, and the mechanism itself has a documented trap:
it only engages when the CDP endpoint has zero pre-existing browser
contexts, silently doing nothing otherwise.

### Goals

- Give `e2e-ui-tester` the ability to record a Playwright-backed
  screencast (`.webm`) of its browser session against the Obscura CDP
  endpoint the `browser` e2e target hands it, saved as an **operational
  log artifact** under `artifacts/logs/e2e/<run-id>/` — never as
  deterministic gate evidence.
- Trigger: **on-anomaly-only** for `e2e-ui-tester`'s ad hoc exploration
  runs — start recording the first time an anomaly (console error / 5xx
  response) is observed, mirroring the existing screenshot trigger;
  never recorded for a clean run.
- Verify, with a real Obscura v0.2.2 binary (opt-in, cleanly-skipping
  test), that `record_video_dir` actually produces a usable `.webm`
  before trusting the mechanism in the exploration flow — **this
  verification is this spec's first module/task and gates the rest.**
- Fail loudly (never silently record nothing) when the CDP endpoint
  already has a pre-existing browser context, so the fresh-context
  precondition `record_video_dir` depends on is never silently violated.

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
  keeps only spawning `obscura serve` and handing back a raw CDP
  endpoint; it never becomes Playwright-aware itself.
- **`e2e-api-tester`** — no browser surface, out of scope.

---

## 2. Architectural Design

### Overview

A new, small module (`parrot.e2e.screencast`) wraps a
`PlaywrightDriver` connected to the `browser` target's existing Obscura
CDP endpoint in `engine="obscura"` mode, with `record_video_dir` set to
the run's own `artifacts/logs/e2e/<run-id>/` directory. Because
`record_video_dir` only takes effect when Playwright creates a *fresh*
context (never when it reuses an existing one), `start_screencast()`
asserts the connection resulted in a freshly created context and raises
a typed error otherwise — it never degrades to "recording silently did
nothing."

Because `e2e-ui-tester` only has `Bash`/`Read`/`Glob`/`Grep`/`Write` as
tools — no persistent Python state across tool calls — the recording
session itself must outlive any single Bash invocation. `parrot e2e
screencast start`/`stop` CLI subcommands (added to the existing `parrot
e2e` Click group) follow the exact detached-daemon pattern `up`/`down`
already use: `start` spawns a detached child that holds the
`PlaywrightDriver` connection open and writes a ticket once ready;
`stop` signals that child, which closes the context (finalizing
Playwright's `.webm` write) and reports the final path.

`e2e-ui-tester`'s own exploration protocol gains one new step: the first
time it observes a console error or 5xx response, it shells out to
`parrot e2e screencast start`; at the end of exploration (success or
failure) it always calls `parrot e2e screencast stop` if a screencast was
started, and adds the resulting path to its existing `evidence_refs`
array — no new top-level field in `e2e-exploration.json`.

### Component Diagram

```
e2e-ui-tester (agent, Bash tool calls)
   │ parrot e2e screencast start/stop (CLI)
   ▼
parrot.e2e.cli (screencast_start_command / screencast_stop_command)
   │ detached daemon, ticket file   (pattern: up_command / _spawn_detached_target)
   ▼
parrot.e2e.screencast (start_screencast / stop_screencast)
   │ PlaywrightDriver(engine="obscura", cdp_endpoint_url=..., record_video_dir=...)
   ▼
parrot_tools.scraping.drivers.playwright_driver.PlaywrightDriver
   │ chromium.connect_over_cdp(endpoint)
   ▼
Obscura CDP endpoint  (owned by the `browser` e2e target, parrot.e2e.targets.browser)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_tools.scraping.drivers.playwright_driver.PlaywrightDriver` | uses | connects in `engine="obscura"` mode against the endpoint the `browser` target already allocates |
| `parrot_tools.scraping.drivers.playwright_config.PlaywrightConfig` | uses | sets `engine`, `cdp_endpoint_url`, `record_video_dir`, `obscura_port`/`browser_type="chromium"` |
| `parrot.e2e.cli` (`e2e` Click group) | extends | adds `screencast start`/`screencast stop` subcommands, reusing `_daemon_log_path`/ticket-file/detached-daemon conventions already used by `up` |
| `parrot.e2e.targets.browser._BrowserAdapter` | reads only | never modified; its `ready()`-reported CDP endpoint is the input to `start_screencast()` |
| `.claude/agents/e2e-ui-tester.md` | extends | adds the on-anomaly screencast step and an `evidence_refs` entry |

### Data Models

```python
# No new Pydantic model. parrot.e2e.screencast works with plain values
# (endpoint URL, Path) and raises typed errors from parrot.e2e.errors
# (new error subclass — see Module 1).
```

### New Public Interfaces

```python
# parrot/e2e/screencast.py (new)
async def start_screencast(cdp_endpoint: str, out_dir: Path) -> "ScreencastSession":
    """Connect over CDP and begin recording; raises if the context is not fresh."""

async def stop_screencast(session: "ScreencastSession") -> Path:
    """Close the context (finalizing the .webm) and return its stable final path."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M0: Real-Obscura screencast spike | no | — | outcome decides whether M1's fresh-context assumption holds at all; a thinking model must read the real result and adjust M1 if it fails |
| M1: `parrot.e2e.screencast` | no | — | the fresh-context loud-failure behavior (C4/Integration Risk #2) is a safety-critical judgment call, not mechanical |
| M2: `parrot.e2e.cli` screencast subcommands | no | — | replicating the detached-daemon/signal/ticket-file lifecycle correctly (matching `up`'s own subtlety around launcher-exit survival) needs careful attention, not a template fill |
| M3: `.claude/agents/e2e-ui-tester.md` protocol edit | yes | insertion point, exact CLI invocations, and JSON shape are all fixed by M1/M2's finished interfaces; the edit is mechanical prose once those exist | — |

### Module 0: Real-Obscura screencast verification spike (gate)

- **Path**: `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py`
- **Responsibility**: Prove, against a real Obscura v0.2.2 binary, that
  `PlaywrightConfig(engine="obscura", record_video_dir=...)` produces a
  real, non-empty `.webm` once `driver.quit()` closes the context.
  Skips cleanly (never fails the suite) when no Obscura binary is
  configured, mirroring the existing `real_obscura_driver` fixture's own
  skip behavior exactly.
- **Depends on**: none — gates Modules 1-3 (if this fails, M1's design
  must change before any other work proceeds, per the proposal's
  resolved U1).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py
  # (modifies test_fixture_site_integration.py:133 — inserted immediately
  #  before `class TestFakeBroker:`, verified: test_fixture_site_integration.py:133)

  class TestObscuraScreencastRecording:
      """Verifies PlaywrightConfig.record_video_dir against a real,
      fresh-context Obscura CDP connection (spike gating FEAT-762)."""

      async def test_record_video_dir_produces_nonempty_webm(
          self, unused_tcp_port: int, tmp_path: "Path"
      ) -> None:
          """Starts its own Obscura process (never reusing `real_obscura_driver`,
          since record_video_dir must be set before PlaywrightDriver.start()),
          connects with engine="obscura" + record_video_dir=tmp_path, navigates
          the local fixture site, calls quit(), and asserts a .webm file exists
          under tmp_path with size > 0. Skips via pytest.skip (never fails) when
          no Obscura binary is configured — same convention as
          `real_obscura_driver` (test_fixture_site_integration.py:79-130),
          verified: test_fixture_site_integration.py:93-95.
          """
  ```

### Module 1: `parrot.e2e.screencast`

- **Path**: `packages/ai-parrot-server/src/parrot/e2e/screencast.py` (new)
- **Responsibility**: Start/stop a Playwright-backed screencast against
  a given Obscura CDP endpoint; enforce the fresh-context precondition
  loudly; finalize and rename the resulting `.webm` to a stable,
  predictable path.
- **Depends on**: Module 0 passing (gate); `PlaywrightDriver`/
  `PlaywrightConfig` from `ai-parrot-tools` — already a declared
  workspace dependency of `ai-parrot-server`
  (`ai-parrot-server/pyproject.toml:34,145`, verified), so this is the
  module's first actual use of that dependency, not a new one.
- **Interface Skeleton**:
  ```python
  # parrot/e2e/screencast.py (new)
  from __future__ import annotations

  from dataclasses import dataclass
  from pathlib import Path

  from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig  # verified: playwright_config.py:95,101-102
  from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver  # verified: playwright_driver.py:107-112,586-618

  from parrot.e2e.errors import E2EError  # verified: parrot/e2e/errors.py (existing typed-error hierarchy)


  class E2EScreencastContextReusedError(E2EError):
      """Raised when the Obscura CDP endpoint already had a browser context.

      record_video_dir only takes effect in engine="obscura" mode when
      PlaywrightDriver._start_obscura_cdp creates a fresh context
      (verified: playwright_driver.py:605-612) — this error makes a reused,
      silently-ignored context a loud failure instead of a no-op recording.
      """


  @dataclass
  class ScreencastSession:
      """A started PlaywrightDriver recording session, not yet finalized."""
      driver: PlaywrightDriver
      out_dir: Path


  async def start_screencast(cdp_endpoint: str, out_dir: Path) -> ScreencastSession:
      """Connect over CDP in a fresh context and begin recording to out_dir.

      Raises:
          E2EScreencastContextReusedError: the endpoint already had a
              browser context (record_video_dir would be silently ignored).
      """

  async def stop_screencast(session: ScreencastSession) -> Path:
      """Close the context (Playwright finalizes the .webm on context.close()
      only — verified against FEAT-763's design-research note on
      WebBrowsingToolkit.close_browser(), same PlaywrightDriver mechanism)
      and rename the resulting file to `<out_dir>/screencast.webm`.
      """
  ```

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
  @click.option("--cdp-endpoint", required=True, help="The browser target's CDP endpoint (e.g. from `parrot e2e up browser`).")
  @click.option("--out", "out_dir", required=True, type=click.Path(path_type=Path))
  @click.option("--owner-id", default=None)
  @click.option("--run-id", "invocation_id", default=None, help="Ticket id, same convention as `up --run-id` (cli.py's own reinterpretation, verified: cli.py:21-35).")
  def screencast_start_command(cdp_endpoint: str, out_dir: Path, owner_id: Optional[str], invocation_id: Optional[str]) -> None:
      """Spawn a detached daemon holding the recording session open; prints a ticket JSON line once ready."""

  @screencast_group.command("stop")
  @click.argument("run_id")
  def screencast_stop_command(run_id: str) -> None:
      """Signal the daemon to close the context and print the finalized .webm path."""
  ```

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
  # screencast start --cdp-endpoint <endpoint> --out artifacts/logs/e2e/<run-id>/
  # --owner-id explore-e2e-ui-tester --run-id <run-id>-screencast`; at the
  # end of exploration, always run `parrot e2e screencast stop
  # --run-id <run-id>-screencast` if one was started, and add its reported
  # path to this observation's evidence_refs."
  # verified: e2e-ui-tester.md:116)
  #
  # (modifies e2e-ui-tester.md:148 — the example `evidence_refs` array
  # gains a second, conditional entry documenting the screencast path
  # shape: "artifacts/logs/e2e/<run-id>/screencast.webm"
  # verified: e2e-ui-tester.md:148)
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_start_screencast_fresh_context_succeeds` | Module 1 | mocked `PlaywrightDriver`: fresh context → `ScreencastSession` returned, `record_video_dir` passed through |
| `test_start_screencast_reused_context_raises` | Module 1 | mocked driver reports an existing context → `E2EScreencastContextReusedError`, never a silent no-op |
| `test_stop_screencast_finalizes_and_renames` | Module 1 | mocked `driver.quit()` + a fake Playwright-written video file → renamed to `<out_dir>/screencast.webm`, path returned |
| `test_screencast_start_command_spawns_ticketed_daemon` | Module 2 | mirrors `test_up_command_*` in the existing `test_cli.py` (verified pattern: `test_cli.py:740`) |
| `test_screencast_stop_command_signals_and_reports_path` | Module 2 | same mirrored pattern |

### Integration Tests

| Test | Description |
|---|---|
| `test_record_video_dir_produces_nonempty_webm` | Module 0 — real Obscura binary, opt-in, skips cleanly without one |

### Validation Contract

tests:
- packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py::TestObscuraScreencastRecording::test_record_video_dir_produces_nonempty_webm
- packages/ai-parrot-server/tests/unit/e2e/test_screencast.py
- packages/ai-parrot-server/tests/unit/e2e/test_cli.py::test_screencast_start_command_spawns_ticketed_daemon
- packages/ai-parrot-server/tests/unit/e2e/test_cli.py::test_screencast_stop_command_signals_and_reports_path
markers: none

### Test Data / Fixtures

```python
# Module 0 reuses the existing local_fixture_site fixture
# (test_fixture_site_integration.py) and builds its own ObscuraProcessManager
# bootstrap inline, following real_obscura_driver's exact pattern
# (verified: test_fixture_site_integration.py:79-130) but WITHOUT reusing
# that fixture directly, since record_video_dir must be set on
# PlaywrightConfig before driver.start() is called and the shared fixture
# does not parameterize it.
```

### E2E Scenarios

Not applicable — this feature adds no deterministic `parrot e2e run`
scenario of its own; its tests run as plain `pytest` (one opt-in
real-binary integration test, the rest mocked unit tests). The `e2e:`
frontmatter key is intentionally omitted (§1 Non-Goals).

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Module 0's spike test exists and either (a) passes against a real
  Obscura binary when run manually with one configured, producing a
  non-empty `.webm`, or (b) skips cleanly (never fails) without one.
- [ ] `start_screencast()` raises `E2EScreencastContextReusedError` —
  never silently records nothing — when the CDP endpoint already has a
  pre-existing browser context.
- [ ] `parrot e2e screencast start` + `parrot e2e screencast stop`
  round-trip produces a `.webm` at a stable, predictable path under
  `artifacts/logs/e2e/<run-id>/`.
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

### Verified Imports

```python
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig  # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py:95,101-102
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver  # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py (module exists, class defined)
from parrot.e2e.errors import E2EError, E2EConfigError, E2EPrerequisiteError  # verified: packages/ai-parrot-server/src/parrot/e2e/errors.py (existing typed-error hierarchy, used throughout cli.py/runner.py)
from parrot.e2e.targets.browser import build_browser_adapter  # verified: packages/ai-parrot-server/src/parrot/e2e/targets/browser.py (factory, existing — read only, never modified)
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
class PlaywrightDriver(AbstractDriver):
    async def start(self) -> None: ...          # line 107 (engine=="obscura" branch returns after _start_obscura_cdp)
    async def quit(self) -> None: ...            # line 157
    def _is_obscura(self) -> bool: ...            # line 521 (property)
    def _cdp_endpoint(self) -> str: ...           # line 577 — returns config.cdp_endpoint_url or f"http://127.0.0.1:{config.obscura_port}"
    async def _start_obscura_cdp(self, browser_launcher) -> None: ...  # line 586
    def _build_context_kwargs(self) -> dict: ...  # line 636 — includes record_video_dir (line 655-656) and record_har_path (657-658) when set

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py
@dataclass
class PlaywrightConfig:
    record_video_dir: Optional[str] = None   # line 95
    engine: str = "playwright"               # line 101
    cdp_endpoint_url: Optional[str] = None   # line 102
    # __post_init__ (existing) requires engine="obscura" => browser_type="chromium"

# packages/ai-parrot-server/src/parrot/e2e/supervisor.py
class E2ESupervisor:
    def _log_path(self, run_id: str, target_id: str) -> Path: ...  # line 889
    # Returns <worktree>/artifacts/logs/e2e/<run_id>/<target_id>.log — the
    # convention a sibling screencast.webm follows (NOT the private
    # sdd/state/e2e/<run_id>/ run_dir from parrot.e2e.state).

# packages/ai-parrot-server/src/parrot/e2e/cli.py
def _daemon_log_path(worktree: Path, invocation_id: str) -> Path: ...  # line 460
async def _spawn_detached_target(...) -> ...: ...                       # line 485 — pattern to mirror for screencast start
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `parrot.e2e.screencast.start_screencast` | `PlaywrightDriver(PlaywrightConfig(engine="obscura", ...))` | direct construction + `await driver.start()` | `playwright_driver.py:107-112,586-618` |
| `parrot.e2e.screencast.start_screencast` | `driver._owns_context` (post-`start()` state) | read, to detect reused vs. fresh context | `playwright_driver.py:81` (`self._owns_context` attribute, set in `_start_obscura_cdp`) |
| `parrot.e2e.cli.screencast_start_command` | `_spawn_detached_target` pattern | mirrors, not calls directly (new daemon entry point for the screencast process) | `cli.py:485` |
| `.claude/agents/e2e-ui-tester.md` | `parrot e2e screencast start`/`stop` | `Bash` tool invocation | `cli.py` (new, Module 2) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.e2e.targets.browser._BrowserAdapter.record_video`~~ — the
  `browser` target adapter has no video-related option; it only spawns
  `obscura serve` (verified absent: `browser.py` `_OWNED_SUPPORTED_OPTIONS
  = frozenset({"port", "stealth", "allow_private_network"})`).
- ~~`RunState.endpoint`~~ — never populated by the supervisor for any
  target kind (per `browser.py`'s own docstring); the CDP endpoint must
  come from `_BrowserAdapter`'s own per-run table or be passed explicitly
  by the caller, never read off a persisted `RunState`.
- ~~`PlaywrightDriver.start_screencast()` / `.record_video()`~~ — no such
  method exists on `PlaywrightDriver` itself; recording is entirely a
  `PlaywrightConfig`-time option plus this feature's own
  `parrot.e2e.screencast` wrapper, never a driver method.
- ~~A `screencast` field in `E2EVerdict` or `VerificationResult`~~ — does
  not exist and this feature does not add one (§1 Non-Goals).

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
| `packages/ai-parrot-server/tests/unit/e2e/test_cli.py` | MODIFY | `def test_resolve_worktree_falls_back_to_start_without_a_git_ancestor(tmp_path: Path) -> None:` | `test_cli.py:740` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- The opt-in, cleanly-skipping real-binary test pattern already used by
  `real_obscura_driver`/`real_playwright_driver` (`pytest.skip`, never
  `pytest.fail`, on a missing binary or failed connection).
- The `up`/`down` detached-daemon/ticket-file lifecycle already in
  `cli.py` (`_spawn_detached_target`, `_daemon_log_path`,
  `artifacts/logs/e2e/_up_tickets/` convention) — Module 2 mirrors this
  rather than inventing a new subprocess-lifecycle mechanism.
- `artifacts/logs/e2e/<run-id>/<target-id>`-shaped file placement
  (`E2ESupervisor._log_path`, `cli.py:889-903`) — the screencast file is
  a sibling in the same per-run directory, not a new top-level location.

### Known Risks / Gotchas

- **Obscura may not support Playwright's video mechanism at all** (no
  row in `docs/obscura-headless-browser.md`'s compatibility matrix for
  video/screencast, and a sibling CDP feature — `get_page_source` — has
  a documented real-binary gap). *Mitigation*: Module 0's gated spike
  runs first; if it fails, Module 1's design must change (e.g. raw CDP
  frame capture) before any further work.
- **A reused CDP context silently drops the recording** even when
  Obscura itself supports the mechanism. *Mitigation*: Module 1 asserts
  `driver._owns_context` after `start()` and raises
  `E2EScreencastContextReusedError` rather than returning a session that
  silently records nothing.
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

None new. `playwright` and `ai-parrot-tools` are already transitive
dependencies of `ai-parrot-server` (verified:
`packages/ai-parrot-server/pyproject.toml:34,145`).

---

## 8. Open Questions

> All open questions raised during the proposal phase were resolved
> there (`sdd/proposals/e2e-browser-screencast-logs.proposal.md` §5);
> none remain blocking at spec time.

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

Status: skipped (the exploration document's status is `discussion`, not
`accepted` — the §3b precondition for an independent `codex` design
review was never met, regardless of `codex` CLI availability).

---

## Worktree Strategy

- **Isolation**: one feature worktree for this spec
  (`feat-FEAT-762-e2e-browser-screencast-logs`); task decomposition
  (`/sdd-task`) may give the `sdd-coder` pool its own sub-worktrees per
  task inside it.
- **Module dependency graph**:
  - M0 (spike test) → no dependencies; gates M1.
  - M1 (`screencast.py`) depends on M0 passing.
  - M2 (`cli.py` subcommands) depends on M1 (imports `start_screencast`/`stop_screencast`).
  - M3 (`e2e-ui-tester.md` prose edit) depends on M2 (needs the final CLI invocation shape).
  - This is a strictly linear chain (M0 → M1 → M2 → M3) — no two modules
    are independent enough to run concurrently; task decomposition
    should reflect that with `depends_on`, not parallel lanes.
- **Shared files**: none touched by more than one module.
- **Exclusive resources**: none — no lockfile, migration, or extension
  rebuild involved.
- **Cross-feature dependencies**: none. (FEAT-763,
  `browsing-playwright-default-and-screencast`, is a related but
  separate feature touching the same `PlaywrightConfig.record_video_dir`
  mechanism from the `WebScrapingToolkit`/browsing-DSL side — no file
  overlap with this spec's Edit Sites, no merge-order dependency.)
