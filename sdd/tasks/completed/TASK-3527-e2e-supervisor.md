# TASK-3527: Own target subprocesses and bounded readiness/teardown

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3526
**Assigned-to**: unassigned
**Module**: M3
**Spec acceptance criteria**: AC3, AC5, AC6

---

## Context

Implement the M3 deliverable **Own target subprocesses and bounded readiness/teardown** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Implement start/request_stdio/stop interfaces; spawn a separate process group per target and register identity before readiness.
- Apply clean worktree source/env/config isolation, strip model credentials for deterministic targets, record module origins and logs.
- Enforce real protocol readiness plus child identity; retry one verified port collision within original deadline.
- On errors/cancel/stop, TERM then wait ≤10s then KILL/reap; preserve unresolved state and never signal adopted/foreign processes.
- Implement lifecycle-report registration handshake; watchdog integration lands in its dependent task before any public CLI use.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/supervisor.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/tests/unit/e2e/test_supervisor.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/src/parrot/mcp/obscura.py:66` — Freshness: manager now has context-manager, atexit and signal hooks (lines 97-168), start at 222 and stop at 343. Preserve these newer ownership semantics. Signature: `ObscuraProcessManager(config: ObscuraProcessConfig, logger: Optional[logging.Logger] = None); async start() -> str; async stop() -> None`. Source SHA-256: `03b2cc237b705144230dc7b2907ba9e38b826faec20d167f099926ef059ddb73`.
- `packages/ai-parrot-server/src/parrot/mcp/server.py:36` — Transport selection and ownership already exist; this wrapper is not a supervisor. Signature: `MCPServer(config: MCPServerConfig, parent_app: Optional[web.Application] = None); register_tools(tools); async start(); async stop()`. Source SHA-256: `73637e33dfd6bc014a1ef7c246bb952136ef1d06a3c5f25c173493bd6afe46af`.

```python
from parrot.mcp.obscura import ObscuraProcessManager
from parrot.mcp.server import MCPServer
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3526 (`sdd/tasks/active/TASK-3526-e2e-control-channel.md`) must be done; consume its declared interfaces and re-read its completion evidence.

- `E2ESupervisor.start(target_id: str, config: TargetConfig) -> RunState (async)`
- `E2ESupervisor.request_stdio(run_id: str, payload: dict[str, JsonValue]) -> dict[str, JsonValue] (async)`
- `E2ESupervisor.stop(run_id: str) -> RunState (async)`

### Modify-Target Freshness

All task targets are CREATE; check for collisions before writing them.

### Does NOT Exist

- The new E2E harness and run/verify machinery do not exist at decomposition time;
  dependent task outputs are not pre-existing imports.
- No `E2ECriterion`, universal agent `/mcp/info`, reliable cookie session backend,
  or automatic provider-wide request budget may be assumed.
- Eligibility annotations are not Delegation Contracts. This task follows normal
  implementation routing until a complete validated code packet is authored.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/e2e/supervisor.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_supervisor.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessManager",
    "sym:packages/ai-parrot-server/src/parrot/mcp/server.py#MCPServer"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3527 owns its declared files for M3. TASK-3526 supplies implement private supervisor control and stdio rpc channel. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Implement start/request_stdio/stop interfaces; spawn a separate process group per target and register identity before readiness.
2. Apply clean worktree source/env/config isolation, strip model credentials for deterministic targets, record module origins and logs.
3. Enforce real protocol readiness plus child identity; retry one verified port collision within original deadline.
4. On errors/cancel/stop, TERM then wait ≤10s then KILL/reap; preserve unresolved state and never signal adopted/foreign processes.
5. Implement lifecycle-report registration handshake; watchdog integration lands in its dependent task before any public CLI use.

### Fixed interfaces

- `E2ESupervisor.start(target_id: str, config: TargetConfig) -> RunState (async)`
- `E2ESupervisor.request_stdio(run_id: str, payload: dict[str, JsonValue]) -> dict[str, JsonValue] (async)`
- `E2ESupervisor.stop(run_id: str) -> RunState (async)`

### `packages/ai-parrot-server/src/parrot/e2e/supervisor.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Implement start/request_stdio/stop interfaces; spawn a separate process group per target and register identity before readiness.

2. Apply clean worktree source/env/config isolation, strip model credentials for deterministic targets, record module origins and logs.

3. Enforce real protocol readiness plus child identity; retry one verified port collision within original deadline.

4. On errors/cancel/stop, TERM then wait ≤10s then KILL/reap; preserve unresolved state and never signal adopted/foreign processes.

5. Implement lifecycle-report registration handshake; watchdog integration lands in its dependent task before any public CLI use.
### `packages/ai-parrot-server/tests/unit/e2e/test_supervisor.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Implement start/request_stdio/stop interfaces; spawn a separate process group per target and register identity before readiness.
- [ ] Apply clean worktree source/env/config isolation, strip model credentials for deterministic targets, record module origins and logs.
- [ ] Enforce real protocol readiness plus child identity; retry one verified port collision within original deadline.
- [ ] On errors/cancel/stop, TERM then wait ≤10s then KILL/reap; preserve unresolved state and never signal adopted/foreign processes.
- [ ] Implement lifecycle-report registration handshake; watchdog integration lands in its dependent task before any public CLI use.
- [ ] Relevant spec criteria AC3, AC5, AC6 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_supervisor.py -q`

## Test Specification

Use focused tests covering success, invalid input, prerequisite failure and cleanup. Assert the outcomes named in Scope; construction-only tests are insufficient.

Test the boundary and negative cases from Scope using the exact task-owned test file(s).

**Runtime E2E validation:** ordinary SDD test selection intentionally excludes E2E.
After the required harness dependencies exist, run declared scenario node IDs via
`parrot e2e run --plan` with `PARROT_TEST_E2E=1`. Live execution additionally needs
`PARROT_TEST_REAL_LLM=1` and the provider key. These are separate from the file-level
pytest contract above. This task cannot claim E2E success solely from agent-tier tests.

## Agent Instructions

1. Read the approved spec and confirm every Depends-on task is done in the per-spec index.
2. For research-gated work, read the completed research contract; BLOCKED research
   does not authorize guessing its unresolved interface.
3. Update `sdd/tasks/index/agentic-e2e-testing.json` to in-progress with assignment/time.
4. Verify imports/signatures, then implement this task's bounded blueprint.
5. Run Validation Commands and applicable runtime probes; retain useful logs.
6. Commit scoped code and SDD state, move this task to `sdd/tasks/completed/`,
   update its index file path/status/timestamps and fill the Completion Note.
7. Never update the historical monolithic task index.

## Completion Note

Completed 2026-09-19. Implemented `E2ESupervisor` with the exact fixed
interfaces: `async start(target_id, config) -> RunState`,
`async request_stdio(run_id, payload) -> dict`, `async stop(run_id) ->
RunState`. Spawns each target in its own process group, captures
`ProcessIdentity`, and persists the initial `starting` `RunState` BEFORE
polling readiness (per TASK-3517's research). Non-stdio targets poll
`TargetAdapter.ready()`; `stdio` targets use supervisor-owned pipe
liveness — every readiness verdict cross-checked against real
`psutil`-observed liveness and `process_identity_matches`. Exactly one
port-collision retry within the original startup deadline. Teardown:
SIGTERM → wait ≤10s → SIGKILL → bounded reap, re-validated via
`is_authorized_to_signal` immediately before every signal — never signals
an adopted/foreign/reused-PID run; unresolved cleanup persists as `failed`,
never a fabricated `stopped`. Each run gets its own `ControlServer` (from
TASK-3526) exposing `status`/`stop`/`stdio` back into this same instance.
Strips model-credential env vars from every spawned target's environment
(unconditional superset), sets `PYTHONDONTWRITEBYTECODE=1`, records
argv/cwd/pythonpath (never env values) per-run under `artifacts/logs/e2e/`.

Two documented, necessary deviations (both reviewed and CONFIRMED — not
scope creep):
1. AF_UNIX control-socket path: this worktree's own path already exceeds
   the 108-byte `sun_path` limit before any run_id is appended (verified
   directly), so `_resolve_control_socket_path` falls back to a short,
   still mode-0700 path under the system temp dir when the spec-literal
   path would not fit.
2. `RunState.endpoint` is always persisted as `None` — neither
   `TargetAdapter.prepare()`/`ready()` gives this module an HTTP endpoint;
   this matches the field's documented valid meaning pending concrete M4
   adapter work, no interface invented.
3. Deferred control-server teardown on remote `stop`: `ControlServer.stop()`
   is scheduled via `asyncio.create_task` rather than awaited inline when
   `stop` is invoked as that same server's own RPC handler (awaiting inline
   deadlocks — `wait_closed()` would wait for the very connection running
   the handler). Verified fixed with a real socket round-trip test.

During implementation, found and fixed two genuine correctness gaps (not
test artifacts) surfaced by a real ~35%-flaky readiness race: (a)
`asyncio`'s child-watcher-driven `returncode` is not reliably resolved
under load across pytest-asyncio's per-test event loops, so `_await_ready`
now cross-checks real `psutil` liveness; (b) the test's own fake adapter
was unconditionally claiming readiness — fixed in the test, not production.

Tests: `pytest packages/ai-parrot-server/tests/unit/e2e/test_supervisor.py -q`
→ 19 passed (stable over 15 repeats after the readiness-race fix). Full-dir
regression: `pytest packages/ai-parrot-server/tests/unit/e2e/ -q` → 245
passed (226+19), no regression against TASK-3520/3521/3524/3525/3526.
`ruff check`: 1 real ASYNC230 finding (blocking `open()` in async code)
fixed via `asyncio.to_thread`, not suppressed.

No unresolved limitations beyond the two documented deviations above.
AC3/AC5/AC6 demonstrated by the contract tests. Watchdog spawn/heartbeat
explicitly deferred to TASK-3528, per this task's own scope note.

Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: 2096.8s · Tokens: 323802 (combined)
