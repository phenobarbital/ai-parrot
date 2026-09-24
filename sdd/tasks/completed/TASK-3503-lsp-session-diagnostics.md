# TASK-3503: Synchronize saved documents and collect versioned diagnostics

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3502
**Assigned-to**: unassigned

## Context

Implement M2 of the approved specification: synchronize saved documents and collect versioned diagnostics. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Extend the existing PyrightSession with exact on-disk open/change/close synchronization, monotonic versions and maximum 20 open documents.
- Collect push diagnostics only for matching current generation/URI/version; a matching empty publication clears prior findings.
- Return DiagnosticBatch with explicit missing/unversioned coverage at deadline, enforcing 2,000 raw diagnostic cap; never infer completeness from silence, timers or other response types.
- Allow warm reuse only of complete publications for unchanged source states; preserve uncropped messages for later multiset comparisons.

**NOT in scope**: Agent methods, persistent baselines, filesystem writes and whole-workspace clean assertions.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/session.py` | MODIFY | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_session_diagnostics.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from parrot.mcp.local_server import StdioMCPServer` — verified in `packages/ai-parrot/src/parrot/mcp/local_server.py`; use only where relevant.

### Existing Signatures to Use

- `StdioMCPServer` — `packages/ai-parrot/src/parrot/mcp/local_server.py:36`: existing MCP stdio server uses line-delimited JSON; it is not an LSP Content-Length client.
- `StdioMCPServer.start` — `packages/ai-parrot/src/parrot/mcp/local_server.py:44`: async start(self); stdin currently uses run_in_executor, so cancellation alone may leave executor shutdown waiting.
- `StdioMCPServer.stop` — `packages/ai-parrot/src/parrot/mcp/local_server.py:80`: async stop(self); sets the running flag, without owned toolkit cleanup.

### Dependency-produced contracts

- TASK-3502 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/session.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

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
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_session_diagnostics.py",
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
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3502 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `async def sync_documents(self, sources: list[SourceState], texts: dict[str, str]) -> None`
- `async def diagnostics(self, sources: list[SourceState], timeout_s: float) -> DiagnosticBatch`

1. Read the session implementation produced by the prerequisite and reverify its private notification seam before editing.
2. Track document lifetimes and versions; retire closed or stale generation state and route versioned publications to waiting checkpoints.
3. Exercise old/new/interleaved/empty/missing/unversioned notifications using the fake server, keeping lifecycle cleanup behavior unchanged.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Extend the existing PyrightSession with exact on-disk open/change/close synchronization, monotonic versions and maximum 20 open documents.
- [ ] Collect push diagnostics only for matching current generation/URI/version; a matching empty publication clears prior findings.
- [ ] Return DiagnosticBatch with explicit missing/unversioned coverage at deadline, enforcing 2,000 raw diagnostic cap; never infer completeness from silence, timers or other response types.
- [ ] Allow warm reuse only of complete publications for unchanged source states; preserve uncropped messages for later multiset comparisons.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_session_diagnostics.py -q`

## Test Specification

- `test_document_open_change_close_versions`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_diagnostic_freshness`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_matching_empty_publication_clears_diagnostics`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_unversioned_missing_and_overflow_are_incomplete`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Added `PyrightSession.sync_documents(sources, texts)`: opens (`didOpen`)/changes (`didChange`)/closes (`didClose`)
exact on-disk documents. Enforces strictly monotonic `document_version`, rejects a repeated version whose hash
changed, treats a repeated `(version, sha256)` as a no-op (preserving warm diagnostic cache), closes any open
document not in the current `sources` set, rejects more than 20 distinct paths with `resource_limit`.

Added `PyrightSession.diagnostics(sources, timeout_s)`: drains TASK-3502's private notification seam
(`_drain_notifications`) via an `asyncio.Event` hooked into `_dispatch_message`; accepts only
`textDocument/publishDiagnostics` publications whose version matches the path's currently-open document
version; version-omitted publication → `unversioned_paths` (never matched); enforces the 2,000 raw-diagnostic
cap by demoting whole oversized-contribution paths to `missing_paths` rather than truncating in place; returns
a `DiagnosticBatch` that is `complete` only when every requested path matched — never raises on timeout, never
infers completeness from silence. Warm reuse via a per-path version-keyed cache resolves an unchanged source
state instantly. A matching version's diagnostics (even empty) replace the prior cache entry, so a matching
empty publication clears earlier findings. `RawDiagnostic.full_message` is never truncated (uncropped, for
M3's multiset comparisons).

**Test design note:** `fake_server.py`'s `happy_path` scenario always publishes a hardcoded diagnostic for
`file:///scenario.py`, which never resolves inside a pytest `tmp_path` root, so it can only exercise "foreign
notification is ignored." Used real subprocesses against `happy_path` for lifecycle/liveness (as TASK-3502
did), and fed synthetic `ParsedMessage` notifications through the session's private `_dispatch_message` seam to
exercise freshness/matching/overflow — the same private-seam-testing convention TASK-3502 established. Applied
the TASK-3502 implementer's fixture-race note: every test waits for `len(session._notifications) >= 2` after
`start()` before writing anything else to stdin.

Validation: `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest
packages/ai-parrot-tools/tests/lsp/test_session_diagnostics.py -q` → 14 passed. Full `packages/ai-parrot-tools/tests/lsp/`
→ 77 passed, no regression. `ruff check` clean; `black --check` flagged only the new test file's line-wrapping
(not session.py); reformatted and re-verified 14/14 still green.

Post-merge regression (`select_tests --tier merge`): 98 passed (`dev_loop/sdd_coder` + `packages/ai-parrot/tests/mcp`),
107 passed/1 deselected (`packages/ai-parrot-tools/tests/lsp` + `tool_optimizations/integration`), 15 passed
(`tests/mcp/test_toolkit_server.py`).

Coder-feedback patterns checked: hasattr-duck-typing — not applicable (version/type discrimination uses
explicit `isinstance`/`is None` checks ordered by definitiveness). unisolated-real-home-in-tests — not
applicable (all tests use `tmp_path` exclusively; URI construction independently re-derived in tests rather
than reusing the session's own encoder, to avoid a self-validating test). unscoped-removal-reuses-full-uninstall-helper
— not applicable (`_close_document` is a new, narrowly-scoped helper).

No code review deferred findings for this delivery; no defects found. No correction feedback filed.

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a (not reported by native
Agent dispatch) · Tokens: 202439 (subagent_tokens, per completion notification).
