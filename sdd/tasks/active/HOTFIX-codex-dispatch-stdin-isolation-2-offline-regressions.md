# HOTFIX-codex-dispatch-stdin-isolation-2: Verify stdin EOF and timeout lifecycle offline

**Feature**: codex-dispatch-stdin-isolation — Codex dispatch stdin isolation (hotfix)
**Spec**: `sdd/specs/codex-dispatch-stdin-isolation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: HOTFIX-codex-dispatch-stdin-isolation-1
**Assigned-to**: unassigned
**Index**: `sdd/tasks/index/codex-dispatch-stdin-isolation.json`

## Context

Implement spec M2 and AC-2, AC-5, AC-8, and provide regression evidence for
AC-1/3/4/6. Depends on HOTFIX-codex-dispatch-stdin-isolation-1 because tests assert its new
DEVNULL, stderr-tail and cleanup behavior in `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`.

## Scope

- Add a real subprocess regression with the parent stdin pipe held open.
- Cover timeout, cancellation, bounded stderr and concurrent dispatch isolation.
- Update existing process/stream fakes to faithfully support bounded reads and lifecycle.

**NOT in scope**: modifying production code, new dependencies, live Codex requests,
Redis servers, changing model availability, or repeating completed roster work.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py` | MODIFY | Offline launcher integration and lifecycle regressions |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing tests import `CodexCodeDispatchProfile`, `CodexCodeDispatcher`,
`DevelopmentOutput`, `DispatchExecutionError`, `DispatchOutputValidationError`,
`ResearchOutput` from `parrot.flows.dev_loop` at line 12, plus `AsyncMock` and pytest.
Use standard-library asyncio, sys and subprocess facilities as needed.

### Existing Signatures to Use

- `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py:22`: `_AsyncBytesStream`; current `read(self) -> bytes` consumes all
  chunks. Update it to accept a byte count and preserve unread bytes.
- Line 37: `_FakeCodexProcess` with `stdout`, `stderr`, async `wait()` and `kill()`;
  extend lifecycle state where tests need `returncode`, delayed EOF or a kill race.
- Line 80: `dispatcher` fixture supplies fake Redis. Line 110: `_published_events`.
- Line 119: existing command/event tests; line 169: existing failure tests.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:370`: real `_create_process(command)` launcher used by the EOF regression.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:79`: dispatch entrypoint; reverify its private helpers after dependency lands.

Verified initial test SHA-256: `be22769157641bc6d6aecfac26332cae8f543f77baff6c554870735d81e79a28`.

### Does NOT Exist

There is no existing open-parent-stdin integration harness in this test file.
Do not replace pytest's own fd 0, require an installed Codex executable, or assume
zero recorded model usage proves no historical network request occurred.

## Implementation Notes

Keep all tests offline. Reuse fake Redis and temporary paths. Inject short test
wall-clock limits without changing the profile's production minimum (60 seconds).
Use event synchronization for blocked readers and cancellation instead of long
sleeps. Always clean up subprocesses, temporary scripts and pipe descriptors.

## Implementation Blueprint

### Steps (in order)

1. Extend the stream fake for bounded `read(n)` while preserving its readline
   behavior and existing tests. Extend process fakes for realistic returncode,
   blocked wait, kill-triggered EOF, and exit-before-kill behavior.
2. Test the asyncio spawn kwargs using AsyncMock and assert stdin DEVNULL,
   existing stdout/stderr pipes, unchanged limit and argv.
3. Build a temporary Python harness launched with stdin=PIPE. Keep the parent's
   write end open; do not call communicate() on that harness because it closes
   stdin. In the harness, use the actual dispatcher launcher with `sys.executable`
   and a child that reads stdin to EOF then writes a fixed sentinel to stdout.
   Assert the launcher/child phase completes within five seconds and before the
   parent closes its pipe. Separate import/bootstrap time from the EOF deadline
   with a readiness signal. Never replace the production launcher in this test.
4. Cover long stderr (including UTF-8 split across chunks), then timeout; assert
   exact final-tail content, bounds, timeout prefix and one failure event.
5. Cover empty stderr, spawn timeout, reader that never reaches EOF, and a child
   exiting between returncode check and kill. Verify original error preservation
   and no remaining reader/waiter task.
6. Cancel dispatch while child is active; verify kill/reap/reader settlement and
   propagated CancelledError. Also check temporary files and context cleanup.
7. Run concurrent dispatches with distinct stderr sentinels; assert independent
   tails and no cross-contamination.
8. Demonstrate the EOF test fails under the original inherited-stdin behavior
   with a test-local controlled negative harness; bound and clean that negative
   process. Do not commit a production-code mutation to demonstrate failure.
9. Run the focused and existing review suites, formatting and lint checks.

**Why this shape**: the actual subprocess harness catches regressions that a
mock of `_create_process` cannot. The parent pipe remains open, reproducing MCP
transport conditions without contacting a provider.

### Completion checklist

- [ ] Harness and negative control are deterministic and clean up on failure.
- [ ] All spec-listed regression cases exist with meaningful assertions.
- [ ] Full focused suite passes with no pending asyncio tasks.

## Acceptance Criteria

- [ ] AC-1: EOF regression passes with fixed launcher and fails with inherited stdin.
- [ ] AC-2: Timeout stderr bounds, exact tail and UTF-8 handling are asserted.
- [ ] AC-3: Cancellation, exit race, missing process and stuck-reader cases pass.
- [ ] AC-4: Concurrent stderr is isolated and resource cleanup is asserted.
- [ ] AC-5: Existing success, nonzero-exit, invalid-output, event and review tests pass.
- [ ] AC-6: Focused pytest, black/ruff and diff checks pass; evidence is saved in artifacts/logs/.

## Test Specification

Required names from the spec:

- `test_spawn_isolates_stdin`
- `test_spawn_child_gets_eof_with_parent_stdin_open`
- `test_timeout_retains_stderr_tail`
- `test_timeout_without_stderr`
- `test_timeout_before_process_creation`
- `test_timeout_settles_stderr_reader`
- `test_timeout_child_already_exited`
- `test_cancellation_cleans_up_child`
- `test_concurrent_stderr_isolation`

Run `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py packages/ai-parrot/tests/flows/dev_loop/test_adversarial_review.py -q`.
Save results in `artifacts/logs/codex_stdin_regression_tests.log`; run
`black --check --line-length 120` and `ruff check` for both touched Python files.
Use the available project venv, not a newly created worktree venv.

## Agent Instructions

1. Read the approved spec and this task; reverify paths and signatures before edits.
2. Update this task and the per-spec index (never the monolithic index) to in-progress.
3. Implement only the declared files. Do not revert other agents' changes.
4. Run the scoped checks and retain logs in artifacts/logs/.
5. Commit implementation and task state, move the task to sdd/tasks/completed/,
   and set its index entry to done with the completion timestamp and updated file path.
6. Fill in the completion note with real results and deviations.

## Completion Note

Pending execution. No implementation or validation run is claimed by this task artifact.
