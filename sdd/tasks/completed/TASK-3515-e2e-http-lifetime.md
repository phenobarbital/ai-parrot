# TASK-3515: Keep standalone HTTP MCP alive until shutdown

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Module**: M1
**Spec acceptance criteria**: AC1, AC17

---

## Context

Implement the M1 deliverable **Keep standalone HTTP MCP alive until shutdown** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Add HTTP-only keep-alive after start returns; install and restore SIGINT/SIGTERM handling with cleanup in finally.
- Keep stdio/Unix blocking behavior and CLI argument shapes; stop exactly once on success, error and cancellation.
- Use real subprocess requests separated in time and a bounded signal teardown regression; unit tests may replace only lifecycle collaborators.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/cli.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-server/tests/mcp/test_cli_lifetime.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/src/parrot/mcp/cli.py:138` — HTTP start returns at line 174 and finally stops immediately; preserve the existing signature. Signature: `async def _run_standalone_server(mcp_server: ParrotMCPServer)`. Source SHA-256: `0bc626a668e2a90c74a9999abfedf308e33b17f35c04627e3d51fb355586ef2f`.
- `packages/ai-parrot-server/src/parrot/mcp/server.py:36` — Transport selection and ownership already exist; this wrapper is not a supervisor. Signature: `MCPServer(config: MCPServerConfig, parent_app: Optional[web.Application] = None); register_tools(tools); async start(); async stop()`. Source SHA-256: `73637e33dfd6bc014a1ef7c246bb952136ef1d06a3c5f25c173493bd6afe46af`.

```python
from parrot.mcp.cli import _run_standalone_server
from parrot.mcp.server import MCPServer
```

### Dependency Interfaces (new, not existing)

None.

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### Modify-Target Freshness

- `packages/ai-parrot-server/src/parrot/mcp/cli.py` current SHA-256: `0bc626a668e2a90c74a9999abfedf308e33b17f35c04627e3d51fb355586ef2f`; re-read at execution because other features may change it.

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
      "path": "packages/ai-parrot-server/src/parrot/mcp/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/mcp/test_cli_lifetime.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/cli.py#_run_standalone_server",
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
- **Parallelism:** TASK-3515 owns its declared files for M1. No task dependencies; uses verified existing contracts only. Exclusive prerequisite/shared-orchestration edit; do not co-schedule.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Add HTTP-only keep-alive after start returns; install and restore SIGINT/SIGTERM handling with cleanup in finally.
2. Keep stdio/Unix blocking behavior and CLI argument shapes; stop exactly once on success, error and cancellation.
3. Use real subprocess requests separated in time and a bounded signal teardown regression; unit tests may replace only lifecycle collaborators.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `packages/ai-parrot-server/src/parrot/mcp/cli.py` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Add HTTP-only keep-alive after start returns; install and restore SIGINT/SIGTERM handling with cleanup in finally.

2. Keep stdio/Unix blocking behavior and CLI argument shapes; stop exactly once on success, error and cancellation.

3. Use real subprocess requests separated in time and a bounded signal teardown regression; unit tests may replace only lifecycle collaborators.
### `packages/ai-parrot-server/tests/mcp/test_cli_lifetime.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Add HTTP-only keep-alive after start returns; install and restore SIGINT/SIGTERM handling with cleanup in finally.
- [ ] Keep stdio/Unix blocking behavior and CLI argument shapes; stop exactly once on success, error and cancellation.
- [ ] Use real subprocess requests separated in time and a bounded signal teardown regression; unit tests may replace only lifecycle collaborators.
- [ ] Relevant spec criteria AC1, AC17 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/mcp/test_cli_lifetime.py -q`

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

Completed 2026-09-19. Added an HTTP-only keep-alive to
`_run_standalone_server` in `packages/ai-parrot-server/src/parrot/mcp/cli.py`:
a new `_wait_for_shutdown_signal(logger)` helper installs SIGINT/SIGTERM
handlers and awaits an `asyncio.Event`, invoked only when
`transport_config.transport == "http"` (HttpMCPServer.start() returns
immediately after binding the socket; stdio/unix already block internally
in their own `start()`, so no change was needed there). The pre-existing
`finally: await server.stop()` guarantees single-stop on success, error and
cancellation.

Tests: `packages/ai-parrot-server/tests/mcp/test_cli_lifetime.py` (new, 10
tests) — 9 unit tests faking only lifecycle collaborators plus 1 real
process-boundary acceptance test that spawns `parrot mcp serve --transport
http` as a genuine subprocess, makes two time-separated real HTTP requests,
sends a real SIGTERM, and asserts bounded teardown + socket release.
`PYTHONPATH="packages/ai-parrot/src:packages/ai-parrot-server/src" pytest
packages/ai-parrot-server/tests/mcp/test_cli_lifetime.py -q` → 10 passed.

Observation: the feature-level `select_tests --tier merge` invocation (run
across all 34 task files per the orchestrator protocol) errored on 4
groups because it also picks up Validation Commands declared by *pending*
sibling tasks (TASK-3536, TASK-3539, TASK-3542, TASK-3545) whose target
test files don't exist yet at 1/34 tasks complete — not a regression from
this merge. This is expected to resolve naturally as those tasks land;
flagged here for visibility rather than filed as a defect.

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 ·
Duration: 562.76s · Tokens: 157809 (subagent, in+out combined; native
usage_known=false in engine seats roll-up).
