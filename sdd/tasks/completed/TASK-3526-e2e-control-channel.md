# TASK-3526: Implement private supervisor control and stdio RPC channel

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3524, TASK-3525
**Assigned-to**: unassigned
**Module**: M3
**Spec acceptance criteria**: AC3, AC5, AC6

---

## Context

Implement the M3 deliverable **Implement private supervisor control and stdio RPC channel** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Implement the ACK/control framing frozen by the lifecycle report over a contained private Unix socket.
- Support owner-bound start/status/stop and serialized stdio exchange; enforce message size, matching JSON-RPC IDs and deadlines.
- Preserve supervisor-owned stdin/stdout pipes; never reopen stdio by PID or send secrets on CLI argv.
- Reject malformed requests, foreign owners and stale run IDs; close sockets/pipes on cancellation.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/control.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/tests/unit/e2e/test_control.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `tests/mcp/test_mcp_local_e2e.py:72` — Legacy helpers illustrate pipes/EOF, but _recv currently uses a blocking readline despite a timeout argument; new supervisor must enforce a real deadline. Signature: `def _spawn(cwd: Path, *args: str) -> subprocess.Popen`. Source SHA-256: `4849a8cf317883d64dcc0c2f9c41b6dec4ebd7ac646d1506a48ae3606e03d1de`.

No unverified project import is prescribed.

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3524 (`sdd/tasks/active/TASK-3524-e2e-run-state.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3525 (`sdd/tasks/active/TASK-3525-e2e-target-protocol.md`) must be done; consume its declared interfaces and re-read its completion evidence.

- `ControlClient.request(operation: str, payload: dict[str, JsonValue]) -> dict[str, JsonValue] (async; schema frozen by research gate)`

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
      "path": "packages/ai-parrot-server/src/parrot/e2e/control.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_control.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:tests/mcp/test_mcp_local_e2e.py#_spawn"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3526 owns its declared files for M3. TASK-3524 supplies persist locked run state and validate process identity; TASK-3525 supplies define target adapter protocol and lazy fixed registry. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Implement the ACK/control framing frozen by the lifecycle report over a contained private Unix socket.
2. Support owner-bound start/status/stop and serialized stdio exchange; enforce message size, matching JSON-RPC IDs and deadlines.
3. Preserve supervisor-owned stdin/stdout pipes; never reopen stdio by PID or send secrets on CLI argv.
4. Reject malformed requests, foreign owners and stale run IDs; close sockets/pipes on cancellation.

### Fixed interfaces

- `ControlClient.request(operation: str, payload: dict[str, JsonValue]) -> dict[str, JsonValue] (async; schema frozen by research gate)`

### `packages/ai-parrot-server/src/parrot/e2e/control.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Implement the ACK/control framing frozen by the lifecycle report over a contained private Unix socket.

2. Support owner-bound start/status/stop and serialized stdio exchange; enforce message size, matching JSON-RPC IDs and deadlines.

3. Preserve supervisor-owned stdin/stdout pipes; never reopen stdio by PID or send secrets on CLI argv.

4. Reject malformed requests, foreign owners and stale run IDs; close sockets/pipes on cancellation.
### `packages/ai-parrot-server/tests/unit/e2e/test_control.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Implement the ACK/control framing frozen by the lifecycle report over a contained private Unix socket.
- [ ] Support owner-bound start/status/stop and serialized stdio exchange; enforce message size, matching JSON-RPC IDs and deadlines.
- [ ] Preserve supervisor-owned stdin/stdout pipes; never reopen stdio by PID or send secrets on CLI argv.
- [ ] Reject malformed requests, foreign owners and stale run IDs; close sockets/pipes on cancellation.
- [ ] Relevant spec criteria AC3, AC5, AC6 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_control.py -q`

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

Completed 2026-09-19. Implemented `ControlServer`/`ControlClient` (plus
`ControlChannelError`, `ControlHandler`, `MAX_MESSAGE_BYTES`,
`SOCKET_FILE_MODE`, `DEFAULT_REQUEST_DEADLINE_S`) with the exact fixed
interface `ControlClient.request(operation, payload) -> dict[str, JsonValue]`
(async). `ControlServer` is generic — it dispatches to a caller-supplied
`operations` mapping and has no built-in start/status/stop semantics of its
own; TASK-3527 (`E2ESupervisor`, the sole dependent) owns what each
operation does. Wire shape: newline-delimited JSON-RPC 2.0 over a Unix
domain socket, mode 0600, per the TASK-3517 research spike's frozen
contract. Every read (both sides) goes through `asyncio.wait_for` — no
blocking `readline()` gap. Authorization checked most-definitive-first
(envelope shape → stale run_id → foreign owner_id) before any handler
dispatch. 1 MiB message-size ceiling enforced on encode and read.
Client-side JSON-RPC id correlation rejects `id_mismatch` before trusting a
response body. Sockets closed in `finally` on both sides including on
`CancelledError`; `stop()`/`__aexit__` unlink idempotently; symlinked
socket paths refused before bind. `ControlServer`/`ControlClient` take an
explicit `socket_path` rather than calling into `parrot.e2e.state.run_dir`
directly, keeping this module decoupled from state.py's directory placement
(left to the TASK-3527 caller).

Tests: `pytest packages/ai-parrot-server/tests/unit/e2e/test_control.py -q`
→ 27 passed. Full-directory regression:
`pytest packages/ai-parrot-server/tests/unit/e2e/ -q` → 226 passed
(199+27), no regression against TASK-3520/3521/3524/3525.

No unresolved limitations. AC3/AC5/AC6 demonstrated by the contract tests.
Flag for the next dependent (TASK-3527): read `control.py` directly for the
exact `ControlServer(socket_path, *, run_id, owner_id, operations,
request_deadline_s)` / `ControlHandler = Callable[[dict], Awaitable[dict]]`
signatures rather than re-deriving them.

Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: 732.2s · Tokens: 196265 (combined)
