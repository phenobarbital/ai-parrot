# TASK-3529: Add real toolkit HTTP and persistent stdio target adapters

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3515, TASK-3525, TASK-3528
**Assigned-to**: unassigned
**Module**: M4
**Spec acceptance criteria**: AC2, AC3, AC6

---

## Context

Implement the M4 deliverable **Add real toolkit HTTP and persistent stdio target adapters** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Implement toolkit HTTP command/config builder and matching configured-base info + initialize/list/call readiness.
- Implement mcp-local stdio builder and supervisor-mediated handshake/notification/calls; no universal HTTP endpoint assumption.
- Use isolated working-memory data and no remote model; no exact tool-count assertions.
- Prove adapter plans execute feature checkout modules and reject unrelated pre-existing service health responses.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/targets/mcp.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/tests/unit/e2e/test_mcp_targets.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/src/parrot/mcp/server.py:36` — Transport selection and ownership already exist; this wrapper is not a supervisor. Signature: `MCPServer(config: MCPServerConfig, parent_app: Optional[web.Application] = None); register_tools(tools); async start(); async stop()`. Source SHA-256: `73637e33dfd6bc014a1ef7c246bb952136ef1d06a3c5f25c173493bd6afe46af`.
- `packages/ai-parrot-server/src/parrot/mcp/cli.py:138` — HTTP start returns at line 174 and finally stops immediately; preserve the existing signature. Signature: `async def _run_standalone_server(mcp_server: ParrotMCPServer)`. Source SHA-256: `0bc626a668e2a90c74a9999abfedf308e33b17f35c04627e3d51fb355586ef2f`.
- `tests/mcp/test_mcp_local_e2e.py:72` — Legacy helpers illustrate pipes/EOF, but _recv currently uses a blocking readline despite a timeout argument; new supervisor must enforce a real deadline. Signature: `def _spawn(cwd: Path, *args: str) -> subprocess.Popen`. Source SHA-256: `4849a8cf317883d64dcc0c2f9c41b6dec4ebd7ac646d1506a48ae3606e03d1de`.

```python
from parrot.mcp.server import MCPServer
from parrot.mcp.cli import _run_standalone_server
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3515 (`sdd/tasks/active/TASK-3515-e2e-http-lifetime.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3525 (`sdd/tasks/active/TASK-3525-e2e-target-protocol.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3528 (`sdd/tasks/active/TASK-3528-e2e-watchdog.md`) must be done; consume its declared interfaces and re-read its completion evidence.

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

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
      "path": "packages/ai-parrot-server/src/parrot/e2e/targets/mcp.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_mcp_targets.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/cli.py#_run_standalone_server",
    "sym:packages/ai-parrot-server/src/parrot/mcp/server.py#MCPServer",
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
- **Parallelism:** TASK-3529 owns its declared files for M4. TASK-3515 supplies keep standalone http mcp alive until shutdown; TASK-3525 supplies define target adapter protocol and lazy fixed registry; TASK-3528 supplies enforce leases and recovery after controller/supervisor death. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Implement toolkit HTTP command/config builder and matching configured-base info + initialize/list/call readiness.
2. Implement mcp-local stdio builder and supervisor-mediated handshake/notification/calls; no universal HTTP endpoint assumption.
3. Use isolated working-memory data and no remote model; no exact tool-count assertions.
4. Prove adapter plans execute feature checkout modules and reject unrelated pre-existing service health responses.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `packages/ai-parrot-server/src/parrot/e2e/targets/mcp.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Implement toolkit HTTP command/config builder and matching configured-base info + initialize/list/call readiness.

2. Implement mcp-local stdio builder and supervisor-mediated handshake/notification/calls; no universal HTTP endpoint assumption.

3. Use isolated working-memory data and no remote model; no exact tool-count assertions.

4. Prove adapter plans execute feature checkout modules and reject unrelated pre-existing service health responses.
### `packages/ai-parrot-server/tests/unit/e2e/test_mcp_targets.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Implement toolkit HTTP command/config builder and matching configured-base info + initialize/list/call readiness.
- [ ] Implement mcp-local stdio builder and supervisor-mediated handshake/notification/calls; no universal HTTP endpoint assumption.
- [ ] Use isolated working-memory data and no remote model; no exact tool-count assertions.
- [ ] Prove adapter plans execute feature checkout modules and reject unrelated pre-existing service health responses.
- [ ] Relevant spec criteria AC2, AC3, AC6 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_mcp_targets.py -q`

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

Completed 2026-09-19. Implemented `build_mcp_toolkit_adapter()` (`mcp-toolkit`:
launches the real `parrot mcp serve <private-yaml> --transport http --port
<port>` exposing `WorkingMemoryToolkit`; `ready()` polls `GET
<base_url>/mcp/info` — real route is `/mcp/info` not `/info`, a genuine
`parrot.mcp.cli`/`MCPServerConfig` `base_path="/mcp"` default discovered
and verified independently of this adapter's own code — rejects any
mismatched server name, then does a live `initialize`/`tools/list` JSON-RPC
round trip) and `build_mcp_stdio_adapter()` (`mcp-stdio`: launches
`parrot mcp-local memory --config <private-yaml>`; `ready()` is always
True by design since `E2ESupervisor._await_ready` never calls it for a
stdio launch — protocol handshake proven via the supervisor's own
`request_stdio()`). Both write private per-run config YAML under
`e2e_state.run_dir()` (mode-0700). `build_mcp_agent_adapter` intentionally
NOT implemented here — confirmed owned by TASK-3540 (M6, live-agent scope).

Two documented environment findings (not worked around by weakening any
assertion): (1) `parrot.mcp.cli`/navconfig bootstrap causes an HTTP-transport
child to self-exit within ~1-2s when `cwd` isn't a real on-disk project
checkout root — isolated to exactly one real-subprocess test using this
worktree's own root with full artifact cleanup in `finally`; the `mcp-stdio`
path is unaffected (no HTTP transport) and stays on `tmp_path`. (2) importing
`parrot.tools` transitively triggers `uvloop.install()`, silently replacing
the caller's event loop policy — an in-process toolkit-importability
precheck that hit this was removed; importability is now proven only by the
child actually starting in its own isolated process.

Sibling-merge integration fallout (flagged by this task, fixed by the
orchestrator in a separate commit, not a defect here): TASK-3525's
`test_get_target_adapter_raises_prerequisite_error_for_unimplemented_kind`
asserted all six kinds were unimplemented; narrowed to the four kinds still
genuinely unimplemented (mcp-agent, botmanager, ui, browser) since
mcp-toolkit/mcp-stdio now resolve for real. See commit 9f4e3eb08.

Tests: `pytest packages/ai-parrot-server/tests/unit/e2e/test_mcp_targets.py -q`
→ 24 passed. Full-directory regression (after the sibling-test fix):
`pytest packages/ai-parrot-server/tests/unit/e2e/ -q` → 278 passed
(254+24), no regression against TASK-3524/3525/3526/3527/3528.

No unresolved limitations beyond the two documented environment findings.
AC2/AC3/AC6 demonstrated by the contract tests.

Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: 2528.7s · Tokens: 419326 (combined)
