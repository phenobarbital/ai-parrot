# TASK-3502: Own Pyright startup, requests and bounded process shutdown

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3499, TASK-3501
**Assigned-to**: unassigned

## Context

Implement M2 of the approved specification: own pyright startup, requests and bounded process shutdown. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Create PyrightSession with start/request/close contracts, version_command verification against 1.1.414, explicit cwd/root, capabilities and configuration negotiation.
- Continuously drain stdout/stderr; map request IDs to futures, handle server configuration/folder/progress requests, reject applyEdit, and disallow arbitrary methods/executeCommand.
- Enforce startup/request deadlines, Node heap option and capped stderr; surface missing/version-mismatched/crashed servers with fixed codes.
- Implement shutdown/exit then bounded terminate/kill/reap, partial-startup cleanup, pending-future cancellation and per-session ownership. Do not add unimplemented diagnostics methods.

**NOT in scope**: Document synchronization/diagnostic completeness (next task), idle toolkit policy and source snapshots.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/session.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from parrot.mcp.local_server import StdioMCPServer` — verified in `packages/ai-parrot/src/parrot/mcp/local_server.py`; use only where relevant.

### Existing Signatures to Use

- `StdioMCPServer` — `packages/ai-parrot/src/parrot/mcp/local_server.py:36`: existing MCP stdio server uses line-delimited JSON; it is not an LSP Content-Length client.
- `StdioMCPServer.start` — `packages/ai-parrot/src/parrot/mcp/local_server.py:44`: async start(self); stdin currently uses run_in_executor, so cancellation alone may leave executor shutdown waiting.
- `StdioMCPServer.stop` — `packages/ai-parrot/src/parrot/mcp/local_server.py:80`: async stop(self); sets the running flag, without owned toolkit cleanup.

### Dependency-produced contracts

- TASK-3499 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/__init__.py`, `packages/ai-parrot-tools/src/parrot_tools/lsp/models.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.
- TASK-3501 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/protocol.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

### Does NOT Exist

- The files marked CREATE are new task deliverables; do not assume their modules or exports already exist.
- Files marked MODIFY that are created by a prerequisite must be verified after that prerequisite lands.
- No existing LSP client, persistent diagnostic baseline API or five-arm pilot harness is established by the references above.
- Do not assume generic MCP transport implements LSP framing, or AST line spans provide identifier columns.
- Verify any additional symbol before use; do not invent provider adapters or methods.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/lsp/session.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer.start",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer.stop"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3499, TASK-3501 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `async def start(self, config: LSPConfig, generation: int) -> None`
- `async def request(self, method: str, params: dict[str, Any], timeout_s: float) -> Any`
- `async def close(self) -> None`

1. Compose protocol.py under one child owner and initialize using immutable configuration and a monotonically identified generation.
2. Dispatch server requests and unsolicited notifications separately from pending client requests; expose a private notification collection seam for the next task.
3. Test every startup/shutdown failure using the fake server, including blocked stderr and a child that ignores graceful exit.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Create PyrightSession with start/request/close contracts, version_command verification against 1.1.414, explicit cwd/root, capabilities and configuration negotiation.
- [ ] Continuously drain stdout/stderr; map request IDs to futures, handle server configuration/folder/progress requests, reject applyEdit, and disallow arbitrary methods/executeCommand.
- [ ] Enforce startup/request deadlines, Node heap option and capped stderr; surface missing/version-mismatched/crashed servers with fixed codes.
- [ ] Implement shutdown/exit then bounded terminate/kill/reap, partial-startup cleanup, pending-future cancellation and per-session ownership. Do not add unimplemented diagnostics methods.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py -q`

## Test Specification

- `test_server_requests_and_mutations`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_startup_timeout_and_partial_cleanup`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_request_cancel_cleans_pending_futures`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_shutdown_escalation_and_reaping`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
