# TASK-4842: Prove active-page Obscura screencast capture and encoding

**Feature**: FEAT-762 — Operational screencast logs for the E2E browser exploration flow
**Spec**: `sdd/specs/e2e-browser-screencast-logs.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement only M0 of the approved spec. After an anomaly, the exploration
page already has a browser context. The old `record_video_dir` approach
cannot enable recording on that existing context. This spike must prove a
separate recorder can capture the exact existing page and encode playable
WebM without replacing or closing the page/context.

The feature is only partially decomposed: M1–M3 are intentionally absent
until this task supplies successful real-binary evidence and updates the
backend contract. Completing this task does not complete FEAT-762. Do not
run feature closeout or treat this one-task index as the complete feature.
After a successful spike, rerun sdd-task to append the remaining modules.

## Scope

- Add `TestObscuraScreencastRecording.test_existing_page_produces_playable_webm`
  to the existing integration test module. Keep capture/encoding prototype
  helpers local to that module; do not import future server recorder code.
- Exercise navigation → controlled anomaly → capture of that same page →
  visible post-start change → stop/encode/decode. Include a distinguishable
  second page to make wrong-target recording detectable.
- Validate page/context/state preservation using the original automation
  connection after recorder stop and before the test-owned browser teardown.
- Persist actual results and backend decisions in the evidence report.
  On a real pass, update the spec backend contract and implementation gate
  with tested APIs, dependencies, session ownership, and cleanup ordering.
- On unsupported capture, missing prerequisites, or unavailable binary,
  record the observed limitation and leave this task incomplete; never
  manufacture success or unlock M1–M3 through skip/xfail.

**NOT in scope**: production recorder/CLI/agent implementation, task creation
for M1–M3, dependency installation or manifest changes, changing browser
adapter behavior, changing existing fixture skip semantics, deterministic
gate evidence, global test configuration, or unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py` | MODIFY | Test-local active-page recording prototype and real-binary test. |
| `sdd/state/FEAT-762/screencast-spike.md` | CREATE | Durable actual evidence, selected backend contract or failure analysis. |
| `sdd/specs/e2e-browser-screencast-logs.spec.md` | MODIFY | Replace pending backend contract only when supported by a real pass. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import os
import shutil
from pathlib import Path

import pytest
from aiohttp.test_utils import TestServer
from parrot.mcp.obscura import ObscuraProcessConfig, ObscuraProcessManager
from .fixtures.local_site import local_fixture_site
```

- `os`, `shutil`, and `pytest` are already imported by the target module.
  `Path` is standard library. `TestServer` and `local_fixture_site` are
  verified in `tests/scraping/fixtures/local_site.py:25,151`.
- The target module already imports `local_fixture_site` in its grouped
  fixture import; do not duplicate that import.
- `ObscuraProcessConfig` and `ObscuraProcessManager` are exported directly
  by `packages/ai-parrot-server/src/parrot/mcp/obscura.py:32,66` and imported
  by the existing test fixture at line 105. They are not in ai-parrot core.
- Capture and encoder imports are deliberately not asserted here: select
  and verify actual APIs and dependency declarations before adding them to
  this contract and the implementation. The root `av` override alone is
  not a dependency declaration. New dependencies require user approval.

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/mcp/obscura.py:32
class ObscuraProcessConfig:
    binary_path: str
    port: int = 9222
    host: str = "127.0.0.1"
    stealth: bool = False
    allow_private_network: bool = False
    attach_only: bool = False
    startup_timeout: float = 10.0

# packages/ai-parrot-server/src/parrot/mcp/obscura.py:66,222,343
class ObscuraProcessManager:
    async def start(self) -> str: ...
    async def stop(self) -> None: ...

# packages/ai-parrot-tools/tests/scraping/fixtures/local_site.py:151
async def local_fixture_site(aiohttp_server) -> TestServer: ...
```

`ObscuraProcessManager(config)` returns a manager; `start()` returns its CDP
endpoint and raises on startup/readiness errors. `stop()` terminates only
its owned process. Use an isolated `unused_tcp_port`, `attach_only=False`,
and `allow_private_network=True` for the local fixture site. Ensure owned
cleanup also runs when startup partially fails.

### Does NOT Exist

- `parrot.e2e.screencast` and its production start/stop API: future M1.
- A verified Obscura active-page capture or WebM encoder contract: the
  deliverable of this spike, not a premise.
- A `record_video_dir` option that retrofits existing contexts: the current
  driver only applies context options when it creates a new context.
- A populated browser `RunState.endpoint`: use `manager.start()` here.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py",
      "action": "MODIFY"
    },
    {
      "path": "sdd/state/FEAT-762/screencast-spike.md",
      "action": "CREATE"
    },
    {
      "path": "sdd/specs/e2e-browser-screencast-logs.spec.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessConfig",
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessManager",
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessManager.start",
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessManager.stop",
    "sym:packages/ai-parrot-tools/tests/scraping/fixtures/local_site.py#local_fixture_site"
  ]
}
```

## Implementation Notes

Candidate: page-scoped CDP `Page.startScreencast`, `Page.screencastFrame`,
`Page.screencastFrameAck`, and `Page.stopScreencast`, followed by an approved
encoder. Treat all Obscura support as unproven until measured. Frame data
is not WebM; encoding, flushing, and decoding must be validated too.

Use async I/O, bounded waits, and a bounded frame queue. Run CPU-bound
encoding in a process. Preserve the original client connection and page
until ownership assertions complete. Do not use `real_obscura_driver`
because it converts connection errors to skips. Do not install dependencies
in a shared environment. Store transient logs/video in `artifacts/logs/`;
only the small evidence report belongs in versioned SDD state.

## Implementation Blueprint

### Steps (in order)

1. Verify binary, transport APIs, and encoder availability — the spike must
   prove the deployable dependency path rather than incidental local imports.
2. Add the test-local prototype and test below — existing page identity and
   visible output assertions expose the original design failure.
3. Run against actual Obscura v0.2.2 with captured logs — missing binary may
   skip ordinary suites but cannot satisfy this task's completion criteria.
4. Write the report from measured results — preserve failure evidence as
   well as the exact successful command/environment when available.
5. Update the spec only from a real pass — downstream task decomposition
   requires concrete tested resource types and APIs, not an assumed backend.

### `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py` (MODIFY)

```python
# BEFORE `class TestFakeBroker:` at line 133; occurrences: 1 (verified).
# Add Path and TestServer to imports; keep existing imports/fixtures.
class TestObscuraScreencastRecording:
    """Prove active-page recording against real Obscura before FEAT-762 M1."""

    async def test_existing_page_produces_playable_webm(
        self,
        unused_tcp_port: int,
        tmp_path: Path,
        local_fixture_site: TestServer,
    ) -> None:
        """Capture the selected existing page and decode its post-start change."""
        # FILL IN: detect absent binary only (AC-2); fail configured errors.
        # FILL IN: start isolated manager with finally cleanup (AC-4).
        # FILL IN: original client navigates and observes anomaly (AC-1).
        # FILL IN: separate recorder selects exact page target ID (AC-1).
        # FILL IN: encode/flush/decode visible post-start change (AC-3).
        # FILL IN: preserve page/context/browser after recorder stop (AC-4).
```

**Why**: the existing fixture's bootstrap is reusable as a pattern, but its
broad skip behavior is not. Keep prototype helpers within this file and
verify their imports before use. Resolve all planning markers in actual code.

### `sdd/state/FEAT-762/screencast-spike.md` (CREATE)

```markdown
# FEAT-762 active-page screencast spike

## Result
Record pass, fail, or unavailable based on the actual run; a skip is unavailable.

## Reproduction and environment
Record command, tested implementation commit, Obscura version, package/codec
versions, install requirements, and paths to raw logs and generated artifact.

## Observations
Record page/context identity before/after recorder lifecycle, controlled
anomaly, visible post-start change, decoded frame assertions, and cleanup.

## Backend contract
Record verified imports and API signatures, target selection, transport,
frame handling, encoder flush/decode, resource types, errors, and ownership.
If unavailable, state what failed and what evidence is still required.

## Handoff
State whether M0 passed. Only a real pass plus a frozen spec contract permits
M1–M3 decomposition. This report does not certify the entire feature.
```

**Why**: persist evidence independently of transient logs; replace these
instructions with actual results, never a claim based solely on file size.

### `sdd/specs/e2e-browser-screencast-logs.spec.md` (MODIFY)

```text
REPLACE content under `### Backend Contract Gate` (line 384; occurrences: 1)
only after a real pass: give verified transport/encoder imports and signatures,
concrete session resource types, target identity, errors, cleanup, and approved
dependency availability. Preserve the following Edit Sites section.
UPDATE `**Implementation gate**:` (line 15; occurrences: 1) only with the
actual gate outcome and a reference to sdd/state/FEAT-762/screencast-spike.md.
Reconcile §2 Overview, M0 gate wording, §8 Open Questions, and §7 dependencies
with the proven backend; retain all on-anomaly and ownership requirements.
```

**Why**: prevent an unsupported or skipped spike from unlocking production
work. Do not mark the whole feature complete or weaken remaining criteria.

### FILL IN checklist

- [ ] Verify transport and encoder APIs/imports/dependency availability.
- [ ] Implement real-page prototype, decode assertions, and cleanup checks.
- [ ] Run real binary and populate evidence report with measured results.
- [ ] Freeze the spec contract only after successful real-binary evidence.

## Acceptance Criteria

- [ ] AC-1: Existing-page navigation/anomaly precedes recording; exact target
  selection is proven with a distinguishable second page.
- [ ] AC-2: No configured/discoverable binary skips cleanly in ordinary suites;
  invalid explicit binary, connection, protocol, or codec failures fail.
- [ ] AC-3: Real Obscura v0.2.2 produces playable WebM whose decoded frames
  show the selected page's deterministic post-start visual change.
- [ ] AC-4: Recorder stop preserves the original page/context/state/browser;
  test-owned resources are cleaned up even on failure.
- [ ] AC-5: Report has reproducible command, implementation commit, versions,
  raw evidence paths, actual assertions, and verified backend contract.
- [ ] AC-6: Spec freezes the proven backend and records gate evidence before
  M1–M3 decomposition. A skip/xfail/mock is not completion evidence.
- [ ] AC-7: `ruff check` passes on the modified Python file; no existing test
  behavior is changed. No unauthorized dependency changes or unfinished code.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py::TestObscuraScreencastRecording::test_existing_page_produces_playable_webm -q -rs`

## Test Specification

Run the exact node above with a configured real Obscura binary. Independently
verify the ordinary-suite no-binary skip path. Preserve logs under
`artifacts/logs/`. Assert decoded content, not just a non-empty file. Use
bounded waits and explicit cleanup; do not monkeypatch capture/encoding in
the acceptance run. Capture failures remain visible test failures.

## Agent Instructions

1. Start through `$sdd-start TASK-4842`; it provisions the feature worktree.
2. Verify this contract and the parent spec before implementing.
3. Modify only declared files; a required new dependency needs approval and
   updated scope before proceeding. Do not touch shared environment installs.
4. If prerequisites are unavailable or the candidate fails, record evidence
   and keep the task incomplete. Do not bypass the M0 gate or generate M1–M3.
5. After actual acceptance, commit implementation and use
   `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and exact
   implementation HEAD. Never manually write the Completion Note or move
   this task to completed. Do not use the legacy close_task.sh flow.
6. Handoff to `$sdd-task` for the remaining modules; do not close FEAT-762
   from this deliberately partial task index.

## Completion Note

**Completed**: 2026-10-27/28 — M0 spike by the orchestrator. Result: PASS for the in-connection recorder (Playwright CDPSession); the separate-process recorder is infeasible on Obscura 0.2.2 (per-connection page isolation). Decision (a) taken by the user; spec revised and M1–M3 decomposed (TASK-4864..4866).
**Verification**: `TestObscuraScreencastRecording::test_existing_page_produces_playable_webm` → 1 passed vs real Obscura 0.2.2 (engine merge-tier green); independent code-review findings 1-5,7,10 adopted. Evidence: `sdd/state/FEAT-762/screencast-spike.md`.
**Deviations**: AC-1 "separate recorder" satisfied by the in-connection design per user decision; decoy created first because Obscura only lets the newest page evaluate JS.
