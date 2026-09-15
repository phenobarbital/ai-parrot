# HOTFIX-codex-dispatch-stdin-isolation-1: Isolate Codex input and bound subprocess diagnostics

**Feature**: codex-dispatch-stdin-isolation — Codex dispatch stdin isolation (hotfix)
**Spec**: `sdd/specs/codex-dispatch-stdin-isolation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Index**: `sdd/tasks/index/codex-dispatch-stdin-isolation.json`

## Context

Implement spec M1 and AC-1, AC-3, AC-4, AC-6. Codex inherits the MCP server's
open stdin and waits for EOF despite receiving its prompt in argv. Preserve
existing API behavior while removing this transport coupling.

## Scope

- Supply DEVNULL stdin to every launch through the shared Codex launcher.
- Drain stderr incrementally into a per-dispatch bounded tail.
- Preserve diagnostics on timeout and nonzero exit.
- Bound timeout/cancellation cleanup and settle reader tasks.

**NOT in scope**: tests owned by HOTFIX-codex-dispatch-stdin-isolation-2, roster changes (already complete),
readiness probes, failure quarantine, retry policy, other dispatchers, model changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` | MODIFY | Input isolation, bounded stderr, owned process cleanup |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing module imports: `import asyncio` (line 10), `from typing import Any,
Dict, List, Optional, Sequence, Type` (line 17). Existing exception imports from
`parrot.flows.dev_loop.dispatchers._shared` include `DispatchExecutionError`.
`codecs` may be added from the standard library for incremental UTF-8 decoding.
No external dependency is needed.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:79`: `async def dispatch(self, *, brief: BaseModel,
  profile: CodexCodeDispatchProfile, output_model: Type[T], run_id: str,
  node_id: str, cwd: str, session_host: Optional[SessionHost] = None,
  labels: Optional[DispatchLabels] = None) -> T`.
- Line 370: `async def _create_process(self, command: Sequence[str]) -> Any`.
- Line 503: `async def _read_stream(self, stream: Any) -> str` (private;
  adapt/replace locally for incremental reading).
- Line 145: existing timeout scope. Line 194: nonzero-exit event stderr_tail.
- Line 223: existing context reset and temporary-file cleanup.

Verified source SHA-256: `a0b81630df781f6e0c0e641e0e590190972bf8cc677f752962f4dd6e22c3fcf3`.

### Does NOT Exist

There is no explicit stdin isolation, bounded incremental stderr collector,
caller-cancellation cleanup, or timeout stderr_tail in the current dispatcher.
Do not assume a process-group helper exists or modify shared backend machinery.

## Implementation Notes

Preserve `_build_command`, sandbox/approval/model settings, stdout JSONL projection,
output validation, profile deadlines and exception types. Buffers belong to each
call, never the dispatcher instance. Retain at most 4000 decoded characters;
read at most 4096 bytes per iteration. Decode with incremental UTF-8 replacement
so split multibyte sequences are handled. No complete stderr transcript in memory.

## Implementation Blueprint

### Steps (in order)

1. In `_create_process`, immediately after `*command,`, insert:

```python
stdin=asyncio.subprocess.DEVNULL,
```

   This anchor occurs once in `_create_process`; retain both output pipes and
   `limit=8 * 1024 * 1024`. The prompt remains in argv.
2. Introduce a private per-dispatch tail holder and asynchronous reader in this
   module. Read bounded chunks, incrementally decode and trim on every update.
   Flush the decoder at EOF. Handle missing stderr as an empty tail.
3. Initialize process and reader-task handles before spawn. Start the stderr
   reader alongside the existing stdout event loop. Successful and nonzero paths
   use the bounded tail after reader completion.
4. Add a private cleanup operation that checks child returncode, kills only a
   running child, tolerates ProcessLookupError, and settles process wait and
   reader within one five-second budget. On budget exhaustion cancel and await
   pending waiter/reader tasks. Do not discard the already captured tail.
5. On timeout, invoke cleanup and publish one dispatch.failed event with
   error_class TimeoutError, the existing timeout message and stderr_tail <=4000.
   Raise DispatchExecutionError with the exact original prefix and append <=1000
   stderr characters only if nonempty. Cleanup errors must not mask the timeout.
6. On caller cancellation, invoke bounded cleanup and propagate CancelledError.
   Keep existing temporary-file cleanup and context resets. Ensure cancellation
   while queued cannot leak context bindings, without changing public signatures.
7. Preserve nonzero-exit diagnostic bounds and existing successful output flow.

**Why this shape**: input isolation fixes the reproduced pre-model hang;
concurrent bounded draining preserves diagnostics without creating a new pipe
backpressure problem. Cleanup is bounded because descendants can retain pipes.

### Completion checklist

- [ ] DEVNULL applied at the shared launcher boundary.
- [ ] Incremental decoding and per-call memory bounds implemented.
- [ ] Timeout/exit/cancellation cleanup handles empty or unavailable process state.
- [ ] Context variables, temporary files and original exception semantics preserved.

## Acceptance Criteria

- [ ] AC-1: Launch cannot read the MCP parent's stdin.
- [ ] AC-2: Timeout event tail <=4000 and exception tail <=1000 characters.
- [ ] AC-3: Original timeout prefix and CancelledError propagation preserved.
- [ ] AC-4: Per-call collector and cleanup have no shared mutable tail or dangling reader task.
- [ ] AC-5: Existing dispatcher and adversarial review suites pass.
- [ ] AC-6: black --check --line-length 120, ruff check and git diff --check pass for the changed file.

## Test Specification

Run existing `test_codex_dispatcher.py` and `test_adversarial_review.py` under
`packages/ai-parrot/tests/flows/dev_loop/` before committing. Save logs under
`artifacts/logs/codex_stdin_existing_tests.log`. New regression coverage is the
next task; passing existing tests alone does not complete the hotfix.

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
