---
kind: brief
slug: e2e-up-launcher-exit-survival
key: 792b6e2a8f25
base_branch: dev
source:
  type: ledger
  ref: issue:792b6e2a8f25
  url: null
jira_issue_key: null
ledger_issue: issue:792b6e2a8f25
created: "2026-10-18"
---

# Brief: Real-subprocess launcher-exit survival test for `parrot e2e up` (AC5)

## Problem

Ledger issue `issue:792b6e2a8f25` (major, feature_gap, discovered in the
TASK-3534 / FEAT-581 code review):

> The `up` command's detached-daemon lifecycle (`_run_daemon` /
> `_spawn_detached_target`) is unit-tested only with monkeypatched
> `asyncio.create_subprocess_exec` and a faked `E2ESupervisor`
> (test_cli.py:302-419). The design is plausible (`start_new_session=True`),
> but there is no integration test that actually spawns `up`, kills the
> invoking CLI process, and confirms the daemon+target genuinely survive —
> the specific sub-claim of AC5 ("survives launcher exit") is designed-for,
> not empirically verified.

## Root cause

Not a code bug — a missing test tier. TASK-3534 deliberately scoped its tests
to monkeypatched unit tests and noted the real-subprocess acceptance tier
"belongs to the M5/M9 integration/E2E scenario suite", but no task ever
materialized that scenario. The suite it belongs to now exists
(`packages/ai-parrot-server/tests/e2e/`, opt-in via `PARROT_TEST_E2E=1`),
so the gap is purely the absent scenario file.

Verified anchors:
- `packages/ai-parrot-server/src/parrot/e2e/cli.py:467` — `_spawn_detached_target` (spawns the daemon, polls the readiness ticket)
- `packages/ai-parrot-server/src/parrot/e2e/cli.py:527` — `start_new_session=True` (the survival mechanism under test)
- `packages/ai-parrot-server/src/parrot/e2e/cli.py:616` — `_run_daemon` (daemon owns the supervised target until signal / cleanup_complete)
- `packages/ai-parrot-server/tests/e2e/conftest.py:28` — opt-in gate (`e2e` marker skipped unless `PARROT_TEST_E2E=1`)
- `packages/ai-parrot-server/tests/unit/e2e/test_cli.py:370` — existing fake-only coverage the issue cites

## Research findings

- `up` prints one RunState JSON line and exits; the daemon
  (`python -m parrot.e2e.cli _run-daemon`) keeps running detached. `RunState`
  carries `supervisor_identity` (daemon) and `process_identity` (target), each
  a `ProcessIdentity` (pid+pgid+create_time+boot_id) — exactly what a survival
  assertion needs without pid-reuse false positives (`models.py:300-336`).
- `_resolve_worktree()` (cli.py:107) walks up from cwd to the nearest `.git`,
  so the test invokes the CLI with `cwd=e2e_worktree` (the repo root the
  existing `e2e_worktree` fixture already provides).
- `down <run_id>` (cli.py:839) + `_run_daemon`'s poll of
  `cleanup_complete` give the deterministic teardown path; existing suite
  tests fall back to `os.killpg` + state cleanup in `finally` blocks
  (test_supervisor.py pattern).
- Cheapest real target: `mcp-stdio` (fixture `mcp_stdio_config`,
  `startup_timeout_s=30`).
- `asyncio_mode = "auto"` and the `e2e` marker are configured in
  `packages/ai-parrot-server/pyproject.toml:131,139`.
- Related ledger issue `issue:e21ec87c6aba`: real-subprocess tests under
  `tests/unit/e2e/` are flaky when run together (resource contention). The new
  scenario therefore goes in `tests/e2e/` behind the opt-in gate, not in
  `tests/unit/e2e/`.

## Assumptions

(No interview round was needed; research settled the open points.)

- Location: `packages/ai-parrot-server/tests/e2e/` (the issue body itself
  assigns the gap to this suite).
- Target kind: `mcp-stdio` — cheapest supported real target with an existing
  config fixture.
- Two scenarios cover AC5's sub-claim: (a) natural launcher exit after
  readiness, (b) SIGKILL of the launcher while it is still polling for the
  ticket — the daemon must still reach readiness and the target must survive.

## Fix plan

- **HOTFIX-792b6e2a8f25-1** — Add
  `packages/ai-parrot-server/tests/e2e/test_up_detached_lifecycle.py` with two
  opt-in real-subprocess scenarios: launcher-exit survival and
  launcher-SIGKILL survival, both asserting daemon+target liveness via
  `ProcessIdentity` (pid + create_time) and tearing down via `down` with a
  killpg fallback.

## Validation commands

```bash
PARROT_TEST_E2E=1 PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src \
  pytest packages/ai-parrot-server/tests/e2e/test_up_detached_lifecycle.py -q
```
