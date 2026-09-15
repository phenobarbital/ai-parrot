---
type: hotfix
base_branch: main
---

# Feature Specification: Codex dispatch stdin isolation

**Identity**: codex-dispatch-stdin-isolation (user-authorized slug identity; no Jira key)
**Date**: 2026-09-15
**Author**: Codex
**Status**: approved
**Target version**: Next patch release containing the Codex dispatcher
**Source consumable**: `artifacts/plan_sdd_codex_timeout_diagnosis.md`

## 1. Motivation & Business Requirements

### Problem Statement

`sdd-coder` launches `codex exec` from an MCP stdio server. The dispatcher
supplies the prompt in argv but inherits the server's open stdin pipe. Installed
codex-cli 0.154.0 also reads piped stdin as additional context and waits for EOF.
Consequently, the child can wait before model execution until the dispatcher's
1800-second deadline expires.

The source diagnosis reproduces this offline: with a prompt and a nonexistent
output-schema file, an open stdin pipe hangs at `Reading additional input from
stdin...`; DEVNULL immediately reaches the missing-schema error. FEAT-147 records
verify 1800.310s and 1800.323s failures for TASK-720 and TASK-721. QuerySource's
roster comment records a third failure, but its terminal record was not recovered.
Historical stdin inheritance is inferred; the blocking mechanism is reproduced.

### Goals

- Ensure a Codex child cannot consume or wait on the MCP server's input channel.
- Preserve useful, bounded stderr diagnostics when dispatch times out.
- Reap the child and settle its stderr reader on timeout or caller cancellation.
- Restore the exact `gpt-5.3-codex-spark` seat requested by the user.
- Verify the fix without credentials, network access, Redis, or model inference.

### Non-Goals

- Readiness probes, cross-task failure quarantine, retry-policy changes, model fallback.
- Changing model IDs, authentication, sandbox permissions, approval policy or deadlines.
- Modifying other dispatchers, `clients/base.py`, QuerySource, or the SDD engine.
- Reintroducing Gemini. The previous `--ask-for-approval` bug is already fixed.

## 2. Architectural Design

### Overview

Keep the current argv-based prompt contract. Set `stdin=asyncio.subprocess.DEVNULL`
in the shared Codex process launcher. Retain stdout/stderr pipes and the existing
stream limit. All Codex coding and review command variants use this launcher.

For stderr, replace the whole-stream accumulation in the dispatch path with a
per-dispatch incremental tail buffer. Read chunks of at most 4096 bytes; retain
at most 4000 decoded characters using an incremental UTF-8 decoder with replacement
for invalid input. Store only the tail, never an unbounded stderr transcript.

Timeout remains `DispatchExecutionError`, with the existing message prefix
`Dispatch exceeded <N>s wall-clock cap`. Append at most the final 1000 stderr
characters when nonempty. The `dispatch.failed` event keeps
`error_class="TimeoutError"` and includes `stderr_tail` of at most 4000 characters,
consistent with the existing nonzero-exit diagnostic limits.

On timeout, kill a still-running direct child, tolerate `ProcessLookupError`, and
settle process wait and stderr draining within a shared five-second cleanup budget.
If a descendant keeps a pipe open, cancel and await pending cleanup/reader tasks
and use the tail already captured. Cleanup failures must not replace the original
timeout. Apply the same cleanup ownership on caller cancellation and re-raise
`asyncio.CancelledError`; never translate cancellation into a dispatch failure.
Initialize task/process handles before awaiting process creation so a timeout
during creation does not reference uninitialized variables. Continue removing
temporary output/schema files and resetting context variables in `finally`.

### Component Diagram

```text
MCP server stdin -> MCP transport only
Task brief -> Codex argv prompt -> Codex child (stdin=/dev/null)
                               -> stdout JSONL -> existing event publisher
                               -> stderr -> bounded per-dispatch tail
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `CodexCodeDispatcher` | Modify launch and lifecycle | Shared coding/review path |
| `CodexCodeDispatchProfile` | Consume unchanged | Existing timeout and sandbox |
| `SddCoderEngine._run_attempt` | Existing caller | No engine changes needed |
| Local MCP roster | Configuration | Exact Spark seat, no fallback |

### Data Models

No public model changes. The bounded tail and reader task are local to each
dispatch, never shared dispatcher state, because concurrent dispatches are allowed.

### New Public Interfaces

None. Existing `dispatch()` and `_create_process()` signatures remain unchanged.
Private helpers may implement the specified buffer and cleanup behavior within
`dispatchers/codex.py`; do not introduce a cross-backend abstraction.

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Launch and lifecycle | yes | DEVNULL stdin; per-call 4000-character stderr tail; five-second cleanup budget; existing error types | — |
| M2: Regression coverage | yes | Real offline child plus injected timeout/cancellation and fake Redis | — |
| M3: Local roster | yes | Exact YAML seat shown below; completed during specification | — |

### Module 1: Codex subprocess isolation and diagnostics

- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`
- **Responsibility**: Implement §2 without changing CLI argument construction.
- **Depends on**: Existing asyncio subprocess and event publication machinery.
- **Interface**: Preserve `async def _create_process(self, command: Sequence[str]) -> Any`
  and `dispatch()` as anchored in §6. Existing `_read_stream()` is private; adapt
  or replace it within this module for incremental bounded stderr capture.

### Module 2: Offline regression tests

- **Path**: `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py`
- **Responsibility**: Cover the inherited-input failure at the actual launcher
  boundary, then timeout diagnostics and cleanup at the dispatch boundary.
- **Depends on**: M1 and existing dispatcher/event fixtures.
- **Interface**: Extend pytest tests; no public production interface.

### Module 3: Restore the local Spark seat

- **Path**: `.parrot/mcp-toolkits.yaml` (git-ignored local configuration).
- **Responsibility**: Restore exactly one seat before native Haiku:

```yaml
- {label: codex-spark, kind: mcp, backend: codex, model: gpt-5.3-codex-spark}
```

- **Depends on**: Existing roster model. Runtime success still depends on M1.
- **State**: Applied at the user's explicit request during specification creation.
  No fallback, global default-model change, or external repository edit.

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_spawn_isolates_stdin` | M1 | Intercept asyncio spawn; verify DEVNULL with existing stdout/stderr pipes and argv preserved |
| `test_timeout_retains_stderr_tail` | M1 | Child emits more than 4000 characters then stalls; event tail <=4000 and exception tail <=1000, preserving timeout prefix |
| `test_timeout_without_stderr` | M1 | Empty stderr still reports original timeout and performs cleanup |
| `test_timeout_before_process_creation` | M1 | Delayed spawn times out without uninitialized-handle errors |
| `test_timeout_settles_stderr_reader` | M1 | Stalled reader is cancelled/awaited under bounded cleanup; no pending reader task |
| `test_timeout_child_already_exited` | M1 | Exit/kill race preserves original error rather than ProcessLookupError |
| `test_cancellation_cleans_up_child` | M1 | Caller cancellation reaps child, settles reader, propagates CancelledError |
| `test_concurrent_stderr_isolation` | M1 | Two concurrent dispatches retain only their own diagnostic tails |

### Integration Tests

| Test | Description |
|---|---|
| `test_spawn_child_gets_eof_with_parent_stdin_open` | An isolated Python harness has a pipe as stdin; keep its write end open. The harness invokes the real `_create_process()` with a Python child that reads stdin until EOF then prints a sentinel. Assert completion within five seconds while the parent pipe remains open. The unfixed launcher must fail this assertion. |

### Test Data / Fixtures

Use `sys.executable` and temporary scripts for the harness/child, no installed
Codex CLI required. Only the isolated harness may own a replaced stdin descriptor;
never change pytest's stdin. Close all pipe descriptors and reap both harness and
child on failure. Extend `_AsyncBytesStream` to support chunked reads as needed.
Use existing fake Redis/event capture fixtures. Inject short deadlines in tests
without changing the validated production profile minimum of 60 seconds.

Run the dispatcher suite and existing adversarial-review tests; store logs under
`artifacts/logs/`. Run black (120 columns), ruff, and `git diff --check` on touched
Python files. Live Spark checks are optional follow-up evidence, not CI gates.

## 5. Acceptance Criteria

- [ ] AC-1: Every process launched through `_create_process()` receives DEVNULL stdin.
- [ ] AC-2: The isolated open-parent-pipe regression passes offline and detects the old implementation.
- [ ] AC-3: Timeout diagnostics preserve the existing exception/event contract and bounded stderr tails.
- [ ] AC-4: Timeout/cancellation settles the direct child and reader without leaking tasks; race and empty-stderr cases pass.
- [ ] AC-5: Success, nonzero exit, invalid output, event forwarding and review command behavior remain covered and passing.
- [ ] AC-6: Stderr memory is bounded per dispatch, including concurrent dispatches.
- [x] AC-7: Local roster restores exactly one `codex-spark` seat with the requested model and no fallback.
- [ ] AC-8: Focused tests, formatting, lint and diff checks pass with logs in `artifacts/logs/`.

## 6. Codebase Contract

Anchors were verified in the current working checkout on 2026-09-15. Reverify
against the clean main-based implementation worktree before coding.

### Verified Imports

Existing production imports in `dispatchers/codex.py:10` include `asyncio`,
`json`, `logging`, `os`, `tempfile`, `time`; typing imports are at line 17.
`codecs` may be added from the standard library for incremental decoding.
Tests already import `CodexCodeDispatcher`, `CodexCodeDispatchProfile`,
`DispatchExecutionError` and `DevelopmentOutput` from `parrot.flows.dev_loop`
at `test_codex_dispatcher.py:12`; exports are in `dev_loop/__init__.py:15` and `:42`.

### Existing Class Signatures

| Symbol | Exact existing contract | Verified at |
|---|---|---|
| `CodexCodeDispatcher._create_process` | `async def _create_process(self, command: Sequence[str]) -> Any` | `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:370` |
| `CodexCodeDispatcher._read_stream` | `async def _read_stream(self, stream: Any) -> str` | Same file, line 503 |
| `CodexCodeDispatcher.dispatch` | Keyword-only brief, profile, output_model, run_id, node_id, cwd; optional session_host and labels; returns T | Same file, line 79 |
| `DispatchExecutionError` | Existing exception class | `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py:418` |
| `CodexCodeDispatchProfile.timeout_seconds` | Default 1800, minimum 60, maximum 7200 | `packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py:22` |
| `RosterSeat` | label, kind, backend, model, fallback_model | `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:45` |
| `RosterConfig` | Required seats list | Same file, line 116 |

### Integration Points

| New Behavior | Connects To | Via | Verified At |
|---|---|---|---|
| Input isolation | Codex process | `asyncio.create_subprocess_exec` | `dispatchers/codex.py:372` |
| Timeout diagnostic tail | Existing failure event | `_publish_event` | `dispatchers/codex.py:172` |
| Cleanup | Existing temporary-file/context cleanup | `finally` | `dispatchers/codex.py:223` |
| Regression fixture | Existing fake process | `_FakeCodexProcess` | `tests/flows/dev_loop/test_codex_dispatcher.py:37` |

### Does NOT Exist (Anti-Hallucination)

- The launcher currently has no explicit stdin isolation or timeout stderr tail.
- The default roster probe is not a live model-access check (`sdd_coder/roster.py:73`).
- `.parrot/mcp-toolkits.yaml` is local ignored configuration, not a tracked model catalog.
- No root-level `parrot/` source directory exists; use distribution paths above.

## 7. Implementation Notes & Constraints

### Patterns to Follow

Async I/O only, standard-library additions only, small focused diffs, black and
ruff. Preserve approval/sandbox behavior and the profile's configured model.
Do not print diagnostics or dump environment variables, authentication or prompts.
Keep stderr reporting within the existing dispatcher diagnostic policy.

### Known Risks / Gotchas

- Restoring Spark does not itself fix the launcher; apply M1 before relying on the seat.
- EOF waits can occur even with a positional prompt. Supplying argv is not isolation.
- Descendants can keep inherited output pipes open; bound cleanup rather than
  waiting indefinitely after killing the direct child.
- Zero recorded usage does not prove the provider was never contacted historically.
- Current working tree contains unrelated modifications; do not revert or stage them.

### External Dependencies

None added. Use Python asyncio/codecs and existing pytest/pytest-asyncio tooling.

### Worktree Strategy

Isolation: per-spec. Resolve flow with `resolve_flow(kind="bug")`, yielding
`type: hotfix`, `base_branch: main`; no FEAT ID reservation is required.
Implementation requires a separate worktree from synchronized `origin/main`.
The user explicitly authorized `codex-dispatch-stdin-isolation` as the hotfix
identity. Use task IDs `HOTFIX-codex-dispatch-stdin-isolation-1` and `-2`, and
branch/worktree `hotfix-codex-dispatch-stdin-isolation`. This is an authorized
naming exception; do not pass a fabricated Jira key to `plan_worktree()`.
Base synchronization was not performed during authoring because the current dev
checkout contains unrelated changes. Verify the anchored dispatcher exists on
main before implementation; report any base-contract mismatch before editing.
Commit only this specification during the spec phase. The local roster remains
outside Git. The source artifact is ignored, so §1 preserves its essential evidence.

## 8. Open Questions

- [x] Input mechanism: preserve argv prompt and provide DEVNULL stdin.
- [x] Model: restore exactly gpt-5.3-codex-spark, with no fallback.
- [x] Scope: include bounded timeout diagnostics and cleanup; defer readiness/quarantine.
- [x] Flow: hotfix/main as resolved for bug work; author Codex, status approved.

No unresolved design questions. Release numbering is assigned by the release process.

## 9. Design Research Cross-Check

Status: skipped. No independent design-review session was launched. Evidence is
the consumed diagnostic artifact, reproduced offline behavior and inspected code.
This is not represented as an independent review or a live Spark availability test.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-15 | Codex | Hotfix spec from timeout diagnosis; local Spark restoration |
